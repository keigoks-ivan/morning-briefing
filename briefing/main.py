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

# 本機測試時載入 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 生產環境不需要 dotenv

from news_fetcher import fetch_financial_news, fetch_market_data
from ai_processor import process_news
from html_template import build_html
from email_sender import send_email


def main() -> None:
    print("=" * 50)
    print("Morning Briefing — starting")
    print("=" * 50)

    # 1. 搜尋新聞 + 即時行情
    print("\n[1/4] Fetching news (Tavily) + market data...")
    market_data = fetch_market_data()
    raw_news = fetch_financial_news()
    print(f"      {len(raw_news)} queries completed")

    # 2. AI 處理
    print("\n[2/4] Processing with Claude...")
    data = process_news(raw_news, market_data)

    # 3. 生成 HTML
    print("\n[3/4] Building HTML...")
    html = build_html(data)
    print(f"      HTML size: {len(html):,} chars")

    # 4. 發送 Email
    print("\n[4/4] Sending email...")
    send_email(html)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
