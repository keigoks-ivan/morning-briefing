"""
ideas_layer.py
--------------
事件判斷層的延伸：投資想法／查核點（idea checkpoints）。2026-09-23 新增，2026-09-23 晚擴充
「早報外掃描」與逐項批次問法；2026-09-24 第二次改版（owner 決定，同日）：候選判斷從「隔天
05:15 深度查核」改成「同一次早報執行內，用 Claude Opus 走訂閱 CLI 讀原文直接判斷」——程式已經
找到候選、也抓得到原文，不必等隔天；Jev 完全退出這一層（Jev 仍用在事件判斷層本體的新舊／
階段／變數等窄問題，不受影響）。

背景：想法定義（每個想法底下的查核點，含 companies／keywords／themes／supports_if／
refutes_if／可選的 due）另外維護在 financial-analysis-bot，發布在
https://research.investmquest.com/ideas/ideas.json（本機開發讀 IDEAS_JSON_PATH，見
CLAUDE.md「投資想法」段）。

這一層做三件事：
① 早報候選（事件判斷層已經判成「新事實」或「進度更新」的項目，跟能進 top 的分類同一組）：
   比對到查核點（程式規則，不問任何模型，見 match_checkpoints），依「公司命中→關鍵詞數→
   新舊」排序，每天最多 MAX_BRIEFING_IDEA_ITEMS 則新聞；超過的記一筆 dropped_by_cap，不當
   candidate（沒有 Jev 年代「entered unjudged」那種佔位列了，因為判斷不再論則計費）。
② 早報之外的新聞（去重後的完整池子＋沒進候選名額的既有新聞卡＋sitemap 全部近期項目）：
   同樣的比對規則，把關（過舊、ledger 已知數字、idea_hits 歷史重複、跟早報候選標題近似）不
   變，每天最多 MAX_WIDE_IDEA_ITEMS 則。
③ 判斷（2026-09-24 新設計，取代 Jev）：①②選出的候選（依新聞分組，一則新聞命中幾個查核點
   就在同一筆列出幾個 checkpoints）抓原文（evidence_fulltext，≤MAX_BODY_CHARS 字，抓不到就
   用「(headline and summary only)」代替，basis 標 headline_summary），組成一個 payload，
   一次（總字數過大就切成幾批，見 _split_into_batches）呼叫 Claude Code CLI
   （briefing/ai_processor._call_claude_code，跟 News／Analysis 同一條訂閱路徑，只是換成
   claude-opus-5-5、不開思考），一次問完當天全部候選的全部查核點，回
   supports／refutes／shaky／neutral／unrelated＋≤60 字中文理由。任一批 CLI 掛掉、逾時、
   JSON 解不開：那一批涵蓋的候選全部退回 verdict="candidate"（可能相關，灰色），不猜、
   不另外重試（_call_claude_code 內部自己已經重試 3 次）。

失效保護：呼叫端（evidence_layer.run_evidence_layer）把整個 run_ideas_step() 包在自己的
try/except 裡；這一層出錯只讓 `ideas` 標 unavailable，不影響事件判斷層其餘輸出。同一天重跑：
idea_hits.json 裡今天的列會被整批換掉（冪等），不是疊加。

unrelated 的處理（2026-09-24 版規則，不能鬆）：verdict="unrelated" 的列不進 idea_hits.json
累加檔（跟舊版一致），但留在當天的 evidence JSON 裡供週度校準用——早報候選留在
item["ideas"]，早報外的留在 `ideas.wide_pairs`（只給 evidence_calibration.py 讀，news 頁不
直接渲染這份，渲染走 idea_hits.json）。

版權規則：full text 只在這次執行的記憶體裡用（給 Claude 判斷），絕不寫進任何輸出檔——跟
evidence_fulltext.py／evidence_layer.build_state 同一條規則。reason_zh（Claude 生成的中文
理由）本身是安全的衍生摘要，不是全文，可以寫進輸出檔／畫面。

注意：`_near_same_headline`／`_normalize_title_key`／`_title_tokens` 是刻意跟
`news_fetcher._near_same_title` 同一套演算法（同樣的正規化與 Jaccard 門檻）另外抄一份，不是
直接 import news_fetcher——news_fetcher.py 掛了 feedparser／requests 等重依賴，這一層被
evidence_layer.py 在模組層級 import，早報以外的測試環境（例如沒裝 feedparser 的
`python3.12 -m pytest`）import 到就會整包炸掉。normalize_url 沒有這個問題（source_registry.py
只用 re／urllib），直接 import。ai_processor.py（判斷步驟用的 Claude CLI helper）掛了
anthropic／google-genai 兩個 SDK，同樣的理由只在真的要呼叫時才 import（見
_default_judge_call），測試一律注入假的 judge_call，不會走到那一行。
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
from evidence_fulltext import fetch_fulltext
from evidence_routing import _keyword_hits
from source_registry import normalize_url

IDEAS_URL = "https://research.investmquest.com/ideas/ideas.json"
RESEARCH_URL = "https://research.investmquest.com/ideas/data/research.json"
HITS_URL = "https://research.investmquest.com/briefing/data/idea_hits.json"
HITS_SCHEMA = "idea-hits-v1"
HITS_WINDOW_DAYS = 365   # idea_hits.json 只留最近這麼多天
MAX_BRIEFING_IDEA_ITEMS = 12   # 每天最多幾則早報候選新聞（2026-09-24：8→12，判斷不再論則計費）
MAX_WIDE_IDEA_ITEMS = 20       # 每天最多幾則「早報外」新聞（2026-09-24：8→20）
STALE_WIDE_DAYS = 3   # 跟 evidence_layer.STALE_EVENT_DAYS 一致：早報外新聞比這個天數更舊就不問

# ── 判斷步驟（2026-09-24 新增，取代 Jev） ───────────────────────────────────
CLAUDE_JUDGE_MODEL = "claude-opus-5-5"   # owner 指定：走訂閱，不省
CLAUDE_JUDGE_LABEL = "IdeaJudge"
CLAUDE_JUDGE_BY = "claude-opus-5-5 (subscription CLI)"
CLAUDE_JUDGE_TIMEOUT = int(os.environ.get("IDEA_JUDGE_TIMEOUT", "300"))   # 秒／批
MAX_BODY_CHARS = 4000       # 每則候選給 Claude 看的原文上限
MAX_BATCH_CHARS = 120_000   # 單批 payload 粗估字數上限，超過切成下一批
JUDGE_VERDICTS = {"supports", "refutes", "shaky", "neutral", "unrelated"}

_JUDGE_GUARD = """
[EXECUTION ENVIRONMENT] You are inside an unattended morning briefing pipeline. Nobody will reply to you.
- Output exactly one valid JSON object, from `{` to `}`, with no preamble, heading, or markdown code fence.
- Do not use any tools. Do not browse. Judge only from the material given in this message.
- If material is genuinely too thin to judge, answer "unrelated" for that row rather than guessing.
"""

_JUDGE_SYSTEM_PROMPT = """You are checking today's news against a set of investment checkpoints for a \
systematic investor. `items` is a JSON array; each item is one news candidate with a `body` (or, when \
unavailable, the literal string "(headline and summary only)", in which case judge from `headline` and \
`summary` instead) and a list of `checkpoints` it was keyword-matched to. For every (item, checkpoint) \
pair, judge only what the material states as fact and decide whether it SUPPORTS, REFUTES, is SHAKY on, \
is NEUTRAL to, or is UNRELATED to that checkpoint (`supports_if` / `refutes_if` on each checkpoint \
describe what would count as each direction).

