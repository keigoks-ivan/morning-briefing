"""
ideas_layer.py
--------------
事件判斷層的延伸：投資想法／查核點（idea checkpoints）。2026-09-23 新增。

背景：想法定義（每個想法底下的查核點，含 companies／keywords／themes／supports_if／
refutes_if）另外維護在 financial-analysis-bot，發布在
https://research.investmquest.com/ideas/ideas.json（本機開發讀 IDEAS_JSON_PATH，見
CLAUDE.md「投資想法」段）。這一層把事件判斷層已經判成「新事實」或「進度更新」的證據項目
（跟能進 `top` 的分類同一組，不含待複核、重述、未判斷）比對到查核點，挑出候選、
每天最多 8 對問 Jev 一題窄選擇題（支持／推翻／無關），寫回 evidence item 的 `ideas`
欄位，並把結果累加進跨日的 `docs/briefing/data/idea_hits.json`。

分工：
- 程式：載入 ideas.json、比對規則（companies／keywords／themes，見 match_checkpoints）、
  依 `_rank_key` 排序取前 8 對、組 Jev state／question、寫 idea_hits.json（冪等、
  跨日累加、保留 365 天）。
- Jev：只答 supports／refutes／unrelated 一題（evidence_questions.build_idea_question），
  不選股、不下結論。

失效保護：呼叫端（evidence_layer.run_evidence_layer）把整個 run_ideas_step() 包在自己的
try/except 裡；這一層出錯只讓 `ideas` 標 unavailable，不影響事件判斷層其餘輸出，也不影響
早報其他部分。同一天重跑：idea_hits.json 裡今天的列會被整批換掉（冪等），不是疊加。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evidence_questions import build_idea_question, interpret_choice
from evidence_routing import _keyword_hits

IDEAS_URL = "https://research.investmquest.com/ideas/ideas.json"
HITS_URL = "https://research.investmquest.com/briefing/data/idea_hits.json"
HITS_SCHEMA = "idea-hits-v1"
HITS_WINDOW_DAYS = 365   # idea_hits.json 只留最近這麼多天
MAX_IDEA_PAIRS = 8       # 每天最多幾對 (item, checkpoint) 問 Jev；超過的仍記一筆 unjudged，不猜


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 載入 ideas.json ─────────────────────────────────────────────────────
def load_ideas(fetch) -> tuple[list[dict], str]:
    """載入順序：IDEAS_JSON_PATH（本機檔案，開發／測試用）→ fetch 站上網址 → 都沒有就整步
    跳過。回 (ideas, status)；status："ok"／"unavailable"。net 還沒部署時 fetch 會 404，
    跟其他錯誤一樣一律當「跳過」，不擋早報（見 CLAUDE.md）。"""
    local = os.environ.get("IDEAS_JSON_PATH")
    if local:
        try:
            payload = json.loads(Path(local).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return [], "unavailable"
        return list(payload.get("ideas") or []), "ok"
    payload, status = fetch(IDEAS_URL)
    if status == "ok" and isinstance(payload, dict):
        return list(payload.get("ideas") or []), "ok"
    return [], "unavailable"


def _catalog(ideas: list[dict]) -> dict:
    """idea id → 想法簡稱／連結／查核點中文標籤（給畫面渲染用；idea_hits.json 的每一列
    只存 checkpoint id，不重複存中文標籤，靠這份對照表查）。"""
    out = {}
    for idea in ideas:
        out[idea.get("id", "")] = {
            "short": idea.get("short") or idea.get("title") or idea.get("id", ""),
            "url": idea.get("url", ""),
            "checkpoints": {cp.get("id", ""): cp.get("label", "") for cp in idea.get("checkpoints") or []},
        }
    return out


# ── 比對規則（程式，不用模型） ───────────────────────────────────────────
def _active_checkpoints(ideas: list[dict]):
    for idea in ideas:
        if idea.get("status") != "active":
            continue
        for cp in idea.get("checkpoints") or []:
            yield idea, cp


def match_checkpoints(text: str, company_keys, confirmed_themes, ideas: list[dict]) -> list[tuple[dict, dict, list[str]]]:
    """text：候選的 headline+summary（cand["text"]；不含全文，全文只給 Jev，見下方 _build_idea_state）。
    company_keys：這則候選比對到的所有公司 key（不分角色，跟 Jev state 裡的 candidate_companies
    是同一份清單）。confirmed_themes：這則已經被既有主題派送（evidence_routing.route）確認的
    研究主題 key。

    規則（兩個都要有 keyword 命中，見 CLAUDE.md「投資想法」段）：
    (a) 候選公司在 checkpoint.companies 裡（或文中出現 checkpoint.company_names 的名稱），
        且文中出現至少一個 checkpoint 關鍵詞；或
    (b) 文中出現兩個以上不同關鍵詞（單複數算同一個），或一個三個字以上的關鍵詞片語，或
        （checkpoint.themes 有一個主題被既有主題派送確認，且文中出現至少一個關鍵詞）。

    回 [(idea, checkpoint, matched_keywords)]，只包含 active 想法的 checkpoint。"""
    company_keys = set(company_keys or [])
    confirmed_themes = set(confirmed_themes or [])
    out = []
    for idea, cp in _active_checkpoints(ideas):
        hits = _keyword_hits(text, cp.get("keywords") or [])
        if not hits:
            continue
        # company_names：路由對照表認不得的公司（Nebius、信驊…），名稱出現在文中就算當事公司
        rule_a = bool(company_keys & set(cp.get("companies") or [])) or bool(
            _keyword_hits(text, cp.get("company_names") or []))
        # 單複數算同一個字：bond／bonds 同時出現不算兩個關鍵詞
        stems = {h.lower().rstrip("s") for h in hits}
        rule_b = (len(stems) >= 2 or any(len(h.split()) >= 3 for h in hits)
                  or bool(confirmed_themes & set(cp.get("themes") or [])))
        if rule_a or rule_b:
            out.append((idea, cp, hits))
    return out


# ── Jev 請求 ─────────────────────────────────────────────────────────────
def _build_idea_state(cand: dict, idea: dict, checkpoint: dict) -> dict:
    today = {"date": cand.get("source_date", ""), "outlet": cand.get("source", ""),
             "headline": cand["headline"], "report": cand["text"]}
    # 2026-09-23：全文（如果這則候選已經被 evidence_fulltext 抓到）只塞進這裡給 Jev 看，
    # 跟 evidence_layer.build_state 同一個規矩：只在這次執行的記憶體裡用，絕不寫進任何輸出檔。
    if cand.get("full_text_excerpt"):
        today["full_text"] = cand["full_text_excerpt"]
    return {"today": today, "idea": idea.get("short") or idea.get("title") or idea.get("id", "")}


def _first_url(item: dict) -> str:
    for s in item.get("sources") or []:
        if s.get("url"):
            return s["url"]
    return ""


# ── idea_hits.json（跨日累加，冪等） ────────────────────────────────────
def _merge_hits(hits_fetch, today: str, today_rows: list[dict]) -> dict:
    """載入昨天的 idea_hits.json（同一種抓取形狀：(payload, status)，見 evidence_layer._fetch_json）
    → 丟掉今天舊的列（同一天重跑要能整批換掉，不是疊加）→ 併入今天的列（同一天內先依
    (fact_key 或 evidence_id, idea, checkpoint) 去重）→ 只留最近 HITS_WINDOW_DAYS 天。

    抓不到昨天的檔案時兩種情況分開處理（不能混，見 CLAUDE.md）：
    - 404（missing）＝真的還沒有歷史（例如今天是這個檔案第一次寫），從空清單開始，不算「抓不到」；
    - 其他錯誤＝我們不知道昨天真正寫了什麼，不能假裝清空歷史就是對的；只寫今天的列，
      並標 history="unavailable"，讓頁面知道這個版本可能不完整。"""
    payload, status = hits_fetch(HITS_URL)
    if status == "ok" and isinstance(payload, dict):
        prior_rows, history = list(payload.get("hits") or []), "ok"
    elif status == "missing":
        prior_rows, history = [], "ok"
    else:
        prior_rows, history = [], "unavailable"

    kept = [r for r in prior_rows if r.get("date") != today]
    seen = set()
    for r in today_rows:
        key = (r.get("fact_key") or r.get("evidence_id"), r.get("idea"), r.get("checkpoint"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)

    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=HITS_WINDOW_DAYS)).strftime("%Y-%m-%d")
    kept = [r for r in kept if r.get("date", "") >= cutoff]
    return {"schema": HITS_SCHEMA, "generated_at": _now_iso(), "date": today, "history": history, "hits": kept}


# ── 主流程 ───────────────────────────────────────────────────────────────
def run_ideas_step(items: list[dict], cand_by_id: dict, jev, today: str, *,
                   ideas: list[dict] | None = None, fetch=None, rank_key=None, hits_fetch=None) -> dict:
    """就地在 items 的每一則加上 `ideas` 欄位（沒比對到就是空清單）。回一份摘要：
    {"status", "ideas_count", "matched_pairs", "asked", "catalog", "hits"}。

    ideas：直接給定就跳過載入（測試注入用）；fetch：抓 ideas.json／idea_hits.json 的函式
    （跟 evidence_layer._fetch_json 同形狀）；rank_key：早報既有的 _rank_key（排序用，
    由 evidence_layer.py 傳進來，避免循環 import）；hits_fetch：抓 idea_hits.json 用，
    預設跟 fetch 同一個。"""
    fetch = fetch or (lambda url, timeout=15: (None, "missing"))
    hits_fetch = hits_fetch or fetch
    rank_key = rank_key or (lambda it: 0)

    for it in items:
        it["ideas"] = []

    if ideas is None:
        ideas, ideas_status = load_ideas(fetch)
    else:
        ideas_status = "ok"

    today_rows: list[dict] = []
    candidates: list[tuple[dict, dict, dict]] = []
    if ideas_status == "ok" and ideas:
        for it in items:
            if (it.get("classification") or {}).get("class") not in ("new_fact", "progress_update"):
                continue
            cand = cand_by_id.get(it["id"])
            if not cand:
                continue
            company_keys = [c["key"] for c in it.get("companies") or []]
            confirmed_themes = [t["key"] for t in (it.get("routes") or {}).get("themes") or []]
            for idea, cp, _hits in match_checkpoints(cand["text"], company_keys, confirmed_themes, ideas):
                candidates.append((it, idea, cp))
        candidates.sort(key=lambda c: rank_key(c[0]))

        for i, (it, idea, cp) in enumerate(candidates):
            if i < MAX_IDEA_PAIRS:
                cand = cand_by_id[it["id"]]
                state = _build_idea_state(cand, idea, cp)
                questions = {"verdict": build_idea_question(idea, cp)}
                resp = jev.ask(state, questions) if jev is not None else None
                if resp:
                    ans = interpret_choice(resp["answers"], "verdict")
                    verdict, conf, by = ans["label"], ans["confidence"], resp.get("model")
                else:
                    verdict, conf, by = "unjudged", None, None
            else:
                verdict, conf, by = "unjudged", None, None   # 額滿：記錄比對到了，但沒被排進 Jev 名額
            it["ideas"].append({"idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                                "label": cp.get("label", ""), "verdict": verdict, "confidence": conf})
            if verdict != "unrelated":   # 無關的不進累加檔；「新事實但無關」只留在當天 JSON 供校準
                today_rows.append({
                    "date": today, "idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                    "verdict": verdict, "confidence": conf, "headline": it.get("headline", ""),
                    "source": it.get("source", ""), "url": _first_url(it),
                    "event_date": it.get("event_date", ""), "fact_key": it.get("fact_key"),
                    "evidence_id": it.get("id", ""), "by": by,
                })

    hits = _merge_hits(hits_fetch, today, today_rows)
    return {"status": ideas_status, "reason": "" if ideas_status == "ok" else "ideas.json not available",
            "ideas_count": len(ideas or []), "matched_pairs": len(candidates),
            "asked": min(len(candidates), MAX_IDEA_PAIRS), "catalog": _catalog(ideas or []), "hits": hits}
