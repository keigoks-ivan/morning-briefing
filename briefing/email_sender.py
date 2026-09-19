"""
email_sender.py
使用 Resend API 發送 HTML Email。
"""

import os
import json
import requests
from datetime import datetime
import pytz


def _post(payload: dict) -> "requests.Response":
    return requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=30,
    )


def send_email(html_content: str, screener_result: dict = None) -> None:
    tz  = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    subject  = f"📊 Morning Briefing — {now.strftime('%a %d %b')}"

    # TO_EMAIL 以逗號分隔，全部都寄。
    raw = os.environ["TO_EMAIL"]
    recipients = [addr.strip() for addr in raw.split(",") if addr.strip()]

    payload = {
        # 注意用 `or` 不是 get 的 default：workflow 在 secret 不存在時會傳空字串進來，
        # get(..., default) 會拿到 ""，寄件人就空了。
        "from": os.environ.get("FROM_EMAIL") or "Morning Briefing <onboarding@resend.dev>",
        "to": recipients,
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

    response = _post(payload)

    # Resend 共用寄件人 onboarding@resend.dev 只准寄給帳號本人。多收件人被擋時
    # 整封會失敗——這裡退回只寄第一位，寧可少寄一個人也不要日報信整個斷掉。
    # 根治方式：在 Resend 驗證自有網域，設 FROM_EMAIL=briefing@investmquest.com。
    if response.status_code not in (200, 201) and len(recipients) > 1:
        print(f"  → Multi-recipient send rejected ({response.status_code}): {response.text[:200]}")
        print(f"  → Falling back to {recipients[0]} only. "
              f"Verify a domain in Resend and set FROM_EMAIL to deliver to all {len(recipients)}.")
        payload["to"] = [recipients[0]]
        response = _post(payload)
        recipients = recipients[:1]

    if response.status_code in (200, 201):
        print(f"  → Email sent: {response.status_code} — {subject}")
        print(f"  → Recipients: {', '.join(recipients)}")
    else:
        print(f"  → Error: {response.status_code} — {response.text}")
        raise Exception(f"Resend API error: {response.status_code}")
