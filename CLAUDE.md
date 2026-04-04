# CLAUDE.md — morning-briefing
# Claude Code 每次啟動自動讀取此文件

---

## 專案概述

每日財經晨報 + RS+VCP Screener 自動化系統。
- 日報：週一到週六台灣時間 05:55，research.investmquest.com/briefing/
- 週報：每週日台灣時間 05:55，research.investmquest.com/weekly/
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

- 日報 cron：55 21 * * *（UTC）= 台灣 05:55
- 週報 cron：55 21 * * 0（UTC）= 週日台灣 05:55
- 排程不跑：git commit --allow-empty -m "resync" && git push
- GitHub Actions timeout：30 分鐘
- 觸發方式：Render Cron Job → trigger.py → GitHub API workflow_dispatch

---

## 檔案職責

### 日報
main.py → 日報主流程，串接所有模組
news_fetcher.py → Perplexity 查詢 + yfinance 行情 + FRED 流動性
ai_processor.py → Claude API streaming，輸出 JSON，含 _validate 預設值
html_template.py → JSON → HTML，所有區塊渲染函式
email_sender.py → Resend API 寄信（支援 Excel 附件）

### 週報
weekly_main.py → 週報主流程
weekly_fetcher.py → 週報 Perplexity 查詢
weekly_processor.py → 週報 Claude 分析
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
- 情緒歷史：VIX/VVIX/SKEW/VIX9D 用 period="10d" 抓5日歷史
- 反向指標（漲=紅）：VIX、VIX9D、VVIX、MOVE
- NYFANG ticker = FNGS（不是 ^NFG）
- 漲跌格式：▲/▼ X.XX%，美10Y用bps

---

## 顏色規範

上漲：#0F6E56，下跌：#C0392B，中性：#888888
類別色塊：股票#1B3A5C、因子#7F77DD、情緒#BA7517、原物料#854F0B
債券#185FA5、外匯#534AB7、信貸#0F6E56、流動性#085041

---

## Screener 規則

- Watchlist：優先讀 Watchlist_Tickers_CIK.xlsx，找不到用硬編碼 fallback
- period="300d" 確保200MA數據足夠
- 週末不跑：weekday < 5 判斷
- Combined Score = RS×60% + VCP×40%
- Excel 三個 sheet：完整排名 / Top 30 / 說明

---

## 週報規則

- 情緒歷史：period="60d", interval="1wk" 抓8週週線
- 第三階段判斷：vvix_peak_weeks_ago >= 2
- 漲跌顯示週漲跌幅
- 標題用「本週主軸」

---

## HTML 排版規則

- 全部用 table 排版（Email 客戶端相容性）
- 不用 CSS Grid 或 Flexbox
- JSON 數值用英文格式（不用中文億/兆，用 B/T）

---

## 日報去重順序

tech_trends → daily_deep_dive → top_stories → world_news →
macro → geopolitical → ai_industry → regional_tech →
fintech_crypto → startup_news → us_market_recap → smart_money

---

## 常見問題

| 問題 | 解法 |
|---|---|
| JSON 解析失敗 | max_tokens=32000，確認 streaming |
| 市場數據空白 | period="7d"，取最後兩筆有效數據 |
| 排程不跑 | 推空白 commit resync |
| Screener 掛掉 | try/except 保護，日報繼續跑 |
| GitHub Pages 不更新 | 檢查 GH_PAT 權限 |
