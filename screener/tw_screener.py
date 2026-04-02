"""
tw_screener.py — 台股 RS + VCP Screener
Pool：0050、0051、富櫃50 成分股
Benchmark：^TWII
版本：2026/04/01（下次季度調整：2026/06）
"""
import yfinance as yf
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

BENCHMARK = "^TWII"

ETF_0050 = {
    "2330.TW": "台積電",
    "2308.TW": "台達電",
    "2317.TW": "鴻海",
    "2454.TW": "聯發科",
    "3711.TW": "日月光投控",
    "2891.TW": "中信金",
    "2345.TW": "智邦",
    "2383.TW": "台光電",
    "2382.TW": "廣達",
    "2881.TW": "富邦金",
    "3017.TW": "奇鋐",
    "2882.TW": "國泰金",
    "2303.TW": "聯電",
    "2360.TW": "致茂",
    "2887.TW": "台新新光金",
    "2885.TW": "元大金",
    "2412.TW": "中華電",
    "2884.TW": "玉山金",
    "2886.TW": "兆豐金",
    "2890.TW": "永豐金",
    "1303.TW": "南亞",
    "2327.TW": "國巨",
    "2357.TW": "華碩",
    "3231.TW": "緯創",
    "1216.TW": "統一",
    "6669.TW": "緯穎",
    "3653.TW": "健策",
    "2368.TW": "金像電",
    "2880.TW": "華南金",
    "2883.TW": "凱基金",
    "2892.TW": "第一金",
    "2449.TW": "京元電子",
    "2301.TW": "光寶科",
    "2344.TW": "華邦電",
    "5880.TW": "合庫金",
    "2408.TW": "南亞科",
    "2603.TW": "長榮",
    "7769.TW": "鴻勁",
    "2002.TW": "中鋼",
    "3661.TW": "世芯-KY",
    "3008.TW": "大立光",
    "1301.TW": "台塑",
    "2059.TW": "川湖",
    "4904.TW": "遠傳",
    "3045.TW": "台灣大",
    "2395.TW": "研華",
    "2207.TW": "和泰車",
    "6919.TW": "康霈",
    "6505.TW": "台塑化",
}

ETF_0051 = {
    "3037.TW": "欣興",
    "6770.TW": "力積電",
    "3443.TW": "創意",
    "6446.TW": "藥華藥",
    "2313.TW": "華通",
    "3481.TW": "群創",
    "2404.TW": "漢唐",
    "1101.TW": "台泥",
    "6239.TW": "力成",
    "3044.TW": "健鼎",
    "1326.TW": "台化",
    "1590.TW": "亞德客-KY",
    "2801.TW": "彰銀",
    "5871.TW": "中租-KY",
    "1519.TW": "華城",
    "5876.TW": "上海商銀",
    "4958.TW": "臻鼎-KY",
    "3533.TW": "嘉澤",
    "4938.TW": "和碩",
    "2324.TW": "仁寶",
    "6863.TW": "潁崴",
    "2376.TW": "技嘉",
    "3036.TW": "文曄",
    "2356.TW": "英業達",
    "8046.TW": "南電",
    "2834.TW": "臺企銀",
    "1605.TW": "華新",
    "1504.TW": "東元",
    "6442.TW": "光聖",
    "3657.TW": "大聯大",
    "2618.TW": "長榮航",
    "2474.TW": "可成",
    "2609.TW": "陽明",
    "2409.TW": "友達",
    "6415.TW": "矽力-KY",
    "6139.TW": "亞翔",
    "1402.TW": "遠東新",
    "2347.TW": "聯強",
    "6805.TW": "富世達",
    "1102.TW": "亞泥",
    "2812.TW": "台中銀",
    "1476.TW": "儒鴻",
    "2353.TW": "宏碁",
    "2385.TW": "群光",
    "1513.TW": "中興電",
    "1477.TW": "聚陽",
    "3706.TW": "神達",
    "9904.TW": "寶成",
    "2027.TW": "大成鋼",
    "2049.TW": "上銀",
    "8341.TW": "億豐",
    "6285.TW": "啟碁",
    "1503.TW": "士電",
    "2377.TW": "微星",
    "6409.TW": "旭隼",
    "1802.TW": "台玻",
    "2610.TW": "華航",
    "2105.TW": "正新",
    "2354.TW": "鴻準",
    "5434.TW": "崇越",
    "6176.TW": "瑞儀",
    "3023.TW": "信邦",
    "2633.TW": "台灣高鐵",
    "8210.TW": "勤誠",
    "2542.TW": "興富發",
    "5269.TW": "祥碩",
    "9945.TW": "潤泰新",
    "6531.TW": "愛普",
    "3005.TW": "神基",
    "2371.TW": "大同",
    "1229.TW": "聯華",
    "9910.TW": "豐泰",
    "1319.TW": "東陽",
    "2451.TW": "創見",
    "3406.TW": "玉晶光",
    "1795.TW": "美時",
    "2006.TW": "東和鋼鐵",
    "6750.TW": "采鈺",
    "6856.TW": "禾榮科",
    "6781.TW": "AES-KY",
    "2915.TW": "潤泰全",
    "2845.TW": "遠東銀",
    "6472.TW": "保瑞",
    "6191.TW": "精成科",
    "1722.TW": "台肥",
    "2206.TW": "三陽工業",
    "2646.TW": "星宇航空",
    "4763.TW": "材料-KY",
    "9917.TW": "中保科",
    "2645.TW": "長榮航太",
    "9941.TW": "裕融",
    "6526.TW": "達發",
    "8454.TW": "富邦媒",
    "9911.TW": "櫻花建",
    "2867.TW": "來億-KY",
    "4161.TW": "台灣精銳",
    "2258.TW": "鴻華先進",
}

