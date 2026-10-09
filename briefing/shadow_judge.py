"""
shadow_judge.py
---------------
事件判斷層的影子判斷（2026-10-10 起，兩週）：同一批候選、同一份 state、同一組題目，Jev
答完之後再問一次 Claude Sonnet（訂閱 CLI），答案只寫進 `shadow_judge_{date}.json` 供比對，
**不影響早報任何輸出**——分類、派送、ledger、網頁、email 全部照 Jev 的答案走。

目的：決定要不要用 Sonnet 取代 Jev。兩週後跑 `briefing/shadow_compare.py` 看分歧、事後新舊
回查誰對、信心分數分布能不能沿用現有門檻（見 CLAUDE.md「影子判斷」段）。

做法：
- 題目原封不動：evidence_questions.build_questions 產生的同一份 questions，題目定義在每批
  只送一次（同一個題號的定義在所有候選都一樣），每則只列題號。
- Sonnet 對每題給「各選項的機率」，程式換成 Jev 的回應格式（choice→機率最高的選項、
  confidence＝最高機率；score→各級機率加權；noul→true 的機率），再走同一個 interpret()
  與 decide()。Jev 這邊也在同一時間用同一份 cand 重算一次 decide()，兩邊條件一致。
- 一天一次：候選依字數切成幾批並行呼叫（通常 2–4 批），任一批失敗只讓那批候選標
  shadow_error，不重試（_call_claude_code 內部已重試 3 次）。
- main.py 在 email 寄出之後才跑這一步，不會拖到早報；過了 SHADOW_LAST_DATE 自動跳過、不寫檔。

版權規則照舊：state 裡的全文只出現在送給 CLI 的提示裡（記憶體），輸出檔只有標籤、機率與
標題；錯誤只記例外型別，不記任何回應或提示內容。
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from evidence_layer import INDIRECT_MIN_CONF, VAR_MIN_CONF, decide
from evidence_questions import interpret
from jev_client import MODEL as JEV_MODEL
from jev_client import validate_response

SCHEMA = "shadow-judge-v1"
SHADOW_MODEL = os.environ.get("SHADOW_JUDGE_MODEL", "claude-sonnet-5-5")
SHADOW_LAST_DATE = os.environ.get("SHADOW_JUDGE_UNTIL", "2026-10-24")   # 含當天；之後自動跳過
SHADOW_TIMEOUT = int(os.environ.get("SHADOW_JUDGE_TIMEOUT", "240"))     # 秒／批／次
SHADOW_LABEL = "ShadowJudge"
MAX_BATCH_CHARS = 80_000    # 單批 payload 粗估字數上限（不含題目定義）
MAX_PARALLEL = 3

_SYSTEM_PROMPT = """You classify news items for a systematic investor's daily evidence log. The user message \
is one JSON object with two keys. `questions` holds every question, keyed by question id; each question has a \
`type`, `instructions` and `criteria` (the allowed answers). `items` is a list; each item has an `id`, a \
`state` (today's report under `today`, earlier records under `prior_records`, and the companies the questions \
refer to under `candidate_companies`) and `question_ids` (the questions to answer for that item).

Answer every listed question for every item, judging only from that item's `state`.

For each question give a probability for each allowed answer:
- type "choice": the answers are the keys of `criteria`.
- type "score": the answers are the level numbers "0", "1", "2", "3", one per `criteria` entry in order.
- type "noul": the answers are "true" and "false".
List only answers with a probability above zero; the probabilities for one question must add up to 1. Put \
less than 1 on the top answer whenever the material leaves real doubt.

Output exactly one JSON object, no other text:
{"items": [{"id": "<item id>", "answers": {"<question id>": {"<answer>": <probability>, ...}, ...}}, ...]}
Every item needs every one of its `question_ids` in `answers`."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 機率 → Jev 回應格式 ──────────────────────────────────────────────────
def _options(q: dict) -> list[str]:
    crit = q.get("criteria")
    if q.get("type") == "score":
        return [str(i) for i in range(len(crit or []))]
    return list((crit or {}).keys())


def to_jev_answers(raw: dict | None, questions: dict) -> dict | None:
    """Sonnet 的 {題號: {選項: 機率}} → Jev 的 answers。缺題、全部機率落在不存在的選項、格式不對
    → None（整則不用，跟 Jev 的 validate_response 一樣全有或全無）。"""
    if not isinstance(raw, dict):
        return None
    out = {}
    for qid, q in questions.items():
        dist = raw.get(qid)
        if not isinstance(dist, dict):
            return None
        opts = _options(q)
        probs = {}
        for o in opts:
            try:
                probs[o] = max(0.0, float(dist.get(o) or 0))
            except (TypeError, ValueError):
                probs[o] = 0.0
        total = sum(probs.values())
        if total <= 0:
            return None
        probs = {o: round(p / total, 4) for o, p in probs.items()}
        best = max(opts, key=lambda o: probs[o])
        if q["type"] == "choice":
            out[qid] = {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}
        elif q["type"] == "noul":
            out[qid] = {"type": "noul", "noul": probs.get("true", 0.0)}
        elif q["type"] == "score":
            out[qid] = {"type": "score", "score": round(sum(int(o) * p for o, p in probs.items()), 2),
                        "confidence": probs[best], "probabilities": probs}
        else:
            return None
    return out if validate_response({"answers": out}, questions) else None


