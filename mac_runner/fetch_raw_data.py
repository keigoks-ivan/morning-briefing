"""
mac_runner/fetch_raw_data.py
----------------------------
Phase 1：抓所有免費即時數據（yfinance + RSS + FRED + CNN Fear&Greed），
輸出 /tmp/raw_data.json 供 Claude Code 任務與 orchestrate.py 使用。

用法：
    python fetch_raw_data.py --mode daily     # Mon-Sat TW（預設）
    python fetch_raw_data.py --mode weekly    # Sun TW

不做 LLM 呼叫、不花 API 費用。可以在任何時間安全重跑。
"""

import os
import sys
import json
import argparse
from datetime import datetime
import pytz

# Mac 端執行時，需要能 import briefing/ 和 screener/ 的模組
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "briefing"))

try:
    from dotenv import load_dotenv
    # 優先吃本機設定
    load_dotenv(os.path.join(REPO_ROOT, "mac_runner", ".env.local"))
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass


def fetch_daily(now_tw, now_et) -> dict:
    from news_fetcher import fetch_market_data, fetch_today_earnings, fetch_moneydj_news

    print("  → fetch_market_data (yfinance + FRED + CNN)...")
    market_data = fetch_market_data()

    print("  → fetch_today_earnings (yfinance)...")
    try:
        today_earnings = fetch_today_earnings()
    except Exception as e:
        print(f"    ⚠ today_earnings failed: {e} (non-fatal)")
        today_earnings = []

    print("  → fetch_moneydj_news (RSS)...")
    try:
        moneydj_news = fetch_moneydj_news()
    except Exception as e:
        print(f"    ⚠ moneydj_news failed: {e} (non-fatal)")
        moneydj_news = []

    return {
        "mode": "daily",
        "generated_at": now_tw.isoformat(),
        "date_tw": now_tw.strftime("%Y-%m-%d"),
        "date_us_et": now_et.strftime("%Y-%m-%d"),
        "weekday_tw": now_tw.strftime("%A"),
        "weekday_num_tw": now_tw.weekday(),
        "market_data": market_data,
        "today_earnings": today_earnings,
        "moneydj_news": moneydj_news,
    }


def fetch_weekly(now_tw, now_et) -> dict:
    from news_fetcher import fetch_weekly_market_data, fetch_moneydj_news

    print("  → fetch_weekly_market_data (yfinance 週線 + FRED + CNN)...")
    market_data = fetch_weekly_market_data()

    print("  → fetch_moneydj_news (RSS，近 7 日累積)...")
    try:
        moneydj_news = fetch_moneydj_news()
    except Exception as e:
        print(f"    ⚠ moneydj_news failed: {e} (non-fatal)")
        moneydj_news = []

    return {
        "mode": "weekly",
        "generated_at": now_tw.isoformat(),
        "date_tw": now_tw.strftime("%Y-%m-%d"),
        "date_us_et": now_et.strftime("%Y-%m-%d"),
        "weekday_tw": now_tw.strftime("%A"),
        "weekday_num_tw": now_tw.weekday(),
        "market_data": market_data,
        "moneydj_news": moneydj_news,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "auto"], default="auto",
                        help="auto = 依 TW 星期自動判斷（週日 → weekly，其他 → daily）")
    parser.add_argument("--out", default="/tmp/raw_data.json")
    args = parser.parse_args()

    tz_tw = pytz.timezone("Asia/Taipei")
    tz_et = pytz.timezone("US/Eastern")
    now_tw = datetime.now(tz_tw)
    now_et = datetime.now(tz_et)

    # auto 模式依 TW 星期判斷
    mode = args.mode
    if mode == "auto":
        mode = "weekly" if now_tw.weekday() == 6 else "daily"

    print(f"[Phase 1] mode={mode} | TW {now_tw.strftime('%Y-%m-%d %H:%M')} | "
          f"US ET {now_et.strftime('%Y-%m-%d %H:%M')}")

    if mode == "daily":
        raw = fetch_daily(now_tw, now_et)
    else:
        raw = fetch_weekly(now_tw, now_et)

    # 儲存
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2, default=str)
    size = os.path.getsize(args.out)
    print(f"  ✓ Saved {size:,} bytes to {args.out}")

    # Summary
    md = raw.get("market_data", {})
    print(f"  → market_data: indices={len(md.get('indices',[]))} "
          f"factors={len(md.get('factors',[]))} "
          f"sentiment={len(md.get('sentiment',[]))} "
          f"commodities={len((md.get('commodities') or {}).get('fixed',[]) if isinstance(md.get('commodities'), dict) else md.get('commodities') or [])} "
          f"bonds={len(md.get('bonds',[]))} "
          f"fx={len(md.get('fx',[]))} "
          f"credit={len(md.get('credit',[]))} "
          f"liquidity={len(md.get('liquidity',[]))}")
    if mode == "daily":
        print(f"  → today_earnings: {len(raw.get('today_earnings',[]))} companies")
    print(f"  → moneydj_news: {len(raw.get('moneydj_news',[]))} items")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
