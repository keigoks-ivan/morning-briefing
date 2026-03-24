"""
news_fetcher.py
---------------
使用 Perplexity API 搜尋每日財經、科技、新創新聞。
限制前24小時內的新聞。
"""

import os
import requests
from datetime import datetime
import pytz


PERPLEXITY_QUERIES = [
    # 總經/市場
    "What happened in US stock markets today? Include specific index levels and percentage changes. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB FRED Blog IMF Axios The Economist",
    "What is the latest Federal Reserve policy stance and interest rate outlook for 2026? Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB BIS FRED Blog JP Morgan Goldman Sachs",
    "What is the current oil price and geopolitical situation affecting energy markets today? Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB Axios Politico",
    # 科技/AI
    "What are the latest AI industry developments today? Include AI companies, products, investments. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Import AI Stratechery AI Snake Oil Axios",
    "What are the latest breakthroughs in AI architecture and model research this week? Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Import AI Stratechery AI Snake Oil",
    # 半導體
    "What are the latest AI and semiconductor industry news today? Include Nvidia, AMD, TSMC. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis Semiconductor Engineering EE Times Nikkei Asia ASML TSMC Intel official Piper Sandler Bernstein",
    # 新創/融資
    "What are the latest AI startup funding rounds and robotics investments announced today? Sources: TechCrunch Bloomberg Reuters Crunchbase The Information Axios",
    # 亞洲市場
    "What is the latest technology and semiconductor news from Taiwan and TSMC today? Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES",
    "What is the latest technology news from Japan today? Include semiconductors and AI. Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES",
    "What is the latest technology and AI industry news from the United States today? Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Stratechery Axios",
    "What is the latest technology and fintech news from Malaysia today? Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES",
    "What is the latest technology and semiconductor news from South Korea today? Include Samsung, SK Hynix. Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES",
    "What is the latest technology and AI news from China today? Include Huawei, Baidu, DeepSeek. Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES",
    "What is the latest technology and AI news from Europe today? Sources: Bloomberg Reuters Nikkei Asia South China Morning Post DIGITIMES The Economist",
    # Fintech/加密
    "What are the latest fintech and cryptocurrency news today? Include Bitcoin, Ethereum, DeFi. Sources: Bloomberg Reuters CoinDesk The Block Financial Times Axios",
    # 總經
    "What are the major macroeconomic data releases and central bank decisions today? Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB BIS FRED Blog IMF The Economist",
    # 地緣政治
    "What are the latest geopolitical risks today? Include Middle East, US-China, Taiwan Strait. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs Belfer Center RAND Brookings Politico The Economist",
    # 新創
    "What are the major startup IPOs, defense tech, and venture capital funding news today? Sources: TechCrunch Bloomberg Reuters Crunchbase The Information Axios",
    # 今日財報預告
    "Earnings reports scheduled for today not yet reported, companies reporting earnings today before market open during market after market close. Sources: Earnings Whispers Bloomberg Reuters CNBC WSJ",
    # 總經行事曆
    "What are the most important macroeconomic calendar events in the next 24 hours? Include Fed speeches, central bank decisions, economic data releases like CPI, PPI, GDP, jobs data, and major earnings reports. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB BIS FRED Blog",
    # 昨日美股重點
    "Earnings reports and conference calls during US market hours yesterday pre-market during-market after-hours results EPS revenue guidance Sources: Bloomberg Reuters CNBC WSJ Seeking Alpha Earnings Whispers",
    "Key statements from earnings calls investor days analyst conferences yesterday US market hours Sources: Bloomberg Reuters CNBC WSJ",
    "Significant stock moves reactions to earnings news yesterday US pre-market market hours after-hours Sources: Bloomberg Reuters CNBC",
    # 機構異動
    "Unusual options activity large block trades institutional buying selling smart money today Sources: Bloomberg CNBC Unusual Whales Barchart ETF flows QQQ SPY SOXX",
    # 國際新聞
    "Major international news today geopolitical developments regional conflicts diplomacy global affairs past 24 hours only most important first Sources: Bloomberg Reuters Financial Times BBC AP",
]


# 第一層：固定12格
FIXED_TICKERS = [
    # (key,    symbol,      prefix, invert, label)
    ("nq100",  "NQ=F",      "",  False, "NQ100"),
    ("sp500",  "^GSPC",     "",  False, "S&P500"),
    ("sox",    "^SOX",      "",  False, "費半"),
    ("vix",    "^VIX",      "",  True,  "VIX"),
    ("twii",   "^TWII",     "",  False, "台灣加權"),
    ("brent",  "BZ=F",      "$", False, "Brent油"),
    ("gold",   "GC=F",      "$", False, "黃金"),
    ("silver", "SI=F",      "$", False, "白銀"),
    ("copper", "HG=F",      "$", False, "銅"),
    ("dxy",    "DX-Y.NYB",  "",  False, "DXY"),
    ("us10y",  "^TNX",      "",  True,  "美10Y"),
    ("btc",    "BTC-USD",   "$", False, "BTC"),
]

