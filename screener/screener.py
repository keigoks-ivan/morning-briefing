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

if __name__ == "__main__":
    df = run_screener()
    if not df.empty:
        print("\nTop 10:")
        print(df.head(10).to_string(index=False))
