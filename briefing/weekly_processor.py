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

只回傳 JSON，不要任何前置說明或 markdown code block。
所有文字使用繁體中文，數字/公司名/技術術語保留英文。
"""

# Generic template for: ai_industry, semiconductor, macro, black_swan
GENERIC_PROMPT = """
以下是「{theme_name}」主題的本週搜尋結果：

{news_text}

{extra_context}

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

EARNINGS_PROMPT = """
以下是「財報季追蹤」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "財報季追蹤",
  "has_earnings": true或false,
  "week_summary": "本週財報季一句話總結（30字以內）",
  "earnings_results": [
    {{
      "company": "公司名稱",
      "ticker": "股票代號",
      "eps_actual": "實際EPS",
      "eps_estimate": "預期EPS",
      "revenue_actual": "實際營收",
      "revenue_estimate": "預期營收",
      "beat_miss": "beat/miss/in-line",
      "guidance": "展望調整（上調/下調/維持/未提供）",
      "key_insight": "最重要的一句話（具體數字）",
      "stock_reaction": "財報後股價反應"
    }}
  ],
  "sector_trends": "本週財報透露的產業趨勢（3-4句）",
  "next_week_earnings": ["下週重要財報預告1", "預告2", "預告3"],
  "risk_flags": ["風險訊號1", "風險訊號2"]
}}

注意事項：
1. has_earnings: 本週是否有重要財報結果公布，如果沒有設為 false
2. 如果 has_earnings=false，earnings_results 輸出空陣列，week_summary 寫「本週無重要財報」
3. earnings_results 列出所有本週公布財報的重要公司
4. 所有數字必須來自搜尋結果
"""

OPTIONS_PROMPT = """
以下是「選擇權市場情緒」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "選擇權市場情緒",
  "week_summary": "一句話總結選擇權市場訊號（30字以內）",
  "vix_data": {{
    "vix_spot": "VIX現值",
    "vix_3m": "VIX3M現值",
    "term_structure": "contango/backwardation/flat",
    "vvix": "VVIX現值",
    "interpretation": "期限結構對市場的含義（2句）"
  }},
  "put_call": {{
    "qqq_ratio": "QQQ Put/Call Ratio",
    "trend": "本週趨勢（上升/下降/持平）",
    "signal": "偏多/偏空/中性",
    "interpretation": "對NQ100方向的含義（2句）"
  }},
  "skew_positioning": "市場偏斜和大型機構部位分析（3-4句）",
  "gamma_environment": "Gamma環境分析，對NQ100波動的影響（2-3句）",
  "key_levels": ["選擇權市場顯示的關鍵支撐/壓力位1", "關鍵位2", "關鍵位3"],
  "nq_signal": "綜合選擇權指標對NQ100的判斷（2-3句，明確說明偏多/偏空/中性及理由）",
  "risk_flags": ["選擇權市場風險訊號1", "風險2"]
}}

注意事項：
1. 如果有提供即時 VIX/VVIX/P-C Ratio 數據，優先使用那些數據填入對應欄位
2. key_levels 固定 3 個
3. nq_signal 必須明確給出方向判斷
"""

COMMODITIES_PROMPT = """
以下是「能源與大宗商品」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "能源與大宗商品",
  "week_summary": "本週大宗商品最重要訊號（30字以內）",
  "energy": {{
    "oil_analysis": "油市供需分析（3-4句，含具體數字）",
    "key_drivers": ["本週油價關鍵驅動因素1", "因素2", "因素3"],
    "opec_update": "OPEC相關動態",
    "nat_gas": "天然氣市場狀況（2句）"
  }},
  "metals": {{
    "gold_analysis": "黃金走勢分析（2-3句）",
    "industrial_metals": "工業金屬（銅、白銀）分析（2-3句）",
    "key_signal": "金屬市場對全球景氣的訊號"
  }},
  "agriculture": "農產品市場重要動態（2句，無重要消息可填空字串）",
  "macro_signal": "大宗商品整體對通膨和景氣的訊號（2-3句）",
  "risk_flags": ["能源/商品市場風險訊號1", "風險2"],
  "next_week_catalysts": ["下週催化劑1", "催化劑2", "催化劑3"]
}}
"""

CENTRAL_BANK_PROMPT = """
以下是「央行政策追蹤」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "央行政策追蹤",
  "week_summary": "本週央行政策最重要訊號（30字以內）",
  "fed": {{
    "key_statements": "本週Fed官員最重要表態（含姓名和具體內容）",
    "rate_probability": "市場隱含的下次升降息機率變化",
    "next_meeting": "下次FOMC會議日期和市場預期",
    "hawkish_dovish_shift": "本週偏鷹/偏鴿的轉變程度（-3到+3，負數偏鴿）"
  }},
  "other_cb": [
    {{
      "bank": "央行名稱",
      "action": "本週動作或表態",
      "implication": "對市場的含義"
    }}
  ],
  "rate_market": "利率市場定價變化分析（3-4句）",
  "nq_implication": "央行政策週變化對NQ100估值的直接影響（2-3句）",
  "next_week_events": ["下週重要央行事件1", "事件2"],
  "risk_flags": ["央行政策風險訊號1", "風險2"]
}}

注意事項：
1. hawkish_dovish_shift 用整數，-3最鴿到+3最鷹
2. other_cb 列出ECB、BOJ、BOE等有動作的央行，無則空陣列
3. 所有數字必須來自搜尋結果
"""

