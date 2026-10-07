"""
new_highs.py
------------
US new-highs scan (S&P 500 + S&P 400 + Nasdaq-100), on dividend+split adjusted CLOSE.
 - ATH: close[last_date] > max(all prior closes)
 - 52w-only: not ATH and close[last_date] > max(prior closes within last 365 calendar days)
Any failure -> status "unavailable"; the briefing still goes out. See CLAUDE.md.

CLI:
  python3 briefing/new_highs.py --refresh-universe   rewrite data/us_universe_gics.json
  python3 briefing/new_highs.py                      run the scan and print a summary
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT_PATH = os.path.join(_ROOT, "data", "us_universe_gics.json")
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_SOURCES = [
    ("sp500", ["https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"]),
    ("sp400", ["https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"]),
    ("ndx", ["https://en.wikipedia.org/wiki/Nasdaq-100",
             "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"]),
]
MIN_UNIVERSE = 800
CHUNK = 200
PARTIAL_RATIO = 0.70
# Share classes whose names do not normalise to the same string.
_EXPLICIT_GROUPS = [("GOOGL", "GOOG"), ("FOXA", "FOX"), ("NWSA", "NWS"), ("BF.B", "BF.A"),
                    ("LEN", "LEN.B"), ("UHAL", "UHAL.B"), ("MOG.A", "MOG.B"), ("HEI", "HEI.A")]


# ------------------------------------------------------------------ universe
def _find_col(cols, *needles, exact=()):
    for c in cols:
        lc = str(c).strip().lower()
        if lc in exact or any(n in lc for n in needles):
            return c
    return None


def _parse_tables(tables, tier: str) -> list[dict]:
    """Pick the first table with a ticker column (+ sub-industry if available, else sector only)."""
    best = None
    for tbl in tables:
        tc = _find_col(tbl.columns, exact=("symbol", "ticker", "ticker symbol"))
        nc = _find_col(tbl.columns, exact=("security", "company", "name"))
        if tc is None or nc is None:
            continue
        sub = _find_col(tbl.columns, "sub-industry", "sub industry")
        sec = _find_col(tbl.columns, "gics sector", exact=("sector",))
        if sub is not None:
            best = (tbl, tc, nc, sec, sub)
            break
        if best is None:  # e.g. NDX table: ICB (not GICS) columns only -> sector "Other", ICB subsector as label
            best = (tbl, tc, nc, sec, _find_col(tbl.columns, "icb subsector"))
    if best is None:
        return []
    tbl, tc, nc, sec, sub = best
    out = []
    for _, r in tbl.iterrows():
        t = str(r[tc]).strip().upper()
        if not t or t == "NAN" or " " in t:
            continue
        out.append({"ticker": t, "name": str(r[nc]).strip(),
                    "sector": str(r[sec]).strip() if sec is not None else "",
                    "sub_industry": str(r[sub]).strip() if sub is not None else "",
                    "tier": tier})
    return out


def _fetch_tables(url: str):
    import pandas as pd
    req = urllib.request.Request(url, headers=_UA)
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    return pd.read_html(io.StringIO(html))


def fetch_universe_live() -> list[dict]:
    """S&P 500 / 400 rows win over Nasdaq-100 rows; NDX-only rows fall back to SP-style sector or 'Other'."""
    merged: dict[str, dict] = {}
    for tier, urls in _SOURCES:
        rows: list[dict] = []
        for url in urls:
            try:
                rows = _parse_tables(_fetch_tables(url), tier)
            except Exception:
                rows = []
            if rows:
                break
        for r in rows:
            if r["ticker"] not in merged:
                merged[r["ticker"]] = r
    for r in merged.values():
        r["sector"] = r["sector"] or OTHER_SECTOR
        r["sub_industry"] = r["sub_industry"] or "Other"
    return list(merged.values())


_YAHOO_TO_GICS = {"Technology": "Information Technology", "Healthcare": "Health Care",
                  "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
                  "Financial Services": "Financials", "Basic Materials": "Materials"}
OTHER_SECTOR = "Other (non-S&P)"


def map_yahoo_sector(name: str) -> str:
    return _YAHOO_TO_GICS.get(name, name)


def enrich_with_yahoo(rows: list[dict], info_fn=None) -> list[dict]:
    """Label non-S&P Nasdaq-100 rows via Yahoo sector/industry (mapped to GICS sector names)."""
    if info_fn is None:
        import yfinance as yf
        info_fn = lambda sym: yf.Ticker(sym).info
    for r in rows:
        if r["sector"] != OTHER_SECTOR:
            continue
        try:
            info = info_fn(yf_symbol(r["ticker"])) or {}
            sec, ind = info.get("sector"), info.get("industry")
            if sec and ind:
                r["sector"], r["sub_industry"], r["label_source"] = map_yahoo_sector(sec), ind, "yahoo"
        except Exception:
            pass
    return rows


def apply_snapshot_labels(rows: list[dict], snap_rows: list[dict]) -> list[dict]:
    """Live rows that are only 'Other' take sector/sub_industry from the snapshot when it has them."""
    by = {r["ticker"]: r for r in snap_rows}
    for r in rows:
        if r["sector"] == OTHER_SECTOR and r["ticker"] in by and by[r["ticker"]]["sector"] != OTHER_SECTOR:
            r["sector"], r["sub_industry"] = by[r["ticker"]]["sector"], by[r["ticker"]]["sub_industry"]
            r["label_source"] = by[r["ticker"]].get("label_source", "snapshot")
    return rows


def refresh_snapshot(path: str = SNAPSHOT_PATH) -> dict:
    rows = enrich_with_yahoo(fetch_universe_live())
    if len(rows) < MIN_UNIVERSE:
        raise RuntimeError(f"universe too small ({len(rows)})")
    snap = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n": len(rows), "tickers": rows}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    return snap


def load_universe(path: str = SNAPSHOT_PATH) -> tuple[list[dict], str]:
    try:
        rows = fetch_universe_live()
        if len(rows) >= MIN_UNIVERSE:
            try:
                with open(path, encoding="utf-8") as f:
                    rows = apply_snapshot_labels(rows, json.load(f)["tickers"])
            except Exception:
                pass
            return rows, "live"
    except Exception:
        pass
    with open(path, encoding="utf-8") as f:
        return json.load(f)["tickers"], "snapshot"


def yf_symbol(ticker: str) -> str:
    return ticker.replace(".", "-")


# ------------------------------------------------------------------ pure computation
def _norm_name(name: str) -> str:
    n = re.sub(r"\(.*?\)", "", str(name))
    n = re.sub(r"\b(class|series)\s+[a-z0-9]\b", "", n, flags=re.I)
    n = re.sub(r"\b(common|ordinary)\s+(stock|shares)\b", "", n, flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()


def _group_key(row: dict) -> str:
    for g in _EXPLICIT_GROUPS:
        if row["ticker"] in g:
            return "x:" + g[0]
    return "n:" + _norm_name(row["name"]) + "|" + row["sub_industry"]


def _merge_share_classes(rows: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(_group_key(r), []).append(r)
    out = []
    for g in groups.values():
        if len(g) == 1:
            out.append(g[0])
            continue
        order = next((x for x in _EXPLICIT_GROUPS if g[0]["ticker"] in x), ())
        g = sorted(g, key=lambda r: (order.index(r["ticker"]) if r["ticker"] in order else 9, r["ticker"]))
        base = dict(g[0])
        base["ticker"] = "/".join(r["ticker"] for r in g)
        base["short_history"] = any(r["short_history"] for r in g)
        out.append(base)
    return out


NEAR_PCT = 5.0
_EPS = 1e-9
HIST_N = 10


def _flags(close):
    """Per-date boolean frames from an adjusted-close frame (pure, vectorised).
    Strict comparisons; prior = earlier rows only."""
    pm_all = close.cummax().ffill().shift(1)
    # 52w window = prior closes with date > t - 365d  ->  rolling over (t-365d, t) excluding current row
    pm52 = close.rolling("365D", closed="neither", min_periods=1).max()
    pn52 = close.rolling("365D", closed="neither", min_periods=1).min()
    ok = close.notna() & pm_all.notna()
    ath = ok & (close > pm_all)
    h52 = ok & (close > pm52)          # includes ATH
    low = ok & (close < pn52)
    return pm_all, pm52, ath, h52, low, ok


def _strength(close, pm_all, ok, labels, pos):
    """Near-ATH share (ATH included) per symbol as of row `pos`. Returns {sym: bool}."""
    c = close.iloc[pos]
    p = pm_all.iloc[pos]
    mask = ok.iloc[pos]
    ratio = c / p.where(p > c, c) - 1
    return {sym: bool(ratio[sym] >= -NEAR_PCT / 100 - _EPS) for sym in close.columns
            if sym in labels and mask[sym]}


def compute_new_highs(close, labels: dict) -> dict:
    """close: DataFrame (index dates, columns yfinance symbols) of adjusted closes.
    labels: {symbol: {ticker, name, sector, sub_industry}}. Pure; no network."""
    import pandas as pd
    close = close.sort_index().dropna(how="all")
    if close.empty:
        raise ValueError("empty price frame")
    lasts = close.apply(lambda s: s.last_valid_index()).dropna()
    last = pd.Series(lasts).mode().min()      # robust: a stray later bar must not wipe out the rest (ties -> earlier)
    close = close[close.index <= last]
    pm_all, pm52, ath_f, h52_f, low_f, ok = _flags(close)
    nrows = len(close)
    prevc = close.ffill().shift(1)
    nvalid = close.notna().sum()
    L = close.iloc[-1]
    ath, h52, near, lows_sec = [], [], [], {}
    ath_s, h52_s, near_s = [], [], []
    evaluated, no_data = [], 0
    for sym, lab in labels.items():
        if sym not in close.columns or not ok.iloc[-1][sym]:
            no_data += 1
            continue
        evaluated.append(sym)
        c = float(L[sym])
        pmax = float(pm_all.iloc[-1][sym])
        row = {"ticker": lab["ticker"], "name": lab["name"], "sector": lab["sector"],
               "sub_industry": lab["sub_industry"], "close": round(c, 2),
               "chg_pct": round((c / float(prevc.iloc[-1][sym]) - 1) * 100, 2),
               "short_history": bool(nvalid[sym] - 1 < 252), "_sym": sym}
        if ath_f.iloc[-1][sym]:
            s_ = close[sym].dropna().iloc[:-1]
            row["prev_high_date"] = s_.idxmax().strftime("%Y-%m-%d")
            ath.append(row); ath_s.append(sym)
        else:
            if h52_f.iloc[-1][sym]:
                row2 = dict(row); row2["pct_below_ath"] = round((c / pmax - 1) * 100, 1)
                h52.append(row2); h52_s.append(sym)
            pct = (c / pmax - 1) * 100
            if c < pmax and pct >= -NEAR_PCT - _EPS:
                row3 = dict(row); row3["pct_below_ath"] = round(pct, 1)
                near.append(row3); near_s.append(sym)
        if low_f.iloc[-1][sym]:
            lows_sec[lab["sector"]] = lows_sec.get(lab["sector"], 0) + 1
    ath, h52, near = _merge_share_classes(ath), _merge_share_classes(h52), _merge_share_classes(near)
    key = lambda r: (r["sector"], r["sub_industry"], -r["chg_pct"], r["ticker"])
    ath.sort(key=key); h52.sort(key=key)
    near.sort(key=lambda r: (-r["pct_below_ath"], r["ticker"]))

    def counts(rows):
        d: dict[str, int] = {}
        for r in rows:
            d[r["sector"]] = d.get(r["sector"], 0) + 1
        return d

    # --- A. breadth (today + last HIST_N sessions)
    hist = []
    for i in range(max(0, nrows - HIST_N), nrows):
        hist.append({"date": close.index[i].strftime("%Y-%m-%d"),
                     "highs": int(h52_f.iloc[i].sum()), "lows": int(low_f.iloc[i].sum())})
    t = hist[-1]
    breadth = {"highs": t["highs"], "lows": t["lows"], "net": t["highs"] - t["lows"],
               "history": hist,
               "lows_by_sector": dict(sorted(lows_sec.items(), key=lambda kv: (-kv[1], kv[0])))}

    # --- D. sector strength
    now = _strength(close, pm_all, ok, labels, nrows - 1)
    prev = _strength(close, pm_all, ok, labels, nrows - 21) if nrows >= 21 else {}
    a200 = {}
    for sym in evaluated:
        v = close[sym].dropna()
        if len(v) >= 200:
            a200[sym] = bool(v.iloc[-1] > v.iloc[-200:].mean())

    def agg(group_of):
        out: dict = {}
        for sym, flag in now.items():
            g = out.setdefault(group_of(labels[sym]), {"n": 0, "near": 0, "n_prev": 0, "near_prev": 0,
                                                       "n200": 0, "above200": 0})
            g["n"] += 1; g["near"] += flag
            if sym in a200:
                g["n200"] += 1; g["above200"] += a200[sym]
        for sym, flag in prev.items():
            g = out.get(group_of(labels[sym]))
            if g is not None:
                g["n_prev"] += 1; g["near_prev"] += flag
        return out

    def pct(a, n):
        return round(100.0 * a / n, 1) if n else None

    sec_rows = []
    for name, g in agg(lambda l: l["sector"]).items():
        np_ = pct(g["near"], g["n"]); pp = pct(g["near_prev"], g["n_prev"])
        sec_rows.append({"sector": name, "n": g["n"], "near_pct": np_,
                         "delta_pp": None if pp is None else round(np_ - pp, 1),
                         "above200_pct": pct(g["above200"], g["n200"])})
    sec_rows.sort(key=lambda r: (-(r["near_pct"] or 0), r["sector"]))
    subs = [{"sub_industry": name, "n": g["n"], "near": g["near"], "near_pct": pct(g["near"], g["n"])}
            for name, g in agg(lambda l: l["sub_industry"]).items() if g["n"] >= 5]
    subs.sort(key=lambda r: (-r["near_pct"], -r["n"], r["sub_industry"]))

    log_entry = {"ath": ath_s, "high52": h52_s, "near": near_s, "universe": evaluated}
    for lst in (ath, h52, near):
        for r in lst:
            r.pop("_sym", None)
    return {"as_of": last.strftime("%Y-%m-%d"), "evaluated_n": len(evaluated), "no_data_n": no_data,
            "ath": ath, "high52": h52, "by_sector": {"ath": counts(ath), "high52": counts(h52)},
            "breadth": breadth, "near_ath": near,
            "sectors": {"rows": sec_rows, "sub_industries": subs[:5]},
            "log_entry": log_entry}


# ------------------------------------------------------------------ download
def download_closes(symbols: list[str]):
    import pandas as pd
    import yfinance as yf

    def grab(syms):
        df = yf.download(syms, period="max", auto_adjust=True, progress=False, threads=True)
        c = df["Close"]
        if not hasattr(c, "columns"):  # single symbol
            c = c.to_frame(syms[0])
        return c

    frames = []
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        try:
            frames.append(grab(chunk))
        except Exception:
            pass
    got = pd.concat(frames, axis=1) if frames else pd.DataFrame()
    got = got.loc[:, ~got.columns.duplicated()]
    failed = [s for s in symbols if s not in got.columns or got[s].dropna().empty]
    if failed:  # retry once
        try:
            r = grab(failed)
            r = r.loc[:, ~r.columns.duplicated()]
            r = r[[c for c in r.columns if not r[c].dropna().empty]]
            got = pd.concat([got.drop(columns=[c for c in r.columns if c in got.columns]), r], axis=1)
        except Exception:
            pass
    return got


# ------------------------------------------------------------------ track record
LOG_SCHEMA = "new-highs-log-v1"
LOG_URL = "https://research.investmquest.com/briefing/data/new_highs_log.json"
LATEST_URL = "https://research.investmquest.com/briefing/data/new_highs_latest.json"
HORIZONS = (5, 20, 60)


def fetch_log(url: str = LOG_URL, getter=None) -> tuple[dict | None, str]:
    """(sessions, status): 'ok' / 'missing' (404 -> start empty) / 'error:<Type>' (do not write)."""
    try:
        if getter is None:
            import requests
            getter = lambda u: requests.get(u, timeout=15)
        r = getter(url)
        if r.status_code == 404:
            # 紀錄檔 404 但 latest 已存在＝站上暫時性異常，不是第一次跑；不准從空紀錄重寫，以免洗掉歷史
            if getter(LATEST_URL).status_code == 200:
                return None, "error:LogMissingButLatestExists"
            return {}, "missing"
        r.raise_for_status()
        j = r.json()
        if j.get("schema") != LOG_SCHEMA or not isinstance(j.get("sessions"), dict):
            return None, "error:BadSchema"
        return j["sessions"], "ok"
    except Exception as e:  # noqa: BLE001
        return None, f"error:{type(e).__name__}"


def merge_log(prev_sessions: dict, as_of: str, entry: dict) -> dict:
    sessions = dict(prev_sessions)
    sessions[as_of] = entry          # same as_of overwrites -> idempotent
    return {"schema": LOG_SCHEMA, "sessions": dict(sorted(sessions.items()))}


def _mean_ret(close, i0: int, i1: int, syms: list[str]):
    cols = [s for s in syms if s in close.columns]
    if not cols:
        return None
    r = (close.iloc[i1][cols] / close.iloc[i0][cols] - 1).dropna()
    return float(r.mean()) if len(r) else None


def compute_track(sessions: dict, close) -> dict:
    """Forward returns of past lists vs same-day universe baseline. Equal weight. Pure."""
    import pandas as pd
    dates = list(sessions)
    first = dates[0] if dates else None
    idx = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(close.index)}
    rows = []
    for h in HORIZONS:
        per = {"ath": [], "high52": [], "near": [], "base": []}
        ex = {"ath": [], "high52": [], "near": []}
        n = 0
        for d, ent in sessions.items():
            i0 = idx.get(d)
            if i0 is None or i0 + h >= len(close):
                continue
            n += 1
            base = _mean_ret(close, i0, i0 + h, ent.get("universe", []))
            if base is not None:
                per["base"].append(base)
            for g in ex:
                v = _mean_ret(close, i0, i0 + h, ent.get(g, []))
                if v is not None:
                    per[g].append(v)
                    if base is not None:
                        ex[g].append((v - base, v > base))
        avg = lambda xs: (sum(xs) / len(xs)) if xs else None
        row = {"h": h, "n": n, "base": avg(per["base"])}
        for g in ex:
            row[g] = avg(per[g])
            row[g + "_excess"] = avg([e for e, _ in ex[g]])
            row[g + "_hit"] = (100.0 * sum(1 for _, w in ex[g] if w) / len(ex[g])) if ex[g] else None
            row[g + "_n"] = len(per[g])
        rows.append(row)
    est = {}
    if first:
        for h in (5, 20):
            est[str(h)] = (pd.Timestamp(first) + pd.offsets.BDay(h)).strftime("%Y-%m-%d")
    return {"status": "ok", "reason": "", "first_logged": first, "n_sessions": len(dates),
            "horizons": rows, "matured_any": any(r["n"] for r in rows), "est": est}


# ------------------------------------------------------------------ entry
def unavailable(reason: str) -> dict:
    return {"status": "unavailable", "reason": reason, "as_of": "", "universe_source": "",
            "universe_n": 0, "evaluated_n": 0, "no_data_n": 0, "ath": [], "high52": [],
            "by_sector": {"ath": {}, "high52": {}},
            "breadth": {}, "near_ath": [], "sectors": {"rows": [], "sub_industries": []},
            "track": {"status": "unavailable", "reason": reason}}


def run_new_highs() -> dict:
    try:
        rows, source = load_universe()
        labels = {yf_symbol(r["ticker"]): {"ticker": r["ticker"], "name": r["name"],
                                           "sector": r["sector"], "sub_industry": r["sub_industry"]}
                  for r in rows}
        close = download_closes(list(labels))
        if close is None or close.empty:
            return unavailable("no price data")
        res = compute_new_highs(close, labels)
        n = len(labels)
        status = "ok" if res["evaluated_n"] >= PARTIAL_RATIO * n else "partial"
        entry = res.pop("log_entry")
        log = None
        try:
            prev, lstat = fetch_log()
            if prev is None:
                track = {"status": "unavailable", "reason": f"log fetch {lstat}"}
            else:
                log = merge_log(prev, res["as_of"], entry)
                track = compute_track(log["sessions"], close.loc[close.index <= res["as_of"]])
        except Exception as e:  # noqa: BLE001
            log, track = None, {"status": "unavailable", "reason": type(e).__name__}
        return {"status": status, "reason": "", "universe_source": source, "universe_n": n,
                **res, "track": track, "_log": log}
    except Exception as e:  # never break the briefing
        return unavailable(f"{type(e).__name__}: {str(e)[:80]}")


if __name__ == "__main__":
    if "--refresh-universe" in sys.argv:
        s = refresh_snapshot()
        print(f"snapshot written: {s['n']} tickers -> {SNAPSHOT_PATH}")
    else:
        import time
        t0 = time.time()
        r = run_new_highs()
        print(r["status"], r.get("reason", ""), r["as_of"], f"ath={len(r['ath'])} 52w={len(r['high52'])} "
              f"evaluated={r['evaluated_n']}/{r['universe_n']} src={r['universe_source']} "
              f"{time.time() - t0:.0f}s")
