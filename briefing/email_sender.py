"""
email_sender.py
使用 Resend API 發送 HTML Email。
"""

import os
import json
import requests
from datetime import datetime
import pytz


def send_email(html_content: str, screener_result: dict = None) -> None:
    tz  = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    date_str = now.strftime("%m/%d")
    weekday  = ["一", "二", "三", "四", "五", "六", "日"][now.weekday()]
    subject  = f"📊 每日財經晨報 {date_str}（週{weekday}）"

    raw = os.environ["TO_EMAIL"]
    recipients = [addr.strip() for addr in raw.split(",") if addr.strip()]

    payload = {
        "from": "Morning Briefing <onboarding@resend.dev>",
        "to": [recipients[0]],  # Resend 測試模式只能寄給帳號本人
        "subject": subject,
        "html": html_content,
    }

    # 加入 Excel 附件
    if screener_result and screener_result.get("excel_b64"):
        payload["attachments"] = [
            {
                "filename": screener_result.get("excel_filename", "screener.xlsx"),
                "content": screener_result["excel_b64"],
            }
        ]

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
        print(f"  → Email sent: {response.status_code} — {subject}")
        print(f"  → Recipients: {', '.join(recipients)}")
    else:
        print(f"  → Error: {response.status_code} — {response.text}")
        raise Exception(f"Resend API error: {response.status_code}")


def send_fallback_alert(reason: str, mode: str = "daily") -> None:
    """Mac mini 失敗 / Mac data 不可用時，寄告警信提醒 GHA 走了 API fallback。"""
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    label = "日報" if mode == "daily" else "週報"
    subject = f"⚠️ Mac mini 未產出 {label} 資料（{now.strftime('%m/%d %H:%M')} TW）— GHA 走 API fallback"

    raw = os.environ.get("TO_EMAIL", "")
    recipients = [addr.strip() for addr in raw.split(",") if addr.strip()]
    if not recipients:
        print("  ⚠ TO_EMAIL not set — skip fallback alert")
        return

    html = f"""
    <div style="font-family:-apple-system,sans-serif;max-width:600px;padding:20px;">
      <h2 style="color:#C0392B;">⚠️ Mac mini 預跑失敗，已切換 API fallback</h2>
      <p><b>時間：</b>{now.strftime('%Y-%m-%d %H:%M')} TW</p>
      <p><b>模式：</b>{label}（{mode}）</p>
      <p><b>原因：</b></p>
      <pre style="background:#F5F5F5;padding:12px;border-radius:6px;white-space:pre-wrap;">{reason}</pre>
      <p>GitHub Actions 已自動走 Perplexity + Claude API fallback 繼續產出 {label}。</p>
      <hr>
      <p style="color:#888;font-size:13px;">常見排查：Mac mini 是否開機 / launchd agent 是否載入 / 網路是否正常 / <code>mac_runner/orchestrate.py</code> 是否有錯。</p>
    </div>
    """

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("  ⚠ RESEND_API_KEY not set — skip fallback alert")
        return

    payload = {
        "from": "Morning Briefing Alert <onboarding@resend.dev>",
        "to": [recipients[0]],
        "subject": subject,
        "html": html,
    }
    response = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=30,
    )
    if response.status_code in (200, 201):
        print(f"  → Fallback alert sent: {subject}")
    else:
        print(f"  → Fallback alert failed: {response.status_code} — {response.text}")
