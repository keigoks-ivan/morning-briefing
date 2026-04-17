"""
ai_processor.py
---------------
Gemini 2.5 Pro（分析區塊）+ Gemini 2.5 Flash（新聞區塊）並行生成結構化 JSON。
分析區塊失敗時 fallback 到 Claude Sonnet。
"""

import os
import json
import anthropic
from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor, as_completed


DYNAMIC_STATUS_OPTIONS = """
可選動態維度（今日選3個最相關的）：
- 聯準會立場、ECB 立場、BOJ 立場
- 地緣油價風險、半導體供應鏈、中國科技風險
- 財報季進度、美元/DXY、日圓匯率
- 信用利差、IPO/市場情緒、監管政策風險
- MYR 匯率、台股技術面
"""

# ═══════════════════════════════════════════════════════════════
# Gemini Prompt — 新聞整理區塊
# ═══════════════════════════════════════════════════════════════

GEMINI_SYSTEM_PROMPT = """
你是一位服務專業系統性投資者的財經新聞編輯。
你的工作是從搜尋結果中提取、摘要、分類新聞，輸出嚴格的 JSON 格式。

【最高優先級：語言規則】
1. 所有輸出必須使用「繁體中文」，嚴禁使用簡體中文
2. 常見錯誤提醒：「規範」不是「规范」、「軟體」不是「软件」、「記憶體」不是「内存」、「晶片」不是「芯片」、「網路」不是「网络」、「數據」不是「数据」、「訊息」不是「信息」
3. 公司名/技術術語/數字保留英文
4. 如果你不確定某個字是繁體還是簡體，使用台灣用語

【去重規則】
去重只在「一般新聞區塊」之間生效：
- top_stories → world_news → macro → geopolitical 這四個區塊之間互相去重
- 同一家公司在同一天的同一件事 = 重複（即使措辭不同）

以下三個「專業區塊」有獨立配額，不受 top_stories 去重影響：
- ai_industry：即使 top_stories 已有 AI 相關新聞，ai_industry 仍必須獨立輸出 4-6 條 AI 產業專屬新聞（模型發布、AI 投資、晶片進展、AI 基礎設施等）。角度不同不算重複：top_stories 是新聞事件角度，ai_industry 是產業趨勢角度。
- fintech_crypto：即使其他區塊有加密相關新聞，仍必須獨立輸出 3-5 條
- startup_news：即使其他區塊有新創相關新聞，仍必須獨立輸出 4-5 條

regional_tech 也是獨立區塊，每個地區必須 2-3 條，不受 top_stories 去重影響。

【來源黑名單（絕對不得使用）】
YouTube、TikTok、Twitter/X、Reddit、Facebook、Instagram、個人部落格、Medium（個人文章）、Substack（非已知媒體）、PR Newswire、BusinessWire、GlobeNewswire、WilmerHale、InfoQ

【來源白名單（只使用這些）】
Bloomberg、Reuters、Financial Times、WSJ、CNBC、Barron's、The Economist、Axios、Politico、
TechCrunch、The Information、Wired、Ars Technica、MIT Technology Review、
DIGITIMES、SemiAnalysis、Semiconductor Engineering、EE Times、Nikkei Asia、
South China Morning Post、Taiwan News、
Foreign Affairs、RAND、Brookings、
Fed、ECB、BOJ、BIS、IMF、SEC、FRED、
Gartner、IDC、McKinsey、Goldman Sachs、JP Morgan、Barchart、MoneyDJ

【新聞內容規則】
- 所有新聞區塊只輸出事件性新聞（公司動態、政策、併購、產品發布、人事異動）
- 嚴禁出現：股價漲跌、指數點位、交易量、市值變化、技術分析、行情走勢
- 只使用過去24小時內的新聞
- 排除所有 ESG 相關內容
- source_date 格式統一為 YYYY-MM-DD

【JSON 格式規則】
- 所有數值用英文格式：$1.42T（不是 $1.42兆）
- 只回傳 JSON，不要任何前置說明或 markdown code block
"""