RULES:
- A single data point with no stated trend or guidance change is at most "neutral", never "supports" or "refutes".
- A price cut on an older-generation product is not evidence for a checkpoint about current-generation pricing.
- Ad-revenue growth counts as evidence for an AI-agent checkpoint only when the article explicitly attributes \
that revenue to AI agents.
- A newly launched product or app's post-launch usage decline does not by itself count as evidence.
- Use only numbers and facts present in the given material; never recall outside knowledge or invent a number.
- A keyword match is not evidence: if the checkpoint is not actually what the article is about, answer "unrelated".

For every row also write `reason_zh`: at most 60 Traditional Chinese characters, plain spoken register (not a \
translated English sentence), full-width punctuation (，。), citing the one key number or fact behind the \
verdict. Never write hedges such as 值得注意的是 or 這代表; state the fact plainly. Even an "unrelated" row \
gets a short reason_zh.
""" + _JUDGE_GUARD + """
Output exactly one JSON object, no other text:
{"verdicts": [{"id": "<item id>", "idea": "<idea id>", "checkpoint": "<checkpoint id>", \
"verdict": "supports|refutes|shaky|neutral|unrelated", "reason_zh": "..."}, ...]}
Every checkpoint listed for every item needs exactly one row in `verdicts`.
"""


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


def load_research(fetch) -> tuple[dict | None, str]:
    """載入 docs/ideas/data/research.json（另一個雲端 routine idea-watch-auto，每天 05:15 台北，
    見 financial-analysis-bot `.claude/skills/idea-watch/SKILL.md`，對每個查核點做主動搜尋／
    到期事件讀財報的「深入查核」，寫每個查核點目前的 supports／shaky／refutes／no_data 狀態＋
    逐則證據＋當天狀態變化）。跟本層 2026-09-24 改版後同一次執行內的判斷是兩件獨立的事：這份
    是另一條 routine 事後、更花時間的查核，供 evidence_calibration.py 當可選的交叉比對參考
    （見該檔「候選判斷交叉比對」段），不影響 idea_hits.json 那條主鏈路。載入慣例跟 load_ideas
    一樣：env IDEA_RESEARCH_JSON_PATH（本機檔案，開發／測試用）→ fetch 站上網址 → 都沒有就
    整步跳過。回 (research_dict_or_None, status)；status："ok"／"unavailable"。這一層只負責把
    整份 research.json 原樣載回來，過濾「今天」與排序留給 html_template.py 的渲染函式。"""
    local = os.environ.get("IDEA_RESEARCH_JSON_PATH")
    if local:
        try:
            payload = json.loads(Path(local).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, "unavailable"
        return payload, "ok"
    payload, status = fetch(RESEARCH_URL)
    if status == "ok" and isinstance(payload, dict):
        return payload, "ok"
    return None, "unavailable"


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
    """text：候選的 headline+summary（cand["text"]；不含全文，全文只給判斷步驟，見
    _build_judge_entries）。company_keys：這則候選比對到的所有公司 key（不分角色，跟判斷步驟
    payload 裡的候選公司是同一份清單）。confirmed_themes：這則已經被既有主題派送
    （evidence_routing.route）確認的研究主題 key（早報外掃描沒有跑 route()，一律傳空清單，見
    _wide_scan）。

    規則（見 CLAUDE.md「投資想法」段）：
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
    """跟 match_checkpoints 的規則 (a) 同一個條件，只用來給候選排序／回報比對到的規則用，不
    重造比對結果本身——match_checkpoints 才是唯一的比對權威，這支不重造規則，只是另外問一次
    同樣的問題。"""
    keys = set(company_keys or [])
    return bool(keys & set(checkpoint.get("companies") or [])) or bool(
        _keyword_hits(text, checkpoint.get("company_names") or []))


