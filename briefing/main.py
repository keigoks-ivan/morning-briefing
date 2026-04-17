"""
main.py
-------
每日財經晨報主程式。
由 GitHub Actions 每日 UTC 22:00（台灣 06:00）觸發執行。

執行流程：
  1. Tavily   → 搜尋財經 / 科技 / 新創新聞（~8 個查詢）
  2. Claude   → 整理成結構化 JSON（Sonnet 4）
  3. Template → 生成 HTML Email
  4. SendGrid → 寄出郵件
"""

import os
import sys
import json
import subprocess
from datetime import datetime
import pytz

# 本機測試時載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 生產環境不需要 dotenv

from news_fetcher import fetch_financial_news, fetch_market_data, fetch_today_earnings, fetch_moneydj_news, fetch_deep_dive_news, fetch_move_index, fetch_earnings_deep_dive
from ai_processor import process_news
from html_template import build_html, build_all_pages
from email_sender import send_email
from trading_system_of_day import get_today_system
from startup_framework_of_day import get_today_framework


# ── Mac-generated data support ──────────────────────────────

FRESHNESS_THRESHOLD_MIN = 20  # Mac 05:55 → GHA 06:15，最多 20 分鐘舊


def try_load_mac_data(mode: str = "daily") -> dict | None:
    """
    嘗試載入 Mac mini 產生的 full_data.json。
    若檔案不存在、太舊、或 schema 無效 → 回 None 觸發 fallback。
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filename = "full_data.json" if mode == "daily" else "weekly_full_data.json"
    path = os.path.join(repo_root, "docs", "briefing", filename)

    if not os.path.exists(path):
        print(f"  ⚠ Mac data missing ({path}) → fallback to API pipeline")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠ Mac data parse error: {e} → fallback")
        return None

    # freshness check
    ts_str = data.get("generated_at", "")
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = pytz.timezone("Asia/Taipei").localize(ts)
        age_min = (datetime.now(ts.tzinfo) - ts).total_seconds() / 60
    except Exception as e:
        print(f"  ⚠ Mac data timestamp parse error ({ts_str!r}): {e} → fallback")
        return None

    if age_min > FRESHNESS_THRESHOLD_MIN:
        print(f"  ⚠ Mac data {age_min:.0f}min old (>{FRESHNESS_THRESHOLD_MIN}min) → fallback")
        return None
    if age_min < -5:
        print(f"  ⚠ Mac data has future timestamp ({age_min:.0f}min) → fallback")
        return None

    # schema check — 重用 mac_runner/validate_schema.py
    sys.path.insert(0, os.path.join(repo_root, "mac_runner"))
    try:
        from validate_schema import validate as _validate_schema
        ok, errors = _validate_schema(data, mode=mode)
    except ImportError:
        print("  ⚠ validate_schema not importable — accepting data as-is")
        ok, errors = True, []

    if not ok:
        print(f"  ⚠ Mac data schema invalid ({len(errors)} errors, first 3):")
        for e in errors[:3]:
            print(f"       - {e}")
        print(f"       → fallback")
        return None

    print(f"  ✓ Using Mac-generated data ({age_min:.0f}min old, schema valid)")
    return data


def main() -> None:
    print("=" * 50)
    print("Morning Briefing — starting")
    print("=" * 50)

    # 0. 嘗試讀 Mac mini 預跑好的資料
    print("\n[0/4] Check Mac-generated data...")
    data = try_load_mac_data(mode="daily")
    used_mac_data = data is not None

    today_earnings = []  # 給後面 email / misc 用（Mac path 會從 data["earnings_preview"] 還原）

    if used_mac_data:
        print("      Skipping API calls (news, deep_dive, earnings_deep, ai_processor).")
        # 從 Mac data 還原 today_earnings 供其他邏輯（如 email）使用
        for e in data.get("earnings_preview", []):
            today_earnings.append({"ticker": e.get("ticker", ""), "time": e.get("report_time", "after-close")})
    else:
        # === Fallback: 原 Perplexity + API pipeline ===
        print("\n[1/4] Fetching news + market data + today earnings...")
        market_data = fetch_market_data()
        move_index_raw = fetch_move_index()
        today_earnings = fetch_today_earnings()
        raw_news = fetch_financial_news()
        moneydj_news = fetch_moneydj_news()
        deep_dive_news = fetch_deep_dive_news()
        earnings_deep_dive = fetch_earnings_deep_dive()
        dd_count = len(deep_dive_news.get("fixed", [])) + len(deep_dive_news.get("dynamic", [])) if isinstance(deep_dive_news, dict) else len(deep_dive_news)
        print(f"      {len(raw_news)} queries completed, {len(today_earnings)} earnings confirmed, {len(moneydj_news)} MoneyDJ news, {dd_count} deep dive, {len(earnings_deep_dive)} earnings deep")

    # 1.5 執行 Screener（台灣週二~週六才跑，對應美股前一交易日）
    # 週日(6)、週一(0)跳過：週六、週日美股休市，無新數據
    tz = pytz.timezone("Asia/Taipei")
    weekday = datetime.now(tz).weekday()  # 0=週一 6=週日

    screener_result = {}
    if weekday in (1, 2, 3, 4, 5):  # 台灣週二~週六
        try:
            print("\n[Screener] 執行 RS+Contraction Screener...")
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            result = subprocess.run(
                [sys.executable, os.path.join(repo_root, "screener", "main.py")],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                with open("/tmp/screener_result.json") as f:
                    screener_result = json.load(f)
                print(f"      Screener: {screener_result.get('total_screened',0)} 支，Top 30 完成")
            else:
                print(f"      Screener 失敗: {result.stderr[:200]}")
        except Exception as e:
            print(f"      Screener 例外: {e}")
    else:
        print("\n[Screener] 今日非交易日（台灣週日或週一），跳過")

    # 1.6 今日交易系統
    print("\n[交易系統] 選出今日系統...")
    today_system = get_today_system()
    if today_system:
        print(f"  今日系統：{today_system.get('name', '')} ({today_system.get('id', '')})")
    else:
        today_system = {}
        print("  ✗ 今日交易系統讀取失敗")

    # 1.7 今日創業框架
    print("\n[創業框架] 選出今日框架...")
    today_framework = get_today_framework()
    if today_framework:
        print(f"  今日框架：{today_framework.get('name', '')} ({today_framework.get('id', '')})")
    else:
        today_framework = {}
        print("  ✗ 今日創業框架讀取失敗")

    # 2. AI 處理（只在 fallback 路徑跑；用 Mac data 則 data 已在 step 0 填好）
    if not used_mac_data:
        print("\n[2/4] Processing with Claude/Gemini...")
        data = process_news(raw_news, market_data, today_earnings, moneydj_news, deep_dive_news, move_index_raw=move_index_raw, earnings_deep_dive=earnings_deep_dive)

    # 注入日期供多頁 builder 使用
    tz_now = datetime.now(tz)
    data["date"] = tz_now.strftime("%Y年%m月%d日 %H:%M TST")

    # 標示資料來源（在 footer 或 debug log 看得到）
    data["_source"] = "mac-claude-code" if used_mac_data else "github-actions-api"
    print(f"\n      Data source: {data['_source']}")

    # 3. 生成多頁 HTML + Email 用單頁
    print("\n[3/4] Building HTML pages...")
    pages = build_all_pages(data, screener_result=screener_result, today_system=today_system, today_framework=today_framework)
    total_size = sum(len(h) for h in pages.values())
    print(f"      {len(pages)} pages, total {total_size:,} chars")

    email_html = build_html(data, screener_result=screener_result)
    print(f"      Email HTML: {len(email_html):,} chars")

    # 3.5 存檔所有頁面（供 GitHub Pages 發布）
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(repo_root, "docs", "briefing")
    os.makedirs(docs_dir, exist_ok=True)
    for filename, html_content in pages.items():
        page_path = os.path.join(docs_dir, filename)
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(html_content)
    print(f"      Saved {len(pages)} pages to {docs_dir}")

    # 同時保留舊的單檔輸出（向後相容）
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "briefing.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(email_html)
    print(f"      Saved to {output_path}")

    # 4. 發送 Email（完整單頁 + 導航連結）
    print("\n[4/4] Sending email...")
    nav_links = """
<div style="margin:20px 0;padding:16px;background:#F8F9FC;border-radius:8px;text-align:center;">
  <div style="font-size:11px;color:#888;margin-bottom:10px;">完整晨報請到網站查看</div>
  <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
    <a href="https://research.investmquest.com/briefing/news.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">要聞・深度</a>
    <a href="https://research.investmquest.com/briefing/geo.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">地緣・國際</a>
    <a href="https://research.investmquest.com/briefing/tech.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">科技・AI</a>
    <a href="https://research.investmquest.com/briefing/trends.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">新創・趨勢</a>
    <a href="https://research.investmquest.com/briefing/misc.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">財報</a>
    <a href="https://research.investmquest.com/briefing/trading.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">交易系統</a>
    <a href="https://research.investmquest.com/briefing/screener.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:5px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">Screener</a>
  </div>
</div>
"""
    email_with_nav = email_html.replace("</body>", nav_links + "</body>")
    send_email(email_with_nav, screener_result=screener_result)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
