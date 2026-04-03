import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import json
import glob as glob_mod
import os
import warnings
warnings.filterwarnings('ignore')

# ── 內建 Watchlist（備用，當 Excel 不存在時使用）────────────────
_WATCHLIST_FALLBACK = [
    # Technology
    "GOOG","NVDA","GLW","PLTR","TSLA","AVGO","AAPL","VRT","LITE","ANET",
    "MSFT","META","AMD","INTC","ASML","AMAT","LRCX","KLAC","TSM","ARM",
    "QCOM","MU","MRVL","WOLF","ON","MPWR","ENTG","ONTO","ACLS","COHU",
    "TER","FORM","SNOW","CRM","NOW","ADBE","ORCL","IBM","UBER","LYFT",
    "ABNB","DASH","CRWD","PANW","ZS","OKTA","NET","DDOG","MDB","GTLB",
    "ESTC","HUBS","TTD","RBLX","U","PINS","SNAP","SHOP","XYZ",
    "COIN","HOOD","SOFI","AFRM","UPST","LC","MSTR","SMCI","DELL","HPQ",
    "HPE","CSCO","NTAP","PSTG","WDC","STX","NXPI","MCHP","ADI",
    "TXN","LSCC","SLAB","ALGM","DIOD","SITM","AMBA","CRUS","SWKS",
    "QRVO","MKSI","CEVA","HIMX","SIMO","CDNS",
    "SNPS","MANH","VEEV","WDAY","INTU","ADSK","PTC","NTNX","DSGX","EPAM",
    "GLOB","FLYW","PAYO","FOUR","GPN","FIS","FISV","MA","V","AXP",
    # Consumer
    "AMZN","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","WBD",
    "NWSA","FOX","LYV","IMAX","AMC","CNK","CARG","OPEN",
    "Z","EXPI","OPAD","MTH","DHI","LEN","PHM","TOL",
    "NVR","TMHC","MHO","SKY","CVCO","WH","HLT","MAR","H",
    "ABNB","BKNG","EXPE","TRIP","PCLN","LMND","ROOT",
    "HUM","CVS","DRVN","BROS","CAVA","SHAK","WING",
    "TXRH","DRI","EAT","CMG","MCD","SBUX","YUM","QSR","JACK",
    "PLAY","RRGB","CAKE","BLMN","BJRI","KRUS","YELP","DASH",
    "WMT","COST","TGT","LOW","HD","AMZN","ETSY","W","BBWI","VSCO",
    "NKE","LULU","UAA","PVH","RL","CRI","COLM","VFC","GOOS",
    "TJX","ROST","DLTR","DG","BJ","FIVE","OLLI","GRWG","BYND",
    "MAPS","TLRY","CGC","ACB","CRON","SNDL",
    "MO","PM","BTI","CARR","GE","HON","MMM",
    # Industrials
    "CAT","DE","EMR","ETN","PH","ROK","ITW","DOV","IR","XYL",
    "GNRC","CSGP","JBHT","CHRW","EXPD","XPO","ODFL","SAIA","WERN","KNX",
    "ARCB","MRTN","HTLD","RUSHA","PCAR","CMI","ALSN","TRN","GATX",
    "WAB","TT","LII","MAS","AOS","SWK","SNA","KMT","TDG",
    "HEI","TDY","TXT","HXL","CW","KTOS","RCAT","LMT","RTX",
    "NOC","GD","BA","HII","LHX","DRS","CACI","LDOS","SAIC","BAH",
    "VIAV","CALX","ADTN","AAOI",
    "COHR","LITE","IPGP","POET","CLFD","ATEN",
    "ATNI","IDT","LUMN","SHEN",
    # Financials
    "JPM","BAC","WFC","C","GS","MS","BLK","SCHW","ICE","CME",
    "SPGI","MCO","BX","KKR","APO","ARES","CG","OWL","HLNE","STEP",
    "AMG","VCTR","VIRT","MKTX","GFI","PIPR","SF","HLI",
    "LPLA","RJF","SEIC","APAM","TROW","IVZ","BEN",
    "IAU","GLD","SLV","PPLT","PALL","USO","UNG","DBO","BNO",
    # Energy
    "XOM","CVX","COP","EOG","DVN","FANG","APA","OXY",
    "SLB","HAL","BKR","PSX","VLO","MPC","DK","PARR","CAPL",
    # Healthcare
    "LLY","JNJ","UNH","ABT","TMO","DHR","MDT","SYK","BSX","EW",
    "ISRG","DXCM","PODD","TNDM","GKOS","SHPH","NVCR","TTOO",
    # Communication
    "GOOGL","META","NFLX","DIS","CMCSA","T","VZ",
    # Materials
    "LIN","APD","ECL","SHW","PPG","NEM","FCX","AA",
]
_WATCHLIST_FALLBACK = list(dict.fromkeys([t for t in _WATCHLIST_FALLBACK if t and len(t) <= 5]))

