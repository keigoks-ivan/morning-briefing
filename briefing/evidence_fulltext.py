"""
evidence_fulltext.py
---------------------
事件判斷層：抓候選新聞的全文（2026-09-23 新增）。

目的：程式挑候選時原本只有標題＋feed 摘要（一兩句），現在對排序在前面的候選多抓一次
原文全文，讓 Jev 與程式規則看到比標題更多的內容。只抓最前面 MAX_FULLTEXT 則（依
build_candidates 已經排好的候選順序），每則試它 rss 條目裡的每個網址，第一個抓不到
就試下一個。

Google News 轉址連結（news.google.com/rss/articles/...）2026 年已不能直接用
HTTP 轉址拿到出版方網址，要走 googlenewsdecoder（它重放 Google 的 batchexecute
端點解碼），實測見下方 resolve_url。內文抽取用 trafilatura。兩個套件都改成函式內
延遲載入，跟本檔其他抓取模組（evidence_sources.http_text 的 requests）風格一致，
離線測試不會因為沒裝套件而炸。

版權規則（硬性，不能鬆）：全文只能在這次執行的記憶體裡用（給 Jev 判斷、比對官方
來源的數字／關鍵詞），絕對不能寫進任何輸出檔（evidence_{date}.json／
evidence_latest.json／evidence_ledger.json／jev_cache）。對外只留：解出來的網址、
網域、字數、抓取狀態，以及最多兩句、合計 300 字以內、含關鍵數字的引句
（quotes_with_figures）。呼叫端（evidence_layer.py）要確保只把 fetch_fulltext()
回傳的這些安全欄位放進 item，excerpt 只拿去組 Jev state、用完即丟。

付費牆網域（PAYWALL_DOMAINS）直接跳過，不發請求。就算抓到頁面，抽出的正文不到
MIN_CHARS 也當失敗（常見是付費牆殘影頁，只有導言）。
"""

from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, wait

from evidence_ledger import extract_figures
from evidence_sources import http_text

UA = "Mozilla/5.0 (compatible; morning-briefing research bot)"
MAX_FULLTEXT = 12          # 每次執行最多抓幾則全文，依候選順序（不是全部 24 則都抓）
FETCH_TIMEOUT = 10         # 抓網頁本文逾時秒數（≤10s／網址）
DECODE_TIMEOUT = 8         # 解 Google News 轉址逾時秒數（≤10s／網址，留一點餘裕給後面的抓取）
WALL_TIMEOUT = 60          # 整個步驟的總時間上限
MIN_CHARS = 400            # 抽出正文低於這個長度當抓取失敗（付費牆殘影頁常見）
EXCERPT_CHARS = 3000       # 給 Jev 看的全文摘要上限（只在記憶體內用，不寫進輸出檔）
QUOTE_CHARS = 300          # 對外公開的引句上限（最多兩句，合計字數）

PAYWALL_DOMAINS = {
    "ft.com", "bloomberg.com", "wsj.com", "theinformation.com", "nikkei.com",
    "barrons.com", "economist.com", "washingtonpost.com", "nytimes.com",
    "businessinsider.com", "seekingalpha.com", "thetimes.co.uk", "telegraph.co.uk",
}

_CAP_WORD_RE = re.compile(r"\b[A-Z][A-Za-z0-9&.'\-]{2,}\b")
_NUM_RE = re.compile(
    r"\d[\d,.]*\s?(?:%|percent|billion|million|thousand|trillion|bn|mn|tn|[kmbt])?", re.I)