def _match_rule(text: str, company_keys, confirmed_themes, checkpoint: dict, hits: list[str]) -> str:
    """給輸出的 `rule` 欄位用：依 match_checkpoints 同一套規則優先序，回報這次命中主要是靠
    哪一條——一則新聞可能同時滿足多條，只回報最具體的那條（公司命中 > 兩個關鍵詞 > 片語 >
    主題＋關鍵詞）。不重造比對邏輯，只是重新問一次同樣的條件（跟 _rule_a_hit 同精神）。"""
    if _rule_a_hit(text, company_keys, checkpoint):
        return "company+keyword"
    stems = {h.lower().rstrip("s") for h in hits}
    if len(stems) >= 2:
        return "two keywords"
    if any(len(h.split()) >= 3 for h in hits):
        return "phrase"
    if set(confirmed_themes or []) & set(checkpoint.get("themes") or []):
        return "theme+keyword"
    return "keyword"   # 理論上到不了這裡：match_checkpoints 已經要求 rule_a 或 rule_b 其中一個成立


def _item_rank_key(text: str, company_keys, matches: list[tuple[dict, dict, list[str]]], days_ago: int | None) -> tuple:
    """排序：規則 (a) 公司命中優先 → 不同關鍵詞數（跨所有命中的查核點合計，單複數視為同一個）→
    越新越前面。用在早報候選與早報外候選各自排序取前 N（兩組分開排，不混排），見 run_ideas_step。"""
    company_match = any(_rule_a_hit(text, company_keys, cp) for _, cp, _ in matches)
    distinct_kw = len({h.lower().rstrip("s") for _, _, hits in matches for h in hits})
    return (0 if company_match else 1, -distinct_kw, days_ago if days_ago is not None else 9_999)


