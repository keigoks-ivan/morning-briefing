"""
evidence_sources.py
-------------------
一手來源查核（2026-09-22）：官方 RSS／JSON、官方網域的 Google News site: 查詢、
當事公司自己發的新聞稿（Business Wire／GlobeNewswire／PR Newswire）、證交所／櫃買中心重大訊息。
清單在 data/evidence_routing.json 的 official_sources。

規則：
- 每次執行每個來源只抓一次（並行），逐來源記錄 ok／empty／error；抓不到就列為當天缺口，
  不當成「官方沒有公告」。
- 比對到候選新聞分兩級：
  matched＝同主體、日期在窗內、而且數字或用字對得上 → 證據基礎升級為「官方文件已對到」；
  nearby＝只是同主體、日期接近（例如同公司當天的重大訊息）→ 只列出來，不宣稱對上。
- 不需要任何金鑰；不帶聯絡資料的 User-Agent。SEC EDGAR 另走 evidence_routing.sec_check。
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from evidence_ledger import content_tokens, extract_figures, figure_label

UA = "Mozilla/5.0 (compatible; morning-briefing research bot)"
GN_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
MATCH_WINDOW_DAYS = 4
_TAG_RE = re.compile(r"<[^>]+>")


def http_text(url: str, timeout: int = 15) -> tuple[str | None, str]:
    """回 (內容, 狀態)。狀態：ok／error:<原因>。"""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code >= 400:
            return None, f"error:HTTP {r.status_code}"
        # 用位元組自己解碼：Fed 的 feed 開頭有 BOM，requests 猜編碼會變亂碼
        return r.content.decode("utf-8-sig", errors="replace"), "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


def _clean(text: str, limit: int = 300) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _to_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    return m.group(1) if m else ""


def parse_feed(text: str) -> list[dict]:
    """RSS／Atom → [{title, link, date, summary, outlet}]。不依賴 feedparser。"""
    items = []
    if isinstance(text, str):
        text = text.lstrip("\ufeff").lstrip("ï»¿").lstrip()
    try:
        root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    except ET.ParseError:
        return items
    for el in root.iter():
        el.tag = el.tag.split("}", 1)[-1]   # 去掉 namespace
    for node in list(root.iter("item")) + list(root.iter("entry")):
        def get(tag):
            child = node.find(tag)
            return (child.text or "") if child is not None and child.text else ""
        link = get("link")
        if not link:
            le = node.find("link")
            link = le.get("href", "") if le is not None else ""
        outlet = ""
        src = node.find("source")
        if src is not None and src.text:
            outlet = src.text.strip()
        title = _clean(get("title"), 240)
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3].strip()
        items.append({
            "title": title,
            "link": link.strip(),
            "date": _to_date(get("pubDate") or get("published") or get("updated") or get("date")),
            "summary": _clean(get("description") or get("summary") or get("content"), 300),
            "outlet": outlet,
        })
    return items


def _roc_to_iso(value: str) -> str:
    value = re.sub(r"\D", "", str(value or ""))
    if len(value) == 7:
        try:
            return date(int(value[:3]) + 1911, int(value[3:5]), int(value[5:7])).isoformat()
        except ValueError:
            return ""
    return ""


def parse_twse(text: str) -> list[dict]:
    """證交所／櫃買中心每日重大訊息 JSON（中文欄位）。"""
    try:
        rows = json.loads(text)
    except ValueError:
        return []
    out = []
    for r in rows if isinstance(rows, list) else []:
        r = {str(k).strip(): v for k, v in r.items()}
        code = str(r.get("公司代號") or r.get("SecuritiesCompanyCode") or "").strip()
        subject = _clean(str(r.get("主旨") or r.get("Subject") or ""), 200)
        if not code or not subject:
            continue
        out.append({
            "title": subject, "link": "https://mops.twse.com.tw/mops/web/t05sr01_1",
            # 用發言日期（公告日）；事實發生日可能是未來的預定日
            "date": _roc_to_iso(r.get("發言日期") or "") or _roc_to_iso(r.get("出表日期") or ""),
            "fact_date": _roc_to_iso(r.get("事實發生日") or ""),
            "summary": _clean(str(r.get("說明") or ""), 300), "outlet": "", "company_code": code,
            "company_name": str(r.get("公司名稱") or "").strip(),
        })
    return out


class OfficialSources:
    def __init__(self, config: dict, fetch_text=http_text, today: str | None = None):
        self.config = {k: v for k, v in (config or {}).items() if not k.startswith("_")}
        self.fetch_text = fetch_text
        self.today = today or datetime.now(timezone.utc).date().isoformat()
        self.items: dict[str, list[dict]] = {}
        self.status: dict[str, dict] = {}

    def _url(self, spec: dict, query: str | None = None) -> str:
        if spec.get("kind") in ("gn", "company_wires"):
            q = f"{query or spec['query']} when:{spec.get('days', 5)}d"
            return GN_URL.format(q=urllib.parse.quote_plus(q))
        return spec["url"]

    def _load(self, sid: str, spec: dict, url: str) -> tuple[str, list[dict], dict]:
        text, status = self.fetch_text(url)
        if text is None:
            return sid, [], {"status": "error", "error": status.split(":", 1)[-1], "label": spec.get("label", sid)}
        items = parse_twse(text) if spec.get("kind") == "twse_json" else parse_feed(text)
        return sid, items, {"status": "ok" if items else "empty", "items": len(items), "label": spec.get("label", sid)}

    def prefetch(self) -> None:
        jobs = [(sid, spec, self._url(spec)) for sid, spec in self.config.items() if spec.get("kind") != "company_wires"]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for sid, items, st in ex.map(lambda j: self._load(*j), jobs):
                self.items[sid], self.status[sid] = items, st

    def fetch_company_wires(self, names: dict) -> None:
        """names: {company_key: 公司名}。每家查一次當事公司的新聞稿。"""
        spec = self.config.get("company_wires")
        if not spec:
            return
        todo = [(k, n) for k, n in names.items() if n and f"company_wires:{k}" not in self.status][: spec.get("max_companies", 12)]
        jobs = [(f"company_wires:{k}", {**spec, "label": f"{n} press releases (wire services)"},
                 self._url(spec, spec["query"].replace("{name}", n))) for k, n in todo]
        with ThreadPoolExecutor(max_workers=8) as ex:
            for sid, items, st in ex.map(lambda j: self._load(*j), jobs):
                # 只收「這家公司自己發的」：標題開頭 40 字內就是公司名（別家新聞稿順帶提到的不算一手）
                name = dict(todo).get(sid.split(":", 1)[1], "").casefold()
                own = [it for it in items if name and name in it["title"].casefold()[:40]]
                st = {**st, "items": len(own), "status": "ok" if own else ("empty" if st["status"] != "error" else "error")}
                self.items[sid], self.status[sid] = own, st

    def relevant(self, entity_keys: set, tw_codes: set) -> list[str]:
        out = []
        for sid, spec in self.config.items():
            covers = set(spec.get("covers") or [])
            if covers & entity_keys or ("*TW" in covers and tw_codes) or ("*TWO" in covers and tw_codes):
                out.append(sid)
        out += [sid for sid in self.status if sid.startswith("company_wires:") and sid.split(":", 1)[1] in entity_keys]
        return out

    def match(self, cand: dict, entity_keys: set, names: list[str], tw_codes: set, today: str) -> dict:
        """cand 需要 text／tokens／figures／event_date。"""
        try:
            lo = (datetime.strptime((cand.get("event_date") or today)[:10], "%Y-%m-%d")
                  - timedelta(days=MATCH_WINDOW_DAYS)).date().isoformat()
        except ValueError:
            lo = today
        names_l = [n.casefold() for n in names if n and len(n) >= 3]
        figs = set(cand.get("figures") or [])
        toks = set(cand.get("tokens") or [])
        result = {"matched": [], "nearby": [], "checked": [], "failed": []}
        for sid in self.relevant(entity_keys, tw_codes):
            st = self.status.get(sid) or {"status": "error", "error": "not fetched", "label": sid}
            label = st.get("label") or (self.config.get(sid) or {}).get("label", sid)
            if st["status"] == "error":
                result["failed"].append({"source": label, "reason": st.get("error", "")})
                continue
            result["checked"].append({"source": label, "status": st["status"], "items": st.get("items", 0)})
            for it in self.items.get(sid) or []:
                d = it.get("date") or ""
                if not d or not (lo <= d <= today):
                    continue
                if it.get("company_code"):
                    if it["company_code"] not in tw_codes:
                        continue
                    shared = figs & set(extract_figures(it["title"] + " " + it["summary"]))
                    entry = {"source": label, "title": it["title"], "url": it["link"], "date": d,
                             "why": ("shared figure " + ", ".join(figure_label(f) for f in shared)) if shared
                             else "same company filing near the date"}
                    (result["matched"] if shared else result["nearby"]).append(entry)
                    continue
                text = f"{it['title']} {it['summary']}"
                it_toks = content_tokens(text)
                union = toks | it_toks
                jac = len(toks & it_toks) / len(union) if union else 0.0
                shared = figs & set(extract_figures(text))
                name_hit = any(n in text.casefold() for n in names_l)
                matched = (shared and (jac >= 0.05 or name_hit)) or (jac >= 0.22 and name_hit) or jac >= 0.35
                if not matched and not name_hit:
                    continue
                why = ("shared figure " + ", ".join(figure_label(f) for f in shared)) if shared else (
                    "same wording" if matched else "same company or institution, content not matched")
                entry = {"source": label, "title": it["title"], "url": it["link"], "date": d, "why": why}
                (result["matched"] if matched else result["nearby"]).append(entry)
        result["matched"] = result["matched"][:3]
        result["nearby"] = result["nearby"][:3]
        return result

    def summary(self) -> dict:
        ok = [s for s, st in self.status.items() if st["status"] == "ok"]
        empty = [s for s, st in self.status.items() if st["status"] == "empty"]
        failed = {s: st.get("error", "") for s, st in self.status.items() if st["status"] == "error"}
        return {"total": len(self.status), "ok": len(ok), "empty": sorted(empty), "failed": failed}
