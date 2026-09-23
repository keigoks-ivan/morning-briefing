"""
gdelt_source.py
----------------
2026-09-23 新增：事件判斷層的第二個候選來源，GDELT DOC 2.0 API。

背景：evidence_layer 的候選只來自早報自己的新聞卡（`briefing/news_fetcher.py` 約 60 個
RSS 來源、主流標題），個股專屬的新聞如果沒被那些 feed 收到就完全看不見。這裡另外查
GDELT（https://api.gdeltproject.org/api/v2/doc/doc，全球新聞索引），只挑：
① 標題點到一家研究公司（EntityMatcher）② 而且文中有主題／環節辨識詞或帶單位的數字。
兩個條件都要，避免抓到公司名字剛好出現、但其實是雜訊的文章。

**實測（2026-09-23）**：GDELT 真的限流一次／5 秒；超過回 **HTTP 429**、純文字內容開頭
是「Please limit requests to one every 5 seconds …」，不是 JSON——程式判斷「JSON 解不開
或狀態碼 429」就算被限流，等 5 秒重試一次，再不行就放棄那一題。這次沙盒環境的對外 IP
被同時間其他流量頂到，多次間隔 20～90 秒仍被 429，沒能穩定量出 query 字元上限；
`MAX_QUERY_CHARS` 先用保守值（1200），之後如果常態性因為查詢太長被拒，再收窄。

分工：程式做全部事（查詢、限流重試、標題過濾、去重、排序、組候選）；不問 Jev、不連 Jev。
Jev 沿用既有流程對這些候選照樣分類（見 evidence_layer.run_evidence_layer）。

失效保護：任何一步出錯（查不到、限流、逾時、解析失敗）都回空清單＋quality 統計，
不丟例外、不讓早報掛掉；呼叫端仍套一層 try/except 加保險。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from datetime import datetime, timezone

GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = "Mozilla/5.0 (compatible; morning-briefing research bot)"
BLOCK_NAME = "gdelt"
GDELT_PRIORITY = 0.2      # BLOCK_PRIORITY 最低（早報自己的區塊最低是 startup_news 0.3，2026-09-23）

RATE_LIMIT_SECONDS = 5.0  # GDELT 官方限流：一次／5 秒
MAX_REQUESTS = 20         # 每次執行最多幾個查詢（≈100–120 秒，含限流間隔）
MAX_QUERY_CHARS = 1200    # 保守值，見檔頭說明；未能在沙盒環境實測出正式上限
MAX_GROUP_TERMS = 25      # 單一 OR 查詢最多幾個公司名，避免稀釋相關度
WALL_TIME_BUDGET = 150.0  # 整個步驟的秒數上限
MAX_KEPT = 10             # 每天最多留幾則
MAXRECORDS = 50           # 每次查詢最多回幾篇
TIMESPAN = "24h"

_RATE_LIMIT_RE = re.compile(r"please limit requests", re.I)


# ── HTTP（可替換，測試用假的） ───────────────────────────────────────────
def _default_http_get(url: str, timeout: int = 20) -> tuple[str, int | None]:
    """回 (內容, HTTP 狀態碼)。網路失敗回 ("", None)。429 也要留下內容才能判斷是不是限流訊息。"""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA})
        return r.text, r.status_code
    except Exception:  # noqa: BLE001
        return "", None


def _parse_articles(text: str) -> list[dict] | None:
    """JSON 解不開就回 None（可能是限流訊息、可能是其他錯誤）。"""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    arts = payload.get("articles")
    return arts if isinstance(arts, list) else []


# ── 查詢：公司名優先序（DD／系統持倉 → 研究主題成員） ───────────────────────
def _distinctive_name(name: str) -> bool:
    name = (name or "").strip()
    if len(name) < 4 or not re.search(r"[A-Za-z]", name):
        return False   # 太短，或只有中文／代號（GDELT 這裡只查 sourcelang:english）
    if re.fullmatch(r"[A-Za-z]{1,3}", name):
        return False   # 太像通用縮寫
    return True


def _resolve_name(ticker: str, routing: dict, matcher) -> str:
    for key, spec in matcher.companies.items():
        if spec.get("same_as"):
            continue
        if key == ticker or spec.get("ticker") == ticker:
            return spec.get("name") or key
    auto = (routing.get("auto_companies") or {}).get(ticker)
    if auto:
        aliases = [a for a in (auto.get("aliases") or []) if a]
        en = [a for a in aliases if not re.search(r"[一-鿿]", a)]
        return (en or aliases)[-1] if aliases else ticker
    return ticker


def company_universe(routing: dict, dd: dict, holdings: dict, matcher) -> list[str]:
    """去重後、依優先序排列的可查詢公司名：DD 已有報告／系統持倉優先，其次研究主題成員。"""
    priority, seen_p = [], set()
    for t, info in (dd or {}).items():
        if info.get("dd_status") == "dd" and t not in seen_p:
            seen_p.add(t)
            priority.append(t)
    for t in list((holdings or {}).get("seats") or {}) + list((holdings or {}).get("index") or {}):
        if t not in seen_p:
            seen_p.add(t)
            priority.append(t)
    theme_tickers, seen_t = [], set()
    for spec in (routing.get("themes") or {}).values():
        for tk in (spec.get("members") or {}):
            if tk not in seen_t:
                seen_t.add(tk)
                theme_tickers.append(tk)
    manual = [k for k, spec in (routing.get("companies") or {}).items() if not spec.get("same_as")]
    ordered = priority + [t for t in theme_tickers if t not in seen_p] + \
        [t for t in manual if t not in seen_p and t not in seen_t]
    names, seen_n = [], set()
    for tk in ordered:
        name = _resolve_name(tk, routing, matcher)
        if not _distinctive_name(name):
            continue
        key = name.casefold()
        if key in seen_n:
            continue
        seen_n.add(key)
        names.append(name)
    return names


def build_queries(routing: dict, dd: dict, holdings: dict, matcher, *,
                  max_requests: int = MAX_REQUESTS, max_query_chars: int = MAX_QUERY_CHARS,
                  max_group_terms: int = MAX_GROUP_TERMS) -> list[str]:
    """公司名分組成 `("A" OR "B" OR ...) sourcelang:english` 查詢字串，依優先序裝箱，
    上限 max_requests 組。"""
    names = company_universe(routing, dd, holdings, matcher)
    suffix = " sourcelang:english"
    queries: list[str] = []
    group: list[str] = []
    for name in names:
        if len(queries) >= max_requests:
            break
        term = f'"{name}"'
        candidate_len = len("(" + " OR ".join(group + [term]) + ")" + suffix)
        if group and (candidate_len > max_query_chars or len(group) >= max_group_terms):
            queries.append("(" + " OR ".join(group) + ")" + suffix)
            group = []
            if len(queries) >= max_requests:
                break
        group.append(term)
    if group and len(queries) < max_requests:
        queries.append("(" + " OR ".join(group) + ")" + suffix)
    return queries[:max_requests]


# ── 抓取：限流重試、時間預算 ─────────────────────────────────────────────
def fetch_raw_articles(queries: list[str], *, http_get=_default_http_get, sleep=time.sleep,
                       now=time.monotonic, wall_time_budget: float = WALL_TIME_BUDGET,
                       maxrecords: int = MAXRECORDS, timespan: str = TIMESPAN) -> tuple[list[dict], dict]:
    articles: list[dict] = []
    quality = {"queries_planned": len(queries), "requests_sent": 0, "ok": 0, "rate_limited": 0,
              "http_errors": 0, "network_errors": 0, "articles_seen": 0}
    start = now()
    last_call = None
    blocked_in_a_row = 0   # 2026-09-23：本機實測被 GDELT 封 IP 後，重試只會越查越久；連續 3 個查詢都被擋就收手

    def _call(query: str) -> tuple[str, int | None]:
        url = GDELT_ENDPOINT + "?" + urllib.parse.urlencode({
            "query": query, "mode": "artlist", "format": "json",
            "maxrecords": maxrecords, "timespan": timespan, "sort": "hybridrel",
        })
        return http_get(url)

    for q in queries:
        if now() - start > wall_time_budget:
            quality["stopped_reason"] = "wall_time_budget"
            break
        if last_call is not None:
            wait = RATE_LIMIT_SECONDS - (now() - last_call)
            if wait > 0:
                sleep(wait)
        text, status = _call(q)
        last_call = now()
        quality["requests_sent"] += 1
        if status is None:
            quality["network_errors"] += 1
            continue
        arts = _parse_articles(text)
        if arts is None and (status == 429 or _RATE_LIMIT_RE.search(text or "")):
            quality["rate_limited"] += 1
            sleep(RATE_LIMIT_SECONDS)
            text, status = _call(q)
            last_call = now()
            quality["requests_sent"] += 1
            arts = _parse_articles(text)
        if arts is None:
            quality["http_errors"] += 1
            if status == 429 or _RATE_LIMIT_RE.search(text or ""):
                blocked_in_a_row += 1
                if blocked_in_a_row >= 3:
                    quality["stopped_reason"] = "rate_limited_3_in_a_row"
                    break
            continue
        blocked_in_a_row = 0
        quality["ok"] += 1
        quality["articles_seen"] += len(arts)
        articles.extend(arts)
    return articles, quality


# ── 過濾與排序 ───────────────────────────────────────────────────────────
def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _theme_and_segment_keywords(routing: dict) -> list[list[str]]:
    lists = [v for k, v in (routing.get("theme_keywords") or {}).items() if not k.startswith("_")]
    for seg in (routing.get("segments") or {}).values():
        if isinstance(seg, dict) and seg.get("keywords"):
            lists.append(seg["keywords"])
    return lists


def filter_and_rank(articles: list[dict], matcher, routing: dict, dedup_titles: list[str],
                    dd: dict, holdings: dict, *, max_kept: int = MAX_KEPT) -> list[dict]:
    """標題要點到研究公司，且有主題／環節辨識詞或帶單位的數字；跟既有標題近似的丟掉；
    黑名單網域丟掉；依 DD／持倉優先、有數字優先、新的優先排序。"""
    from evidence_ledger import extract_figures
    from evidence_routing import _company_tickers, _keyword_hits
    from news_fetcher import _near_same_title
    from source_registry import is_blacklisted

    priority_tickers = {t for t, info in (dd or {}).items() if info.get("dd_status") == "dd"}
    priority_tickers |= set((holdings or {}).get("seats") or {}) | set((holdings or {}).get("index") or {})
    kw_lists = _theme_and_segment_keywords(routing)

    seen_urls: set[str] = set()
    kept_titles: list[str] = []
    kept: list[dict] = []
    for art in articles:
        if not isinstance(art, dict):
            continue
        title = (art.get("title") or "").strip()
        url = (art.get("url") or "").strip()
        if not title or not url or url in seen_urls:
            continue
        domain = (art.get("domain") or "").strip().casefold() or _domain_of(url)
        if is_blacklisted(domain, url):
            continue
        companies = matcher.match(title)
        if not companies:
            continue   # 沒點到研究公司：不夠具體，可能是雜訊
        figures = extract_figures(title)
        theme_hit = any(_keyword_hits(title, kws) for kws in kw_lists)
        if not (figures or theme_hit):
            continue   # 只有公司名、沒有數字也沒有主題辨識詞：純雜訊
        if any(_near_same_title(title, t) for t in dedup_titles):
            continue   # 跟早報既有新聞卡／RSS 標題撞了，不重複帶進來
        if any(_near_same_title(title, t) for t in kept_titles):
            continue
        seen_urls.add(url)
        kept_titles.append(title)
        is_priority = any(c in priority_tickers or any(tk in priority_tickers for tk in _company_tickers(c, routing))
                          for c in companies)
        kept.append({
            "title": title, "url": url, "domain": domain, "companies": companies,
            "figures": figures, "seendate": str(art.get("seendate") or ""),
            "has_figure": bool(figures), "priority": is_priority,
        })
    # 穩定排序，由次要到主要依序套：新的優先 → 有數字優先 → DD／持倉公司優先
    kept.sort(key=lambda k: k["seendate"], reverse=True)
    kept.sort(key=lambda k: k["has_figure"], reverse=True)
    kept.sort(key=lambda k: k["priority"], reverse=True)
    return kept[:max_kept]


# ── 組成候選（跟 evidence_layer.build_candidates 同一個 cand 形狀） ─────────
def _seendate_to_iso(seendate: str) -> str:
    try:
        dt = datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError):
        return ""


def make_candidate(art: dict, matcher, today: str) -> dict:
    from evidence_ledger import content_tokens, extract_event_date
    title = art["title"]
    published_iso = _seendate_to_iso(art.get("seendate", ""))
    source_date = published_iso[:10] if published_iso else today
    date_info = extract_event_date(title, source_date or today) or \
        {"event_date": source_date, "date_basis": "published"}
    cid = "c_gdelt_" + hashlib.sha1(
        f"{today}|{re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()}".encode()).hexdigest()[:12]
    return {
        "also_in": [], "subjects": matcher.subjects(title), "cid": cid, "block": BLOCK_NAME,
        "priority": GDELT_PRIORITY, "headline": title, "text": title[:1400], "unknowns": "",
        "source": art["domain"], "source_date": source_date, "published_at": published_iso,
        **date_info,
        "companies": art["companies"][:5], "figures": art["figures"], "headline_figures": art["figures"],
        "terms": matcher.terms(title), "tokens": content_tokens(title),
        "rss": [{"source": art["domain"], "title": title, "summary": "", "url": art["url"],
                 "published": published_iso, "also_in": []}],
        "basis": {"code": "headline_summary", "display": "Headline and feed summary only, unverified"},
        # 2026-09-24：給 evidence_layer._merge_reserved_candidates 跟 sitemap 候選一起排序用
        # （見 sitemap_source.py 同名欄位的註解），不是給 Jev 或畫面用的欄位。
        "_match_priority": bool(art.get("priority")),
        "_match_has_figure": bool(art.get("has_figure")),
    }


# ── 進入點 ───────────────────────────────────────────────────────────────
def fetch_gdelt_candidates(routing: dict, matcher, dd: dict, holdings: dict, dedup_titles: list[str],
                           today: str, *, max_kept: int = MAX_KEPT, max_requests: int = MAX_REQUESTS,
                           http_get=_default_http_get, sleep=time.sleep, now=time.monotonic,
                           wall_time_budget: float = WALL_TIME_BUDGET) -> tuple[list[dict], dict]:
    """回 (候選清單, quality)。任何一步出錯都回空清單＋quality，不丟例外。"""
    quality = {"enabled": True, "requests_sent": 0, "ok": 0, "rate_limited": 0, "articles_seen": 0, "kept": 0}
    if max_kept <= 0:
        quality["enabled"], quality["reason"] = False, "no candidate slots left"
        return [], quality
    try:
        queries = build_queries(routing, dd, holdings, matcher, max_requests=max_requests)
        quality["queries"] = len(queries)
        if not queries:
            quality["reason"] = "no distinctive company names to query"
            return [], quality
        articles, fetch_quality = fetch_raw_articles(queries, http_get=http_get, sleep=sleep, now=now,
                                                      wall_time_budget=wall_time_budget)
        quality.update(fetch_quality)
        kept = filter_and_rank(articles, matcher, routing, dedup_titles, dd, holdings, max_kept=max_kept)
        quality["kept"] = len(kept)
        quality["kept_titles"] = [k["title"] for k in kept]
        cands = [make_candidate(k, matcher, today) for k in kept]
        return cands, quality
    except Exception as e:  # noqa: BLE001 — GDELT 掛掉不能連累早報
        quality["enabled"] = False
        quality["error"] = f"{type(e).__name__}: {e}"
        return [], quality
