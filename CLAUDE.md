# CLAUDE.md — morning-briefing
# Claude Code 每次啟動自動讀取此文件

---

## 專案概述

每日財經晨報 + RS+VCP Screener 自動化系統，**全部在 GitHub Actions 上跑**。
- 日報：週一到週六台灣時間 06:15，research.investmquest.com/briefing/
- 週報：每週日台灣時間 06:15，research.investmquest.com/weekly/
- Screener：跟日報一起跑（週二到週六），Top 30 附在 Email + Excel 附件
- Repo：keigoks-ivan/morning-briefing（private）

---

## 絕對規則

1. 改完一定推上 GitHub（除非特別說不要）
2. 除非明確說要觸發，不要自動跑 workflow
3. 市場數字來自 yfinance，絕不讓 Claude API 猜測
4. 新聞區塊嚴禁行情數字（漲跌幅、指數點位）
5. Claude API 必須用 streaming（max_tokens=32000）；Claude Code headless 路徑不適用（`claude -p` 自己處理）
6. 新聞搜尋（原 Perplexity，2026-08-17 起 Claude Code＋WebSearch）與 RSS 抓取都用 ThreadPoolExecutor max_workers=8 並行
7. 分析用 NDX 現貨（^NDX），NQ 期貨已移除
8. Screener 失敗時 screener_result={} 日報繼續跑不受影響

---

## 排程設定

- 日報 GitHub cron（主，2026-08-17 起）：`15 22 * * 0-5`（UTC）= 週一到週六台灣 06:15 → daily_briefing.yml；Render cron 22:15 UTC → trigger.py → workflow_dispatch 保留為備援。workflow 內 `dedup` job 以台灣日期查當日已成功 run，兩者同日只寄一封
- 2026-06-23～2026-08-16 日報曾暫停（與 Gemini API 暫停同因），已恢復；週報仍停用（workflow disabled_manually）
- 週報 GitHub cron：15 22 * * 6（UTC）= 週日台灣 06:15 → weekly_report.yml
- 週日 trigger.py 自己判斷跳過日報（weekday==6）
- 排程不跑：git commit --allow-empty -m "resync" && git push
- GitHub Actions timeout：45 分鐘（日報，2026-08-17 由 30 分上調，因 Claude Code 主路徑重試＋逾時後要留時間給 API fallback）/ 60 分鐘（週報）

---

## AI 模型路由（2026-08-17 改制：主路徑改走 Max 訂閱）

三個 LLM 區塊（分析 / 新聞 / 財報深度）都是**三層 fallback**，任一層掛掉自動往下掉，日報不會斷：

| 層 | 走什麼 | 認證 | 花錢嗎 |
|---|---|---|---|
| **主** | Claude Code CLI headless（`claude -p`），模型 `claude-sonnet-5`，內建 3 次重試 | `CLAUDE_CODE_OAUTH_TOKEN` secret | **不花**，吃 Max 訂閱額度 |
| 備援 1 | Gemini 2.5 Pro／Flash — **已停用**（持有人 2026-08-17 決定只用月租；workflow 不傳 `GEMINI_API_KEY`，程式碼保留，要開回來取消 yml 註解即可） | — | — |
| 備援 2 | Anthropic API SDK（Sonnet 4 / 4.6）— **已停用**（2026-08-17 晚持有人明確不要走 API；workflow 不傳 `ANTHROPIC_API_KEY`，程式碼保留，要開回來取消 yml 註解） | — | — |

