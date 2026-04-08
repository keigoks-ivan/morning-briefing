# CHANGELOG — morning-briefing

格式：每次 push 後手動或讓 Claude Code 補一筆

---

## 2026-04-04

### Screener 系統完成
- 新增 screener/ 目錄（screener.py、excel_exporter.py、main.py）
- RS Score 升級：三個時間維度（1w/4w/13w）+ 趨勢方向加分
- VCP Score 升級：局部高低點識別 + 回撤幅度遞減 + 量能遞減
- Excel 附件：三個 sheet + 條件格式（紅白綠漸層）
- GitHub Pages：docs/screener/index.html + history/{date}.json
- 排名變化對比：↑↓ 新進
- 產業分類：從 Watchlist_Tickers_CIK.xlsx 讀取
- 週末不跑（weekday < 5）
- Screener 失敗日報繼續跑（try/except 保護）

### 文件系統完成
- 新增 SYSTEM_BLUEPRINT.md（完整系統藍圖，含設計決策）
- 更新根目錄 CLAUDE.md（整體規則 + Screener 規則）
- 更新 briefing/CLAUDE.md（程式碼細節 + 週報規則）
- 新增 Watchlist_Tickers_CIK.xlsx（396支，含產業分類）

---

## 2026-03-28

### Screener 初版
- 新增 screener/screener.py：RS Score（63日百分位）+ Contraction Score
- 新增 screener/excel_exporter.py：基本 Excel 輸出
- 新增 screener/main.py：主流程
- 測試通過：376 支有效標的

---

## 2026-03-26

### 週報系統
- 新增 weekly_main.py、weekly_fetcher.py、weekly_processor.py、weekly_template.py
- 十個主題：central_bank → liquidity → credit → options → ai_industry → semiconductor → earnings → macro → commodities → black_swan
- 情緒歷史：8週週線，vvix_peak_weeks_ago >= 2

---

## 2026-03-24

### 市場數據大幅升級
- 情緒歷史趨勢：VIX/VVIX/SKEW/VIX9D 5日歷史 + 趨勢方向 + 見頂天數
- 第二層趨勢：HYG/DXY/10Y/黃金/BTC/RSP_SPY/IWM_SPY 方向字串
- market_pulse 升級為三層推論框架（歷史類比 + 新模式雙軌）
- implied_trends 升級：4個訊號，2週到3個月視野，引用 sentiment_history
- 新增 Sector ETF 動態選池（選3個）
- 新增原物料動態池（選2個）

---

## 2026-03-23

### 日報多頁式架構
- html_template.py 拆成7個頁面（index/news/geo/tech/trends/misc/screener）
- Tab 導覽列
- Email 只寄首頁 + 6個連結按鈕

---

## 2026-03-21

### 系統初版上線
- 從 Tavily 換到 Perplexity（search_recency_filter: "day"）
- ThreadPoolExecutor max_workers=8 並行查詢
- Claude API streaming（max_tokens=32000）
- Render Cron → trigger.py → GitHub Actions
- Resend Email 寄送
