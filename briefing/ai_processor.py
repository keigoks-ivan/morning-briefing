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

來源黑名單（絕對不得使用，無例外）：
影片/社群平台：YouTube、TikTok、Twitter/X、Reddit、Facebook、Instagram
個人創作平台：個人部落格、Medium（個人文章）、Substack（非已知媒體帳號）
新聞稿平台：PR Newswire（非重大官方公告）、BusinessWire、GlobeNewswire、EurekAlert
法律/專業機構：WilmerHale、任何律師事務所網站
技術開發媒體：InfoQ、任何純技術開發者媒體
其他：LawNext、任何來源標注為影片平台或社群媒體的內容

執行規則：
- 如果 source 欄位填入以上任何來源，該條新聞必須刪除並替換為白名單來源的新聞
- 寧可輸出較少的新聞，也不得使用黑名單來源
- 來源不明或無法識別的新聞一律排除

新聞來源白名單（最高優先級）：
1. 只使用以下白名單來源的新聞和數據：
   一線財經媒體：Bloomberg、Reuters、Financial Times、WSJ、CNBC、Barron's、The Economist、Axios、Politico
   科技/AI 媒體：TechCrunch、The Information、Wired、Ars Technica、MIT Technology Review、Import AI、Stratechery、AI Snake Oil
   半導體專業：DIGITIMES、SemiAnalysis、Semiconductor Engineering、EE Times、Nikkei Asia、AnandTech、ASML 官方、TSMC 官方、Intel 官方投資人日簡報
   亞洲財經：Nikkei Asia、South China Morning Post、Taiwan News
   地緣/智庫：Foreign Affairs、Belfer Center、RAND Corporation、Brookings Institution
   官方來源：Fed、ECB、BOJ、BIS（國際清算銀行）、IMF World Economic Outlook、TSMC、Nvidia 等公司官方聲明、SEC 文件、FRED Blog
   研究機構：Gartner、IDC、McKinsey（公開報告）、Goldman Sachs Global Investment Research、JP Morgan Asset Management、Piper Sandler、Bernstein Research、BIS Quarterly Review
   學術研究：Duke University、MIT、Stanford、Harvard（限官方研究報告，非新聞稿）
   市場數據：Barchart（限選擇權和市場數據內容）
   台灣財經媒體：MoneyDJ（台灣本地財經新聞，限台股、台灣產業、國際財經類內容）
2. 每條新聞的 source 欄位必須填入白名單內的媒體名稱，如果來源不明或不在白名單內，該條新聞不得使用
3. 數字和數據必須有明確的白名單來源支撐，不能使用來源不明的數字

去重規則（最高優先級）：
1. tech_trends 區塊優先權最高，出現在 tech_trends 的公司、事件、新聞，不得再出現在 top_stories、macro、ai_industry、regional_tech、fintech_crypto、geopolitical、startup_news 任何一個區塊
2. 其餘所有區塊之間也不得重複，同一事件只放在最相關的一個區塊
3. 執行順序：先填 tech_trends → 再填其他區塊，填其他區塊時主動排除已在 tech_trends 出現的內容

新聞內容規則：
- top_stories、macro、ai_industry、regional_tech、fintech_crypto、geopolitical、startup_news、world_news 所有新聞類區塊只輸出事件性新聞（公司動態、政策、併購、產品發布、人事異動等）
- 嚴禁在新聞類區塊出現以下內容：股價漲跌、指數點位、交易量、市值變化、技術分析、行情走勢
- 行情數字只出現在 market_data 區塊，新聞類區塊的內容不得重複行情數字
- 如果一條新聞的主要內容是行情走勢（如：「NQ100今日下跌2%」），該條新聞不得列入新聞類區塊

新聞時效與排序規則：
- 所有新聞類區塊只使用過去24小時內的新聞，超過24小時的一律不得使用
- 每個區塊內的新聞同時按重要程度和時效排序：importance=high 且最新的排最前面，importance=high 但較早的排其次，importance=medium 且最新的排再其次
- 如果一條新聞的 source_date 無法確認在過去24小時內，不得列入任何新聞類區塊

JSON 格式規則：
- 所有數值必須用英文格式，不要用中文單位（兆、億、萬）
- 正確：$1420000000000 或 $1.42T 或 1420B
- 錯誤：$1.42兆、$600億
- 這樣可以避免 JSON 解析錯誤

market_data 規則：
- market_data 直接使用 market_context 提供的真實數字，不得修改
- move_index.val 從 Perplexity 搜尋結果中提取真實數值
- 如果 Perplexity 沒有搜到 MOVE Index，val 填 "—"

