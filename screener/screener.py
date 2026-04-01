import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import warnings
warnings.filterwarnings('ignore')

# ── Watchlist（396支）──────────────────────────────────────────
WATCHLIST = [
    # Technology
    "GOOG","NVDA","GLW","PLTR","TSLA","AVGO","AAPL","VRT","LITE","ANET",
    "MSFT","META","AMD","INTC","ASML","AMAT","LRCX","KLAC","TSM","ARM",
    "QCOM","MU","MRVL","WOLF","ON","MPWR","ENTG","ONTO","ACLS","COHU",
    "TER","FORM","SNOW","CRM","NOW","ADBE","ORCL","IBM","UBER","LYFT",
    "ABNB","DASH","CRWD","PANW","ZS","OKTA","NET","DDOG","MDB","GTLB",
    "ESTC","CFLT","HUBS","TTD","RBLX","U","PINS","SNAP","SHOP","SQ",
    "COIN","HOOD","SOFI","AFRM","UPST","LC","MSTR","SMCI","DELL","HPQ",
    "HPE","CSCO","JNPR","NTAP","PSTG","WDC","STX","NXPI","MCHP","ADI",
    "TXN","LSCC","SLAB","ALGM","DIOD","SITM","AMBA","CRUS","MLNX","SWKS",
    "QRVO","IPHI","IIVI","II","MKSI","CEVA","HIMX","SIMO","ANSS","CDNS",
    "SNPS","MANH","VEEV","WDAY","INTU","ADSK","PTC","NTNX","DSGX","EPAM",
    "GLOB","FLYW","PAYO","FOUR","GPN","FIS","FISV","MA","V","AXP",
    # Consumer
    "AMZN","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","PARA","WBD",
    "NWSA","FOX","LYV","WWE","EDR","IMAX","AMC","CNK","CARG","OPEN",
    "Z","RDFN","EXPI","OPAD","HOUS","MTH","DHI","LEN","PHM","TOL",
    "NVR","TMHC","MHO","SKY","CVCO","WH","HLT","MAR","H","WYNDM",
    "ABNB","BKNG","EXPE","TRIP","PCLN","VRBO","AIRBNB","LMND","ROOT",
    "OSCAR","HUM","CVS","WBA","RAD","DRVN","BROS","CAVA","SHAK","WING",
    "TXRH","DRI","EAT","CMG","MCD","SBUX","YUM","QSR","JACK","DENN",
    "PLAY","RRGB","CAKE","BLMN","RUTH","BJRI","KRUS","YELP","GRUB","DASH",
    "WMT","COST","TGT","LOW","HD","AMZN","ETSY","W","BBWI","VSCO",
    "NKE","LULU","UAA","PVH","RL","HBI","CRI","COLM","VFC","GOOS",
    "TJX","ROST","DLTR","DG","BJ","FIVE","OLLI","PRTY","GRWG","BYND",
    "TTCF","APPH","MAPS","TLRY","CGC","ACB","CRON","SNDL","APHA","HEXO",
    "MO","PM","BTI","LO","SWMAY","VGR","CARR","GE","HON","MMM",
    # Industrials
    "CAT","DE","EMR","ETN","PH","ROK","ITW","DOV","IR","XYL",
    "GNRC","CSGP","JBHT","CHRW","EXPD","XPO","ODFL","SAIA","WERN","KNX",
    "ARCB","MRTN","HTLD","USX","RUSHA","PCAR","CMI","ALSN","TRN","GATX",
    "WAB","TT","LII","MAS","AOS","FBHS","SWK","SNA","KMT","TDG",
    "HEI","TDY","TXT","HXL","SPR","CW","KTOS","RCAT","LMT","RTX",
    "NOC","GD","BA","HII","LHX","DRS","CACI","LDOS","SAIC","BAH",
    "MANT","ICAD","SWIR","VIAV","CASA","CALX","ADTRAN","ADTN","INFN","AAOI",
    "IIVI","COHR","LITE","IPGP","FNSR","OCLR","NPTN","POET","CLFD","ATEN",
    "ATNI","IDT","LUMN","CNSL","SHEN","OTEL","NTELOS","NTLS","UTSTARCOM",
    # Financials
    "JPM","BAC","WFC","C","GS","MS","BLK","SCHW","ICE","CME",
    "SPGI","MCO","BX","KKR","APO","ARES","CG","OWL","HLNE","STEP",
    "AMG","WDR","VCTR","VIRT","MKTX","BGCP","GFI","PIPR","SF","HLI",
    "LPLA","RJF","SEIC","APAM","TROW","IVZ","BEN","WisdomTree","GBTC",
    "IAU","GLD","SLV","PPLT","PALL","USO","UNG","DBO","BNO","OILK",
    # Energy
    "XOM","CVX","COP","EOG","PXD","DVN","FANG","MRO","APA","OXY",
    "SLB","HAL","BKR","PSX","VLO","MPC","DK","PARR","CVRR","CAPL",
    # Healthcare
    "LLY","JNJ","UNH","ABT","TMO","DHR","MDT","SYK","BSX","EW",
    "ISRG","DXCM","PODD","TNDM","GKOS","SHPH","NVCR","TTOO","APEN",
    # Communication
    "GOOGL","META","NFLX","DIS","CMCSA","T","VZ",
    # Materials
    "LIN","APD","ECL","SHW","PPG","NEM","FCX","AA",
]

