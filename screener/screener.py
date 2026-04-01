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
    """計算 RS Score：個股63日漲跌幅 vs SPY 的百分位排名"""
    closes = data.get("Close", pd.DataFrame())
    if closes.empty:
        return {}

    results = {}

    # 計算 SPY 63日漲跌幅
    if BENCHMARK not in closes.columns:
        return {}

    spy_closes = closes[BENCHMARK].dropna()
    if len(spy_closes) < 63:
        return {}

    spy_return_63d = (spy_closes.iloc[-1] - spy_closes.iloc[-63]) / spy_closes.iloc[-63] * 100

    # 計算每支股票的63日漲跌幅
    returns_63d = {}
    for ticker in tickers:
        if ticker not in closes.columns:
            continue
        ticker_closes = closes[ticker].dropna()
        if len(ticker_closes) < 63:
            continue
        ret = (ticker_closes.iloc[-1] - ticker_closes.iloc[-63]) / ticker_closes.iloc[-63] * 100
        returns_63d[ticker] = ret

    if not returns_63d:
        return {}

    # 計算百分位排名
    all_returns = list(returns_63d.values())
    for ticker, ret in returns_63d.items():
        percentile = sum(1 for r in all_returns if r <= ret) / len(all_returns) * 100
        results[ticker] = {
            "return_63d": round(ret, 2),
            "rs_score": round(percentile, 1),
            "vs_spy_63d": round(ret - spy_return_63d, 2),
        }

    return results

def calc_contraction_score(data: dict, tickers: list[str]) -> dict:
    """計算 Contraction Score：ATR收縮 + 價格區間緊縮 + 成交量萎縮"""
    closes = data.get("Close", pd.DataFrame())
    highs  = data.get("High",  pd.DataFrame())
    lows   = data.get("Low",   pd.DataFrame())
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

            if len(c) < 30:
                continue

            # 1. ATR 收縮：近10日 ATR vs 近60日 ATR
            tr = pd.concat([
                h - l,
                (h - c.shift(1)).abs(),
                (l - c.shift(1)).abs(),
            ], axis=1).max(axis=1)

            atr_10 = tr.iloc[-10:].mean()
            atr_60 = tr.iloc[-60:].mean()

            if atr_60 == 0:
                continue

            atr_ratio = atr_10 / atr_60  # 越小越收縮
            atr_score = max(0, min(100, (1 - atr_ratio) * 100 + 50))

            # 2. 價格區間緊縮：近10日高低點範圍 vs 近30日
            range_10 = (h.iloc[-10:].max() - l.iloc[-10:].min()) / c.iloc[-1] * 100
            range_30 = (h.iloc[-30:].max() - l.iloc[-30:].min()) / c.iloc[-1] * 100

            if range_30 == 0:
                continue

            range_ratio = range_10 / range_30  # 越小越收縮
            range_score = max(0, min(100, (1 - range_ratio) * 100 + 50))

            # 3. 成交量萎縮：近10日均量 vs 近60日均量
            vol_10 = v.iloc[-10:].mean()
            vol_60 = v.iloc[-60:].mean()

            if vol_60 == 0:
                continue

            vol_ratio = vol_10 / vol_60  # 越小越萎縮
            vol_score = max(0, min(100, (1 - vol_ratio) * 100 + 50))

            # 綜合 Contraction Score（ATR 50% + 區間 30% + 成交量 20%）
            contraction_score = atr_score * 0.5 + range_score * 0.3 + vol_score * 0.2

            results[ticker] = {
                "contraction_score": round(contraction_score, 1),
                "atr_contraction": round((1 - atr_ratio) * 100, 1),
                "price_range_pct": round(range_10, 2),
                "volume_ratio": round(vol_10 / vol_60, 2),
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
    if not data:
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
            "Contraction_Score": con["contraction_score"],
            "Combined_Score": round(combined, 1),
            "Price": price,
            "Return_63d": rs["return_63d"],
            "vs_SPY_63d": rs["vs_spy_63d"],
            "vs_200MA_pct": vs_200ma,
            "ATR_Contraction_pct": con["atr_contraction"],
            "Price_Range_10d_pct": con["price_range_pct"],
            "Volume_Ratio_10d_60d": con["volume_ratio"],
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
