# Morning Financial Briefing

每日 06:00 台灣時間自動發送的財經晨報系統。

## 架構

```
GitHub Actions (cron: UTC 22:00)
  → briefing/news_fetcher.py   Tavily API 搜尋新聞
  → briefing/ai_processor.py   Claude Sonnet 整理成結構化 JSON
  → briefing/html_template.py  生成 HTML Email
  → briefing/email_sender.py   SendGrid 發送
```

## 本機測試

1. 複製環境變數範本：
```bash
cp .env.example .env
# 填入你的 API Keys
```

2. 安裝套件：
```bash
pip install -r requirements.txt
```

3. 執行：
```bash
cd briefing
python main.py
```

## GitHub Secrets 設定

在 Repository → Settings → Secrets and variables → Actions 新增：

| 名稱 | 說明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console 取得 |
| `TAVILY_API_KEY` | Tavily Dashboard 取得 |
| `SENDGRID_API_KEY` | SendGrid API Keys 取得 |
| `TO_EMAIL` | 收件 Email（需完成 Sender Verification）|

## 每月成本估算

| 項目 | 費用 |
|---|---|
| Claude Sonnet API | ~$2.84/月 |
| Tavily Search | $0（免費額度 1000次/月）|
| SendGrid | $0（免費額度 100封/天）|
| GitHub Actions | $0（免費 2000分鐘/月）|
| **合計** | **~$3/月** |

## 版面結構（widget v5）

1. 市場即時數據（5格）
2. 核心要聞（5–6條）
3. 系統狀態評估（固定3格 + 動態3格）
4. 硬核科技趨勢（4–5條，含技術子項目）
5. 新創產業發展（4–5條，縮短版）
6. 隱含趨勢分析（4格）
7. 今日重要行程（4–6個）
