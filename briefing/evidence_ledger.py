"""
evidence_ledger.py
------------------
跨日事件／事實紀錄（evidence ledger）。

一筆紀錄＝一個「事實」，不是一篇文章：同一件事被不同媒體、不同天重述，會更新同一筆的
last_seen／seen_dates，而不是新增一筆。新舊判斷的單位是「事實增量」：
- 程式負責：公司辨識（對照表別名）、數字正規化（30 million＝30M＝3000萬）、日期、
  找先前紀錄（同公司＋同數字／同關鍵詞）、冪等寫入。
- Jev 負責：在程式挑出的先前紀錄旁邊，判斷今天這則是新事實、進度更新還是重述。

存放：docs/briefing/data/evidence_ledger.json（隨早報發布到網站，隔天抓回來）。
一筆一行，排序穩定，讓每天的 git diff 只有新增與更新的那幾行。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta

LEDGER_SCHEMA = "evidence-ledger-v1"
LEDGER_WINDOW_DAYS = 180   # 超過就修剪；origin=seed 的人工種子不修剪
PRIOR_MAX = 3              # 每則最多帶幾筆先前紀錄給 Jev

# ── 數字正規化 ───────────────────────────────────────────────────────────
_SCALE = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "tn": 1e12, "trillion": 1e12,
    "萬": 1e4, "万": 1e4, "億": 1e8, "亿": 1e8, "兆": 1e12,
}
_FIG_RE = re.compile(
    r"(?<![A-Za-z0-9_.])\$?\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?"  # 前面可以是中文字（「突破3000萬」）
    r"(%|x\b|times\b|gw\b|mw\b|trillion|billion|million|thousand|bn\b|mn\b|tn\b|[kmbt]\b|萬|万|億|亿|兆)",
    re.I,
)


def _sig(value: float) -> str:
    """三位有效數字，讓 34.12B 與 34.1B 視為同一個數。"""
    if value == 0:
        return "0"
    return f"{value:.3g}"


def extract_figures(text: str) -> list[str]:
    """抽出帶單位的數字並正規化：金額／數量 → 'n:3e+07'，百分比 → 'pct:6.75'，倍數 → 'x:4'。
    年份、日期、沒有單位的裸數字一律不收（太容易誤配）。"""
    out = []
    for m in _FIG_RE.finditer(text or ""):
        raw, unit = m.group(1).replace(",", ""), m.group(2).lower()
        try:
            num = float(raw)
        except ValueError:
            continue
        if unit == "%":
            key = f"pct:{_sig(num)}"
        elif unit in ("x", "times"):
            key = f"x:{_sig(num)}"
        elif unit in ("gw", "mw"):
            key = f"gw:{_sig(num / 1000 if unit == 'mw' else num)}"
        else:
            key = f"n:{_sig(num * _SCALE.get(unit, 1))}"
        if key not in out:
            out.append(key)
    return out


def figure_label(key: str) -> str:
    kind, val = key.split(":", 1)
    v = float(val)
    if kind == "pct":
        return f"{v:g}%"
    if kind == "x":
        return f"{v:g}x"
    if kind == "gw":
        return f"{v:g} GW"
    for unit, scale in (("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3)):
        if v >= scale:
            return f"{v / scale:g} {unit}"
    return f"{v:g}"


# ── 公司與關鍵詞 ─────────────────────────────────────────────────────────
def _alias_regex(alias: str, case_sensitive: bool | None = None) -> re.Pattern:
    """case_sensitive=None：全大寫短代號（AMD、KLA）區分大小寫，其他不分；True／False 強制。"""
    if re.fullmatch(r"[A-Za-z0-9 .&'’\-+]+", alias):
        if case_sensitive is None:
            case_sensitive = alias.isupper() and len(alias) <= 5
        return re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", 0 if case_sensitive else re.I)
    return re.compile(re.escape(alias))


def _cased(alias: str) -> bool:
    """總經主題／國家／自動公司名：有大寫字母就區分大小寫（Fed ≠ fed、Visa ≠ visa），全小寫片語不分。"""
    return any(ch.isupper() for ch in alias)


class EntityMatcher:
    """公司別名 → 對照表 key。公司清單由程式（對照表＋DD universe）提供，Jev 不自由生成公司名。"""

    def __init__(self, routing: dict, extra_tickers: dict | None = None):
        self.companies = {k: v for k, v in (routing.get("companies") or {}).items() if not k.startswith("_")}
        self.patterns: list[tuple[str, re.Pattern]] = []
        self.auto_names: dict = {}
        for key, spec in self.companies.items():
            if spec.get("same_as"):
                continue
            for alias in spec.get("aliases") or []:
                if len(alias) >= 2:
                    self.patterns.append((key, _alias_regex(alias)))
        # 2026-09-22：研究主題角色欄抽出的公司名（evidence_routing_auto.json），區分大小寫
        hand_alias = {a.casefold(): k for k, spec in self.companies.items() if not spec.get("same_as")
                      for a in spec.get("aliases") or []}
        for ticker, spec in (routing.get("auto_companies") or {}).items():
            key = self.canonical(ticker) if ticker in self.companies else ticker
            dup = [hand_alias[a.casefold()] for a in spec.get("aliases") or [] if a.casefold() in hand_alias]
            if dup and key not in self.companies:
                continue   # 同一家公司人工表已經有（例：OpenAI），不再另立一個 key
            aliases = [a for a in spec.get("aliases") or [] if len(a) >= 3 or re.search(r"[\u4e00-\u9fff]", a)]
            for alias in aliases:
                self.patterns.append((key, _alias_regex(alias, case_sensitive=_cased(alias))))
            if key not in self.companies and aliases:
                en = [a for a in aliases if not re.search(r"[\u4e00-\u9fff]", a)]
                self.auto_names[key] = (en or aliases)[-1]
        # 總經主題與國家
        self.subject_specs = {k: v for k, v in (routing.get("macro_subjects") or {}).items() if not k.startswith("_")}
        self.subject_patterns = [(k, _alias_regex(a, case_sensitive=_cased(a)))
                                 for k, spec in self.subject_specs.items() for a in spec.get("aliases") or []]
        self.country_patterns = [(c, _alias_regex(a, case_sensitive=_cased(a)))
                                 for c, aliases in (routing.get("countries") or {}).items() if not c.startswith("_")
                                 for a in aliases]
        # DD universe 裡對照表沒有的公司：用 ticker（全大寫）＋公司全名比對
        for ticker, name in (extra_tickers or {}).items():
            if ticker in self.companies:
                continue
            base = ticker.split(".")[0]
            if base.isalpha() and len(base) >= 3:
                self.patterns.append((ticker, re.compile(r"(?<![A-Za-z0-9])" + re.escape(base) + r"(?![A-Za-z0-9])")))
            if name and len(name) >= 4 and name.upper() != ticker.upper():
                clean = re.sub(r",?\s+(Inc\.?|Corp\.?|Corporation|plc|Ltd\.?|Holdings?|Co\.?|N\.V\.|S\.A\.)$", "", name, flags=re.I)
                if len(clean) >= 4:
                    self.patterns.append((ticker, _alias_regex(clean)))
        self.term_aliases = {k: v for k, v in (routing.get("term_aliases") or {}).items() if not k.startswith("_")}

    def canonical(self, key: str) -> str:
        spec = self.companies.get(key) or {}
        return spec.get("same_as") or key

    def name(self, key: str) -> str:
        spec = self.companies.get(key) or {}
        return spec.get("name") or self.auto_names.get(key) or key

    def country(self, text: str) -> str | None:
        """最早出現的國家；都沒有回 None。"""
        best = None
        for c, pat in self.country_patterns:
            m = pat.search(text or "")
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), c)
        return best[1] if best else None

    def country_near(self, text: str, pos: int) -> str | None:
        """離 pos 最近的國家（同一句裡「中國 CPI、美國零售銷售」要各自對到自己的國家）。"""
        best = None
        for c, pat in self.country_patterns:
            for m in pat.finditer(text or ""):
                d = abs(m.start() - pos)
                if best is None or d < best[0]:
                    best = (d, c)
        return best[1] if best else None

    def subjects(self, text: str) -> list[str]:
        """總經主題 key；scoped 的加國別（CPI@US），沒寫國家就當美國。"""
        found = []
        for key, pat in self.subject_patterns:
            m = pat.search(text or "")
            if not m:
                continue
            spec = self.subject_specs[key]
            k = f"{key}@{self.country_near(text, m.start()) or 'US'}" if spec.get("scoped") else key
            if k not in found:
                found.append(k)
        return found

    def subject_label(self, key: str) -> str:
        base, _, country = key.partition("@")
        label = (self.subject_specs.get(base) or {}).get("label", base)
        return f"{label} ({country})" if country else label

    def match(self, text: str) -> list[str]:
        found = []
        for key, pat in self.patterns:
            key = self.canonical(key)
            if key not in found and pat.search(text or ""):
                found.append(key)
        return found

    def terms(self, text: str) -> list[str]:
        folded = (text or "").casefold()
        return [k for k, aliases in self.term_aliases.items()
                if any(a.casefold() in folded for a in aliases)]


_WORD_RE = re.compile(r"[a-z][a-z0-9\-]{3,}")
_STOP = {"that", "this", "with", "from", "have", "been", "will", "said", "says", "than", "into",
         "over", "after", "about", "also", "more", "most", "year", "years", "week", "month",
         "quarter", "first", "record", "billion", "million", "percent", "company", "companies"}


def content_tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").casefold()) if w not in _STOP}


# ── 日期 ────────────────────────────────────────────────────────────────
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
_MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
                "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
_DATE_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?(?:,?\s+(20\d\d))?\b",
    re.I,
)


def extract_event_date(text: str, ref: str) -> dict:
    """文字裡明寫的事件日期（程式算，不問 Jev）。區間（September 1-20）回期末＋區間標籤。
    沒寫就回空，呼叫端用發布日期，並標 date_basis=published。"""
    try:
        ref_d = datetime.strptime(ref[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {}
    for m in _DATE_RE.finditer(text or ""):
        month = _MONTHS[m.group(1).lower().rstrip(".")]
        year = int(m.group(4)) if m.group(4) else ref_d.year
        try:
            start = date(year, month, int(m.group(2)))
            end = date(year, month, int(m.group(3))) if m.group(3) else start
        except ValueError:
            continue
        if not m.group(4) and end > ref_d + timedelta(days=2):
            # 沒寫年份又落在未來：多半是去年同月，或是預告日期；兩者都不當事件日
            continue
        out = {"event_date": end.isoformat(), "date_basis": "stated"}
        if end != start:
            out["period"] = f"{start.isoformat()}..{end.isoformat()}"
        return out
    return {}


# ── 紀錄 ────────────────────────────────────────────────────────────────
def fact_key(companies: list[str], figures: list[str], terms: list[str], headline: str) -> str:
    """事實鍵：公司＋數字＋關鍵詞＋標題實詞，不含日期與 URL（同一事實跨日要撞在一起）。"""
    toks = sorted(content_tokens(headline))[:8]
    cjk = "".join(re.findall(r"[一-鿿]", headline or ""))[:40]  # 中文標題也要進鍵，否則全撞在一起
    raw = "|".join([",".join(sorted(companies)), ",".join(sorted(figures)),
                    ",".join(sorted(terms)), ",".join(toks), cjk])
    return "fact_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def _days_between(a: str, b: str) -> int | None:
    try:
        return (datetime.strptime(a[:10], "%Y-%m-%d") - datetime.strptime(b[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


class Ledger:
    def __init__(self, records: list[dict] | None = None, available: bool = True, origin_note: str = ""):
        self.records: list[dict] = [r for r in (records or []) if isinstance(r, dict) and r.get("fact_key")]
        self.available = available        # False＝今天抓不到昨天的紀錄 → 不得宣稱「新」
        self.origin_note = origin_note

    @classmethod
    def from_json(cls, payload, available: bool = True, origin_note: str = "") -> "Ledger":
        if isinstance(payload, dict):
            return cls(payload.get("facts") or [], available, origin_note)
        if isinstance(payload, list):
            return cls(payload, available, origin_note)
        return cls([], False, origin_note or "unreadable ledger")

    def merge(self, other_records: list[dict]) -> None:
        """種子／回填紀錄併入；同 fact_key 以既有的為準。"""
        have = {r["fact_key"] for r in self.records}
        for r in other_records or []:
            if isinstance(r, dict) and r.get("fact_key") and r["fact_key"] not in have:
                self.records.append(r)
                have.add(r["fact_key"])

    def _idf(self) -> dict:
        """關鍵詞與數字的稀有度（越少紀錄出現，權重越高）：白埔比 CoWoS 更能指認同一件事。"""
        n = len(self.records)
        if getattr(self, "_idf_cache", (None,))[0] == n:
            return self._idf_cache[1]
        df: dict = {}
        for r in self.records:
            for x in set(r.get("terms") or []) | set(r.get("figures") or []):
                df[x] = df.get(x, 0) + 1
        idf = {x: math.log((n + 1) / (c + 1)) + 1.0 for x, c in df.items()}
        self._idf_cache = (n, idf)
        return idf

    def find_prior(self, companies: list[str], figures: list[str], terms: list[str],
                   tokens: set[str], today: str, limit: int = PRIOR_MAX,
                   key_figures: list[str] | None = None) -> list[dict]:
        """今天以前、同公司、且共享數字／關鍵詞／足夠多實詞的紀錄，依相關度排序。
        first_seen == today 的紀錄是今天自己寫的（同日重跑），絕不當成「先前已知」。
        只保留分數達最高分 65% 的紀錄，避免只沾到公司名的舊聞混進「上次已知」。"""
        comp = set(companies)
        idf = self._idf()
        scored = []
        for r in self.records:
            if (r.get("first_seen") or "") >= today:
                continue
            age = _days_between(today, r.get("first_seen") or "")
            if age is None or (age > LEDGER_WINDOW_DAYS and r.get("origin") != "seed"):
                continue
            shared_c = comp & (set(r.get("companies") or []) | set(r.get("subjects") or []))
            if not shared_c:
                continue
            shared_f = set(figures) & set(r.get("figures") or [])
            shared_t = set(terms) & set(r.get("terms") or [])
            r_tokens = set(r.get("tokens") or [])
            jac = len(tokens & r_tokens) / len(tokens | r_tokens) if (tokens and r_tokens) else 0.0
            if not (shared_f or shared_t or jac >= 0.2):
                continue
            score = (1.5 * sum(idf.get(f, 1.0) for f in shared_f) + sum(idf.get(t, 1.0) for t in shared_t)
                     + 4 * jac + 0.5 * len(shared_c))
            scored.append((score, r.get("first_seen") or "", r, sorted(shared_f), sorted(shared_t)))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        floor = scored[0][0] * 0.65 if scored else 0
        # 同一天、同樣共享數字與關鍵詞的紀錄（同一件事被多張卡寫過）只留一筆
        picked, seen_sig = [], set()
        for s in scored:
            sig = ((s[2].get("event_date") or s[1]), tuple(s[3]), tuple(s[4]))
            if s[0] >= floor and sig not in seen_sig:
                picked.append(s)
                seen_sig.add(sig)
        picked = picked[:limit]
        # 標題數字最早出現的那筆一定要留（「7 月就公布過」比「上週又被報導」更重要）
        key = set(key_figures or [])
        firsts = sorted((s for s in scored if key & set(s[3])), key=lambda s: s[1])
        if firsts and firsts[0] not in picked:
            picked = picked[:max(0, limit - 1)] + [firsts[0]]
        out = []
        for score, _, r, sf, st in sorted(picked, key=lambda s: s[1]):   # 依日期由舊到新
            out.append({**r, "_match": {"score": round(score, 2), "shared_figures": sf, "shared_terms": st}})
        return out

    def find_today(self, cid: str, fkey: str, today: str) -> dict | None:
        for r in self.records:
            if r.get("first_seen") == today and (r.get("fact_key") == fkey or cid in (r.get("candidate_ids") or [])):
                return r
        return None

    def upsert(self, rec: dict, today: str, restated_key: str | None = None) -> str:
        """冪等寫入。回傳動作：'inserted'／'updated_today'／'restated'。
        - 同日重跑：同 candidate id 或同 fact_key 的今日紀錄 → 覆寫判斷欄位，不新增。
        - 重述舊事實：更新那筆舊紀錄的 last_seen／seen_dates，不新增。"""
        if restated_key:
            for r in self.records:
                if r.get("fact_key") == restated_key:
                    r["last_seen"] = max(r.get("last_seen") or "", today)
                    seen = r.setdefault("seen_dates", [])
                    if today not in seen:
                        seen.append(today)
                        del seen[:-10]
                    srcs = r.setdefault("sources", [])
                    for s in rec.get("sources") or []:
                        if s.get("url") and s["url"] not in {x.get("url") for x in srcs}:
                            srcs.append(s)
                    del srcs[:-8]
                    return "restated"
        existing = self.find_today(rec.get("candidate_ids", [""])[0], rec["fact_key"], today)
        if existing is not None:
            keep_first = existing.get("first_seen")
            cids = sorted(set(existing.get("candidate_ids") or []) | set(rec.get("candidate_ids") or []))
            existing.clear()
            existing.update(rec)
            existing["first_seen"] = keep_first
            existing["candidate_ids"] = cids
            return "updated_today"
        self.records.append(rec)
        return "inserted"

    def prune(self, today: str) -> int:
        before = len(self.records)
        keep = []
        for r in self.records:
            age = _days_between(today, r.get("last_seen") or r.get("first_seen") or "")
            if r.get("origin") == "seed" or age is None or age <= LEDGER_WINDOW_DAYS:
                keep.append(r)
        self.records = keep
        return before - len(keep)

    def to_json_text(self, today: str) -> str:
        """一筆一行、排序穩定：(first_seen, fact_key)。"""
        recs = sorted(self.records, key=lambda r: (r.get("first_seen") or "", r.get("fact_key")))
        head = json.dumps({"schema": LEDGER_SCHEMA, "updated": today, "count": len(recs)}, ensure_ascii=False)
        lines = ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in recs)
        return head[:-1] + ', "facts": [\n' + lines + "\n]}\n"
