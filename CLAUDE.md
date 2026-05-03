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
5. Claude API 必須用 streaming（max_tokens=32000）
6. Perplexity 查詢用 ThreadPoolExecutor max_workers=8 並行
7. 分析用 NDX 現貨（^NDX），NQ 期貨已移除
8. Screener 失敗時 screener_result={} 日報繼續跑不受影響

---

## 排程設定

- 日報 Render cron：22:15 UTC（每天）= 台灣 06:15 → trigger.py → GitHub API workflow_dispatch → daily_briefing.yml
- 週報 GitHub cron：15 22 * * 6（UTC）= 週日台灣 06:15 → weekly_report.yml
- 週日 trigger.py 自己判斷跳過日報（weekday==6）
- 排程不跑：git commit --allow-empty -m "resync" && git push
- GitHub Actions timeout：30 分鐘（日報）/ 60 分鐘（週報）

---

## 檔案職責

### 日報
main.py → 日報主流程，串接所有模組
news_fetcher.py → Perplexity 查詢 + yfinance 行情 + FRED 流動性
ai_processor.py → Gemini 2.5 Pro（分析）+ Gemini 2.5 Flash（新聞）+ Claude fallback，輸出 JSON，含 _validate 預設值
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
市場情緒：^VIX、^VIX9D、^SKEW、^VVIX、CNN Fear&Greed、MOVE（Perplexity）
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

1.masthead+summary 2.alert 3._market_strip 4._index_factor_reading
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
