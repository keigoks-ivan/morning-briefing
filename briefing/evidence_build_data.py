"""
evidence_build_data.py
----------------------
本機維護工具（不在 CI 跑）：從 financial-analysis-bot 重建事件判斷層的兩份資料。

  python3 briefing/evidence_build_data.py routing --fab ~/financial-analysis-bot
      → 重建 data/evidence_routing_auto.json：全部研究主題（ID）的成員、深度、姊妹主題，
        從角色欄抽出的公司名，以及總經報告（MACRO）的關鍵指標。人工對照表不動。

  python3 briefing/evidence_build_data.py seed --fab ~/financial-analysis-bot --days 60
      → 重建 data/evidence_seed_ledger.json（「先前已知」種子）：
        ① 每檔最新 DD 的 dd-meta oneliner（當時的已知事實，例如 MSFT 7/30：Copilot 席位 30M）
        ② 過去 N 天已發布早報 news.html 的新聞卡（從 git 歷史讀，不動工作目錄）
        種子紀錄 origin=seed，不會被 180 天修剪。

只讀 fab repo（git show／讀檔），不寫、不 commit。
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from evidence_ledger import EntityMatcher, content_tokens, extract_figures  # noqa: E402

ROUTING = ROOT / "data" / "evidence_routing.json"
SEED = ROOT / "data" / "evidence_seed_ledger.json"


def _load_routing() -> dict:
    return json.loads(ROUTING.read_text(encoding="utf-8"))


AUTO = ROOT / "data" / "evidence_routing_auto.json"

# 研究主題報告角色欄的開頭常是公司名（「Ibiden — …」「台達電，…」），抽出來當公司別名。
# 單字常用詞當公司名會誤中（United、Delta、Target…），一律不收。
_NAME_STOP = {"United", "American", "Delta", "Southwest", "Block", "Target", "Sea", "Square", "Match",
              "Meta", "Apple", "Amazon", "Crown", "Global", "General", "National", "Energy",
              "Hybrid", "Scale", "Merchant", "Performance", "Custom", "Private", "Public", "Master"}
_NAME_EN = re.compile(r"(?:[A-Z0-9][A-Za-z0-9&.'’\-]*)(?: (?:[A-Z0-9&][A-Za-z0-9&.'’\-]*|of|de|and))*")
_NAME_ZH = re.compile(r"[\u4e00-\u9fff]{2,6}")


# 角色欄開頭是描述不是公司名的中文詞（2026-09-22 人工看過全部 47 個中文候選後列出）
_ZH_JUNK = {"端側推論", "創意席次", "沉積與磊晶", "沉積", "燃料電池", "非顯而易見", "邊緣", "電纜製造", "電氣設備",
            "互鎖", "探針卡", "製程控制", "車用", "身份", "雞肉純玩家", "純電塔", "德國", "蛋白終端"}
_ASIA_SUFFIX = (".TW", ".TWO", ".T", ".KS", ".KQ", ".SZ", ".SS", ".HK")


def _role_name(role: str) -> str | None:
    head = re.split(r"——|—|－|，|,|（|\(|；|;|：|:|／| / ", role or "")[0].strip()
    if 2 <= len(head) <= 30 and _NAME_EN.fullmatch(head) and head not in _NAME_STOP and not head.isdigit():
        return head
    # 中文只收短的公司名；含「方、體、戶、益、買、主、收、典、範、游、層、段、類」多半是角色描述（下游客戶、出錢方）
    if _NAME_ZH.fullmatch(head) and len(head) <= 5 and not re.search(r"[方體戶益買主收典範游層段類商群者]", head):
        return head
    return None


def _meta(page: Path, tag: str) -> dict | None:
    m = re.search(rf'<script[^>]*id="{tag}"[^>]*>(.*?)</script>', page.read_text(encoding="utf-8", errors="ignore"), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def build_auto(fab: Path) -> None:
    """從研究主題（ID）與總經（MACRO）報告自動產生：themes、auto_companies、macro_reports。
    寫到 data/evidence_routing_auto.json；人工對照表 data/evidence_routing.json 不動。"""
    latest = {}
    for page in (fab / "docs" / "id").glob("ID_*_*.html"):
        m = re.match(r"ID_(.+)_(\d{8})\.html$", page.name)
        if m and (m.group(1) not in latest or m.group(2) > latest[m.group(1)][0]):
            latest[m.group(1)] = (m.group(2), page)
    id_map = json.loads((fab / "portfolio" / "id_dd_map.json").read_text(encoding="utf-8")).get("id_to_tickers", {})
    themes, companies = {}, {}
    for key, (d, page) in sorted(latest.items()):
        if key.startswith("CNTW_"):   # 地緣母題系列，不是產業主題
            continue
        meta = _meta(page, "id-meta") or {}
        members = {}
        for rt in meta.get("related_tickers") or []:
            tk = str(rt.get("ticker") or "").strip()
            if not tk:
                continue
            name = _role_name(str(rt.get("role") or ""))
            if name and name.isupper() and len(name) <= 5 and name != tk.split(".")[0]:
                name = None   # EUV、AWS、SOC 這類全大寫短字多半是技術或產品，不是公司名
            if name and re.search(r"[\u4e00-\u9fff]", name) and (name in _ZH_JUNK or not tk.endswith(_ASIA_SUFFIX)) \
                    and name not in {"英特爾", "科林研發", "美光", "安森美", "德州儀器", "應用材料", "艾頓", "施耐德"}:
                name = None
            members[tk] = {"depth": rt.get("depth", ""), "purity": rt.get("purity_pct"), "name": name or ""}
            if name:
                aliases = companies.setdefault(tk, {"aliases": []})["aliases"]
                if name not in aliases:
                    aliases.append(name)
        if not members:
            for tk in id_map.get(page.name, []):
                members[tk] = {"depth": "", "purity": None, "name": ""}
        sisters = []
        for s in meta.get("sister_ids") or []:
            sm = re.match(r"ID_(.+)_\d{8}\.html$", str(s))
            if sm and sm.group(1) != key:
                sisters.append(sm.group(1))
        label = str(meta.get("theme") or "").strip()
        if not label:
            t = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8", errors="ignore"), re.S)
            label = html_lib.unescape(re.sub(r"\s+", " ", t.group(1))).split("|")[0].strip()[:80] if t else key
        themes[key] = {"label": label[:80], "path": f"/id/{page.name}", "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                       "mega": meta.get("mega") or "", "sub_group": meta.get("sub_group") or "",
                       "sisters": list(dict.fromkeys(sisters))[:6], "members": members}
    macro = {}
    for page in sorted((fab / "docs" / "macro").glob("MACRO_*_*.html")):
        meta = _meta(page, "macro-meta") or {}
        slug = meta.get("slug") or re.sub(r"MACRO_(.+)_\d{8}\.html$", r"\1", page.name)
        if slug in macro and macro[slug]["date"] >= str(meta.get("date") or ""):
            continue
        macro[slug] = {"topic": meta.get("topic", slug), "path": f"/macro/{page.name}", "date": str(meta.get("date") or ""),
                       "kill_metrics": [{"metric": k.get("metric", ""), "source": k.get("source", "")}
                                        for k in meta.get("kill_metrics") or []]}
    out = {"schema": "evidence-routing-auto-v1",
           "_comment": "自動產生，不要手改。重建：python3 briefing/evidence_build_data.py routing --fab ~/financial-analysis-bot",
           "built_from": fab.name, "themes": themes, "auto_companies": companies, "macro_reports": macro}
    AUTO.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  ✓ themes {len(themes)}｜companies with names {len(companies)}｜macro reports {len(macro)} → {AUTO}")


# ── 種子 ────────────────────────────────────────────────────────────────
def _seed_record(companies, claim, detail, date, source, url, kind, terms=None, subjects=None):
    text = f"{claim}. {detail}"
    figs = extract_figures(text)
    raw = f"{kind}|{date}|{claim}|{','.join(sorted(companies))}"
    return {
        "fact_key": "fact_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
        "origin": "seed", "seed_kind": kind,
        "first_seen": date, "last_seen": date, "seen_dates": [date],
        "event_date": date, "date_basis": "published",
        "companies": companies, "claim": claim[:200], "detail": detail[:400],
        "subjects": subjects or [],
        "figures": figs, "terms": terms or [], "tokens": sorted(content_tokens(text))[:40],
        "sources": [{"source": source, "url": url, "published": date}],
    }


def seed_from_dd(fab: Path, matcher: EntityMatcher) -> list[dict]:
    latest = {}
    for p in (fab / "docs" / "dd").glob("DD_*_*.html"):
        m = re.match(r"DD_(.+)_(\d{8})\.html$", p.name)
        if m and (m.group(1) not in latest or m.group(2) > latest[m.group(1)][0]):
            latest[m.group(1)] = (m.group(2), p)
    out = []
    for ticker, (d, p) in sorted(latest.items()):
        m = re.search(r'<script[^>]*id="dd-meta"[^>]*>(.*?)</script>', p.read_text(encoding="utf-8", errors="ignore"), re.S)
        if not m:
            continue
        try:
            meta = json.loads(m.group(1))
        except ValueError:
            continue
        one = str(meta.get("oneliner") or "").strip()
        if not one:
            continue
        key = matcher.canonical(ticker) if ticker in matcher.companies else ticker
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        out.append(_seed_record([key], f"DD {ticker} ({date})", one, date, "DD report", f"/dd/{p.name}", "dd",
                                matcher.terms(one)))
    return out


_SRC_LINE = re.compile(r"^(20\d\d-\d\d-\d\d) · (.{2,60})$")
_BADGES = {"Key", "重要", "Index book", "指數部", "AI capex", "M&A", "Evidence ▸", "Value chain ▸",
           "Unknowns ▸", "關鍵證據 ▸", "產業鏈 ▸", "尚待確認 ▸", "已知影響 ▸"}


def _cards_from_html(page: str) -> list[dict]:
    text = html_lib.unescape(re.sub(r"<[^>]+>", "\n", page))
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    cards = []
    for i, line in enumerate(lines):
        m = _SRC_LINE.match(line)
        if not m:
            continue
        window = lines[max(0, i - 16):i]
        # 分類事實卡：標題與內文在第一個「▸」摺疊段之前；只看那之前
        marks = [k for k, l in enumerate(window) if l.endswith("▸")]
        if marks:
            window = window[:marks[0]]
        else:
            window = window[-8:]
        prev = [l for l in window if l not in _BADGES and len(l) > 4 and not _SRC_LINE.match(l)]
        body = next((l for l in reversed(prev) if len(l) >= 40), "")
        if not body:
            continue
        bi = max(k for k, l in enumerate(prev) if l == body)
        head = next((l for l in reversed(prev[:bi]) if 6 <= len(l) <= 140 and not _SRC_LINE.match(l)), "")
        if head:
            cards.append({"headline": head, "body": body, "source_date": m.group(1), "source": m.group(2)})
    return cards


def seed_from_briefings(fab: Path, matcher: EntityMatcher, days: int, until: str) -> list[dict]:
    since = (datetime.strptime(until, "%Y-%m-%d") - timedelta(days=days)).date().isoformat()
    log = subprocess.run(["git", "-C", str(fab), "log", "origin/main", "--format=%h %s", f"--since={since}",
                          "--", "docs/briefing/news.html"], capture_output=True, text=True, check=True).stdout
    by_day = {}
    for line in log.splitlines():
        h, _, subj = line.partition(" ")
        m = re.search(r"20\d\d-\d\d-\d\d", subj)
        if m and m.group() < until and m.group() not in by_day:   # log 新到舊：每天取最後發布的版本
            by_day[m.group()] = h
    out = []
    for day, h in sorted(by_day.items()):
        page = subprocess.run(["git", "-C", str(fab), "show", f"{h}:docs/briefing/news.html"],
                              capture_output=True, text=True).stdout
        for c in _cards_from_html(page):
            text = f"{c['headline']} {c['body']}"
            comps = matcher.match(text)
            subjects = matcher.subjects(text)   # 2026-09-22：總經新聞也收（沒有公司也要）
            if not comps and not subjects:
                continue
            out.append(_seed_record(comps, c["headline"], c["body"], c["source_date"] or day,
                                    c["source"], "", "briefing_history", matcher.terms(text), subjects))
    return out


def build_seed(fab: Path, days: int, until: str) -> None:
    from evidence_routing import load_routing
    routing = load_routing()   # 人工表＋自動檔（公司名、總經主題都要）
    matcher = EntityMatcher(routing)
    recs = seed_from_dd(fab, matcher) + seed_from_briefings(fab, matcher, days, until)
    uniq = {}
    for r in recs:
        uniq.setdefault(r["fact_key"], r)
    facts = sorted(uniq.values(), key=lambda r: (r["first_seen"], r["fact_key"]))
    head = json.dumps({"schema": "evidence-ledger-v1", "updated": until, "count": len(facts),
                       "note": f"seed: latest DD oneliners + published briefing cards {days} days before {until}"},
                      ensure_ascii=False)
    body = ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in facts)
    SEED.write_text(head[:-1] + ', "facts": [\n' + body + "\n]}\n", encoding="utf-8")
    kinds = {}
    for r in facts:
        kinds[r["seed_kind"]] = kinds.get(r["seed_kind"], 0) + 1
    print(f"  ✓ seed: {len(facts)} facts {kinds} → {SEED} ({SEED.stat().st_size:,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["routing", "seed"])
    ap.add_argument("--fab", default=str(Path.home() / "financial-analysis-bot"))
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--until", default=datetime.now().date().isoformat(),
                    help="只收這天以前的早報（不含當天），避免把今天的新聞當成先前已知")
    a = ap.parse_args()
    fab = Path(a.fab).expanduser()
    if a.cmd == "routing":
        build_auto(fab)
    else:
        build_seed(fab, a.days, a.until)


if __name__ == "__main__":
    main()
