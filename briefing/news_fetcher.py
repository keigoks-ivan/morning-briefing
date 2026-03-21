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
    "What are today major economic calendar events, Fed speeches, and earnings reports?",
]


def fetch_market_data() -> dict:
    try:
        import yfinance as yf
        tickers = yf.download(
            ["NQ=F", "^GSPC", "BZ=F", "^VIX"],
            period="2d", interval="1d", progress=False, auto_adjust=True,
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

        nq_val,    nq_chg    = get_close("NQ=F")
        sp_val,    sp_chg    = get_close("^GSPC")
        brent_val, brent_chg = get_close("BZ=F")
        vix_val,   vix_chg   = get_close("^VIX")

        def fmt_val(v, prefix=""):
            return f"{prefix}{v:,.2f}" if v is not None else "—"
        def fmt_chg(c):
            if c is None: return "—"
            return f"{'▲' if c > 0 else '▼'} {abs(c):.2f}%"
        def direction(c, invert=False):
            if c is None: return "neu"
            return ("neg" if c > 0 else "pos") if invert else ("pos" if c > 0 else "neg")

        market = {
            "nq100":    {"val": fmt_val(nq_val),         "chg": fmt_chg(nq_chg),    "dir": direction(nq_chg)},
            "sp500":    {"val": fmt_val(sp_val),         "chg": fmt_chg(sp_chg),    "dir": direction(sp_chg)},
            "brent":    {"val": fmt_val(brent_val, "$"), "chg": fmt_chg(brent_chg), "dir": direction(brent_chg, invert=True)},
            "vix":      {"val": fmt_val(vix_val),        "chg": fmt_chg(vix_chg),   "dir": direction(vix_chg, invert=True)},
            "fed_rate": {"val": "3.5–3.75%",             "chg": "維持不變",          "dir": "neu"},
        }
        nq = market['nq100']['val']
        sp = market['sp500']['val']
        br = market['brent']['val']
        vx = market['vix']['val']
        print(f"  ✓ Market: NQ={nq} SP={sp} Brent={br} VIX={vx}")
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