- ⚠ **CLI 子程序絕不能帶 `ANTHROPIC_API_KEY`**：Claude Code 同時看到 API key 與 OAuth token 時會優先用 API key 計費到 Console（2026-08-17 三次日報實際被扣款才發現）。`_cli_env()`／`_claude_search` 已把 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`／`ANTHROPIC_BASE_URL` 從子程序 env 拿掉；日後任何新的 `claude -p` 呼叫都要照做。驗證：手動跑 `claude_auth_check.yml`（30 秒，只帶 OAuth token 跑一句 haiku，印 `AUTH_OK`）。
- 月租三次都失敗的後果：新聞區塊空白；分析區塊 `_call_claude` 因缺 key 拋錯 → workflow 紅燈 → GitHub 寄失敗通知。這是刻意設計：寧可紅燈也不偷偷花錢。
- 實作在 `briefing/ai_processor.py` 的 `_call_claude_code()` + `_cc_analysis/_cc_news/_cc_earnings`；三個 dispatch 在 `process_news()` 裡。
- 換模型：設環境變數 `CLAUDE_CODE_MODEL`（別名 `sonnet` 也可）。單次逾時：`CLAUDE_CODE_TIMEOUT`（預設 900 秒，2026-08-17 由 600 上調：regime 版分析實測 440～600 秒）；思考預算 `CLAUDE_CODE_THINKING`（分析／財報預設 8000，2026-08-17 由 4000 上調給 regime 推理；新聞固定 0）。
- **OAuth token 會過期**。過期徵兆＝log 出現 `[.. / Claude Code] failed:` 三次、workflow 紅燈。修法：本機跑 `claude setup-token`，把新 token 更新到 GitHub secret。
- workflow 裡 `Install Claude Code CLI` 這步是 `continue-on-error: true`——裝不起來時分析區塊會因無備援而紅燈（見上）。
- log 印的 Claude Code `cost` 是 **API 等價參考值，不是實際帳單**（訂閱制不另計費）。
- ⚠ Max 額度與跑 DD 報告共用同一池，忙的時候會互相排擠。

**新聞素材與品質（2026-08-17 晚改制，起因＝首日輸出 36% 過期、Nvidia $500B 重複 5 次、硬湊地區新聞）**
- 素材兩層：① `RSS_FEEDS`（news_fetcher.py）約 27 個 feed 並行抓（MoneyDJ／中央社／CNBC／FT／Axios／TechCrunch／The Information／DIGITIMES／SCMP／CoinDesk／The Block 直連；Bloomberg／Reuters／TrendForce／台韓日中歐／東南亞資料中心／Fed 走 **Google News RSS `site:`／關鍵字查詢**當代理），每 feed 有條數上限與回看小時數，總上限 220，`_RSS_NOISE` 濾開獎等噪音；② `PERPLEXITY_QUERIES` 由 25 題砍到 13 題，只留「需跨來源整理」的主題（Fed／總經數據／行事曆／能源地緣／AI／半導體供應鏈／台韓／新創／機構／財報×3），Sources 只列白名單。WSJ／Nikkei 官方 RSS 已停更，不要加回。
- prompt 原則改為「寧缺勿濫」：數量全是**上限**、地區沒素材留 `[]`；`{today}`／`{cutoff_date}`（`_news_date_window()`：平日回看 2 天、週一 3 天）為硬規則；同一事件整份 JSON 只能出現一次；top_stories 前 3–5 條必須是指數部相關（tag「指數部」）；白名單擴充（AP／BBC／CNN Business／TrendForce／CoinDesk／The Block／Crunchbase／Focus Taiwan／Yonhap／Korea Herald／Caixin），黑名單加 Seeking Alpha／Yahoo 轉載／Motley Fool／Benzinga。regional_tech 的 `malaysia` 改為 `asean`（東南亞）。
- 後處理（ai_processor.py，`process_news` 內、`_validate` 前）：`_sanitize_news()`＝簡繁／錯字一對一修正表 `_ZH_FIX`、`source_date` 早於允收起始日整條丟、標題含漲跌% 整條丟、body 含行情句（`_MARKET_SENT_RE`：股價／指數／幣價／油價／ticker＋漲跌＋數字）砍該句；`_dedup_news()` 改為 token Jaccard ≥ 0.4 或「同金額＋同專名」視為同一事件，涵蓋 tech_trends／daily_deep_dive／regional_tech。log 會印 `sanitize:`／`dedup:` 統計。
- 想加 RSS：在 `RSS_FEEDS` 加一行 tuple；Google News 代理寫法見 `_GN`。想加白名單媒體：改 `GEMINI_SYSTEM_PROMPT` 白名單段，並同步該媒體到相關搜尋題目的 Sources。

**新聞搜尋層（news_fetcher.py，2026-08-17 同日改制）**：Perplexity 已停用（帳號當日全面 429，持有人決定不再付費）。所有搜尋走 `_llm_search()` → 主＝Claude Code headless `--allowed-tools WebSearch`、模型 `haiku`（最便宜，搜尋只是找資料）；備援＝Perplexity（僅在 workflow 傳 `PERPLEXITY_API_KEY` 時啟用，目前註解掉）。換模型：`NEWS_SEARCH_MODEL`；單次逾時：`NEWS_SEARCH_TIMEOUT`（預設 240 秒）。來源網址由模型在答案末尾 `SOURCES:` 區塊列出後解析。`_fetch_dynamic_deep_topics()` 是死碼（無呼叫端），仍寫死 Perplexity，勿誤用。

---

## 分析骨架：主軸先行（regime-first，2026-08-17 改制）

分析區塊（`CLAUDE_SYSTEM_PROMPT` / `CLAUDE_USER_PROMPT_TEMPLATE`）不再是「每個區塊各自解讀」，而是先立主軸再讓各區塊對主軸表態：

- JSON 頂層新增 `regime`：`call`（一句有方向的市場狀態）／`axes`（risk_appetite・liquidity・volatility 各 state＋evidence，證據要有實數）／`confirms`／`contradicts`（沒有反證要說為什麼可疑）／`falsifiers`（metric＋threshold＋meaning，具體門檻）／`for_w52_engine`（只講週線閘門與波動率環境，**不下買賣指令**）／`confidence`＋`confidence_reason`。
- `market_pulse`、`index_factor_reading`、`sentiment_analysis` 各多一個 `vs_regime`：格式「支持｜／反對｜／中性｜ ＋ 一句話」，必須把矛盾點講出來。
- 渲染：`html_template._regime_block()`（放在 alert 之後、market_strip 之前，email 與 index 頁都有）＋ `_vs_regime_line()`（三個區塊底部一行）。`_validate` 有預設值，模型漏寫時區塊直接不顯示、不炸。
- 人設已改成持有人真實系統（W52 × 自適應波動率 cap 1.5，QQQ/SMH、0050/2330），不是泛泛的「資深分析師」。中文句子標點一律全形。

---

## 檔案職責

### 日報
main.py → 日報主流程，串接所有模組
news_fetcher.py → 新聞素材（`RSS_FEEDS` 多來源 RSS＋Google News 代理；`_llm_search`：Claude Code Haiku＋WebSearch 主、Perplexity 備援）+ yfinance 行情 + FRED 流動性
ai_processor.py → 三區塊（分析/新聞/財報）並行產 JSON，含 _validate 預設值。模型路由見下「AI 模型路由」
html_template.py → JSON → HTML，所有區塊渲染函式（含多頁 tab 導航）
email_sender.py → Resend API 寄信（支援 Excel 附件）
trading_system_of_day.py → 每日交易系統（50天輪替，data/trading_systems.json）
startup_framework_of_day.py → 每日創業框架（50天輪替，data/startup_frameworks.json）

### 週報
weekly_main.py → 週報主流程
weekly_fetcher.py → 週報 Perplexity 查詢
weekly_processor.py → 週報 Gemini 2.5 Flash（Claude Sonnet fallback）分析
weekly_template.py → 週報 HTML 渲染

### Screener
screener/screener.py → RS+VCP 計算邏輯，從 Watchlist_Tickers_CIK.xlsx 讀取
screener/excel_exporter.py → Excel 輸出（條件格式、三個 sheet）
screener/main.py → Screener 主流程 + GitHub Pages 發布

### 其他
trigger.py → Render Cron → GitHub API

---

## 市場數據規則

- 所有 ticker 用 period="7d", interval="1d"
- 取 dropna() 後 iloc[-1]（最新）和 iloc[-2]（前一日）計算漲跌
- 反向指標（漲=紅）：VIX、VIX9D、VVIX、MOVE
- NDX 現貨（^NDX）用於分析，NQ 期貨已移除
- NYFANG ticker = FNGS（不是 ^NFG）
- 漲跌格式：▲/▼ X.XX%，美10Y用bps（▲/▼ Xbps）

---

## 固定指標清單

股票指數：^NDX、^GSPC、^SOX、^TWII、^GDAXI、VT、VO、BTC-USD
美股因子：FNGS、VTV、VUG、MTUM、IWM、RSP（+SPY計算比值）
市場情緒：^VIX、^VIX9D、^SKEW、^VVIX、CNN Fear&Greed、MOVE（網路搜尋，見 _llm_search）
原物料固定：BZ=F、CL=F、GC=F、SI=F、HG=F、ALI=F
原物料動態：NG=F、PA=F、PL=F、ZW=F、ZC=F、ZS=F、CC=F、KC=F、SB=F（選2個）
債券：^IRX(2Y)、^TNX(10Y)、^TYX(30Y)、TLT，10Y-2Y利差計算
外匯固定：DX-Y.NYB、JPY=X、TWD=X，動態2個
信貸：HYG、LQD、BKLN，HYG/LQD比值計算
流動性(FRED)：RRPONTSYD、NFCI、WTREGEN、WRESBAL

---

## 情緒歷史趨勢

- VIX/VVIX/SKEW/VIX9D 用 period="10d" 抓5日歷史
- 計算：趨勢方向（連續回落/持續上升/震盪）、見頂天數、峰值回落幅度
- 第三階段判斷：vvix_peak_days_ago >= 2 且 VIX > 35 且 SKEW < 120
- 第二層趨勢（只傳方向）：HYG、DXY、10Y、黃金、BTC、RSP/SPY、IWM/SPY

---

## 顏色規範

上漲：#0F6E56，下跌：#C0392B，中性：#888888
類別色塊：股票#1B3A5C、因子#7F77DD、情緒#BA7517、原物料#854F0B
債券#185FA5、外匯#534AB7、信貸#0F6E56、流動性#085041

---

## HTML 排版規則

- 全部用 table 排版（Email 客戶端相容性）
- 不用 CSS Grid 或 Flexbox
- JSON 數值用英文格式（不用中文億/兆，用 B/T）

---

## Screener 規則

- Watchlist：優先讀 Watchlist_Tickers_CIK.xlsx，找不到用硬編碼 fallback
- period="300d" 確保200MA數據足夠
- 週末不跑：weekday < 5 判斷
- Combined Score = RS×60% + VCP×40%
- Excel 三個 sheet：完整排名 / Top 30 / 說明

---

## 日報 build_html 區塊順序

1.masthead+summary 2.alert 2b._regime_block（今日主軸） 3._market_strip 4._index_factor_reading
5._sentiment_analysis 6._market_pulse 7._daily_deep_dive
8.top_stories 9.world_news 10.us_market_recap 11.macro
12.geopolitical 13.ai_industry 14.regional_tech 15.fintech_crypto
16.system_status 17.tech_trends 18.startup_news 19.smart_money
20.earnings_preview 21.implied_trends 22.fun_fact 23.today_events 24.footer

---

## 日報去重順序（最高優先級）

tech_trends → daily_deep_dive → top_stories → world_news →
macro → geopolitical → ai_industry → regional_tech →
fintech_crypto → startup_news → us_market_recap → smart_money

---

## 週報規則

- 市場週度數據：period="14d", interval="1d"，找最近完整交易週（週一到週五）第一筆和最後一筆計算週漲跌
- 情緒歷史：period="60d", interval="1wk" 抓8週週線
- 週度第三階段判斷：vvix_peak_weeks_ago >= 2（比日報更嚴格）
- VVIX 連續3週回落 = 強烈底部訊號
- Fear&Greed 只顯示當週最新值，不計算週漲跌
- FRED 數據顯示週變化，標注數據日期
- 標題用「本週主軸」

---

## 週報主題順序

central_bank → liquidity → credit → options →
ai_industry → semiconductor → earnings → macro → commodities → black_swan

---

## 週報 vs 日報差異

- 標題：「本週主軸」（不是「今日主軸」）
- 漲跌：顯示週漲跌幅（不是日漲跌）
- 情緒分析：weekly_sentiment_analysis，輸出 week_conclusion（2句）而非 one_line
- 市場脈絡：weekly_market_pulse，cross_asset_signals 引用週度數據
- 去重規則：與日報相同的優先順序

---

## 常見問題

| 問題 | 解法 |
|---|---|
| JSON 解析失敗 | max_tokens=32000，確認 streaming |
| 市場數據空白 | period="7d"，取最後兩筆有效數據 |
| 排程不跑 | 推空白 commit resync |
| Screener 掛掉 | try/except 保護，日報繼續跑 |
| GitHub Pages 不更新 | 檢查 GH_PAT 權限 |
