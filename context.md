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

三個子系統：
1. 日報：每天台灣時間 05:55 自動跑，research.investmquest.com/briefing/
2. 週報：每週日台灣時間 05:55，research.investmquest.com/weekly/
3. RS+VCP Screener：跟日報一起跑，Top 30 Email + Excel 附件

技術棧：Python + Perplexity API + yfinance + FRED + Claude API（streaming）+ Resend + GitHub Pages

完整系統藍圖在 repo 根目錄的 SYSTEM_BLUEPRINT.md。

---

## 工作環境

- Mac Mini（主力）和 MacBook Pro（次要），git 同步
- Claude Code 作為執行代理，我生成指令 → Claude Code 執行 → git push
- 兩台 Mac 的 repo 路徑：
  /Users/ivanchang/Desktop/morning-briefing/morning-briefing/

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

2026-04-04：
- Screener 系統完成（RS 三時間維度 + VCP 結構評分）
- 文件系統完成（SYSTEM_BLUEPRINT.md、CLAUDE.md、briefing/CLAUDE.md）
- Watchlist_Tickers_CIK.xlsx 已放進 repo 根目錄
- SYSTEM_BLUEPRINT.md 已推上 GitHub
- 待完成：觸發一次完整 daily_briefing workflow 整合測試
- 待完成：新聞整理區塊換 Gemini Flash（選項，省 ~$3.5/月）
- 待完成：台股 Screener（0050 + 中型100 + 富櫃50）
