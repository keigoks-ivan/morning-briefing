"""
news_fetcher.py
---------------
使用 Perplexity API 搜尋每日財經、科技、新創新聞。
限制前24小時內的新聞。
"""

import os
import time
import requests
import feedparser
from datetime import datetime, timedelta
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

DEEP_DIVE_QUERIES = [
    "Semiconductor supply chain today: inventory levels fab utilization TSMC Samsung capacity pricing DRAM NAND HBM latest data Sources: Digitimes SemiAnalysis Bloomberg Reuters TrendForce",
    "AI model architecture research today: training efficiency inference optimization new model releases benchmarks compute costs Sources: Bloomberg Reuters TechCrunch The Information Ars Technica",
    "Global liquidity indicators today: Fed balance sheet overnight reverse repo RRP bank reserves SOFR NFCI financial conditions Sources: Federal Reserve Bloomberg Reuters FRED",
    "Energy market today: oil price WTI Brent OPEC supply LNG natural gas inventory EIA data Sources: Bloomberg Reuters EIA IEA Financial Times",
    "Most important industry development today that deserves deeper analysis: any major structural shift technology breakthrough regulatory change market dislocation Sources: Bloomberg Reuters FT WSJ",
]


FIXED_TICKERS = {
    # 股票指數
    "nq100":     {"ticker": "NQ=F",      "label": "NQ期貨",   "prefix": "",  "type": "index"},
    "ndx":       {"ticker": "^NDX",      "label": "NDX現貨",  "prefix": "",  "type": "index"},
    "sp500":     {"ticker": "^GSPC",     "label": "S&P500",   "prefix": "",  "type": "index"},
    "sox":       {"ticker": "^SOX",      "label": "費半",      "prefix": "",  "type": "index"},
    "twii":      {"ticker": "^TWII",     "label": "台灣加權",  "prefix": "",  "type": "index"},
    "dax":       {"ticker": "^GDAXI",    "label": "歐洲DAX",  "prefix": "",  "type": "index"},
    "vt":        {"ticker": "VT",        "label": "VT",       "prefix": "$", "type": "etf"},
    "vo":        {"ticker": "VO",        "label": "VO",       "prefix": "$", "type": "etf"},
    "btc":       {"ticker": "BTC-USD",   "label": "BTC",      "prefix": "$", "type": "crypto"},
    # 美股因子
    "nyfang":    {"ticker": "FNGS",      "label": "NYFANG",   "prefix": "",  "type": "factor"},
    "vtv":       {"ticker": "VTV",       "label": "VTV 價值",  "prefix": "$", "type": "factor"},
    "vug":       {"ticker": "VUG",       "label": "VUG 成長",  "prefix": "$", "type": "factor"},
    "rsp":       {"ticker": "RSP",       "label": "RSP",      "prefix": "$", "type": "factor"},
    "spy":       {"ticker": "SPY",       "label": "SPY",      "prefix": "$", "type": "factor"},
    "mtum":      {"ticker": "MTUM",      "label": "MTUM",     "prefix": "$", "type": "factor"},
    "iwm":       {"ticker": "IWM",       "label": "IWM",      "prefix": "$", "type": "factor"},
    # 市場情緒
    "vix":       {"ticker": "^VIX",      "label": "VIX",      "prefix": "",  "type": "sentiment", "invert": True},
    "vix9d":     {"ticker": "^VIX9D",    "label": "VIX9D",    "prefix": "",  "type": "sentiment", "invert": True},
    "skew":      {"ticker": "^SKEW",     "label": "SKEW",     "prefix": "",  "type": "sentiment"},
    "vvix":      {"ticker": "^VVIX",     "label": "VVIX",     "prefix": "",  "type": "sentiment", "invert": True},
    # 原物料
    "brent":     {"ticker": "BZ=F",      "label": "Brent油",  "prefix": "$", "type": "commodity"},
    "wti":       {"ticker": "CL=F",      "label": "WTI油",    "prefix": "$", "type": "commodity"},
    "gold":      {"ticker": "GC=F",      "label": "黃金",      "prefix": "$", "type": "commodity"},
    "silver":    {"ticker": "SI=F",      "label": "白銀",      "prefix": "$", "type": "commodity"},
    "copper":    {"ticker": "HG=F",      "label": "銅",        "prefix": "$", "type": "commodity"},
    "alum":      {"ticker": "ALI=F",     "label": "鋁",        "prefix": "$", "type": "commodity"},
    # 債券
    "us10y":     {"ticker": "^TNX",      "label": "美10Y",    "prefix": "",  "type": "bond", "use_bps": True},
    # 外匯
    "dxy":       {"ticker": "DX-Y.NYB",  "label": "DXY",      "prefix": "",  "type": "fx"},
    "jpyusd":    {"ticker": "JPY=X",     "label": "JPY/USD",  "prefix": "¥", "type": "fx"},
    # 信貸
    "hyg":       {"ticker": "HYG",       "label": "HYG",      "prefix": "$", "type": "credit"},
    "lqd":       {"ticker": "LQD",       "label": "LQD",      "prefix": "$", "type": "credit"},
    "bkln":      {"ticker": "BKLN",      "label": "BKLN",     "prefix": "$", "type": "credit"},
}