def _rank_and_cap(candidates: list[dict], cap: int) -> tuple[list[dict], list[dict]]:
    """candidates 裡每筆要有 text／company_keys／matches／days_ago 四個 key（多的欄位不管）。
    回 (進了名額的, 額滿沒進去的)，都依 _item_rank_key 排好序。"""
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
    """給早報外掃描的「同網址／同標題已經問過」把關用；抓不到就當作沒有歷史可比對(保守：
    寧可少擋一次重複，也不假裝知道歷史內容——真正的合併／history 狀態仍由 _merge_hits 負責。"""
    try:
        payload, status = hits_fetch(HITS_URL)
    except Exception:  # noqa: BLE001
        return []
    if status == "ok" and isinstance(payload, dict):
        return list(payload.get("hits") or [])
    return []


def _curated_card_as_pool_item(card: dict) -> dict:
    """把一張既有新聞卡（tech_trends／world_news／frontier_tech…，evidence_layer 已經排除
    掉變成早報候選的）轉成跟 RSS 條目同樣的形狀，好併進 _wide_scan 同一個迴圈、重用全部既有
    把關。沒有 link／url：url_norm 會是空字串，命中不到 used_urls／hits_history 的網址比對，
    但標題比對照常吃得到。published 直接用 source_date——早報的卡一律是 YYYY-MM-DD，跟 RSS
    的 published 一樣可以餵給 _days_between。"""
    return {
        "title": str(card.get("headline") or card.get("title") or "").strip(),
        "summary": str(card.get("body") or card.get("summary") or ""),
        "link": "", "source": str(card.get("source") or ""),
        "published": str(card.get("source_date") or ""),
    }


