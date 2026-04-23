"""
main.py
-------
每日財經晨報主程式。
由 GitHub Actions 每日 UTC 22:15（台灣 06:15）觸發執行。

執行流程：
  1. Perplexity  → 搜尋財經 / 科技 / 新創新聞（~8 個查詢）
  2. Gemini/Claude → 整理成結構化 JSON
  3. Template    → 生成多頁 HTML
  4. Resend      → 寄出郵件
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


def main() -> None:
    print("=" * 50)
    print("Morning Briefing — starting")
    print("=" * 50)

    # 1. 抓新聞 + 行情 + 財報
    print("\n[1/4] Fetching news + market data + today earnings...")
    market_data = fetch_market_data()
    move_index_raw = fetch_move_index()
    today_earnings = fetch_today_earnings()
    raw_news = fetch_financial_news()
    moneydj_news = fetch_moneydj_news()
    deep_dive_news = fetch_deep_dive_news()
    # 日報財報深度分析暫停 — 已改由 Claude remote routine 獨立跑（trig_01Y14kkNRWHHtWLfVGCFLQs8，
    # 每日 TW 08:00，存 Google Drive「04 美股財報」）。這邊傳空 list 讓下游走 empty stub，
    # HTML 區塊會自動隱藏。要恢復的話打開下一行即可。
    # earnings_deep_dive = fetch_earnings_deep_dive()
    earnings_deep_dive = []
    dd_count = len(deep_dive_news.get("fixed", [])) + len(deep_dive_news.get("dynamic", [])) if isinstance(deep_dive_news, dict) else len(deep_dive_news)
    print(f"      {len(raw_news)} queries completed, {len(today_earnings)} earnings confirmed, {len(moneydj_news)} MoneyDJ news, {dd_count} deep dive, {len(earnings_deep_dive)} earnings deep (paused — handled by Claude remote routine)")

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

    # 2. AI 處理
    print("\n[2/4] Processing with Gemini/Claude...")
    data = process_news(raw_news, market_data, today_earnings, moneydj_news, deep_dive_news, move_index_raw=move_index_raw, earnings_deep_dive=earnings_deep_dive)

    # 注入日期供多頁 builder 使用
    tz_now = datetime.now(tz)
    data["date"] = tz_now.strftime("%Y年%m月%d日 %H:%M TST")

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
