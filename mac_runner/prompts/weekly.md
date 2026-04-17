# Task: Weekly Deep Report (10 Themes)

You produce a comprehensive weekly financial + macro + industry report covering 10 themes. Output ONE JSON object containing all themes — the orchestrator splits it to per-theme JSON files afterwards.

## Context

**FIRST, Read `/tmp/raw_data.json`.** For weekly mode, it contains:
- `market_data`: weekly bars (period=60d, 1wk interval), sentiment_history 8 weeks
- `market_data.second_layer_trends`: weekly trend direction of HYG/DXY/gold/BTC etc.
- `moneydj_news`: past 7 days local news

## Time window

Past 7 days (本週 + 前 1-2 天). 如果某個主題 7 天內沒大事，說明無重大事件即可；不要硬湊。

## Research

Use WebSearch + WebFetch. Whitelist same as news.md (Bloomberg/Reuters/FT/WSJ/DIGITIMES/SemiAnalysis/Nikkei/etc.). Blacklist same.

For each theme, ~3-5 web searches focused on that theme. Cite specific numbers and sources.

## Analysis style

- Think SemiAnalysis / DIGITIMES-level depth: 有觀點、有數字、有邏輯鏈，不是新聞摘要堆砌
- Identify structural changes behind surface news
- Every claim backed by specific data
- Clearly state what changed vs last week
- Conclusions that matter for investment decisions

## Theme list — output all 10

All themes share these default fields:
- `theme`: theme display name
- `week_summary`: 本週最重要訊號（≤30 字）
- `risk_flags`: list of risk warnings

### 1. central_bank 央行政策追蹤
```
{
  "theme": "央行政策追蹤",
  "week_summary": "...",
  "fed": {"key_statements": "...", "rate_probability": "...", "next_meeting": "...", "hawkish_dovish_shift": -3 to 3},
  "other_cb": [{"bank": "...", "action": "...", "implication": "..."}],
  "rate_market": "3-4 句",
  "nq_implication": "2-3 句",
  "next_week_events": ["...", "..."],
  "risk_flags": ["...", "..."]
}
```

### 2. liquidity 流動性週報
```
{
  "theme": "流動性週報",
  "week_summary": "...",
  "rrp": "RRP 週變化（含數字）",
  "tga": "TGA 週變化",
  "reserves": "銀行準備金週變化",
  "nfci": {"value": "...", "interpretation": "正收緊/負寬鬆"},
  "liquidity_signal": "綜合解讀（3-4 句）",
  "nq_implication": "2-3 句",
  "risk_flags": ["..."]
}
```

### 3. credit 信貸市場週報
```
{
  "theme": "信貸市場週報",
  "week_summary": "...",
  "spread_data": {"hyg_weekly_return": "...", "lqd_weekly_return": "...", "hyg_lqd_ratio_change": "...", "spread_direction": "擴大|收窄|持平", "interpretation": "2-3 句"},
  "credit_conditions": "3-4 句",
  "stress_signals": "...",
  "leading_indicator": "2-3 句",
  "risk_flags": ["..."]
}
```

### 4. options 選擇權市場情緒 (includes weekly_sentiment_analysis)
```
{
  "theme": "選擇權市場情緒",
  "week_summary": "...",
  "vix_data": {"vix_spot": "...", "vix_3m": "...", "term_structure": "contango|backwardation", "vvix": "...", "week_change": "..."},
  "put_call": {"qqq_ratio": "...", "trend": "上升|下降|持平", "signal": "偏多|偏空|中性", "interpretation": "2 句"},
  "skew_positioning": "3-4 句",
  "gamma_environment": "2-3 句",
  "key_levels": ["支撐1", "壓力1", "關鍵位"],
  "nq_signal": "2-3 句明確方向",
  "weekly_sentiment_analysis": {
    "stage": "第一階段|第二階段|第三階段|第四階段|無明確訊號",
    "stage_name": "暴風雨前的寧靜|崩盤啟動|落底訊號浮現|反轉確立|正常市場",
    "week_vix_change": "1 句含週漲跌",
    "week_vvix_change": "1-2 句，含今日值、週趨勢、距峰值週數、較峰值回落幅度",
    "week_skew_change": "1 句",
    "week_credit_check": "1 句",
    "week_cross_asset": "1 句",
    "reliability": "高|中|低",
    "reliability_reason": "1 句",
    "week_conclusion": "2 句，有明確立場和下週展望"
  },
  "risk_flags": ["..."]
}
```