def _wide_scan(rss_items: list[dict], cand_by_id: dict, matcher, ledger, ideas: list[dict],
              today: str, hits_history_rows: list[dict], curated_cards: list[dict] | None = None,
              sitemap_items: list[dict] | None = None) -> tuple[list[dict], dict]:
    """早報外掃描（見檔頭②）。rss_items：main.py 傳進 run_evidence_layer 的去重後完整新聞池。
    cand_by_id：事件判斷層自己的候選，用來排除池子裡已經被早報用掉的新聞、以及近似標題比對的
    基準。curated_cards：evidence_layer.run_evidence_layer 算好的「沒進候選名額的既有新聞卡」。
    sitemap_items：sitemap_source.to_pool_items() 算好的「全部近期 sitemap 項目」，已經是 RSS
    條目形狀，link 是真實網址。

    回 (candidates, stats)。candidates 是通過全部把關、可以拿去判斷的（每筆有
    headline／text／source／url／published／days_ago／matches／company_keys）；stats 是
    pool_size／curated_pool_size／already_in_candidates／chinese_count／matched_items／
    skipped_by_reason，寫進當天 evidence JSON 的 ideas.wide_scan。"""
    used_urls = _briefing_used_urls(cand_by_id)
    briefing_headlines = _briefing_headlines(cand_by_id)
    hist_urls = {normalize_url(r["url"]) for r in hits_history_rows if r.get("url")}
    hist_titles = {_normalize_title_key(r["headline"]) for r in hits_history_rows if r.get("headline")}

    curated_cards = curated_cards or []
    sitemap_items = sitemap_items or []
    pool = list(rss_items or []) + [_curated_card_as_pool_item(c) for c in curated_cards] + list(sitemap_items)
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
            chinese += 1   # 英文關鍵詞比對本來就配不到，這裡只是報數，不另外做中文比對

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
            # 共享公司／主題「而且」共享數字，當作已經記過，不再問
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

    stats = {"pool_size": len(pool), "curated_pool_size": len(curated_cards),
             "sitemap_pool_size": len(sitemap_items), "already_in_candidates": already,
             "chinese_count": chinese, "matched_items": matched_items, "skipped_by_reason": skipped,
             "kept_items": 0, "dropped_by_cap": 0}
    return candidates, stats


# ── 判斷步驟（2026-09-24 新增）：抓原文 → 組 payload → 呼叫 Claude Opus CLI ──────────────
def _split_into_batches(entries: list[dict], max_chars: int = MAX_BATCH_CHARS) -> list[list[dict]]:
    """粗估每筆 entry 的 JSON 字數（不重算 token，這裡只是切批用），累計超過 max_chars 就切下
    一批；單筆超過 max_chars 也自成一批（不會憑空消失）。"""
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for e in entries:
        size = len(json.dumps(e, ensure_ascii=False))
        if current and current_chars + size > max_chars:
            batches.append(current)
            current, current_chars = [], 0
        current.append(e)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _default_judge_call(system_prompt: str, user_prompt: str) -> dict:
    """真的呼叫 Claude Code CLI（跟 News／Analysis 同一條訂閱路徑，briefing/ai_processor.py）。
    ai_processor.py 掛了 anthropic／google-genai 兩個 SDK，只在真的要判斷時才 import，測試一律
    注入假的 judge_call，不會走到這裡（見檔頭）。"""
    from ai_processor import _call_claude_code
    return _call_claude_code(system_prompt, user_prompt, CLAUDE_JUDGE_LABEL, thinking_tokens=0,
                             model=CLAUDE_JUDGE_MODEL, timeout=CLAUDE_JUDGE_TIMEOUT)


def _judge_candidates(entries: list[dict], *, judge_call) -> dict[tuple[str, str, str], dict]:
    """entries：每則候選一筆（見 _build_judge_entries），內含 checkpoints 清單。總字數過大就切
    成幾批（_split_into_batches），每批各自呼叫一次 judge_call。回
    {(item_id, idea_id, checkpoint_id): {"verdict", "reason_zh"}}——任何一批失敗（CLI 掛掉、
    逾時、JSON 解不開、回應形狀不對），那一批涵蓋的 (item, checkpoint) 全部不會出現在回傳值
    裡，呼叫端沒拿到的一律退回 verdict="candidate"，不猜、不重試（見 run_ideas_step）。"""
    out: dict[tuple[str, str, str], dict] = {}
    if not entries:
        return out
    for batch in _split_into_batches(entries):
        user_prompt = json.dumps({"items": batch}, ensure_ascii=False)
        try:
            resp = judge_call(_JUDGE_SYSTEM_PROMPT, user_prompt)
        except Exception:  # noqa: BLE001 — 這批判斷失敗，涵蓋的 (item, checkpoint) 全部退回候選
            continue
        verdicts = resp.get("verdicts") if isinstance(resp, dict) else None
        if not isinstance(verdicts, list):
            continue
        for v in verdicts:
            if not isinstance(v, dict):
                continue
            item_id, idea_id, cp_id = v.get("id"), v.get("idea"), v.get("checkpoint")
            verdict = v.get("verdict")
            if not (item_id and idea_id and cp_id) or verdict not in JUDGE_VERDICTS:
                continue
            reason_zh = str(v.get("reason_zh") or "")[:120]
            out[(item_id, idea_id, cp_id)] = {"verdict": verdict, "reason_zh": reason_zh}
    return out