其他規則：
- 只回傳 JSON，不要任何前置說明、後記或 markdown code block
- 所有文字使用繁體中文，數字/公司名/技術術語保留英文
- 排除所有 ESG、永續發展、綠能相關內容
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
    "indices":    [{{"label":"","val":"","chg":"","dir":"","is_dynamic":false}}],
    "factors":    [{{"label":"","val":"","chg":"","dir":"","is_dynamic":false}}],
    "sentiment":  [{{"label":"","val":"","chg":"","dir":""}}],
    "move_index": {{"val": "MOVE指數數值（從Perplexity）", "interpretation": "一句話解讀（偏高/正常/偏低）"}},
    "commodities":[{{"label":"","val":"","chg":"","dir":""}}],
    "bonds":      [{{"label":"","val":"","chg":"","dir":""}}],
    "fx":         [{{"label":"","val":"","chg":"","dir":""}}],
    "credit":     [{{"label":"","val":"","chg":"","dir":""}}]
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

  "world_news": [
    {{
      "headline": "標題（30字以內）",
      "body": "2–3句，著重事件本身和區域影響，不含行情數字",
      "region": "地區（如：中東、歐洲、東南亞、拉美、非洲、北美、東北亞）",
      "tag": "分類標籤（如：外交、衝突、選舉、氣候、人道）",
      "source": "來源媒體",
      "source_date": "日期 YYYY-MM-DD",
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

  "daily_deep_dive": [
    {{
      "theme": "主題名稱（如：半導體供應鏈、AI架構、全球流動性、能源市場、今日焦點）",
      "theme_type": "semiconductor/ai_arch/liquidity/energy/spotlight",
      "headline": "今日這個主題最重要的一句話（25字以內）",
      "situation": "現況描述（3-4句，必須含具體數字和來源，描述今日最新狀態）",
      "key_data": [
        {{"metric": "指標名稱", "value": "具體數值", "change": "變化方向和幅度", "context": "這個數字的含義"}}
      ],
      "structural_signal": "這個主題今日透露的結構性訊號（2-3句，跨越單一新聞的洞察）",
      "implication": "對投資決策的直接含義（2句，具體說明影響哪些標的或市場）",
      "source": "主要來源媒體",
      "source_date": "日期 YYYY-MM-DD"
    }}
  ],

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
10. earnings_preview 只輸出今日（美股當日）即將發布但尚未公布數字的財報，不要輸出已經發布的財報，不要輸出非今日的財報，yfinance 確認的優先列出且 yfinance_confirmed=true，Perplexity 搜尋到的作為補充且 yfinance_confirmed=false，如今日無重要財報則輸出空陣列。earnings_preview 和 us_market_recap 嚴格互斥：earnings_preview 是今日即將發布但尚未公布數字的財報，us_market_recap 是已經公布數字的昨日財報結果，同一家公司不得同時出現在兩個區塊。
11. implied_trends 固定 4 條，跨多條新聞的綜合訊號
12. today_events 只輸出未來24小時內即將發生的真實行程，按時間由早到晚排序，不要列已經發生的事件，不要編造
13. us_market_recap 嚴格規則：只輸出已經發生且已公布結果的財報和事件，時間範圍為台灣時間昨日 16:00 至今日 05:55 之間實際發生的事件。盤前（pre-market）財報只在財報數字已公布後才列入，不得列入「預計今日發布」的財報。如果財報只是「預計今日發布」但尚未公布數字，不得列入 us_market_recap，應列入 earnings_preview。has_events=false 優先於輸出不確定的事件。所有條目按時間由早到晚排序（盤前→盤中→盤後），session 欄位標注對應時段。
14. smart_money 只輸出今日被可信來源報導的真實異常機構成交或選擇權活動，最多輸出 3 條最重要的，沒有可信來源支撐的不要輸出，has_signals=false 時 signals 輸出空陣列
15. world_news 固定輸出 3 條，著重國際情勢和區域發展，全球範圍皆可，優先選過去24小時內最重要且與金融市場或地緣政治有潛在關聯的事件，importance=high 的優先排前，同級別按 source_date 最新優先，嚴禁與 top_stories、geopolitical、macro 等其他區塊的新聞重複
16. 所有新聞排除 ESG 相關內容
17. source_date 格式統一為 YYYY-MM-DD
18. implied_trends 引用的數字必須來自搜尋結果，不能推測
19. daily_deep_dive 輸出 3-5 個主題，優先輸出今日有重要新發展的主題：
    (1) 半導體供應鏈（semiconductor）：只在今日有具體庫存/產能/定價新數據時輸出
    (2) AI模型與架構（ai_arch）：只在今日有新模型發布/重要研究/算力動態時輸出
    (3) 全球流動性（liquidity）：只在今日有Fed動態/RRP變化/重要流動性數據時輸出
    (4) 能源市場（energy）：只在今日有重要油價/LNG/OPEC動態時輸出
    (5) 今日焦點（spotlight）：由Claude自行判斷今日最值得深挖的主題，可以是以上四個之外的任何主題
    key_data 每個主題輸出 2-4 個具體指標，必須有實際數值。
    如果某個主題今日沒有重要新發展，不要強行輸出，寧可少不要濫。
    所有內容來自過去24小時，數字必須有可信來源支撐。
"""


def build_news_text(raw_news: list[dict], moneydj_news: list[dict] | None = None, deep_dive_news: list[dict] | None = None) -> str:
    parts = []
    for item in raw_news:
        parts.append(f"## {item['query']}")
        if item.get("answer"):
            parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"來源：{src}")
        parts.append("")

    if moneydj_news:
        parts.append("## MoneyDJ 台灣財經即時新聞（過去24小時）")
        for item in moneydj_news:
            parts.append(f"標題：{item['title']}\n摘要：{item['summary']}\n來源：MoneyDJ {item['published']}")
        parts.append("")

    if deep_dive_news:
        parts.append("## 深度聚焦搜尋結果（用於 daily_deep_dive 區塊）")
        for item in deep_dive_news:
            parts.append(f"### {item['query']}")
            if item.get("answer"):
                parts.append(item["answer"])
            for src in item.get("sources", []):
                parts.append(f"來源：{src}")
            parts.append("")

    return "\n".join(parts)


def process_news(raw_news: list[dict], market_data: dict | None = None, today_earnings: list | None = None, moneydj_news: list[dict] | None = None, deep_dive_news: list[dict] | None = None, move_index_raw: str = "") -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    news_text = build_news_text(raw_news, moneydj_news, deep_dive_news)

    market_context = ""
    if market_data:
        def _fmt_items(items):
            return ", ".join(f"{it['label']}: {it.get('val','—')} {it.get('chg','—')}" for it in items)

        indices_str = _fmt_items(market_data.get("indices", []))
        factors_list = market_data.get("factors", [])
        static_factors = [f for f in factors_list if not f.get("is_dynamic")]
        dynamic_factors = [f for f in factors_list if f.get("is_dynamic")]
        factors_str = _fmt_items(static_factors)
        top_sectors = ", ".join(f["label"] for f in dynamic_factors)
        sentiment_str = _fmt_items(market_data.get("sentiment", []))
        move_index_str = move_index_raw if move_index_raw else "無資料"
        commodities_str = _fmt_items(market_data.get("commodities", []))
        bonds_str = _fmt_items(market_data.get("bonds", []))
        fx_str = _fmt_items(market_data.get("fx", []))
        credit_str = _fmt_items(market_data.get("credit", []))

        lines = []
        lines.append(f"【股票指數】{indices_str}")
        lines.append(f"【美股因子】{factors_str}（含今日波動最大 Sector：{top_sectors}）")
        lines.append(f"【市場情緒】{sentiment_str}")
        lines.append(f"【MOVE Index】{move_index_str}（從Perplexity搜尋）")
        lines.append(f"【原物料】{commodities_str}")
        lines.append(f"【債券】{bonds_str}")
        lines.append(f"【外匯】{fx_str}")
        lines.append(f"【信貸市場】{credit_str}")

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

    print("  → Calling Claude API (streaming)...")
    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=32000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text

    raw_text = full_text.strip()

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
        # Preserve Claude's move_index interpretation, merge with fetched data
        claude_move = data.get("market_data", {}).get("move_index", {})
        data["market_data"] = market_data
        data["market_data"]["move_index"] = claude_move

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
    data.setdefault("world_news", [])
    data["world_news"] = data["world_news"][:3]
    data.setdefault("tech_trends", [])
    data.setdefault("startup_news", [])
    data.setdefault("earnings_preview", [])
    data.setdefault("implied_trends", [])
    data.setdefault("us_market_recap", {"has_events": False, "earnings": [], "other_events": [], "summary": ""})
    data.setdefault("smart_money", {"has_signals": False, "signals": [], "summary": ""})
    data.setdefault("daily_deep_dive", [])
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
    md.setdefault("indices", [])
    md.setdefault("factors", [])
    md.setdefault("sentiment", [])
    md.setdefault("move_index", {"val": "—", "interpretation": ""})
    md.setdefault("commodities", [])
    md.setdefault("bonds", [])
    md.setdefault("fx", [])
    md.setdefault("credit", [])

    rt = data.get("regional_tech", {})
    for region in ["taiwan", "japan", "us", "malaysia", "korea", "china", "europe"]:
        rt.setdefault(region, [])