GEMINI_USER_PROMPT_TEMPLATE = """
以下是今日財經新聞搜尋結果：
{news_text}

{earnings_context}

輸出以下 JSON（全部使用繁體中文，嚴禁簡體字）：

{{{{
  "top_stories": [
    {{{{
      "headline": "標題（30字以內）",
      "body": "2–3句，必須包含具體數字",
      "tag": "分類標籤",
      "tag_type": "macro|geo|tech|cb",
      "source": "來源媒體名稱",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "macro": [
    {{{{
      "headline": "總經標題（25字以內）",
      "body": "2句說明，含具體數據",
      "tag": "分類標籤",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "ai_industry": [
    {{{{
      "headline": "AI產業動態標題（25字以內）",
      "body": "2句說明，含具體數據和公司名稱",
      "tag": "分類標籤",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "regional_tech": {{{{
    "taiwan":   [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "japan":    [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "us":       [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "malaysia": [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "korea":    [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "china":    [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "europe":   [{{{{"headline": "標題", "body": "1–2句", "source": "來源", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}]
  }}}},

  "fintech_crypto": [
    {{{{
      "headline": "Fintech/加密貨幣標題（25字以內）",
      "body": "2句說明，含具體數據",
      "tag": "Fintech|Crypto|DeFi|Stablecoin",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "geopolitical": [
    {{{{
      "headline": "地緣政治標題（25字以內）",
      "body": "2句說明，含對市場的直接影響",
      "region": "中東|台海|中美|其他",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "world_news": [
    {{{{
      "headline": "標題（30字以內）",
      "body": "2–3句",
      "region": "地區",
      "tag": "分類標籤",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "startup_news": [
    {{{{
      "headline": "標題（35字以內）",
      "summary": "1–2句",
      "tag": "分類標籤",
      "tag_type": "defense|ai|health|fintech|other",
      "accent": "defense|ai_gov|health|fintech|cyber|other",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "us_market_recap": {{{{
    "has_events": true,
    "earnings": [
      {{{{
        "company": "公司名稱",
        "ticker": "股票代號",
        "beat_miss": "beat/miss/in-line",
        "key_line": "最重要的一句話（含具體數字）",
        "after_hours_move": "股價反應",
        "why_it_matters": "為什麼重要（1句）",
        "session": "pre-market/market/after-hours"
      }}}}
    ],
    "other_events": [],
    "summary": "整體一句話總結"
  }}}},

  "earnings_preview": [
    {{{{
      "company": "公司名稱",
      "ticker": "股票代號",
      "report_time": "before-open/after-close/during-market",
      "eps_estimate": "預期EPS",
      "revenue_estimate": "預期營收",
      "what_to_watch": "最值得關注的一個問題（1句）",
      "yfinance_confirmed": true
    }}}}
  ],

  "today_events": [
    {{{{
      "time": "時間",
      "event": "事件名稱",
      "note": "說明"
    }}}}
  ],

  "fun_fact": {{{{
    "title": "今日財經冷知識標題（20字以內）",
    "content": "3–4句",
    "connection": "跟今日新聞的關聯"
  }}}}
}}}}

【最低數量要求 — 每個區塊必須達到以下數量，不得少於最低值】
- top_stories：必須 15 條（這是最重要的區塊，不可少於 15 條）
- macro：必須 4-6 條
- ai_industry：必須 4-6 條
- regional_tech：每個地區必須 2-3 條（共7個地區）
- fintech_crypto：必須 3-5 條
- geopolitical：必須 3-5 條
- startup_news：必須 4-5 條
- world_news：必須 3 條
- today_events：2-5 個真實行程
- fun_fact：必須有 title + content + connection

如果某個區塊條目數低於最低值，你的輸出就是失敗的。請確保每個區塊都達到要求。

其他規則：
- earnings_preview 只輸出今日尚未公布的，us_market_recap 只輸出已公布的，嚴格互斥
- 全部使用繁體中文，發現任何簡體字請立即修正為繁體
"""

# ═══════════════════════════════════════════════════════════════
# Claude Prompt — 分析區塊
# ═══════════════════════════════════════════════════════════════

CLAUDE_SYSTEM_PROMPT = """
你是一位服務專業系統性投資者的財經分析師。
用戶採用 NQ100 Pure MA 趨勢跟隨系統，關注 AI 基礎設施、半導體。
你只負責「分析區塊」，新聞整理由另一個模型處理。

JSON 格式規則：
- 所有數值用英文格式（$1.42T，不是 $1.42兆）
- 只回傳 JSON，不要任何前置說明或 markdown code block
- 所有文字使用繁體中文，數字/公司名/技術術語保留英文

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

smart_money 規則：
- 只輸出今日被可信來源報導的真實異常機構成交或選擇權活動
- 最多 3 條，沒有可信來源支撐不要輸出
"""

