"""
weekly_main.py
--------------
每週日深度週報主程式。

執行流程：
  1. 依序處理十個主題
  2. 每個主題：fetch → process → build HTML
  3. 存到 briefing/weekly_output/
  4. 寄送摘要 Email
  5. 發布到 financial-analysis-bot repo
"""

import os
import sys
import json
import subprocess
import shutil
import tempfile
from datetime import datetime, timedelta
import pytz
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from weekly_fetcher import (
    fetch_weekly_news, WEEKLY_THEMES,
    fetch_options_data, fetch_credit_data, fetch_nfci_data,
)
from weekly_processor import process_weekly_theme
from weekly_template import build_weekly_html, build_weekly_index
from news_fetcher import fetch_weekly_market_data


THEME_ORDER = [
    "central_bank", "liquidity", "credit", "options",
    "ai_industry", "semiconductor", "earnings",
    "macro", "commodities", "black_swan",
]

THEME_LABEL = {
    "central_bank": "🏦 央行政策追蹤",
    "liquidity": "💧 流動性週報",
    "credit": "💳 信貸市場週報",
    "options": "📊 選擇權市場情緒",
    "ai_industry": "🤖 AI 產業發展",
    "semiconductor": "🔬 半導體供應鏈",
    "earnings": "📈 財報季追蹤",
    "macro": "🌍 全球景氣狀況",
    "commodities": "🛢️ 能源與大宗商品",
    "black_swan": "🦢 黑天鵝與灰犀牛",
}


def _get_date_info() -> tuple[str, str, str]:
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    date_short = now.strftime("%m/%d")
    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    return today, date_short, start


def _fetch_extra_context(theme_key: str) -> str:
    """Fetch yfinance/FRED data for themes that need it."""
    if theme_key == "options":
        data = fetch_options_data()
        return (
            f"\n即時市場數據（以此為準）：\n"
            f"VIX Spot: {data['vix_spot']}\n"
            f"VIX 3M: {data['vix_3m']}\n"
            f"Term Structure: {data['term_structure']}\n"
            f"VVIX: {data['vvix']}\n"
            f"QQQ Put/Call Ratio: {data['qqq_pc_ratio']}\n"
        )
    elif theme_key == "credit":
        data = fetch_credit_data()
        return (
            f"\n即時市場數據（以此為準）：\n"
            f"HYG 週報酬: {data['hyg_weekly_return']}\n"
            f"LQD 週報酬: {data['lqd_weekly_return']}\n"
            f"HYG/LQD 比值週變化: {data['hyg_lqd_ratio_change']}\n"
        )
    elif theme_key == "liquidity":
        data = fetch_nfci_data()
        return (
            f"\n即時 NFCI 數據（以此為準）：\n"
            f"NFCI 最新值: {data['latest_value']}（日期: {data['latest_date']}）\n"
            f"上週值: {data['prev_week']}\n"
            f"週變化: {data['week_change']}\n"
            f"4 週趨勢: {data['4week_trend']}\n"
        )
    return ""


def send_weekly_email(summaries: dict[str, str], today: str, date_short: str) -> None:
    """Send one email with previews and links for all reports."""
    base_url = "https://research.investmquest.com/weekly"

    cards = ""
    for key in THEME_ORDER:
        label = THEME_LABEL[key]
        summary = summaries.get(key, "")
        if not summary:
            continue
        link = f"{base_url}/{today}-{key}.html"
        cards += f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:8px;
            padding:18px 22px;margin-bottom:14px;">
  <div style="font-size:17px;font-weight:600;color:#1B3A5C;margin-bottom:8px;">
    {label}</div>
  <div style="font-size:15px;color:#555;line-height:1.7;margin-bottom:12px;">
    {summary}</div>
  <a href="{link}" style="display:inline-block;background:#1B3A5C;color:#fff;
     font-size:14px;font-weight:500;padding:8px 20px;border-radius:5px;
     text-decoration:none;">閱讀完整報告 →</a>
