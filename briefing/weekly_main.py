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
import anthropic

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
from news_fetcher import fetch_weekly_market_data, fetch_move_index


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
        lines = [
            f"\n即時市場數據（以此為準）：",
            f"VIX Spot: {data['vix_spot']}",
            f"VIX 3M: {data['vix_3m']}",
            f"Term Structure: {data['term_structure']}",
            f"VVIX: {data['vvix']}",
            f"QQQ Put/Call Ratio: {data['qqq_pc_ratio']}",
        ]
        # Add weekly sentiment history
        try:
            from weekly_fetcher import fetch_weekly_sentiment_history
            sh, slt = fetch_weekly_sentiment_history()
            if sh:
                def _fmt_8w(entries):
                    return " → ".join(f"{e['val']}" for e in entries) if entries else "—"
                lines.append(f"\n【情緒指標8週趨勢】")
                lines.append(f"VIX 過去8週：{_fmt_8w(sh.get('vix_8w', []))}（週趨勢：{sh.get('vix_weekly_trend', '震盪')}，{sh.get('vix_peak_weeks_ago', 0)}週前見頂）")
                lines.append(f"VVIX 過去8週：{_fmt_8w(sh.get('vvix_8w', []))}（週趨勢：{sh.get('vvix_weekly_trend', '震盪')}，{sh.get('vvix_peak_weeks_ago', 0)}週前見頂於{sh.get('vvix_peak_val', 0)}，較峰值回落{sh.get('vvix_peak_decline_pct', 0):.1f}%）")
                lines.append(f"SKEW 過去8週：{_fmt_8w(sh.get('skew_8w', []))}（週趨勢：{sh.get('skew_weekly_trend', '震盪')}）")
            if slt:
                lines.append(f"\n【第二層指標週度趨勢方向】")
                lines.append(f"HYG信貸：{slt.get('hyg_weekly_trend', '震盪')} | DXY美元：{slt.get('dxy_weekly_trend', '震盪')} | 美10Y：{slt.get('us10y_weekly_trend', '震盪')}")
                lines.append(f"黃金：{slt.get('gold_weekly_trend', '震盪')} | BTC：{slt.get('btc_weekly_trend', '震盪')}")
                lines.append(f"RSP/SPY市場寬度：{slt.get('rsp_spy_weekly_trend', '震盪')} | IWM/SPY小型股：{slt.get('iwm_spy_weekly_trend', '震盪')}")
        except Exception as e:
            print(f"  ✗ Weekly sentiment context failed: {e}")
        return "\n".join(lines)
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
    market_pulse: dict | None = None,
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
            market_pulse=market_pulse,
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


def generate_weekly_market_pulse(market_data: dict) -> dict:
    """Call Claude to generate weekly cross-indicator market pulse analysis."""
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        def _fmt_items(items):
            return ", ".join(f"{it['label']}: {it.get('val','—')} {it.get('chg','—')}" for it in items)

        market_summary = []
        for cat in ["indices", "factors", "sentiment", "commodities", "bonds", "fx", "credit"]:
            items = market_data.get(cat, [])
            if items:
                market_summary.append(f"{cat}: {_fmt_items(items)}")
        market_str = "\n".join(market_summary)

        prompt = f"""根據以下週度市場數據，分析本週跨指標的訊號：
{market_str}

輸出 JSON：
{{
  "observations": [
    {{
      "signal": "週度訊號標題（15字以內）",
      "detail": "具體說明（3-4句，引用週度漲跌數字，說明本週指標組合暗示什麼）",
      "implication": "下週值得注意的走勢（1句）"
    }}
  ],
  "hidden_risk": "從本週指標背離中看到的潛在風險（2句）",
  "hidden_opportunity": "從本週超賣或背離中看到的潛在機會（2句）"
}}

規則：
- observations 輸出 2-3 個週度跨指標組合觀察
- 重點找本週出現的異常背離或結構性變化
- 引用具體週漲跌數字
- 語氣使用不確定性詞彙：可能、值得注意、暗示、或許、需要觀察
- 嚴禁顯而易見的觀察
- 只回傳 JSON，不要 markdown code block
- 繁體中文，數字保留英文"""

        print("  → Calling Claude for weekly market pulse...")
        full_text = ""
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                full_text += text

        raw = full_text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
            raw = raw.rsplit("```", 1)[0].strip()
        start_idx = raw.find("{")
        end_idx = raw.rfind("}") + 1
        if start_idx != -1 and end_idx > start_idx:
            raw = raw[start_idx:end_idx]

        result = json.loads(raw)
        print(f"  ✓ Weekly pulse: {len(result.get('observations', []))} observations")
        return result
    except Exception as e:
        print(f"  ✗ Weekly market pulse failed: {e}")
        return {"observations": [], "hidden_risk": "", "hidden_opportunity": ""}


def _try_load_weekly_mac_data() -> dict | None:
    """嘗試載入 Mac mini 產生的 weekly_full_data.json"""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, "docs", "briefing", "weekly_full_data.json")

    if not os.path.exists(path):
        print(f"  ⚠ Mac weekly data missing ({path}) → fallback")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ⚠ parse error: {e} → fallback")
        return None

    ts_str = data.get("generated_at", "")
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = pytz.timezone("Asia/Taipei").localize(ts)
        age_min = (datetime.now(ts.tzinfo) - ts).total_seconds() / 60
    except Exception as e:
        print(f"  ⚠ timestamp parse error: {e} → fallback")
        return None

    if age_min > 20:
        print(f"  ⚠ Mac weekly data {age_min:.0f}min old → fallback")
        return None

    # schema check
    sys.path.insert(0, os.path.join(repo_root, "mac_runner"))
    try:
        from validate_schema import validate as _validate_schema
        ok, errors = _validate_schema(data, mode="weekly")
    except ImportError:
        ok, errors = True, []

    if not ok:
        print(f"  ⚠ schema invalid ({len(errors)} errors) → fallback")
        for e in errors[:3]:
            print(f"       - {e}")
        return None

    print(f"  ✓ Using Mac-generated weekly data ({age_min:.0f}min old)")
    return data


def main() -> None:
    print("=" * 50)
    print("Weekly Deep Report — starting")
    print("=" * 50)

    # 0. 嘗試讀 Mac 預跑好的資料
    print("\n[0] Check Mac-generated weekly data...")
    mac_data = _try_load_weekly_mac_data()
    if mac_data:
        print("      Mac weekly path not fully integrated yet — still running fallback pipeline")
        # TODO (PR4+): 加上 Mac weekly data → 主題 JSON 的分派邏輯；先走 fallback
    print(f"      (using fallback pipeline regardless for now)")

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
    # Add MOVE Index from Perplexity
    move_raw = fetch_move_index()
    weekly_market["move_index"] = {"val": "—", "interpretation": ""}
    if move_raw:
        # Extract numeric value from Perplexity response
        import re
        nums = re.findall(r'\b(\d{2,3}(?:\.\d+)?)\b', move_raw)
        if nums:
            weekly_market["move_index"]["val"] = nums[0]

    # Generate weekly market pulse
    print(f"\n[Pulse] Generating weekly market pulse...")
    weekly_pulse = generate_weekly_market_pulse(weekly_market)

    # Send email
    print(f"\n[Email] Sending weekly summary...")
    send_weekly_email(summaries, today, date_short)

    # Publish to GitHub
    print(f"\n[Publish] Publishing to financial-analysis-bot...")
    publish_weekly_to_github(output_dir, today, start, theme_data, weekly_market, weekly_pulse)

    print("\n✓ Weekly report done.\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
