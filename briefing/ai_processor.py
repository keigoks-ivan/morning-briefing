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
【最高優先級：全域去重規則】

執行順序（嚴格按照此順序填寫各區塊，後面的區塊不得重複前面已用過的內容）：

Step 1：先填 tech_trends（硬核科技趨勢）
Step 2：先填 daily_deep_dive（每日深度聚焦）
Step 3：再填 top_stories（核心要聞）— 排除已在Step1、Step2出現的公司/事件/數據
Step 4：再填 world_news（國際新聞）— 排除Step1-3已用內容
Step 5：再填 macro（總經動態）— 排除Step1-4已用內容
Step 6：再填 geopolitical（地緣政治）— 排除Step1-5已用內容
Step 7：再填 ai_industry（AI產業動態）— 排除Step1-6已用內容
Step 8：再填 regional_tech（四國科技）— 排除Step1-7已用內容
Step 9：再填 fintech_crypto（Fintech/加密）— 排除Step1-8已用內容
Step 10：再填 startup_news（新創產業）— 排除Step1-9已用內容
Step 11：再填 us_market_recap（昨日美股重點）— 排除Step1-10已用內容
Step 12：再填 smart_money（機構異動）— 排除Step1-11已用內容

去重定義：
- 同一家公司在同一天的同一件事 = 重複（即使措辭不同）
- 同一個數據點（如「Fed維持利率不變」）= 重複
- 同一個地緣政治事件（如「霍爾木茲海峽關閉」）= 重複
- 但同一個大主題的不同面向不算重複
  例如：AI晶片需求（tech_trends）≠ Nvidia財報預告（earnings_preview）
  例如：半導體供應鏈分析（daily_deep_dive）≠ 台積電法說會摘要（us_market_recap）

如果某個區塊找不到不重複的新內容，寧可輸出較少條目（最少1條），
也不要把已經出現過的內容重複放入。

tech_trends 和 daily_deep_dive 的深度分析部分（sub_items、key_data、deep_analysis等）
不受去重限制，可以深度分析任何主題，但其他區塊不得把相同的新聞事件再列一遍。

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

market_pulse 分析規則：
- 股票指數分析使用 NDX（^NDX）數值，這是美股前一日正式收盤價
- cross_asset_signals 輸出 2-3 個，每個必須是跨指標的組合觀察，不是單一指標的描述
- 三層推論框架：(1)背離識別：找出指標之間的異常組合 (2)雙軌機制推論：從背離推導可能的驅動機制 (3)情境推演：推導如果機制持續，下一步會怎樣
- 可分析的指標來源：股票指數（NDX）、因子（NYFANG vs NDX、RSP/SPY市場寬度、MTUM動能、IWM小型股）、情緒（VIX/VIX9D/SKEW/VVIX）、MOVE Index、原物料、債券、外匯、信貸（HYG/LQD比值）、流動性（RRP/TGA/銀行準備金/NFCI + 綜合評分）
- 每個 detail 必須引用至少兩個具體指標數字
- dominant_theme 必須有明確立場方向（如「流動性驅動的風險偏好回升」），不可模糊
- hidden_risk / hidden_opportunity 各2句，不是顯而易見的觀察
- key_level_to_watch 用 NDX 價位
- historical_analog 點名具體時間段做類比
- new_pattern 如果當前不符合歷史模式，說明可能的新範式
- 語氣使用不確定性詞彙
- 嚴禁輸出顯而易見的觀察
- 整體 300字以內

sentiment_analysis 強化分析規則：

【四部曲判斷邏輯】
第一階段（暴風雨前）：VIX < 20 + SKEW > 135 + VVIX 平穩
第二階段（崩盤啟動）：VIX > 30 且快速上升 + VVIX > 120 且飆升 + SKEW 急跌
第三階段（落底訊號）：VIX > 40 或維持高檔 + VVIX 已見頂開始回落 + SKEW 低於115
第四階段（反轉確立）：VIX 從高檔回落 + VVIX 回到 100 左右 + 股市反彈

