"""
evidence_calibration.py
------------------------
事件判斷層的週度自動校準（2026-09-23 新增）。

目的：不找人標記，用「後見之明」與「結果」自動回頭檢查 Jev 這週的判斷準不準。
Sonnet 二次意見只是參考，不是真相；真相來自事後的紀錄庫與市場結果。
這支永遠不改任何門檻，只寫建議；門檻要不要改，由持有人自己決定。

三個檢查（都是程式規則，不問 Jev）：
1. 事後新舊回查：Jev 這週標「新事實／進度更新」的每一則，用「跑完這週之後」更完整的
   evidence_ledger.json 重新比對一次，看有沒有更早的紀錄——這是活動層判斷當下看不到的
   資訊。也看有沒有後來的紀錄把它當「先前紀錄」引用（prior_refs 指到它），這是新事實
   確實存在過的正面證據。
2. 重要度對結果：有 ticker 的新聞看股價當天／隔一交易日的異常報酬（vs 對應市場基準，
   超過該檔 60 天日報酬標準差 2 倍才算有反應）；不分市場都看後續 3 天紀錄庫有沒有再被
   提到、之後有沒有補到官方來源。股價有沒有反應，不等於這則新聞重不重要，報告裡要講清楚。
3. Sonnet 二次意見：把同樣的窄問題（新舊、階段、直接影響哪些變數）再問一次 Claude Sonnet
   （走 Claude Code CLI headless，跟 news_fetcher._claude_search 同一種呼叫方式，不開任何
   工具），跟 Jev 的答案比對出分歧率。這條完全不呼叫付費的 Jev API。每週最多問 60 則；
   CLI 不可用就整條跳過，原因寫進報告。

版權規則（跟 evidence_fulltext.py 一樣，不能鬆）：全文只在這支程式執行時、組給 Sonnet 的
提示裡用一次，絕不寫進 calibration_{date}.json／calibration_latest.json／calibration.html。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from evidence_fulltext import fetch_fulltext
from evidence_ledger import EntityMatcher, Ledger, content_tokens, extract_figures
from evidence_questions import (
    COMPANY_VAR_IDS, MACRO_VAR_IDS, MACRO_VARIABLES, NOVELTY_DISPLAY, STAGE_DISPLAY, VARIABLES,
    VAR_LABEL, _NOVELTY, _STAGE,
)
from evidence_routing import _company_tickers, load_routing
from html_template import BASE_CSS, NAV_BLOCK_BRIEF, _esc
from ideas_layer import load_ideas

SCHEMA = "evidence-calibration-v1"
SITE_DATA_URL = "https://research.investmquest.com/briefing/data"

WEEK_DAYS = 7                    # 檢查最近幾天的項目
HINDSIGHT_JACCARD_MIN = 0.30     # 比活動層 Ledger.find_prior 的 0.20 更嚴（見 evidence_ledger.py）
STALE_GAP_DAYS = 3               # 跟 evidence_layer.STALE_EVENT_DAYS 一致：event_date 比「當天」早這麼多天算可疑
NOVELTY_CONF_BUCKETS = [(0.6, 0.8), (0.8, 0.9), (0.9, 1.0)]
MIN_SAMPLE_FOR_SUGGESTION = 30   # 少於這個數，報告只說樣本太小，不建議數字
MIN_BUCKET_N = 5                 # 單一信心區間至少要有幾則才拿來算佔比

IMPORTANCE_HIGH = 2.5
IMPORTANCE_LOW = 1.5
MAX_TICKERS_PER_ITEM = 3
MARKET_STDEV_LOOKBACK = 60       # 交易日
MARKET_FLAG_MULT = 2.0
FOLLOWUP_WINDOW_DAYS = 3

SONNET_MODEL = os.environ.get("CALIBRATION_MODEL", "sonnet")
SONNET_MAX_ITEMS = 60
SONNET_TIMEOUT = int(os.environ.get("CALIBRATION_TIMEOUT", "240"))

# 投資想法校準（Task 2，2026-09-23 晚新增；2026-09-24 改版：判斷不再是 Jev，是同一次執行內
# Claude Opus 讀原文判斷，見 ideas_layer.py 檔頭——這裡不再問 Sonnet 二次意見，「keyword
# precision」直接看當天判斷結果的無關佔比，見檔尾「投資想法校準」段）
IDEA_UNRELATED_FLAG_SHARE = 0.5   # 無關佔比達到這個門檻才建議「關鍵詞可能太寬」
IDEA_MIN_SAMPLE = 5               # 單一查核點至少要有幾對才拿來算佔比、寫進建議
_IDEA_VERDICT_ZH = {"supports": "支持", "refutes": "推翻", "shaky": "動搖", "neutral": "中性",
                    "unrelated": "無關"}

VAR_DEFS = {v: d for v, _, d in VARIABLES + MACRO_VARIABLES}

_CALIBRATION_GUARD = """
[EXECUTION ENVIRONMENT] You are inside an unattended weekly calibration job. Nobody will reply to you.
- Output exactly one valid JSON object, from `{` to `}`, with no preamble, heading, or markdown code fence.
- Do not use any tools. Do not browse. Answer only from the material given in this message.
- If the material is too thin to tell, still choose the closest label; never ask a question.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gap_days(a: str, b: str) -> int | None:
    """a 減 b 差幾天（只取前 10 碼 YYYY-MM-DD）；算不出來回 None。"""
    try:
        return (datetime.strptime(a[:10], "%Y-%m-%d") - datetime.strptime(b[:10], "%Y-%m-%d")).days
    except (TypeError, ValueError):
        return None


# ── 取資料 ───────────────────────────────────────────────────────────────
def _fetch_json(url: str, timeout: int = 15):
    """回 (payload, status)。status：'ok'／'missing'（404）／'error:<型別>'。跟 evidence_layer 同約定。"""
    try:
        import requests
        r = requests.get(url, timeout=timeout)
        if r.status_code == 404:
            return None, "missing"
        r.raise_for_status()
        return r.json(), "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


def _dates_back(end_date: str, days: int) -> list[str]:
    """end_date 之前的 days 天（不含 end_date 本身），由舊到新。"""
    end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    return [(end - timedelta(days=i)).isoformat() for i in range(days, 0, -1)]


def collect_week_items(today: str, *, fetch=_fetch_json, days: int = WEEK_DAYS,
                       site: str = SITE_DATA_URL) -> tuple[list[dict], list[dict]]:
    """抓最近 days 天的 evidence_{date}.json，把每則 item 附上它所屬那天的日期。
    某天沒有檔案（例如週日沒出早報）就記 missing，不擋其他天。"""
    dates = _dates_back(today, days)
    items, day_reports = [], []
    for d in dates:
        payload, status = fetch(f"{site}/evidence_{d}.json")
        n = 0
        if status == "ok" and isinstance(payload, dict):
            for it in payload.get("items") or []:
                if isinstance(it, dict):
                    items.append({**it, "date": payload.get("date") or d})
                    n += 1
        day_reports.append({"date": d, "status": status, "items": n})
    return items, day_reports


def load_ledger_records(*, fetch=_fetch_json, site: str = SITE_DATA_URL) -> tuple[list[dict], str]:
    payload, status = fetch(f"{site}/evidence_ledger.json")
    if status == "ok":
        return Ledger.from_json(payload, True, "site ledger").records, "ok"
    return [], status


# ── 檢查①：事後新舊回查 ─────────────────────────────────────────────────
def _ledger_entities(rec: dict) -> set:
    return set(rec.get("companies") or []) | set(rec.get("subjects") or [])


def _item_entities(item: dict) -> set:
    return ({c.get("key") for c in item.get("companies") or [] if c.get("key")}
            | {t.get("key") for t in item.get("topics") or [] if t.get("key")})