# 第三層：動態備選池
# fmt: "pct" = 百分比漲跌, "bps" = 基點絕對變化
DYNAMIC_POOL_TICKERS = [
    # 利率/債券 (bps)
    # key,        symbol,    prefix, invert, label,           fmt
    ("us2y",      "^IRX",    "",  True,  "美2Y殖利率",      "bps"),
    ("us30y",     "^TYX",    "",  True,  "美30Y殖利率",     "bps"),
    # 10Y-2Y spread is computed separately
    ("tlt",       "TLT",     "$", False, "TLT長債ETF",      "pct"),
    ("hyg",       "HYG",     "$", False, "HYG高收益債",     "pct"),
    ("lqd",       "LQD",     "$", False, "LQD投資級債",     "pct"),
    # 外匯
    ("jpyusd",    "JPY=X",   "¥", False, "JPY/USD",         "pct"),
    ("twdusd",    "TWD=X",   "",  False, "TWD/USD",         "pct"),
    ("myrusd",    "MYR=X",   "",  False, "MYR/USD",         "pct"),
    ("cnyusd",    "CNY=X",   "",  False, "CNY/USD",         "pct"),
    ("eurusd",    "EURUSD=X","",  False, "EUR/USD",         "pct"),
    ("krwusd",    "KRW=X",   "",  False, "KRW/USD",         "pct"),
    # 股市
    ("nikkei",    "^N225",   "",  False, "日經225",          "pct"),
    ("hsi",       "^HSI",    "",  False, "恒生",             "pct"),
    ("kospi",     "^KS11",   "",  False, "KOSPI",            "pct"),
    ("dax",       "^GDAXI",  "",  False, "DAX",              "pct"),
    ("rut",       "^RUT",    "",  False, "羅素2000",         "pct"),
    ("kbe",       "KBE",     "$", False, "銀行股ETF",       "pct"),
    ("soxx",      "SOXX",    "$", False, "半導體ETF",       "pct"),
    # 大宗商品
    ("wti",       "CL=F",    "$", False, "WTI油",            "pct"),
    ("nat_gas",   "NG=F",    "$", False, "天然氣",           "pct"),
    ("palladium", "PA=F",    "$", False, "鈀金",             "pct"),
    ("platinum",  "PL=F",    "$", False, "鉑金",             "pct"),
    ("wheat",     "ZW=F",    "$", False, "小麥",             "pct"),
    # 加密
    ("eth",       "ETH-USD", "$", False, "ETH",              "pct"),
    ("sol",       "SOL-USD", "$", False, "SOL",              "pct"),
    # 波動率
    ("vvix",      "^VVIX",   "",  True,  "VVIX",             "pct"),
    ("skew",      "^SKEW",   "",  False, "SKEW指數",        "pct"),
]


def _fetch_fear_greed() -> dict:
    """Fetch CNN Fear & Greed Index."""
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers={"User-Agent": "Mozilla/5.0 (compatible; MorningBriefing/1.0)"},
            timeout=10,
        )
        resp.raise_for_status()
        fg = resp.json().get("fear_and_greed", {})
        score = str(int(fg.get("score", 0)))
        rating = fg.get("rating", "—")
        print(f"  ✓ Fear & Greed: {score} ({rating})")
        return {"val": score, "chg": rating, "dir": "neu"}
    except Exception as e:
        print(f"  ✗ Fear & Greed failed: {e}")
        return {"val": "—", "chg": "—", "dir": "neu"}