【Fear&Greed 整合】
- Fear&Greed < 15 + VIX > 40 + VVIX 見頂回落 → 三重確認底部訊號
- Fear&Greed > 70 + SKEW > 135 + VIX < 20 → 第一階段警示加強版

【假底判斷：信貸交叉確認】
- HYG 跌幅 < 1% 且 LQD 穩定 → 非系統性恐慌，可靠性「高」
- HYG 跌幅 1-3% + LQD 略跌 → 信貸壓力中等，可靠性「中」
- HYG 跌幅 > 3% + LQD 同步大跌 → 系統性信貸危機風險，四部曲可能失效，可靠性「低」

【跨資產確認訊號】（需至少2個才算確認）
- 黃金從跟股票一起跌轉為走強或穩定 → 流動性危機緩解
- BTC 跌幅收窄或開始反彈 → 風險偏好最敏感指標率先反應
- 日圓升值放緩（JPY/USD 不再快速升值）→ carry trade 平倉接近尾聲
- DXY 見頂或走弱 → 美元流動性危機緩解

【時間維度判斷（使用5日歷史數據）】

第三階段精確判斷：
必要條件：
1. VIX 今日值 > 35
2. VVIX 已從高點連續回落 2天以上（vvix_peak_days_ago >= 2）
3. SKEW < 120

充分條件：
4. VIX 今日值 > 40
5. VVIX 較峰值回落超過 10%（vvix_peak_decline_pct > 10）
6. Fear&Greed < 20

滿足必要條件但不滿足充分條件：stage=第三階段，reliability=中
同時滿足必要和充分條件：stage=第三階段，reliability=高

第二階段 vs 第三階段區分：
- vvix_peak_days_ago <= 1（今天或昨天才見頂）→ 第二階段
- vvix_peak_days_ago >= 2（2天前已見頂）且 VIX 仍高 → 第三階段

vvix_reading 格式：
若 vvix_peak_days_ago >= 2：
  「VVIX {今日值}，{vvix_trend}，{vvix_peak_days_ago}天前見頂於{vvix_peak_val}，較峰值已回落{vvix_peak_decline_pct}%」
若 vvix_peak_days_ago <= 1：
  「VVIX {今日值}，{vvix_trend}，剛於{vvix_peak_days_ago}天前見頂，第三階段條件尚未成熟」
若 vvix_trend == 持續上升：
  「VVIX {今日值}，持續上升尚未見頂，仍處第二階段加速期」

【第二層趨勢加強分析】
在 cross_asset_confirm 中必須整合第二層趨勢：
- 黃金連續上升 + BTC 震盪或下降 → 避險需求主導，非風險偏好回升
- 黃金連續下降 → 流動性危機（拋售一切），底部訊號可靠性下降
- DXY 連續上升 + HYG 連續下降 → 美元強勢收緊全球流動性，壓力持續
- RSP/SPY 連續收縮 + IWM/SPY 連續收縮 → 市場高度集中化，底部前通常需要寬化確認
- BTC 連續上升 先於黃金和股票 → 風險偏好率先回升，底部訊號增強

【可靠性判斷矩陣】
高：信貸穩定（HYG跌<1%）+ 至少2個跨資產確認 + 非金融危機環境
中：信貸輕微壓力（HYG跌1-3%）或跨資產確認不足 或 有金融系統風險苗頭
低：信貸嚴重惡化（HYG跌>3%）或 系統性危機環境（類2008）

【one_line 要求】
必須包含：當前階段 + 可靠性 + 最可能的下一步
引用至少兩個指標的具體數值
不能兩邊都說，不能說「需要觀察」作為結論

index_factor_reading 分析規則：
- 所有分析必須引用具體的漲跌幅數字
- market_breadth 同時使用兩個寬度指標：
  RSP/SPY 比值上升=等權重強於市值加權=市場變寬
  IWM/SPY 比值上升=小型股強於大型股=風險偏好上升
  兩個都上升=真正的市場變寬
  兩個都下降=高度集中化，少數大型股主導
  RSP/SPY上升但IWM/SPY下降=中型股強但小型股弱，部分寬化