def _find_earlier_match(item: dict, ledger_records: list[dict], matcher: EntityMatcher | None,
                        jaccard_min: float = HINDSIGHT_JACCARD_MIN) -> dict | None:
    """比活動層 Ledger.find_prior 更嚴、更徹底：不看分數地板，只認「日期確定在候選之前」的
    紀錄；公司／主題要有交集，再加數字重疊、關鍵詞重疊，或字詞 Jaccard 達門檻才算同一件事。
    用的是「現在」完整的 ledger（比判斷當天多了之後幾天的紀錄），這正是事後回查的重點。"""
    item_date = item.get("date") or item.get("source_date") or ""
    fkey = item.get("fact_key")
    headline = item.get("headline", "")
    entities = _item_entities(item)
    # 2026-09-23：extract_figures 讀「3.75-4.00%」只拿到 4%，先把範圍補成「3.75%-4.00%」
    figs = set(extract_figures(re.sub(r"(\d(?:\.\d+)?)\s*[-–]\s*(\d(?:\.\d+)?)%", r"\1%-\2%", headline)))
    toks = content_tokens(headline)
    terms = set(matcher.terms(headline)) if matcher else set()
    best = None
    for r in ledger_records:
        if fkey and r.get("fact_key") == fkey:
            continue
        r_date = r.get("first_seen") or r.get("event_date") or ""
        if not r_date or not item_date or r_date >= item_date:
            continue
        if not (entities & _ledger_entities(r)):
            continue
        shared_f = figs & set(r.get("figures") or [])
        shared_term = terms & set(r.get("terms") or [])
        r_toks = set(r.get("tokens") or [])
        union = toks | r_toks
        jac = len(toks & r_toks) / len(union) if union else 0.0
        # 2026-09-23：只共用一個關鍵詞（如 chip exports）或一個數字太鬆，9/23 回放把「韓國 9 月晶片出口」
        # 對到 8/19 的川習會新聞（用字重疊 0）。改成至少兩個訊號：每個共同數字各算一個（最多兩個，
        # 中文紀錄對英文標題時只有數字對得上，例如 Fed 升息的 3.75%／4.00%）、關鍵詞一個、用字重疊一個
        if min(len(shared_f), 2) + bool(shared_term) + (jac >= jaccard_min) < 2:
            continue
        score = 2 * len(shared_f) + len(shared_term) + jac
        if best is None or score > best[0]:
            best = (score, r, sorted(shared_f), round(jac, 3))
    if best is None:
        return None
    _, r, shared_f, jac = best
    return {"record": r, "shared_figures": shared_f, "jaccard": jac}


def _cited_by_later(item: dict, ledger_records: list[dict]) -> list[str]:
    """後來（比 item 的日期晚）有哪些紀錄把 item 的 fact_key 列為 prior_refs：這代表 item
    真的是後續事件引用的「先前事實」，是新事實確實存在過的正面證據。回日期，由舊到新。"""
    fkey = item.get("fact_key")
    item_date = item.get("date") or ""
    if not fkey:
        return []
    dates = sorted(r.get("first_seen") or "" for r in ledger_records
                   if fkey in (r.get("prior_refs") or []) and (r.get("first_seen") or "") > item_date)
    return dates


def hindsight_check(item: dict, ledger_records: list[dict], matcher: EntityMatcher | None) -> dict:
    """回 {"label": confirmed_new/actually_old/unclear, "reason": str, "matched_fact_key": str|None}。"""
    match = _find_earlier_match(item, ledger_records, matcher)
    if match:
        r = match["record"]
        outlet = ", ".join(sorted({s.get("source", "") for s in (r.get("sources") or []) if s.get("source")}))
        why = "shared figures" if match["shared_figures"] else f"word overlap {match['jaccard']}"
        return {"label": "actually_old", "matched_fact_key": r.get("fact_key"),
                "reason": f"Earlier record found, first seen {r.get('first_seen') or r.get('event_date')}"
                          f"{f' ({outlet})' if outlet else ''}; matched by {why}."}
    restated = _cited_by_later(item, ledger_records)
    if restated:
        return {"label": "confirmed_new", "matched_fact_key": None,
                "reason": f"Cited as the earlier record by {len(restated)} later ledger entr"
                          f"{'y' if len(restated) == 1 else 'ies'}, starting {restated[0]}."}
    gap = _gap_days(item.get("date") or "", item.get("event_date") or "")
    if gap is not None and gap > STALE_GAP_DAYS:
        return {"label": "unclear", "matched_fact_key": None,
                "reason": f"Event dated {gap} days before it was reported as new; "
                          "no matching earlier ledger record found to confirm or refute."}
    return {"label": "confirmed_new", "matched_fact_key": None,
            "reason": "No earlier ledger record found and no contradicting signal."}


def _in_bucket(x: float, lo: float, hi: float) -> bool:
    return lo <= x <= hi if hi >= 1.0 else lo <= x < hi


def aggregate_hindsight(checks: list[dict]) -> dict:
    """checks：每則 {"confidence": float|None, "label": str}。依 Jev 信心分三區，算 actually_old 佔比。"""
    buckets = []
    for lo, hi in NOVELTY_CONF_BUCKETS:
        sel = [c for c in checks if c["confidence"] is not None and _in_bucket(c["confidence"], lo, hi)]
        n = len(sel)
        old = sum(1 for c in sel if c["label"] == "actually_old")
        buckets.append({"range": f"{lo:.1f}-{hi:.1f}", "lo": lo, "hi": hi, "n": n, "actually_old": old,
                        "actually_old_share": round(old / n, 3) if n else None})
    return {
        "buckets": buckets, "n_total": len(checks),
        "n_actually_old": sum(1 for c in checks if c["label"] == "actually_old"),
        "n_confirmed_new": sum(1 for c in checks if c["label"] == "confirmed_new"),
        "n_unclear": sum(1 for c in checks if c["label"] == "unclear"),
    }


def suggest_novelty_min_conf(agg: dict, *, min_bucket_n: int = MIN_BUCKET_N,
                             max_share: float = 0.10) -> dict:
    """建議 NOVELTY_MIN_CONF：actually_old 佔比不超過 10% 的最低信心區間。只是建議，不會自動套用。"""
    if agg["n_total"] < MIN_SAMPLE_FOR_SUGGESTION:
        return {"suggested": None, "reason": f"Only {agg['n_total']} new/progress items this week; "
                "under 30, so no threshold number is suggested."}
    candidates = [b for b in agg["buckets"] if b["n"] >= min_bucket_n and b["actually_old_share"] is not None
                 and b["actually_old_share"] <= max_share]
    if not candidates:
        return {"suggested": None, "reason": "No confidence bucket with enough items "
                f"(at least {min_bucket_n}) stayed at or under a {max_share:.0%} actually-old share this week."}
    best = min(candidates, key=lambda b: b["lo"])
    return {"suggested": best["lo"], "reason": f"Bucket {best['range']} had {best['n']} items, "
            f"{best['actually_old_share']:.0%} later found to be old — at or under the {max_share:.0%} bar."}


# ── 檢查②：重要度對結果 ─────────────────────────────────────────────────
_TICKER_RE = re.compile(r"^\^?[A-Z0-9]{1,8}(\.[A-Z]{1,3})?$")


def _looks_like_ticker(t: str) -> bool:
    return bool(t) and bool(_TICKER_RE.fullmatch(t)) and not t.isdigit()


def _benchmark_for(ticker: str) -> str:
    if ticker.endswith(".TW") or ticker.endswith(".TWO"):
        return "0050.TW"
    if ticker.endswith(".T"):
        return "^N225"
    if ticker.endswith(".KS"):
        return "^KS11"
    return "SPY"


