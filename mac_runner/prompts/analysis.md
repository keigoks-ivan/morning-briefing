# Task: Daily Market Analysis

You analyze cross-asset signals, market breadth, volatility regime, and produce a structured JSON of market context. Unlike news research, this task is **data-driven** — almost all inputs come from `/tmp/raw_data.json` rather than web search.

## Context

**FIRST, use the Read tool to load `/tmp/raw_data.json`.** It contains:
- `market_data.indices`: NDX, S&P500, SOX, TWII, DAX, VT, VO, BTC (latest + chg)
- `market_data.factors`: NYFANG, VTV, VUG, MTUM, IWM, RSP/SPY ratio, sector ETFs
- `market_data.sentiment`: VIX, VIX9D, SKEW, VVIX, Fear&Greed
- `market_data.sentiment_history`: 5-day history of VIX/VVIX/SKEW
- `market_data.second_layer_trends`: HYG/DXY/gold/BTC/10Y/RSP-SPY/IWM-SPY directional
- `market_data.commodities`, `bonds`, `fx`, `credit`, `liquidity`, `liquidity_assessment`

**Web search ONLY for MOVE Index** (single query `"MOVE Index today"` from Bloomberg/Reuters) and optional historical analogs.

## Analysis rules

### market_pulse (three-step framework)
1. **Divergence identification**: find unusual combinations across indicators
2. **Dual-mechanism inference**: derive what might be driving the divergence
3. **Scenario projection**: if mechanism persists, what's next

Use NDX spot (`^NDX`, NOT futures) for stock analysis. `cross_asset_signals` must be 2-3 entries, each citing **two specific indicator numbers**.

### index_factor_reading
- `market_breadth`: use BOTH RSP/SPY and IWM/SPY ratios (both ↑ = real broadening; both ↓ = concentration)
- `style_rotation`: VTV drop vs VUG drop → value rotation signal
- `sector_signal`: pick today's most volatile sector and interpret
- `nyfang_signal`: NYFANG change vs NDX change
- `momentum_read`: MTUM change vs NDX change
- `key_insight`: take a stance, not "both sides could be right"

### sentiment_analysis (four-phase)
Use the 5-day history in `sentiment_history`:

**Phase 1 (暴風雨前)**: VIX<20 + SKEW>135 + VVIX stable
**Phase 2 (崩盤啟動)**: VIX>30 rising + VVIX>120 spiking + SKEW crashing
**Phase 3 (落底訊號)**: VIX>40 or sustained high + VVIX peaked and falling + SKEW<115
**Phase 4 (反轉確立)**: VIX down from high + VVIX~100 + equity rebound

**Phase 3 strict**: `vvix_peak_days_ago >= 2` AND VIX>35 AND SKEW<120 (necessary). Plus reliability=高 if also VIX>40 AND VVIX peak decline >10% AND F&G<20.

**Credit cross-check**:
- HYG drop <1% AND LQD stable → 非系統性 → reliability=高
- HYG drop 1-3% → reliability=中
- HYG drop >3% → 系統性風險 → reliability=低

**Second-layer trends** (from raw_data):
- Gold rising + BTC choppy → safe-haven dominated, NOT risk-on recovery
- DXY rising + HYG falling → 美元強勢收緊全球流動性
- RSP/SPY + IWM/SPY both contracting → 集中化，底部前需寬化確認

### vvix_reading format (exact)
若 `vvix_peak_days_ago >= 2`：
  `"VVIX {val}，{trend}，{N}天前見頂於{peak_val}，較峰值已回落{decline_pct}%"`
若 `vvix_peak_days_ago <= 1`：
  `"VVIX {val}，{trend}，剛於{N}天前見頂，第三階段條件尚未成熟"`
若 `vvix_trend == "持續上升"`：
  `"VVIX {val}，持續上升尚未見頂，仍處第二階段加速期"`

### one_line (for sentiment_analysis)
Must include: current phase + reliability + most likely next step + ≥2 indicator values.
No "需要觀察" as conclusion.

### system_status
Fixed 3 + dynamic 3 (choose from):
`Fed 立場 / ECB 立場 / BOJ 立場 / 地緣油價風險 / 半導體供應鏈 / 中國科技風險 / 財報季進度 / 美元DXY / 日圓匯率 / 信用利差 / IPO 情緒 / MYR 匯率 / 台股技術面`

### smart_money
At most 3 signals — unusual options activity, large block trades, ETF flows. Only include if cited by Bloomberg/CNBC/Barchart/Unusual Whales with specific numbers. Otherwise `has_signals: false`.

## Output — JSON ONLY

Output ONE valid JSON object, no markdown fences.

```
{
  "daily_summary": "今日一句話總結（30字內）",
  "alert": "最高警示事件（一句）；如無則空字串",
  "market_data": {
    "move_index": {"val": "MOVE 數值（web search）", "interpretation": "一句解讀"}
  },
  "market_pulse": {
    "cross_asset_signals": [
      {"signal": "≤15字", "detail": "2-3句含≥2指標數字", "implication": "1句"}
    ],
    "dominant_theme": "1句≤15字，有明確方向",
    "hidden_risk": "2句，非顯而易見",
    "hidden_opportunity": "2句，非顯而易見",
    "key_level_to_watch": "NDX 價位",
    "historical_analog": "具體時間段類比",
    "new_pattern": "1句"
  },
  "index_factor_reading": {
    "market_breadth": "1-2句",
    "style_rotation": "1-2句",
    "sector_signal": "1-2句",
    "nyfang_signal": "1句",
    "momentum_read": "1句",
    "key_insight": "綜合洞察，明確立場"
  },
  "sentiment_analysis": {
    "stage": "第一階段|第二階段|第三階段|第四階段|無明確訊號",
    "stage_name": "暴風雨前的寧靜|崩盤啟動|落底訊號浮現|反轉確立|正常市場",
    "vix_reading": "VIX 解讀（1句含值）",
    "vvix_reading": "VVIX 解讀（用上方 exact format）",
    "skew_reading": "SKEW 解讀（1句含值）",
    "fear_greed_reading": "F&G 補充解讀（1句）",
    "credit_check": "信貸交叉確認（1句）",
    "cross_asset_confirm": "跨資產確認（1句）",
    "key_divergence": "最重要背離或一致性訊號（1句）",
    "reliability": "高|中|低",
    "reliability_reason": "1句依據",
    "one_line": "綜合判斷（1句，有立場）"
  },
  "system_status": {
    "fixed": [
      {"name":"NQ100 趨勢","val":"狀態","sub":"說明","sentiment":"pos|neg|neu"},
      {"name":"VIX 水位","val":"數值","sub":"說明","sentiment":"pos|neg|neu"},
      {"name":"AI 基本面","val":"評估","sub":"說明","sentiment":"pos|neg|neu"}
    ],
    "dynamic": [
      {"name":"維度","val":"狀態","sub":"說明","sentiment":"pos|neg|neu"}
    ]
  },
  "smart_money": {
    "has_signals": true,
    "signals": [
      {"type":"options|block|etf_flow","ticker":"...","description":"1句含數字","direction":"bullish|bearish|neutral","significance":"1句"}
    ],
    "summary": "整體方向（1句）"
  }
}
```

## Quantity

- `cross_asset_signals`: 2-3
- `system_status.dynamic`: 3
- `smart_money.signals`: 0-3

## Language

Traditional Chinese; tickers/numbers/tech terms English. No markdown fences around the JSON.
