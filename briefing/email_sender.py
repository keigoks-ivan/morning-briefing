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