# 去重
WATCHLIST = list(dict.fromkeys([t for t in WATCHLIST if t and len(t) <= 5]))

BENCHMARK = "SPY"

def fetch_data(tickers: list[str], period: str = "90d") -> dict:
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
    """計算 VCP Score：局部高低點回撤序列 + ATR 收縮"""
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

            if len(c) < 60:
                continue

            # ── 1. 找局部高低點（近90日）────────────────────────
            window = min(len(c), 90)
            c_w = c.iloc[-window:]
            h_w = h.iloc[-window:]
            l_w = l.iloc[-window:]
            v_w = v.iloc[-window:]

            # 用滾動視窗找局部高點（5日視窗）
            local_highs = []
            for i in range(5, len(c_w) - 5):
                if h_w.iloc[i] == h_w.iloc[i-5:i+6].max():
                    local_highs.append((i, float(h_w.iloc[i])))

            local_lows = []
            for i in range(5, len(c_w) - 5):
                if l_w.iloc[i] == l_w.iloc[i-5:i+6].min():
                    local_lows.append((i, float(l_w.iloc[i])))

            # ── 2. 計算回撤序列 ──────────────────────────────────
            pullbacks = []
            for i in range(len(local_highs) - 1):
                high_idx, high_val = local_highs[i]
                # 找這個高點之後的最低點
                subsequent_lows = [(idx, val) for idx, val in local_lows if idx > high_idx]
                if not subsequent_lows:
                    continue
                low_idx, low_val = min(subsequent_lows, key=lambda x: x[1])

                pullback_pct = (high_val - low_val) / high_val * 100
                avg_vol_pullback = float(v_w.iloc[high_idx:low_idx+1].mean()) if low_idx > high_idx else 0

                pullbacks.append({
                    "high_idx": high_idx,
                    "low_idx": low_idx,
                    "high": high_val,
                    "low": low_val,
                    "pullback_pct": pullback_pct,
                    "avg_vol": avg_vol_pullback,
                })

            # ── 3. VCP 評分 ──────────────────────────────────────
            vcp_score = 50  # 基礎分

            # 評分項目1：收縮次數（2-4次最理想）
            n_pullbacks = len(pullbacks)
            if 2 <= n_pullbacks <= 4:
                vcp_score += 15
            elif n_pullbacks == 1:
                vcp_score += 5
            elif n_pullbacks > 4:
                vcp_score += 8

            # 評分項目2：回撤幅度遞減（後一次 < 前一次）
            if len(pullbacks) >= 2:
                decreasing_pullbacks = all(
                    pullbacks[i+1]["pullback_pct"] < pullbacks[i]["pullback_pct"]
                    for i in range(len(pullbacks)-1)
                )
                if decreasing_pullbacks:
                    vcp_score += 15

                # 最後一次回撤幅度
                last_pullback = pullbacks[-1]["pullback_pct"]
                if last_pullback < 5:
                    vcp_score += 15  # 非常緊縮
                elif last_pullback < 8:
                    vcp_score += 10
                elif last_pullback < 12:
                    vcp_score += 5

            # 評分項目3：成交量遞減
            if len(pullbacks) >= 2:
                decreasing_vol = all(
                    pullbacks[i+1]["avg_vol"] < pullbacks[i]["avg_vol"]
                    for i in range(len(pullbacks)-1)
                )
                if decreasing_vol:
                    vcp_score += 10

            # 評分項目4：目前距離前期高點的距離（越近越好）
            dist_from_high = None
            if local_highs:
                recent_high = max(local_highs, key=lambda x: x[0])[1]
                current_price = float(c_w.iloc[-1])
                dist_from_high = (recent_high - current_price) / recent_high * 100

                if dist_from_high < 3:
                    vcp_score += 15  # 接近突破點
                elif dist_from_high < 5:
                    vcp_score += 10
                elif dist_from_high < 10:
                    vcp_score += 5
                else:
                    vcp_score -= 5

            # 評分項目5：ATR 收縮（輔助確認）
            tr = pd.concat([
                h - l,
                (h - c.shift(1)).abs(),
                (l - c.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr_10 = tr.iloc[-10:].mean()
            atr_60 = tr.iloc[-60:].mean()
            atr_ratio = atr_10 / atr_60 if atr_60 > 0 else 1
            if atr_ratio < 0.6:
                vcp_score += 10
            elif atr_ratio < 0.8:
                vcp_score += 5

            vcp_score = max(0, min(100, vcp_score))

            # 收縮次數和最後回撤幅度
            last_pullback_pct = pullbacks[-1]["pullback_pct"] if pullbacks else None
            dist_from_high_pct = dist_from_high

            results[ticker] = {
                "contraction_score": round(vcp_score, 1),
                "vcp_pullback_count": n_pullbacks,
                "last_pullback_pct": round(last_pullback_pct, 1) if last_pullback_pct else None,
                "dist_from_high_pct": round(dist_from_high_pct, 1) if dist_from_high_pct else None,
                "atr_contraction": round((1 - atr_ratio) * 100, 1),
                "price_range_pct": round(
                    (h_w.iloc[-10:].max() - l_w.iloc[-10:].min()) / float(c_w.iloc[-1]) * 100, 2
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

    print(f"  ✓ 完成：{len(df)} 支有效標的")
    return df

if __name__ == "__main__":
    df = run_screener()
    if not df.empty:
        print("\nTop 10:")
        print(df.head(10).to_string(index=False))
