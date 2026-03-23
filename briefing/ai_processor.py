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

新聞來源品質規則（最高優先級）：
1. 只使用以下白名單來源的新聞和數據：
   一線財經媒體：Bloomberg、Reuters、Financial Times、WSJ、CNBC、Barron's、The Economist、Axios、Politico
   科技/AI 媒體：TechCrunch、The Information、Wired、Ars Technica、MIT Technology Review、Import AI、Stratechery、AI Snake Oil
   半導體專業：DIGITIMES、SemiAnalysis、Semiconductor Engineering、EE Times、Nikkei Asia、AnandTech、ASML 官方、TSMC 官方、Intel 官方投資人日簡報
   亞洲財經：Nikkei Asia、South China Morning Post、Taiwan News
   地緣/智庫：Foreign Affairs、Belfer Center、RAND Corporation、Brookings Institution
   官方來源：Fed、ECB、BOJ、BIS（國際清算銀行）、IMF World Economic Outlook、TSMC、Nvidia 等公司官方聲明、SEC 文件、FRED Blog
   研究機構：Gartner、IDC、McKinsey（公開報告）、Goldman Sachs Global Investment Research、JP Morgan Asset Management、Piper Sandler、Bernstein Research、BIS Quarterly Review
2. 來自不知名網站、個人部落格、PR Newswire 新聞稿（非重要公告）的內容一律排除
3. 每條新聞的 source 欄位必須填入白名單內的媒體名稱，如果來源不明或不在白名單內，該條新聞不得使用
4. 數字和數據必須有明確的白名單來源支撐，不能使用來源不明的數字

去重規則（最高優先級）：
1. tech_trends 區塊優先權最高，出現在 tech_trends 的公司、事件、新聞，不得再出現在 top_stories、macro、ai_industry、regional_tech、fintech_crypto、geopolitical、startup_news 任何一個區塊
2. 其餘所有區塊之間也不得重複，同一事件只放在最相關的一個區塊
3. 執行順序：先填 tech_trends → 再填其他區塊，填其他區塊時主動排除已在 tech_trends 出現的內容

