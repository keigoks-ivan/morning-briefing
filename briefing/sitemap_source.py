"""
sitemap_source.py
------------------
2026-09-24 新增：事件判斷層的第三個候選來源，跟 `gdelt_source.py` 並列（見 CLAUDE.md「Sitemap
候選」段）。背景：GDELT DOC 2.0 在 GitHub Actions 上常態性被限流（2026-09-24 排程：
`rate_limited 3`、`kept 0`），這裡另開一條不靠 GDELT 搜尋索引的候選管道——直接讀新聞網站自己
發布的 Google News 相容 sitemap（`<news:title>`／`<news:publication_date>`），來源清單在
`data/news_sitemaps.json`（可編輯，不用改程式），見該檔案 `_comment` 說明各來源的取捨。

三種來源 type：
- news_sitemap：Google News 相容格式，直接有 `<news:title>`／`<news:publication_date>`（CNBC／
  Reuters／TheElec／Korea Herald／Tom's Hardware）。
- sitemap_index：先抓索引頁，取最新的 `max_children` 個子 sitemap（預設 1）各自當
  news_sitemap 解析（Nikkei Asia 索引頁按日期分檔，`max_children=2` 剛好對到 48 小時窗）。
- site_sitemap：全站泛用 sitemap，沒有 `news:` 標籤，只有 `<lastmod>`；靠 `url_filter`
  （正則，對 `<loc>` 比對）篩出新聞／新聞稿路徑，標題從網址 slug 猜（`title_from_slug=True`，
  TrendForce 的 slug 是日期＋流水號，猜出來的標題通常沒有意義，僅供除錯）。

分工（跟 gdelt_source.py 同一個規矩，2026-09-22 定）：程式做全部事（抓取、重試、解析、篩選、
排序、組候選）；不問 Jev、不連 Jev；Jev 沿用既有流程對這些候選照樣分類（見
evidence_layer.run_evidence_layer）。

兩個用途（見 CLAUDE.md）：
① evidence 候選：標題點到研究公司，或點到研究主題／環節辨識詞（`filter_for_evidence`），
   跟既有新聞卡／RSS 標題近似的丟掉，黑名單網域丟掉；跟 GDELT 候選共用
   `evidence_layer.GDELT_MAX_SLOTS` 剩下的名額（見 evidence_layer._merge_reserved_candidates），
   不是各自獨立 8 則。block 叫 "sitemap"，優先序跟 gdelt 一樣是 0.2。
② 早報外掃描（ideas_layer._wide_scan）：全部在 48 小時內、通過各來源 url_filter 的項目（不只
   標題點到公司的），轉成 RSS 條目形狀（`to_pool_items`）餵進去，讓查核點關鍵詞比對看得到；
   既有把關（過舊、ledger 已知數字、idea_hits 歷史重複、跟早報候選標題近似）照舊套用，不重造
   規則。

失效保護：單一來源抓不到、被擋（403／429）、解析失敗都只讓那個來源標對應狀態＋0 則，不影響
其他來源；整支 `fetch_sitemap_candidates` 另外包一層 try/except，任何沒預期到的錯誤都回空清單
＋quality，不丟例外、不讓早報掛掉（呼叫端 evidence_layer.py 仍再套一層 try/except 加保險）。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = "Mozilla/5.0 (compatible; morning-briefing research bot)"
BLOCK_NAME = "sitemap"
SITEMAP_PRIORITY = 0.2     # 跟 gdelt 同一個優先序（BLOCK_PRIORITY 裡兩者並列最低，見 CLAUDE.md）

CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "news_sitemaps.json"
FETCH_TIMEOUT = 15         # 秒／來源（含子 sitemap）
RETRY_WAIT_SECONDS = 2.0   # 重試前固定等這麼久；不分析回應內容（不是官方限流訊息，見檔頭）
DEFAULT_MAX_AGE_HOURS = 48.0
MAX_KEPT = 10              # 每天最多留幾則進 evidence 候選（跟 gdelt MAX_KEPT 同一個量級）


# ── 載入設定 ─────────────────────────────────────────────────────────────
def load_sources(path: Path | None = None) -> list[dict]:
    try:
        payload = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [s for s in (payload.get("sources") or []) if isinstance(s, dict) and s.get("url")]


# ── HTTP（可替換，測試用假的） ───────────────────────────────────────────
def _default_http_get(url: str, timeout: int = FETCH_TIMEOUT) -> tuple[str, int | None]:
    """回 (內容, HTTP 狀態碼)。網路失敗回 ("", None)。支援 gzip：requests 本來就會處理
    Content-Encoding: gzip 的傳輸層壓縮；這裡另外偵測回應內容本身就是 gzip 檔（.xml.gz 這種
    payload 層級壓縮，例如某些網站用 gzip 檔案本體發布 sitemap），開頭是 gzip magic bytes
    就地解壓。"""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        content = r.content
        if content[:2] == b"\x1f\x8b":
            import gzip
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
        return content.decode("utf-8", errors="replace"), r.status_code
    except Exception:  # noqa: BLE001
        return "", None


def _fetch_with_retry(url: str, http_get, sleep) -> tuple[str, int | None]:
    """最多重試一次（2026-09-24）。跟 gdelt_source 的限流重試不同：這裡的失敗多半是暫時性網路
    問題或對方伺服器偶發 5xx，不是官方限流訊息，不分析回應內容，重試前固定等
    RETRY_WAIT_SECONDS。拿到 200 且有內容就不重試。"""
    text, status = http_get(url)
    if status == 200 and text:
        return text, status
    sleep(RETRY_WAIT_SECONDS)
    return http_get(url)


# ── 解析：sitemap XML（news_sitemap／sitemap_index／site_sitemap 共用） ───────
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _url_block_to_item(url_elem) -> dict:
    loc = lastmod = title = pub_date = ""
    for child in url_elem:
        name = _local(child.tag)
        if name == "loc":
            loc = (child.text or "").strip()
        elif name == "lastmod":
            lastmod = (child.text or "").strip()
        elif name == "news":
            for nchild in child.iter():
                nname = _local(nchild.tag)
                if nname == "title" and not title:
                    title = (nchild.text or "").strip()
                elif nname == "publication_date" and not pub_date:
                    pub_date = (nchild.text or "").strip()
    return {"loc": loc, "lastmod": lastmod, "title": title, "publication_date": pub_date}


def parse_sitemap_xml(xml_text: str) -> tuple[str, list]:
    """回 (kind, payload)。kind："index"（payload 是子 sitemap 網址字串清單）／
    "urlset"（payload 是 `_url_block_to_item` 的清單）／"error"（XML 解不開或不是預期的根節點，
    payload 是 []）。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "error", []
    kind = _local(root.tag)
    if kind == "sitemapindex":
        children = []
        for sm in root:
            if _local(sm.tag) != "sitemap":
                continue
            loc = ""
            for c in sm:
                if _local(c.tag) == "loc":
                    loc = (c.text or "").strip()
            if loc:
                children.append(loc)
        return "index", children
    if kind == "urlset":
        return "urlset", [_url_block_to_item(u) for u in root if _local(u.tag) == "url"]
    return "error", []