COMMODITY_POOL = {
    "NG=F": "天然氣", "PA=F": "鈀金", "PL=F": "鉑金",
    "ZW=F": "小麥", "ZC=F": "玉米", "ZS=F": "黃豆",
    "CC=F": "可可", "KC=F": "咖啡", "SB=F": "糖",
}

SECTOR_ETFS = {
    "XLE": "能源", "XLF": "金融", "XLK": "科技",
    "XLV": "醫療", "XLI": "工業", "XLY": "非必需消費",
    "XLP": "必需消費", "XLU": "公用事業", "XLB": "材料",
    "XLRE": "房地產", "XLC": "通訊", "XBI": "生技",
}


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


def fetch_fred_data() -> dict:
    """Fetch RRP, NFCI, TGA, and bank reserves from FRED via CSV endpoint."""
    result = {}
    fred_series = {
        "rrp":      "RRPONTSYD",  # 隔夜逆回購餘額
        "nfci":     "NFCI",       # 芝加哥Fed金融條件指數
        "tga":      "WTREGEN",    # 財政部一般帳戶
        "reserves": "WRESBAL",    # 銀行準備金
    }
    LABELS = {"rrp": "RRP餘額", "nfci": "NFCI", "tga": "TGA", "reserves": "銀行準備金"}
    for key, series_id in fred_series.items():
        try:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            lines = resp.text.strip().split("\n")
            rows = [line.split(",") for line in lines[1:] if line.strip()]
            rows = [(r[0], r[1]) for r in rows if len(r) >= 2 and r[1] not in ("", ".")]
            if len(rows) >= 2:
                latest_date, latest_val = rows[-1]
                _prev_date, prev_val = rows[-2]
                latest = float(latest_val)
                prev = float(prev_val)
                change = latest - prev
                if key == "nfci":
                    result[key] = {
                        "label": "NFCI",
                        "val": f"{latest:.3f}",
                        "chg": f"{'▲' if change > 0 else '▼'} {abs(change):.3f}",
                        "dir": "neg" if change > 0 else "pos",  # NFCI上升=收緊=neg
                        "date": latest_date,
                    }
                elif key == "tga":
                    result[key] = {
                        "label": "TGA",
                        "val": f"${latest:.0f}B",
                        "chg": f"{'▲' if change > 0 else '▼'} {abs(change):.0f}B",
                        "dir": "pos" if change < 0 else "neg",  # TGA下降=政府花錢=流動性增加
                        "date": latest_date,
                    }
                elif key == "reserves":
                    result[key] = {
                        "label": "銀行準備金",
                        "val": f"${latest:.0f}B",
                        "chg": f"{'▲' if change > 0 else '▼'} {abs(change):.0f}B",
                        "dir": "pos" if change > 0 else "neg",  # 準備金增加=流動性充裕
                        "date": latest_date,
                    }
                else:  # rrp
                    result[key] = {
                        "label": "RRP餘額",
                        "val": f"${latest:.0f}B",
                        "chg": f"{'▲' if change > 0 else '▼'} {abs(change):.0f}B",
                        "dir": "pos" if change < 0 else "neg",  # RRP下降=流動性釋放
                        "date": latest_date,
                    }
                print(f"  ✓ FRED {series_id}: {latest_val} ({latest_date})")
            else:
                raise ValueError("not enough data points")
        except Exception as e:
            print(f"  ✗ FRED {series_id}: {e}")
            result[key] = {
                "label": LABELS.get(key, key),
                "val": "—", "chg": "—", "dir": "neu", "date": "",
            }
    return result


