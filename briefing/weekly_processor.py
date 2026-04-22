"""
weekly_processor.py
-------------------
將每個主題的 Perplexity 搜尋結果送給 Gemini 2.5 Flash，生成深度週報 JSON。
失敗時 fallback 到 Claude Sonnet。
"""

import os
import json
import anthropic
from google import genai
from google.genai import types


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

weekly_sentiment_analysis 強化分析規則（用於選擇權市場情緒主題）：

【四部曲判斷邏輯】
第一階段（暴風雨前）：VIX < 20 + SKEW > 135 + VVIX 平穩
第二階段（崩盤啟動）：VIX > 30 且快速上升 + VVIX > 120 且飆升 + SKEW 急跌
第三階段（落底訊號）：VIX > 40 或維持高檔 + VVIX 已見頂開始回落 + SKEW 低於115
第四階段（反轉確立）：VIX 從高檔回落 + VVIX 回到 100 左右 + 股市反彈

【週度四部曲判斷（使用8週歷史數據）】

週度判斷更嚴格，因為週線數據消除了日內雜訊：

第三階段週度精確判斷：
必要條件：
1. VIX 本週收盤 > 35
2. VVIX 已從週高點回落 2週以上（vvix_peak_weeks_ago >= 2）
3. SKEW < 120
4. VVIX 週趨勢為「連續回落」或「高位震盪後回落」

充分條件：
5. VIX 本週收盤 > 40
6. VVIX 較峰值回落超過 15%（週度標準更嚴格）
7. Fear&Greed < 20
8. HYG 週趨勢非「持續下降」

週度判斷加強版：
- VVIX 連續3週回落 → 強烈底部訊號
- VVIX 連續3週上升 → 恐慌尚未見頂，第二階段持續
- 8週內 VIX 先升後降而 VVIX 已回落 → 典型第三階段週度確認

【假底判斷：信貸交叉確認】
- HYG 跌幅 < 1% 且 LQD 穩定 → 非系統性恐慌，可靠性「高」
- HYG 跌幅 1-3% + LQD 略跌 → 信貸壓力中等，可靠性「中」
- HYG 跌幅 > 3% + LQD 同步大跌 → 系統性信貸危機風險，可靠性「低」

【第二層週度跨資產確認】
- 黃金連續3週上升 + BTC 近2週止跌 → 底部跨資產確認強
- DXY 週趨勢由升轉平或下降 → 美元流動性壓力緩解
- RSP/SPY 週度比值止跌或回升 → 市場寬度開始改善，底部信號加強
- 黃金連續下降 → 流動性危機（拋售一切），底部訊號可靠性下降
- DXY 連續上升 + HYG 連續下降 → 美元強勢收緊全球流動性，壓力持續
- RSP/SPY 連續收縮 + IWM/SPY 連續收縮 → 市場高度集中化，底部前通常需要寬化確認
- BTC 連續上升 先於黃金和股票 → 風險偏好率先回升，底部訊號增強

【可靠性判斷矩陣】
高：信貸穩定（HYG跌<1%）+ 至少2個跨資產確認 + 非金融危機環境
中：信貸輕微壓力（HYG跌1-3%）或跨資產確認不足
低：信貸嚴重惡化（HYG跌>3%）或 系統性危機環境

【week_conclusion 要求】
- 必須引用 VVIX 的週趨勢和距峰值的週數
- 必須說明第二層指標是否提供跨資產確認
- 給出明確的下週展望，不能兩邊都說

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
  "weekly_sentiment_analysis": {{
    "stage": "第一階段/第二階段/第三階段/第四階段/無明確訊號",
    "stage_name": "暴風雨前的寧靜/崩盤啟動/落底訊號浮現/反轉確立/正常市場",
    "week_vix_change": "本週VIX變化解讀（1句，含週漲跌）",
    "week_vvix_change": "VVIX週度解讀（1-2句，必須說明：今日值、週趨勢、距峰值幾週、較峰值回落幅度）",
    "week_skew_change": "本週SKEW變化解讀（1句）",
    "week_credit_check": "本週信貸市場狀態（1句）",
    "week_cross_asset": "本週跨資產確認訊號（1句）",
    "reliability": "高/中/低",
    "reliability_reason": "可靠性依據（1句）",
    "week_conclusion": "本週情緒總結及下週展望（2句，有明確立場）"
  }},
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
    """Process one weekly theme: Gemini 2.5 Pro → Claude fallback."""
    news_text = _build_news_text(raw_news)

    prompt_template = THEME_PROMPTS.get(theme_key, GENERIC_PROMPT)
    user_prompt = prompt_template.format(
        theme_name=theme_name,
        news_text=news_text,
        extra_context=extra_context,
    )

    try:
        raw_text = _call_gemini_flash_weekly(theme_key, user_prompt)
    except Exception as e:
        print(f"  ⚠ [Gemini Flash] failed for [{theme_key}]: {e}, falling back to Claude...")
        raw_text = _call_claude_weekly(theme_key, user_prompt)

    with open(f"/tmp/weekly_{theme_key}_raw.txt", "w") as f:
        f.write(raw_text)

    # 清理 JSON
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


def _call_gemini_flash_weekly(theme_key: str, user_prompt: str) -> str:
    """呼叫 Gemini 2.5 Flash 處理週報主題"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = genai.Client(api_key=api_key)

    print(f"  → [Gemini Flash] Calling API for [{theme_key}]...")

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=WEEKLY_SYSTEM_PROMPT,
                    max_output_tokens=8192,
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
                print(f"  ⚠ [Gemini Flash] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    # Gemini 2.5 Flash: input $0.30/MTok, output $2.50/MTok
    cost = in_tok / 1_000_000 * 0.30 + out_tok / 1_000_000 * 2.50
    print(f"  → [Gemini Flash] [{theme_key}] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    return response.text


def _call_claude_weekly(theme_key: str, user_prompt: str) -> str:
    """呼叫 Claude API 處理週報主題（fallback）"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print(f"  → [Claude] Calling API for [{theme_key}] (fallback)...")
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8192,
        system=WEEKLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = msg.content[0].text.strip()

    usage = msg.usage
    cost = usage.input_tokens / 1_000_000 * 3 + usage.output_tokens / 1_000_000 * 15
    print(f"  → [Claude] [{theme_key}] tokens: in={usage.input_tokens:,} out={usage.output_tokens:,} cost=${cost:.4f}")

    return raw_text


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
        data.setdefault("weekly_sentiment_analysis", {
            "stage": "無明確訊號",
            "stage_name": "正常市場",
            "week_vix_change": "",
            "week_vvix_change": "",
            "week_skew_change": "",
            "week_credit_check": "",
            "week_cross_asset": "",
            "reliability": "中",
            "reliability_reason": "",
            "week_conclusion": ""
        })
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