# 內建產業分類（備用）
_SECTOR_FALLBACK = {
    "Technology": [
        "GOOG","NVDA","GLW","PLTR","TSLA","AVGO","AAPL","VRT","LITE","ANET",
        "MSFT","META","AMD","INTC","ASML","AMAT","LRCX","KLAC","TSM","ARM",
        "QCOM","MU","MRVL","WOLF","ON","MPWR","ENTG","ONTO","ACLS","COHU",
        "TER","FORM","SNOW","CRM","NOW","ADBE","ORCL","IBM","UBER","LYFT",
        "ABNB","DASH","CRWD","PANW","ZS","OKTA","NET","DDOG","MDB","GTLB",
        "ESTC","HUBS","TTD","RBLX","U","PINS","SNAP","SHOP","XYZ",
        "COIN","HOOD","SOFI","AFRM","UPST","LC","MSTR","SMCI","DELL","HPQ",
        "HPE","CSCO","NTAP","PSTG","WDC","STX","NXPI","MCHP","ADI",
        "TXN","LSCC","SLAB","ALGM","DIOD","SITM","AMBA","CRUS","SWKS",
        "QRVO","MKSI","CEVA","HIMX","SIMO","CDNS",
        "SNPS","MANH","VEEV","WDAY","INTU","ADSK","PTC","NTNX","DSGX","EPAM",
        "GLOB","FLYW","PAYO","FOUR","GPN","FIS","FISV","MA","V","AXP",
        "GOOGL",
    ],
    "Consumer": [
        "AMZN","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","WBD",
        "NWSA","FOX","LYV","IMAX","AMC","CNK","CARG","OPEN",
        "Z","EXPI","OPAD","MTH","DHI","LEN","PHM","TOL",
        "NVR","TMHC","MHO","SKY","CVCO","WH","HLT","MAR","H",
        "BKNG","EXPE","TRIP","PCLN","LMND","ROOT",
        "HUM","CVS","DRVN","BROS","CAVA","SHAK","WING",
        "TXRH","DRI","EAT","CMG","MCD","SBUX","YUM","QSR","JACK",
        "PLAY","RRGB","CAKE","BLMN","BJRI","KRUS","YELP",
        "WMT","COST","TGT","LOW","HD","ETSY","W","BBWI","VSCO",
        "NKE","LULU","UAA","PVH","RL","CRI","COLM","VFC","GOOS",
        "TJX","ROST","DLTR","DG","BJ","FIVE","OLLI","GRWG","BYND",
        "MAPS","TLRY","CGC","ACB","CRON","SNDL",
        "MO","PM","BTI","CARR","GE","HON","MMM",
    ],
    "Industrials": [
        "CAT","DE","EMR","ETN","PH","ROK","ITW","DOV","IR","XYL",
        "GNRC","CSGP","JBHT","CHRW","EXPD","XPO","ODFL","SAIA","WERN","KNX",
        "ARCB","MRTN","HTLD","RUSHA","PCAR","CMI","ALSN","TRN","GATX",
        "WAB","TT","LII","MAS","AOS","SWK","SNA","KMT","TDG",
        "HEI","TDY","TXT","HXL","CW","KTOS","RCAT","LMT","RTX",
        "NOC","GD","BA","HII","LHX","DRS","CACI","LDOS","SAIC","BAH",
        "VIAV","CALX","ADTN","AAOI",
        "COHR","IPGP","POET","CLFD","ATEN",
        "ATNI","IDT","LUMN","SHEN",
    ],
    "Financials": [
        "JPM","BAC","WFC","C","GS","MS","BLK","SCHW","ICE","CME",
        "SPGI","MCO","BX","KKR","APO","ARES","CG","OWL","HLNE","STEP",
        "AMG","VCTR","VIRT","MKTX","GFI","PIPR","SF","HLI",
        "LPLA","RJF","SEIC","APAM","TROW","IVZ","BEN",
        "IAU","GLD","SLV","PPLT","PALL","USO","UNG","DBO","BNO",
    ],
    "Energy": [
        "XOM","CVX","COP","EOG","DVN","FANG","APA","OXY",
        "SLB","HAL","BKR","PSX","VLO","MPC","DK","PARR","CAPL",
    ],
    "Healthcare": [
        "LLY","JNJ","UNH","ABT","TMO","DHR","MDT","SYK","BSX","EW",
        "ISRG","DXCM","PODD","TNDM","GKOS","SHPH","NVCR","TTOO",
    ],
    "Materials": [
        "LIN","APD","ECL","SHW","PPG","NEM","FCX","AA",
    ],
}

_TICKER_SECTOR_FALLBACK = {}
for _sector, _tickers in _SECTOR_FALLBACK.items():
    for _t in _tickers:
        if _t not in _TICKER_SECTOR_FALLBACK:
            _TICKER_SECTOR_FALLBACK[_t] = _sector

BENCHMARK = "SPY"


