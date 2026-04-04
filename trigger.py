import os
import requests
import sys
from datetime import datetime
import pytz

def trigger_workflow(workflow_filename: str) -> bool:
    token = os.environ["GH_PAT"]
    owner = "keigoks-ivan"
    repo = "morning-briefing"

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_filename}/dispatches"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {"ref": "main"}

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code == 204:
        print(f"✓ Triggered {workflow_filename} successfully")
        return True
    else:
        print(f"✗ Failed to trigger {workflow_filename}: {response.status_code} {response.text}")
        return False

if __name__ == "__main__":
    tz = pytz.timezone("Asia/Taipei")
    weekday = datetime.now(tz).weekday()  # 0=週一 6=週日
    if weekday == 6:  # 台灣週日不跑日報
        print("✗ 台灣週日，跳過日報")
        sys.exit(0)
    success = trigger_workflow("daily_briefing.yml")
    sys.exit(0 if success else 1)