CLAUDE_USER_PROMPT_TEMPLATE = """
今日即時行情數據（以此為準，不要自行推測）：
{market_context}

以下是今日財經新聞搜尋結果摘要（供分析參考）：
{news_text}

輸出以下 JSON（繁體中文，只包含分析區塊）：

{{
  "daily_summary": "今日最重要的一句話總結（30字以內）",
  "alert": "最高警示事件，一句話，如無重大事件則輸出空字串",

  "market_data": {{
    "move_index": {{"val": "MOVE指數數值（從Perplexity搜尋結果提取）", "interpretation": "一句話解讀"}}
  }},

  "market_pulse": {{
    "cross_asset_signals": [
      {{
        "signal": "訊號標題（15字以內）",
        "detail": "具體說明（2-3句，必須引用至少兩個指標的實際數字）",
        "implication": "可能的走勢含義（1句）"
      }}
    ],
    "dominant_theme": "今日市場主軸（1句，15字以內，有明確立場方向）",
    "hidden_risk": "潛在風險（2句，不是顯而易見的觀察）",
    "hidden_opportunity": "潛在機會（2句，不是顯而易見的觀察）",
    "key_level_to_watch": "關鍵價位（用NDX價位）",
    "historical_analog": "歷史類比（1句，點名具體時間段）",
    "new_pattern": "新模式可能性（1句）"
  }},

  "index_factor_reading": {{
    "market_breadth": "市場寬度解讀（1-2句，引用RSP/SPY和IWM/SPY比值）",
    "style_rotation": "風格輪動訊號（1-2句，基於VTV/VUG差異）",
    "sector_signal": "今日動態Sector的含義（1-2句）",
    "nyfang_signal": "科技巨頭訊號（1句，NYFANG vs NDX）",
    "momentum_read": "動能訊號（1句）",
    "key_insight": "最重要的一句洞察（整合以上所有因子，有明確立場）"
  }},

  "sentiment_analysis": {{
    "stage": "第一階段/第二階段/第三階段/第四階段/無明確訊號",
    "stage_name": "暴風雨前的寧靜/崩盤啟動/落底訊號浮現/反轉確立/正常市場",
    "vix_reading": "VIX解讀（1句，含數值）",
    "vvix_reading": "VVIX解讀（1句，含數值）",
    "skew_reading": "SKEW解讀（1句，含數值）",
    "fear_greed_reading": "Fear&Greed補充解讀（1句）",
    "credit_check": "信貸市場交叉確認（1句）",
    "cross_asset_confirm": "跨資產確認（1句）",
    "key_divergence": "最重要的背離或一致性訊號（1句）",
    "reliability": "高/中/低",
    "reliability_reason": "可靠性判斷依據（1句）",
    "one_line": "綜合判斷（1句，有明確立場）"
  }},

  "daily_deep_dive": [
    {{
      "theme": "主題名稱",
      "theme_type": "semiconductor/ai_arch/liquidity/energy/spotlight",
      "headline": "今日這個主題最重要的一句話（25字以內）",
      "situation": "現況描述（4-6句）",
      "key_data": [
        {{"metric": "指標名稱", "value": "具體數值", "change": "變化", "context": "含義（1句）"}}
      ],
      "deep_analysis": "深度分析（4-6句，邏輯推演）",
      "structural_signal": "結構性訊號（2-3句）",
      "bull_case": "樂觀情境（2句）",
      "bear_case": "悲觀情境（2句）",
      "implication": "對投資決策的含義（2-3句）",
      "source": "來源媒體",
      "source_date": "YYYY-MM-DD"
    }}
  ],

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
      "source_date": "YYYY-MM-DD"
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

  "smart_money": {{
    "has_signals": true,
    "signals": [
      {{
        "type": "options/block/etf_flow",
        "ticker": "標的代號",
        "description": "一句話描述異動內容（含具體數字）",
        "direction": "bullish/bearish/neutral",
        "significance": "為什麼值得注意（1句）"
      }}
    ],
    "summary": "今日機構異動整體方向（1句）"
  }}
}}

注意：
1. system_status.dynamic 固定 3 個，從以下選：{dynamic_options}
2. tech_trends 5–6 條，sub_items 固定 3 個
3. daily_deep_dive 固定 2 個主題，從固定查詢（半導體、AI架構）和動態查詢中選最重要的 2 個
4. smart_money 最多 3 條，沒有可信來源不要輸出
5. cross_asset_signals 2-3 個
"""