CREDIT_PROMPT = """
以下是「信貸市場週報」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "信貸市場週報",
  "week_summary": "本週信貸市場最重要訊號（30字以內）",
  "spread_data": {{
    "hyg_weekly_return": "HYG週報酬",
    "lqd_weekly_return": "LQD週報酬",
    "hyg_lqd_ratio_change": "HYG/LQD比值週變化",
    "spread_direction": "利差擴大/收窄/持平",
    "interpretation": "利差變化對市場的含義（2-3句）"
  }},
  "credit_conditions": "企業信貸條件和發債環境分析（3-4句）",
  "stress_signals": "信貸市場壓力訊號（有則列出，無則說明目前無明顯壓力）",
  "leading_indicator": "信貸市場作為股市領先指標的當前讀數（2-3句）",
  "risk_flags": ["信貸市場風險訊號1", "風險2"]
}}

注意事項：
1. 如果有提供即時 HYG/LQD 數據，優先使用那些數據填入 spread_data
2. spread_direction 必須明確判斷方向
"""

LIQUIDITY_PROMPT = """
以下是「流動性週報」主題的本週搜尋結果：

{news_text}

{extra_context}

輸出以下 JSON 結構（繁體中文）：

{{
  "theme": "流動性週報",
  "week_summary": "本週流動性環境一句話總結（30字以內）",
  "nfci": {{
    "latest_value": "NFCI最新值",
    "prev_week": "上週值",
    "week_change": "週變化",
    "4week_trend": "4週趨勢",
    "interpretation": "NFCI解讀（3-4句）",
    "historical_context": "歷史位置（2句）"
  }},
  "fed_liquidity": {{
    "balance_sheet": "Fed資產負債表週變化",
    "rrp": "隔夜逆回購餘額和趨勢",
    "reserves": "銀行準備金狀況"
  }},
  "liquidity_signal": "綜合流動性訊號（3-4句）",
  "nq_implication": "對NQ100的直接影響（2-3句）",
  "risk_flags": ["流動性風險訊號1", "風險2"]
}}

注意事項：
1. 如果有提供即時 NFCI 數據，優先使用那些數據填入 nfci 區塊
2. nfci.interpretation 必須說明正數代表收緊、負數代表寬鬆
"""

THEME_PROMPTS = {
    "earnings": EARNINGS_PROMPT,
    "options": OPTIONS_PROMPT,
    "commodities": COMMODITIES_PROMPT,
    "central_bank": CENTRAL_BANK_PROMPT,
    "credit": CREDIT_PROMPT,
    "liquidity": LIQUIDITY_PROMPT,
}


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


def process_weekly_theme(
    theme_key: str,
    theme_name: str,
    raw_news: list[dict],
    extra_context: str = "",
) -> dict:
    """Process one weekly theme and return structured JSON."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    news_text = _build_news_text(raw_news)

    prompt_template = THEME_PROMPTS.get(theme_key, GENERIC_PROMPT)
    user_prompt = prompt_template.format(
        theme_name=theme_name,
        news_text=news_text,
        extra_context=extra_context,
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

    _validate(data, theme_key, theme_name)

    print(f"  → [{theme_key}] done")

    return data


def _validate(data: dict, theme_key: str, theme_name: str) -> None:
    data.setdefault("theme", theme_name)
    data.setdefault("week_summary", "")
    data.setdefault("risk_flags", [])

    if theme_key == "earnings":
        data.setdefault("has_earnings", False)
        data.setdefault("earnings_results", [])
        data.setdefault("sector_trends", "")
        data.setdefault("next_week_earnings", [])
    elif theme_key == "options":
        data.setdefault("vix_data", {})
        data.setdefault("put_call", {})
        data.setdefault("skew_positioning", "")
        data.setdefault("gamma_environment", "")
        data.setdefault("key_levels", [])
        data.setdefault("nq_signal", "")
    elif theme_key == "commodities":
        data.setdefault("energy", {})
        data.setdefault("metals", {})
        data.setdefault("agriculture", "")
        data.setdefault("macro_signal", "")
        data.setdefault("next_week_catalysts", [])
    elif theme_key == "central_bank":
        data.setdefault("fed", {})
        data.setdefault("other_cb", [])
        data.setdefault("rate_market", "")
        data.setdefault("nq_implication", "")
        data.setdefault("next_week_events", [])
    elif theme_key == "credit":
        data.setdefault("spread_data", {})
        data.setdefault("credit_conditions", "")
        data.setdefault("stress_signals", "")
        data.setdefault("leading_indicator", "")
    elif theme_key == "liquidity":
        data.setdefault("nfci", {})
        data.setdefault("fed_liquidity", {})
        data.setdefault("liquidity_signal", "")
        data.setdefault("nq_implication", "")
    else:
        # Generic themes
        data.setdefault("signal_change", "")
        data.setdefault("deep_analysis", [])
        data.setdefault("earnings_calls", [])
        data.setdefault("analyst_views", [])
        data.setdefault("watchlist_impact", "")
        data.setdefault("next_week_catalysts", [])

        for item in data.get("deep_analysis", []):
            item.setdefault("title", "")
            item.setdefault("content", "")
            item.setdefault("evidence", [])
            item.setdefault("implication", "")

        for item in data.get("earnings_calls", []):
            item.setdefault("company", "")
            item.setdefault("key_quotes", "")
            item.setdefault("what_it_means", "")

        for item in data.get("analyst_views", []):
            item.setdefault("firm", "")
            item.setdefault("view", "")
            item.setdefault("target_change", "")