def assess_liquidity(fred: dict) -> dict:
    """Assess overall liquidity from RRP, TGA, reserves, NFCI."""
    score = 0
    signals = []
    for key, up_label, down_label in [
        ("rrp", "RRP↑", "RRP↓"),
        ("tga", "TGA↑", "TGA↓"),
        ("reserves", "準備金↑", "準備金↓"),
        ("nfci", "NFCI收緊", "NFCI改善"),
    ]:
        item = fred.get(key, {})
        d = item.get("dir", "neu")
        if d == "pos":
            score += 1
            signals.append(down_label if key in ("rrp", "tga") else up_label if key == "reserves" else down_label)
        elif d == "neg":
            score -= 1
            signals.append(up_label if key in ("rrp", "tga") else down_label if key == "reserves" else up_label)
    if score >= 2:
        return {"label": "流動性寬鬆", "color": "pos", "score": score, "signals": signals}
    elif score <= -2:
        return {"label": "流動性收縮", "color": "neg", "score": score, "signals": signals}
    return {"label": "流動性中性", "color": "neu", "score": score, "signals": signals}


def _download_symbols(symbols: list[str], period: str = "5d") -> dict:
    """Download each symbol individually to avoid SQLite database locked errors."""
    import yfinance as yf
    cache = {}
    for symbol in symbols:
        try:
            df = yf.download(
                symbol, period=period, interval="1d",
                progress=False, auto_adjust=True,
            )
            if df is not None and not df.empty:
                closes = df["Close"].dropna().astype(float)
                cache[symbol] = closes
        except Exception as e:
            print(f"  ✗ yfinance {symbol}: {e}")
    return cache


