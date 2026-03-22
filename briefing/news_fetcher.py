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


MARKET_TICKERS = [
    # (key,          symbol,       prefix, invert, label)
    # 股票指數
    ("nq100",        "NQ=F",       "",  False, "NQ100"),
    ("sp500",        "^GSPC",      "",  False, "S&P500"),
    ("dow",          "YM=F",       "",  False, "道瓊"),
    ("sox",          "^SOX",       "",  False, "費半"),
    ("twii",         "^TWII",      "",  False, "台灣加權"),
    ("nikkei",       "^N225",      "",  False, "日經225"),
    ("hsi",          "^HSI",       "",  False, "恒生"),
    ("kospi",        "^KS11",      "",  False, "KOSPI"),
    ("dax",          "^GDAXI",     "",  False, "DAX"),
    # 商品
    ("brent",        "BZ=F",       "$", False, "Brent油"),
    ("wti",          "CL=F",       "$", False, "WTI油"),
    ("nat_gas",      "NG=F",       "$", False, "天然氣"),
    ("gold",         "GC=F",       "$", False, "黃金"),
    ("silver",       "SI=F",       "$", False, "白銀"),
    ("copper",       "HG=F",       "$", False, "銅"),
    # 債券/利率
    ("us10y",        "^TNX",       "",  True,  "美10Y"),
    ("us2y",         "^IRX",       "",  True,  "美2Y"),
    # 外匯
    ("dxy",          "DX-Y.NYB",   "",  False, "DXY"),
    ("jpyusd",       "JPY=X",      "¥", False, "JPY/USD"),
    ("twdusd",       "TWD=X",      "",  False, "TWD/USD"),
    ("myrusd",       "MYR=X",      "",  False, "MYR/USD"),
    ("cnyusd",       "CNY=X",      "",  False, "CNY/USD"),
    ("eurusd",       "EURUSD=X",   "",  False, "EUR/USD"),
    # 加密貨幣
    ("btc",          "BTC-USD",    "$", False, "BTC"),
    ("eth",          "ETH-USD",    "$", False, "ETH"),
    # VIX（反向）
    ("vix",          "^VIX",       "",  True,  "VIX"),
]


def fetch_market_data() -> dict:
    try:
        import yfinance as yf

        symbols = [t[1] for t in MARKET_TICKERS]
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

        market = {}
        for key, symbol, prefix, invert, label in MARKET_TICKERS:
            val, chg = get_close(symbol)
            market[key] = {
                "val": fmt_val(val, prefix),
                "chg": fmt_chg(chg),
                "dir": direction(chg, invert=invert),
            }

        market["fed_rate"] = {"val": "3.5–3.75%", "chg": "維持不變", "dir": "neu"}

        print(f"  ✓ Market: NQ={market['nq100']['val']} SP={market['sp500']['val']} "
              f"Brent={market['brent']['val']} VIX={market['vix']['val']} "
              f"BTC={market['btc']['val']} Gold={market['gold']['val']}")
        return market
    except Exception as e:
        print(f"  ✗ Market data failed: {e}")
        return {}


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