# ── Watchlist 載入（Excel 優先，內建備用）─────────────────────
def load_watchlist():
    """從 Watchlist_Tickers_CIK.xlsx 讀取 watchlist + sector，找不到時用內建清單"""
    # 搜尋 Excel 檔案（repo 根目錄或 screener/ 目錄）
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in [
        os.path.join(repo_root, "Watchlist_Tickers_CIK.xlsx"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "Watchlist_Tickers_CIK.xlsx"),
    ]:
        if os.path.exists(candidate):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(candidate)
                ws = wb.active
                tickers = []
                sector_map = {}
                for row in list(ws.iter_rows(values_only=True))[3:]:
                    if not row[0] or row[0] == "Ticker":
                        continue
                    ticker = str(row[0]).strip()
                    sector = str(row[3]).strip() if len(row) > 3 and row[3] else "Unknown"
                    tickers.append(ticker)
                    sector_map[ticker] = sector
                tickers = list(dict.fromkeys([t for t in tickers if t and len(t) <= 5]))
                print(f"  ✓ Watchlist 從 Excel 讀取：{len(tickers)} 支（{candidate}）")
                return tickers, sector_map
            except Exception as e:
                print(f"  ✗ Excel 讀取失敗: {e}")
                break

    print(f"  ℹ Excel 不存在，使用內建清單：{len(_WATCHLIST_FALLBACK)} 支")
    return _WATCHLIST_FALLBACK, _TICKER_SECTOR_FALLBACK


WATCHLIST, TICKER_SECTOR = load_watchlist()