# ═══════════════════════════════════════════════════════════════
# Gemini Pro Prompt — 深度財報分析區塊
# ═══════════════════════════════════════════════════════════════

EARNINGS_ANALYSIS_SYSTEM_PROMPT = """
你是一位服務專業系統性投資者的財報分析師。
從 Perplexity 給的「最近一個完整美股交易日的財報」原始資料中，只分析「重要財報 × 已實際發布」的公司，整理出深度分析。

【語言規則】
- 輸出全部使用繁體中文；公司名/ticker/數字保留英文
- 嚴禁簡體字，常見錯誤：規範不是规范、晶片不是芯片、數據不是数据

【最高優先級：排除 preview / 分析師預期文章】
只收「已實際發布」的公司。Perplexity 原始資料中若出現以下字樣，該公司一律排除，絕不納入分析：
- "expected to report", "will report", "is set to announce", "ahead of earnings"
- "analysts expect", "consensus forecasts", "Wall Street expects"
- "earnings preview", "what to watch", "what to expect"
- "scheduled for ... after the close", "scheduled for ... before the open"
- 任何「預期 / 預計 / 將於 / 即將公布」等未來式語氣

必須有「actual released」字樣才納入：
- "reported Q1 EPS of $X", "posted revenue of $Y", "Q1 results announced"
- "beat / missed / in line with estimates"（必須是已公布後的比較）
- "the company said / disclosed / reported in its release"
- CEO/CFO 實際在財報電話會議上的言論（非事前預告）

若分不清是 preview 還是 actual，一律排除。寧可少報，不要編造。

【重要財報判斷 — 嚴格篩選】
公司必須同時滿足「已實際發布」AND 以下至少一項：
1. 市值 ≥ $40B 的大型股
2. 指標股（S&P 500 前 100 大、NDX 前 30 大、道瓊成分股）
3. 產業代表股（半導體：NVDA/TSMC/ASML/AMD/AVGO/MU/SK hynix；銀行：JPM/BAC/C/MS/GS/WFC；雲端軟體：MSFT/AMZN/GOOGL/ORCL/CRM；消費：AAPL/WMT/COST/HD/MCD/KO/PEP；醫療：JNJ/UNH/LLY/PFE/ABBV；工業：CAT/DE/GE/BA；能源：XOM/CVX；支付：V/MA；媒體：NFLX/DIS）
4. 有明確論點影響（AI 基建鏈、Fed 貨幣政策傳導、消費者信用、地緣供應鏈）
5. 該次財報有「意外」：大幅 beat/miss、guidance 大幅上下修、CEO 更替、併購宣布

以下情況一律排除：
- 小型股（市值 < $10B）除非是該細分產業的唯一公開資訊來源
- 中型股（$10B-$40B）除非財報有前述「意外」
- 路徑依賴型 beat（例如房貸 REIT 照表操課 beat 幾 cent）
- 資料不齊（Perplexity 只有一句話帶過，無 EPS/營收具體數字）

若整批資料中找不到任何符合（已發布 AND 重要）的財報 → has_content 設 false，companies/industry_trends/winners/losers/contradictions 全空陣列，conclusion 留空。

【內容規則 — 魔鬼在細節】
- 冷靜客觀陳述事實，不要花俏語句、不要煽情詞彙
- 所有重點必須含具體數字（EPS、營收、毛利率、segment 佔比、股價反應 %）
- 當一次性項目（併購稀釋、終止費、重組費用）扭曲 headline EPS 時，必須點出並計算排除後真實數字
- 產業 imply 不得重複新聞標題；必須是「如果這個訊號持續，下一步會怎樣」的推論
- 贏家/輸家：同時考慮「基本面贏家」與「股價輸家」的背離（如 ASML 業績好但股價跌）
- 矛盾與不合邏輯：優先找同業 FICC 差異、beat 但跌/miss 但漲、口頭保守但資本支出進取、宏觀擔憂與業績爆量並存

【JSON 格式規則】
- 只回傳 JSON，不要 markdown code block 或前置說明
- 數值用英文格式：$1.25B、YoY +17%
"""

