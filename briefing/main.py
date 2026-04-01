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

# 本機測試時載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 生產環境不需要 dotenv

from news_fetcher import fetch_financial_news, fetch_market_data, fetch_today_earnings, fetch_moneydj_news, fetch_deep_dive_news, fetch_move_index
from ai_processor import process_news
from html_template import build_html
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

    # 1.5 執行 Screener
    print("\n[Screener] 執行 RS+Contraction Screener...")
    screener_dir = os.path.join(os.path.dirname(__file__), "..", "screener")
    subprocess.run([sys.executable, os.path.join(screener_dir, "main.py")], check=False)

    screener_result = {}
    try:
        with open("/tmp/screener_result.json") as f:
            screener_result = json.load(f)
        print(f"      Screener: {screener_result.get('total_screened',0)} 支，Top 30 完成")
    except Exception:
        print("      Screener 結果讀取失敗，跳過")

    # 2. AI 處理
    print("\n[2/4] Processing with Claude...")
    data = process_news(raw_news, market_data, today_earnings, moneydj_news, deep_dive_news, move_index_raw=move_index_raw)

    # 3. 生成 HTML
    print("\n[3/4] Building HTML...")
    html = build_html(data, screener_result=screener_result)
    print(f"      HTML size: {len(html):,} chars")

    # 3.5 存檔 HTML（供 GitHub Pages 發布）
    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "briefing.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"      Saved to {output_path}")

    # 4. 發送 Email
    print("\n[4/4] Sending email...")
    send_email(html, screener_result=screener_result)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