def calc_rank_change(df: pd.DataFrame, today: str) -> pd.DataFrame:
    """跟上次結果比較排名變化"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    history_dir = os.path.join(repo_root, "docs", "screener", "history")

    history_files = sorted(glob_mod.glob(os.path.join(history_dir, "*.json")))
    history_files = [f for f in history_files if today not in f]

    if not history_files:
        df["Rank_Change"] = None
        df["Rank_Change_Str"] = "—"
        return df

    with open(history_files[-1]) as f:
        prev = json.load(f)

    prev_ranks = {item["Ticker"]: item["Rank"] for item in prev.get("data", [])}

    def calc_change(row):
        ticker = row["Ticker"]
        curr_rank = int(row["Rank"])
        if ticker not in prev_ranks:
            return pd.Series([None, "新進"])
        prev_rank = int(prev_ranks[ticker])
        change = prev_rank - curr_rank
        if change > 0:
            return pd.Series([change, f"↑{change}"])
        elif change < 0:
            return pd.Series([change, f"↓{abs(change)}"])
        else:
            return pd.Series([0, "—"])

    df[["Rank_Change", "Rank_Change_Str"]] = df.apply(calc_change, axis=1)
    return df


def fetch_data(tickers: list[str], period: str = "300d") -> dict:
    """批次下載所有 ticker 的日線數據"""
    print(f"  下載 {len(tickers)} 支股票數據...")
    all_tickers = tickers + [BENCHMARK]

    try:
        data = yf.download(
            all_tickers,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        return data
    except Exception as e:
        print(f"  ✗ 下載失敗: {e}")
        return {}

def calc_rs_score(data: dict, tickers: list[str]) -> dict:
    """計算 RS Persistence Score：三時間維度加權 + 趨勢加分"""
    closes = data.get("Close", pd.DataFrame())
    if closes.empty or BENCHMARK not in closes.columns:
        return {}

    spy = closes[BENCHMARK].dropna()
    if len(spy) < 63:
        return {}

    # SPY 各時間段漲跌幅
    spy_ret = {
        "1w":  (spy.iloc[-1] - spy.iloc[-5])  / spy.iloc[-5]  * 100 if len(spy) >= 5  else None,
        "4w":  (spy.iloc[-1] - spy.iloc[-21]) / spy.iloc[-21] * 100 if len(spy) >= 21 else None,
        "13w": (spy.iloc[-1] - spy.iloc[-63]) / spy.iloc[-63] * 100 if len(spy) >= 63 else None,
    }

    # 計算所有股票的各時段漲跌幅
    all_returns = {"1w": {}, "4w": {}, "13w": {}}

    for ticker in tickers:
        if ticker not in closes.columns:
            continue
        c = closes[ticker].dropna()

        if len(c) >= 5:
            all_returns["1w"][ticker]  = (c.iloc[-1] - c.iloc[-5])  / c.iloc[-5]  * 100
        if len(c) >= 21:
            all_returns["4w"][ticker]  = (c.iloc[-1] - c.iloc[-21]) / c.iloc[-21] * 100
        if len(c) >= 63:
            all_returns["13w"][ticker] = (c.iloc[-1] - c.iloc[-63]) / c.iloc[-63] * 100

    # 計算百分位排名
    def percentile_rank(val, all_vals):
        vals = list(all_vals.values())
        return sum(1 for v in vals if v <= val) / len(vals) * 100 if vals else 50

    results = {}
    for ticker in tickers:
        rs_scores = {}
        for period in ["1w", "4w", "13w"]:
            if ticker in all_returns[period]:
                rs_scores[period] = round(percentile_rank(
                    all_returns[period][ticker], all_returns[period]
                ), 1)

        if "13w" not in rs_scores:
            continue

        # RS Persistence Score（加權平均）
        rs_1w  = rs_scores.get("1w",  rs_scores["13w"])
        rs_4w  = rs_scores.get("4w",  rs_scores["13w"])
        rs_13w = rs_scores["13w"]

        persistence = rs_1w * 0.2 + rs_4w * 0.3 + rs_13w * 0.5

        # RS 趨勢方向
        if rs_1w > rs_4w > rs_13w:
            rs_trend = "加速上升"
            trend_bonus = 5
        elif rs_1w >= rs_4w >= rs_13w:
            rs_trend = "穩定維持"
            trend_bonus = 2
        elif rs_1w < rs_4w < rs_13w:
            rs_trend = "開始衰退"
            trend_bonus = -5
        else:
            rs_trend = "震盪"
            trend_bonus = 0

        final_rs = min(100, persistence + trend_bonus)

        results[ticker] = {
            "rs_score": round(final_rs, 1),
            "rs_1w": rs_1w,
            "rs_4w": rs_4w,
            "rs_13w": rs_13w,
            "rs_trend": rs_trend,
            "return_63d": round(all_returns["13w"].get(ticker, 0), 2),
            "vs_spy_63d": round(
                all_returns["13w"].get(ticker, 0) - (spy_ret["13w"] or 0), 2
            ),
        }

    return results

def calc_contraction_score(data: dict, tickers: list[str]) -> dict:
    """
    升級版 VCP 演算法，修復四個問題：
    1. 假回撤過濾（回撤 < 3% 不算、高點間距 < 10日不算）
    2. 底部抬高檢查（每次回撤低點要比上次高）
    3. 趨勢過濾（股價 > 150MA > 200MA）
    4. 逐次回撤的量能比較（不是整體均量）
    """
    closes  = data.get("Close",  pd.DataFrame())
    highs   = data.get("High",   pd.DataFrame())
    lows    = data.get("Low",    pd.DataFrame())
    volumes = data.get("Volume", pd.DataFrame())

    if closes.empty:
        return {}

    results = {}

    for ticker in tickers:
        try:
            if ticker not in closes.columns:
                continue

            c = closes[ticker].dropna()
            h = highs[ticker].dropna()
            l = lows[ticker].dropna()
            v = volumes[ticker].dropna()

            if len(c) < 150:
                continue

            # ── 趨勢過濾：股價 > 150MA > 200MA ──────────────
            ma150 = c.iloc[-150:].mean()
            ma200 = c.iloc[-200:].mean() if len(c) >= 200 else c.mean()
            current_price = float(c.iloc[-1])

            trend_ok = current_price > ma150 > ma200
            trend_score = 20 if trend_ok else 0

            # ── 找局部高點（近90日，11日視窗）────────────────
            window = min(len(c), 90)
            c_w = c.iloc[-window:]
            h_w = h.iloc[-window:]
            l_w = l.iloc[-window:]
            v_w = v.iloc[-window:]

            local_highs = []
            for i in range(10, len(c_w) - 5):
                if float(h_w.iloc[i]) == float(h_w.iloc[i-10:i+6].max()):
                    local_highs.append((i, float(h_w.iloc[i])))

            # 合併太近的高點（間距 < 10日只保留較高的）
            filtered_highs = []
            for idx, val in local_highs:
                if filtered_highs and idx - filtered_highs[-1][0] < 10:
                    if val > filtered_highs[-1][1]:
                        filtered_highs[-1] = (idx, val)
                else:
                    filtered_highs.append((idx, val))
            local_highs = filtered_highs

            # ── 建立回撤序列（兩高點之間找最低點）────────────
            pullbacks = []
            for i in range(len(local_highs) - 1):
                high_idx, high_val = local_highs[i]
                next_high_idx = local_highs[i+1][0]

                segment_lows = l_w.iloc[high_idx:next_high_idx]
                if segment_lows.empty:
                    continue

                low_val = float(segment_lows.min())
                low_idx = high_idx + int(segment_lows.values.argmin())

                pullback_pct = (high_val - low_val) / high_val * 100

                # 回撤 < 3% 不算有效收縮
                if pullback_pct < 3:
                    continue

                avg_vol = float(v_w.iloc[high_idx:low_idx+1].mean()) if low_idx > high_idx else float(v_w.iloc[high_idx])

                pullbacks.append({
                    "high_idx": high_idx,
                    "low_idx": low_idx,
                    "high": high_val,
                    "low": low_val,
                    "pullback_pct": pullback_pct,
                    "avg_vol": avg_vol,
                })

            # ── VCP 評分 ──────────────────────────────────────
            vcp_score = trend_score

            n_pullbacks = len(pullbacks)

            # 評分1：有效收縮次數（2-4次最理想）
            if 2 <= n_pullbacks <= 4:
                vcp_score += 20
            elif n_pullbacks == 1:
                vcp_score += 8
            elif n_pullbacks > 4:
                vcp_score += 10

            rising_lows = None
            if n_pullbacks >= 2:
                # 評分2：回撤幅度遞減
                pullback_pcts = [p["pullback_pct"] for p in pullbacks]
                decreasing_pullbacks = all(
                    pullback_pcts[i+1] < pullback_pcts[i]
                    for i in range(len(pullback_pcts)-1)
                )
                if decreasing_pullbacks:
                    vcp_score += 15

                # 評分2b：底部抬高檢查
                lows_list = [p["low"] for p in pullbacks]
                rising_lows = all(
                    lows_list[i+1] > lows_list[i]
                    for i in range(len(lows_list)-1)
                )
                if rising_lows:
                    vcp_score += 15

                # 評分2c：逐次回撤量能遞減
                vols = [p["avg_vol"] for p in pullbacks]
                decreasing_vol = all(
                    vols[i+1] < vols[i]
                    for i in range(len(vols)-1)
                )
                if decreasing_vol:
                    vcp_score += 10

            # 評分3：最後一次回撤幅度
            if pullbacks:
                last_pb = pullbacks[-1]["pullback_pct"]
                if last_pb < 4:
                    vcp_score += 15
                elif last_pb < 6:
                    vcp_score += 10
                elif last_pb < 10:
                    vcp_score += 5

            # 評分4：距前期高點距離
            dist_from_high = None
            if local_highs:
                recent_high = max(local_highs, key=lambda x: x[0])[1]
                dist_from_high = (recent_high - current_price) / recent_high * 100
                if dist_from_high < 3:
                    vcp_score += 15
                elif dist_from_high < 5:
                    vcp_score += 10
                elif dist_from_high < 10:
                    vcp_score += 5
                else:
                    vcp_score -= 5

            # ATR 收縮輔助確認
            tr = pd.concat([
                h - l,
                (h - c.shift(1)).abs(),
                (l - c.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr_10 = tr.iloc[-10:].mean()
            atr_60 = tr.iloc[-60:].mean()
            atr_ratio = atr_10 / atr_60 if atr_60 > 0 else 1
            if atr_ratio < 0.5:
                vcp_score += 10
            elif atr_ratio < 0.7:
                vcp_score += 5

            vcp_score = max(0, min(100, vcp_score))

            results[ticker] = {
                "contraction_score": round(vcp_score, 1),
                "vcp_pullback_count": n_pullbacks,
                "last_pullback_pct": round(pullbacks[-1]["pullback_pct"], 1) if pullbacks else None,
                "dist_from_high_pct": round(dist_from_high, 1) if dist_from_high is not None else None,
                "rising_lows": rising_lows,
                "trend_ok": trend_ok,
                "atr_contraction": round((1 - atr_ratio) * 100, 1),
                "price_range_pct": round(
                    (h_w.iloc[-10:].max() - l_w.iloc[-10:].min()) / current_price * 100, 2
                ),
                "volume_ratio": round(
                    float(v.iloc[-10:].mean()) / float(v.iloc[-60:].mean()), 2
                ) if float(v.iloc[-60:].mean()) > 0 else 1.0,
            }

        except Exception:
            continue

    return results

def pick_top_candidates(df: pd.DataFrame) -> dict:
    """
    三個方向各選1支最佳候選股
    返回 {"minervini": {...}, "momentum": {...}, "vcp": {...}}
    """
    records = df.to_dict(orient="records")

    # ── 方向一：Minervini 最佳組合（最低門檻 RS>=75, VCP>=65）
    minervini_conditions = [
        lambda r: (
            r.get("RS_Score", 0) >= 80 and
            r.get("Contraction_Score", 0) >= 75 and
            r.get("rs_trend") == "加速上升" and
            (r.get("dist_from_high_pct") or 99) < 5 and
            (r.get("volume_ratio") or r.get("Volume_Ratio_10d_60d") or 1) < 0.8
        ),
        lambda r: (
            r.get("RS_Score", 0) >= 80 and
            r.get("Contraction_Score", 0) >= 75 and
            r.get("rs_trend") == "加速上升" and
            (r.get("dist_from_high_pct") or 99) < 8
        ),
        lambda r: (
            r.get("RS_Score", 0) >= 78 and
            r.get("Contraction_Score", 0) >= 70 and
            r.get("rs_trend") in ["加速上升", "穩定維持"]
        ),
        lambda r: (
            r.get("RS_Score", 0) >= 75 and
            r.get("Contraction_Score", 0) >= 65
        ),
    ]

    minervini_pick = None
    for condition in minervini_conditions:
        candidates = [r for r in records if condition(r)]
        if candidates:
            candidates.sort(key=lambda r: r.get("Combined_Score", 0), reverse=True)
            minervini_pick = candidates[0]
            break

    # ── 方向二：排名上升最多（必須有真實排名上升 + RS>=65）
    momentum_pick = None
    ranked_up = [
        r for r in records
        if isinstance(r.get("Rank_Change"), (int, float)) and r["Rank_Change"] > 0
        and r.get("RS_Score", 0) >= 65
    ]
    if ranked_up:
        ranked_up.sort(key=lambda r: r.get("Rank_Change", 0), reverse=True)
        momentum_pick = ranked_up[0]
    # 沒有排名上升的就不選（不 fallback）

    # ── 方向三：VCP 形態最完美（最低門檻 VCP>=75, RS>=70）
    vcp_pick = None
    vcp_candidates = [
        r for r in records
        if r.get("Contraction_Score", 0) >= 75
        and r.get("RS_Score", 0) >= 70
    ]
    if vcp_candidates:
        vcp_candidates.sort(key=lambda r: (
            r.get("Contraction_Score", 0) * 0.7 +
            r.get("RS_Score", 0) * 0.3
        ), reverse=True)
        vcp_pick = vcp_candidates[0]
    # 沒有符合門檻的就不選（不 fallback）

    # 確保三個方向選不同的股票
    used_tickers = set()
    result = {}

    for key, pick in [("minervini", minervini_pick), ("momentum", momentum_pick), ("vcp", vcp_pick)]:
        if pick is None:
            continue
        ticker = pick.get("Ticker", "")
        if ticker in used_tickers:
            # 從同方向符合門檻的候選人中找不重複的
            pool = {
                "minervini": [r for r in records if r.get("RS_Score", 0) >= 75 and r.get("Contraction_Score", 0) >= 65],
                "momentum":  [r for r in ranked_up if r.get("Ticker") not in used_tickers],
                "vcp":       [r for r in records if r.get("Contraction_Score", 0) >= 75 and r.get("RS_Score", 0) >= 70],
            }
            found = False
            for alt in pool.get(key, []):
                if alt.get("Ticker") not in used_tickers:
                    pick = alt
                    ticker = alt.get("Ticker", "")
                    found = True
                    break
            if not found:
                continue  # 找不到不重複的就跳過這個方向

        used_tickers.add(ticker)
        result[key] = {
            **pick,
            "reason": generate_pick_reason(pick),
        }

    return result


def generate_pick_reason(pick: dict) -> str:
    """產出一句話說明選股原因"""
    rs = pick.get("RS_Score", 0) or 0
    vcp = pick.get("Contraction_Score", 0) or 0
    trend = pick.get("rs_trend", "")
    dist = pick.get("dist_from_high_pct")
    vol = pick.get("Volume_Ratio_10d_60d") or pick.get("volume_ratio")
    vs_ma = pick.get("vs_200MA_pct")
    pullbacks = pick.get("vcp_pullback_count", 0)
    last_pb = pick.get("last_pullback_pct")
    rank_change = pick.get("Rank_Change")
    rising_lows = pick.get("rising_lows")

    reasons = []
    if rs >= 80:
        reasons.append(f"RS {rs:.0f}")
    if trend == "加速上升":
        reasons.append("RS加速上升")
    elif trend == "穩定維持":
        reasons.append("RS穩定維持")
    if vcp >= 75:
        reasons.append(f"VCP {vcp:.0f}")
    if pullbacks and pullbacks >= 2:
        reasons.append(f"{pullbacks}次收縮")
    if rising_lows:
        reasons.append("底部抬高")
    if last_pb and last_pb < 8:
        reasons.append(f"末段回撤{last_pb:.1f}%")
    if dist and dist < 5:
        reasons.append(f"距前高{dist:.1f}%")
    if vol and vol < 0.8:
        reasons.append(f"量縮{vol:.2f}x")
    if vs_ma and vs_ma > 0:
        reasons.append(f"200MA+{vs_ma:.1f}%")
    if rank_change and rank_change > 0:
        reasons.append(f"排名↑{rank_change}")

    return "、".join(reasons[:5]) if reasons else f"綜合分 {pick.get('Combined_Score', 0):.0f}"


def fetch_fundamentals(tickers: list) -> dict:
    """對 Top 30 股票單獨查詢基本面數據"""
    results = {}
    print(f"  [基本面] 查詢 {len(tickers)} 支股票...")

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info

            fwd_eps = info.get("forwardEps")
            trail_eps = info.get("trailingEps")

            eps_next_yr = None
            try:
                est = t.earnings_estimate
                if est is not None and not est.empty:
                    if "+1y" in est.index:
                        v = est.loc["+1y", "avg"] if "avg" in est.columns else None
                        eps_next_yr = round(float(v), 2) if v is not None and not pd.isna(v) else None
            except Exception:
                pass

            # EPS 2年真正 CAGR：trailingEps → +1Y 預估，(next/trail)^0.5 - 1
            eps_cagr_2y = None
            if trail_eps and eps_next_yr and trail_eps > 0 and eps_next_yr > 0:
                eps_cagr_2y = round(((eps_next_yr / trail_eps) ** 0.5 - 1) * 100, 1)

            fcf = info.get("freeCashflow")
            rev = info.get("totalRevenue")
            fcf_margin = round(fcf / rev * 100, 1) if fcf and rev and rev > 0 else None

            roe = info.get("returnOnEquity")
            roa = info.get("returnOnAssets")
            roic_approx, roic_source = None, None
            if roe is not None:
                roic_approx, roic_source = round(roe * 100, 1), "ROE"
            elif roa is not None:
                roic_approx, roic_source = round(roa * 100, 1), "ROA"

            op_margin = info.get("operatingMargins")
            op_margin_pct = round(op_margin * 100, 1) if op_margin is not None else None

            gross_margin = info.get("grossMargins")
            gross_margin_pct = round(gross_margin * 100, 1) if gross_margin is not None else None

            rev_growth = info.get("revenueGrowth")
            rev_growth_pct = round(rev_growth * 100, 1) if rev_growth is not None else None

            results[ticker] = {
                "eps_ttm": round(trail_eps, 2) if trail_eps is not None else None,
                "eps_fwd": round(fwd_eps, 2) if fwd_eps is not None else None,
                "eps_next_yr": eps_next_yr,
                "eps_cagr_2y": eps_cagr_2y,
                "fcf_margin": fcf_margin,
                "roic": roic_approx,
                "roic_source": roic_source,
                "op_margin": op_margin_pct,
                "gross_margin": gross_margin_pct,
                "rev_growth": rev_growth_pct,
            }
            print(f"    ✓ {ticker}: EPS CAGR 2Y={eps_cagr_2y}% FCF={fcf_margin}% ROIC={roic_approx}%")

        except Exception as e:
            print(f"    ✗ {ticker}: {e}")
            results[ticker] = {}

    return results


def calc_ma_position(data: dict, tickers: list[str]) -> dict:
    """計算距離200日均線的位置"""
    closes = data.get("Close", pd.DataFrame())
    results = {}

    for ticker in tickers:
        try:
            if ticker not in closes.columns:
                continue
            c = closes[ticker].dropna()
            if len(c) < 200:
                continue
            ma200 = c.iloc[-200:].mean()
            vs_ma200 = (c.iloc[-1] - ma200) / ma200 * 100
            results[ticker] = round(vs_ma200, 2)
        except Exception:
            continue

    return results

def run_screener() -> pd.DataFrame:
    """執行完整 Screener，回傳排名 DataFrame"""
    print("\n" + "="*50)
    print("RS + Contraction Screener")
    print("="*50)

    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")
    print(f"  日期：{today}")
    print(f"  標的數量：{len(WATCHLIST)}")

    # 下載數據
    data = fetch_data(WATCHLIST)
    if isinstance(data, pd.DataFrame) and data.empty:
        print("  ✗ 數據下載失敗")
        return pd.DataFrame()
    if isinstance(data, dict) and not data:
        print("  ✗ 數據下載失敗")
        return pd.DataFrame()

    # 計算各指標
    print("  計算 RS Score...")
    rs_results = calc_rs_score(data, WATCHLIST)

    print("  計算 Contraction Score...")
    contraction_results = calc_contraction_score(data, WATCHLIST)

    print("  計算 MA 位置...")
    ma_results = calc_ma_position(data, WATCHLIST)

    # 取當日收盤價
    closes = data.get("Close", pd.DataFrame())

    # 合併結果
    rows = []
    for ticker in WATCHLIST:
        if ticker not in rs_results or ticker not in contraction_results:
            continue

        rs = rs_results[ticker]
        con = contraction_results[ticker]

        price = round(float(closes[ticker].dropna().iloc[-1]), 2) if ticker in closes.columns else 0
        vs_200ma = ma_results.get(ticker, None)

        # Combined Score（RS 60% + Contraction 40%）
        combined = rs["rs_score"] * 0.6 + con["contraction_score"] * 0.4

        rows.append({
            "Ticker": ticker,
            "Sector": TICKER_SECTOR.get(ticker, "Other"),
            "RS_Score": rs["rs_score"],
            "rs_trend": rs.get("rs_trend", ""),
            "rs_1w": rs.get("rs_1w"),
            "rs_4w": rs.get("rs_4w"),
            "rs_13w": rs.get("rs_13w"),
            "Contraction_Score": con["contraction_score"],
            "vcp_pullback_count": con.get("vcp_pullback_count"),
            "last_pullback_pct": con.get("last_pullback_pct"),
            "dist_from_high_pct": con.get("dist_from_high_pct"),
            "Combined_Score": round(combined, 1),
            "Price": price,
            "Return_63d": rs["return_63d"],
            "vs_SPY_63d": rs["vs_spy_63d"],
            "vs_200MA_pct": vs_200ma,
            "ATR_Contraction_pct": con["atr_contraction"],
            "Price_Range_10d_pct": con.get("price_range_pct"),
            "Volume_Ratio_10d_60d": con.get("volume_ratio"),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # 按 Combined Score 排序
    df = df.sort_values("Combined_Score", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    # 計算排名變化
    print("  計算排名變化...")
    df = calc_rank_change(df, today)

    print(f"  ✓ 完成：{len(df)} 支有效標的")
    return df


# ── 美股類股 RS 排名 ──────────────────────────────────────────
US_SECTORS = {
    "VTV":  "價值因子",
    "VUG":  "成長因子",
    "MTUM": "動能因子",
    "IWM":  "小型股",
    "RSP":  "等權重",
    "XLE":  "能源",
    "XLF":  "金融",
    "XLK":  "科技",
    "XLV":  "醫療",
    "XLI":  "工業",
    "XLY":  "非必需消費",
    "XLP":  "必需消費",
    "XLU":  "公用事業",
    "XLB":  "材料",
    "XLRE": "房地產",
    "XLC":  "通訊",
    "XBI":  "生技",
}
US_SECTOR_BENCHMARK = "SPY"

# ── 全球指數 RS 排名 ──────────────────────────────────────────
GLOBAL_INDICES = {
    "^GSPC":      "美國",
    "^GSPTSE":    "加拿大",
    "^FTSE":      "英國",
    "^GDAXI":     "德國",
    "^FCHI":      "法國",
    "^SSMI":      "瑞士",
    "^IBEX":      "西班牙",
    "FTSEMIB.MI": "義大利",
    "^BVSP":      "巴西",
    "^MXX":       "墨西哥",
    "^HSI":       "香港",
    "000001.SS":  "中國",
    "^TWII":      "台灣",
    "^KS11":      "韓國",
    "^N225":      "日本",
    "^STI":       "新加坡",
    "^KLSE":      "馬來西亞",
    "^BSESN":     "印度",
    "^AXJO":      "澳洲",
    "^NZ50":      "紐西蘭",
    "^TA125.TA":  "以色列",
    "UAE":        "杜拜",
    "^JKSE":      "印尼",
    "PSEI.PS":    "菲律賓",
    "^SET.BK":    "泰國",
    "VNM":        "越南",
    "EPOL":       "波蘭",
}
GLOBAL_BENCHMARK = "VT"


def calc_rs_ranking(tickers_dict: dict, benchmark_ticker: str, period: str = "300d") -> list[dict]:
    """
    計算一組 ticker 相對於 benchmark 的 RS Score 並排名
    tickers_dict: {ticker: 顯示名稱}
    回傳：按 RS Score 排序的 list
    """
    all_tickers = list(tickers_dict.keys()) + [benchmark_ticker]

    try:
        data = yf.download(
            all_tickers, period=period, interval="1d",
            progress=False, auto_adjust=True, threads=True
        )
        closes = data["Close"] if "Close" in data else data
    except Exception as e:
        print(f"  ✗ 數據下載失敗: {e}")
        return []

    if benchmark_ticker not in closes.columns:
        return []

    bm = closes[benchmark_ticker].dropna()
    bm_ret = {}
    for days, key in [(5, "1w"), (21, "4w"), (63, "13w")]:
        if len(bm) >= days:
            bm_ret[key] = (bm.iloc[-1] - bm.iloc[-days]) / bm.iloc[-days] * 100

    if "13w" not in bm_ret:
        return []

    # 計算每個 ticker 的漲跌幅
    all_returns = {"1w": {}, "4w": {}, "13w": {}}
    for ticker in tickers_dict.keys():
        if ticker not in closes.columns:
            continue
        c = closes[ticker].dropna()
        for days, key in [(5, "1w"), (21, "4w"), (63, "13w")]:
            if len(c) >= days:
                all_returns[key][ticker] = (c.iloc[-1] - c.iloc[-days]) / c.iloc[-days] * 100

    # 百分位排名
    def pct_rank(val, all_vals):
        vals = list(all_vals.values())
        return round(sum(1 for v in vals if v <= val) / len(vals) * 100, 1) if vals else 50

    results = []
    for ticker, name in tickers_dict.items():
        if ticker not in all_returns.get("13w", {}):
            continue

        rs_1w = pct_rank(all_returns["1w"].get(ticker, 0), all_returns["1w"]) if all_returns["1w"] else 50
        rs_4w = pct_rank(all_returns["4w"].get(ticker, 0), all_returns["4w"]) if all_returns["4w"] else 50
        rs_13w = pct_rank(all_returns["13w"][ticker], all_returns["13w"])

        persistence = rs_1w * 0.2 + rs_4w * 0.3 + rs_13w * 0.5

        if rs_1w > rs_4w > rs_13w:
            trend = "加速上升"; bonus = 5
        elif rs_1w >= rs_4w >= rs_13w:
            trend = "穩定維持"; bonus = 2
        elif rs_1w < rs_4w < rs_13w:
            trend = "開始衰退"; bonus = -5
        else:
            trend = "震盪"; bonus = 0

        final_rs = min(100, persistence + bonus)

        c = closes[ticker].dropna()
        price = round(float(c.iloc[-1]), 2) if len(c) > 0 else 0
        ret_13w = round(float(all_returns["13w"][ticker]), 2)
        vs_bm = round(ret_13w - float(bm_ret["13w"]), 2)

        results.append({
            "ticker": ticker,
            "name": name,
            "rs_score": round(final_rs, 1),
            "rs_1w": rs_1w,
            "rs_4w": rs_4w,
            "rs_13w": rs_13w,
            "rs_trend": trend,
            "return_13w": ret_13w,
            "vs_benchmark": vs_bm,
            "price": price,
        })

    results.sort(key=lambda x: x["rs_score"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def run_sector_screener() -> list[dict]:
    print("  [Sector] 計算美股類股 RS 排名...")
    return calc_rs_ranking(US_SECTORS, US_SECTOR_BENCHMARK)


def run_global_screener() -> list[dict]:
    print("  [Global] 計算全球指數 RS 排名...")
    return calc_rs_ranking(GLOBAL_INDICES, GLOBAL_BENCHMARK)


if __name__ == "__main__":
    df = run_screener()
    if not df.empty:
        print("\nTop 10:")
        print(df.head(10).to_string(index=False))
