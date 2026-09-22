"""
evidence_build_data.py
----------------------
本機維護工具（不在 CI 跑）：從 financial-analysis-bot 重建事件判斷層的兩份資料。

  python3 briefing/evidence_build_data.py routing --fab ~/financial-analysis-bot
      → 更新 data/evidence_routing.json 的 themes（segments 用到的研究主題：最新 ID 報告路徑＋成員 ticker）

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


def build_themes(fab: Path) -> None:
    routing = _load_routing()
    id_map = json.loads((fab / "portfolio" / "id_dd_map.json").read_text(encoding="utf-8"))
    latest = {}
    for fn, tickers in id_map.get("id_to_tickers", {}).items():
        m = re.match(r"ID_(.+)_(\d{8})\.html$", fn)
        if m and (m.group(1) not in latest or m.group(2) > latest[m.group(1)][0]):
            latest[m.group(1)] = (m.group(2), fn, tickers)
    wanted = {th for seg in routing["segments"].values() for th in seg.get("themes") or []}
    themes = {}
    for key in sorted(wanted):
        if key not in latest:
            print(f"  ! theme {key} not found in id_dd_map.json")
            continue
        d, fn, tickers = latest[key]
        label = key
        page = fab / "docs" / "id" / fn
        if page.exists():
            t = re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8", errors="ignore"), re.S)
            if t:
                label = html_lib.unescape(re.sub(r"\s+", " ", t.group(1))).split("|")[0].strip()[:80] or key
        themes[key] = {"path": f"/id/{fn}", "date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "label": label,
                       "tickers": sorted(tickers)[:20]}
    routing["themes"] = themes
    text = ROUTING.read_text(encoding="utf-8")
    # 只替換 themes 段，其餘手寫排版不動
    new_block = '"themes": ' + json.dumps(themes, ensure_ascii=False, indent=1).replace("\n", "\n ")
    text = re.sub(r'"themes": \{.*\}\s*\}\s*$', new_block + "\n}\n", text, flags=re.S)
    json.loads(text)
    ROUTING.write_text(text, encoding="utf-8")
    print(f"  ✓ themes: {len(themes)} → {ROUTING}")


# ── 種子 ────────────────────────────────────────────────────────────────
def _seed_record(companies, claim, detail, date, source, url, kind, terms=None):
    text = f"{claim}. {detail}"
    figs = extract_figures(text)
    raw = f"{kind}|{date}|{claim}|{','.join(sorted(companies))}"
    return {
        "fact_key": "fact_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14],
        "origin": "seed", "seed_kind": kind,
        "first_seen": date, "last_seen": date, "seen_dates": [date],
        "event_date": date, "date_basis": "published",
        "companies": companies, "claim": claim[:200], "detail": detail[:400],
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
            comps = matcher.match(f"{c['headline']} {c['body']}")
            if not comps:
                continue
            out.append(_seed_record(comps, c["headline"], c["body"], c["source_date"] or day,
                                    c["source"], "", "briefing_history",
                                    matcher.terms(f"{c['headline']} {c['body']}")))
    return out


def build_seed(fab: Path, days: int, until: str) -> None:
    routing = _load_routing()
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
        build_themes(fab)
    else:
        build_seed(fab, a.days, a.until)


if __name__ == "__main__":
    main()
