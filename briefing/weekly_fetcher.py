"""
weekly_fetcher.py
-----------------
使用 Perplexity API 搜尋十個深度主題的過去7天新聞。
同時提供 yfinance / FRED 資料抓取輔助函式。
"""

import os
import requests
from datetime import datetime
import pytz


WEEKLY_THEMES = {
    "central_bank": {
        "name": "央行政策追蹤",
        "queries": [
            "Federal Reserve Fed speeches statements this week rate outlook. Sources: Bloomberg Reuters Federal Reserve ECB BOJ official statements Financial Times WSJ",
            "ECB Bank of England BOJ central bank this week policy signals. Sources: Bloomberg Reuters Federal Reserve ECB BOJ official statements Financial Times WSJ",
            "Interest rate market pricing Fed funds futures this week. Sources: Bloomberg Reuters Federal Reserve Financial Times WSJ CNBC Goldman Sachs JP Morgan",
            "Inflation data impact on central bank policy this week. Sources: Bloomberg Reuters Federal Reserve ECB Financial Times WSJ CNBC",
            "Fed dot plot market expectations change this week. Sources: Bloomberg Reuters Federal Reserve Financial Times WSJ CNBC Goldman Sachs",
        ],
    },
    "liquidity": {
        "name": "流動性週報",
        "queries": [
            "Federal Reserve balance sheet reserves liquidity this week. Sources: Bloomberg Reuters Federal Reserve FRED Chicago Fed official data",
            "Overnight reverse repo RRP Fed liquidity this week. Sources: Bloomberg Reuters Federal Reserve FRED Chicago Fed official data",
            "NFCI National Financial Conditions Index latest update. Sources: Bloomberg Reuters Federal Reserve FRED Chicago Fed official data",
            "Bank reserves money market rates SOFR this week. Sources: Bloomberg Reuters Federal Reserve FRED Chicago Fed official data",
            "Financial conditions tightening easing this week indicators. Sources: Bloomberg Reuters Federal Reserve FRED Chicago Fed official data The Economist",
        ],
    },
    "credit": {
        "name": "信貸市場週報",
        "queries": [
            "High yield investment grade credit spreads this week change. Sources: Bloomberg Reuters Financial Times BIS Bank of America Credit Research",
            "Corporate bond market issuance demand this week. Sources: Bloomberg Reuters Financial Times BIS Bank of America Credit Research",
            "CLO leveraged loan market this week. Sources: Bloomberg Reuters Financial Times BIS Bank of America Credit Research",
            "Bank lending conditions credit availability this week. Sources: Bloomberg Reuters Financial Times BIS Bank of America Credit Research",
            "Credit default swaps CDS sovereign corporate this week. Sources: Bloomberg Reuters Financial Times BIS Bank of America Credit Research",
        ],
    },
    "options": {
        "name": "選擇權市場情緒",
        "queries": [
            "QQQ NDX options put call ratio this week sentiment. Sources: Bloomberg Reuters CBOE Barchart Options Clearing Corporation",
            "VIX term structure contango backwardation this week. Sources: Bloomberg Reuters CBOE Barchart Options Clearing Corporation",
            "Options market positioning large bets institutional this week Nasdaq. Sources: Bloomberg Reuters CBOE Barchart Options Clearing Corporation",
            "CBOE skew index volatility surface changes this week. Sources: Bloomberg Reuters CBOE Barchart Options Clearing Corporation",
            "Gamma exposure dealer positioning Nasdaq 100 this week. Sources: Bloomberg Reuters CBOE Barchart Options Clearing Corporation",
        ],
    },
    "ai_industry": {
        "name": "AI 產業發展",
        "queries": [
            "AI industry major developments this week funding acquisitions products. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Import AI Stratechery AI Snake Oil Axios",
            "Large language model AI research breakthroughs this week. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Import AI Stratechery AI Snake Oil",
            "AI infrastructure data center investment this week. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC Axios The Economist",
            "AI earnings results analyst reports this week Nvidia Microsoft Google. Sources: Bloomberg Reuters Financial Times WSJ CNBC Piper Sandler Bernstein Goldman Sachs",
            "AI regulation policy developments this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Politico Axios Brookings",
            "Earnings call transcripts AI commentary this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Piper Sandler Bernstein",
        ],
    },
    "semiconductor": {
        "name": "半導體供應鏈",
        "queries": [
            "Semiconductor supply chain news this week TSMC Samsung ASML. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis Semiconductor Engineering EE Times Nikkei Asia ASML TSMC Intel official",
            "Chip demand inventory cycle update this week. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis Semiconductor Engineering EE Times Nikkei Asia Piper Sandler Bernstein",
            "Semiconductor capital expenditure fab expansion this week. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis Semiconductor Engineering EE Times Nikkei Asia",
            "Advanced packaging HBM memory supply demand this week. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis Semiconductor Engineering EE Times Nikkei Asia",
            "Semiconductor analyst reports price target changes this week. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis EE Times Nikkei Asia Piper Sandler Bernstein Goldman Sachs",
            "Earnings call semiconductor commentary this week. Sources: Bloomberg Reuters DIGITIMES SemiAnalysis EE Times Nikkei Asia Piper Sandler Bernstein",
        ],
    },
    "earnings": {
        "name": "財報季追蹤",
        "queries": [
            "Earnings results this week vs estimates beat miss revenue EPS major companies. Sources: Bloomberg Reuters WSJ CNBC Seeking Alpha Earnings Whispers",
            "Tech company earnings this week Nvidia Microsoft Apple Google Meta Amazon. Sources: Bloomberg Reuters WSJ CNBC Seeking Alpha Earnings Whispers",
            "Semiconductor earnings this week TSMC ASML AMD Broadcom results. Sources: Bloomberg Reuters WSJ CNBC Seeking Alpha Earnings Whispers",
            "Earnings guidance outlook raised lowered this week. Sources: Bloomberg Reuters WSJ CNBC Seeking Alpha Earnings Whispers",
        ],
    },
    "macro": {
        "name": "全球景氣狀況",
        "queries": [
            "Global economy indicators this week GDP inflation employment. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB BIS IMF FRED Blog The Economist",
            "Central bank Fed ECB BOJ policy signals this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB BIS JP Morgan Goldman Sachs",
            "PMI manufacturing services data this week global. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB IMF The Economist",
            "Credit markets high yield investment grade spreads this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC JP Morgan Goldman Sachs BIS Quarterly Review",
            "Consumer spending retail sales economic data this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB FRED Blog",
            "Recession probability leading indicators this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC JP Morgan Goldman Sachs IMF The Economist",
        ],
    },
    "commodities": {
        "name": "能源與大宗商品",
        "queries": [
            "Oil price WTI Brent supply demand this week OPEC inventory. Sources: Bloomberg Reuters EIA IEA OPEC Financial Times",
            "Natural gas supply demand storage this week. Sources: Bloomberg Reuters EIA IEA Financial Times",
            "Gold silver copper metals price drivers this week. Sources: Bloomberg Reuters EIA IEA Financial Times",
            "Agricultural commodities wheat corn soybean this week. Sources: Bloomberg Reuters Financial Times",
            "Energy geopolitical supply disruption this week. Sources: Bloomberg Reuters EIA IEA OPEC Financial Times Foreign Affairs",
        ],
    },
    "black_swan": {
        "name": "黑天鵝與灰犀牛",
        "queries": [
            "Geopolitical risk escalation this week tail risk. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs Belfer Center RAND Brookings Politico The Economist",
            "Financial system stress signals this week credit banking. Sources: Bloomberg Reuters Financial Times WSJ CNBC BIS Quarterly Review JP Morgan Goldman Sachs",
            "Known but ignored risks gray rhino economic this week. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs Brookings RAND The Economist",
            "Unexpected market events volatility spike this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Axios The Economist",
            "Systemic risk indicators this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC BIS Quarterly Review IMF",
            "Black swan potential events emerging risks this week. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs Belfer Center RAND Brookings The Economist",
        ],
    },
}


