"""
ideas_layer.py
--------------
事件判斷層的延伸：投資想法／查核點（idea checkpoints）。2026-09-23 新增，2026-09-23 晚擴充
「早報外掃描」（wide scan，見下方②）與逐項批次問法（見下方①）。

背景：想法定義（每個想法底下的查核點，含 companies／keywords／themes／supports_if／
refutes_if／可選的 due）另外維護在 financial-analysis-bot，發布在
https://research.investmquest.com/ideas/ideas.json（本機開發讀 IDEAS_JSON_PATH，見
CLAUDE.md「投資想法」段）。

這一層做兩件事：
① 早報候選（事件判斷層已經判成「新事實」或「進度更新」的項目，跟能進 `top` 的分類同一組）：
   比對到查核點，每天最多 8 則「新聞項目」問 Jev——不是每對 (item, checkpoint) 各問一次，
   是同一則新聞命中的所有查核點合成「一題選擇題」，一次請求問完（`jev.ask` 本來就支援一次
   問多題），省請求數。
② 早報之外的新聞（去重後的完整池子，main.py 傳進來的 `rss_items`，約 300-400 則，早報自己
   只挑了其中一小部分當候選）：對池子裡「還沒被早報候選用到」的每一則，只用程式規則（英文
   關鍵詞比對，不問模型）比對查核點；比對到的再套幾條程式新舊把關（見 _wide_scan），把關
   後每天最多再挑 8 則問 Jev（一樣是逐則批次問法）。這些「早報外」的命中永遠不會進
   `items`／`top`／DD 派送／ledger 新事實，只在 idea_hits.json 多一欄 origin="wide"，
   evidence_basis="headline_summary"（早報頁面會標「早報外」＋「只讀到標題與摘要」）。

分工：
- 程式：載入 ideas.json、比對規則（companies／keywords／themes，見 match_checkpoints，不動
  這支函式）、早報外掃描的新舊把關（事件日期過舊、ledger 已有同公司／主題＋同數字的紀錄、
  idea_hits.json 歷史已經問過同網址或同標題、標題跟某則早報候選近似）、排序取前 8＋8、組
  Jev state／questions、寫 idea_hits.json（冪等、跨日累加、保留 365 天）。
- Jev：只答 supports／refutes／unrelated（evidence_questions.build_idea_question），一則新聞
  命中幾個查核點就答幾題，不選股、不下結論。

失效保護：呼叫端（evidence_layer.run_evidence_layer）把整個 run_ideas_step() 包在自己的
try/except 裡；這一層出錯只讓 `ideas` 標 unavailable，不影響事件判斷層其餘輸出。同一天重跑：
idea_hits.json 裡今天的列會被整批換掉（冪等），不是疊加。

注意：`_near_same_headline`／`_normalize_title_key`／`_title_tokens` 是刻意跟
`news_fetcher._near_same_title` 同一套演算法（同樣的正規化與 Jaccard 門檻）另外抄一份，不是
直接 import news_fetcher——news_fetcher.py 掛了 feedparser／requests 等重依賴，這一層被
evidence_layer.py 在模組層級 import，早報以外的測試環境（例如沒裝 feedparser 的
`python3.12 -m pytest`）import 到就會整包炸掉。normalize_url 沒有這個問題（source_registry.py
只用 re／urllib），直接 import。
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evidence_ledger import _days_between, content_tokens, extract_figures
from evidence_ledger import fact_key as ledger_fact_key
from evidence_questions import build_idea_question, interpret_choice
from evidence_routing import _keyword_hits
from source_registry import normalize_url

IDEAS_URL = "https://research.investmquest.com/ideas/ideas.json"
HITS_URL = "https://research.investmquest.com/briefing/data/idea_hits.json"
HITS_SCHEMA = "idea-hits-v1"
HITS_WINDOW_DAYS = 365   # idea_hits.json 只留最近這麼多天
MAX_BRIEFING_IDEA_ITEMS = 8   # 每天最多幾則早報候選新聞問 Jev（一則可能命中多個查核點，合成一題一次問）
MAX_WIDE_IDEA_ITEMS = 8       # 每天最多幾則「早報外」新聞問 Jev
IDEA_ITEM_BUDGET = MAX_BRIEFING_IDEA_ITEMS + MAX_WIDE_IDEA_ITEMS   # 給 evidence_layer 組 JevClient 請求上限用
STALE_WIDE_DAYS = 3   # 跟 evidence_layer.STALE_EVENT_DAYS 一致：早報外新聞比這個天數更舊就不問


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
    只存 checkpoint id，不重複存中文標籤，靠這份對照表查）＋這個想法未來到期的查核點
    （只收 active 想法；`due` 是 ideas.json 的選填欄位，見檔頭）。"""
    out = {}
    for idea in ideas:
        due = []
        if idea.get("status") == "active":
            for cp in idea.get("checkpoints") or []:
                for d in cp.get("due") or []:
                    if isinstance(d, dict) and d.get("date"):
                        due.append({"date": d.get("date", ""), "label": d.get("label", ""),
                                    "approx": bool(d.get("approx")), "checkpoint": cp.get("id", ""),
                                    "checkpoint_label": cp.get("label", "")})
        out[idea.get("id", "")] = {
            "short": idea.get("short") or idea.get("title") or idea.get("id", ""),
            "url": idea.get("url", ""),
            "checkpoints": {cp.get("id", ""): cp.get("label", "") for cp in idea.get("checkpoints") or []},
            "due": due,
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
    """text：候選的 headline+summary（cand["text"]；不含全文，全文只給 Jev，見下方 _build_item_state）。
    company_keys：這則候選比對到的所有公司 key（不分角色，跟 Jev state 裡的 candidate_companies
    是同一份清單）。confirmed_themes：這則已經被既有主題派送（evidence_routing.route）確認的
    研究主題 key（早報外掃描沒有跑 route()，一律傳空清單，見 _wide_scan）。

    規則（兩個都要有 keyword 命中，見 CLAUDE.md「投資想法」段）：
    (a) 候選公司在 checkpoint.companies 裡（或文中出現 checkpoint.company_names 的名稱），
        且文中出現至少一個 checkpoint 關鍵詞；或
    (b) 文中出現兩個以上不同關鍵詞（單複數算同一個），或一個三個字以上的關鍵詞片語，或
        （checkpoint.themes 有一個主題被既有主題派送確認，且文中出現至少一個關鍵詞）。

    回 [(idea, checkpoint, matched_keywords)]，只包含 active 想法的 checkpoint。這支刻意不動：
    早報候選跟早報外掃描共用同一份規則，見檔頭①②。"""
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


def _rule_a_hit(text: str, company_keys, checkpoint: dict) -> bool:
    """跟 match_checkpoints 的規則 (a) 同一個條件，只用來給候選排序（公司命中優先），不影響
    比對結果本身——match_checkpoints 才是唯一的比對權威，這支不重造規則，只是另外問一次同樣的問題。"""
    keys = set(company_keys or [])
    return bool(keys & set(checkpoint.get("companies") or [])) or bool(
        _keyword_hits(text, checkpoint.get("company_names") or []))


def _item_rank_key(text: str, company_keys, matches: list[tuple[dict, dict, list[str]]], days_ago: int | None) -> tuple:
    """排序：規則 (a) 公司命中優先 → 不同關鍵詞數（跨所有命中的查核點合計，單複數視為同一個）→
    越新越前面。用在早報候選與早報外候選各自排序取前 8（兩組分開排，不混排），見 run_ideas_step。"""
    company_match = any(_rule_a_hit(text, company_keys, cp) for _, cp, _ in matches)
    distinct_kw = len({h.lower().rstrip("s") for _, _, hits in matches for h in hits})
    return (0 if company_match else 1, -distinct_kw, days_ago if days_ago is not None else 9_999)


def _rank_and_cap(candidates: list[dict], cap: int) -> tuple[list[dict], list[dict]]:
    """candidates 裡每筆要有 text／company_keys／matches／days_ago 四個 key（多的欄位不管）。
    回 (問到名額的, 額滿沒問到的)，都依 _item_rank_key 排好序。"""
    ranked = sorted(candidates, key=lambda c: _item_rank_key(c["text"], c["company_keys"], c["matches"], c["days_ago"]))
    return ranked[:cap], ranked[cap:]


# ── 早報外掃描：中文偵測與標題近似（程式規則，不用模型） ───────────────────
_CJK_RE = re.compile(r"[一-鿿]")


def _is_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _normalize_title_key(title: str) -> str:
    text = unicodedata.normalize("NFKC", title or "").casefold()
    text = re.sub(r"\s+-\s+[^-]{2,40}$", "", text)
    return re.sub(r"[^a-z0-9一-鿿]+", "", text)


def _title_tokens(title: str) -> set[str]:
    text = unicodedata.normalize("NFKC", title or "").casefold()
    english = set(re.findall(r"[a-z0-9][a-z0-9.\-]{1,}", text))
    cjk = "".join(re.findall(r"[一-鿿]", text))
    return english | {cjk[i:i + 2] for i in range(max(0, len(cjk) - 1))}


def _near_same_headline(a: str, b: str) -> bool:
    na, nb = _normalize_title_key(a), _normalize_title_key(b)
    if na and na == nb:
        return True
    ta, tb = _title_tokens(a), _title_tokens(b)
    if len(ta) < 3 or len(tb) < 3:
        return False
    return len(ta & tb) / len(ta | tb) >= 0.82


def _briefing_used_urls(cand_by_id: dict) -> set[str]:
    return {normalize_url(r["url"]) for c in cand_by_id.values() for r in (c.get("rss") or []) if r.get("url")}


def _briefing_headlines(cand_by_id: dict) -> list[str]:
    return [c.get("headline", "") for c in cand_by_id.values() if c.get("headline")]


def _load_hits_rows(hits_fetch) -> list[dict]:
    """給早報外掃描的「同網址／同標題已經問過」把關用；抓不到就當作沒有歷史可比對（保守：
    寧可少擋一次重複，也不假裝知道歷史內容——真正的合併／history 狀態仍由 _merge_hits 負責。"""
    try:
        payload, status = hits_fetch(HITS_URL)
    except Exception:  # noqa: BLE001
        return []
    if status == "ok" and isinstance(payload, dict):
        return list(payload.get("hits") or [])
    return []


def _wide_scan(rss_items: list[dict], cand_by_id: dict, matcher, ledger, ideas: list[dict],
              today: str, hits_history_rows: list[dict]) -> tuple[list[dict], dict]:
    """早報外掃描（見檔頭②）。rss_items：main.py 傳進 run_evidence_layer 的去重後完整新聞池
    （已經是 rss_items 參數本身，不用另外從 main.py 多傳一份——news_fetcher.fetch_rss_news()
    回傳的就是去重後的池子）。cand_by_id：事件判斷層自己的候選（不分早報候選最終被判成什麼
    類別），用來排除池子裡已經被早報用掉的新聞、以及近似標題比對的基準。

    回 (candidates, stats)。candidates 是通過全部把關、可以拿去問 Jev 的（每筆有
    headline／text／source／url／published／days_ago／matches／company_keys）；stats 是
    pool_size／already_in_candidates／chinese_count／matched_items／skipped_by_reason，寫進
    當天 evidence JSON 的 ideas.wide_scan（見 CLAUDE.md「投資想法」段）。"""
    used_urls = _briefing_used_urls(cand_by_id)
    briefing_headlines = _briefing_headlines(cand_by_id)
    hist_urls = {normalize_url(r["url"]) for r in hits_history_rows if r.get("url")}
    hist_titles = {_normalize_title_key(r["headline"]) for r in hits_history_rows if r.get("headline")}

    pool = rss_items or []
    already = chinese = matched_items = 0
    skipped = {"stale_event": 0, "ledger_known_figure": 0, "hits_history_duplicate": 0, "near_dup_briefing": 0}
    candidates = []
    for it in pool:
        url_norm = normalize_url(it.get("link", ""))
        if url_norm and url_norm in used_urls:
            already += 1
            continue
        title = str(it.get("title") or "")
        summary = str(it.get("summary") or "")
        text = f"{title}. {summary}".strip()
        if _is_chinese(title) or _is_chinese(summary):
            chinese += 1   # 英文關鍵詞比對本來就配不到，這裡只是報數，不另外做中文比對（見 CLAUDE.md）

        company_keys = matcher.match(text)
        matches = match_checkpoints(text, company_keys, [], ideas)   # 早報外沒有跑 route()，不做主題確認
        if not matches:
            continue
        matched_items += 1

        published = str(it.get("published") or "")
        days_ago = _days_between(today, published[:10]) if published else None
        if days_ago is not None and days_ago > STALE_WIDE_DAYS:
            skipped["stale_event"] += 1
            continue

        subjects = matcher.subjects(text)
        figures = extract_figures(text)
        headline_figs = extract_figures(title)
        terms = matcher.terms(text)
        tokens = content_tokens(text)
        priors = ledger.find_prior(list(company_keys) + subjects, figures, terms, tokens, today,
                                   key_figures=headline_figs)
        if any((p.get("_match") or {}).get("shared_figures") for p in priors):
            # 重用既有 ledger 比對（跟事件判斷層 _figure_overlap 同精神）：先前紀錄已經跟這則
            # 共享公司／主題「而且」共享數字，當作已經記過，不再問 Jev
            skipped["ledger_known_figure"] += 1
            continue

        if (url_norm and url_norm in hist_urls) or (title and _normalize_title_key(title) in hist_titles):
            skipped["hits_history_duplicate"] += 1
            continue

        if any(_near_same_headline(title, h) for h in briefing_headlines):
            skipped["near_dup_briefing"] += 1
            continue

        candidates.append({
            "headline": title, "text": text, "summary": summary, "source": str(it.get("source") or ""),
            "url": it.get("link", ""), "published": published, "days_ago": days_ago,
            "matches": matches, "company_keys": company_keys,
        })

    stats = {"pool_size": len(pool), "already_in_candidates": already, "chinese_count": chinese,
             "matched_items": matched_items, "skipped_by_reason": skipped, "asked_items": 0}
    return candidates, stats


# ── Jev 請求（逐則批次問法：一則新聞命中幾個查核點就在同一次請求問幾題） ───
def _build_item_state(headline: str, source_date: str, source: str, text: str,
                      full_text_excerpt: str | None = None) -> dict:
    today = {"date": source_date, "outlet": source, "headline": headline, "report": text}
    # 全文（如果這則候選已經被 evidence_fulltext 抓到；早報外的候選不抓全文，evidence_basis
    # 固定是 headline_summary）只塞進這裡給 Jev 看，跟 evidence_layer.build_state 同一個規矩：
    # 只在這次執行的記憶體裡用，絕不寫進任何輸出檔。
    if full_text_excerpt:
        today["full_text"] = full_text_excerpt
    return {"today": today}


def _question_key(idea: dict, cp: dict) -> str:
    return f"{idea.get('id', '')}::{cp.get('id', '')}"


def _ask_item(jev, state: dict, matches: list[tuple[dict, dict, list[str]]]):
    """一次請求問完這則新聞命中的所有查核點；回 (resp, qmap)，resp 是 jev.ask 的回應或 None。"""
    questions, qmap = {}, {}
    for idea, cp, _hits in matches:
        qkey = _question_key(idea, cp)
        questions[qkey] = build_idea_question(idea, cp)
        qmap[qkey] = (idea, cp)
    resp = jev.ask(state, questions) if jev is not None else None
    return resp, qmap


def _first_url(item: dict) -> str:
    for s in item.get("sources") or []:
        if s.get("url"):
            return s["url"]
    return ""


def _hit_row(today: str, idea: dict, cp: dict, verdict: str, conf: float | None, it: dict, *,
            origin: str, by: str | None) -> dict:
    return {"date": today, "idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
           "verdict": verdict, "confidence": conf, "headline": it.get("headline", ""),
           "source": it.get("source", ""), "url": _first_url(it),
           "event_date": it.get("event_date", ""), "fact_key": it.get("fact_key"),
           "evidence_id": it.get("id", ""), "by": by, "origin": origin}


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
                   ideas: list[dict] | None = None, fetch=None, hits_fetch=None,
                   matcher=None, rss_items: list[dict] | None = None, ledger=None) -> dict:
    """就地在 items 的每一則加上 `ideas` 欄位（沒比對到就是空清單；早報外的候選不會出現在
    items 裡，見檔頭②）。回一份摘要：
    {"status", "ideas_count", "matched_pairs", "asked", "catalog", "hits", "wide_scan", "wide_pairs"}。

    ideas：直接給定就跳過載入（測試注入用）；fetch：抓 ideas.json／idea_hits.json 的函式
    （跟 evidence_layer._fetch_json 同形狀）；hits_fetch：抓 idea_hits.json 用，預設跟 fetch
    同一個；matcher：evidence_ledger.EntityMatcher，早報外掃描要用來辨識公司／主題；
    rss_items：main.py 傳進 run_evidence_layer 的去重後新聞池（早報外掃描的候選來源）；
    ledger：evidence_ledger.Ledger，早報外掃描要查「先前紀錄有沒有同公司／主題＋同數字」。
    matcher／ledger 任一沒給就跳過早報外掃描（測試裡只測早報候選時常見；早報正式流程一律會給）。"""
    fetch = fetch or (lambda url, timeout=15: (None, "missing"))
    hits_fetch = hits_fetch or fetch
    rss_items = rss_items or []

    for it in items:
        it["ideas"] = []

    if ideas is None:
        ideas, ideas_status = load_ideas(fetch)
    else:
        ideas_status = "ok"

    today_rows: list[dict] = []
    wide_pairs: list[dict] = []
    wide_stats = {"pool_size": len(rss_items), "already_in_candidates": 0, "chinese_count": 0,
                 "matched_items": 0, "skipped_by_reason": {}, "asked_items": 0}
    briefing_matched_pairs = wide_matched_pairs = asked_briefing_count = 0

    if ideas_status == "ok" and ideas:
        # ① 早報候選：只比對這次判成「新事實」或「進度更新」的項目
        briefing_cands = []
        for it in items:
            if (it.get("classification") or {}).get("class") not in ("new_fact", "progress_update"):
                continue
            cand = cand_by_id.get(it["id"])
            if not cand:
                continue
            company_keys = [c["key"] for c in it.get("companies") or []]
            confirmed_themes = [t["key"] for t in (it.get("routes") or {}).get("themes") or []]
            matches = match_checkpoints(cand["text"], company_keys, confirmed_themes, ideas)
            if not matches:
                continue
            date_str = it.get("event_date") or it.get("source_date") or today
            briefing_cands.append({"it": it, "cand": cand, "matches": matches, "company_keys": company_keys,
                                   "text": cand["text"], "days_ago": _days_between(today, date_str[:10])})
        briefing_matched_pairs = sum(len(c["matches"]) for c in briefing_cands)
        asked_briefing, overflow_briefing = _rank_and_cap(briefing_cands, MAX_BRIEFING_IDEA_ITEMS)
        asked_briefing_count = len(asked_briefing)

        for c in overflow_briefing:   # 額滿：比對到了，但沒被排進 Jev 名額，記一筆 unjudged 不猜
            for idea, cp, _hits in c["matches"]:
                c["it"]["ideas"].append({"idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                                         "label": cp.get("label", ""), "verdict": "unjudged", "confidence": None})
                today_rows.append(_hit_row(today, idea, cp, "unjudged", None, c["it"], origin="briefing", by=None))

        for c in asked_briefing:
            it, cand = c["it"], c["cand"]
            state = _build_item_state(cand["headline"], cand.get("source_date", ""), cand.get("source", ""),
                                      cand["text"], cand.get("full_text_excerpt"))
            resp, qmap = _ask_item(jev, state, c["matches"])
            for qkey, (idea, cp) in qmap.items():
                if resp:
                    ans = interpret_choice(resp["answers"], qkey)
                    verdict, conf, by = ans["label"], ans["confidence"], resp.get("model")
                else:
                    verdict, conf, by = "unjudged", None, None
                # summary：cand["text"] 去掉開頭的標題那段，跟 evidence_layer.py 組 ledger
                # rec["detail"] 同一個切法，只是留短一點（240 字）；給週度校準的 Sonnet 二次意見
                # 當材料用（見 evidence_calibration.py「投資想法校準」段），不是全文，早報的自產
                # 摘要本來就已經在公開頁面上（news.html 各處），沒有新的版權疑慮。
                summary = cand["text"][len(cand.get("headline", "")):].strip()[:240]
                it["ideas"].append({"idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                                    "label": cp.get("label", ""), "verdict": verdict, "confidence": conf,
                                    "summary": summary})
                if verdict != "unrelated":   # 無關的不進累加檔；留在當天 item["ideas"] 供校準
                    today_rows.append(_hit_row(today, idea, cp, verdict, conf, it, origin="briefing", by=by))

        # ② 早報外掃描：只有給了 matcher／ledger 才跑（早報正式流程一律會給，見上方參數註解）
        if matcher is not None and ledger is not None:
            hist_rows = _load_hits_rows(hits_fetch)
            wide_cands, scan_stats = _wide_scan(rss_items, cand_by_id, matcher, ledger, ideas, today, hist_rows)
            wide_matched_pairs = sum(len(c["matches"]) for c in wide_cands)
            asked_wide, _overflow_wide = _rank_and_cap(wide_cands, MAX_WIDE_IDEA_ITEMS)
            scan_stats["asked_items"] = len(asked_wide)
            wide_stats = scan_stats

            for c in asked_wide:
                state = _build_item_state(c["headline"], c.get("published", ""), c.get("source", ""), c["text"])
                resp, qmap = _ask_item(jev, state, c["matches"])
                if not resp:   # 早報外的候選本來就多，問不到就不記錄（不硬記 unjudged 洗版）
                    continue
                for qkey, (idea, cp) in qmap.items():
                    ans = interpret_choice(resp["answers"], qkey)
                    verdict, conf = ans["label"], ans["confidence"]
                    wide_pairs.append({"idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                                       "label": cp.get("label", ""), "verdict": verdict, "confidence": conf,
                                       "headline": c["headline"], "summary": c.get("summary", "")[:240],
                                       "source": c.get("source", ""), "url": c.get("url", "")})
                    if verdict != "unrelated":
                        fk = ledger_fact_key(list(c["company_keys"]), extract_figures(c["text"]),
                                             matcher.terms(c["text"]), c["headline"])
                        today_rows.append({
                            "date": today, "idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                            "verdict": verdict, "confidence": conf, "headline": c["headline"],
                            "source": c.get("source", ""), "url": c.get("url", ""),
                            "event_date": (c.get("published") or "")[:10], "fact_key": fk,
                            "evidence_id": "wide_" + fk[-12:], "by": resp.get("model"),
                            "origin": "wide", "evidence_basis": "headline_summary",
                        })

    hits = _merge_hits(hits_fetch, today, today_rows)
    return {"status": ideas_status, "reason": "" if ideas_status == "ok" else "ideas.json not available",
           "ideas_count": len(ideas or []), "matched_pairs": briefing_matched_pairs + wide_matched_pairs,
           "asked": asked_briefing_count + wide_stats["asked_items"], "catalog": _catalog(ideas or []),
           "hits": hits, "wide_scan": wide_stats, "wide_pairs": wide_pairs}