def tickers_for_item(item: dict, routing: dict) -> list[str]:
    """經 DD／持倉／公司對照表三條路徑找 ticker（沿用 evidence_routing 的 route() 結果與
    _company_tickers），只留看起來像 yfinance 代碼的（見 _looks_like_ticker）。"""
    out = []
    for d in (item.get("routes") or {}).get("dd") or []:
        if d.get("ticker"):
            out.append(d["ticker"])
    for h in (item.get("routes") or {}).get("holdings") or []:
        if h.get("position"):
            out.append(h["position"])
    for c in item.get("companies") or []:
        if c.get("role") == "party":
            out.extend(_company_tickers(c["key"], routing))
    seen, result = set(), []
    for t in out:
        if t and t not in seen and _looks_like_ticker(t):
            seen.add(t)
            result.append(t)
    return result


def _default_price_fetch(ticker: str, period: str = "4mo") -> list[tuple[str, float]] | None:
    """yfinance 收盤價，由舊到新。跟 news_fetcher._download_symbols 同一種下載方式。"""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    except Exception:  # noqa: BLE001
        return None
    if df is None or df.empty:
        return None
    close = df["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    closes = close.dropna().astype(float)
    return [(d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d)[:10], float(v))
           for d, v in closes.items()]


def _returns(history: list[tuple[str, float]] | None) -> list[tuple[str, float]]:
    if not history:
        return []
    out = []
    for i in range(1, len(history)):
        prev, cur = history[i - 1][1], history[i][1]
        if prev:
            out.append((history[i][0], cur / prev - 1))
    return out


