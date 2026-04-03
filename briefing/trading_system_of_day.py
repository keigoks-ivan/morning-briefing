import json
import os
from datetime import datetime
import pytz


def get_today_system() -> dict:
    """根據今天的日期選出今日交易系統（50天一輪）"""
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz)
    day_of_year = today.timetuple().tm_yday

    json_path = os.path.join(os.path.dirname(__file__), "..", "data", "trading_systems.json")

    try:
        with open(json_path, encoding="utf-8") as f:
            systems = json.load(f)
        idx = day_of_year % len(systems)
        return systems[idx]
    except Exception as e:
        print(f"  ✗ 交易系統資料庫讀取失敗: {e}")
        return {}


def build_applicability_prompt(system: dict, market_data: dict) -> str:
    """
    建立今日市場適用性的 prompt，傳給 Claude API
    只需要生成這個小區塊，約200字，token 成本極低
    """
    name = system.get("name", "")
    conditions = system.get("applicability_conditions", {})
    favorable = conditions.get("favorable", "")
    unfavorable = conditions.get("unfavorable", "")
    category = system.get("category", "")

    # 從 market_data 提取關鍵指標
    vix = market_data.get("vix", {}).get("val", "—")
    fear_greed = market_data.get("fear_greed", {}).get("val", "—")
    rsp_spy = market_data.get("rsp_spy", {}).get("val", "—")
    hyg = market_data.get("hyg", {}).get("chg", "—")

    prompt = f"""你是一個交易系統分析師。根據今日市場數據，評估「{name}」（{category}）的當前適用性。

今日市場數據：
- VIX: {vix}
- Fear & Greed 指數: {fear_greed}
- RSP/SPY 比值變化: {rsp_spy}
- HYG 信貸 ETF 漲跌: {hyg}

這個系統的適合條件：{favorable}
這個系統的不適合條件：{unfavorable}

請輸出以下格式（繁體中文，約150–200字）：
{{
  "verdict": "✓ 條件具備" 或 "⚠ 條件不佳" 或 "✕ 不建議",
  "verdict_reason": "一句話說明判斷依據（引用具體數字）",
  "analysis": "2–3句話深入分析：當前市場環境如何影響這個系統的有效性，具體操作建議",
  "key_metrics": "今日最關鍵的1–2個監控指標和數值"
}}

只輸出 JSON，不要有其他文字。"""

    return prompt


def generate_applicability(system: dict, market_data: dict) -> dict:
    """呼叫 Claude API 生成今日市場適用性評估"""
    import anthropic

    if not system:
        return {}

    prompt = build_applicability_prompt(system, market_data)

    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        text = message.content[0].text.strip()
        # 清理可能的 markdown 包裹
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        return result
    except Exception as e:
        print(f"  ✗ 今日市場適用性生成失敗: {e}")
        return {
            "verdict": "— 暫無評估",
            "verdict_reason": "數據處理中",
            "analysis": "",
            "key_metrics": ""
        }
