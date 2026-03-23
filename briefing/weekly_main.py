"""
weekly_main.py
--------------
每週日深度週報主程式。

執行流程：
  1. 依序處理四個主題：ai_industry、semiconductor、macro、black_swan
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

from weekly_fetcher import fetch_weekly_news, WEEKLY_THEMES
from weekly_processor import process_weekly_theme
from weekly_template import build_weekly_html


THEME_ORDER = ["ai_industry", "semiconductor", "macro", "black_swan"]

THEME_LABEL = {
    "ai_industry": "🤖 AI 產業發展",
    "semiconductor": "🔬 半導體供應鏈",
    "macro": "🌍 全球景氣狀況",
    "black_swan": "🦢 黑天鵝與灰犀牛",
}


def _get_date_info() -> tuple[str, str, str]:
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    date_short = now.strftime("%m/%d")
    start = (now - timedelta(days=6)).strftime("%Y-%m-%d")
    return today, date_short, start


def send_weekly_email(summaries: dict[str, str], today: str, date_short: str) -> None:
    """Send one email with previews and links for all four reports."""
    base_url = "https://research.investmquest.com/weekly"

    cards = ""
    for key in THEME_ORDER:
        label = THEME_LABEL[key]
        summary = summaries.get(key, "")
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


def publish_weekly_to_github(output_dir: str, today: str) -> None:
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

        # Build index.html
        _build_weekly_index(weekly_dir)

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

        # Check if there are changes
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


def _build_weekly_index(weekly_dir: str) -> None:
    """Build or update the index.html for weekly reports."""
    # Scan existing HTML files (excluding index.html)
    entries: dict[str, list[str]] = {}
    for fname in sorted(os.listdir(weekly_dir), reverse=True):
        if fname == "index.html" or not fname.endswith(".html"):
            continue
        # Format: YYYY-MM-DD-theme_key.html
        parts = fname.replace(".html", "").split("-", 3)
        if len(parts) == 4:
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            theme_key = parts[3]
            entries.setdefault(date_str, []).append((theme_key, fname))

    rows = ""
    for date_str in sorted(entries.keys(), reverse=True):
        links = ""
        for theme_key, fname in sorted(entries[date_str]):
            label = THEME_LABEL.get(theme_key, theme_key)
            links += f'<a href="{fname}" style="display:inline-block;background:#EBF2FA;color:#185FA5;font-size:14px;font-weight:500;padding:6px 14px;border-radius:4px;text-decoration:none;margin:0 8px 8px 0;">{label}</a>'
        rows += f'''
<div style="padding:16px 0;border-bottom:1px solid #f0f0f0;">
  <div style="font-size:17px;font-weight:600;color:#222;margin-bottom:10px;">{date_str}</div>
  <div>{links}</div>
</div>'''

    index_html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每週深度週報</title>
</head>
<body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;padding:24px 20px;color:#222;">
<div style="border-bottom:2px solid #1B3A5C;padding-bottom:12px;margin-bottom:20px;">
  <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#888;margin-bottom:4px;">WEEKLY DEEP REPORTS</div>
  <div style="font-family:Georgia,serif;font-size:26px;font-weight:700;color:#1B3A5C;">每週深度週報</div>
</div>
{rows}
<div style="font-size:12px;color:#aaa;border-top:1px solid #e8e8e8;padding-top:12px;margin-top:20px;">
  AI 輔助分析 · 僅供參考
</div>
</body>
</html>"""

    with open(os.path.join(weekly_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)


def main() -> None:
    print("=" * 50)
    print("Weekly Deep Report — starting")
    print("=" * 50)

    today, date_short, start = _get_date_info()
    output_dir = os.path.join(os.path.dirname(__file__), "weekly_output")
    os.makedirs(output_dir, exist_ok=True)

    summaries = {}

    for i, theme_key in enumerate(THEME_ORDER, 1):
        theme = WEEKLY_THEMES[theme_key]
        theme_name = theme["name"]
        print(f"\n[{i}/4] Processing: {theme_name}")

        # Fetch
        print(f"  Fetching news...")
        raw_news = fetch_weekly_news(theme_key)
        print(f"  {len(raw_news)} queries completed")

        # Process
        print(f"  Processing with Claude...")
        data = process_weekly_theme(theme_key, theme_name, raw_news)
        summaries[theme_key] = data.get("week_summary", "")

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

    # Send email
    print(f"\n[Email] Sending weekly summary...")
    send_weekly_email(summaries, today, date_short)

    # Publish to GitHub
    print(f"\n[Publish] Publishing to financial-analysis-bot...")
    publish_weekly_to_github(output_dir, today)

    print("\n✓ Weekly report done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