_HEADLINE_STOP = {"the", "a", "an", "this", "that", "these", "those", "in", "on", "at", "for",
                  "with", "from", "to", "of", "and", "or", "its", "his", "her", "their"}
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def domain_of(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except ValueError:
        return ""
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def is_paywalled(url: str) -> bool:
    d = domain_of(url)
    return any(d == pd or d.endswith("." + pd) for pd in PAYWALL_DOMAINS)


def _gnews_decode(url: str) -> str | None:
    from googlenewsdecoder import gnewsdecoder
    res = gnewsdecoder(url, interval=0, timeout=DECODE_TIMEOUT)
    if isinstance(res, dict) and res.get("success"):
        return res.get("decoded_url")
    return None


def resolve_url(url: str, decode=None) -> str:
    """Google News 轉址連結解成出版方網址；不是 Google News 連結或解不出來就回原網址。"""
    if "news.google.com" not in url:
        return url
    decode = decode or _gnews_decode
    try:
        resolved = decode(url)
    except Exception:  # noqa: BLE001 — 解碼失敗不擋主流程，回原網址讓後面當一般失敗處理
        return url
    return resolved or url


def _extract_text(html: str) -> str | None:
    import trafilatura
    try:
        return trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception:  # noqa: BLE001
        return None


def window_around_headline(text: str, headline: str, limit: int = EXCERPT_CHARS) -> str:
    """全文太長時，取標題數字／公司名第一次出現的地方附近那一段，不是硬砍前 N 字。"""
    if len(text) <= limit:
        return text
    anchors = [a.strip() for a in (_NUM_RE.findall(headline) + _CAP_WORD_RE.findall(headline))
              if a.strip() and a.strip().casefold() not in _HEADLINE_STOP]
    pos = None
    for a in anchors:
        idx = text.find(a) if a[:1].isdigit() else text.casefold().find(a.casefold())
        if idx != -1:
            pos = idx
            break
    if pos is None:
        return text[:limit]
    start = max(0, min(pos - limit // 3, len(text) - limit))
    return text[start:start + limit]


def quotes_with_figures(text: str, headline_figures: list[str], limit_total: int = QUOTE_CHARS) -> list[str]:
    """最多兩句、合計不超過 limit_total 字、含標題數字的引句（對外公開用）。"""
    target = set(headline_figures or [])
    if not target:
        return []
    out, used = [], 0
    for sent in _SENT_SPLIT_RE.split(text):
        sent = sent.strip()
        if not sent or not (target & set(extract_figures(sent))):
            continue
        room = limit_total - used
        if room <= 0:
            break
        q = sent[:room]
        out.append(q)
        used += len(q)
        if len(out) >= 2:
            break
    return out


def _fetch_one(cand: dict, http_get, decode) -> dict:
    urls = [it.get("url") for it in (cand.get("rss") or []) if it.get("url")]
    if not urls:
        return {"status": "no_url"}
    first_paywall = None
    for url in urls:
        resolved = resolve_url(url, decode=decode)
        if is_paywalled(resolved):
            first_paywall = first_paywall or resolved
            continue
        html, status = http_get(resolved)
        if not html:
            continue
        text = _extract_text(html)
        if not text or len(text) < MIN_CHARS:
            continue
        return {
            "status": "ok", "url": resolved, "domain": domain_of(resolved),
            "word_count": len(text.split()),
            "excerpt": window_around_headline(text, cand.get("headline", "")),
            "quotes": quotes_with_figures(text, cand.get("headline_figures")),
            "figures": extract_figures(text),
        }
    if first_paywall:
        return {"status": "paywalled", "url": first_paywall, "domain": domain_of(first_paywall)}
    failed_url = resolve_url(urls[0], decode=decode)
    return {"status": "failed", "url": failed_url, "domain": domain_of(failed_url)}


def _default_get(url: str) -> tuple[str | None, str]:
    return http_text(url, timeout=FETCH_TIMEOUT)


def fetch_fulltext(cands: list[dict], *, http_get=None, decode=None,
                   max_candidates: int = MAX_FULLTEXT, max_workers: int = 8,
                   wall_timeout: float = WALL_TIMEOUT) -> dict[str, dict]:
    """依候選順序，最多抓 max_candidates 則的全文（並行）。回 {cid: outcome}。
    outcome 一定有 status（ok／paywalled／failed／no_url）；ok 另外有 excerpt（只給 Jev，
    呼叫端用完要丟、不可寫進輸出）、quotes（對外安全的引句）、url／domain／word_count／figures。
    整步總時間不超過 wall_timeout：逾時還沒回來的候選當失敗，不等它。"""
    http_get = http_get or _default_get
    targets = cands[:max_candidates]
    results: dict[str, dict] = {}
    if not targets:
        return results
    ex = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futs = {ex.submit(_fetch_one, c, http_get, decode): c["cid"] for c in targets}
        done, not_done = wait(list(futs), timeout=wall_timeout)
        for f in done:
            try:
                results[futs[f]] = f.result()
            except Exception:  # noqa: BLE001
                results[futs[f]] = {"status": "failed"}
        for f in not_done:
            results[futs[f]] = {"status": "failed", "reason": "timeout"}
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return results