def fetch_market_data() -> dict:
    try:
        # Collect all symbols to download
        all_symbols = set()
        for info in FIXED_TICKERS.values():
            all_symbols.add(info["ticker"])
        for symbol in SECTOR_ETFS:
            all_symbols.add(symbol)
        for symbol in COMMODITY_POOL:
            all_symbols.add(symbol)

        closes_cache = _download_symbols(list(all_symbols), period="5d")

        def get_close(symbol):
            try:
                closes = closes_cache.get(symbol)
                if closes is None:
                    return None, None
                if len(closes) >= 2:
                    return closes.iloc[-1].item(), closes.iloc[-2].item()
                elif len(closes) == 1:
                    return closes.iloc[-1].item(), None
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

        # Build items per category from FIXED_TICKERS
        category_keys = {
            "indices":     ["nq100", "ndx", "sp500", "sox", "twii", "dax", "vt", "vo", "btc"],
            "factors":     ["nyfang", "vtv", "vug", "mtum", "iwm"],
            "sentiment":   ["vix", "vix9d", "skew", "vvix"],
            "commodities": ["brent", "wti", "gold", "silver", "copper", "alum"],
            "bonds":       ["us10y"],
            "fx":          ["dxy", "jpyusd"],
            "credit":      ["hyg", "lqd", "bkln"],
        }

        result = {cat: [] for cat in category_keys}

        for cat, keys in category_keys.items():
            for key in keys:
                info = FIXED_TICKERS[key]
                today_v, prev_v = get_close(info["ticker"])
                invert = info.get("invert", False)
                use_bps = info.get("use_bps", False)
                if use_bps:
                    chg_str, chg_raw = fmt_chg_bps(today_v, prev_v)
                else:
                    chg_str, chg_raw = fmt_chg_pct(today_v, prev_v)
                result[cat].append({
                    "label": info["label"],
                    "val": fmt_val(today_v, info["prefix"]),
                    "chg": chg_str,
                    "dir": direction(chg_raw, invert=invert),
                    "is_dynamic": False,
                })

        # RSP/SPY ratio — compute and insert into factors (replacing individual RSP/SPY)
        rsp_today, rsp_prev = get_close("RSP")
        spy_today, spy_prev = get_close("SPY")
        # Remove individual RSP and SPY from factors list
        result["factors"] = [f for f in result["factors"] if f["label"] not in ("RSP", "SPY")]
        if rsp_today and spy_today and spy_today != 0:
            ratio_today = rsp_today / spy_today
            if rsp_prev and spy_prev and spy_prev != 0:
                ratio_prev = rsp_prev / spy_prev
                ratio_chg = (ratio_today - ratio_prev) / ratio_prev * 100
                ratio_chg_str = f"{'▲' if ratio_chg > 0 else '▼'} {abs(ratio_chg):.2f}%"
                ratio_dir = "pos" if ratio_chg > 0 else ("neg" if ratio_chg < 0 else "neu")
            else:
                ratio_chg_str, ratio_dir = "—", "neu"
            rsp_spy_item = {
                "label": "RSP/SPY",
                "val": f"{ratio_today:.4f}",
                "chg": ratio_chg_str,
                "dir": ratio_dir,
                "is_dynamic": False,
            }
        else:
            rsp_spy_item = {"label": "RSP/SPY", "val": "—", "chg": "—", "dir": "neu", "is_dynamic": False}
        # Insert after VUG (index 2)
        result["factors"].insert(2, rsp_spy_item)

        # Sector ETFs — pick top 3 by abs change
        sector_items = []
        for symbol, label in SECTOR_ETFS.items():
            today_v, prev_v = get_close(symbol)
            chg_str, chg_raw = fmt_chg_pct(today_v, prev_v)
            sector_items.append({
                "label": f"{symbol} {label}",
                "val": fmt_val(today_v, "$"),
                "chg": chg_str,
                "dir": direction(chg_raw),
                "is_dynamic": True,
                "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })
        sector_items.sort(key=lambda x: x.get("_abs_chg", 0), reverse=True)
        top_sectors = []
        for s in sector_items[:3]:
            item = {k: v for k, v in s.items() if k != "_abs_chg"}
            top_sectors.append(item)
        result["factors"].extend(top_sectors)

        # Dynamic commodities — top 2 by abs change from COMMODITY_POOL
        commodity_pool = []
        for symbol, label in COMMODITY_POOL.items():
            today_v, prev_v = get_close(symbol)
            if today_v is None:
                continue
            chg_str, chg_raw = fmt_chg_pct(today_v, prev_v)
            commodity_pool.append({
                "label": label,
                "val": fmt_val(today_v, "$"),
                "chg": chg_str,
                "dir": direction(chg_raw),
                "is_dynamic": True,
                "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })
        commodity_pool.sort(key=lambda x: x.get("_abs_chg", 0), reverse=True)
        dyn_commodities = []
        for c in commodity_pool[:2]:
            item = {k: v for k, v in c.items() if k != "_abs_chg"}
            dyn_commodities.append(item)
        result["commodities"] = {"fixed": result["commodities"], "dynamic": dyn_commodities}

        # Fear & Greed → sentiment
        fear_greed = _fetch_fear_greed()
        fg_item = {
            "label": "Fear&Greed",
            "val": fear_greed.get("val", "—"),
            "chg": fear_greed.get("chg", "—"),
            "dir": fear_greed.get("dir", "neu"),
        }
        # Insert after VIX (index 1 in sentiment)
        result["sentiment"].insert(1, fg_item)

        # HYG/LQD ratio
        hyg_today, hyg_prev = get_close("HYG")
        lqd_today, lqd_prev = get_close("LQD")
        if hyg_today is not None and lqd_today is not None and lqd_today != 0:
            ratio_today = hyg_today / lqd_today
            if hyg_prev is not None and lqd_prev is not None and lqd_prev != 0:
                ratio_prev = hyg_prev / lqd_prev
                ratio_chg = (ratio_today - ratio_prev) / ratio_prev * 100
                ratio_chg_str = f"{'▲' if ratio_chg > 0 else '▼'} {abs(ratio_chg):.2f}%"
                ratio_dir = "pos" if ratio_chg > 0 else ("neg" if ratio_chg < 0 else "neu")
            else:
                ratio_chg_str, ratio_dir = "—", "neu"
            ratio_item = {
                "label": "HYG/LQD",
                "val": f"{ratio_today:.4f}",
                "chg": ratio_chg_str,
                "dir": ratio_dir,
            }
        else:
            ratio_item = {"label": "HYG/LQD", "val": "—", "chg": "—", "dir": "neu"}
        # Insert HYG/LQD ratio after LQD (before BKLN)
        result["credit"].insert(2, ratio_item)

        # Liquidity: fetch from FRED
        fred = fetch_fred_data()
        _empty = lambda lbl: {"label": lbl, "val": "—", "chg": "—", "dir": "neu", "date": ""}
        result["liquidity"] = [
            fred.get("rrp", _empty("RRP餘額")),
            fred.get("tga", _empty("TGA")),
            fred.get("reserves", _empty("銀行準備金")),
            fred.get("nfci", _empty("NFCI")),
        ]
        result["liquidity_assessment"] = assess_liquidity(fred)

        print(f"  ✓ Market: NQ={result['indices'][0]['val']} SP={result['indices'][2]['val']} "
              f"VIX={result['sentiment'][0]['val']} BTC={result['indices'][8]['val']} "
              f"F&G={fg_item['val']} sectors={[s['label'] for s in top_sectors]}")

        return result
    except Exception as e:
        print(f"  ✗ Market data failed: {e}")
        import traceback
        traceback.print_exc()
        return {}


def fetch_move_index() -> str:
    """Fetch MOVE Index value via Perplexity search."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        print("  ✗ MOVE Index: no PERPLEXITY_API_KEY")
        return ""
    query = "MOVE Index current value today ICE BofA MOVE bond market volatility index latest reading Sources: Bloomberg Reuters ICE"
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    try:
        payload = {
            "model": "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"Today is {today} Taiwan time (UTC+8). "
                        "Return only the current MOVE Index numerical value and a brief context. "
                        "Be concise."
                    ),
                },
                {"role": "user", "content": query},
            ],
            "search_recency_filter": "day",
            "return_citations": True,
            "max_tokens": 300,
        }
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=30,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
        print(f"  ✓ MOVE Index: {answer[:80]}...")
        return answer
    except Exception as e:
        print(f"  ✗ MOVE Index search failed: {e}")
        return ""


# 週報用：重用 FIXED_TICKERS，產生與日報相同分類結構
def fetch_weekly_market_data() -> dict:
    """Fetch weekly market data using 7d daily data (first vs last weekday close)."""
    try:
        all_symbols = set()
        for info in FIXED_TICKERS.values():
            all_symbols.add(info["ticker"])
        for symbol in SECTOR_ETFS:
            all_symbols.add(symbol)
        for symbol in COMMODITY_POOL:
            all_symbols.add(symbol)

        closes_cache = _download_symbols(list(all_symbols), period="7d")

        def get_week_vals(symbol):
            try:
                closes = closes_cache.get(symbol)
                if closes is None:
                    return None, None
                weekday_closes = closes[closes.index.dayofweek < 5]
                if len(weekday_closes) >= 2:
                    return weekday_closes.iloc[0].item(), weekday_closes.iloc[-1].item()
                elif len(weekday_closes) == 1:
                    return weekday_closes.iloc[0].item(), weekday_closes.iloc[0].item()
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

        # Build same category structure as daily
        category_keys = {
            "indices":     ["nq100", "ndx", "sp500", "sox", "twii", "dax", "vt", "vo", "btc"],
            "factors":     ["nyfang", "vtv", "vug", "mtum", "iwm"],
            "sentiment":   ["vix", "vix9d", "skew", "vvix"],
            "commodities": ["brent", "wti", "gold", "silver", "copper", "alum"],
            "bonds":       ["us10y"],
            "fx":          ["dxy", "jpyusd"],
            "credit":      ["hyg", "lqd", "bkln"],
        }

        result = {cat: [] for cat in category_keys}

        for cat, keys in category_keys.items():
            for key in keys:
                info = FIXED_TICKERS[key]
                first, last = get_week_vals(info["ticker"])
                invert = info.get("invert", False)
                use_bps = info.get("use_bps", False)
                if use_bps:
                    chg_str, chg_raw = fmt_chg_bps(first, last)
                else:
                    chg_str, chg_raw = fmt_chg_pct(first, last)
                result[cat].append({
                    "label": info["label"],
                    "val": fmt_val(last, info["prefix"]),
                    "chg": chg_str,
                    "dir": direction(chg_raw, invert=invert),
                    "is_dynamic": False,
                })

        # RSP/SPY ratio for weekly
        rsp_first, rsp_last = get_week_vals("RSP")
        spy_first, spy_last = get_week_vals("SPY")
        result["factors"] = [f for f in result["factors"] if f["label"] not in ("RSP", "SPY")]
        if rsp_last and spy_last and spy_last != 0:
            ratio_last = rsp_last / spy_last
            if rsp_first and spy_first and spy_first != 0:
                ratio_first = rsp_first / spy_first
                ratio_chg = (ratio_last - ratio_first) / ratio_first * 100
                ratio_chg_str = f"{'▲' if ratio_chg > 0 else '▼'} {abs(ratio_chg):.2f}%"
                ratio_dir = "pos" if ratio_chg > 0 else ("neg" if ratio_chg < 0 else "neu")
            else:
                ratio_chg_str, ratio_dir = "—", "neu"
            rsp_spy_item = {"label": "RSP/SPY", "val": f"{ratio_last:.4f}", "chg": ratio_chg_str, "dir": ratio_dir, "is_dynamic": False}
        else:
            rsp_spy_item = {"label": "RSP/SPY", "val": "—", "chg": "—", "dir": "neu", "is_dynamic": False}
        result["factors"].insert(2, rsp_spy_item)

        # Sector ETFs top 3
        sector_items = []
        for symbol, label in SECTOR_ETFS.items():
            first, last = get_week_vals(symbol)
            chg_str, chg_raw = fmt_chg_pct(first, last)
            sector_items.append({
                "label": f"{symbol} {label}",
                "val": fmt_val(last, "$"),
                "chg": chg_str,
                "dir": direction(chg_raw),
                "is_dynamic": True,
                "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })
        sector_items.sort(key=lambda x: x.get("_abs_chg", 0), reverse=True)
        for s in sector_items[:3]:
            item = {k: v for k, v in s.items() if k != "_abs_chg"}
            result["factors"].append(item)

        # Fear & Greed
        fear_greed = _fetch_fear_greed()
        fg_item = {
            "label": "Fear&Greed",
            "val": fear_greed.get("val", "—"),
            "chg": fear_greed.get("chg", "—"),
            "dir": fear_greed.get("dir", "neu"),
        }
        result["sentiment"].insert(1, fg_item)

        # HYG/LQD ratio
        hyg_first, hyg_last = get_week_vals("HYG")
        lqd_first, lqd_last = get_week_vals("LQD")
        if hyg_last is not None and lqd_last is not None and lqd_last != 0:
            ratio_last = hyg_last / lqd_last
            if hyg_first is not None and lqd_first is not None and lqd_first != 0:
                ratio_first = hyg_first / lqd_first
                ratio_chg = (ratio_last - ratio_first) / ratio_first * 100
                ratio_chg_str = f"{'▲' if ratio_chg > 0 else '▼'} {abs(ratio_chg):.2f}%"
                ratio_dir = "pos" if ratio_chg > 0 else ("neg" if ratio_chg < 0 else "neu")
            else:
                ratio_chg_str, ratio_dir = "—", "neu"
            ratio_item = {"label": "HYG/LQD", "val": f"{ratio_last:.4f}", "chg": ratio_chg_str, "dir": ratio_dir}
        else:
            ratio_item = {"label": "HYG/LQD", "val": "—", "chg": "—", "dir": "neu"}
        result["credit"].insert(2, ratio_item)

        # Liquidity
        fred = fetch_fred_data()
        _empty = lambda lbl: {"label": lbl, "val": "—", "chg": "—", "dir": "neu", "date": ""}
        result["liquidity"] = [
            fred.get("rrp", _empty("RRP餘額")),
            fred.get("tga", _empty("TGA")),
            fred.get("reserves", _empty("銀行準備金")),
            fred.get("nfci", _empty("NFCI")),
        ]
        result["liquidity_assessment"] = assess_liquidity(fred)

        # Dynamic commodities for weekly
        commodity_pool = []
        for symbol, label in COMMODITY_POOL.items():
            first, last = get_week_vals(symbol)
            if last is None:
                continue
            chg_str, chg_raw = fmt_chg_pct(first, last)
            commodity_pool.append({
                "label": label, "val": fmt_val(last, "$"),
                "chg": chg_str, "dir": direction(chg_raw),
                "is_dynamic": True, "_abs_chg": abs(chg_raw) if chg_raw is not None else 0,
            })
        commodity_pool.sort(key=lambda x: x.get("_abs_chg", 0), reverse=True)
        dyn_commodities = []
        for c in commodity_pool[:2]:
            item = {k: v for k, v in c.items() if k != "_abs_chg"}
            dyn_commodities.append(item)
        result["commodities"] = {"fixed": result["commodities"], "dynamic": dyn_commodities}

        # For backwards compat with weekly_template, also provide flat "items" list
        items_flat = []
        for cat in ["indices", "factors", "sentiment", "bonds", "fx", "credit", "liquidity"]:
            items_flat.extend(result[cat])
        # Commodities is now a dict, flatten it
        items_flat.extend(result["commodities"]["fixed"])
        items_flat.extend(result["commodities"]["dynamic"])

        print(f"  ✓ Weekly market: NQ={result['indices'][0]['val']} SP={result['indices'][2]['val']} "
              f"BTC={result['indices'][8]['val']} F&G={fg_item['val']}")

        return {**result, "items": items_flat, "fear_greed": fear_greed, "dynamic": []}
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
    "DIS", "CMCSA", "T", "VZ", "TMUS", "CHTR", "WBD",
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


def fetch_moneydj_news() -> list[dict]:
    """
    抓取 MoneyDJ 即時財經新聞 RSS。
    只取過去24小時內的新聞。
    """
    RSS_URLS = [
        "https://www.moneydj.com/KMDJ/RSS/NewsRSS.aspx?a=MB010000",  # 國際財經
        "https://www.moneydj.com/KMDJ/RSS/NewsRSS.aspx?a=MB020000",  # 台股新聞
        "https://www.moneydj.com/KMDJ/RSS/NewsRSS.aspx?a=MB060000",  # 科技產業
    ]

    tz = pytz.timezone("Asia/Taipei")
    cutoff = datetime.now(tz) - timedelta(hours=24)
    results = []

    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                # 解析發布時間
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published = datetime.fromtimestamp(
                        time.mktime(entry.published_parsed), tz=pytz.utc
                    ).astimezone(tz)

                # 只取24小時內
                if published and published < cutoff:
                    continue

                results.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "source": "MoneyDJ",
                    "published": published.strftime("%Y-%m-%d %H:%M") if published else "",
                })
        except Exception as e:
            print(f"  ✗ MoneyDJ RSS {url}: {e}")

    print(f"  ✓ MoneyDJ: {len(results)} 條新聞（過去24小時）")
    return results


def fetch_deep_dive_news() -> list[dict]:
    """使用 Perplexity 搜尋深度聚焦主題（max_tokens=1000）。"""
    api_key = os.environ["PERPLEXITY_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    results = []

    for query in DEEP_DIVE_QUERIES:
        try:
            payload = {
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Today is {today} Taiwan time (UTC+8). "
                            "Only report news from the past 24 hours. No exceptions. "
                            "Provide detailed data, specific numbers, and source names. "
                            "Focus on structural developments, not surface-level summaries. "
                            "Never include ESG, sustainability, or green energy related news."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "search_recency_filter": "day",
                "return_citations": True,
                "max_tokens": 1000,
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
            print(f"  ✓ [deep] {query[:55]}... ({len(citations)} sources)")
        except Exception as e:
            print(f"  ✗ [deep] {query[:55]}... — {e}")
            results.append({"query": query, "answer": "", "sources": []})

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