其他規則：
- 只回傳 JSON，不要任何前置說明、後記或 markdown code block
- 所有文字使用繁體中文，數字/公司名/技術術語保留英文
- 排除所有 ESG、永續發展、綠能相關內容
- 新聞按日期排序，最新的排最前面
- 來源必須標注原始媒體名稱和日期
- 新聞來源限制在過去24小時內
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
    "dynamic": [
      {{"label": "動態格標籤", "val": "數值", "chg": "漲跌", "dir": "pos|neg|neu"}}
    ]
  }},

  "us_market_recap": {{
    "has_events": true,
    "earnings": [
      {{
        "company": "公司名稱",
        "ticker": "股票代號",
        "beat_miss": "beat/miss/in-line",
        "key_line": "法說會或財報最重要的一句話（含具體數字）",
        "after_hours_move": "股價反應（如：▲ +8.2%）",
        "why_it_matters": "為什麼這個結果重要（1句）",
        "session": "pre-market/market/after-hours"
      }}
    ],
    "other_events": [
      {{
        "company": "公司或機構名稱",
        "event": "事件類型（如：analyst day、investor conference、product launch）",
        "key_line": "最重要的一句話",
        "market_impact": "對市場的影響（1句）",
        "session": "pre-market/market/after-hours"
      }}
    ],
    "summary": "整體一句話總結（如無重要事件則輸出空字串）"
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
      "report_time": "before-open/after-close/during-market",
      "eps_estimate": "預期EPS（有則填，無則填空字串）",
      "revenue_estimate": "預期營收（有則填，無則填空字串）",
      "what_to_watch": "今日這份財報最值得關注的一個指標或問題（1句）",
      "yfinance_confirmed": true
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

  "smart_money": {{
    "has_signals": true,
    "signals": [
      {{
        "type": "options/block/etf_flow",
        "ticker": "標的代號",
        "description": "一句話描述異動內容（含具體數字）",
        "direction": "bullish/bearish/neutral",
        "significance": "為什麼值得注意（1句，15字以內）"
      }}
    ],
    "summary": "今日機構異動整體方向（1句，如無訊號則空字串）"
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
10. earnings_preview 只輸出今日（美股當日）即將發布的財報，不要輸出已經發布的財報，不要輸出非今日的財報，yfinance 確認的優先列出且 yfinance_confirmed=true，Perplexity 搜尋到的作為補充且 yfinance_confirmed=false，如今日無重要財報則輸出空陣列
11. implied_trends 固定 4 條，跨多條新聞的綜合訊號
12. today_events 只輸出未來24小時內即將發生的真實行程，按時間由早到晚排序，不要列已經發生的事件，不要編造
13. us_market_recap 涵蓋台灣時間昨日 16:00 至今日 06:00 之間（即美股完整交易日：盤前、盤中、盤後）發生的重要財報和法說會事件。earnings 輸出這段時間內發布財報的重要公司結果。other_events 輸出這段時間內的重要法說會、Investor Day、產品發布、重大聲明。所有條目按時間由早到晚排序（盤前→盤中→盤後），session 欄位標注對應時段。如無重要事件 has_events 輸出 false，earnings 和 other_events 輸出空陣列。
14. smart_money 只輸出今日被可信來源報導的真實異常機構成交或選擇權活動，最多輸出 3 條最重要的，沒有可信來源支撐的不要輸出，has_signals=false 時 signals 輸出空陣列
15. 所有新聞排除 ESG 相關內容
16. source_date 格式統一為 YYYY-MM-DD
17. implied_trends 引用的數字必須來自搜尋結果，不能推測
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


def process_news(raw_news: list[dict], market_data: dict | None = None, today_earnings: list | None = None) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    news_text = build_news_text(raw_news)

    market_context = ""
    if market_data:
        lines = []
        # Fixed 12
        lines.append("【固定行情（12格）】")
        for item in market_data.get("fixed", []):
            lines.append(f"{item['label']}: {item.get('val','—')} {item.get('chg','—')}")
        # Fear & Greed
        fg = market_data.get("fear_greed", {})
        lines.append(f"\n【CNN Fear & Greed Index】")
        lines.append(f"Score: {fg.get('val','—')}  Rating: {fg.get('chg','—')}")
        # Dynamic pool
        lines.append(f"\n【動態備選池（從中選4個最重要的放入 market_data.dynamic）】")
        for item in market_data.get("dynamic_pool", []):
            lines.append(f"{item['label']}({item.get('key','')}): {item.get('val','—')} {item.get('chg','—')}")
        lines.append("\n從 dynamic_pool 中選出今日最重要的 4 個動態格，")
        lines.append("選擇標準：今日漲跌幅絕對值最大、或與當日重大新聞最相關、或能補充固定格沒有的市場視角，")
        lines.append("確保選出的標的不與固定12格重複。")
        lines.append("把選出的動態格放入 market_data.dynamic 陣列，每格包含 label/val/chg/dir。")

        # Today's earnings from yfinance
        if today_earnings:
            lines.append("\n【yfinance 確認今日財報】")
            for e in today_earnings:
                lines.append(f"{e['ticker']} ({e.get('time','—')})")
            lines.append("以上為 yfinance 確認的今日財報公司，請優先列入 earnings_preview，")
            lines.append("並將 yfinance_confirmed 設為 true。")
            lines.append("Perplexity 搜尋到但 yfinance 未確認的公司，yfinance_confirmed 設為 false。")
        else:
            lines.append("\n【yfinance 確認今日財報】無")

        market_context = "\n".join(lines)

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
        # Preserve Claude's dynamic picks, merge with fetched data
        claude_dynamic = data.get("market_data", {}).get("dynamic", [])
        data["market_data"] = market_data
        data["market_data"]["dynamic"] = claude_dynamic

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
    data.setdefault("us_market_recap", {"has_events": False, "earnings": [], "other_events": [], "summary": ""})
    data.setdefault("smart_money", {"has_signals": False, "signals": [], "summary": ""})
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
    md.setdefault("fixed", [])
    md.setdefault("fear_greed", {"val": "—", "chg": "—", "dir": "neu"})
    md.setdefault("dynamic_pool", [])
    md.setdefault("dynamic", [])

    rt = data.get("regional_tech", {})
    for region in ["taiwan", "japan", "us", "malaysia", "korea", "china", "europe"]:
        rt.setdefault(region, [])
