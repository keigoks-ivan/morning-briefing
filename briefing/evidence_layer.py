"""
evidence_layer.py
-----------------
早報的事件判斷層：新聞進來 → 相對於過去紀錄有沒有新證據 → 影響哪些經濟變數、怎麼傳導
→ 派給 DD／研究主題／持倉 → 交給 html_template 呈現。

在 process_news()（白名單、過期、行情句、跨區塊去重都做完）之後、產生 HTML 之前執行。

分工（2026-09-22 定，不要讓 Jev 越界）：
- 程式：挑候選（沿用去重後的新聞卡）、對回 RSS 原始條目拿 URL／發布時間、公司辨識、
  數字正規化與比對、日期、找先前紀錄、一手來源檢查、派送、「尚未證實」的護欄文字、
  冪等寫入、品質統計。
- Jev：只答預先定義選項的窄問題（evidence_questions.py）。
- Jev 不決定買賣、不改投資結論、不產生公司名與論述；分類信心是分類的把握，不是漲跌機率。

沒有 TYPESAFE_API_KEY、API 失敗、預算用完：早報照出，這一層標「未判斷」，不補假答案。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from evidence_fulltext import fetch_fulltext
from evidence_ledger import (
    EntityMatcher, Ledger, content_tokens, extract_event_date, extract_figures, fact_key, figure_label,
)
from evidence_questions import (
    ATTRIBUTION_DISPLAY, COMPANY_VAR_IDS, MACRO_VAR_IDS, NOVELTY_DISPLAY, STAGE_DISPLAY, TIMING_DISPLAY,
    VAR_LABEL, build_questions, interpret,
)
from evidence_routing import (
    PARTY_NO, PARTY_YES, _company_tickers, _keyword_hits, dd_index, load_routing, potential_impact,
    public_holdings_view, route, sec_check, segment_gaps,
)
from evidence_sources import OfficialSources, http_text
from ideas_layer import IDEA_ITEM_BUDGET
from jev_client import MODEL, JevClient, get_api_key

SCHEMA = "evidence-layer-v1"
SITE_DATA_URL = "https://research.investmquest.com/briefing/data"
SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "evidence_seed_ledger.json"

MAX_CANDIDATES = 30        # 每天最多判斷幾則（依區塊優先序）；2026-09-23：24→30，配合
                            # JevClient 預設每次執行 30 個請求上限，讓 GDELT 保留的名額都能被問到
GDELT_MAX_SLOTS = 8         # 早報自己的新聞卡填完 MAX_CANDIDATES-GDELT_MAX_SLOTS 個名額之後，
                            # 剩下的名額（最多 8 個）留給 GDELT 候選（2026-09-23）
TOP_SHOWN = 5              # 早報主區塊最多顯示幾則
NOVELTY_MIN_CONF = 0.60    # 新舊分類信心低於此 → 待複核
VAR_MIN_CONF = 0.50        # 變數判定信心低於此 → 不當成影響
INDIRECT_MIN_CONF = 0.70   # 間接影響門檻較高（2026-09-22 真 Jev 實測：間接很容易被標滿）
TIMING_MIN_CONF = 0.50     # timing 顯示門檻（2026-09-23）：低於此一律顯示「Timing unclear」，
                           # 原始 label 仍照實存放供之後校準，不因此改寫
MAX_COMPANIES_PER_ITEM = 5
STALE_EVENT_DAYS = 3       # 事件日期超過這麼多天才算「過舊」（規則 A，2026-09-23）
STALE_MATCH_WINDOW_DAYS = 2  # 過舊事件要跟先前紀錄的事件日期差在幾天內，才當成同一件事的重述

# 候選來源：去重後的新聞卡，依早報既有的優先序
BLOCK_PRIORITY = [
    ("top_stories", 1.0), ("industry_developments", 0.9), ("watchlist_news", 0.85),
    ("ai_industry", 0.7), ("macro", 0.6), ("regional_tech", 0.5), ("geopolitical", 0.4),
    ("gdelt", 0.2),   # 2026-09-23：GDELT 候選（早報既有 RSS 以外的公司專屬新聞），優先序最低
]
PRIMARY_DOMAINS = ("sec.gov", "federalreserve.gov", "fda.gov", "mops.twse.com.tw", "customs.go.kr",
                   "motie.go.kr", "pr.tsmc.com", "nvidianews.nvidia.com", "news.microsoft.com",
                   "ir.amd.com", "investor.", "dart.fss.or.kr")
PRIMARY_SOURCES = {"SEC", "Federal Reserve", "FDA", "ECB", "BOJ", "BIS", "IMF", "FRED"}
CAPACITY_TERMS = ("CoWoS", "CoPoS", "SoIC", "HBM", "wafer", "fab", "packaging", "production line")
_COMPUTE_RE = re.compile(r"\b(OpenAI|Anthropic|GPUs?|compute|data cent(?:er|re)s?|AI)\b")
_EQUITY_RE = re.compile(r"\b(stake|shares|equity|invest(?:s|ed|ment|ing)?)\b", re.I)
_NOTHING_OUTSTANDING = re.compile(r"nothing outstanding|none|n/?a", re.I)
_MARKET_IMPLIED_RE = re.compile(r"FedWatch|futures (?:imply|price|pricing)|market pricing|priced in|implied probability", re.I)
_TALKS_RE = re.compile(r"\b(talks?|negotiat\w*|summit|proposal|proposes?|dialogue|framework)\b", re.I)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── 候選 ─────────────────────────────────────────────────────────────────
def _card_text(card: dict) -> str:
    parts = [card.get("headline") or card.get("title") or "", card.get("body") or "",
             card.get("evidence") or "", card.get("market_move") or ""]
    return " ".join(str(p).strip() for p in parts if p).strip()


def collect_cards(data: dict) -> list[tuple[str, float, dict]]:
    out = []
    for block, prio in BLOCK_PRIORITY:
        items = data.get(block)
        if isinstance(items, dict):  # regional_tech
            items = [it for region in items.values() if isinstance(region, list) for it in region]
        for card in items or []:
            if isinstance(card, dict) and (card.get("headline") or card.get("title")):
                out.append((block, prio, card))
    return out


def _rss_index(rss_items: list[dict], matcher: EntityMatcher) -> list[dict]:
    out = []
    for it in rss_items or []:
        text = f"{it.get('title', '')}. {it.get('summary', '')}"
        out.append({
            "item": it,
            "companies": set(matcher.match(text)) | set(it.get("watch") or []),
            "tokens": content_tokens(text),
            "figures": set(extract_figures(text)),
        })
    return out


def _match_rss(cand_companies: set, cand_tokens: set, cand_figures: set, rss_idx: list[dict]) -> list[dict]:
    scored = []
    for r in rss_idx:
        shared_c = cand_companies & r["companies"]
        union = cand_tokens | r["tokens"]
        jac = len(cand_tokens & r["tokens"]) / len(union) if union else 0.0
        shared_f = cand_figures & r["figures"]
        if (shared_c and (jac >= 0.12 or shared_f)) or jac >= 0.3:
            scored.append((len(shared_f) * 0.3 + jac + 0.2 * len(shared_c), r["item"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:3]]


def _basis(card: dict, rss: list[dict]) -> dict:
    urls = [it.get("link", "") for it in rss if it.get("link")]
    if card.get("source") in PRIMARY_SOURCES or any(d in u for u in urls for d in PRIMARY_DOMAINS):
        return {"code": "primary_document", "display": "Primary document"}
    if rss:
        return {"code": "headline_summary", "display": "Headline and feed summary only, unverified"}
    return {"code": "briefing_summary_only", "display": "Briefing summary only, unverified"}


def build_candidates(data: dict, rss_items: list[dict], matcher: EntityMatcher, today: str,
                     max_n: int = MAX_CANDIDATES) -> list[dict]:
    rss_idx = _rss_index(rss_items, matcher)
    cands, seen_events = [], set()
    for block, prio, card in collect_cards(data):
        ev_id = card.get("event_id")
        if ev_id and ev_id in seen_events:
            continue
        if ev_id:
            seen_events.add(ev_id)
        headline = str(card.get("headline") or card.get("title") or "").strip()
        text = _card_text(card)
        companies = matcher.match(headline) + [c for c in matcher.match(text) if c not in matcher.match(headline)]
        if card.get("ticker"):
            companies.append(matcher.canonical(str(card["ticker"])))
        tokens = content_tokens(text)
        figures = extract_figures(text)
        rss = _match_rss(set(companies), tokens, set(figures), rss_idx)
        for it in rss:
            for t in it.get("watch") or []:
                companies.append(matcher.canonical(t))
        companies = list(dict.fromkeys(c for c in companies if c))[:MAX_COMPANIES_PER_ITEM]
        source_date = str(card.get("source_date") or "")
        date_info = extract_event_date(text, source_date or today) or {"event_date": source_date, "date_basis": "published"}
        published = sorted(it.get("published", "") for it in rss if it.get("published"))
        # 同一次執行裡，同公司＋共享數字＋用字相近的卡視為同一事件（例：頭條與關注清單各寫一次）：
        # 併入第一張的來源，不另問 Jev、不另寫紀錄
        twin = None
        subj = set(matcher.subjects(text))
        for prev in cands:
            union = tokens | prev["tokens"]
            jac = len(tokens & prev["tokens"]) / len(union) if union else 0.0
            if ((set(companies) & set(prev["companies"]) or subj & set(prev.get("subjects") or []))
                    and set(figures) & set(prev["figures"]) and jac >= 0.2):
                twin = prev
                break
        if twin is not None:
            twin["also_in"].append({"block": block, "headline": headline, "source": str(card.get("source") or "")})
            continue
        cid = "c_" + hashlib.sha1(f"{today}|{re.sub(r'[^a-z0-9]+', ' ', headline.lower()).strip()}".encode()).hexdigest()[:12]
        subjects = matcher.subjects(text)
        cands.append({
            "also_in": [],
            "subjects": subjects,
            "cid": cid, "block": block, "priority": prio,
            "headline": headline, "text": text[:1400],
            "unknowns": str(card.get("unknowns") or "").strip(),
            "source": str(card.get("source") or ""), "source_date": source_date,
            "published_at": published[0] if published else "",
            **date_info,
            "companies": companies,
            "figures": figures, "headline_figures": extract_figures(headline),
            "terms": matcher.terms(text), "tokens": tokens,
            "rss": [{"source": it.get("source", ""), "title": it.get("title", ""), "summary": it.get("summary", ""),
                     "url": it.get("link", ""), "published": it.get("published", ""),
                     "also_in": it.get("alternate_sources") or []} for it in rss],
            "basis": _basis(card, rss),
        })
        if len(cands) >= max_n:
            break
    return cands


# ── Jev 請求 ─────────────────────────────────────────────────────────────
def _prior_brief(r: dict) -> dict:
    return {
        "date": r.get("event_date") or r.get("first_seen") or "",
        "outlet": ", ".join(sorted({s.get("source", "") for s in (r.get("sources") or []) if s.get("source")})) or r.get("origin", ""),
        "text": (str(r.get("claim") or "") + ". " + str(r.get("detail") or ""))[:420],
        "figures": ", ".join(figure_label(f) for f in (r.get("figures") or [])),
    }


def candidate_kind(cand: dict, routing: dict) -> str:
    """company：公司新聞；macro：總經（有總經主題、沒有公司也沒有產業環節）；mixed：兩者都有（兩組變數都問）。"""
    segs = [s for k, s in (routing.get("segments") or {}).items() if not k.startswith("_")]
    seg_hit = any(_keyword_hits(cand["text"], s.get("keywords") or []) for s in segs)
    if cand.get("subjects") and not cand["companies"] and not seg_hit:
        return "macro"
    if cand.get("subjects"):
        return "mixed"
    return "company"


def var_ids_for(kind: str) -> list[str]:
    if kind == "macro":
        return list(MACRO_VAR_IDS)
    if kind == "mixed":
        return COMPANY_VAR_IDS + [v for v in MACRO_VAR_IDS if v not in COMPANY_VAR_IDS]
    return list(COMPANY_VAR_IDS)


def build_state(cand: dict, priors: list[dict], matcher: EntityMatcher) -> dict:
    today = {
        "date": cand["source_date"], "outlet": cand["source"], "headline": cand["headline"],
        "report": cand["text"],
        "source_excerpts": [f"{r['title']}. {r['summary']}".strip() for r in cand["rss"]][:3],
    }
    # 2026-09-23：抓到全文時多給 Jev 一段全文摘要（見 evidence_fulltext.py）；只送給 Jev，
    # 不寫進任何輸出檔——jev_cache 只存 answers/usage，state 本身不落地。
    if cand.get("full_text_excerpt"):
        today["full_text"] = cand["full_text_excerpt"]
    return {
        "today": today,
        "prior_records": [_prior_brief(r) for r in priors],
        "candidate_companies": [matcher.name(k) for k in cand["companies"]],
    }


# ── 判斷規則（程式） ─────────────────────────────────────────────────────
def _day_gap(a: str, b: str) -> int | None:
    """a 減 b 差幾天（只取前 10 碼 YYYY-MM-DD）；算不出來回 None。2026-09-23 新增，供規則 A 用。"""
    try:
        return (datetime.strptime(a[:10], "%Y-%m-%d") - datetime.strptime(b[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


def _figure_overlap(cand: dict, priors: list[dict]) -> dict:
    """標題數字是否全部在先前紀錄出現過。回 {all_seen, seen: [(fig, date, outlet)]}。
    2026-09-23：只算「該筆先前紀錄也跟候選共享公司或主題」的數字，避免不相干事實只因巧合撞到同一個
    數字就被當成重述的證據（例：個股新聞裡的百分比／整數金額，撞到毫不相干總經公告的同一個數字）。"""
    cand_entities = set(cand["companies"]) | set(cand.get("subjects") or [])
    seen = []
    prior_figs = {}
    for r in priors:
        r_entities = set(r.get("companies") or []) | set(r.get("subjects") or [])
        if not (cand_entities & r_entities):
            continue
        for f in r.get("figures") or []:
            prior_figs.setdefault(f, r)
    key_figs = cand["headline_figures"] or []
    for f in key_figs:
        if f in prior_figs:
            r = prior_figs[f]
            seen.append({"figure": figure_label(f), "date": r.get("event_date") or r.get("first_seen", ""),
                         "outlet": _prior_brief(r)["outlet"]})
    return {"all_seen": bool(key_figs) and len(seen) == len(key_figs), "seen": seen}


def _stale_event_match(cand: dict, priors: list[dict], today: str) -> dict | None:
    """規則 A（2026-09-23）：候選的事件日期（不論 date_basis 是 stated 還是 published，見
    extract_event_date）比今天早超過 STALE_EVENT_DAYS 天，就算「過舊」；未來日期（差值為負，例如
    後天才開的高峰會）不算過舊，回 None。過舊時，priors 裡（已經跟候選共享公司或主題）只要有一筆事件
    日期落在候選事件日期 ±STALE_MATCH_WINDOW_DAYS 天內，代表這件事其實早就記過，回 {"prior": 那筆紀錄}；
    找不到就回 {"prior": None}，代表這麼舊的事件卻沒有先前紀錄，要送複核而不是直接放行。"""
    event_date = cand.get("event_date") or ""
    age = _day_gap(today, event_date)
    if age is None or age <= STALE_EVENT_DAYS:
        return None
    for r in priors:
        gap = _day_gap(event_date, r.get("event_date") or "")
        if gap is not None and abs(gap) <= STALE_MATCH_WINDOW_DAYS:
            return {"age": age, "prior": r}
    return {"age": age, "prior": None}


# 「追加／另一筆」字眼：同金額再出現時，可能是第二筆交易，不能由程式直接判成重述
_FOLLOW_ON_RE = re.compile(r"\b(additional|another|second|third|further|follow-on|top-up|tops? up|adds? \$?[\d.]+ ?\w* to)\b", re.I)


def decide(cand: dict, j: dict | None, priors: list[dict], ledger_available: bool, today: str) -> dict:
    """Jev 答案＋程式訊號 → 最終分類。Jev 沒答就是 not_judged，不補。
    reasons：需要人複核的原因（有就進待複核）。notes：程式覆寫或補充說明（不觸發複核）。"""
    overlap = _figure_overlap(cand, priors)
    if not j:
        return {"class": "not_judged", "jev_label": None, "confidence": None, "reasons": [], "notes": [],
                "figure_overlap": overlap, "lane": "unjudged"}
    lab, conf = j["novelty"]["label"], j["novelty"]["confidence"]
    reasons, notes = [], []
    cls = lab
    direct = [v for v, x in j["variables"].items() if x["link"] == "direct"]
    if j["stage"]["label"] == "market_price_only" and set(direct) <= {"market_valuation"} and lab in ("new_fact", "progress_update"):
        cls = "market_move_only"
        notes.append("Only a price or valuation move is stated, so it is not counted as fundamental evidence")
    # 規則 A（2026-09-23，跑在追加字眼規則之前）：事件本身已經過舊，且先前紀錄裡有同一天前後的紀錄，
    # 就直接判重述，不管 Jev 怎麼答；過舊卻找不到先前紀錄，送複核而不是照單全收。防的是「7 天前的
    # Fed 升息被當成今天的新事實」這種：事件日期一過舊，程式比 Jev 的新舊判斷更可信。
    stale = _stale_event_match(cand, priors, today)
    if stale is not None:
        if stale["prior"] is not None:
            r = stale["prior"]
            if cls != "known_restatement":
                notes.append(f"Event dated {cand.get('event_date', '')}, already recorded on "
                             f"{r.get('event_date') or r.get('first_seen', '')} ({_prior_brief(r)['outlet']}); "
                             "treated as a restatement")
            cls = "known_restatement"
        else:
            reasons.append(f"Event dated {cand.get('event_date', '')}, {stale['age']} days ago; "
                           "no earlier record found")
    if cls == "new_fact" and overlap["all_seen"]:
        s = overlap["seen"][0]
        if _FOLLOW_ON_RE.search(cand["text"]):
            reasons.append(f"Same figure ({s['figure']}) was already recorded on {s['date']} ({s['outlet']}) and the report "
                           "calls it additional; check whether this is a separate transaction or the earlier one re-reported")
        else:
            # 程式事實：標題數字同公司早就記錄過、文中也沒有「追加」字眼 → 重述（分類器說新也不採用）
            cls = "known_restatement"
            notes.append(f"Classifier said new ({conf:.2f}); code found the headline figure {s['figure']} already "
                         f"recorded on {s['date']} ({s['outlet']}), so it is treated as a restatement")
    if conf < NOVELTY_MIN_CONF:
        reasons.append(f"Low classification confidence ({conf:.2f})")
    if cls in ("new_fact", "progress_update") and not ledger_available:
        reasons.append("Earlier evidence record could not be loaded today, so 'new' is not verified")
    if cls == "known_restatement" and not priors:
        reasons.append("Classified as a restatement, but no earlier record was found")
    final = "needs_review" if reasons else cls
    lane = "main" if cls in ("new_fact", "progress_update") else "low"
    return {"class": final, "jev_label": lab, "code_label": cls, "confidence": conf, "reasons": reasons,
            "notes": notes, "figure_overlap": overlap, "lane": lane}


def _terms_in(text: str, terms) -> list[str]:
    folded = text.casefold()
    return [t for t in terms if t.casefold() in folded]


def unconfirmed_notes(cand: dict, j: dict | None, final: dict, priors: list[dict], parties: dict,
                      routing: dict, matcher: EntityMatcher, ledger_available: bool) -> list[str]:
    """「尚未證實」：程式規則產生，防止把階段、融資、統計總量、股價當成已發生的基本面。"""
    notes = []
    text = cand["text"]
    ft = cand.get("full_text_check") or {}
    if cand["basis"]["code"] == "headline_summary":
        # 2026-09-23：全文讀到了（basis 已升級成 full_article）就不會走到這支；
        # 這裡只處理沒讀到全文的三種情況：付費牆、抓不到、沒試過全文
        if ft.get("status") == "paywalled":
            notes.append(f"The article is paywalled at {ft.get('domain') or 'the outlet'}; "
                         "only the headline and feed summary were read.")
        elif ft.get("status") == "failed":
            notes.append("The full article could not be fetched; only the headline and feed summary were read.")
        else:
            notes.append("Only the headline and feed summary were read; the full article and any primary document were not checked.")
    elif cand["basis"]["code"] == "briefing_summary_only":
        notes.append("No source article was matched; this rests on the briefing's own summary and needs a source check.")
    if not ledger_available:
        notes.append("The earlier evidence record could not be loaded today, so novelty is not verified.")
    if j:
        stage = j["stage"]["label"]
        direct = {v for v, x in j["variables"].items() if x["link"] == "direct"}
        indirect = {v for v, x in j["variables"].items() if x["link"] == "indirect"}
        cap_terms = _terms_in(text, CAPACITY_TERMS)
        if stage in ("plan_or_intent", "filing_or_offering", "agreement_signed", "construction_started") and (
                "supply_capacity" in direct | indirect or cap_terms):
            what = "/".join(t for t in cap_terms if t not in ("packaging", "fab", "production line"))[:40] or "production"
            notes.append(f"{STAGE_DISPLAY[stage]} is not added capacity: no new {what} capacity is in operation yet.")
        if "financing" in direct:
            if stage in ("filing_or_offering", "plan_or_intent"):
                notes.append("The offering is launched, not priced or closed; final size, pricing and terms are not known.")
            compute = _COMPUTE_RE.search(text)
            notes.append("Money raised is not money spent: no completed "
                         + ("GPU or compute purchase" if compute else "purchase") + " is shown.")
        if "capex" in direct and "demand" not in direct:
            said = False
            if _EQUITY_RE.search(text):
                # 入股／買股權：投資方的產品訂單沒有因此增加
                for key in parties:
                    product = ((routing.get("companies") or {}).get(key) or {}).get("product", "")
                    if re.search(r"GPU|CPU|chip", product):
                        notes.append(f"An equity investment by {matcher.name(key)} is not an order for its "
                                     f"{product}s: this does not show more {product} orders.")
                        said = True
            if not said:
                notes.append("Money committed to building is not yet revenue for suppliers or new output.")
        kind = cand.get("kind", "company")
        if kind != "macro" and (stage == "official_statistic" or ("shipments" in direct and not parties)):
            notes.append("Country- or industry-level total: it cannot be attributed to any single company's revenue, including AI revenue.")
        # 總經（2026-09-22）：官員發言、市場定價、部分月份資料、初值、談判、預測，都不是已發生的結果
        if stage == "official_comment" or (
                (j.get("attribution") or {}).get("label") in ("commentary_or_analysis", "official_statement")
                and "policy_rate" in direct | indirect and stage != "policy_decision"):
            notes.append("An official's view is not a policy decision; rates are set at the policy meeting.")
        if _MARKET_IMPLIED_RE.search(text):
            notes.append("Market-implied odds describe current pricing, not an outcome.")
        period = cand.get("period") or ""
        if stage == "official_statistic" and period and int(period[-2:]) < 28:
            notes.append("Partial-month data; the full-month figure is released later and can differ.")
        bases = {s.split("@")[0] for s in cand.get("subjects") or []}
        if stage == "official_statistic" and bases & {"GDP", "JOBS", "RETAIL_SALES", "INDUSTRIAL_OUTPUT", "PMI", "TRADE_DATA"}:
            notes.append("First official release; these figures are often revised.")
        if ("trade" in direct | indirect or "TARIFFS" in bases) and stage in ("plan_or_intent", "official_comment", "unclear") \
                and _TALKS_RE.search(text):
            notes.append("Talks or proposals, not an agreement in force; nothing changes until an official notice gives terms and a start date.")
        if stage == "forecast_or_estimate":
            notes.append("A forecast or estimate, not an outcome.")
        if stage == "policy_decision" and cand["basis"]["code"] != "primary_document":
            notes.append("No official notice matched yet; the effective date and scope are not confirmed.")
    if not j and final.get("figure_overlap", {}).get("all_seen"):
        s = final["figure_overlap"]["seen"][0]
        notes.append(f"Code check (no classifier today): the headline figure {s['figure']} was already recorded on "
                     f"{s['date']} ({s['outlet']}), so this may be a restatement.")
    if final["class"] == "market_move_only" or (j and {v for v, x in j["variables"].items() if x["link"] == "direct"} == {"market_valuation"}):
        notes.append("Price or valuation signal only: it does not update demand, capacity or earnings assumptions.")
    if final["class"] == "known_restatement" and priors:
        briefs = [_prior_brief(r) for r in priors]
        first, later = briefs[0], briefs[1:]
        txt = f"First recorded on {first['date']} ({first['outlet']})"
        if later:
            txt += "; repeated on " + ", ".join(f"{b['date']} ({b['outlet']})" for b in later)
        notes.append(txt + ". Not counted as new evidence.")
    unk = cand.get("unknowns") or ""
    if unk and not _NOTHING_OUTSTANDING.fullmatch(unk.strip().rstrip(".")):
        notes.append(f"Briefing note on unknowns: {unk}")
    return list(dict.fromkeys(notes))[:7]


def _transmission(direct: list[str], routing: dict) -> list[str]:
    tr = routing.get("transmission") or {}
    out = []
    for v in direct:
        for target, why in tr.get(v, [])[:1]:
            out.append(f"{VAR_LABEL.get(v, v)} → {VAR_LABEL.get(target, target)}: {why}")
    return out[:3]


def _new_today(cand: dict, j: dict | None, final: dict, priors: list[dict]) -> str:
    """今天新增了什麼：只用來源已寫的內容（標題＋程式挑出的新數字），不讓模型生成。"""
    prior_figs = {f for r in priors for f in (r.get("figures") or [])}
    new_figs = [figure_label(f) for f in cand["figures"] if f not in prior_figs][:4]
    base = cand["headline"]
    if j and j["stage"]["label"] not in ("unclear", None):
        base += f" [stage: {STAGE_DISPLAY.get(j['stage']['label'], j['stage']['label'])}]"
    if priors and new_figs:
        base += f" — figures not in earlier records: {', '.join(new_figs)}"
    elif priors and cand["figures"] and not new_figs:
        base += " — no figure that is not already in earlier records"
    return base


def _status(final: dict, routes: dict) -> dict:
    if final["class"] == "not_judged":
        return {"code": "not_judged", "display": "Not classified today"}
    if final["class"] == "needs_review":
        return {"code": "needs_review", "display": "Needs review: " + (final["reasons"][0] if final["reasons"] else "")}
    if final["lane"] == "low":
        return {"code": "logged", "display": "Logged only"}
    linked = routes["dd"] or routes["themes"] or routes.get("macro")
    if routes["pending"] and not linked:
        return {"code": "needs_review", "display": "Needs review: research link unclear"}
    if linked:
        return {"code": "routed", "display": "Routed to research"}
    return {"code": "logged", "display": "Logged; no research link"}


def _rank_key(it: dict) -> tuple:
    """main 區排序（2026-09-23 改，取代單比 Jev 重要度分數）：
    ① 新事實／進度更新排在待複核前面；
    ② 有派到任何研究（DD、系統持倉、研究主題、總經報告、產業環節）排在什麼都沒派到的前面；
       不再細分 DD 高於主題：9/23 回放時 DD 優先會讓「Apple 開發健身手環」擠掉產業級消息；
    ③ 同一層再比 Jev 重要度分數；
    ④ 一手來源比只有標題／簡介的更可信；
    ⑤ 最後比早報原本的區塊優先序。
    needs_review 是否真的擋在 top 外面，由呼叫端另外過濾（這裡只決定 main 內部次序）。"""
    cls_rank = 0 if it["classification"]["class"] in ("new_fact", "progress_update") else 1
    routes = it.get("routes") or {}
    rel_rank = 0 if any(routes.get(k) for k in ("dd", "holdings", "themes", "macro", "segments")) else 1
    imp = (it.get("importance") or {}).get("score") or 0
    basis_rank = {"primary_document": 2, "full_article": 1.5, "headline_summary": 1}.get(it["evidence_basis"]["code"], 0)
    prio = dict(BLOCK_PRIORITY).get(it["block"], 0.3)
    return (cls_rank, rel_rank, -imp, -basis_rank, -prio)


# ── 主流程 ───────────────────────────────────────────────────────────────
def _fetch_json(url: str, timeout: int = 15):
    """回 (payload, status)。status：'ok'／'missing'（404）／'error:<型別>'。"""
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        if r.status_code == 404:
            return None, "missing"
        r.raise_for_status()
        return r.json(), "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


def _sec_get_json(url: str, user_agent: str):
    import requests
    r = requests.get(url, timeout=12, headers={"User-Agent": user_agent, "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def load_ledger(today: str, fetch=_fetch_json, seed_path: Path = SEED_PATH) -> Ledger:
    local = os.environ.get("EVIDENCE_LEDGER_PATH")
    if local:
        try:
            payload, status = json.loads(Path(local).read_text(encoding="utf-8")), "ok"
        except (OSError, ValueError) as e:
            payload, status = None, f"error:{type(e).__name__}"
    else:
        payload, status = fetch(os.environ.get("EVIDENCE_LEDGER_URL", f"{SITE_DATA_URL}/evidence_ledger.json"))
    seed = []
    try:
        seed_payload = json.loads(seed_path.read_text(encoding="utf-8"))
        seed = seed_payload.get("facts") if isinstance(seed_payload, dict) else seed_payload
    except (OSError, ValueError):
        pass
    if status == "ok":
        ledger = Ledger.from_json(payload, True, "site ledger")
    elif status == "missing" and seed:
        ledger = Ledger([], True, "first run: seed only")
    else:
        ledger = Ledger([], False, f"ledger unavailable ({status})")
    ledger.merge(seed or [])
    return ledger


def load_jev_cache(today: str, data_dir: Path | None, fetch=_fetch_json) -> dict:
    """同日重跑不重付：先讀本機今天的輸出，再讀網站上今天已發布的輸出。"""
    cache = {}
    if data_dir:
        p = Path(data_dir) / f"evidence_{today}.json"
        try:
            cache.update(json.loads(p.read_text(encoding="utf-8")).get("jev_cache") or {})
        except (OSError, ValueError):
            pass
    payload, status = fetch(f"{SITE_DATA_URL}/evidence_{today}.json")
    if status == "ok" and isinstance(payload, dict):
        for k, v in (payload.get("jev_cache") or {}).items():
            cache.setdefault(k, v)
    return cache


def quality_record(news_quality: dict | None, data: dict, cands: list[dict], items: list[dict],
                   jev_stats: dict, routing: dict) -> dict:
    nq = news_quality or {}
    feeds = nq.get("feeds") or {}
    ok = sum(1 for f in feeds.values() if f.get("status") == "ok")
    failed = sorted(k for k, f in feeds.items() if f.get("status") == "error")
    empty = sorted(k for k, f in feeds.items() if f.get("status") == "empty")
    entered = sum(len(v) for k, v in data.items()
                  if k in dict(BLOCK_PRIORITY) and isinstance(v, list))
    entered += sum(len(v) for v in (data.get("regional_tech") or {}).values() if isinstance(v, list))
    primary_checked = [c for it in items for c in (it.get("primary_check") or {}).get("checked", [])]
    gaps = []
    for it in items:
        for g in (it.get("primary_check") or {}).get("gaps", []):
            if g.get("reason") != "not connected":
                continue   # 「今天沒抓到」另外列在 official_sources.failed
            label = g.get("source") or g.get("segment")
            if label and label not in gaps:
                gaps.append(label)
    return {
        "feeds_total": len(feeds), "feeds_ok": ok, "feeds_empty": empty, "feeds_failed": failed,
        "feed_success_rate": round(ok / len(feeds), 3) if feeds else None,
        "raw_candidates": nq.get("total_before_dedup"),
        "duplicates_removed": nq.get("duplicate_removed"),
        "blocked_by_whitelist": nq.get("blocked_by_whitelist"),
        "after_dedup": nq.get("total_after_dedup"),
        "entered_briefing": entered,
        "judged_candidates": len(cands),
        "jev": {k: v for k, v in jev_stats.items() if k != "errors"},
        "jev_error_kinds": sorted(set(jev_stats.get("errors") or []))[:5],
        "primary_checks": {
            "attempted": len(primary_checked),
            "ok": sum(1 for c in primary_checked if c.get("status") == "ok"),
            "failed": sum(1 for c in primary_checked if c.get("status") == "failed"),
            "skipped": sum(1 for c in primary_checked if c.get("status") == "skipped"),
        },
        "primary_source_gaps": gaps[:8],
    }


def _tw_codes(keys: list[str], routing: dict) -> set:
    codes = set()
    for k in keys:
        for tk in _company_tickers(k, routing):
            m = re.fullmatch(r"(\d{4,6})(?:\.TWO?|)", tk)
            if m and (tk.endswith((".TW", ".TWO")) or tk.isdigit()):
                codes.add(m.group(1))
    return codes


def _jp_codes(keys: list[str], routing: dict) -> set:
    """東證代號：4 碼（有些新代號含字母，如 285A）＋ .T。TDnet 清單頁的代號多一碼檢查碼，
    parse_tdnet 已經只留前 4 碼，這裡對回同樣的 4 碼。"""
    codes = set()
    for k in keys:
        for tk in _company_tickers(k, routing):
            m = re.fullmatch(r"([0-9A-Z]{4})\.T", tk)
            if m:
                codes.add(m.group(1))
    return codes


def run_evidence_layer(data: dict, rss_items: list[dict] | None, watchlist: list[dict] | None,
                       news_quality: dict | None, today: str, data_dir: Path | None = None, *,
                       routing: dict | None = None, ledger: Ledger | None = None,
                       holdings_json: dict | None = None, jev: JevClient | None = None,
                       fetch=_fetch_json, sec_get_json=_sec_get_json,
                       sec_user_agent: str | None = None, official_fetch=http_text,
                       full_text_fetch=None, gdelt_fetch=None,
                       ideas: list[dict] | None = None) -> tuple[dict, Ledger]:
    routing = routing or load_routing()
    dd = dd_index(watchlist)
    matcher = EntityMatcher(routing, {t: v.get("name", "") for t, v in dd.items()})
    ledger = ledger if ledger is not None else load_ledger(today, fetch)
    if holdings_json is None:
        holdings_json, _ = fetch(os.environ.get("PUBLIC_HOLDINGS_URL", "https://research.investmquest.com/pm/holdings.json"))
    holdings = public_holdings_view(holdings_json)
    if jev is None:
        # 請求上限＝候選數＋想法步驟的名額（早報候選＋早報外各最多 8 則，逐則批次問法，一則
        # 一個請求）＋2 備用。2026-09-23 晚：想法步驟改成逐則批次問（一則新聞命中幾個查核點就
        # 在同一次請求問完，不是每對 (item, checkpoint) 各一個請求），IDEA_ITEM_BUDGET=16 遠比
        # 舊版「MAX_CANDIDATES 用光就把想法步驟擠成全 unjudged」更寬裕。
        jev = JevClient(api_key=get_api_key(), cache=load_jev_cache(today, data_dir, fetch),
                        max_requests=MAX_CANDIDATES + IDEA_ITEM_BUDGET + 2)
    if sec_user_agent is None:
        sec_user_agent = os.environ.get("SEC_USER_AGENT", "").strip() or None
    official = OfficialSources(routing.get("official_sources") or {}, fetch_text=official_fetch, today=today)
    official.prefetch()   # 官方來源每次執行只抓一次（並行）

    # 早報自己的新聞卡先佔名額，留 GDELT_MAX_SLOTS 個名額給 GDELT（2026-09-23；gdelt_fetch 沒傳就不查，
    # 測試預設不連網）。GDELT 失敗、逾時、被限流都不能連累這一層，全部包一層 try/except。
    cands = build_candidates(data, rss_items or [], matcher, today, max_n=MAX_CANDIDATES - GDELT_MAX_SLOTS)
    gdelt_quality: dict = {"enabled": False, "reason": "not configured"}
    if gdelt_fetch is not None:
        try:
            dedup_titles = [str(c.get("headline") or c.get("title") or "") for _, _, c in collect_cards(data)] + \
                [it.get("title", "") for it in (rss_items or [])]
            slots = max(0, MAX_CANDIDATES - len(cands))
            gdelt_cands, gdelt_quality = gdelt_fetch(routing, matcher, dd, holdings, dedup_titles, today,
                                                      max_kept=slots)
            cands += gdelt_cands[:slots]
        except Exception as e:  # noqa: BLE001 — GDELT 掛掉不能連累早報
            gdelt_quality = {"enabled": False, "error": f"{type(e).__name__}: {e}"}

    # ①b 全文（2026-09-23 新增）：只抓最前面 12 則（見 evidence_fulltext.MAX_FULLTEXT），
    # 抓到就把摘要塞進 state 給 Jev、把數字／關鍵詞併進去給官方來源比對用、basis 升級成
    # full_article；抓不到、付費牆都不擋主流程，只是 unconfirmed 的說法不同。
    full_text_fetch = full_text_fetch or fetch_fulltext
    fulltext = full_text_fetch(cands)
    for cand in cands:
        ft = fulltext.get(cand["cid"]) or {"status": "not_attempted"}
        if ft.get("status") == "ok":
            cand["figures"] = list(dict.fromkeys(cand["figures"] + (ft.get("figures") or [])))
            cand["terms"] = list(dict.fromkeys(cand["terms"] + matcher.terms(ft["excerpt"])))
            if cand["basis"]["code"] != "primary_document":
                cand["basis"] = {"code": "full_article", "display": f"Full article read: {ft['domain']}"}
            cand["full_text_excerpt"] = ft["excerpt"]   # 只用來組 Jev state，絕不寫進輸出檔
        cand["full_text_check"] = {k: v for k, v in ft.items() if k in ("status", "url", "domain", "word_count", "quotes")}

    # ① 問 Jev（每則一個請求；同樣的請求從快取拿）
    judged = []
    for cand in cands:
        cand["kind"] = candidate_kind(cand, routing)
        priors = ledger.find_prior(cand["companies"] + cand["subjects"], cand["figures"], cand["terms"],
                                   cand["tokens"], today, key_figures=cand["headline_figures"])
        state = build_state(cand, priors, matcher)
        questions = build_questions(len(cand["companies"]), var_ids_for(cand["kind"]))
        resp = jev.ask(state, questions)
        j = interpret(resp["answers"], cand["companies"], var_min_conf=VAR_MIN_CONF) if resp else None
        judged.append((cand, priors, resp, j, decide(cand, j, priors, ledger.available, today)))

    # ② 當事公司自己發的新聞稿：所有候選的當事公司一次查齊
    party_names = {}
    for cand, _, _, j, _ in judged:
        for k, p in (j["parties"] if j else {}).items():
            if p >= PARTY_YES:
                party_names.setdefault(k, matcher.name(k))
    official.fetch_company_wires(party_names)

    # ③ 派送、一手來源、組裝、寫紀錄
    sec_cache: dict = {}
    items = []
    ledger_actions = {"inserted": 0, "updated_today": 0, "restated": 0}
    for cand, priors, resp, j, final in judged:
        parties = {k: p for k, p in (j["parties"] if j else {}).items() if p >= PARTY_YES}
        pending = {k: p for k, p in (j["parties"] if j else {}).items() if PARTY_NO <= p < PARTY_YES}
        direct = [v for v, x in (j["variables"].items() if j else []) if x["link"] == "direct"]
        # 間接：要把握夠高、最多 3 個；「市場估值」只在直接時列（幾乎任何新聞都會間接影響股價，沒有資訊量）
        indirect = sorted((v for v, x in (j["variables"].items() if j else [])
                           if x["link"] == "indirect" and x["confidence"] >= INDIRECT_MIN_CONF and v != "market_valuation"),
                          key=lambda v: -j["variables"][v]["confidence"])[:3]
        routes = route(cand["text"], parties, pending, routing, dd, holdings, bool(j), cand["companies"],
                       subjects=cand["subjects"], direct_vars=direct if final["lane"] == "main" else [],
                       today=today, ledger_records=ledger.records, name_of=matcher.name)
        check_keys = list(parties) if j else []
        primary = sec_check(check_keys, routing, cand.get("event_date") or "", today, sec_user_agent,
                            sec_get_json, cache=sec_cache)
        primary["gaps"] += segment_gaps([s["id"] for s in routes["segments"]], routing)
        # 官方來源：當事公司（沒判斷時用比對到的公司）＋總經主題
        ent_keys = set(check_keys or cand["companies"]) | set(cand["subjects"])
        ent_keys |= {tk for k in (check_keys or cand["companies"]) for tk in _company_tickers(k, routing)}
        names = [matcher.name(k) for k in (check_keys or cand["companies"])] + \
                [matcher.subject_label(s).split(" (")[0] for s in cand["subjects"]]
        off = official.match(cand, ent_keys, names, _tw_codes(check_keys or cand["companies"], routing), today,
                             jp_codes=_jp_codes(check_keys or cand["companies"], routing))
        primary["official"] = off
        for f in off["failed"]:
            primary["gaps"].append({"source": f["source"], "reason": f"not read today ({f['reason']})"})
        basis = dict(cand["basis"])
        if off["matched"]:
            basis = {"code": "primary_document", "display": f"Official source matched: {off['matched'][0]['source']}"}

        company_roles = []
        for k in cand["companies"]:
            p = (j["parties"].get(k) if j else None)
            role = ("party" if p is not None and p >= PARTY_YES else
                    "pending" if p is not None and p >= PARTY_NO else
                    "mentioned" if p is not None else "unverified")
            company_roles.append({"key": k, "name": matcher.name(k), "role": role, "p": p})

        cand_for_notes = {**cand, "basis": basis}
        item = {
            "id": cand["cid"], "block": cand["block"], "kind": cand["kind"], "headline": cand["headline"],
            "source": cand["source"], "source_date": cand["source_date"], "published_at": cand["published_at"],
            "event_date": cand.get("event_date", ""), "date_basis": cand.get("date_basis", ""),
            "period": cand.get("period", ""),
            "companies": company_roles,
            "topics": [{"key": s, "label": matcher.subject_label(s)} for s in cand["subjects"]],
            "figures": [figure_label(f) for f in cand["figures"]],
            "classification": {
                "class": final["class"],
                "display": (NOVELTY_DISPLAY.get(final["class"]) or
                            {"needs_review": "Needs review", "not_judged": "Not classified"}.get(final["class"], final["class"])),
                "jev_label": final["jev_label"], "confidence": final["confidence"],
                "by": (resp or {}).get("model") if resp else None, "reasons": final["reasons"],
                "notes": final.get("notes", []),
            },
            "stage": ({"label": j["stage"]["label"], "display": STAGE_DISPLAY.get(j["stage"]["label"], ""),
                       "confidence": j["stage"]["confidence"]} if j else None),
            # 2026-09-23 新增，display-only：何時對營運／總經產生效果，只記錄供之後校準用，
            # 不進排序（_rank_key）、不進分道／分類（decide）、不進派送（route）。低信心一律顯示
            # 「Timing unclear」，但 label 仍存 Jev 原始答案，不因信心低被改寫。
            "timing": ({"label": j["timing"]["label"],
                        "display": (TIMING_DISPLAY.get(j["timing"]["label"], "Timing unclear")
                                    if j["timing"]["confidence"] >= TIMING_MIN_CONF else "Timing unclear"),
                        "confidence": j["timing"]["confidence"]} if j else None),
            "attribution": ({"label": j["attribution"]["label"],
                             "display": ATTRIBUTION_DISPLAY.get(j["attribution"]["label"], ""),
                             "confidence": j["attribution"]["confidence"]} if j else None),
            "importance": j["importance"] if j else None,
            "variables": {
                "direct": [{"var": v, "label": VAR_LABEL[v], "direction": j["variables"][v]["direction"],
                            "confidence": j["variables"][v]["confidence"]} for v in direct],
                "indirect": [{"var": v, "label": VAR_LABEL[v], "confidence": j["variables"][v]["confidence"]}
                             for v in indirect],
            },
            "last_known": [{**_prior_brief(r), "origin": r.get("origin", ""), "fact_key": r.get("fact_key"),
                            "shared_figures": [figure_label(f) for f in r["_match"]["shared_figures"]]}
                           for r in priors],
            "new_today": _new_today(cand, j, final, priors),
            "transmission": _transmission(direct, routing),
            # 價格訊號、重述、未判斷不往外推產業名單
            "potential_impact": (potential_impact(
                routes,
                [{"var": v, "label": VAR_LABEL[v], "direction": j["variables"][v]["direction"]} for v in direct],
                parties, routing, matcher.name) if (j and final["lane"] == "main") else None),
            "unconfirmed": unconfirmed_notes(cand_for_notes, j, final, priors, parties, routing, matcher, ledger.available),
            "evidence_basis": basis,
            "primary_check": primary,
            # 2026-09-23：只放安全欄位（狀態／網址／網域／字數／短引句），全文不進來，見 evidence_fulltext.py 檔頭
            "article_check": cand.get("full_text_check") or {"status": "not_attempted"},
            "routes": routes,
            "sources": [{"source": r["source"], "url": r["url"], "published": r["published"], "title": r["title"]}
                        for r in cand["rss"]]
                       or [{"source": cand["source"], "url": "", "published": cand["source_date"],
                            "title": "(outlet named by the briefing; no feed item matched)"}],
            "also_in": cand["also_in"],
            "lane": final["lane"],
            "status": _status(final, routes),
            "request_hash": (resp or {}).get("request_hash"),
        }
        items.append(item)

        # 寫入跨日紀錄（冪等）
        fkey = fact_key(cand["companies"] + cand["subjects"], cand["figures"], cand["terms"], cand["headline"])
        rec = {
            "fact_key": fkey, "candidate_ids": [cand["cid"]], "origin": "briefing",
            "first_seen": today, "last_seen": today, "seen_dates": [today],
            "event_date": cand.get("event_date", ""), "date_basis": cand.get("date_basis", ""),
            "period": cand.get("period", ""), "published_at": cand["published_at"],
            "companies": cand["companies"], "subjects": cand["subjects"], "parties": sorted(parties),
            "themes": [t["key"] for t in routes["themes"]],
            "claim": cand["headline"], "detail": cand["text"][len(cand["headline"]):].strip()[:400],
            "figures": cand["figures"], "terms": cand["terms"], "tokens": sorted(cand["tokens"])[:40],
            "stage": j["stage"]["label"] if j else None,
            "timing": j["timing"]["label"] if j else None,  # 2026-09-23：只記錄供之後校準，不參與任何判斷規則
            "novelty": final["class"], "jev_novelty": final["jev_label"],
            "variables_direct": direct, "variables_indirect": indirect,
            "sources": [{"source": r["source"], "url": r["url"], "published": r["published"]} for r in cand["rss"]]
                       or [{"source": cand["source"], "url": "", "published": cand["source_date"]}],
            "official_matches": [{"source": m["source"], "url": m["url"], "date": m["date"]} for m in off["matched"]],
            "judged_by": (resp or {}).get("model") if resp else None,
            "prior_refs": [r.get("fact_key") for r in priors],
        }
        restated = None
        if final["class"] == "known_restatement" and priors:
            same_fig = [r for r in priors if r["_match"]["shared_figures"]]
            restated = (same_fig or priors)[0]["fact_key"]
        today_twin = ledger.find_today(cand["cid"], fkey, today)
        if today_twin is None and not restated:
            ents = set(cand["companies"]) | set(cand["subjects"])
            for r in ledger.records:
                if (r.get("first_seen") == today
                        and ents & (set(r.get("companies") or []) | set(r.get("subjects") or []))
                        and set(r.get("figures") or []) == set(cand["figures"]) and cand["figures"]):
                    rec["fact_key"] = r["fact_key"]
                    break
        ledger_actions[ledger.upsert(rec, today, restated_key=restated)] += 1
        item["fact_key"] = rec["fact_key"] if not restated else restated

    # ④ 投資想法／查核點（2026-09-23 新增，見 ideas_layer.py）：獨立一層，包自己的 try/except，
    # 失敗只讓這一步標 unavailable，不影響事件判斷層其餘輸出。刻意跑在 items 全部組好之後（需要
    # 每則的 classification／routes／companies），沿用同一個 jev（快取與預算共用，同一天重跑或
    # 已經問過的請求不重付；idea_hits.json 的合併規則見 ideas_layer._merge_hits）。
    cand_by_id = {c["cid"]: c for c, *_ in judged}
    try:
        from ideas_layer import run_ideas_step
        ideas_result = run_ideas_step(items, cand_by_id, jev, today, ideas=ideas, fetch=fetch,
                                      matcher=matcher, rss_items=rss_items, ledger=ledger)
    except Exception as e:  # noqa: BLE001 — 想法層掛掉不能連累事件判斷層其餘輸出
        for it in items:
            it.setdefault("ideas", [])
        ideas_result = {"status": "unavailable", "reason": f"ideas step error ({type(e).__name__}: {e})",
                        "ideas_count": 0, "matched_pairs": 0, "asked": 0, "catalog": {}, "hits": None,
                        "wide_scan": {}, "wide_pairs": []}

    pruned = ledger.prune(today)

    # 排序與分道（2026-09-22 版只比 Jev 重要度分數，分數接近飽和時排序沒意義，
    # needs_review 也可能混進 top；2026-09-23 改成 _rank_key 的五層排序，見該函式註解）：
    main = sorted([it for it in items if it["lane"] == "main"], key=_rank_key)
    low = [it for it in items if it["lane"] == "low"]
    unjudged = [it for it in items if it["lane"] == "unjudged"]
    # needs_review 一律不進 top（就算分數再高），排定後另外分：
    top = [it for it in main if it["classification"]["class"] != "needs_review"][:TOP_SHOWN]
    top_ids = {it["id"] for it in top}
    more = [it for it in main if it["id"] not in top_ids]

    if not jev.available and not jev.stats["cache_hits"]:
        jev_status, reason = "unavailable", "TYPESAFE_API_KEY not set"
    elif jev.stats["failures"] and not (jev.stats["requests_sent"] - jev.stats["failures"]) and not jev.stats["cache_hits"]:
        jev_status, reason = "unavailable", "Jev API calls failed"
    elif unjudged:
        jev_status, reason = "partial", f"{len(unjudged)} item(s) not classified (API failure or budget)"
    else:
        jev_status, reason = "judged", ""

    quality = quality_record(news_quality, data, cands, items, jev.stats, routing)
    quality["official_sources"] = official.summary()
    quality["gdelt"] = gdelt_quality
    result = {
        "schema": SCHEMA, "date": today, "generated_at": _now_iso(), "model": MODEL,
        "jev": {"status": jev_status, "reason": reason},
        "ledger": {"available": ledger.available, "note": ledger.origin_note, "records": len(ledger.records),
                   "pruned": pruned, **ledger_actions},
        "holdings_source": {"kind": "public system portfolio (/pm/holdings.json)", "available": holdings["available"],
                            "as_of": holdings["as_of"]},
        "top": [it["id"] for it in top],
        "more": [it["id"] for it in more],
        "low_priority": [it["id"] for it in low],
        "unjudged": [it["id"] for it in unjudged],
        "items": items,
        "quality": quality,
        "jev_cache": dict(jev.cache),
        "ideas": {"status": ideas_result["status"], "reason": ideas_result.get("reason", ""),
                 "ideas_count": ideas_result.get("ideas_count", 0),
                 "matched_pairs": ideas_result.get("matched_pairs", 0),
                 "asked": ideas_result.get("asked", 0), "catalog": ideas_result.get("catalog") or {},
                 # 2026-09-23 晚：早報外掃描統計（見 ideas_layer._wide_scan）＋早報外每對命中
                 # （含 unrelated，只給週度校準用，不對外渲染；早報外的 supports／refutes／
                 # unjudged 已經另外進 idea_hits.json，見 ideas_layer.run_ideas_step）
                 "wide_scan": ideas_result.get("wide_scan") or {},
                 "wide_pairs": ideas_result.get("wide_pairs") or []},
        "idea_hits": ideas_result.get("hits"),
    }
    return result, ledger


def save_outputs(result: dict, ledger: Ledger, data_dir: Path, today: str) -> list[str]:
    """同一天重跑：同名檔覆寫（不追加）。"""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    written = []
    (data_dir / "evidence_ledger.json").write_text(ledger.to_json_text(today), encoding="utf-8")
    written.append("evidence_ledger.json")
    body = json.dumps(result, ensure_ascii=False, indent=1)
    for fn in (f"evidence_{today}.json", "evidence_latest.json"):
        (data_dir / fn).write_text(body, encoding="utf-8")
        written.append(fn)
    q = {"schema": "source-quality-v1", "date": today, "generated_at": result.get("generated_at"),
         **result.get("quality", {})}
    for fn in (f"source_quality_{today}.json", "source_quality_latest.json"):
        (data_dir / fn).write_text(json.dumps(q, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(fn)
    if result.get("idea_hits"):
        (data_dir / "idea_hits.json").write_text(
            json.dumps(result["idea_hits"], ensure_ascii=False, indent=1), encoding="utf-8")
        written.append("idea_hits.json")
    return written


def unavailable_result(today: str, reason: str) -> dict:
    """整層掛掉時給 html_template 的最小結構：如實顯示未判斷。"""
    return {"schema": SCHEMA, "date": today, "generated_at": _now_iso(), "model": MODEL,
            "jev": {"status": "unavailable", "reason": reason},
            "ledger": {"available": False, "note": reason}, "items": [], "top": [], "more": [],
            "low_priority": [], "unjudged": [], "quality": {}, "jev_cache": {},
            "ideas": {"status": "unavailable", "reason": reason, "ideas_count": 0, "matched_pairs": 0,
                     "asked": 0, "catalog": {}, "wide_scan": {}, "wide_pairs": []}, "idea_hits": None}
