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

from news_fetcher import fetch_financial_news, fetch_market_data, fetch_today_earnings, fetch_moneydj_news, fetch_deep_dive_news, fetch_move_index
from ai_processor import process_news
from html_template import build_html, build_all_pages
from email_sender import send_email


def main() -> None:
    print("=" * 50)
    print("Morning Briefing — starting")
    print("=" * 50)

    # 1. 搜尋新聞 + 即時行情 + 今日財報
    print("\n[1/4] Fetching news + market data + today earnings...")
    market_data = fetch_market_data()
    move_index_raw = fetch_move_index()
    today_earnings = fetch_today_earnings()
    raw_news = fetch_financial_news()
    moneydj_news = fetch_moneydj_news()
    deep_dive_news = fetch_deep_dive_news()
    dd_count = len(deep_dive_news.get("fixed", [])) + len(deep_dive_news.get("dynamic", [])) if isinstance(deep_dive_news, dict) else len(deep_dive_news)
    print(f"      {len(raw_news)} queries completed, {len(today_earnings)} earnings confirmed, {len(moneydj_news)} MoneyDJ news, {dd_count} deep dive")

    # 1.5 執行 Screener（週末跳過）
    tz = pytz.timezone("Asia/Taipei")
    weekday = datetime.now(tz).weekday()  # 0=週一 6=週日

    screener_result = {}
    if weekday < 5:
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
        print("\n[Screener] 週末跳過")

    # 2. AI 處理
    print("\n[2/4] Processing with Claude...")
    data = process_news(raw_news, market_data, today_earnings, moneydj_news, deep_dive_news, move_index_raw=move_index_raw)

    # 3. 生成多頁 HTML
    print("\n[3/4] Building HTML pages...")
    pages = build_all_pages(data, screener_result=screener_result)
    total_size = sum(len(h) for h in pages.values())
    print(f"      {len(pages)} pages, total {total_size:,} chars")

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
        f.write(pages["index.html"])
    print(f"      Saved index to {output_path}")

    # 4. 發送 Email（只寄首頁 + 導航連結）
    print("\n[4/4] Sending email...")
    email_html = pages["index.html"]
    nav_links = """
<div style="margin:20px 0;padding:16px;background:#F8F9FC;border-radius:8px;text-align:center;">
  <div style="font-size:11px;color:#888;margin-bottom:8px;">完整晨報請到網站查看</div>
  <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
    <a href="https://research.investmquest.com/briefing/news.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">要聞・深度</a>
    <a href="https://research.investmquest.com/briefing/geo.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">地緣・國際</a>
    <a href="https://research.investmquest.com/briefing/tech.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">科技・AI</a>
    <a href="https://research.investmquest.com/briefing/trends.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">新創・趨勢</a>
    <a href="https://research.investmquest.com/briefing/misc.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">財報・冷知識</a>
    <a href="https://research.investmquest.com/briefing/screener.html" style="font-size:12px;color:#1B3A5C;text-decoration:none;padding:4px 10px;border:0.5px solid #1B3A5C;border-radius:4px;">Screener</a>
  </div>
</div>
"""
    # 在 </body> 前插入導航連結
    email_with_nav = email_html.replace("</body>", nav_links + "</body>")
    send_email(email_with_nav, screener_result=screener_result)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