def _kept_context(kept_briefing: list[dict], kept_wide: list[dict]) -> dict:
    """把①②選出的候選（post-cap）統一成一份 {item_key: context} 字典，item_key 只在這次執行
    內用來把「抓原文」「組 payload」「判斷結果」三步串起來，不落地、不是 evidence_id。"""
    ctx: dict[str, dict] = {}
    for i, c in enumerate(kept_briefing):
        key = f"b{i}"
        cand, it = c["cand"], c["it"]
        ctx[key] = {
            "origin": "briefing", "it": it, "headline": cand.get("headline", ""),
            "source": cand.get("source", ""), "url": _first_url(it),
            "date": cand.get("source_date", "") or it.get("event_date", ""),
            "summary": cand["text"][len(cand.get("headline", "")):].strip()[:400],
            "text": c["text"], "matches": c["matches"], "company_keys": c["company_keys"],
            "confirmed_themes": c.get("confirmed_themes", []),
            "rss": cand.get("rss") or [], "headline_figures": cand.get("headline_figures") or [],
        }
    for i, c in enumerate(kept_wide):
        key = f"w{i}"
        url = c.get("url", "")
        ctx[key] = {
            "origin": "wide", "headline": c.get("headline", ""), "source": c.get("source", ""),
            "url": url, "date": (c.get("published") or "")[:10], "summary": c.get("summary", "")[:400],
            "text": c["text"], "matches": c["matches"], "company_keys": c["company_keys"],
            "confirmed_themes": [],
            "rss": [{"url": url}] if url else [], "headline_figures": extract_figures(c.get("headline", "")),
        }
    return ctx


def _build_judge_entries(ctx: dict, fulltext: dict) -> tuple[list[dict], dict[str, str]]:
    """回 (entries 給 _judge_candidates 用, {item_key: basis})。basis 是程式自己判斷的（抓到
    全文就是 full_article，抓不到就是 headline_summary），不信任模型自己回報，避免模型亂寫。"""
    entries, basis_map = [], {}
    for key, v in ctx.items():
        ft = fulltext.get(key) or {"status": "not_attempted"}
        if ft.get("status") == "ok" and ft.get("excerpt"):
            body = ft["excerpt"][:MAX_BODY_CHARS]
            basis_map[key] = "full_article"
        else:
            body = "(headline and summary only)"
            basis_map[key] = "headline_summary"
        checkpoints = [{
            "idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
            "idea_label": idea.get("short") or idea.get("title") or idea.get("id", ""),
            "checkpoint_label": cp.get("label", ""),
            "supports_if": cp.get("supports_if", ""), "refutes_if": cp.get("refutes_if", ""),
        } for idea, cp, _hits in v["matches"]]
        entries.append({"id": key, "headline": v["headline"], "summary": v["summary"],
                        "source": v["source"], "url": v["url"], "date": v["date"],
                        "body": body, "checkpoints": checkpoints})
    return entries, basis_map


