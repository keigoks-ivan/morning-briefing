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
    "What happened in US stock markets today? Include specific index levels and percentage changes.",
    "What is the latest Federal Reserve policy stance and interest rate outlook for 2026?",
    "What is the current oil price and geopolitical situation affecting energy markets today?",
    "What are the latest AI industry developments today? Include AI companies, products, investments.",
    "What are the latest AI and semiconductor industry news today? Include Nvidia, AMD, TSMC.",
    "What are the latest AI startup funding rounds and robotics investments announced today?",
    "What are the latest breakthroughs in AI architecture and model research this week?",
    "What is the latest technology and semiconductor news from Taiwan and TSMC today?",
    "What is the latest technology news from Japan today? Include semiconductors and AI.",
    "What is the latest technology and AI industry news from the United States today?",
    "What is the latest technology and fintech news from Malaysia today?",
    "What is the latest technology and semiconductor news from South Korea today? Include Samsung, SK Hynix.",
    "What is the latest technology and AI news from China today? Include Huawei, Baidu, DeepSeek.",
    "What is the latest technology and AI news from Europe today?",
    "What are the latest fintech and cryptocurrency news today? Include Bitcoin, Ethereum, DeFi.",
    "What are the major macroeconomic data releases and central bank decisions today?",
    "What are the latest geopolitical risks today? Include Middle East, US-China, Taiwan Strait.",
    "What are the major startup IPOs, defense tech, and venture capital funding news today?",
    "What are the important earnings reports scheduled this week? Include tech companies.",
    "What are the most important macroeconomic calendar events in the next 24 hours? Include Fed speeches, central bank decisions, economic data releases like CPI, PPI, GDP, jobs data, and major earnings reports.",
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
DYNAMIC_POOL_TICKERS = [
    ("us2y",    "^IRX",     "",  True,  "美2Y"),
    ("jpyusd",  "JPY=X",    "¥", False, "JPY/USD"),
    ("twdusd",  "TWD=X",    "",  False, "TWD/USD"),
    ("myrusd",  "MYR=X",    "",  False, "MYR/USD"),
    ("eth",     "ETH-USD",  "$", False, "ETH"),
    ("hyg",     "HYG",      "$", False, "HYG"),
    ("lqd",     "LQD",      "$", False, "LQD"),
    ("nat_gas", "NG=F",     "$", False, "天然氣"),
    ("hsi",     "^HSI",     "",  False, "恒生"),
    ("nikkei",  "^N225",    "",  False, "日經"),
    ("uso",     "USO",      "$", False, "USO"),
    ("kbe",     "KBE",      "$", False, "KBE"),
]


def _fetch_fear_greed() -> dict:
    """Fetch CNN Fear & Greed Index."""
    try:
        resp = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
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

        all_tickers = FIXED_TICKERS + DYNAMIC_POOL_TICKERS
        symbols = [t[1] for t in all_tickers]
        tickers = yf.download(
            symbols, period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def get_close(symbol):
            try:
                closes = tickers["Close"][symbol].dropna()
                if len(closes) >= 2:
                    today = float(closes.iloc[-1])
                    prev  = float(closes.iloc[-2])
                    return today, (today - prev) / prev * 100
                elif len(closes) == 1:
                    return float(closes.iloc[-1]), None
            except Exception:
                pass
            return None, None

        def fmt_val(v, prefix=""):
            return f"{prefix}{v:,.2f}" if v is not None else "—"
        def fmt_chg(c):
            if c is None: return "—"
            return f"{'▲' if c > 0 else '▼'} {abs(c):.2f}%"
        def direction(c, invert=False):
            if c is None: return "neu"
            return ("neg" if c > 0 else "pos") if invert else ("pos" if c > 0 else "neg")

        def build_item(key, symbol, prefix, invert, label):
            val, chg = get_close(symbol)
            return {
                "label": label, "key": key,
                "val": fmt_val(val, prefix),
                "chg": fmt_chg(chg),
                "dir": direction(chg, invert=invert),
            }

        fixed = [build_item(*t) for t in FIXED_TICKERS]
        dynamic_pool = [build_item(*t) for t in DYNAMIC_POOL_TICKERS]
        fear_greed = _fetch_fear_greed()

        print(f"  ✓ Market: NQ={fixed[0]['val']} SP={fixed[1]['val']} "
              f"VIX={fixed[3]['val']} BTC={fixed[11]['val']} "
              f"F&G={fear_greed['val']}")

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
    """Fetch weekly market data (first close vs last close over 5d)."""
    try:
        import yfinance as yf

        symbols = [t[1] for t in WEEKLY_MARKET_TICKERS]
        tickers = yf.download(
            symbols, period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def get_weekly_change(symbol):
            try:
                closes = tickers["Close"][symbol].dropna()
                if len(closes) >= 2:
                    last = float(closes.iloc[-1])
                    first = float(closes.iloc[0])
                    return last, (last - first) / first * 100
                elif len(closes) == 1:
                    return float(closes.iloc[-1]), None
            except Exception:
                pass
            return None, None

        def fmt_val(v, prefix=""):
            return f"{prefix}{v:,.2f}" if v is not None else "—"
        def fmt_chg(c):
            if c is None: return "—"
            return f"{'▲' if c > 0 else '▼'} {abs(c):.2f}%"
        def direction(c, invert=False):
            if c is None: return "neu"
            return ("neg" if c > 0 else "pos") if invert else ("pos" if c > 0 else "neg")

        items = []
        for key, symbol, prefix, invert, label in WEEKLY_MARKET_TICKERS:
            val, chg = get_weekly_change(symbol)
            items.append({
                "label": label, "key": key,
                "val": fmt_val(val, prefix),
                "chg": fmt_chg(chg),
                "dir": direction(chg, invert=invert),
            })

        fear_greed = _fetch_fear_greed()

        print(f"  ✓ Weekly market: NQ={items[0]['val']} SP={items[1]['val']} "
              f"BTC={items[11]['val']} F&G={fear_greed['val']}")

        return {"items": items, "fear_greed": fear_greed}
    except Exception as e:
        print(f"  ✗ Weekly market data failed: {e}")
        return {"items": [], "fear_greed": {"val": "—", "chg": "—", "dir": "neu"}}


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
                            "Only report news from the past 24 hours. "
                            "Always include specific numbers, dates, and source names. "
                            "Never include ESG, sustainability, or green energy related news. "
                            "If no news from past 24 hours is available, say so explicitly."
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
