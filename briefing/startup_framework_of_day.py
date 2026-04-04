import json
import os
from datetime import datetime
import pytz


def get_today_framework() -> dict:
    """根據今天的日期選出今日創業框架（50天一輪）"""
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz)
    day_of_year = today.timetuple().tm_yday

    json_path = os.path.join(os.path.dirname(__file__), "..", "data", "startup_frameworks.json")

    try:
        with open(json_path, encoding="utf-8") as f:
            frameworks = json.load(f)
        idx = day_of_year % len(frameworks)
        return frameworks[idx]
    except Exception as e:
        print(f"  ✗ 創業框架資料庫讀取失敗: {e}")
        return {}


def generate_framework_applicability(framework: dict, market_data: dict) -> dict:
    """呼叫 Claude API 生成今日框架應用建議"""
    import anthropic

    if not framework:
        return {}

    name = framework.get("name", "")
    category = framework.get("category", "")
    daily_app = framework.get("today_application", "")

    vix = market_data.get("vix", {}).get("val", "—")
    fear_greed = market_data.get("fear_greed", {}).get("val", "—")
    hyg = market_data.get("hyg", {}).get("chg", "—")

    prompt = f"""你是一位創業教練。根據今日市場環境，為「{name}」（{category}）框架生成今日具體應用建議。

今日市場環境：
- VIX: {vix}
- Fear & Greed 指數: {fear_greed}
- HYG 信貸 ETF 漲跌: {hyg}

框架的日常應用指引：{daily_app}

請輸出以下格式（繁體中文，約150字）：
{{
  "application": "2-3句話，根據今日市場環境，具體說明今天如何應用這個框架（引用市場數據）",
  "key_action": "今天最重要的一個行動（一句話，具體可執行）"
}}

只輸出 JSON，不要有其他文字。"""

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        return result
    except Exception as e:
        print(f"  ✗ 創業框架適用性生成失敗: {e}")
        return {
            "application": daily_app,
            "key_action": "回顧今天的產品決策是否符合這個框架"
        }