def fetch_market_data() -> dict:
    try:
        import yfinance as yf

        all_symbols = set()
        for t in FIXED_TICKERS:
            all_symbols.add(t[1])
        for t in DYNAMIC_POOL_TICKERS:
            all_symbols.add(t[1])
        # Also need ^TNX and ^IRX for 10Y-2Y spread
        all_symbols.update(["^TNX", "^IRX"])

        tickers = yf.download(
            list(all_symbols), period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def get_close(symbol):
            try:
                closes = tickers["Close"][symbol].dropna()
                if len(closes) >= 2:
                    return float(closes.iloc[-1]), float(closes.iloc[-2])
                elif len(closes) == 1:
                    return float(closes.iloc[-1]), None
            except Exception:
                pass
            return None, None

        def fmt_val(v, prefix=""):
            return f"{prefix}{v:,.2f}" if v is not None else "—"

        def fmt_chg_pct(today, prev):
            if today is None or prev is None or prev == 0:
                return "—", None
            c = (today - prev) / prev * 100
            return f"{'▲' if c > 0 else '▼'} {abs(c):.2f}%", c

        def fmt_chg_bps(today, prev):
            if today is None or prev is None:
                return "—", None
            diff = (today - prev) * 100  # yield points to bps
            return f"{'▲' if diff > 0 else '▼'} {abs(diff):.0f}bps", diff

        def direction(c, invert=False):
            if c is None:
                return "neu"
            return ("neg" if c > 0 else "pos") if invert else ("pos" if c > 0 else "neg")

        # Build fixed items (all pct)
        fixed = []
        for key, symbol, prefix, invert, label in FIXED_TICKERS:
            today_v, prev_v = get_close(symbol)
            chg_str, chg_raw = fmt_chg_pct(today_v, prev_v)
            fixed.append({
                "label": label, "key": key,
                "val": fmt_val(today_v, prefix),
                "chg": chg_str,
                "dir": direction(chg_raw, invert=invert),
            })

        # Build dynamic pool items (pct or bps)
        dynamic_pool = []
        for key, symbol, prefix, invert, label, fmt in DYNAMIC_POOL_TICKERS:
            today_v, prev_v = get_close(symbol)
            if today_v is None:
                continue  # skip failed tickers
            if fmt == "bps":
                chg_str, chg_raw = fmt_chg_bps(today_v, prev_v)
            else:
                chg_str, chg_raw = fmt_chg_pct(today_v, prev_v)
            dynamic_pool.append({
                "label": label, "key": key,
                "val": fmt_val(today_v, prefix),
                "chg": chg_str,
                "dir": direction(chg_raw, invert=invert),
                "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })

        # Add computed 10Y-2Y spread
        tnx_today, tnx_prev = get_close("^TNX")
        irx_today, irx_prev = get_close("^IRX")
        if tnx_today is not None and irx_today is not None:
            spread_today = tnx_today - irx_today
            spread_prev = (tnx_prev - irx_prev) if (tnx_prev is not None and irx_prev is not None) else None
            if spread_prev is not None:
                diff_bps = (spread_today - spread_prev) * 100
                chg_str = f"{'▲' if diff_bps > 0 else '▼'} {abs(diff_bps):.0f}bps"
                d = "pos" if diff_bps > 0 else ("neg" if diff_bps < 0 else "neu")
            else:
                chg_str = "—"
                d = "neu"
                diff_bps = 0
            dynamic_pool.append({
                "label": "10Y-2Y利差", "key": "spread_10y2y",
                "val": f"{spread_today:.2f}%",
                "chg": chg_str, "dir": d,
                "_abs_chg": abs(diff_bps) if diff_bps else 0,
            })

        fear_greed = _fetch_fear_greed()

        print(f"  ✓ Market: NQ={fixed[0]['val']} SP={fixed[1]['val']} "
              f"VIX={fixed[3]['val']} BTC={fixed[11]['val']} "
              f"F&G={fear_greed['val']} pool={len(dynamic_pool)}")

        return {
            "fixed": fixed,
            "fear_greed": fear_greed,
            "dynamic_pool": dynamic_pool,
        }
    except Exception as e:
        print(f"  ✗ Market data failed: {e}")
        return {}


# 週報用固定 tickers（與日報相同的前11個 + BTC）
WEEKLY_MARKET_TICKERS = [
    # (key,    symbol,      prefix, invert, label)
    ("nq100",  "NQ=F",      "",  False, "NQ100"),
    ("sp500",  "^GSPC",     "",  False, "S&P500"),
    ("sox",    "^SOX",      "",  False, "費半"),
    ("vix",    "^VIX",      "",  True,  "VIX"),
    ("twii",   "^TWII",     "",  False, "台灣加權"),
    ("brent",  "BZ=F",      "$", False, "Brent油"),
    ("gold",   "GC=F",      "$", False, "黃金"),
    ("silver", "SI=F",      "$", False, "白銀"),
    ("copper", "HG=F",      "$", False, "銅"),
    ("dxy",    "DX-Y.NYB",  "",  False, "DXY"),
    ("us10y",  "^TNX",      "",  True,  "美10Y"),
    ("btc",    "BTC-USD",   "$", False, "BTC"),
]


def fetch_weekly_market_data() -> dict:
    """Fetch weekly market data using 7d daily data (first vs last weekday close)."""
    try:
        import yfinance as yf

        all_symbols = set()
        for t in WEEKLY_MARKET_TICKERS:
            all_symbols.add(t[1])
        for t in DYNAMIC_POOL_TICKERS:
            all_symbols.add(t[1])
        all_symbols.update(["^TNX", "^IRX"])

        tickers = yf.download(
            list(all_symbols), period="7d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def get_week_vals(symbol):
            """Get first and last weekday close from 7d daily data."""
            try:
                closes = tickers["Close"][symbol].dropna()
                # Filter to weekdays only (Mon=0 .. Fri=4)
                weekday_closes = closes[closes.index.dayofweek < 5]
                if len(weekday_closes) >= 2:
                    return float(weekday_closes.iloc[0]), float(weekday_closes.iloc[-1])
                elif len(weekday_closes) == 1:
                    return float(weekday_closes.iloc[0]), float(weekday_closes.iloc[0])
            except Exception:
                pass
            return None, None

        def fmt_val(v, prefix=""):
            return f"{prefix}{v:,.2f}" if v is not None else "—"

        def fmt_chg_pct(first, last):
            if first is None or last is None or first == 0:
                return "—", None
            c = (last - first) / first * 100
            return f"{'▲' if c > 0 else '▼'} {abs(c):.2f}%", c

        def fmt_chg_bps(first, last):
            if first is None or last is None:
                return "—", None
            diff = (last - first) * 100
            return f"{'▲' if diff > 0 else '▼'} {abs(diff):.0f}bps", diff

        def direction(c, invert=False):
            if c is None:
                return "neu"
            return ("neg" if c > 0 else "pos") if invert else ("pos" if c > 0 else "neg")

        # Fixed 12
        fixed_keys = set()
        items = []
        for key, symbol, prefix, invert, label in WEEKLY_MARKET_TICKERS:
            first, last = get_week_vals(symbol)
            chg_str, chg_raw = fmt_chg_pct(first, last)
            items.append({
                "label": label, "key": key,
                "val": fmt_val(last, prefix),
                "chg": chg_str,
                "dir": direction(chg_raw, invert=invert),
            })
            fixed_keys.add(key)

        # Dynamic pool
        pool = []
        for key, symbol, prefix, invert, label, fmt in DYNAMIC_POOL_TICKERS:
            if key in fixed_keys:
                continue
            first, last = get_week_vals(symbol)
            if last is None:
                continue
            if fmt == "bps":
                chg_str, chg_raw = fmt_chg_bps(first, last)
            else:
                chg_str, chg_raw = fmt_chg_pct(first, last)
            pool.append({
                "label": label, "key": key,
                "val": fmt_val(last, prefix),
                "chg": chg_str,
                "dir": direction(chg_raw, invert=invert),
                "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })

        # 10Y-2Y spread
        tnx_first, tnx_last = get_week_vals("^TNX")
        irx_first, irx_last = get_week_vals("^IRX")
        if tnx_last is not None and irx_last is not None:
            spread_last = tnx_last - irx_last
            if tnx_first is not None and irx_first is not None:
                spread_first = tnx_first - irx_first
                diff_bps = (spread_last - spread_first) * 100
                chg_str = f"{'▲' if diff_bps > 0 else '▼'} {abs(diff_bps):.0f}bps"
                d = "pos" if diff_bps > 0 else ("neg" if diff_bps < 0 else "neu")
            else:
                chg_str, d, diff_bps = "—", "neu", 0
            pool.append({
                "label": "10Y-2Y利差", "key": "spread_10y2y",
                "val": f"{spread_last:.2f}%", "chg": chg_str, "dir": d,
                "_abs_chg": abs(diff_bps) if diff_bps else 0,
            })

        # Auto-select top 2 by abs change
        pool.sort(key=lambda x: x.get("_abs_chg", 0), reverse=True)
        top_dynamic = []
        for p in pool[:2]:
            item = {k: v for k, v in p.items() if k != "_abs_chg"}
            top_dynamic.append(item)

        fear_greed = _fetch_fear_greed()

        print(f"  ✓ Weekly market: NQ={items[0]['val']} SP={items[1]['val']} "
              f"BTC={items[11]['val']} F&G={fear_greed['val']} "
              f"top_dyn={[d['label'] for d in top_dynamic]}")

        return {"items": items, "fear_greed": fear_greed, "dynamic": top_dynamic}
    except Exception as e:
        print(f"  ✗ Weekly market data failed: {e}")
        return {"items": [], "fear_greed": {"val": "—", "chg": "—", "dir": "neu"}, "dynamic": []}


EARNINGS_WATCHLIST = [
    # 科技/AI
    "NVDA", "AMD", "INTC", "MSFT", "GOOGL", "META", "AMZN", "AAPL",
    "NFLX", "PLTR", "SNOW", "CRM", "NOW", "ADBE", "ORCL", "IBM",
    "UBER", "LYFT", "ABNB", "DASH",
    # 半導體
    "ASML", "AMAT", "LRCX", "KLAC", "TSM", "ARM", "AVGO",
    "QCOM", "MU", "MRVL", "WOLF", "ON", "MPWR", "ENTG", "ONTO",
    "ACLS", "COHU", "TER", "FORM",
    # S&P500 大型權值股
    "BRK-B", "LLY", "JPM", "V", "UNH", "XOM", "MA", "JNJ",
    "PG", "HD", "COST", "BAC", "WMT", "ABBV", "GS", "MS",
    "TSLA", "GE", "CAT", "RTX", "NEE", "CVX", "PFE", "MRK",
    "TMO", "DHR", "ABT", "BMY", "AMGN", "GILD",
    # 金融
    "C", "WFC", "AXP", "BLK", "SCHW", "ICE", "CME", "SPGI",
    "MCO", "BX", "KKR", "APO",
    # 能源
    "SLB", "HAL", "BKR", "OXY", "COP", "EOG", "PSX", "VLO",
    # 消費/零售
    "MCD", "SBUX", "NKE", "TGT", "LOW", "TJX", "ROST", "DLTR",
    # 媒體/電信
    "DIS", "CMCSA", "T", "VZ", "TMUS", "CHTR", "PARA", "WBD",
    # 台灣/亞洲ADR
    "UMC", "ASX",
    # 國防/航太
    "LMT", "NOC", "GD", "BA", "HII", "KTOS", "RCAT",
]


def fetch_today_earnings() -> list[dict]:
    """Check WATCHLIST for earnings scheduled today via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("  ✗ yfinance not available for earnings check")
        return []

    tz = pytz.timezone("US/Eastern")
    today_us = datetime.now(tz).strftime("%Y-%m-%d")

    results = []
    for symbol in EARNINGS_WATCHLIST:
        try:
            t = yf.Ticker(symbol)
            cal = t.calendar
            if cal is None or cal.empty if hasattr(cal, 'empty') else not cal:
                continue
            # calendar can be a DataFrame or dict
            if hasattr(cal, "iloc"):
                # DataFrame: first column is the earnings date
                earn_date = str(cal.iloc[0, 0])[:10] if cal.shape[1] > 0 else ""
            elif isinstance(cal, dict):
                ed = cal.get("Earnings Date", [])
                earn_date = str(ed[0])[:10] if ed else ""
            else:
                continue

            if earn_date == today_us:
                # Try to determine timing
                timing = "after-close"  # default
                if hasattr(cal, "iloc") and cal.shape[0] > 1:
                    try:
                        hour_val = cal.iloc[1, 0]
                        if hasattr(hour_val, 'hour') and hour_val.hour < 12:
                            timing = "before-open"
                    except Exception:
                        pass

                results.append({
                    "ticker": symbol,
                    "date": earn_date,
                    "time": timing,
                })
        except Exception:
            continue

    print(f"  ✓ Today earnings: {len(results)} companies from watchlist "
          f"({', '.join(r['ticker'] for r in results[:5])}{'...' if len(results) > 5 else ''})")
    return results


def fetch_financial_news() -> list[dict]:
    api_key = os.environ["PERPLEXITY_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    results = []

    for query in PERPLEXITY_QUERIES:
        try:
            payload = {
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Today is {today} Taiwan time (UTC+8). "
                            "Only report news from the past 24 hours. No exceptions. "
                            "Sort results by BOTH recency AND importance: breaking news and high-impact events first, "
                            "then other recent news. If no news from past 24 hours is available, say so explicitly. "
                            "Never include news older than 24 hours even if no recent news is available. "
                            "Always include specific numbers, dates, and source names. "
                            "Never include ESG, sustainability, or green energy related news."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "search_recency_filter": "day",
                "return_citations": True,
                "max_tokens": 600,
            }
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers, json=payload, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            results.append({"query": query, "answer": answer, "sources": citations[:3]})
            print(f"  ✓ {query[:55]}... ({len(citations)} sources)")
        except Exception as e:
            print(f"  ✗ {query[:55]}... — {e}")
            results.append({"query": query, "answer": "", "sources": []})

    return results