- style_rotation：VTV 跌幅 < VUG 跌幅=資金往價值股（防禦），VTV 跌幅 > VUG=追逐成長
- sector_signal：說明今日波動最大的Sector反映的產業資金邏輯
- nyfang_signal：NYFANG 跌幅 > NDX=科技巨頭領跌，NYFANG 跌幅 < NDX=巨頭相對抗跌
- momentum_read：MTUM 跌幅 vs NDX，MTUM 抗跌=動能股仍被追捧，MTUM 領跌=動能瓦解
- key_insight 必須有立場，不能兩邊都說，要說明今日美股最重要的結構性特徵

殖利率曲線分析：
- 10Y-2Y利差 < 0 = 倒掛，歷史上是衰退的6-18個月領先指標
- 倒掛轉正（熊市陡峭化）往往比倒掛本身更危險，代表短端利率快速下降（Fed緊急降息）
- 30Y-10Y利差擴大代表長期通膨預期上升

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

  "market_pulse": {{
    "cross_asset_signals": [
      {{
        "signal": "訊號標題（15字以內）",
        "detail": "具體說明（2-3句，必須引用至少兩個指標的實際數字，說明它們組合起來暗示什麼）",
        "implication": "可能的走勢含義（1句，用「可能」「值得注意」等不確定性語氣）"
      }}
    ],
    "dominant_theme": "今日市場主軸（1句，15字以內，有明確立場方向）",
    "hidden_risk": "從指標背離或異常組合中發現的潛在風險（2句，不是顯而易見的觀察）",
    "hidden_opportunity": "從指標背離或超賣訊號中發現的潛在機會（2句，不是顯而易見的觀察）",
    "key_level_to_watch": "今日最值得關注的一個關鍵價位或門檻（用NDX價位）",
    "historical_analog": "歷史類比（1句，點名具體時間段，如：類似2023年10月底的流動性轉折）",
    "new_pattern": "新模式可能性（1句，如果當前組合不符合歷史模式，說明可能的新範式）"
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

  "implied_trends": [],

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
      "theme": "主題名稱",
      "theme_type": "semiconductor/ai_arch/liquidity/energy/spotlight",
      "headline": "今日這個主題最重要的一句話（25字以內）",
      "situation": "現況描述（4-6句，必須含具體數字、公司名稱、來源，描述今日最新狀態的完整圖景）",
      "key_data": [
        {{"metric": "指標名稱", "value": "具體數值", "change": "變化方向和幅度", "context": "這個數字的含義（1句）"}}
      ],
      "deep_analysis": "深度分析（4-6句，從數據中識別表面看不到的結構性含義，必須有邏輯推演過程，不是描述事實）",
      "structural_signal": "結構性訊號（2-3句，跨越單一新聞的中長期含義，指出這個趨勢指向哪裡）",
      "bull_case": "樂觀情境（2句，如果這個訊號往正面發展，可能的走勢）",
      "bear_case": "悲觀情境（2句，如果這個訊號往負面發展，可能的走勢）",
      "implication": "對投資決策的直接含義（2-3句，具體說明影響哪些標的、產業鏈或市場）",
      "source": "主要來源媒體",
      "source_date": "日期 YYYY-MM-DD"
    }}
  ],

  "index_factor_reading": {{
    "market_breadth": "市場寬度解讀（1-2句，同時引用RSP/SPY比值變化和IWM/SPY比值變化，說明這波漲跌是廣泛還是集中）",
    "style_rotation": "風格輪動訊號（1-2句，基於VTV/VUG漲跌幅差異，說明資金在價值和成長之間的移動方向）",
    "sector_signal": "今日動態Sector的含義（1-2句，說明波動最大的Sector反映了什麼產業邏輯）",
    "nyfang_signal": "科技巨頭訊號（1句，NYFANG vs NDX比較，說明科技巨頭是帶頭跌還是相對抗跌）",
    "momentum_read": "動能訊號（1句，MTUM表現說明市場動能是否持續）",
    "key_insight": "最重要的一句洞察（整合以上所有因子，說明今日美股結構性特徵，有明確立場）"
  }},

  "sentiment_analysis": {{
    "stage": "第一階段/第二階段/第三階段/第四階段/無明確訊號",
    "stage_name": "暴風雨前的寧靜/崩盤啟動/落底訊號浮現/反轉確立/正常市場",
    "vix_reading": "VIX解讀（1句，含數值）",
    "vvix_reading": "VVIX解讀（1句，含數值，特別注意是否見頂回落）",
    "skew_reading": "SKEW解讀（1句，含數值）",
    "fear_greed_reading": "Fear&Greed補充解讀（1句，說明是否強化或矛盾主要訊號）",
    "credit_check": "信貸市場交叉確認（1句，HYG/LQD狀態是否支持底部訊號）",
    "cross_asset_confirm": "跨資產確認（1句，黃金/BTC/日圓是否有確認訊號）",
    "key_divergence": "最重要的背離或一致性訊號（1句）",
    "reliability": "高/中/低",
    "reliability_reason": "可靠性判斷依據（1句）",
    "one_line": "綜合判斷：現在市場狀態及未來最可能發展（1句，有明確立場）"
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
10. earnings_preview 只輸出今日（美股當日）即將發布但尚未公布數字的財報，不要輸出已經發布的財報，不要輸出非今日的財報，yfinance 確認的優先列出且 yfinance_confirmed=true，Perplexity 搜尋到的作為補充且 yfinance_confirmed=false，如今日無重要財報則輸出空陣列。earnings_preview 和 us_market_recap 嚴格互斥：earnings_preview 是今日即將發布但尚未公布數字的財報，us_market_recap 是已經公布數字的昨日財報結果，同一家公司不得同時出現在兩個區塊。
11. implied_trends：已停用，直接輸出空陣列 []
12. today_events 只輸出未來24小時內即將發生的真實行程，按時間由早到晚排序，不要列已經發生的事件，不要編造
13. us_market_recap 嚴格規則：只輸出已經發生且已公布結果的財報和事件，時間範圍為台灣時間昨日 16:00 至今日 05:55 之間實際發生的事件。盤前（pre-market）財報只在財報數字已公布後才列入，不得列入「預計今日發布」的財報。如果財報只是「預計今日發布」但尚未公布數字，不得列入 us_market_recap，應列入 earnings_preview。has_events=false 優先於輸出不確定的事件。所有條目按時間由早到晚排序（盤前→盤中→盤後），session 欄位標注對應時段。
14. smart_money 只輸出今日被可信來源報導的真實異常機構成交或選擇權活動，最多輸出 3 條最重要的，沒有可信來源支撐的不要輸出，has_signals=false 時 signals 輸出空陣列
15. world_news 固定輸出 3 條，著重國際情勢和區域發展，全球範圍皆可，優先選過去24小時內最重要且與金融市場或地緣政治有潛在關聯的事件，importance=high 的優先排前，同級別按 source_date 最新優先，嚴禁與 top_stories、geopolitical、macro 等其他區塊的新聞重複
16. 所有新聞排除 ESG 相關內容
17. source_date 格式統一為 YYYY-MM-DD
18. （implied_trends 已停用）
19. daily_deep_dive 動態主題規則：
    - 固定輸出 2 個主題，不多不少
    - 可選範圍：固定查詢（半導體、AI架構）+ 動態查詢（今日最重要的3個主題）共5個
    - 選擇標準：今日新聞數據最豐富、對投資決策影響最深遠的 2 個
    - 如果動態主題明顯比固定主題更重要（如央行緊急行動、重大地緣事件），優先選動態主題
    - theme 欄位標注：固定主題寫「半導體供應鏈」或「AI架構」，動態主題寫實際主題名稱
    - situation 必須 4-6 句，完整描述今日最新狀態
    - key_data 每個主題輸出 3-5 個具體指標，必須有實際數值
    - deep_analysis 必須有邏輯推演，不是新聞摘要，要說明為什麼這件事重要
    - bull_case 和 bear_case 必須是具體的情境描述，不是模糊的可能性
    - structural_signal 要指向中長期（3-12個月）的含義
    - 所有數字必須來自今日可信來源，不得推測或捏造
    - 深度優先於廣度：寧可兩個主題非常深入，不要五個主題都很淺
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
        # Support both old list format and new dict format
        if isinstance(deep_dive_news, dict):
            fixed_deep = deep_dive_news.get("fixed", [])
            dynamic_deep = deep_dive_news.get("dynamic", [])
        else:
            fixed_deep = deep_dive_news
            dynamic_deep = []

        if fixed_deep:
            parts.append("## 深度聚焦搜尋結果 — 固定主題（用於 daily_deep_dive 區塊）")
            for item in fixed_deep:
                parts.append(f"### [深度-固定] {item.get('query', '')[:60]}")
                if item.get("answer"):
                    parts.append(item["answer"])
                for src in item.get("sources", []):
                    parts.append(f"來源：{src}")
                parts.append("")

        if dynamic_deep:
            parts.append("## 深度聚焦搜尋結果 — 今日動態主題（用於 daily_deep_dive 區塊）")
            for item in dynamic_deep:
                parts.append(f"### [深度-動態] 今日焦點：{item.get('topic', '')}")
                if item.get("result"):
                    parts.append(item["result"])
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
        commodities_data = market_data.get("commodities", {})
        if isinstance(commodities_data, dict):
            all_commodities = commodities_data.get("fixed", []) + commodities_data.get("dynamic", [])
        elif isinstance(commodities_data, list):
            all_commodities = commodities_data
        else:
            all_commodities = []
        commodities_str = _fmt_items(all_commodities)
        bonds_str = _fmt_items(market_data.get("bonds", []))
        fx_str = _fmt_items(market_data.get("fx", []))
        credit_str = _fmt_items(market_data.get("credit", []))

        liquidity_items = market_data.get("liquidity", [])
        liq_parts = []
        for li in liquidity_items:
            date_str = f"（{li['date']}）" if li.get("date") else ""
            liq_parts.append(f"{li['label']}: {li.get('val','—')} {li.get('chg','—')}{date_str}")
        liquidity_str = ", ".join(liq_parts) if liq_parts else "無資料"

        lines = []
        lines.append(f"【股票指數】{indices_str}")
        lines.append(f"【美股因子】{factors_str}（含今日波動最大 Sector：{top_sectors}）")
        # Extract RSP/SPY and IWM/SPY for market breadth context
        rsp_spy_val = rsp_spy_chg = iwm_spy_val = iwm_spy_chg = "—"
        for f in static_factors:
            if f.get("label") == "RSP/SPY":
                rsp_spy_val, rsp_spy_chg = f.get("val", "—"), f.get("chg", "—")
            elif f.get("label") == "IWM/SPY 小型":
                iwm_spy_val, iwm_spy_chg = f.get("val", "—"), f.get("chg", "—")
        lines.append(f"【市場寬度】RSP/SPY比值：{rsp_spy_val}（{rsp_spy_chg}），IWM/SPY比值：{iwm_spy_val}（{iwm_spy_chg}）")
        lines.append(f"【市場情緒】{sentiment_str}")
        lines.append(f"【MOVE Index】{move_index_str}（從Perplexity搜尋）")
        lines.append(f"【原物料】{commodities_str}")
        lines.append(f"【債券】{bonds_str}")
        lines.append(f"【外匯】{fx_str}")
        lines.append(f"【信貸市場】{credit_str}")
        lines.append(f"【流動性】{liquidity_str}")
        liq_assess = market_data.get("liquidity_assessment", {})
        if liq_assess:
            assess_label = liq_assess.get("label", "")
            assess_score = liq_assess.get("score", 0)
            assess_signals = ", ".join(liq_assess.get("signals", []))
            lines.append(f"【流動性綜合】{assess_label}（評分：{assess_score}，訊號：{assess_signals}）")

        # Sentiment 5-day history context
        sh = market_data.get("sentiment_history", {})
        if sh:
            def _fmt_5d(entries):
                return " → ".join(f"{e['val']}" for e in entries) if entries else "—"
            vix_trend = sh.get("vix_trend", "震盪")
            vix_peak_days = sh.get("vix_peak_days_ago", 0)
            vvix_trend = sh.get("vvix_trend", "震盪")
            vvix_peak_days = sh.get("vvix_peak_days_ago", 0)
            vvix_peak_v = sh.get("vvix_peak_val", 0)
            vvix_decline = sh.get("vvix_peak_decline_pct", 0)
            skew_trend = sh.get("skew_trend", "震盪")
            lines.append(f"【情緒指標5日趨勢】")
            lines.append(f"VIX 過去5日：{_fmt_5d(sh.get('vix_5d', []))}（趨勢：{vix_trend}，{vix_peak_days}天前見頂）")
            lines.append(f"VVIX 過去5日：{_fmt_5d(sh.get('vvix_5d', []))}（趨勢：{vvix_trend}，{vvix_peak_days}天前見頂於{vvix_peak_v}，較峰值回落{vvix_decline:.1f}%）")
            lines.append(f"SKEW 過去5日：{_fmt_5d(sh.get('skew_5d', []))}（趨勢：{skew_trend}）")

        # Second layer trends context
        slt = market_data.get("second_layer_trends", {})
        if slt:
            lines.append(f"【第二層指標趨勢方向】")
            lines.append(f"HYG信貸：{slt.get('hyg_trend','震盪')} | DXY美元：{slt.get('dxy_trend','震盪')} | 美10Y：{slt.get('us10y_trend','震盪')}")
            lines.append(f"黃金：{slt.get('gold_trend','震盪')} | BTC：{slt.get('btc_trend','震盪')}")
            lines.append(f"RSP/SPY市場寬度：{slt.get('rsp_spy_trend','震盪')} | IWM/SPY小型股：{slt.get('iwm_spy_trend','震盪')}")

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
    data["implied_trends"] = []  # 已停用，強制清空
    data.setdefault("us_market_recap", {"has_events": False, "earnings": [], "other_events": [], "summary": ""})
    data.setdefault("smart_money", {"has_signals": False, "signals": [], "summary": ""})
    data.setdefault("market_pulse", {"cross_asset_signals": [], "dominant_theme": "", "hidden_risk": "", "hidden_opportunity": "", "key_level_to_watch": "", "historical_analog": "", "new_pattern": ""})
    data.setdefault("daily_deep_dive", [])
    data.setdefault("index_factor_reading", {
        "market_breadth": "",
        "style_rotation": "",
        "sector_signal": "",
        "nyfang_signal": "",
        "momentum_read": "",
        "key_insight": ""
    })
    data.setdefault("sentiment_analysis", {
        "stage": "無明確訊號",
        "stage_name": "正常市場",
        "vix_reading": "",
        "vvix_reading": "",
        "skew_reading": "",
        "fear_greed_reading": "",
        "credit_check": "",
        "cross_asset_confirm": "",
        "key_divergence": "",
        "reliability": "中",
        "reliability_reason": "",
        "one_line": ""
    })
    data.setdefault("fun_fact", {})
    data.setdefault("today_events", [])

    ss = data.setdefault("system_status", {})
    ss.setdefault("fixed", [])
    ss.setdefault("dynamic", [])
    ss["fixed"]   = ss["fixed"][:3]
    ss["dynamic"] = ss["dynamic"][:3]

    # implied_trends 已停用，不再處理

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
    md.setdefault("liquidity", [])
    md.setdefault("liquidity_assessment", {"label": "—", "color": "neu", "score": 0, "signals": []})

    rt = data.get("regional_tech", {})
    for region in ["taiwan", "japan", "us", "malaysia", "korea", "china", "europe"]:
        rt.setdefault(region, [])
