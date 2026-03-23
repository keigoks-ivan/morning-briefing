"""
weekly_processor.py
-------------------
將每個主題的 Perplexity 搜尋結果送給 Claude，生成深度週報 JSON。
"""

import os
import json
import anthropic


WEEKLY_SYSTEM_PROMPT = """
你是一位為專業投資者撰寫深度週報的資深分析師。
不同於每日晨報的廣度，週報的核心價值是：
1. 把本週所有相關訊號整合成一個連貫的敘事
2. 識別表面新聞背後的結構性變化
3. 提供具體數字支撐的分析，而不是模糊的評論
4. 明確指出這週的訊號跟上週相比有什麼變化
5. 對投資決策有直接含義的結論

輸出風格參考 SemiAnalysis 和 Digitimes 的深度：有觀點、有數字、有邏輯鏈，而不是新聞摘要的堆砌。
只回傳 JSON，不要任何前置說明或 markdown code block。
所有文字使用繁體中文，數字/公司名/技術術語保留英文。
"""

WEEKLY_USER_PROMPT_TEMPLATE = """
以下是「{theme_name}」主題的本週搜尋結果：

{news_text}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "{theme_name}",

  "week_summary": "本週這個主題最重要的一句話（30字以內）",

  "signal_change": "跟上週相比，最關鍵的變化是什麼（2-3句，有具體數字）",

  "deep_analysis": [
    {{
      "title": "分析角度標題（20字以內）",
      "content": "深度分析內容（6-10句，必須包含具體數字、公司名稱、技術細節）",
      "evidence": ["支撐這個分析的具體證據或數據點1", "證據2", "證據3"],
      "implication": "對投資決策的直接含義（2-3句）"
    }}
  ],

  "earnings_calls": [
    {{
      "company": "公司名稱",
      "key_quotes": "法說會最重要的一句話或數據",
      "what_it_means": "為什麼這句話重要（1-2句）"
    }}
  ],

  "analyst_views": [
    {{
      "firm": "投行或研究機構名稱",
      "view": "觀點摘要",
      "target_change": "目標價或評級變化（如有，否則填空字串）"
    }}
  ],

  "watchlist_impact": "對觀察清單的直接影響評估（2-3句）",

  "next_week_catalysts": ["下週值得關注的催化劑1", "催化劑2", "催化劑3"],

  "risk_flags": ["當前最需要警惕的風險訊號1", "風險訊號2", "風險訊號3"]
}}

注意事項：
1. deep_analysis 輸出 4-5 個角度
2. earnings_calls 輸出本週有法說會的公司，無則輸出空陣列
3. analyst_views 輸出 3-5 個
4. next_week_catalysts 固定 3 個
5. risk_flags 固定 3 個
6. 所有引用的數字必須來自搜尋結果，不能推測
"""


def _build_news_text(raw_news: list[dict]) -> str:
    parts = []
    for item in raw_news:
        parts.append(f"## {item['query']}")
        if item.get("answer"):
            parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"來源：{src}")
        parts.append("")
    return "\n".join(parts)


def process_weekly_theme(theme_key: str, theme_name: str, raw_news: list[dict]) -> dict:
    """Process one weekly theme and return structured JSON."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    news_text = _build_news_text(raw_news)

    user_prompt = WEEKLY_USER_PROMPT_TEMPLATE.format(
        theme_name=theme_name,
        news_text=news_text,
    )

    print(f"  → Calling Claude API for [{theme_key}]...")
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=WEEKLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = msg.content[0].text.strip()

    with open(f"/tmp/weekly_{theme_key}_raw.txt", "w") as f:
        f.write(raw_text)

    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    if start != -1 and end > start:
        raw_text = raw_text[start:end]

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"  JSON error at char {e.pos}: {e.msg}")
        print(f"  Context: ...{raw_text[max(0,e.pos-200):e.pos+200]}...")
        raise

    _validate(data, theme_name)

    print(f"  → [{theme_key}] analysis={len(data.get('deep_analysis',[]))}, "
          f"earnings={len(data.get('earnings_calls',[]))}, "
          f"analysts={len(data.get('analyst_views',[]))}")

    return data


def _validate(data: dict, theme_name: str) -> None:
    data.setdefault("theme", theme_name)
    data.setdefault("week_summary", "")
    data.setdefault("signal_change", "")
    data.setdefault("deep_analysis", [])
    data.setdefault("earnings_calls", [])
    data.setdefault("analyst_views", [])
    data.setdefault("watchlist_impact", "")
    data.setdefault("next_week_catalysts", [])
    data.setdefault("risk_flags", [])

    for item in data["deep_analysis"]:
        item.setdefault("title", "")
        item.setdefault("content", "")
        item.setdefault("evidence", [])
        item.setdefault("implication", "")

    for item in data["earnings_calls"]:
        item.setdefault("company", "")
        item.setdefault("key_quotes", "")
        item.setdefault("what_it_means", "")

    for item in data["analyst_views"]:
        item.setdefault("firm", "")
        item.setdefault("view", "")
        item.setdefault("target_change", "")
