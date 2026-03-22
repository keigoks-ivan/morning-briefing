"""
ai_processor.py
---------------
將 Perplexity 搜尋結果送給 Claude API，生成結構化 JSON。
"""

import os
import json
import anthropic


DYNAMIC_STATUS_OPTIONS = """
可選動態維度（今日選3個最相關的）：
- 聯準會立場、ECB 立場、BOJ 立場
- 地緣油價風險、半導體供應鏈、中國科技風險
- 財報季進度、美元/DXY、日圓匯率
- 信用利差、IPO/市場情緒、監管政策風險
- MYR 匯率、台股技術面
"""

SYSTEM_PROMPT = """
你是一位服務專業系統性投資者的財經分析師。
用戶採用 NQ100 Pure MA 趨勢跟隨系統，關注 AI 基礎設施、半導體、台灣/日本/韓國/中國/歐洲/馬來西亞/新加坡市場。

規則：
- 只回傳 JSON，不要任何前置說明、後記或 markdown code block
- 所有文字使用繁體中文，數字/公司名/技術術語保留英文
- 排除所有 ESG、永續發展、綠能相關內容
- 新聞按日期排序，最新的排最前面
- 來源必須標注原始媒體名稱和日期
- 新聞來源限制在過去24小時內
- 各區塊之間不可出現重複的新聞事件。同一個事件只能出現在最相關的一個區塊，其他區塊不得重複提及。硬核科技趨勢（tech_trends）的內容不受此限制。
"""