def _stdev(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return var ** 0.5


def market_reaction(ticker: str, event_date: str, *, price_fetch=None,
                    lookback: int = MARKET_STDEV_LOOKBACK, flag_mult: float = MARKET_FLAG_MULT) -> dict:
    """事件日與隔一交易日，相對市場基準的異常報酬；超過該檔 60 天日報酬標準差的 flag_mult 倍
    才標記 flagged。基準：.TW 用 0050.TW、.T 用 ^N225、.KS 用 ^KS11，其餘用 SPY。"""
    price_fetch = price_fetch or _default_price_fetch
    hist = price_fetch(ticker)
    if not hist or len(hist) < 3:
        return {"ticker": ticker, "available": False, "reason": "no price history"}
    bench_ticker = _benchmark_for(ticker)
    bench_hist = price_fetch(bench_ticker) if bench_ticker != ticker else hist
    rets = _returns(hist)
    dates = [d for d, _ in rets]
    idx0 = next((i for i, d in enumerate(dates) if d >= event_date), None)
    if idx0 is None:
        return {"ticker": ticker, "available": False, "reason": "event date after available price data"}
    bench_rets = dict(_returns(bench_hist))

    def abnormal(i):
        if i is None or i >= len(rets):
            return None
        d, r = rets[i]
        b = bench_rets.get(d)
        return None if b is None else r - b

    window = [r for _, r in rets[max(0, idx0 - lookback):idx0]]
    sd = _stdev(window)
    ab_event = abnormal(idx0)
    ab_next = abnormal(idx0 + 1) if idx0 + 1 < len(rets) else None
    flagged_event = sd is not None and ab_event is not None and abs(ab_event) > flag_mult * sd
    flagged_next = sd is not None and ab_next is not None and abs(ab_next) > flag_mult * sd
    return {
        "ticker": ticker, "benchmark": bench_ticker, "available": True,
        "event_trading_date": dates[idx0],
        "abnormal_event": round(ab_event, 4) if ab_event is not None else None,
        "abnormal_next": round(ab_next, 4) if ab_next is not None else None,
        "stdev_60d": round(sd, 4) if sd is not None else None,
        "flagged_event": flagged_event, "flagged_next": flagged_next,
        "flagged": bool(flagged_event or flagged_next),
    }


def followup_and_official(item: dict, ledger_records: list[dict],
                          window_days: int = FOLLOWUP_WINDOW_DAYS) -> dict:
    """後續 3 天紀錄庫又被提到幾次（seen_dates），以及後來有沒有被一則帶官方來源的紀錄引用
    （prior_refs 指到它，而且那筆紀錄有 official_matches）。"""
    fkey = item.get("fact_key")
    item_date = item.get("date") or ""
    own = next((r for r in ledger_records if r.get("fact_key") == fkey), None)
    seen_within = 0
    if own:
        for d in own.get("seen_dates") or []:
            gap = _gap_days(d, item_date)
            if gap is not None and 0 < gap <= window_days:
                seen_within += 1
    later_official, later_official_date = False, None
    for r in ledger_records:
        if r.get("fact_key") == fkey:
            continue
        if fkey and fkey in (r.get("prior_refs") or []) and r.get("official_matches"):
            fs = r.get("first_seen") or ""
            if fs > item_date:
                later_official, later_official_date = True, fs
                break
    return {"followup_seen_within_3d": seen_within, "later_official_confirmation": later_official,
           "later_official_date": later_official_date}


def importance_bucket(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= IMPORTANCE_HIGH:
        return "high"
    if score < IMPORTANCE_LOW:
        return "low"
    return "mid"


def build_outcome_record(item: dict, ledger_records: list[dict], routing: dict, *, price_fetch=None) -> dict:
    tickers = tickers_for_item(item, routing)[:MAX_TICKERS_PER_ITEM]
    market = [market_reaction(t, item.get("event_date") or item.get("date") or "", price_fetch=price_fetch)
             for t in tickers]
    has_reaction = any(m.get("flagged") for m in market if m.get("available"))
    fu = followup_and_official(item, ledger_records)
    importance = (item.get("importance") or {}).get("score")
    return {
        "id": item.get("id"), "date": item.get("date"), "headline": item.get("headline", ""),
        "importance_score": importance, "importance_bucket": importance_bucket(importance),
        "tickers": tickers, "market": market, "has_market_reaction": has_reaction,
        "followup_seen_within_3d": fu["followup_seen_within_3d"],
        "later_official_confirmation": fu["later_official_confirmation"],
        "has_followup": bool(fu["followup_seen_within_3d"] or fu["later_official_confirmation"]),
    }


def aggregate_outcomes(records: list[dict], *, min_bucket_n: int = MIN_BUCKET_N) -> dict:
    out = {}
    for b in ("high", "mid", "low"):
        sel = [r for r in records if r["importance_bucket"] == b]
        with_data = [r for r in sel if any(m.get("available") for m in r["market"])]
        n_reaction = sum(1 for r in with_data if r["has_market_reaction"])
        n_followup = sum(1 for r in sel if r["has_followup"])
        out[b] = {
            "n_items": len(sel), "n_with_market_data": len(with_data),
            "market_reaction_rate": round(n_reaction / len(with_data), 3) if len(with_data) >= min_bucket_n else None,
            "followup_rate": round(n_followup / len(sel), 3) if len(sel) >= min_bucket_n else None,
        }
    return out


def importance_discrimination_note(agg: dict) -> str:
    """重要度分數有沒有區分力：只比 high 跟 low 兩桶的市場反應率。股價有沒有反應不等於重不重要，
    這句一定要講，不能只丟數字。"""
    high, low = agg.get("high") or {}, agg.get("low") or {}
    hr, lr = high.get("market_reaction_rate"), low.get("market_reaction_rate")
    if hr is None or lr is None:
        return ("Not enough items with market data in the high and low importance buckets this week "
                "to tell whether the score discriminates market reaction.")
    if hr > lr + 0.05:
        return (f"High-importance items showed a flagged market move {hr:.0%} of the time this week, versus "
                f"{lr:.0%} for low-importance items. The score does separate them somewhat, but a market move "
                "is not the same thing as importance: many important facts move no price, and many flagged "
                "price moves have nothing to do with the news item at hand.")
    return (f"High-importance items showed a flagged market move {hr:.0%} of the time this week, about the "
           f"same as {lr:.0%} for low-importance items. The importance score did not clearly separate market "
           "reaction this week. That does not mean the score is wrong: a market move is not the same thing "
           "as importance.")


# ── 檢查③：Sonnet 二次意見 ──────────────────────────────────────────────
_RESTRICTED_FLAG: "bool | None" = None


def _supports_restricted(cli: str) -> bool:
    global _RESTRICTED_FLAG
    if _RESTRICTED_FLAG is None:
        try:
            out = subprocess.run([cli, "-p", "--help"], capture_output=True, text=True, timeout=30)
            _RESTRICTED_FLAG = "--restricted" in (out.stdout or "") + (out.stderr or "")
        except Exception:  # noqa: BLE001
            _RESTRICTED_FLAG = False
    return _RESTRICTED_FLAG


def _cli_available() -> bool:
    return bool(shutil.which("claude")) and bool(
        os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("CLAUDE_CODE_USE_LOCAL_AUTH"))


def _var_ids_for_item(item: dict) -> list[str]:
    """跟 evidence_layer.var_ids_for 邏輯一致（不 import 每日主流程，讓這支獨立運作）。"""
    kind = item.get("kind")
    if kind == "macro":
        return list(MACRO_VAR_IDS)
    if kind == "mixed":
        return COMPANY_VAR_IDS + [v for v in MACRO_VAR_IDS if v not in COMPANY_VAR_IDS]
    return list(COMPANY_VAR_IDS)


def _parse_json(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]
    return json.loads(text)


def _second_opinion_prompts(item: dict, ft: dict, var_ids: list[str]) -> tuple[str, str]:
    """跟 Jev 同一組窄問題（新舊、階段、直接變數），criteria 直接沿用 evidence_questions
    的定義，確保問的是同一題。全文摘要只放進這裡（in-memory），不寫進任何輸出檔。"""
    var_lines = "\n".join(f"- {v}: {VAR_DEFS[v]}" for v in var_ids)
    system = (
        "You are re-checking a news classification as an independent second opinion. Judge only what the "
        "material states as fact; ignore its opinions, analysis and forecasts.\n\n"
        "NOVELTY — " + _NOVELTY["instructions"]["question"] + " " + _NOVELTY["instructions"]["note"] + "\n"
        + "\n".join(f"- {k}: {v}" for k, v in _NOVELTY["criteria"].items()) + "\n\n"
        "STAGE — " + _STAGE["instructions"] + "\n"
        + "\n".join(f"- {k}: {v}" for k, v in _STAGE["criteria"].items()) + "\n\n"
        "DIRECT VARIABLES — for each variable below, does the material state as fact a direct change in it "
        "for the companies or industry involved (not a forecast, not a general possible effect)?\n"
        + var_lines + "\n\n"
        "Reply with exactly one JSON object: "
        '{"novelty": "<one novelty label>", "stage": "<one stage label>", '
        '"direct_variables": ["<variable id>", ...]}. '
        "direct_variables lists only the ids answered yes; use an empty list if none. "
        "No other text, no markdown fences." + _CALIBRATION_GUARD
    )
    priors = item.get("last_known") or []
    prior_lines = "\n".join(
        f"- {p.get('date', '')} ({p.get('outlet', '')}): {p.get('text', '')} [figures: {p.get('figures', '')}]"
        for p in priors) or "(none recorded)"
    excerpts = "\n".join(f"- {s.get('source', '')}: {s.get('title', '')}"
                         for s in item.get("sources") or [] if s.get("title"))
    full_text = ft.get("excerpt") if ft.get("status") == "ok" else ""
    user = (
        f"HEADLINE: {item.get('headline', '')}\n"
        f"DATE: {item.get('date', '')}\n"
        f"SOURCE EXCERPTS:\n{excerpts or '(none)'}\n\n"
        f"PRIOR RECORDS (recorded before this date):\n{prior_lines}\n\n"
        + (f"FULL ARTICLE TEXT (read once for this check, not stored):\n{full_text}\n\n" if full_text else "")
        + "Answer the JSON object now."
    )
    return system, user


def _second_opinion_cli(system_prompt: str, user_prompt: str, model: str, timeout: int) -> dict:
    """跟 news_fetcher._claude_search 同一種呼叫方式：Claude Code CLI headless，不過這裡不開
    任何工具（不需要上網，材料都在提示裡），輸出純 JSON。"""
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError("claude CLI not found on PATH")
    if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("CLAUDE_CODE_USE_LOCAL_AUTH")):
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set")
    cmd = [cli, "-p", "--output-format", "json", "--model", model,
           "--system-prompt", system_prompt, "--allowed-tools", ""]
    if _supports_restricted(cli):
        cmd.insert(2, "--restricted")
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        env.pop(k, None)
    env["MAX_THINKING_TOKENS"] = "0"
    proc = subprocess.run(cmd, input=user_prompt, capture_output=True, text=True,
                          timeout=timeout, cwd="/tmp", env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {(proc.stderr or proc.stdout)[:200]}")
    envelope = json.loads(proc.stdout)
    if envelope.get("is_error") or envelope.get("subtype") != "success":
        raise RuntimeError(f"claude CLI error envelope: {str(envelope)[:200]}")
    raw = (envelope.get("result") or "").strip()
    if not raw:
        raise RuntimeError("empty result")
    return _parse_json(raw)


def _parse_second_opinion(raw: dict, var_ids: list[str]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("response is not a JSON object")
    novelty, stage, direct = raw.get("novelty"), raw.get("stage"), raw.get("direct_variables")
    if novelty not in _NOVELTY["criteria"]:
        raise ValueError(f"unrecognised novelty label: {novelty!r}")
    if stage not in _STAGE["criteria"]:
        raise ValueError(f"unrecognised stage label: {stage!r}")
    if not isinstance(direct, list):
        raise ValueError("direct_variables is not a list")
    return {"novelty": novelty, "stage": stage, "direct_variables": sorted({v for v in direct if v in var_ids})}


def _fulltext_cand(item: dict) -> dict:
    return {
        "cid": item.get("id"),
        "headline": item.get("headline", ""),
        "headline_figures": extract_figures(item.get("headline", "")),
        "rss": [{"url": s.get("url")} for s in item.get("sources") or [] if s.get("url")],
    }


def _compare_second_opinion(results: list[dict]) -> dict:
    n = len(results)
    dis_novelty = dis_stage = dis_vars = 0
    items_out = []
    for r in results:
        jev, sonnet = r["jev"], r["sonnet"]
        d_novelty = jev["novelty"] != sonnet["novelty"]
        d_stage = jev["stage"] != sonnet["stage"]
        j_vars, s_vars = set(jev["direct_variables"]), set(sonnet["direct_variables"])
        d_vars = j_vars != s_vars
        dis_novelty += d_novelty
        dis_stage += d_stage
        # 2026-09-23：變數是複選，差一個不等於完全不同；用「兩邊不重疊的比例」（1 − 交集／聯集）平均
        union = j_vars | s_vars
        dis_vars += (1 - len(j_vars & s_vars) / len(union)) if union else 0.0
        if d_novelty or d_stage or d_vars:
            items_out.append({
                "id": r["id"], "date": r["date"], "headline": r["headline"],
                "novelty": {"jev": jev["novelty"], "sonnet": sonnet["novelty"]} if d_novelty else None,
                "stage": {"jev": jev["stage"], "sonnet": sonnet["stage"]} if d_stage else None,
                "direct_variables": {"jev": sorted(j_vars), "sonnet": sorted(s_vars)} if d_vars else None,
            })
    rates = {
        "novelty": round(dis_novelty / n, 3) if n else None,
        "stage": round(dis_stage / n, 3) if n else None,
        "direct_variables": round(dis_vars / n, 3) if n else None,
    }
    return {"rates": rates, "items": items_out}


def run_second_opinion(items: list[dict], *, cli_call=None, max_items: int = SONNET_MAX_ITEMS,
                       model: str | None = None, timeout: int = SONNET_TIMEOUT,
                       full_text_fetch=None) -> dict:
    model = model or SONNET_MODEL
    if cli_call is None and not _cli_available():
        return {"status": "skipped", "reason": "claude CLI not found or CLAUDE_CODE_OAUTH_TOKEN not set",
               "model": model, "attempted": 0, "checked": 0, "errors": [],
               "disagreement_rate": {}, "disagreements": []}
    call = cli_call or _second_opinion_cli
    targets = items[:max_items]
    full_text_fetch = full_text_fetch or fetch_fulltext
    cands = [_fulltext_cand(it) for it in targets]
    fulltext = full_text_fetch(cands, max_candidates=len(cands)) if cands else {}
    results, errors = [], []
    for it in targets:
        ft = fulltext.get(it.get("id")) or {}
        var_ids = _var_ids_for_item(it)
        try:
            sys_p, user_p = _second_opinion_prompts(it, ft, var_ids)
            raw = call(sys_p, user_p, model, timeout)
            parsed = _parse_second_opinion(raw, var_ids)
        except Exception as e:  # noqa: BLE001 — 單則失敗不擋其他則
            errors.append({"id": it.get("id"), "error": f"{type(e).__name__}: {str(e)[:160]}"})
            continue
        jev = {
            "novelty": (it.get("classification") or {}).get("jev_label"),
            "stage": (it.get("stage") or {}).get("label"),
            "direct_variables": sorted(v["var"] for v in ((it.get("variables") or {}).get("direct") or [])),
        }
        results.append({"id": it.get("id"), "date": it.get("date"), "headline": it.get("headline", ""),
                        "jev": jev, "sonnet": parsed})
    comparison = _compare_second_opinion(results)
    status = "judged" if results else ("all_failed" if targets else "no_items")
    return {"status": status, "model": model, "attempted": len(targets), "checked": len(results),
           "errors": errors[:10], "disagreement_rate": comparison["rates"], "disagreements": comparison["items"]}


# ── 檢查④：投資想法校準（Task 2，2026-09-23 晚新增；2026-09-24 改版） ───────────────────
# 不找人標記，用這週每天的 evidence_{date}.json 裡已經留著的每一對 (新聞, 查核點) 判斷（含
# 「無關」——ideas_layer.run_ideas_step 只把 unrelated 排除在 idea_hits.json 累加檔外，當天的
# evidence JSON 本身一律留著，見 briefing/ideas_layer.py 檔頭）。跟事件判斷層本體的校準同一個
# 精神：只寫建議（哪個查核點關鍵詞可能太寬），永遠不自動改 ideas.json；門檻要不要動由持有人
# 自己看了決定。2026-09-24 owner 決定：判斷從「隔天 05:15 深度查核」改成「同一次早報執行內
# Claude Opus 讀原文判斷」，所以這裡的「keyword precision」＝同一次執行判斷出來的無關佔比
# （1－unrelated_share），不再問 Sonnet 二次意見（沒有 Jev 判斷可以二次確認）。research.json
# 的 candidate_reviews（另一條完全獨立的雲端 routine idea-watch-auto 如果有寫）只當可選的
# 交叉比對參考，見 cross_check_candidate_reviews，沒有就整段標 unavailable，不擋主要指標。
def collect_week_idea_pairs(today: str, *, fetch=_fetch_json, days: int = WEEK_DAYS,
                            site: str = SITE_DATA_URL) -> tuple[list[dict], list[dict]]:
    """抓最近 days 天的 evidence_{date}.json，把每一對 (新聞, 查核點) 判斷攤平成一列，含
    unrelated（跟 collect_week_items 給事件判斷層本體檢查①②用的目的不同，那支不看 ideas）。
    早報候選的列在 items[].ideas（origin 欄位回填成 "briefing"）；早報外的列在
    ideas.wide_pairs（只有真的判斷過的才會出現，見 ideas_layer.py）。"candidate"（判斷步驟
    失敗時的退回狀態）跟舊版的 unjudged 一樣：沒有真的判斷過，校準不算它。"""
    dates = _dates_back(today, days)
    pairs, day_reports = [], []
    for d in dates:
        payload, status = fetch(f"{site}/evidence_{d}.json")
        n = 0
        if status == "ok" and isinstance(payload, dict):
            date_ = payload.get("date") or d
            for it in payload.get("items") or []:
                if not isinstance(it, dict):
                    continue
                src_url = next((s.get("url") for s in it.get("sources") or [] if s.get("url")), "")
                for h in it.get("ideas") or []:
                    if h.get("verdict") not in _IDEA_VERDICT_ZH:
                        continue   # candidate／unjudged：沒真的判斷過，校準不算它
                    pairs.append({**h, "origin": h.get("origin") or "briefing", "date": date_,
                                 "headline": it.get("headline", ""), "url": h.get("url") or src_url})
                    n += 1
            for p in ((payload.get("ideas") or {}).get("wide_pairs")) or []:
                if p.get("verdict") not in _IDEA_VERDICT_ZH:
                    continue
                pairs.append({**p, "origin": "wide", "date": date_})
                n += 1
        day_reports.append({"date": d, "status": status, "pairs": n})
    return pairs, day_reports


def idea_checkpoint_defs(ideas: list[dict]) -> dict[tuple[str, str], dict]:
    """(idea_id, checkpoint_id) → 想法簡稱／查核點標籤／supports_if／refutes_if，給畫面渲染
    查表用（跟 ideas_layer._catalog 分開：那支只給 news.html 用，不含 supports_if／
    refutes_if）。"""
    out = {}
    for idea in ideas or []:
        short = idea.get("short") or idea.get("title") or idea.get("id", "")
        for cp in idea.get("checkpoints") or []:
            out[(idea.get("id", ""), cp.get("id", ""))] = {
                "idea_short": short, "label": cp.get("label", ""),
                "supports_if": cp.get("supports_if", ""), "refutes_if": cp.get("refutes_if", ""),
            }
    return out


_VERDICT_COUNT_KEYS = ("supports", "refutes", "shaky", "neutral", "unrelated")


def aggregate_idea_hits(pairs: list[dict], defs: dict, *, min_n: int = IDEA_MIN_SAMPLE,
                        flag_share: float = IDEA_UNRELATED_FLAG_SHARE) -> dict:
    """依 (idea, checkpoint) 分組：supports／refutes／shaky／neutral／unrelated 則數、無關佔比
    （＝「關鍵詞精準度」的補數，1－unrelated_share）、早報候選／早報外各幾則。無關佔比達門檻
    （且樣本數夠）才建議「關鍵詞可能太寬」，只建議不動 ideas.json。"""
    by_cp: dict[tuple[str, str], dict] = {}
    idea_shorts: dict[str, str] = {}
    for p in pairs:
        key = (p.get("idea", ""), p.get("checkpoint", ""))
        row = by_cp.setdefault(key, {k: 0 for k in _VERDICT_COUNT_KEYS} | {"briefing": 0, "wide": 0})
        v = p.get("verdict")
        if v in _VERDICT_COUNT_KEYS:
            row[v] += 1
        origin = p.get("origin") or "briefing"
        if origin in ("briefing", "wide"):
            row[origin] += 1
        idea_shorts[p.get("idea", "")] = defs.get(key, {}).get("idea_short") or p.get("idea", "")

    by_checkpoint, suggestions = [], []
    for (idea_id, cp_id), counts in sorted(by_cp.items()):
        n = sum(counts[k] for k in _VERDICT_COUNT_KEYS)
        share = round(counts["unrelated"] / n, 3) if n else None
        precision = round(1 - share, 3) if share is not None else None
        meta = defs.get((idea_id, cp_id), {})
        by_checkpoint.append({"idea": idea_id, "idea_short": meta.get("idea_short") or idea_shorts.get(idea_id, idea_id),
                              "checkpoint": cp_id, "checkpoint_label": meta.get("label", cp_id),
                              "n": n, "unrelated_share": share, "keyword_precision": precision, **counts})
        if n >= min_n and share is not None and share >= flag_share:
            suggestions.append(f"{cp_id}（{meta.get('label', cp_id)}）關鍵詞可能太寬：這週 {n} 對裡 "
                              f"{share:.0%} 被判無關")

    by_idea_counts: dict[str, dict] = {}
    for p in pairs:
        idea_id = p.get("idea", "")
        row = by_idea_counts.setdefault(idea_id, {k: 0 for k in _VERDICT_COUNT_KEYS})
        v = p.get("verdict")
        if v in row:
            row[v] += 1
    by_idea = [{"idea": idea_id, "idea_short": idea_shorts.get(idea_id, idea_id),
               "n": sum(c.values()),
               "unrelated_share": round(c["unrelated"] / sum(c.values()), 3) if sum(c.values()) else None, **c}
              for idea_id, c in sorted(by_idea_counts.items())]
    return {"by_checkpoint": by_checkpoint, "by_idea": by_idea, "suggestions": suggestions}


def cross_check_candidate_reviews(pairs: list[dict], *, fetch=_fetch_json) -> dict:
    """可選的交叉比對（2026-09-24 新增）：跟 research.json 的 candidate_reviews（如果有）比對，
    當第二個獨立的「關鍵詞準不準」參考數字——不是主要指標。主要指標是同一次執行 Claude Opus
    判斷出來的無關佔比（見 aggregate_idea_hits 的 keyword_precision），research.json 是另一條
    完全獨立的雲端 routine（idea-watch-auto，每天 05:15 台北，事後查核）寫的，兩邊不一定一致，
    僅供對照。用 (url, idea, checkpoint) 比對這週的候選；沒有 candidate_reviews 欄位就整段標
    unavailable，不擋其他校準（見 CLAUDE.md）。"""
    from ideas_layer import load_research
    research_data, status = load_research(fetch)
    if status != "ok" or not isinstance(research_data, dict):
        return {"status": "unavailable", "reason": "research.json not available"}
    reviews = research_data.get("candidate_reviews")
    if not isinstance(reviews, list) or not reviews:
        return {"status": "unavailable", "reason": "no candidate_reviews in research.json"}
    review_by_key = {}
    for r in reviews:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        review_by_key[(r["url"], r.get("idea", ""), r.get("checkpoint", ""))] = r.get("verdict")
    matched = unrelated = 0
    for p in pairs:
        key = (p.get("url") or "", p.get("idea", ""), p.get("checkpoint", ""))
        v = review_by_key.get(key)
        if v is None:
            continue
        matched += 1
        if v == "unrelated":
            unrelated += 1
    if not matched:
        return {"status": "no_overlap", "matched": 0}
    return {"status": "ok", "matched": matched, "unrelated": unrelated,
           "unrelated_share": round(unrelated / matched, 3)}


def run_idea_calibration(today: str, *, fetch=_fetch_json, days: int = WEEK_DAYS,
                         ideas: list[dict] | None = None) -> dict:
    if ideas is None:
        ideas, status = load_ideas(fetch)
    else:
        status = "ok"
    if status != "ok":
        return {"status": status, "checked": 0, "by_checkpoint": [], "by_idea": [], "suggestions": [],
               "candidate_reviews": {"status": "unavailable", "reason": "ideas.json not available"},
               "day_reports": []}
    defs = idea_checkpoint_defs(ideas)
    pairs, day_reports = collect_week_idea_pairs(today, fetch=fetch, days=days)
    agg = aggregate_idea_hits(pairs, defs)
    cross_check = cross_check_candidate_reviews(pairs, fetch=fetch)
    return {"status": "ok", "checked": len(pairs), "by_checkpoint": agg["by_checkpoint"],
           "by_idea": agg["by_idea"], "suggestions": agg["suggestions"], "candidate_reviews": cross_check,
           "day_reports": day_reports}


# ── 主流程 ───────────────────────────────────────────────────────────────
def run_calibration(today: str, *, fetch=_fetch_json, days: int = WEEK_DAYS, price_fetch=None,
                    cli_call=None, sonnet_max_items: int = SONNET_MAX_ITEMS, routing: dict | None = None,
                    full_text_fetch=None, ideas: list[dict] | None = None) -> dict:
    routing = routing or load_routing()
    matcher = EntityMatcher(routing)
    items, day_reports = collect_week_items(today, fetch=fetch, days=days)
    ledger_records, ledger_status = load_ledger_records(fetch=fetch)
    judged_items = [it for it in items if (it.get("classification") or {}).get("jev_label")]

    # 檢查①
    novelty_items = [it for it in judged_items
                     if it["classification"]["jev_label"] in ("new_fact", "progress_update")]
    hindsight_checks = []
    for it in novelty_items:
        r = hindsight_check(it, ledger_records, matcher)
        hindsight_checks.append({"id": it["id"], "date": it.get("date"), "headline": it.get("headline", ""),
                                 "confidence": it["classification"].get("confidence"),
                                 "label": r["label"], "reason": r["reason"]})
    hindsight_agg = aggregate_hindsight(hindsight_checks)
    novelty_suggestion = suggest_novelty_min_conf(hindsight_agg)

    # 檢查②
    outcome_records = [build_outcome_record(it, ledger_records, routing, price_fetch=price_fetch)
                       for it in judged_items]
    outcome_agg = aggregate_outcomes(outcome_records)
    importance_note = importance_discrimination_note(outcome_agg)

    # 檢查③
    second_opinion = run_second_opinion(judged_items, cli_call=cli_call, max_items=sonnet_max_items,
                                        full_text_fetch=full_text_fetch)

    # 檢查④：投資想法校準（見上方「檢查④」段落）
    idea_calibration = run_idea_calibration(today, fetch=fetch, days=days, ideas=ideas)

    return {
        "schema": SCHEMA, "date": today, "generated_at": _now_iso(),
        "week": {"dates": [d["date"] for d in day_reports],
                "days_with_data": sum(1 for d in day_reports if d["items"]),
                "days_checked": len(day_reports), "day_reports": day_reports},
        "sample_size": len(items), "judged_sample_size": len(judged_items),
        "ledger": {"status": ledger_status, "records": len(ledger_records)},
        "hindsight_novelty": {
            "checked": len(hindsight_checks), "buckets": hindsight_agg["buckets"],
            "totals": {"actually_old": hindsight_agg["n_actually_old"],
                      "confirmed_new": hindsight_agg["n_confirmed_new"], "unclear": hindsight_agg["n_unclear"]},
            "items": hindsight_checks,
        },
        "outcomes": {"checked": len(outcome_records), "by_importance": outcome_agg,
                    "note": importance_note, "items": outcome_records},
        "second_opinion": second_opinion,
        "ideas": idea_calibration,
        "suggestions": {
            "novelty_min_conf": novelty_suggestion,
            "importance_discrimination": importance_note,
            "note": "These are suggestions only. This report never changes any threshold automatically; "
                    "a person decides whether to act on them.",
        },
    }


# ── HTML 頁面（docs/briefing/calibration.html） ────────────────────────
def _page_shell(title: str, date: str, content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta name="robots" content="noindex,nofollow">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)} &mdash; {_esc(date)}</title>
<style>
{BASE_CSS}
table {{ border-collapse:collapse; }}
th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid #eee; font-size:13px; vertical-align:top; }}
th {{ color:#888; font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
.card {{ background:#FAFBFC; border:1px solid #E8E8E8; border-radius:6px; padding:14px 16px; margin-bottom:10px; }}
.note {{ font-size:12px; color:#666; line-height:1.6; }}
</style>
</head>
<body>
{NAV_BLOCK_BRIEF}
<div style="padding:20px 16px 48px;max-width:1040px;margin:0 auto;">
<div style="margin-bottom:22px;">
  <div style="font-size:9px;letter-spacing:2px;color:#888;text-transform:uppercase;margin-bottom:4px;">InvestMQuest Research</div>
  <h1 style="font-size:22px;font-weight:600;color:#1B3A5C;margin-bottom:4px;">{_esc(title)}</h1>
  <div style="font-size:12px;color:#888;">{_esc(date)}</div>
</div>
{content}
</div>
</body>
</html>"""


def _section(label: str, body: str) -> str:
    return (f'<div class="section"><div class="section-label">{_esc(label)}</div>{body}</div>')


def _pct(x: float | None) -> str:
    """百分比字串，None 顯示空白。獨立成函式是因為 Python 3.11（workflow 用的版本）不准 f-string
    裡再嵌一層用同一種引號的 f-string，寫成三元運算式塞在 f-string 裡會直接語法錯誤。"""
    return "" if x is None else f"{x:.0%}"


def _sample_section(result: dict) -> str:
    wk = result["week"]
    p = (f"這份報告檢查最近 7 天、{wk['days_with_data']} 天有出早報的資料。"
        f"這 7 天裡 Jev 一共判斷了 {result['judged_sample_size']} 則新聞，"
        f"其中 {result['hindsight_novelty']['checked']} 則被標成「新事實」或「進度更新」，"
        f"{result['outcomes']['checked']} 則有拿去對市場結果。")
    if result["judged_sample_size"] < MIN_SAMPLE_FOR_SUGGESTION:
        p += f" 樣本只有 {result['judged_sample_size']} 則，數字僅供參考，不建議照著調整門檻。"
    missing = [d["date"] for d in wk["day_reports"] if d["status"] != "ok"]
    if missing:
        p += f" 沒有資料的日期：{', '.join(missing)}。"
    return _section("樣本", f'<p class="note">{_esc(p)}</p>')


def _hindsight_section(result: dict) -> str:
    hn = result["hindsight_novelty"]
    tot = hn["totals"]
    intro = (f'Jev 這週標「新事實」或「進度更新」的有 {hn["checked"]} 則。用跑完這週之後、更完整的'
             f'紀錄庫重新查一次，{tot["actually_old"]} 則其實早就記過，{tot["confirmed_new"]} 則沒找到反證，'
             f'{tot["unclear"]} 則不確定。')
    rows = "".join(
        f'<tr><td>{_esc(b["range"])}</td><td>{b["n"]}</td><td>{b["actually_old"]}</td>'
        f'<td>{_pct(b["actually_old_share"])}</td></tr>'
        for b in hn["buckets"])
    table = (f'<table><tr><th>Jev 信心區間</th><th>則數</th><th>後來發現是舊聞</th><th>佔比</th></tr>{rows}</table>')
    old_items = [c for c in hn["items"] if c["label"] == "actually_old"][:15]
    list_html = ""
    if old_items:
        rows2 = "".join(
            f'<div class="card"><div style="font-size:13px;font-weight:500;margin-bottom:4px;">{_esc(c["headline"])}</div>'
            f'<div class="note">{_esc(c["date"])}・Jev 當時信心 {c["confidence"]}・事後查證：紀錄庫裡有更早的紀錄，'
            f'這則其實是舊聞重述。</div></div>'
            for c in old_items)
        list_html = f'<div style="margin-top:10px;">{rows2}</div>'
    sug = result["suggestions"]["novelty_min_conf"]
    if sug["suggested"] is not None:
        best = next(b for b in hn["buckets"] if b["lo"] == sug["suggested"])
        sug_txt = (f'信心區間 {best["range"]} 這週有 {best["n"]} 則，事後發現是舊聞的只有 '
                  f'{best["actually_old_share"]:.0%}，在 10% 的門檻之內。可以考慮把新舊判斷的信心門檻'
                  f'設到 {sug["suggested"]:.2f}。')
    elif hn["checked"] < MIN_SAMPLE_FOR_SUGGESTION:
        sug_txt = f'這週只有 {hn["checked"]} 則新事實／進度更新，不到 30 則，樣本太小，不建議數字。'
    else:
        sug_txt = "這週沒有任何一個信心區間（至少 5 則）把事後發現是舊聞的比例壓到 10% 以下，先不建議門檻數字。"
    return _section("事後回查：新舊判斷準不準",
                    f'<p class="note">{_esc(intro)}</p>{table}{list_html}'
                    f'<p class="note" style="margin-top:10px;">建議（只是建議，不會自動套用）：{_esc(sug_txt)}</p>')


def _outcomes_section(result: dict) -> str:
    oc = result["outcomes"]
    rows = "".join(
        f'<tr><td>{lbl}</td><td>{v["n_items"]}</td><td>{v["n_with_market_data"]}</td>'
        f'<td>{_pct(v["market_reaction_rate"])}</td>'
        f'<td>{_pct(v["followup_rate"])}</td></tr>'
        for lbl, v in (("高（≥2.5 分）", oc["by_importance"]["high"]), ("中", oc["by_importance"]["mid"]),
                       ("低（<1.5 分）", oc["by_importance"]["low"])))
    table = (f'<table><tr><th>重要度</th><th>則數</th><th>有股價可查</th>'
            f'<th>股價異常反應</th><th>後續 3 天有追蹤</th></tr>{rows}</table>')
    intro = ("重要度是 Jev 對這則新聞材料重不重要的分類把握，不是股價會不會漲。"
            "股價異常反應：事件當天或隔一個交易日，相對同市場基準的報酬超過該檔過去 60 天日報酬"
            "標準差的 2 倍。股價有沒有反應，不等於這則新聞重不重要：很多重要的事實當天股價完全沒動，"
            "很多股價異常也只是同一天剛好有別的消息。")
    high, low = oc["by_importance"]["high"], oc["by_importance"]["low"]
    hr, lr = high.get("market_reaction_rate"), low.get("market_reaction_rate")
    if hr is None or lr is None:
        note = "這週高、低重要度兩組裡，有股價可查的則數都不夠（各要至少 5 則），先不判斷分數有沒有區分力。"
    elif hr > lr + 0.05:
        note = (f"這週高重要度的新聞有 {hr:.0%} 出現股價異常反應，低重要度的只有 {lr:.0%}，"
               "分數多少有區分到。但股價有反應不等於重要，兩者不能畫等號。")
    else:
        note = (f"這週高重要度的新聞有 {hr:.0%} 出現股價異常反應，跟低重要度的 {lr:.0%} 差不多，"
               "分數這週沒有明顯區分出股價反應。這不代表分數錯，股價有沒有動本來就不等於重不重要。")
    return _section("結果驗證：重要度分數有沒有意義",
                    f'<p class="note">{_esc(intro)}</p>{table}'
                    f'<p class="note" style="margin-top:10px;">{_esc(note)}</p>')


_SKIP_REASON_ZH = {
    "claude CLI not found or CLAUDE_CODE_OAUTH_TOKEN not set": "這台機器沒有裝 Claude Code CLI，或是沒有設訂閱認證。",
}


def _novelty_zh(label: str | None) -> str:
    return NOVELTY_DISPLAY.get(label, label or "（無）")


def _stage_zh(label: str | None) -> str:
    return STAGE_DISPLAY.get(label, label or "（無）")


def _vars_zh(var_ids: list[str]) -> str:
    return "、".join(VAR_LABEL.get(v, v) for v in var_ids) if var_ids else "無"


def _second_opinion_section(result: dict) -> str:
    so = result["second_opinion"]
    if so["status"] == "skipped":
        reason = _SKIP_REASON_ZH.get(so["reason"], so["reason"])
        return _section("Sonnet 二次意見", f'<p class="note">這次跳過：{_esc(reason)}</p>')
    rates = so["disagreement_rate"]
    fail_note = f"，{len(so['errors'])} 則失敗" if so["errors"] else ""
    intro = (f'把同樣的新舊、階段、直接影響變數三個問題，再問一次 Claude Sonnet（不呼叫付費的 Jev API），'
             f'跟 Jev 的答案比對。這次問了 {so["attempted"]} 則，{so["checked"]} 則有拿到回答{fail_note}。')
    rows = "".join(f'<tr><td>{q}</td><td>{_pct(r)}</td></tr>'
                   for q, r in (("新舊判斷", rates.get("novelty")), ("事實階段", rates.get("stage")),
                                ("直接影響哪些變數（兩邊選的不重疊部分）", rates.get("direct_variables"))))
    table = f'<table><tr><th>問題</th><th>跟 Jev 不一樣的比例</th></tr>{rows}</table>'
    dis = so["disagreements"][:15]
    list_html = ""
    if dis:
        rows2 = "".join(
            f'<div class="card"><div style="font-size:13px;font-weight:500;margin-bottom:4px;">{_esc(d["headline"])}</div>'
            f'<div class="note">'
            + (f'新舊：Jev「{_esc(_novelty_zh(d["novelty"]["jev"]))}」，Sonnet「{_esc(_novelty_zh(d["novelty"]["sonnet"]))}」。'
               if d.get("novelty") else "")
            + (f'階段：Jev「{_esc(_stage_zh(d["stage"]["jev"]))}」，Sonnet「{_esc(_stage_zh(d["stage"]["sonnet"]))}」。'
               if d.get("stage") else "")
            + (f'直接影響變數：Jev「{_esc(_vars_zh(d["direct_variables"]["jev"]))}」，'
               f'Sonnet「{_esc(_vars_zh(d["direct_variables"]["sonnet"]))}」。'
               if d.get("direct_variables") else "")
            + '</div></div>'
            for d in dis)
        list_html = f'<div style="margin-top:10px;">{rows2}</div>'
    return _section("Sonnet 二次意見", f'<p class="note">{_esc(intro)}</p>{table}{list_html}')


def _ideas_calibration_section(result: dict) -> str:
    ic = result.get("ideas") or {}
    if ic.get("status") != "ok":
        return _section("投資想法校準", '<p class="note">這次沒讀到 ideas.json，跳過。</p>')
    intro = (f'這週共有 {ic["checked"]} 對「新聞、查核點」被同一次早報執行內的 Claude 判斷過'
            '（含「無關」），用來看查核點的關鍵詞會不會抓到太多不相干的新聞。「關鍵詞精準度」'
            '＝沒被判無關的佔比，數字越高代表這個查核點的關鍵詞抓得越準。')
    rows = "".join(
        f'<tr><td>{_esc(r["idea_short"])}</td><td>{_esc(r["checkpoint_label"])}</td><td>{r["n"]}</td>'
        f'<td>{r["supports"]}</td><td>{r["refutes"]}</td><td>{r["shaky"]}</td><td>{r["neutral"]}</td>'
        f'<td>{r["unrelated"]}</td><td>{_pct(r["keyword_precision"])}</td>'
        f'<td>{r["briefing"]}</td><td>{r["wide"]}</td></tr>'
        for r in ic["by_checkpoint"])
    table = (f'<table><tr><th>想法</th><th>查核點</th><th>則數</th><th>支持</th><th>推翻</th>'
            f'<th>動搖</th><th>中性</th><th>無關</th><th>關鍵詞精準度</th><th>早報候選</th>'
            f'<th>早報外</th></tr>{rows}</table>'
            if ic["by_checkpoint"] else '<p class="note">這週沒有任何一對比對到查核點。</p>')
    if ic["suggestions"]:
        items = "".join(f'<li class="note">{_esc(s)}</li>' for s in ic["suggestions"])
        sug_html = (f'<p class="note" style="margin-top:8px;">建議（只是建議，不會自動改 ideas.json，'
                   f'要不要改由人決定）：</p><ul style="margin:2px 0 0 18px;padding:0;">{items}</ul>')
    else:
        sug_html = '<p class="note" style="margin-top:8px;">這週沒有查核點的無關佔比達到門檻。</p>'

    cc = ic.get("candidate_reviews") or {"status": "unavailable"}
    if cc.get("status") == "ok":
        cc_html = (f'<p class="note" style="margin-top:10px;">可選的交叉比對：research.json 另一條'
                  f'獨立的深度查核 routine 這週覆核了 {cc["matched"]} 對，判無關 {cc["unrelated"]} 對'
                  f'（{_pct(cc["unrelated_share"])}）——僅供對照，不是主要指標，兩邊不一定一致。</p>')
    elif cc.get("status") == "no_overlap":
        cc_html = '<p class="note" style="margin-top:10px;">research.json 有 candidate_reviews，但這週沒有比對到同一則。</p>'
    else:
        cc_html = '<p class="note" style="margin-top:10px;">這次沒有 research.json 的 candidate_reviews 可以交叉比對，跳過（不影響上面的主要指標）。</p>'
    return _section("投資想法校準", f'<p class="note">{_esc(intro)}</p>{table}{sug_html}{cc_html}')


def render_calibration_html(result: dict) -> str:
    content = (_sample_section(result) + _hindsight_section(result) + _outcomes_section(result)
              + _second_opinion_section(result) + _ideas_calibration_section(result)
              + _section("怎麼用這份報告",
                         '<p class="note">這份報告每週自動產生，資料來自後見之明（後來的紀錄庫）跟市場結果，'
                         '不是人工標記，Sonnet 二次意見只是參考。報告只給建議，不會自動改任何門檻；'
                         '門檻要不要改，由人決定。</p>'))
    return _page_shell("Jev 週度校準", result["date"], content)


# ── 輸出 ─────────────────────────────────────────────────────────────────
def save_outputs(result: dict, data_dir: Path) -> list[str]:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    written = []
    body = json.dumps(result, ensure_ascii=False, indent=1)
    for fn in (f"calibration_{result['date']}.json", "calibration_latest.json"):
        (data_dir / fn).write_text(body, encoding="utf-8")
        written.append(fn)
    return written


def save_html(html_text: str, docs_dir: Path) -> str:
    docs_dir = Path(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "calibration.html"
    path.write_text(html_text, encoding="utf-8")
    return str(path)


def main() -> None:
    import pytz
    today = datetime.now(pytz.timezone("Asia/Taipei")).strftime("%Y-%m-%d")
    result = run_calibration(today)
    root = Path(__file__).resolve().parents[1]
    written = save_outputs(result, root / "docs" / "briefing" / "data")
    html_path = save_html(render_calibration_html(result), root / "docs" / "briefing")
    print(f"Saved {', '.join(written)} and {html_path}")
    print(f"Sample size: {result['sample_size']} items ({result['judged_sample_size']} judged) "
         f"across {result['week']['days_with_data']}/{result['week']['days_checked']} days with data")


if __name__ == "__main__":
    main()
