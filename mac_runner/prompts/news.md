# Task: Daily Financial + Tech + Geopolitical News Research

You research the past 24 hours of US / global financial, tech, AI, startup, and geopolitical news, and produce a structured JSON summary.

## Context

First, read `/tmp/raw_data.json` (via the Read tool) to see:
- `date_tw`, `date_us_et` — today's dates
- `market_data` — reference for what tickers / sectors matter
- `moneydj_news` — pre-fetched TW local news, may be reused in regional_tech.taiwan

## Time window

Past 24 hours. Anything older than 24 hours — EXCLUDE.

## Research workflow

Use WebSearch + WebFetch against this whitelist ONLY:

**一線財經**：Bloomberg, Reuters, Financial Times, WSJ, CNBC, Barron's, The Economist, Axios, Politico
**科技/AI**：TechCrunch, The Information, Wired, Ars Technica, MIT Technology Review
**半導體**：DIGITIMES, SemiAnalysis, Semiconductor Engineering, EE Times, Nikkei Asia
**亞洲**：Nikkei Asia, South China Morning Post, Taiwan News
**地緣/智庫**：Foreign Affairs, RAND, Brookings
**官方**：Fed, ECB, BOJ, BIS, IMF, SEC, FRED
**研究機構**：Gartner, IDC, McKinsey, Goldman Sachs, JP Morgan, Barchart, MoneyDJ

**永不使用**：YouTube, TikTok, Twitter/X, Reddit, Facebook, Instagram, 個人部落格, Medium (個人), Substack (非已知媒體), PR Newswire, BusinessWire, GlobeNewswire, WilmerHale, InfoQ

### Research plan (execute in order)

1. **Top stories**: `"top US financial news [date]"` + `"Fed policy today"` + `"major market-moving events [date]"`
2. **Macro**: `"macroeconomic data releases [date]"` + `"central bank decisions this week"`
3. **AI industry**: `"AI industry news [date]"` + `"AI infrastructure investment"` + `"AI model release this week"`
4. **Semiconductors**: `"TSMC news [date]"` + `"Nvidia AMD semiconductor news"` + `"ASML chip news"`
5. **Regional tech** (Taiwan, Japan, US, Malaysia, Korea, China, Europe): per-region tech+semi search
6. **Fintech/Crypto**: `"Bitcoin Ethereum news [date]"` + `"fintech news [date]"`
7. **Geopolitical**: `"Middle East news [date]"` + `"US-China tensions [date]"` + `"Taiwan Strait [date]"`
8. **World news**: major international developments
9. **Startup**: `"AI startup funding [date]"` + `"defense tech VC [date]"`
10. **US market recap**: yesterday's US session — major earnings RELEASED, beat/miss, stock moves
11. **Today events**: calendar of Fed speeches / data releases / earnings due in next 24h
12. **Deep dive topics (fixed)**: semiconductor supply chain today + AI architecture research today
13. **Deep dive topics (dynamic)**: first WebSearch "most important market-moving topics today", pick top 2-3, research each
14. **Fun fact**: one finance-related trivia connected to today's news

## Dedup (critical)

Same event → appears in ONLY ONE section. Priority order (higher = wins):
1. tech_trends
2. daily_deep_dive
3. top_stories
4. world_news
5. macro
6. geopolitical
7. ai_industry
8. regional_tech
9. fintech_crypto
10. startup_news

These are separate: **ai_industry**, **fintech_crypto**, **startup_news**, **regional_tech** have independent quotas — even if top_stories already has AI news, ai_industry MUST still output 4-6 unique AI angles.

## Content rules

- Traditional Chinese (繁體中文). Forbid simplified: 規範≠规范, 晶片≠芯片, 網路≠网络, 數據≠数据, 訊息≠信息, 記憶體≠内存, 軟體≠软件
- Company names / tickers / tech terms stay English
- Numbers in English format: $1.42T not $1.42兆
- **News sections are event-driven, NOT market data**: NEVER include stock price % changes, index levels, volume, technical chart talk. Those go in `market_pulse` / `index_factor_reading` (handled by analysis.md)
- Exclude ESG / sustainability / green-energy-only stories
- Every story must have a concrete source URL from the whitelist
- `source_date` format: YYYY-MM-DD