# ── 日期／標題正規化 ─────────────────────────────────────────────────────
def _parse_dt(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    for candidate in (raw, raw.replace("Z", "+00:00")):
        try:
            dt = datetime.fromisoformat(candidate)
            break
        except ValueError:
            dt = None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_SLUG_STOP_EXT_RE = re.compile(r"\.(html?|php|aspx?|xml)$", re.I)
_SLUG_QUERY_RE = re.compile(r"[?#].*$")


def _title_from_slug(url: str) -> str:
    """sitemap 沒有 news:title 時（site_sitemap 類型），從網址最後一段猜標題。粗糙備援：
    slug 是有意義的字詞（用連字號／底線分隔）才猜得出東西，像 TrendForce 那種「日期＋流水號」
    slug（20260914-13235）猜出來也只是數字，見 data/news_sitemaps.json 的 _note。"""
    try:
        path = urllib.parse.urlsplit(url).path
    except ValueError:
        return url
    slug = _SLUG_QUERY_RE.sub("", path).rstrip("/").rsplit("/", 1)[-1]
    slug = _SLUG_STOP_EXT_RE.sub("", slug)
    words = [w for w in re.split(r"[-_]+", slug) if w]
    if not words:
        return url
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _normalize_item(block: dict, cfg: dict) -> tuple[dict, datetime | None] | None:
    url = block.get("loc") or ""
    if not url:
        return None
    title = block.get("title") or ""
    title_from_slug = False
    if not title:
        title = _title_from_slug(url)
        title_from_slug = True
    dt = _parse_dt(block.get("publication_date") or block.get("lastmod") or "")
    item = {
        "title": title.strip(), "url": url, "source_name": cfg.get("name", ""),
        "domain": _domain_of(url), "lang": cfg.get("lang", ""),
        "published_iso": dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else "",
        "title_from_slug": title_from_slug,
    }
    return item, dt


# ── 抓單一來源（三種 type 都走這支） ─────────────────────────────────────
def fetch_one_source(cfg: dict, *, http_get=None, sleep=None,
                     now=None) -> tuple[list[dict], dict]:
    """回 (items, status)。status 一定有 status（ok／empty／blocked／error）、items_seen
    （這份 sitemap 原始 <url> 筆數，篩選前）、items_recent（套用 url_filter＋48 小時窗之後）。
    被擋（403／429）或解析失敗就整個來源收手，不重試第三次、不影響其他來源（見 fetch_all）。"""
    http_get = http_get or _default_http_get
    sleep = sleep or time.sleep
    now = now or (lambda: datetime.now(timezone.utc))

    kind = cfg.get("type", "news_sitemap")
    max_age = float(cfg.get("max_age_hours") or DEFAULT_MAX_AGE_HOURS)
    url_filter = re.compile(cfg["url_filter"]) if cfg.get("url_filter") else None
    cutoff = now() - timedelta(hours=max_age)

    def _fetch_blocks(url: str) -> tuple[str, list, int | None]:
        text, status = _fetch_with_retry(url, http_get, sleep)
        if status in (403, 429):
            return "blocked", [], status
        if not text or status != 200:
            return "error", [], status
        parsed_kind, payload = parse_sitemap_xml(text)
        return parsed_kind, payload, status

    root_kind, payload, status_code = _fetch_blocks(cfg["url"])
    if root_kind in ("blocked", "error"):
        return [], {"status": root_kind, "http_status": status_code, "items_seen": 0, "items_recent": 0}

    blocks: list[dict] = []
    if root_kind == "index":
        if kind != "sitemap_index":
            return [], {"status": "error", "http_status": status_code, "items_seen": 0, "items_recent": 0,
                       "reason": "got a sitemap index, but source is not configured as sitemap_index"}
        max_children = max(1, int(cfg.get("max_children") or 1))
        children_failed = 0
        for child_url in payload[:max_children]:
            c_kind, c_payload, _c_status = _fetch_blocks(child_url)
            if c_kind == "urlset":
                blocks.extend(c_payload)
            else:
                children_failed += 1
        if not blocks and children_failed:
            return [], {"status": "blocked" if children_failed >= max_children else "error",
                       "http_status": status_code, "items_seen": 0, "items_recent": 0,
                       "children_failed": children_failed}
    elif root_kind == "urlset":
        blocks = payload
    else:
        return [], {"status": "error", "http_status": status_code, "items_seen": 0, "items_recent": 0}

    items_seen = len(blocks)
    items: list[dict] = []
    for block in blocks:
        if url_filter and not url_filter.search(block.get("loc") or ""):
            continue
        normalized = _normalize_item(block, cfg)
        if normalized is None:
            continue
        it, dt = normalized
        if dt is None or dt < cutoff:
            continue   # 沒有可用日期，或超過 max_age_hours：不採用（見檔頭）
        items.append(it)

    status = "ok" if items_seen else "empty"
    return items, {"status": status, "http_status": status_code, "items_seen": items_seen,
                   "items_recent": len(items)}


def fetch_all(configs: list[dict] | None = None, *, http_get=None, sleep=None,
             now=None) -> tuple[list[dict], dict]:
    """抓全部設定來源，一個一個來（不平行——來源數少、逐一抓對伺服器比較客氣）。單一來源出錯
    不拖垮其他來源。回 (全部近期項目, {來源名稱: status})。"""
    configs = configs if configs is not None else load_sources()
    all_items: list[dict] = []
    per_source: dict = {}
    for cfg in configs:
        name = cfg.get("name") or cfg.get("url", "?")
        try:
            items, status = fetch_one_source(cfg, http_get=http_get, sleep=sleep, now=now)
        except Exception as e:  # noqa: BLE001 — 單一來源出錯不能拖垮其他來源
            items, status = [], {"status": "error", "items_seen": 0, "items_recent": 0,
                                 "error": f"{type(e).__name__}: {e}"}
        per_source[name] = status
        all_items.extend(items)
    return all_items, per_source


# ── evidence 候選：篩選與排序 ─────────────────────────────────────────────
def filter_for_evidence(items: list[dict], matcher, routing: dict, dedup_titles: list[str],
                        dd: dict, holdings: dict) -> list[dict]:
    """標題要點到研究公司，或點到研究主題／環節辨識詞（兩者有一個就算，比 GDELT 的「公司＋
    數字或主題」寬——sitemap 來源本身就是精選媒體，不是搜尋索引，見 CLAUDE.md）；跟既有標題
    近似的丟掉；黑名單網域丟掉；依 DD／持倉公司優先 → 有公司命中優先（比只有主題命中強）→
    有數字優先 → 新的優先排序。不在這裡截斷成 max_kept——留給呼叫端（
    fetch_sitemap_candidates）截斷，好讓 quality 同時看得到「符合條件的全部」與「實際留用的」
    兩個數字。"""
    from evidence_ledger import extract_figures
    from evidence_routing import _company_tickers, _keyword_hits
    from gdelt_source import _theme_and_segment_keywords
    from news_fetcher import _near_same_title
    from source_registry import is_blacklisted

    priority_tickers = {t for t, info in (dd or {}).items() if info.get("dd_status") == "dd"}
    priority_tickers |= set((holdings or {}).get("seats") or {}) | set((holdings or {}).get("index") or {})
    kw_lists = _theme_and_segment_keywords(routing)

    seen_urls: set[str] = set()
    kept_titles: list[str] = []
    kept: list[dict] = []
    for it in items:
        title = it.get("title") or ""
        url = it.get("url") or ""
        if not title or not url or url in seen_urls:
            continue
        if is_blacklisted(it.get("domain") or "", url):
            continue
        companies = matcher.match(title)
        theme_hit = any(_keyword_hits(title, kws) for kws in kw_lists)
        if not (companies or theme_hit):
            continue   # 標題沒點到研究公司，也沒點到研究主題／環節辨識詞：不夠具體
        if any(_near_same_title(title, t) for t in dedup_titles):
            continue   # 跟早報既有新聞卡／RSS 標題撞了，不重複帶進來
        if any(_near_same_title(title, t) for t in kept_titles):
            continue
        seen_urls.add(url)
        kept_titles.append(title)
        figures = extract_figures(title)
        is_priority = any(c in priority_tickers or any(tk in priority_tickers for tk in _company_tickers(c, routing))
                          for c in companies)
        kept.append({**it, "companies": companies, "figures": figures, "has_figure": bool(figures),
                    "company_match": bool(companies), "theme_hit": theme_hit, "priority": is_priority})
    # 穩定排序，由次要到主要依序套（跟 gdelt_source.filter_and_rank 同一個寫法）：
    # 新的優先 → 有數字優先 → 公司命中優先（比只有主題命中強）→ DD／持倉公司優先
    kept.sort(key=lambda k: k["published_iso"], reverse=True)
    kept.sort(key=lambda k: k["has_figure"], reverse=True)
    kept.sort(key=lambda k: k["company_match"], reverse=True)
    kept.sort(key=lambda k: k["priority"], reverse=True)
    return kept


# ── 組成候選（跟 evidence_layer.build_candidates／gdelt_source.make_candidate 同一個 cand 形狀） ──
def make_candidate(item: dict, matcher, today: str) -> dict:
    from evidence_ledger import content_tokens, extract_event_date
    title = item["title"]
    published_iso = item.get("published_iso") or ""
    source_date = published_iso[:10] if published_iso else today
    date_info = extract_event_date(title, source_date or today) or \
        {"event_date": source_date, "date_basis": "published"}
    cid = "c_sitemap_" + hashlib.sha1(
        f"{today}|{re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()}".encode()).hexdigest()[:12]
    return {
        "also_in": [], "subjects": matcher.subjects(title), "cid": cid, "block": BLOCK_NAME,
        "priority": SITEMAP_PRIORITY, "headline": title, "text": title[:1400], "unknowns": "",
        "source": item.get("source_name") or item.get("domain", ""), "source_date": source_date,
        "published_at": published_iso,
        **date_info,
        "companies": item["companies"][:5], "figures": item["figures"], "headline_figures": item["figures"],
        "terms": matcher.terms(title), "tokens": content_tokens(title),
        "rss": [{"source": item.get("source_name", ""), "title": title, "summary": "", "url": item["url"],
                 "published": published_iso, "also_in": []}],
        "basis": {"code": "headline_summary", "display": "Headline and feed summary only, unverified"},
        # 2026-09-24：給 evidence_layer._merge_reserved_candidates 跟 GDELT 候選一起排序用
        # （「match strength」＝優先公司優先、有數字優先），不是給 Jev 或畫面用的欄位。
        "_match_priority": bool(item.get("priority")),
        "_match_has_figure": bool(item.get("has_figure")),
        "title_from_slug": bool(item.get("title_from_slug")),
    }


# ── 早報外掃描的池子：ALL 近期項目（不只標題點到公司的），轉成 RSS 條目形狀 ──────
def to_pool_items(items: list[dict]) -> list[dict]:
    """給 ideas_layer._wide_scan 用（見 CLAUDE.md「投資想法」段）：不先篩公司／主題，讓查核點
    關鍵詞比對自己去配，既有把關（過舊、ledger 已知數字、idea_hits 歷史重複、跟早報候選標題
    近似）在 _wide_scan 裡照舊套用。"""
    return [{"title": it.get("title", ""), "summary": "", "link": it.get("url", ""),
            "source": it.get("source_name", ""), "published": it.get("published_iso", "")}
           for it in items]


# ── 進入點 ───────────────────────────────────────────────────────────────
def fetch_sitemap_candidates(routing: dict, matcher, dd: dict, holdings: dict, dedup_titles: list[str],
                             today: str, *, max_kept: int = MAX_KEPT, configs: list[dict] | None = None,
                             http_get=None, sleep=None, now=None) -> tuple[list[dict], list[dict], dict]:
    """回 (evidence 候選, 早報外掃描用的完整近期新聞池, quality)。跟 gdelt_source 不同：就算
    max_kept<=0（早報候選已經用完跟 GDELT 共用的名額，見 evidence_layer.py），還是要抓——早報
    外掃描要的是「全部近期項目」，不受 evidence 候選名額限制。任何一步出錯都回空清單＋quality，
    不丟例外（呼叫端仍另外套一層 try/except，見 evidence_layer.run_evidence_layer）。"""
    quality: dict = {"enabled": True, "sources": {}, "items_seen_total": 0, "items_recent_total": 0,
                     "matched": 0, "kept": 0, "kept_titles": [], "pool_size": 0}
    try:
        cfgs = configs if configs is not None else load_sources()
        if not cfgs:
            quality["enabled"], quality["reason"] = False, "no sources configured"
            return [], [], quality
        items, per_source = fetch_all(cfgs, http_get=http_get, sleep=sleep, now=now)
        quality["sources"] = per_source
        quality["items_seen_total"] = sum(s.get("items_seen", 0) for s in per_source.values())
        quality["items_recent_total"] = sum(s.get("items_recent", 0) for s in per_source.values())
        pool_items = to_pool_items(items)
        quality["pool_size"] = len(pool_items)
        matched = filter_for_evidence(items, matcher, routing, dedup_titles, dd, holdings)
        quality["matched"] = len(matched)
        kept = matched[:max(0, max_kept)]
        quality["kept"] = len(kept)
        quality["kept_titles"] = [k["title"] for k in kept]
        cands = [make_candidate(k, matcher, today) for k in kept]
        return cands, pool_items, quality
    except Exception as e:  # noqa: BLE001 — sitemap 掛掉不能連累早報
        quality["enabled"] = False
        quality["error"] = f"{type(e).__name__}: {e}"
        return [], [], quality