def summarize(answers: dict, cand: dict, priors: list[dict], ledger_available: bool, today: str) -> dict:
    """Jev 或 Sonnet 的 answers → 比對用的精簡判斷（同一套 interpret／decide）。"""
    j = interpret(answers, cand["companies"], var_min_conf=VAR_MIN_CONF)
    final = decide(cand, j, priors, ledger_available, today)
    vs = j["variables"]
    direct = sorted(v for v, x in vs.items() if x["link"] == "direct")

    def pair(k):
        return [j[k]["label"], j[k]["confidence"]]

    return {
        "class": final["class"], "code_label": final.get("code_label"), "lane": final["lane"],
        "review_reasons": len(final["reasons"]),
        "novelty": pair("novelty"), "stage": pair("stage"), "timing": pair("timing"),
        "attribution": pair("attribution"),
        "importance": [j["importance"]["score"], j["importance"]["confidence"]],
        "direct": direct,
        "indirect": sorted(v for v, x in vs.items() if x["raw_link"] == "indirect"
                           and x["confidence"] >= INDIRECT_MIN_CONF and v != "market_valuation"),
        "uncertain": sorted(v for v, x in vs.items() if x["link"] == "uncertain"),
        "directions": {v: vs[v]["direction"] for v in direct},
        "parties": j["parties"],
    }


# ── 呼叫 ────────────────────────────────────────────────────────────────
def _split_into_batches(entries: list[dict], max_chars: int = MAX_BATCH_CHARS) -> list[list[dict]]:
    batches, current, size_now = [], [], 0
    for e in entries:
        size = len(json.dumps(e, ensure_ascii=False))
        if current and size_now + size > max_chars:
            batches.append(current)
            current, size_now = [], 0
        current.append(e)
        size_now += size
    if current:
        batches.append(current)
    return batches


def _batch_prompt(batch: list[dict], qmap: dict[str, dict]) -> str:
    bank: dict = {}
    for e in batch:
        for qid in e["question_ids"]:
            q = qmap[e["id"]][qid]
            if bank.setdefault(qid, q) != q:
                raise ValueError(f"question {qid} differs between items")
    return json.dumps({"questions": bank, "items": batch}, ensure_ascii=False)


def _default_judge_call(system_prompt: str, user_prompt: str) -> dict:
    from ai_processor import _call_claude_code
    return _call_claude_code(system_prompt, user_prompt, SHADOW_LABEL, thinking_tokens=0,
                             model=SHADOW_MODEL, timeout=SHADOW_TIMEOUT)


def _ask_batch(batch: list[dict], qmap: dict[str, dict], judge_call) -> dict[str, dict]:
    resp = judge_call(_SYSTEM_PROMPT, _batch_prompt(batch, qmap))
    ids = {e["id"] for e in batch}
    out = {}
    for it in (resp.get("items") if isinstance(resp, dict) else None) or []:
        if isinstance(it, dict) and it.get("id") in ids and isinstance(it.get("answers"), dict):
            out[it["id"]] = it["answers"]
    return out


def run_shadow(jobs: list[dict], today: str, ledger_available: bool, *, judge_call=None,
               last_date: str | None = None, model: str | None = None) -> dict:
    """jobs：evidence_layer.run_evidence_layer(shadow_jobs=...) 收集的每則候選
    {cand, priors, state, questions, jev_answers}。回影子判斷結果（status skipped 時不寫檔）。"""
    base = {"schema": SCHEMA, "date": today, "generated_at": _now_iso(),
            "model": model or SHADOW_MODEL, "baseline": JEV_MODEL}
    last = last_date or SHADOW_LAST_DATE
    if today > last:
        return {**base, "status": "skipped", "reason": f"shadow window ended {last}", "stats": {}, "items": []}
    if not jobs:
        return {**base, "status": "skipped", "reason": "no candidates", "stats": {}, "items": []}
    judge_call = judge_call or _default_judge_call

    qmap = {jb["cand"]["cid"]: jb["questions"] for jb in jobs}
    entries = [{"id": jb["cand"]["cid"], "state": jb["state"], "question_ids": list(jb["questions"])}
               for jb in jobs]
    batches = _split_into_batches(entries, MAX_BATCH_CHARS)
    raw_by_id: dict[str, dict] = {}
    batch_errors: list[str] = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batches))) as ex:
        futs = [ex.submit(_ask_batch, b, qmap, judge_call) for b in batches]
        for f in as_completed(futs):
            try:
                raw_by_id.update(f.result())
            except Exception as e:  # noqa: BLE001 — 只記型別，不記內容（可能含全文）
                batch_errors.append(type(e).__name__)
    seconds = round(time.monotonic() - t0, 1)

    items = []
    for jb in jobs:
        cand, cid = jb["cand"], jb["cand"]["cid"]
        args = (cand, jb["priors"], ledger_available, today)
        row = {"id": cid, "headline": cand.get("headline", ""), "kind": cand.get("kind"),
               "jev": summarize(jb["jev_answers"], *args) if jb.get("jev_answers") else None,
               "shadow": None}
        answers = to_jev_answers(raw_by_id.get(cid), jb["questions"])
        if answers is not None:
            row["shadow"] = summarize(answers, *args)
        else:
            row["shadow_error"] = "missing" if cid not in raw_by_id else "invalid"
        items.append(row)

    judged = sum(1 for r in items if r["shadow"])
    status = "judged" if judged == len(items) else ("partial" if judged else "failed")
    return {**base, "status": status, "reason": "",
            "stats": {"items": len(items), "judged": judged, "batches": len(batches),
                      "batch_errors": batch_errors, "seconds": seconds},
            "items": items}


def save_shadow(result: dict, data_dir, today: str) -> str | None:
    """同一天重跑覆寫同名檔。skipped 不寫檔。"""
    if result.get("status") == "skipped":
        return None
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    fn = f"shadow_judge_{today}.json"
    (data_dir / fn).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return fn
