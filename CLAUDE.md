# CLAUDE.md — morning-briefing

## 專案概述
每日財經晨報自動化系統。
- 日報：每天台灣時間 05:55，research.investmquest.com/briefing/
- 週報：每週日台灣時間 05:55，research.investmquest.com/weekly/
- repo：keigoks-ivan/morning-briefing（private）

## 絕對規則
1. 改完一定推上 GitHub（除非特別說不要）
2. 除非明確說要觸發，不要自動跑 workflow
3. 市場數字來自 yfinance，絕不讓 Claude API 猜測
4. 新聞區塊嚴禁行情數字（漲跌幅、指數點位）
5. Claude API 必須用 streaming（max_tokens=32000）
6. Perplexity 查詢用 ThreadPoolExecutor max_workers=8 並行

## 排程設定
- 日報 cron：55 21 * * *（UTC）= 台灣 05:55
- 週報 cron：55 21 * * 0（UTC）= 週日台灣 05:55
- 排程不跑時：git commit --allow-empty -m "resync" && git push
- GitHub Actions timeout：30 分鐘
- 觸發方式：Render Cron Job → trigger.py → GitHub API workflow_dispatch

## 檔案結構
trigger.py → Render Cron → GitHub API
.github/workflows/daily_briefing.yml → workflow_dispatch only
.github/workflows/weekly_report.yml → cron + workflow_dispatch
briefing/ → 日報和週報所有 Python 程式碼
docs/ → GitHub Pages 發布目錄

## GitHub Secrets
ANTHROPIC_API_KEY, PERPLEXITY_API_KEY, RESEND_API_KEY, TO_EMAIL, GH_PAT

## 成本概覽
Claude API 日報 ~$6/月，週報 ~$4/月，Perplexity ~$1.5/月，合計 ~$11.5/月