def _fetch_fulltext_for(ctx: dict, full_text_fetch) -> dict[str, dict]:
    """把①②選出的候選全部交給 full_text_fetch（不先濾掉沒有網址的——evidence_fulltext.fetch_fulltext
    本來就會把沒有網址的候選標 no_url，這裡不用重造這條判斷）。"""
    if not ctx:
        return {}
    cands = [{"cid": key, "rss": v["rss"], "headline": v["headline"], "headline_figures": v["headline_figures"]}
            for key, v in ctx.items()]
    return full_text_fetch(cands, max_candidates=len(cands))


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
def run_ideas_step(items: list[dict], cand_by_id: dict, today: str, *,
                   ideas: list[dict] | None = None, fetch=None, hits_fetch=None,
                   matcher=None, rss_items: list[dict] | None = None, ledger=None,
                   curated_cards: list[dict] | None = None,
                   sitemap_items: list[dict] | None = None,
                   full_text_fetch=None, judge_call=None) -> dict:
    """就地在 items 的每一則加上 `ideas` 欄位（沒比對到就是空清單；早報外的候選不會出現在
    items 裡，見檔頭②）。回一份摘要：
    {"status", "ideas_count", "matched_pairs", "kept", "dropped_by_cap", "catalog", "hits",
     "wide_scan", "wide_pairs"}。

    ideas：直接給定就跳過載入（測試注入用）；fetch：抓 ideas.json／idea_hits.json 的函式
    （跟 evidence_layer._fetch_json 同形狀）；hits_fetch：抓 idea_hits.json 用，預設跟 fetch
    同一個；matcher：evidence_ledger.EntityMatcher，早報外掃描要用來辨識公司／主題；
    rss_items：main.py 傳進 run_evidence_layer 的去重後新聞池（早報外掃描的候選來源）；
    ledger：evidence_ledger.Ledger，早報外掃描要查「先前紀錄有沒有同公司／主題＋同數字」；
    curated_cards／sitemap_items：見 _wide_scan 的參數說明。
    full_text_fetch：抓候選原文的函式（跟 evidence_fulltext.fetch_fulltext 同形狀），預設就是
    那支；judge_call：真的做判斷的函式 (system_prompt, user_prompt) -> dict，預設
    _default_judge_call（真的打 Claude CLI），測試一律注入假的。
    matcher／ledger 任一沒給就跳過早報外掃描（測試裡只測早報候選時常見；早報正式流程一律會給）。"""
    fetch = fetch or (lambda url, timeout=15: (None, "missing"))
    hits_fetch = hits_fetch or fetch
    full_text_fetch = full_text_fetch or fetch_fulltext
    judge_call = judge_call or _default_judge_call
    rss_items = rss_items or []
    curated_cards = curated_cards or []
    sitemap_items = sitemap_items or []

    for it in items:
        it["ideas"] = []

    if ideas is None:
        ideas, ideas_status = load_ideas(fetch)
    else:
        ideas_status = "ok"

    today_rows: list[dict] = []
    wide_pairs: list[dict] = []
    wide_stats = {"pool_size": len(rss_items) + len(curated_cards) + len(sitemap_items),
                 "curated_pool_size": len(curated_cards), "sitemap_pool_size": len(sitemap_items),
                 "already_in_candidates": 0, "chinese_count": 0,
                 "matched_items": 0, "skipped_by_reason": {}, "kept_items": 0, "dropped_by_cap": 0}
    briefing_matched_pairs = wide_matched_pairs = 0
    kept_briefing_count = dropped_briefing_pairs = 0

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
                                   "confirmed_themes": confirmed_themes,
                                   "text": cand["text"], "days_ago": _days_between(today, date_str[:10])})
        briefing_matched_pairs = sum(len(c["matches"]) for c in briefing_cands)
        kept_briefing, overflow_briefing = _rank_and_cap(briefing_cands, MAX_BRIEFING_IDEA_ITEMS)
        kept_briefing_count = len(kept_briefing)
        dropped_briefing_pairs = sum(len(c["matches"]) for c in overflow_briefing)

        # ② 早報外掃描：只有給了 matcher／ledger 才跑（早報正式流程一律會給，見上方參數註解）
        kept_wide: list[dict] = []
        if matcher is not None and ledger is not None:
            hist_rows = _load_hits_rows(hits_fetch)
            wide_cands, scan_stats = _wide_scan(rss_items, cand_by_id, matcher, ledger, ideas, today, hist_rows,
                                               curated_cards=curated_cards, sitemap_items=sitemap_items)
            wide_matched_pairs = sum(len(c["matches"]) for c in wide_cands)
            kept_wide, overflow_wide = _rank_and_cap(wide_cands, MAX_WIDE_IDEA_ITEMS)
            scan_stats["kept_items"] = len(kept_wide)
            scan_stats["dropped_by_cap"] = sum(len(c["matches"]) for c in overflow_wide)
            wide_stats = scan_stats

        # ③ 判斷：抓原文 → 組 payload → 呼叫 Claude Opus CLI（一批或幾批）
        ctx = _kept_context(kept_briefing, kept_wide)
        if ctx:
            fulltext = _fetch_fulltext_for(ctx, full_text_fetch)
            entries, basis_map = _build_judge_entries(ctx, fulltext)
            verdict_map = _judge_candidates(entries, judge_call=judge_call)

            for key, v in ctx.items():
                basis = basis_map.get(key, "headline_summary")
                for idea, cp, hits in v["matches"]:
                    rule = _match_rule(v["text"], v["company_keys"], v["confirmed_themes"], cp, hits)
                    got = verdict_map.get((key, idea.get("id", ""), cp.get("id", "")))
                    if got:
                        verdict, reason_zh, by = got["verdict"], got["reason_zh"], CLAUDE_JUDGE_BY
                    else:
                        verdict, reason_zh, by = "candidate", "", None
                    row = {"idea": idea.get("id", ""), "checkpoint": cp.get("id", ""),
                          "label": cp.get("label", ""), "verdict": verdict,
                          "matched_keywords": hits, "rule": rule, "reason_zh": reason_zh, "basis": basis}

                    if v["origin"] == "briefing":
                        v["it"]["ideas"].append(dict(row))
                        if verdict != "unrelated":
                            today_rows.append({
                                "date": today, **row,
                                "headline": v["it"].get("headline", ""), "source": v["it"].get("source", ""),
                                "url": _first_url(v["it"]), "event_date": v["it"].get("event_date", ""),
                                "fact_key": v["it"].get("fact_key"), "evidence_id": v["it"].get("id", ""),
                                "origin": "briefing", "by": by, "summary": v["summary"][:240],
                            })
                    else:
                        wide_pairs.append({**row, "headline": v["headline"], "summary": v["summary"][:240],
                                          "source": v["source"], "url": v["url"]})
                        if verdict != "unrelated":
                            fk = ledger_fact_key(list(v["company_keys"]), extract_figures(v["text"]),
                                                 matcher.terms(v["text"]) if matcher else [], v["headline"])
                            today_rows.append({
                                "date": today, **row,
                                "headline": v["headline"], "source": v["source"], "url": v["url"],
                                "event_date": v["date"], "fact_key": fk, "evidence_id": "wide_" + fk[-12:],
                                "origin": "wide", "by": by, "summary": v["summary"][:240],
                            })

    hits = _merge_hits(hits_fetch, today, today_rows)
    return {"status": ideas_status, "reason": "" if ideas_status == "ok" else "ideas.json not available",
           "ideas_count": len(ideas or []), "matched_pairs": briefing_matched_pairs + wide_matched_pairs,
           "kept": kept_briefing_count + wide_stats["kept_items"],
           "dropped_by_cap": dropped_briefing_pairs + wide_stats["dropped_by_cap"],
           "catalog": _catalog(ideas or []), "hits": hits, "wide_scan": wide_stats, "wide_pairs": wide_pairs}