## Output — JSON ONLY

Output ONE valid JSON object, no markdown fences, no explanation.

```
{
  "top_stories": [
    {"headline": "≤30字", "body": "2-3句，含具體數字", "tag": "分類", "tag_type": "macro|geo|tech|cb", "source": "媒體", "source_date": "YYYY-MM-DD", "importance": "high|medium"}
  ],
  "macro": [{"headline": "≤25字", "body": "2句", "tag": "...", "source": "...", "source_date": "YYYY-MM-DD", "importance": "high|medium"}],
  "ai_industry": [{"headline": "≤25字", "body": "2句+數字+公司", "tag": "...", "source": "...", "source_date": "YYYY-MM-DD", "importance": "high|medium"}],
  "regional_tech": {
    "taiwan":   [{"headline":"...", "body":"1-2句", "source":"...", "source_date":"YYYY-MM-DD", "importance":"high|medium"}],
    "japan":    [...], "us": [...], "malaysia": [...], "korea": [...], "china": [...], "europe": [...]
  },
  "fintech_crypto": [{"headline":"...","body":"2句","tag":"Fintech|Crypto|DeFi|Stablecoin","source":"...","source_date":"YYYY-MM-DD","importance":"high|medium"}],
  "geopolitical": [{"headline":"...","body":"2句+市場影響","region":"中東|台海|中美|其他","source":"...","source_date":"YYYY-MM-DD","importance":"high|medium"}],
  "world_news": [{"headline":"≤30字","body":"2-3句","region":"...","tag":"...","source":"...","source_date":"YYYY-MM-DD","importance":"high|medium"}],
  "startup_news": [{"headline":"≤35字","summary":"1-2句","tag":"...","tag_type":"defense|ai|health|fintech|other","accent":"defense|ai_gov|health|fintech|cyber|other","source":"...","source_date":"YYYY-MM-DD","importance":"high|medium"}],
  "tech_trends": [
    {"label":"子領域","label_type":"robotics|arch|infra_ai|science|other","headline":"≤40字","summary":"2-3句","sub_items":[{"key":"...","val":"..."},{"key":"...","val":"..."},{"key":"...","val":"..."}],"chips":[{"text":"...","type":"up|risk|watch|new|amber"}],"source":"...","source_date":"YYYY-MM-DD"}
  ],
  "daily_deep_dive": [
    {"theme":"...","theme_type":"semiconductor|ai_arch|liquidity|energy|spotlight","headline":"≤25字","situation":"4-6句","key_data":[{"metric":"...","value":"...","change":"...","context":"..."}],"deep_analysis":"4-6句","structural_signal":"2-3句","bull_case":"2句","bear_case":"2句","implication":"2-3句","source":"...","source_date":"YYYY-MM-DD"}
  ],
  "us_market_recap": {
    "has_events": true,
    "earnings": [{"company":"...","ticker":"...","beat_miss":"beat|miss|in-line","key_line":"含數字一句","after_hours_move":"股價反應","why_it_matters":"1句","session":"pre-market|market|after-hours"}],
    "other_events": [],
    "summary": "整體一句話"
  },
  "today_events": [{"time":"...","event":"...","note":"..."}],
  "fun_fact": {"title":"≤20字","content":"3-4句","connection":"跟今日新聞的關聯"}
}
```

## Minimum quantities

- `top_stories` ≥ **15**（必要！不可少）
- `macro` 4-6
- `ai_industry` 4-6
- `regional_tech.*` 每區 2-3（共 7 區）
- `fintech_crypto` 3-5
- `geopolitical` 3-5
- `world_news` 3（固定）
- `startup_news` 4-5
- `tech_trends` 5-6（每個 sub_items 固定 3 個）
- `daily_deep_dive` 2（1 固定主題 + 1 今日動態主題，從搜尋結果中選）
- `today_events` 2-5
- `fun_fact` 必填 title + content + connection

If a category has less than the minimum after research, expand search; do not produce fewer items.
