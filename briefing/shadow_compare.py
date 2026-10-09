"""
shadow_compare.py
-----------------
影子判斷（shadow_judge.py）兩週結束後的比對：Sonnet 與 Jev 在同一批候選上的判斷差在哪、
事後回查誰對、Sonnet 的信心分數能不能沿用現有門檻。只讀檔，不呼叫任何模型、不寫進站上。

用法：
    python3 shadow_compare.py                          # 預設 2026-10-10 → 2026-10-24，從站上抓
    python3 shadow_compare.py --local ~/financial-analysis-bot/docs/briefing/data
    python3 shadow_compare.py --start 2026-10-12 --end 2026-10-18 --json /tmp/shadow_cmp.json

看什麼（依對早報的影響排序）：
1. 主線／低優先（lane）一致率：這是早報版面上真正會變的地方。
2. 事後新舊回查：用「現在」完整的 ledger 回查每則是否早有紀錄（evidence_calibration 的
   同一套規則），各算兩邊「判成新」的那批裡有多少其實是舊聞；兩邊新舊判斷相反的，逐則列出
   回查結果。回查是程式比對，不是標準答案，unclear 不算任何一方對。
3. 各題標籤一致率、直接變數集合重疊度、重要性分區一致率。
4. 新舊題信心分布：Sonnet 的機率是自己報的，跟 Jev 的校準方式不同；若 Sonnet 大量落在
   NOVELTY_MIN_CONF 以下或全部擠在 0.9 以上，現有門檻不能直接沿用。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from evidence_calibration import (SITE_DATA_URL, _fetch_json, _find_earlier_match, hindsight_check,
                                  importance_bucket, load_ledger_records)
from evidence_layer import NOVELTY_MIN_CONF
from evidence_ledger import EntityMatcher
from evidence_routing import PARTY_YES, load_routing

DEFAULT_START = "2026-10-10"
DEFAULT_END = "2026-10-24"
NEW_LABELS = ("new_fact", "progress_update")
CONF_EDGES = [0.5, 0.6, 0.7, 0.8, 0.9]
LABEL_FIELDS = ("class", "novelty", "stage", "timing", "attribution")


def _dates(start: str, end: str) -> list[str]:
    d, e, out = date.fromisoformat(start), date.fromisoformat(end), []
    while d <= e:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _local_fetch(root: Path):
    def fetch(url: str, timeout: int = 15):
        p = root / url.rsplit("/", 1)[-1]
        if not p.exists():
            return None, "missing"
        try:
            return json.loads(p.read_text(encoding="utf-8")), "ok"
        except Exception as e:  # noqa: BLE001
            return None, f"error:{type(e).__name__}"
    return fetch


def load_rows(start: str, end: str, fetch) -> tuple[list[dict], list[dict]]:
    """每則 {date, id, headline, jev, shadow, shadow_error, evidence}；evidence 是同一天
    evidence_{date}.json 裡同 id 的那則（事後回查要用它的公司、主題、日期與 fact_key）。"""
    rows, days = [], []
    for d in _dates(start, end):
        shadow, s_status = fetch(f"{SITE_DATA_URL}/shadow_judge_{d}.json")
        if s_status != "ok" or not isinstance(shadow, dict):
            days.append({"date": d, "status": s_status})
            continue
        ev, _ = fetch(f"{SITE_DATA_URL}/evidence_{d}.json")
        ev_by_id = {it["id"]: it for it in (ev or {}).get("items") or [] if isinstance(it, dict)}
        stats = shadow.get("stats") or {}
        days.append({"date": d, "status": shadow.get("status"), "items": stats.get("items"),
                     "judged": stats.get("judged"), "seconds": stats.get("seconds"),
                     "batch_errors": stats.get("batch_errors") or []})
        for it in shadow.get("items") or []:
            e = ev_by_id.get(it["id"])
            rows.append({**it, "date": d, "evidence": {**e, "date": d} if e else None})
    return rows, days


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def _bucket(c: float | None) -> str:
    if c is None:
        return "n/a"
    lo = "<0.5"
    for edge in CONF_EDGES:
        if c >= edge:
            lo = f"≥{edge}"
    return lo


def hindsight(evidence: dict, ledger_records: list[dict], matcher) -> dict:
    """evidence_calibration.hindsight_check，但先不帶 fact_key 找一次較早紀錄：被判成重述的那則
    會沿用先前紀錄的 fact_key，原函式會因此跳過正好能證明它是舊聞的那筆。"""
    m = _find_earlier_match({**evidence, "fact_key": None}, ledger_records, matcher)
    if m:
        r = m["record"]
        return {"label": "actually_old", "matched": r.get("claim", "")[:80],
                "first_seen": r.get("first_seen") or r.get("event_date")}
    return {"label": hindsight_check(evidence, ledger_records, matcher)["label"], "matched": None,
            "first_seen": None}


def compare(rows: list[dict], ledger_records: list[dict], matcher) -> dict:
    both = [r for r in rows if r.get("jev") and r.get("shadow")]
    out: dict = {"n_rows": len(rows), "n_both": len(both),
                 "n_shadow_missing": sum(1 for r in rows if not r.get("shadow")),
                 "n_jev_missing": sum(1 for r in rows if not r.get("jev"))}

    # ① lane
    lane = Counter((r["jev"]["lane"], r["shadow"]["lane"]) for r in both)
    out["lane"] = {"agree": _rate(sum(v for (a, b), v in lane.items() if a == b), len(both)),
                   "matrix": {f"jev={a} / sonnet={b}": v for (a, b), v in sorted(lane.items())}}

    # ③ 標籤、變數、重要性
    labels = {}
    for f in LABEL_FIELDS:
        get = (lambda x, f=f: x[f]) if f == "class" else (lambda x, f=f: x[f][0])
        conf = Counter((get(r["jev"]), get(r["shadow"])) for r in both)
        labels[f] = {"agree": _rate(sum(v for (a, b), v in conf.items() if a == b), len(both)),
                     "top_disagreements": [{"jev": a, "sonnet": b, "n": v} for (a, b), v in conf.most_common()
                                           if a != b][:5]}
    out["labels"] = labels
    jac, exact = [], 0
    for r in both:
        a, b = set(r["jev"]["direct"]), set(r["shadow"]["direct"])
        exact += a == b
        jac.append(len(a & b) / len(a | b) if a | b else 1.0)
    out["direct_vars"] = {"exact": _rate(exact, len(both)),
                          "mean_jaccard": round(sum(jac) / len(jac), 3) if jac else None}
    imp = sum(importance_bucket(r["jev"]["importance"][0]) == importance_bucket(r["shadow"]["importance"][0])
              for r in both)
    out["importance_bucket_agree"] = _rate(imp, len(both))
    pa = [(k, r) for r in both for k in r["jev"]["parties"] if k in r["shadow"]["parties"]]
    out["party_agree"] = _rate(sum((r["jev"]["parties"][k] >= PARTY_YES) == (r["shadow"]["parties"][k] >= PARTY_YES)
                                   for k, r in pa), len(pa))

    # ④ 信心分布（新舊題）
    dist = {}
    for who in ("jev", "shadow"):
        confs = [r[who]["novelty"][1] for r in both]
        dist[who] = {"buckets": dict(sorted(Counter(_bucket(c) for c in confs).items())),
                     "below_novelty_min": _rate(sum(c < NOVELTY_MIN_CONF for c in confs), len(confs)),
                     "has_review_reason": _rate(sum(r[who]["review_reasons"] > 0 for r in both), len(both)),
                     "mean_uncertain_vars": round(sum(len(r[who]["uncertain"]) for r in both) / len(both), 2)
                     if both else None}
    out["novelty_confidence"] = dist

    # ② 事後新舊回查
    checks = []
    for r in both:
        if not r.get("evidence"):
            continue
        h = hindsight(r["evidence"], ledger_records, matcher)
        checks.append({**r, "hindsight": h})
    hs = {}
    for who in ("jev", "shadow"):
        said_new = [c for c in checks if c[who]["novelty"][0] in NEW_LABELS]
        said_old = [c for c in checks if c[who]["novelty"][0] == "known_restatement"]
        hs[who] = {"said_new": len(said_new),
                   "said_new_actually_old": sum(c["hindsight"]["label"] == "actually_old" for c in said_new),
                   "said_restatement": len(said_old),
                   "said_restatement_confirmed_new": sum(c["hindsight"]["label"] == "confirmed_new"
                                                         for c in said_old)}
    split = []
    for c in checks:
        jn, sn = c["jev"]["novelty"][0], c["shadow"]["novelty"][0]
        if (jn in NEW_LABELS) == (sn in NEW_LABELS) or "known_restatement" not in (jn, sn):
            continue
        h = c["hindsight"]["label"]
        old_side = "jev" if jn == "known_restatement" else "sonnet"
        right = None if h == "unclear" else (old_side if h == "actually_old" else
                                             ("sonnet" if old_side == "jev" else "jev"))
        split.append({"date": c["date"], "headline": c.get("headline", "")[:90], "jev": jn, "sonnet": sn,
                      "hindsight": h, "matched": c["hindsight"]["matched"], "right": right})
    out["hindsight"] = {"checked": len(checks), "by_judge": hs, "novelty_splits": split,
                        "split_score": dict(Counter(s["right"] or "unclear" for s in split))}
    return out


def _fmt(res: dict, days: list[dict]) -> str:
    L = []
    ok = [d for d in days if d["status"] not in ("missing",) and d.get("items") is not None]
    L.append(f"影子判斷比對（{days[0]['date']} → {days[-1]['date']}）")
    L.append(f"有檔天數 {len(ok)}／{len(days)}；候選 {res['n_rows']} 則，兩邊都有判斷 {res['n_both']} 則，"
             f"Sonnet 缺 {res['n_shadow_missing']}、Jev 缺 {res['n_jev_missing']}")
    secs = [d["seconds"] for d in ok if d.get("seconds") is not None]
    errs = sum(len(d.get("batch_errors") or []) for d in ok)
    if secs:
        L.append(f"Sonnet 每天耗時 平均 {sum(secs) / len(secs):.0f} 秒、最長 {max(secs):.0f} 秒；批次失敗 {errs} 次")
    L.append("")
    L.append(f"① 主線／低優先一致率 {res['lane']['agree']}")
    for k, v in res["lane"]["matrix"].items():
        L.append(f"   {k}: {v}")
    h = res["hindsight"]
    L.append("")
    L.append(f"② 事後新舊回查（回查 {h['checked']} 則）")
    for who, name in (("jev", "Jev"), ("shadow", "Sonnet")):
        x = h["by_judge"][who]
        L.append(f"   {name}：判成新 {x['said_new']} 則，其中回查為舊聞 {x['said_new_actually_old']}；"
                 f"判成重述 {x['said_restatement']} 則，其中回查為新 {x['said_restatement_confirmed_new']}")
    L.append(f"   新舊判斷相反 {len(h['novelty_splits'])} 則，回查站在哪邊：{h['split_score']}")
    for s in h["novelty_splits"]:
        L.append(f"   - {s['date']} {s['headline']}｜Jev {s['jev']}／Sonnet {s['sonnet']}｜回查 {s['hindsight']}"
                 + (f"（對到：{s['matched']}）" if s["matched"] else ""))
    L.append("")
    L.append("③ 各題一致率")
    for f, v in res["labels"].items():
        top = "；".join(f"{d['jev']}→{d['sonnet']}×{d['n']}" for d in v["top_disagreements"][:3])
        L.append(f"   {f}: {v['agree']}" + (f"（常見分歧 {top}）" if top else ""))
    L.append(f"   直接變數集合完全相同 {res['direct_vars']['exact']}，平均 Jaccard {res['direct_vars']['mean_jaccard']}")
    L.append(f"   重要性分區一致 {res['importance_bucket_agree']}；涉及公司判斷一致 {res['party_agree']}")
    L.append("")
    L.append(f"④ 新舊題信心分布（門檻 {NOVELTY_MIN_CONF}）")
    for who, name in (("jev", "Jev"), ("shadow", "Sonnet")):
        x = res["novelty_confidence"][who]
        L.append(f"   {name}：{x['buckets']}｜低於門檻 {x['below_novelty_min']}｜"
                 f"有複審理由 {x['has_review_reason']}｜平均未定變數 {x['mean_uncertain_vars']}")
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    ap.add_argument("--local", help="讀本機資料夾（shadow_judge_*.json、evidence_*.json、evidence_ledger.json）")
    ap.add_argument("--json", help="另存完整比對結果")
    a = ap.parse_args()
    fetch = _local_fetch(Path(a.local).expanduser()) if a.local else _fetch_json
    rows, days = load_rows(a.start, a.end, fetch)
    if not rows:
        print(f"{a.start} → {a.end} 沒有任何 shadow_judge 檔。")
        sys.exit(1)
    records, status = load_ledger_records(fetch=fetch)
    if status != "ok":
        print(f"⚠ ledger 讀取失敗（{status}），事後回查會全部是 confirmed_new／unclear")
    res = compare(rows, records, EntityMatcher(load_routing()))
    print(_fmt(res, days))
    if a.json:
        Path(a.json).write_text(json.dumps({"days": days, **res}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n完整結果：{a.json}")


if __name__ == "__main__":
    main()