ETF_00714 = {
    "1785.TWO": "光洋科",
    "1815.TWO": "富喬",
    "3078.TWO": "僑威",
    "3081.TWO": "聯亞",
    "3105.TWO": "穩懋",
    "3131.TWO": "弘塑",
    "3163.TWO": "波若威",
    "3211.TWO": "順達",
    "3227.TWO": "原相",
    "3260.TWO": "威剛",
    "3264.TWO": "欣銓",
    "3293.TWO": "鈤象",
    "3324.TWO": "雙鴻",
    "3363.TWO": "上詮",
    "3374.TWO": "精材",
    "3491.TWO": "昇達科",
    "3529.TWO": "力旺",
    "3680.TWO": "家登",
    "4749.TWO": "新應材",
    "4772.TWO": "台特化",
    "4966.TWO": "譜瑞-KY",
    "4979.TWO": "華星光",
    "5009.TWO": "榮剛",
    "5274.TWO": "信驊",
    "5289.TWO": "宜鼎",
    "5314.TWO": "世紀",
    "5347.TWO": "世界",
    "5371.TWO": "中光電",
    "5439.TWO": "高技",
    "5483.TWO": "中美晶",
    "5536.TWO": "聖暉",
    "5904.TWO": "寶雅",
    "6121.TWO": "新普",
    "6146.TWO": "耕興",
    "6147.TWO": "頎邦",
    "6187.TWO": "萬潤",
    "6188.TWO": "廣明",
    "6223.TWO": "旺矽",
    "6274.TWO": "台燿",
    "6290.TWO": "良維",
    "6488.TWO": "環球晶",
    "6510.TWO": "精測",
    "6548.TWO": "長科",
    "6584.TWO": "南俊國際",
    "7734.TWO": "印能科技",
    "8069.TWO": "元太",
    "8086.TWO": "宏捷科",
    "8299.TWO": "群聯",
    "8358.TWO": "金居",
    "8932.TWO": "智通",
}


def get_tw_watchlist():
    ticker_name = {}
    ticker_etf = {}
    for ticker, name in ETF_0050.items():
        ticker_name[ticker] = name
        ticker_etf[ticker] = "0050"
    for ticker, name in ETF_0051.items():
        if ticker not in ticker_name:
            ticker_name[ticker] = name
            ticker_etf[ticker] = "0051"
    for ticker, name in ETF_00714.items():
        if ticker not in ticker_name:
            ticker_name[ticker] = name
            ticker_etf[ticker] = "富櫃50"
    return list(ticker_name.keys()), ticker_name, ticker_etf


WATCHLIST, TICKER_NAME, TICKER_ETF = get_tw_watchlist()