def fetch_weekly_news(theme_key: str) -> list[dict]:
    """Fetch weekly news for a specific theme."""
    theme = WEEKLY_THEMES[theme_key]
    api_key = os.environ["PERPLEXITY_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    results = []
    for query in theme["queries"]:
        try:
            payload = {
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Today is {today} Taiwan time (UTC+8). "
                            "Report on developments from the past 7 days. "
                            "Include specific numbers, dates, company names, and source names. "
                            "Provide detailed analysis, not just headlines. "
                            "Never include ESG, sustainability, or green energy related news."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "search_recency_filter": "week",
                "return_citations": True,
                "max_tokens": 1200,
            }
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            results.append({"query": query, "answer": answer, "sources": citations[:5]})
            print(f"  ✓ [{theme_key}] {query[:60]}... ({len(citations)} sources)")
        except Exception as e:
            print(f"  ✗ [{theme_key}] {query[:60]}... — {e}")
            results.append({"query": query, "answer": "", "sources": []})

    return results


def fetch_options_data() -> dict:
    """Fetch VIX, VIX3M, VVIX, and QQQ put/call ratio via yfinance."""
    try:
        import yfinance as yf

        tickers = yf.download(
            ["^VIX", "^VIX3M", "^VVIX"], period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def _last(symbol):
            try:
                closes = tickers["Close"][symbol].dropna()
                return f"{float(closes.iloc[-1]):.2f}" if len(closes) > 0 else "—"
            except Exception:
                return "—"

        vix = _last("^VIX")
        vix3m = _last("^VIX3M")
        vvix = _last("^VVIX")

        # Determine term structure
        try:
            v = float(vix)
            v3 = float(vix3m)
            if v < v3:
                term = "contango"
            elif v > v3:
                term = "backwardation"
            else:
                term = "flat"
        except (ValueError, TypeError):
            term = "—"

        # QQQ put/call ratio from options chain
        pc_ratio = "—"
        try:
            qqq = yf.Ticker("QQQ")
            exp = qqq.options[0] if qqq.options else None
            if exp:
                calls = qqq.option_chain(exp).calls
                puts = qqq.option_chain(exp).puts
                if len(calls) > 0 and len(puts) > 0:
                    call_vol = calls["volume"].sum()
                    put_vol = puts["volume"].sum()
                    if call_vol > 0:
                        pc_ratio = f"{put_vol / call_vol:.2f}"
        except Exception:
            pass

        print(f"  ✓ Options: VIX={vix} VIX3M={vix3m} VVIX={vvix} P/C={pc_ratio} ({term})")
        return {
            "vix_spot": vix, "vix_3m": vix3m, "vvix": vvix,
            "term_structure": term, "qqq_pc_ratio": pc_ratio,
        }
    except Exception as e:
        print(f"  ✗ Options data failed: {e}")
        return {
            "vix_spot": "—", "vix_3m": "—", "vvix": "—",
            "term_structure": "—", "qqq_pc_ratio": "—",
        }


def fetch_credit_data() -> dict:
    """Fetch HYG, LQD weekly returns and ratio change via yfinance."""
    try:
        import yfinance as yf

        tickers = yf.download(
            ["HYG", "LQD"], period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )

        def _weekly_return(symbol):
            try:
                closes = tickers["Close"][symbol].dropna()
                if len(closes) >= 2:
                    first = float(closes.iloc[0])
                    last = float(closes.iloc[-1])
                    return f"{(last - first) / first * 100:+.2f}%", first, last
            except Exception:
                pass
            return "—", None, None

        hyg_ret, hyg_first, hyg_last = _weekly_return("HYG")
        lqd_ret, lqd_first, lqd_last = _weekly_return("LQD")

        ratio_chg = "—"
        if hyg_first and lqd_first and lqd_first > 0 and lqd_last > 0:
            r_start = hyg_first / lqd_first
            r_end = hyg_last / lqd_last
            ratio_chg = f"{(r_end - r_start) / r_start * 100:+.3f}%"

        print(f"  ✓ Credit: HYG={hyg_ret} LQD={lqd_ret} Ratio Δ={ratio_chg}")
        return {
            "hyg_weekly_return": hyg_ret,
            "lqd_weekly_return": lqd_ret,
            "hyg_lqd_ratio_change": ratio_chg,
        }
    except Exception as e:
        print(f"  ✗ Credit data failed: {e}")
        return {
            "hyg_weekly_return": "—",
            "lqd_weekly_return": "—",
            "hyg_lqd_ratio_change": "—",
        }


def fetch_nfci_data() -> dict:
    """Fetch NFCI from FRED CSV."""
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NFCI"
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MorningBriefing/1.0)"
        }, timeout=15)
        resp.raise_for_status()

        lines = resp.text.strip().split("\n")
        # Parse last 4 data rows
        data_rows = []
        for line in lines[1:]:  # skip header
            parts = line.split(",")
            if len(parts) == 2 and parts[1] != ".":
                try:
                    data_rows.append((parts[0], float(parts[1])))
                except ValueError:
                    continue

        if len(data_rows) >= 2:
            latest_date, latest_val = data_rows[-1]
            prev_date, prev_val = data_rows[-2]
            week_chg = latest_val - prev_val

            # 4-week trend
            if len(data_rows) >= 4:
                four_weeks_ago = data_rows[-4][1]
                if latest_val > four_weeks_ago + 0.05:
                    trend = "tightening"
                elif latest_val < four_weeks_ago - 0.05:
                    trend = "easing"
                else:
                    trend = "stable"
            else:
                trend = "—"

            print(f"  ✓ NFCI: {latest_val:.2f} (Δ {week_chg:+.2f}, {trend})")
            return {
                "latest_value": f"{latest_val:.2f}",
                "latest_date": latest_date,
                "prev_week": f"{prev_val:.2f}",
                "week_change": f"{week_chg:+.2f}",
                "4week_trend": trend,
            }
        else:
            print("  ✗ NFCI: insufficient data")
            return {"latest_value": "—", "latest_date": "—", "prev_week": "—", "week_change": "—", "4week_trend": "—"}
    except Exception as e:
        print(f"  ✗ NFCI data failed: {e}")
        return {"latest_value": "—", "latest_date": "—", "prev_week": "—", "week_change": "—", "4week_trend": "—"}