EARNINGS_ANALYSIS_USER_TEMPLATE = """
以下是過去 24 小時美股重要財報的 Perplexity 搜尋結果（3 組深度查詢）：

{earnings_raw_text}

【市場即時行情（供判斷股價反應是否合理）】
{market_context}

請輸出以下 JSON（繁體中文，嚴禁簡體字）：

{{{{
  "has_content": true,
  "window": "時間窗標示，如 4/15-4/16 或 過去 24 小時",
  "overview": "一句話總覽（25 字內，指出今日財報主軸）",

  "companies": [
    {{{{
      "name": "公司全名",
      "ticker": "TICKER",
      "category": "金融|半導體|媒體串流|工業/REIT|消費|醫療|能源|其他",
      "result_tag": "beat|miss|mixed",
      "key_points": [
        "第一個重點（含具體數字，如 EPS $X vs 估 $Y、營收 YoY +Z%）",
        "第二個重點",
        "第三個重點",
        "第四個重點（可選）"
      ],
      "weakness": "弱點或警示（1 句，可空字串）",
      "one_time_items": "一次性項目說明（排除後真實數字，可空字串）"
    }}}}
  ],

  "industry_trends": [
    {{{{
      "industry": "產業名稱，如 金融業、半導體",
      "core_trend": "核心趨勢（2 句，含具體數字證據）",
      "sub_signals": [
        "子產業訊號 1（含公司名與數字）",
        "子產業訊號 2",
        "子產業訊號 3（可選）"
      ],
      "imply": "對產業的含義（2 句，必須是推論，不是重複事實）"
    }}}}
  ],

  "winners": [
    {{{{
      "name": "公司名",
      "ticker": "TICKER",
      "type": "基本面贏家|股價贏家|兩者皆是",
      "reason": "成為贏家的具體原因（2 句，含數字）"
    }}}}
  ],

  "losers": [
    {{{{
      "name": "公司名",
      "ticker": "TICKER",
      "type": "基本面輸家|股價輸家|兩者皆是",
      "reason": "成為輸家的具體原因（2 句，含數字）"
    }}}}
  ],

  "contradictions": [
    {{{{
      "issue": "矛盾/不合邏輯的標題（15 字內）",
      "detail": "具體矛盾說明（3-4 句，點出數字）",
      "imply": "對產業/市場的含義（1-2 句）"
    }}}}
  ],

  "conclusion": "總結（3-5 句，點出本次財報週的 2-3 個核心主題，含推論）"
}}}}

【數量要求 — 寧缺勿濫】
- companies：最多 10 家，但只收符合「重要財報判斷」的標的。若當日只有 2-3 家重要 → 就輸出 2-3 家，不要湊數
- industry_trends：至少覆蓋 2 個產業；若只有 1 個產業有料就只給 1 個；若不足 2 家公司可歸納就留空陣列
- winners/losers：各 1-4 家；若沒有明顯輸家就留空陣列
- contradictions：0-4 個；找不到真正的矛盾時寧可留空，不要編造
- conclusion：綜合性推論，不要條列；若重要財報太少，conclusion 可以只寫 1-2 句

若過去 24 小時無任何符合「重要財報判斷」的標的（週末、假日、或當天只有小型股），has_content 設 false，全部陣列留空，conclusion 留空。
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


def _build_market_context(market_data: dict, today_earnings: list | None, move_index_raw: str) -> str:
    """把 market_data 格式化成文字，供 Claude 分析用"""
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
        lines.append(f"【流動性綜合】{liq_assess.get('label','')}（評分：{liq_assess.get('score',0)}，訊號：{', '.join(liq_assess.get('signals', []))}）")

    sh = market_data.get("sentiment_history", {})
    if sh:
        def _fmt_5d(entries):
            return " → ".join(f"{e['val']}" for e in entries) if entries else "—"
        lines.append(f"【情緒指標5日趨勢】")
        lines.append(f"VIX 過去5日：{_fmt_5d(sh.get('vix_5d', []))}（趨勢：{sh.get('vix_trend','震盪')}，{sh.get('vix_peak_days_ago',0)}天前見頂）")
        lines.append(f"VVIX 過去5日：{_fmt_5d(sh.get('vvix_5d', []))}（趨勢：{sh.get('vvix_trend','震盪')}，{sh.get('vvix_peak_days_ago',0)}天前見頂於{sh.get('vvix_peak_val',0)}，較峰值回落{sh.get('vvix_peak_decline_pct',0):.1f}%）")
        lines.append(f"SKEW 過去5日：{_fmt_5d(sh.get('skew_5d', []))}（趨勢：{sh.get('skew_trend','震盪')}）")

    slt = market_data.get("second_layer_trends", {})
    if slt:
        lines.append(f"【第二層指標趨勢方向】")
        lines.append(f"HYG信貸：{slt.get('hyg_trend','震盪')} | DXY美元：{slt.get('dxy_trend','震盪')} | 美10Y：{slt.get('us10y_trend','震盪')}")
        lines.append(f"黃金：{slt.get('gold_trend','震盪')} | BTC：{slt.get('btc_trend','震盪')}")
        lines.append(f"RSP/SPY市場寬度：{slt.get('rsp_spy_trend','震盪')} | IWM/SPY小型股：{slt.get('iwm_spy_trend','震盪')}")

    if today_earnings:
        lines.append("\n【yfinance 確認今日財報】")
        for e in today_earnings:
            lines.append(f"{e['ticker']} ({e.get('time','—')})")
    else:
        lines.append("\n【yfinance 確認今日財報】無")

    return "\n".join(lines)


def _parse_json(raw_text: str) -> dict:
    """從 API 回應文字中解析 JSON，含自動修復"""
    import re
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    # 第一次嘗試直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 修復常見 JSON 問題
    # 1. 移除 trailing commas（}, ] 前的逗號）
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # 2. 修復缺少逗號：}\n{ 或 ]\n[ 或 "\n"
    text = re.sub(r'"\s*\n\s*"', '",\n"', text)
    text = re.sub(r'}\s*\n\s*{', '},\n{', text)
    text = re.sub(r']\s*\n\s*\[', '],\n[', text)
    # 3. 修復 }\n" 缺少逗號
    text = re.sub(r'}\s*\n\s*"', '},\n"', text)
    text = re.sub(r']\s*\n\s*"', '],\n"', text)

    return json.loads(text)


def _call_gemini_pro(market_context: str, news_text: str) -> dict:
    """呼叫 Gemini 2.5 Pro（分析區塊，主要模型）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set, falling back to Claude")

    client = genai.Client(api_key=api_key)
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )

    print("  → [Gemini Pro] Calling API (analysis sections)...")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CLAUDE_SYSTEM_PROMPT,
                    max_output_tokens=16000,
                    temperature=0.5,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = (attempt + 1) * 15
                print(f"  ⚠ [Gemini Pro] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    raw_text = response.text
    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    # Gemini 2.5 Pro: input $1.25/MTok, output $10/MTok
    cost = in_tok / 1_000_000 * 1.25 + out_tok / 1_000_000 * 10
    print(f"  → [Gemini Pro] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/gemini_pro_raw.txt", "w") as f:
        f.write(raw_text)

    try:
        return _parse_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [Gemini Pro] JSON error at char {e.pos}: {e.msg}")
        raise


def _call_claude(market_context: str, news_text: str) -> dict:
    """呼叫 Claude API（分析區塊 fallback）"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )

    print("  → [Claude] Calling API (analysis sections, fallback)...")
    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        final_msg = stream.get_final_message()

    usage = final_msg.usage
    input_tok = usage.input_tokens
    output_tok = usage.output_tokens
    cost_input = input_tok / 1_000_000 * 3
    cost_output = output_tok / 1_000_000 * 15
    cost_total = cost_input + cost_output
    print(f"  → [Claude] tokens: in={input_tok:,} out={output_tok:,} cost=${cost_total:.4f}")

    with open("/tmp/claude_raw.txt", "w") as f:
        f.write(full_text)

    try:
        return _parse_json(full_text)
    except json.JSONDecodeError as e:
        print(f"  [Claude] JSON error at char {e.pos}: {e.msg}")
        raise


def _call_gemini(news_text: str, earnings_context: str) -> dict:
    """呼叫 Gemini API（新聞區塊）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠ GEMINI_API_KEY not set, skipping Gemini call")
        return {}

    client = genai.Client(api_key=api_key)

    user_prompt = GEMINI_USER_PROMPT_TEMPLATE.format(
        news_text=news_text,
        earnings_context=earnings_context,
    )

    print("  → [Gemini] Calling API (news sections)...")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=GEMINI_SYSTEM_PROMPT,
                    max_output_tokens=16000,
                    temperature=0.5,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = (attempt + 1) * 15  # 15s, 30s
                print(f"  ⚠ [Gemini] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    raw_text = response.text
    # Token usage log
    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    # Gemini 2.5 Flash Preview: input $0.15/MTok, output $0.60/MTok (thinking off)
    cost = in_tok / 1_000_000 * 0.15 + out_tok / 1_000_000 * 0.60
    print(f"  → [Gemini] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/gemini_raw.txt", "w") as f:
        f.write(raw_text)

    try:
        return _parse_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [Gemini] JSON error at char {e.pos}: {e.msg}")
        raise


def _build_earnings_raw_text(earnings_deep_dive: list[dict] | None) -> str:
    """把 Perplexity 財報查詢結果組成文字。"""
    if not earnings_deep_dive:
        return ""
    parts = []
    for i, item in enumerate(earnings_deep_dive, 1):
        if not item.get("answer"):
            continue
        parts.append(f"## 查詢 {i}: {item.get('query','')[:120]}")
        parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"來源：{src}")
        parts.append("")
    return "\n".join(parts)


def _has_earnings_content(earnings_raw_text: str) -> bool:
    """判斷 Perplexity 回傳是否含實質財報內容；若無直接跳過 LLM。"""
    if not earnings_raw_text or not earnings_raw_text.strip():
        return False
    text = earnings_raw_text.lower()
    # 內容太短 → 視為無
    if len(text) < 800:
        return False
    # 明確宣告無財報的字樣主導
    neg_phrases = [
        "no major earnings", "no significant earnings", "no earnings reports",
        "no earnings were released", "no notable earnings", "no us company earnings",
        "there are no earnings", "no earnings announcements",
    ]
    neg_hits = sum(text.count(p) for p in neg_phrases)
    # 關鍵字出現次數太少 → 視為無
    kw_count = text.count("eps") + text.count("revenue") + text.count("earnings") + text.count("reported")
    if kw_count < 4:
        return False
    # 否定字出現且關鍵字很稀 → 視為無
    if neg_hits >= 2 and kw_count < 10:
        return False
    return True


def _call_claude_earnings_analysis(earnings_raw_text: str, market_context: str) -> dict:
    """呼叫 Claude Sonnet 4.6 做深度財報分析。無當日財報時直接跳過。"""
    empty_stub = {"has_content": False, "companies": [], "industry_trends": [],
                  "winners": [], "losers": [], "contradictions": [],
                  "conclusion": "", "window": "", "overview": ""}

    if not _has_earnings_content(earnings_raw_text):
        print("  ⚠ [Earnings Analysis] 當日無實質財報資料，跳過 LLM 呼叫")
        return empty_stub

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = EARNINGS_ANALYSIS_USER_TEMPLATE.format(
        earnings_raw_text=earnings_raw_text,
        market_context=market_context or "（無）",
    )

    print("  → [Earnings Analysis] Calling Claude Sonnet 4.6...")

    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=EARNINGS_ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        final_msg = stream.get_final_message()

    usage = final_msg.usage
    in_tok = usage.input_tokens
    out_tok = usage.output_tokens
    cost = in_tok / 1_000_000 * 3 + out_tok / 1_000_000 * 15
    print(f"  → [Earnings Analysis] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/claude_earnings_raw.txt", "w") as f:
        f.write(full_text)

    try:
        return _parse_json(full_text)
    except json.JSONDecodeError as e:
        print(f"  [Earnings Analysis] JSON error at char {e.pos}: {e.msg}")
        raise


def _dedup_news(data: dict) -> None:
    """跨區塊去重：用 headline 前15字做指紋，後面的區塊移除與前面重複的"""
    seen = set()

    # 按優先順序處理
    DEDUP_ORDER = [
        ("tech_trends", "headline"),
        ("daily_deep_dive", "headline"),
        ("top_stories", "headline"),
        ("world_news", "headline"),
        ("macro", "headline"),
        ("geopolitical", "headline"),
        ("ai_industry", "headline"),
        ("fintech_crypto", "headline"),
        ("startup_news", "headline"),
    ]

    for key, field in DEDUP_ORDER:
        items = data.get(key, [])
        if not isinstance(items, list):
            continue
        cleaned = []
        for item in items:
            fingerprint = str(item.get(field, ""))[:15]
            if fingerprint and fingerprint in seen:
                continue
            if fingerprint:
                seen.add(fingerprint)
            cleaned.append(item)
        data[key] = cleaned

    # regional_tech 各地區也做去重
    rt = data.get("regional_tech", {})
    if isinstance(rt, dict):
        for region, items in rt.items():
            if not isinstance(items, list):
                continue
            cleaned = []
            for item in items:
                fp = str(item.get("headline", ""))[:15]
                if fp and fp in seen:
                    continue
                if fp:
                    seen.add(fp)
                cleaned.append(item)
            rt[region] = cleaned


def process_news(raw_news: list[dict], market_data: dict | None = None, today_earnings: list | None = None, moneydj_news: list[dict] | None = None, deep_dive_news: list[dict] | None = None, move_index_raw: str = "", earnings_deep_dive: list[dict] | None = None) -> dict:
    news_text = build_news_text(raw_news, moneydj_news, deep_dive_news)

    market_context = ""
    if market_data:
        market_context = _build_market_context(market_data, today_earnings, move_index_raw)

    # 財報上下文（給 Gemini 用）
    earnings_lines = []
    if today_earnings:
        earnings_lines.append("【yfinance 確認今日財報】")
        for e in today_earnings:
            earnings_lines.append(f"{e['ticker']} ({e.get('time','—')})")
        earnings_lines.append("yfinance 確認的設 yfinance_confirmed=true，其餘設 false。")
    earnings_context = "\n".join(earnings_lines)

    # 深度財報 Perplexity 原始資料（給 Gemini Pro 做分析用）
    earnings_raw_text = _build_earnings_raw_text(earnings_deep_dive)

    # ── 並行呼叫：分析(Gemini Pro → Claude fallback) + 新聞(Gemini Flash) + 深度財報(Gemini Pro) ──
    analysis_data = {}
    gemini_data = {}
    earnings_analysis_data = {}

    def _call_analysis_with_fallback():
        """Gemini Pro 為主，失敗時 fallback 到 Claude"""
        try:
            return _call_gemini_pro(market_context, news_text)
        except Exception as e:
            print(f"  ⚠ [Gemini Pro] failed: {e}, falling back to Claude...")
            return _call_claude(market_context, news_text)

    with ThreadPoolExecutor(max_workers=3) as executor:
        analysis_future = executor.submit(_call_analysis_with_fallback)
        gemini_future = executor.submit(_call_gemini, news_text, earnings_context)
        earnings_future = executor.submit(_call_claude_earnings_analysis, earnings_raw_text, market_context)

        try:
            analysis_data = analysis_future.result()
            print(f"  ✓ Analysis sections received")
        except Exception as e:
            print(f"  ✗ Analysis failed (both Gemini Pro & Claude): {e}")

        try:
            gemini_data = gemini_future.result()
            print(f"  ✓ [Gemini Flash] news sections received")
        except Exception as e:
            print(f"  ✗ [Gemini Flash] failed: {e}")

        try:
            earnings_analysis_data = earnings_future.result()
            print(f"  ✓ [Earnings Analysis] received")
        except Exception as e:
            print(f"  ✗ [Earnings Analysis] failed: {e}")

    # ── 合併：分析區塊 + Gemini 新聞 ──
    data = {}

    # 分析區塊（Gemini Pro 或 Claude fallback）
    for key in ["daily_summary", "alert", "market_pulse", "index_factor_reading",
                "sentiment_analysis", "daily_deep_dive", "tech_trends",
                "system_status", "smart_money"]:
        if key in analysis_data:
            data[key] = analysis_data[key]

    # 分析模型的 market_data 只有 move_index
    analysis_move = analysis_data.get("market_data", {}).get("move_index", {})

    # Gemini 新聞區塊
    for key in ["top_stories", "macro", "ai_industry", "regional_tech",
                "fintech_crypto", "geopolitical", "world_news", "startup_news",
                "us_market_recap", "earnings_preview", "today_events", "fun_fact"]:
        if key in gemini_data:
            data[key] = gemini_data[key]

    # 深度財報分析
    if earnings_analysis_data:
        data["earnings_deep_analysis"] = earnings_analysis_data

    # 注入真實市場數據
    if market_data:
        data["market_data"] = market_data
        data["market_data"]["move_index"] = analysis_move

    # 跨區塊去重（code-based）
    _dedup_news(data)

    _validate(data)

    print(f"  → stories={len(data.get('top_stories',[]))}, "
          f"macro={len(data.get('macro',[]))}, "
          f"ai={len(data.get('ai_industry',[]))}, "
          f"tech={len(data.get('tech_trends',[]))}")

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
    data.setdefault("earnings_deep_analysis", {
        "has_content": False,
        "window": "",
        "overview": "",
        "companies": [],
        "industry_trends": [],
        "winners": [],
        "losers": [],
        "contradictions": [],
        "conclusion": "",
    })

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
