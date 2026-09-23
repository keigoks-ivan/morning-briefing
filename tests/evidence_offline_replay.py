"""
離線重播 2026-09-22 早報案例（不呼叫付費 API、不寄信、不發布）。

  python3.12 tests/evidence_offline_replay.py --out /tmp/evidence_replay [--mode fake|nokey]

fake：用 tests/fixtures 的假 Jev 答案（測試劇本，不是真實 Jev 輸出）
nokey：模擬沒有 TYPESAFE_API_KEY，看早報如何標「未判斷」
輸出：evidence_*.json、evidence_ledger.json、source_quality_*.json、news.html、email.html
"""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_fixtures as fx  # noqa: E402

for mod in ("anthropic", "google", "google.genai", "google.genai.types"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

from evidence_layer import run_evidence_layer, save_outputs  # noqa: E402
from jev_client import JevClient  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["fake", "nokey"], default="fake")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    data = fx.briefing_data()
    if a.mode == "fake":
        jev, _ = fx.fake_client()
    else:
        jev = JevClient(api_key=None, cache={})
    ev, ledger = run_evidence_layer(
        data, [], fx.watchlist(), fx.news_quality(failed_feeds=("Korea Tech (GN)",)), fx.TODAY, out,
        ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch, sec_user_agent=None,
        official_fetch=fx.offline_sources)
    data["evidence_layer"] = ev
    data["date"] = "Tue 22 Sep 2026, 06:15 TST (offline replay)"
    written = save_outputs(ev, ledger, out, fx.TODAY)

    import html_template
    (out / "news.html").write_text(html_template.build_news_html(data), encoding="utf-8")
    (out / "email.html").write_text(html_template.build_html(data), encoding="utf-8")
    print("written:", ", ".join(written + ["news.html", "email.html"]))
    by_id = {it["id"]: it for it in ev["items"]}
    for lane in ("top", "more", "low_priority", "unjudged"):
        for i in ev[lane]:
            it = by_id[i]
            print(f"[{lane}] {it['headline'][:70]}")
            print(f"    class={it['classification']['display']} conf={it['classification']['confidence']} "
                  f"stage={(it.get('stage') or {}).get('label')} status={it['status']['display'][:110]}")
            print(f"    direct={[v['label'] + ' ' + str(v['direction']) for v in it['variables']['direct']]} "
                  f"indirect={[v['label'] for v in it['variables']['indirect']]}")
            print(f"    last_known={[(p['date'], p['outlet'][:20]) for p in it['last_known']]}")
            print(f"    dd={[d['ticker'] for d in it['routes']['dd']]} themes={[t['key'] for t in it['routes']['themes']]} "
                  f"holdings={[h['position'] for h in it['routes']['holdings']]} pending={[p['key'] for p in it['routes']['pending']]}")
            if it.get("potential_impact"):
                print(f"    knock_on={[(k['segment'], k['companies'][:3]) for k in it['potential_impact']['knock_on']]}")
            for n in it["unconfirmed"]:
                print(f"    ! {n}")
    print("ledger:", json.dumps(ev["ledger"]))
    print("jev:", json.dumps(ev["jev"]), json.dumps(ev["quality"]["jev"]))

    # 2026-09-23：投資想法／查核點層（briefing/ideas_layer.py）。設 IDEAS_JSON_PATH 才會真的讀到
    # 想法定義；沒設就會照常標 unavailable（本檔 fetch 一律用 fx.no_fetch，不連網）。
    print("ideas:", json.dumps(ev.get("ideas")))
    hit_items = [it for it in ev["items"] if it.get("ideas")]
    print(f"idea matches: {sum(len(it['ideas']) for it in hit_items)} pair(s) across {len(hit_items)} item(s)")
    for it in hit_items:
        print(f"  [{it['classification']['class']}] {it['headline'][:70]}")
        for h in it["ideas"]:
            print(f"    -> {h['idea']}/{h['checkpoint']} ({h['label']}): {h['verdict']} "
                  f"conf={h['confidence']}")
    if ev.get("idea_hits") is not None:
        rows = ev["idea_hits"].get("hits") or []
        print(f"idea_hits.json: history={ev['idea_hits'].get('history')} rows_today={len(rows)}")


if __name__ == "__main__":
    main()