USER_PROMPT_TEMPLATE = """
今日即時行情數據（以此為準，不要自行推測）：
{market_context}

以下是今日財經新聞搜尋結果：
{news_text}

輸出以下 JSON 結構（繁體中文）：

{{
  "daily_summary": "今日最重要的一句話總結（30字以內，點出最關鍵的市場訊號）",

  "alert": "最高警示事件，一句話，如無重大事件則輸出空字串",

  "market_data": {{
    "nq100":    {{"val": "數值", "chg": "漲跌", "dir": "pos|neg|neu"}},
    "sp500":    {{"val": "數值", "chg": "漲跌", "dir": "pos|neg|neu"}},
    "brent":    {{"val": "價格", "chg": "漲跌", "dir": "pos|neg|neu"}},
    "vix":      {{"val": "數值", "chg": "漲跌", "dir": "pos|neg|neu"}},
    "fed_rate": {{"val": "利率", "chg": "維持/升/降", "dir": "neu"}}
  }},

  "top_stories": [
    {{
      "headline": "標題（30字以內）",
      "body": "2–3句，必須包含具體數字，避免模糊形容詞",
      "tag": "分類標籤",
      "tag_type": "macro|geo|tech|cb",
      "source": "來源媒體名稱（如：Bloomberg、CNBC、Reuters）",
      "source_date": "新聞日期（如：2026-03-21）",
      "importance": "high|medium"
    }}
  ],

  "macro": [
    {{
      "headline": "總經標題（25字以內）",
      "body": "2句說明，含具體數據",
      "tag": "分類標籤",
      "source": "來源媒體",
      "source_date": "日期",
      "importance": "high|medium"
    }}
  ],

  "ai_industry": [
    {{
      "headline": "AI產業動態標題（25字以內）",
      "body": "2句說明，含具體數據和公司名稱",
      "tag": "分類標籤",
      "source": "來源媒體",
      "source_date": "日期",
      "importance": "high|medium"
    }}
  ],

  "regional_tech": {{
    "taiwan":   [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "japan":    [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "us":       [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "malaysia": [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "korea":    [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "china":    [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}],
    "europe":   [{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "日期", "importance": "high|medium"}}]
  }},

  "fintech_crypto": [
    {{
      "headline": "Fintech/加密貨幣標題（25字以內）",
      "body": "2句說明，含具體數據",
      "tag": "Fintech|Crypto|DeFi|Stablecoin",
      "source": "來源媒體",
      "source_date": "日期",
      "importance": "high|medium"
    }}
  ],

  "geopolitical": [
    {{
      "headline": "地緣政治標題（25字以內）",
      "body": "2句說明，含對市場的直接影響",
      "region": "中東|台海|中美|其他",
      "source": "來源媒體",
      "source_date": "日期",
      "importance": "high|medium"
    }}
  ],

  "system_status": {{
    "fixed": [
      {{"name": "NQ100 趨勢", "val": "狀態", "sub": "說明", "sentiment": "pos|neg|neu"}},
      {{"name": "VIX 水位",   "val": "數值+警示", "sub": "說明", "sentiment": "pos|neg|neu"}},
      {{"name": "AI 基本面",  "val": "評估", "sub": "說明", "sentiment": "pos|neg|neu"}}
    ],
    "dynamic": [
      {{"name": "動態維度", "val": "狀態", "sub": "說明", "sentiment": "pos|neg|neu"}}
    ]
  }},

  "tech_trends": [
    {{
      "label": "子領域標籤",
      "label_type": "robotics|arch|infra_ai|science|other",
      "headline": "標題（40字以內）",
      "summary": "2–3句，含具體數字和技術名詞",
      "sub_items": [
        {{"key": "技術維度", "val": "具體說明"}},
        {{"key": "技術維度", "val": "具體說明"}},
        {{"key": "技術維度", "val": "具體說明"}}
      ],
      "chips": [{{"text": "標籤", "type": "up|risk|watch|new|amber"}}],
      "source": "來源媒體",
      "source_date": "日期"
    }}
  ],

  "startup_news": [
    {{
      "headline": "標題（35字以內）",
      "summary": "1–2句，聚焦產業意義",
      "tag": "分類標籤",
      "tag_type": "defense|ai|health|fintech|other",
      "accent": "defense|ai_gov|health|fintech|cyber|other",
      "source": "來源媒體",
      "source_date": "日期",
      "importance": "high|medium"
    }}
  ],

  "earnings_preview": [
    {{
      "company": "公司名稱",
      "ticker": "股票代號",
      "date": "財報日期",
      "note": "一句重點說明"
    }}
  ],

  "implied_trends": [
    {{
      "num": "①",
      "title": "趨勢標題（20字以內）",
      "desc": "3–4句，跨多條新聞的結構性訊號，引用數字必須來自搜尋結果",
      "implication": "1–2句，對應 NQ100 系統或台灣/日本/東南亞市場"
    }}
  ],

  "fun_fact": {{
    "title": "今日財經冷知識標題（20字以內）",
    "content": "3–4句，跟今日時事有關的有趣財經知識或歷史背景",
    "connection": "一句話說明跟今日新聞的關聯"
  }},

  "today_events": [
    {{
      "time": "時間",
      "event": "事件名稱",
      "note": "說明"
    }}
  ]
}}

注意事項：
1. top_stories 輸出 15 條，按 importance 排序，high 優先，同級按日期最新優先
2. macro 輸出 4–6 條總經新聞
3. ai_industry 輸出 4–6 條 AI 產業動態
4. regional_tech 每個地區 2–3 條
5. fintech_crypto 輸出 3–5 條
6. geopolitical 輸出 3–5 條
7. system_status.dynamic 固定輸出 3 個，從以下選：{dynamic_options}
8. tech_trends 輸出 5–6 條，sub_items 固定 3 個
9. startup_news 輸出 4–5 條
10. earnings_preview 輸出本週重要財報，若無則輸出空陣列
11. implied_trends 固定 4 條，跨多條新聞的綜合訊號
12. today_events 只輸出未來24小時內即將發生的真實行程，按時間由早到晚排序，不要列已經發生的事件，不要編造
13. 所有新聞排除 ESG 相關內容
14. source_date 格式統一為 YYYY-MM-DD
15. implied_trends 引用的數字必須來自搜尋結果，不能推測
"""


def build_news_text(raw_news: list[dict]) -> str:
    parts = []
    for item in raw_news:
        parts.append(f"## {item['query']}")
        if item.get("answer"):
            parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"來源：{src}")
        parts.append("")
    return "\n".join(parts)