</div>'''

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px 20px;color:#222;">
<div style="border-bottom:2px solid #1B3A5C;padding-bottom:12px;margin-bottom:20px;">
  <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#888;
              margin-bottom:4px;">WEEKLY DEEP REPORT</div>
  <div style="font-family:Georgia,serif;font-size:24px;font-weight:700;color:#1B3A5C;">
    每週深度週報</div>
</div>
{cards}
<div style="font-size:12px;color:#aaa;border-top:1px solid #e8e8e8;padding-top:12px;margin-top:8px;">
  AI 輔助分析 · 僅供參考
</div>
</body></html>"""

    raw = os.environ["TO_EMAIL"]
    recipients = [addr.strip() for addr in raw.split(",") if addr.strip()]
    subject = f"📊 每週深度週報 {date_short}"

    payload = {
        "from": "Morning Briefing <onboarding@resend.dev>",
        "to": [recipients[0]],
        "subject": subject,
        "html": html,
    }
    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )
    if response.status_code in (200, 201):
        print(f"  → Weekly email sent: {subject}")
    else:
        print(f"  → Email error: {response.status_code} — {response.text}")
        raise Exception(f"Resend API error: {response.status_code}")


def publish_weekly_to_github(
    output_dir: str,
    today: str,
    start: str,
    theme_data: dict[str, dict],
    market_data: dict,
) -> None:
    """Push weekly HTML files to financial-analysis-bot repo."""
    gh_pat = os.environ.get("GH_PAT", "")
    if not gh_pat:
        print("  ⚠ GH_PAT not set, skipping publish")
        return

    repo_url = f"https://x-access-token:{gh_pat}@github.com/keigoks-ivan/financial-analysis-bot.git"
    tmp_dir = tempfile.mkdtemp()

    try:
        print("  → Cloning financial-analysis-bot...")
        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, tmp_dir],
            check=True, capture_output=True, text=True,
        )

        weekly_dir = os.path.join(tmp_dir, "docs", "weekly")
        os.makedirs(weekly_dir, exist_ok=True)

        # Copy HTML files
        for key in THEME_ORDER:
            src = os.path.join(output_dir, f"{today}-{key}.html")
            if os.path.exists(src):
                shutil.copy2(src, weekly_dir)
                print(f"  → Copied {today}-{key}.html")

        # Build index.html with market data + theme cards
        index_html = build_weekly_index(
            theme_data=theme_data,
            market_data=market_data,
            today=today,
            start=start,
            end=today,
            weekly_dir=weekly_dir,
        )
        with open(os.path.join(weekly_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"  → Built index.html with market data")

        # Commit and push
        subprocess.run(
            ["git", "config", "user.name", "github-actions[bot]"],
            cwd=tmp_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
            cwd=tmp_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "add", "docs/weekly/"],
            cwd=tmp_dir, check=True, capture_output=True,
        )

        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=tmp_dir, capture_output=True,
        )
        if result.returncode == 0:
            print("  → No changes to commit")
            return

        subprocess.run(
            ["git", "commit", "-m", f"Weekly reports {today}"],
            cwd=tmp_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"],
            cwd=tmp_dir, check=True, capture_output=True,
        )
        print(f"  → Published to financial-analysis-bot/docs/weekly/")
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Git error: {e.stderr}")
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    print("=" * 50)
    print("Weekly Deep Report — starting")
    print("=" * 50)

    today, date_short, start = _get_date_info()
    output_dir = os.path.join(os.path.dirname(__file__), "weekly_output")
    os.makedirs(output_dir, exist_ok=True)

    total = len(THEME_ORDER)
    summaries = {}
    theme_data = {}

    for i, theme_key in enumerate(THEME_ORDER, 1):
        theme = WEEKLY_THEMES[theme_key]
        theme_name = theme["name"]
        print(f"\n[{i}/{total}] Processing: {theme_name}")

        # Fetch extra data for themes that need it
        extra_context = ""
        if theme_key in ("options", "credit", "liquidity"):
            print(f"  Fetching market data for {theme_key}...")
            extra_context = _fetch_extra_context(theme_key)

        # Fetch news
        print(f"  Fetching news...")
        raw_news = fetch_weekly_news(theme_key)
        print(f"  {len(raw_news)} queries completed")

        # Process
        print(f"  Processing with Claude...")
        data = process_weekly_theme(theme_key, theme_name, raw_news, extra_context)
        summaries[theme_key] = data.get("week_summary", "")
        theme_data[theme_key] = data

        # Save JSON
        json_path = os.path.join(output_dir, f"{today}-{theme_key}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Build HTML
        html = build_weekly_html(data, theme_key)
        html_path = os.path.join(output_dir, f"{today}-{theme_key}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  → Saved: {html_path} ({len(html):,} chars)")

    # Fetch weekly market data for index page
    print(f"\n[Market] Fetching weekly market data...")
    weekly_market = fetch_weekly_market_data()

    # Send email
    print(f"\n[Email] Sending weekly summary...")
    send_weekly_email(summaries, today, date_short)

    # Publish to GitHub
    print(f"\n[Publish] Publishing to financial-analysis-bot...")
    publish_weekly_to_github(output_dir, today, start, theme_data, weekly_market)

    print("\n✓ Weekly report done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