def run_tw_screener() -> tuple:
    """執行台股 RS + VCP Screener，回傳 (DataFrame, picks dict)"""
    from screener.screener import pick_top_candidates, calc_contraction_score
    import pytz
    from datetime import datetime
    import os, json, glob

    print(f"\n  [TW Screener] 台股篩選：{len(WATCHLIST)} 支")
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    all_tickers = WATCHLIST + [BENCHMARK]
    try:
        data = yf.download(
            all_tickers, period="300d", interval="1d",
            progress=False, auto_adjust=True, threads=True
        )
    except Exception as e:
        print(f"  ✗ 台股數據下載失敗: {e}")
        return pd.DataFrame(), {}

    closes = data.get("Close", pd.DataFrame())
    if isinstance(closes, pd.Series):
        closes = closes.to_frame()
    if closes.empty or BENCHMARK not in closes.columns:
        print("  ✗ 無法取得 benchmark 數據")
        return pd.DataFrame(), {}

    bm = closes[BENCHMARK].dropna()
    bm_ret = {}
    for days, key in [(5, "1w"), (21, "4w"), (63, "13w")]:
        if len(bm) >= days:
            bm_ret[key] = (bm.iloc[-1] - bm.iloc[-days]) / bm.iloc[-days] * 100

    if "13w" not in bm_ret:
        return pd.DataFrame(), {}

    all_returns = {"1w": {}, "4w": {}, "13w": {}}
    for ticker in WATCHLIST:
        if ticker not in closes.columns:
            continue
        c = closes[ticker].dropna()
        for days, key in [(5, "1w"), (21, "4w"), (63, "13w")]:
            if len(c) >= days:
                all_returns[key][ticker] = (c.iloc[-1] - c.iloc[-days]) / c.iloc[-days] * 100

    def pct_rank(val, all_vals):
        vals = list(all_vals.values())
        return round(sum(1 for v in vals if v <= val) / len(vals) * 100, 1) if vals else 50

    rows = []
    for ticker in WATCHLIST:
        if ticker not in all_returns.get("13w", {}):
            continue

        rs_1w = pct_rank(all_returns["1w"].get(ticker, 0), all_returns["1w"])
        rs_4w = pct_rank(all_returns["4w"].get(ticker, 0), all_returns["4w"])
        rs_13w = pct_rank(all_returns["13w"][ticker], all_returns["13w"])
        persistence = rs_1w * 0.2 + rs_4w * 0.3 + rs_13w * 0.5

        if rs_1w > rs_4w > rs_13w:
            trend, bonus = "加速上升", 5
        elif rs_1w >= rs_4w >= rs_13w:
            trend, bonus = "穩定維持", 2
        elif rs_1w < rs_4w < rs_13w:
            trend, bonus = "開始衰退", -5
        else:
            trend, bonus = "震盪", 0

        rs_score = min(100, persistence + bonus)

        # VCP Score
        vcp_result = {}
        try:
            highs = data.get("High", pd.DataFrame())
            lows = data.get("Low", pd.DataFrame())
            volumes = data.get("Volume", pd.DataFrame())
            if (ticker in closes.columns and ticker in highs.columns and
                    ticker in lows.columns and ticker in volumes.columns):
                c = closes[ticker].dropna()
                if len(c) >= 60:
                    sub_data = {
                        "Close": closes[[ticker]],
                        "High": highs[[ticker]],
                        "Low": lows[[ticker]],
                        "Volume": volumes[[ticker]],
                    }
                    tmp = calc_contraction_score(sub_data, [ticker])
                    vcp_result = tmp.get(ticker, {})
        except Exception:
            pass

        vcp_score = vcp_result.get("contraction_score", 50)
        combined = rs_score * 0.6 + vcp_score * 0.4

        c = closes[ticker].dropna()
        price = round(float(c.iloc[-1]), 1)

        vs_ma = None
        if len(c) >= 200:
            ma200 = float(c.iloc[-200:].mean())
            vs_ma = round((price - ma200) / ma200 * 100, 2)

        rows.append({
            "Ticker": ticker,
            "Name": TICKER_NAME.get(ticker, ticker),
            "ETF": TICKER_ETF.get(ticker, ""),
            "RS_Score": round(rs_score, 1),
            "rs_1w": rs_1w,
            "rs_4w": rs_4w,
            "rs_13w": rs_13w,
            "rs_trend": trend,
            "Contraction_Score": round(vcp_score, 1),
            "Combined_Score": round(combined, 1),
            "Price": price,
            "vs_200MA_pct": vs_ma,
            "vcp_pullback_count": vcp_result.get("vcp_pullback_count"),
            "last_pullback_pct": vcp_result.get("last_pullback_pct"),
            "dist_from_high_pct": vcp_result.get("dist_from_high_pct"),
            "rising_lows": vcp_result.get("rising_lows"),
            "volume_ratio": vcp_result.get("volume_ratio"),
            "Rank_Change": None,
            "Rank_Change_Str": "—",
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df, {}

    df = df.sort_values("Combined_Score", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    # 排名變化
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    history_dir = os.path.join(repo_root, "docs", "screener", "tw_history")
    os.makedirs(history_dir, exist_ok=True)
    history_files = sorted(glob.glob(os.path.join(history_dir, "*.json")))
    history_files = [f for f in history_files if today not in f]

    if history_files:
        try:
            with open(history_files[-1]) as f:
                prev = json.load(f)
            prev_ranks = {item["Ticker"]: item["Rank"] for item in prev.get("data", [])}

            def calc_change(row):
                t = row["Ticker"]
                curr = int(row["Rank"])
                if t not in prev_ranks:
                    return None, "新進"
                prev_r = int(prev_ranks[t])
                change = prev_r - curr
                if change > 0:
                    return change, f"↑{change}"
                elif change < 0:
                    return change, f"↓{abs(change)}"
                else:
                    return 0, "—"

            df["Rank_Change"], df["Rank_Change_Str"] = zip(*df.apply(calc_change, axis=1))
        except Exception:
            pass

    # 今日精選
    picks = pick_top_candidates(df)

    # 發布 history
    screener_dir = os.path.join(repo_root, "docs", "screener")
    all_records = df[["Rank", "Ticker", "Name", "ETF", "RS_Score", "rs_trend",
                       "Contraction_Score", "Combined_Score", "Price", "vs_200MA_pct"]].to_dict(orient="records")
    with open(os.path.join(history_dir, f"{today}.json"), "w", encoding="utf-8") as f:
        json.dump({"date": today, "total": len(df), "data": all_records}, f, ensure_ascii=False)
    with open(os.path.join(screener_dir, "tw_latest.json"), "w", encoding="utf-8") as f:
        json.dump({"date": today, "total": len(df), "data": all_records}, f, ensure_ascii=False)

    print(f"  ✓ 台股 Screener 完成：{len(df)} 支")
    return df, picks
