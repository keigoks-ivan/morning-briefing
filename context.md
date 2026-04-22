# context.md — 跨機器工作前貼進 Claude.ai chat

把這份文件的內容貼在新對話的第一則訊息即可。

---

## 我是誰

全職系統性投資者，12年買方經驗。
在 claude.ai 用 Claude 協助開發個人投資研究平台。
主要開發工具：Claude Code（在 Mac 上執行）。

---

## 現在在做的專案

**keigoks-ivan/morning-briefing**（private repo）

三個子系統，**全部在 GitHub Actions 上跑**：
1. 日報：每天台灣時間 06:15 自動跑，research.investmquest.com/briefing/
2. 週報：每週日台灣時間 06:15，research.investmquest.com/weekly/
3. RS+VCP Screener：跟日報一起跑，Top 30 Email + Excel 附件

技術棧：Python + Perplexity + yfinance + FRED + Gemini 2.5（Claude fallback）+ Resend + GitHub Pages

完整系統藍圖在 repo 根目錄的 SYSTEM_BLUEPRINT.md。

---

## 工作環境

- Mac Mini（主力）和 MacBook Pro（次要），git 同步
- Claude Code 作為執行代理，我生成指令 → Claude Code 執行 → git push
- Repo 本機路徑：
  /Users/ivanchang/morning-briefing/
- 實際執行全部在 GitHub Actions（不依賴本機 Mac）

---

## 這次要做的事

（在這裡填入本次工作目標）

---

## 注意事項

- 改完一定推上 GitHub（除非特別說不要）
- 除非明確說要觸發，不要自動跑 workflow
- 市場數字來自 yfinance，不讓 Claude API 猜測
- 分析用 NDX 現貨（^NDX），NQ 期貨已移除
- NYFANG ticker = FNGS（不是 ^NFG）
- Screener 失敗時日報繼續跑（try/except 保護）
- 週末不跑 Screener（weekday < 5 判斷）
- 排程不跑時：git commit --allow-empty -m "resync" && git push

---

## 上次停在哪

（每次工作結束前更新這裡）

2026-04-22：
- 拆除 Mac runner 整條（mac_runner/、launchd plist、try_load_mac_data、send_fallback_alert 全部移除）
- 日報、週報完全跑在 GitHub Actions 上，不再依賴本機 Mac
- weekly_processor 從 Gemini Pro 換 Gemini Flash
- 修了 weekly_report.yml 漏傳 GEMINI_API_KEY 的 bug
- 待完成：台股 Screener（0050 + 中型100 + 富櫃50）