Weekly phase judgment is stricter than daily. Phase 3 requires VVIX peaked ≥ 2 weeks ago (vs ≥ 2 days daily).

### 5. ai_industry AI 產業發展
```
{
  "theme": "AI 產業發展",
  "week_summary": "...",
  "major_events": [{"event": "...", "companies": ["..."], "significance": "..."}],
  "funding_ma": "本週融資與併購動態",
  "tech_progress": "本週技術突破",
  "industry_signal": "對 AI 產業結構的影響（3-4 句）",
  "risk_flags": ["..."]
}
```

### 6. semiconductor 半導體供應鏈
```
{
  "theme": "半導體供應鏈",
  "week_summary": "...",
  "fab_capacity": "TSMC/Samsung/Intel 產能與利用率",
  "inventory": "DRAM/NAND 庫存狀況",
  "pricing": "HBM/先進封裝定價",
  "geopolitical": "美中晶片戰進展",
  "downstream_demand": "下游需求訊號",
  "key_developments": ["...", "..."],
  "risk_flags": ["..."]
}
```

### 7. earnings 財報季追蹤
```
{
  "theme": "財報季追蹤",
  "week_summary": "...",
  "has_earnings": true,
  "earnings_results": [{"ticker": "...", "company": "...", "result_tag": "beat|miss|mixed", "key_numbers": "...", "key_takeaways": "..."}],
  "sector_trends": "本週財報顯示的產業趨勢（3-4 句）",
  "next_week_earnings": [{"ticker": "...", "date": "YYYY-MM-DD", "importance": "high|medium"}],
  "risk_flags": ["..."]
}
```

### 8. macro 全球景氣狀況
```
{
  "theme": "全球景氣狀況",
  "week_summary": "...",
  "us_data": "本週美國關鍵數據",
  "europe_china": "歐元區與中國數據",
  "inflation_labor": "通膨與勞動市場",
  "recession_signal": "衰退領先指標當前狀態",
  "risk_flags": ["..."]
}
```

### 9. commodities 能源與大宗商品
```
{
  "theme": "能源與大宗商品",
  "week_summary": "...",
  "energy": {"oil_analysis": "3-4 句", "key_drivers": ["..."], "opec_update": "...", "nat_gas": "2 句"},
  "metals": {"gold_analysis": "2-3 句", "industrial_metals": "2-3 句", "key_signal": "..."},
  "agriculture": "2 句，無則空",
  "macro_signal": "2-3 句",
  "risk_flags": ["..."],
  "next_week_catalysts": ["...", "..."]
}
```

### 10. black_swan 黑天鵝與灰犀牛
```
{
  "theme": "黑天鵝與灰犀牛",
  "week_summary": "...",
  "gray_rhinos": [{"risk": "...", "update": "本週動向", "probability": "..."}],
  "black_swans": "本週新浮現的黑天鵝（若無則空字串）",
  "risk_flags": ["..."]
}
```

## Plus top-level weekly fields

```
{
  "week_theme": "本週主軸（≤20 字）",
  "weekly_market_pulse": {"cross_asset_signals": [...], "dominant_theme": "...", "hidden_risk": "...", "hidden_opportunity": "...", "key_level_to_watch": "...", "historical_analog": "...", "new_pattern": "..."},
  "weekly_sentiment_analysis": {...},  // 與 options 內的同欄位一致，方便頂層快取

  "central_bank": {...},
  "liquidity": {...},
  "credit": {...},
  "options": {...},
  "ai_industry": {...},
  "semiconductor": {...},
  "earnings": {...},
  "macro": {...},
  "commodities": {...},
  "black_swan": {...}
}
```

## Output

ONE valid JSON object with all fields above. No markdown fences, no prose, no emoji.

Traditional Chinese throughout; tickers/numbers/terms English.