def process_news(raw_news: list[dict], market_data: dict | None = None) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    news_text = build_news_text(raw_news)

    market_context = ""
    if market_data:
        md = market_data
        def _mc(label, key):
            d = md.get(key, {})
            return f"{label}: {d.get('val','—')} {d.get('chg','—')}"
        market_context = "\n".join([
            _mc("NQ100", "nq100"), _mc("S&P 500", "sp500"),
            _mc("道瓊", "dow"), _mc("費半", "sox"),
            _mc("台灣加權", "twii"), _mc("日經225", "nikkei"),
            _mc("恒生", "hsi"), _mc("KOSPI", "kospi"), _mc("DAX", "dax"),
            _mc("Brent", "brent"), _mc("WTI", "wti"),
            _mc("天然氣", "nat_gas"), _mc("黃金", "gold"),
            _mc("白銀", "silver"), _mc("銅", "copper"),
            _mc("美10Y殖利率", "us10y"), _mc("美2Y殖利率", "us2y"),
            _mc("DXY", "dxy"), _mc("JPY/USD", "jpyusd"),
            _mc("TWD/USD", "twdusd"), _mc("MYR/USD", "myrusd"),
            _mc("CNY/USD", "cnyusd"), _mc("EUR/USD", "eurusd"),
            _mc("BTC", "btc"), _mc("ETH", "eth"),
            _mc("VIX", "vix"),
            f"Fed Rate: {md.get('fed_rate',{}).get('val','—')}",
        ])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )

    print("  → Calling Claude API...")
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = msg.content[0].text.strip()

    with open("/tmp/claude_raw.txt", "w") as f:
        f.write(raw_text)

    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    start = raw_text.find("{")
    end   = raw_text.rfind("}") + 1
    if start != -1 and end > start:
        raw_text = raw_text[start:end]

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"  JSON error at char {e.pos}: {e.msg}")
        print(f"  Context: ...{raw_text[max(0,e.pos-200):e.pos+200]}...")
        raise

    if market_data:
        data["market_data"] = market_data

    _validate(data)

    print(f"  → stories={len(data.get('top_stories',[]))}, "
          f"macro={len(data.get('macro',[]))}, "
          f"ai={len(data.get('ai_industry',[]))}, "
          f"tech={len(data.get('tech_trends',[]))}, "
          f"trends={len(data.get('implied_trends',[]))}")

    return data


def _validate(data: dict) -> None:
    data.setdefault("daily_summary", "")
    data.setdefault("alert", "")
    data.setdefault("market_data", {})
    data.setdefault("top_stories", [])
    data.setdefault("macro", [])
    data.setdefault("ai_industry", [])
    data.setdefault("regional_tech", {"taiwan": [], "japan": [], "us": [], "malaysia": [], "korea": [], "china": [], "europe": []})
    data.setdefault("fintech_crypto", [])
    data.setdefault("geopolitical", [])
    data.setdefault("tech_trends", [])
    data.setdefault("startup_news", [])
    data.setdefault("earnings_preview", [])
    data.setdefault("implied_trends", [])
    data.setdefault("fun_fact", {})
    data.setdefault("today_events", [])

    ss = data.setdefault("system_status", {})
    ss.setdefault("fixed", [])
    ss.setdefault("dynamic", [])
    ss["fixed"]   = ss["fixed"][:3]
    ss["dynamic"] = ss["dynamic"][:3]

    data["implied_trends"] = data["implied_trends"][:4]
    nums = ["①", "②", "③", "④"]
    for i, t in enumerate(data["implied_trends"]):
        t["num"] = nums[i]

    for trend in data.get("tech_trends", []):
        trend.setdefault("sub_items", [])
        trend.setdefault("chips", [])
        trend.setdefault("label_type", "other")
        trend["sub_items"] = trend["sub_items"][:3]

    md = data.get("market_data", {})
    for key in [
        "nq100", "sp500", "dow", "sox", "twii", "nikkei", "hsi", "kospi", "dax",
        "brent", "wti", "nat_gas", "gold", "silver", "copper",
        "us10y", "us2y",
        "dxy", "jpyusd", "twdusd", "myrusd", "cnyusd", "eurusd",
        "btc", "eth",
        "vix", "fed_rate",
    ]:
        md.setdefault(key, {"val": "—", "chg": "—", "dir": "neu"})

    rt = data.get("regional_tech", {})
    for region in ["taiwan", "japan", "us", "malaysia", "korea", "china", "europe"]:
        rt.setdefault(region, [])
