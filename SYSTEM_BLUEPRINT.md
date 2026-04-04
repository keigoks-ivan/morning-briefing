# Morning Briefing System Blueprint
# 每日財經晨報 + RS+VCP Screener — 完整系統藍圖
# 版本：2026-04 | 用途：新對話 context，直接貼給 Claude 即可復原完整系統知識

---

## 一、系統概覽

**三個子系統：**
1. **日報**：每天台灣時間 05:55，research.investmquest.com/briefing/
2. **週報**：每週日台灣時間 05:55，research.investmquest.com/weekly/
3. **RS+VCP Screener**：跟日報一起跑（週一到週五），Top 30 附在 Email 最後，Excel 作附件

**Repo：** keigoks-ivan/morning-briefing（private）
**部署：** GitHub Pages（docs/ 目錄）

---

## 二、技術架構

```
Render Cron Job（UTC 21:50）
→ trigger.py 呼叫 GitHub API workflow_dispatch
→ GitHub Actions daily_briefing.yml（timeout: 30分鐘）
→ Python 主程式（約 10-13 分鐘）
   ├── Perplexity API 並行查詢（30+ 個，ThreadPoolExecutor max_workers=8）
   ├── yfinance 抓取市場數據（period="7d", interval="1d"）
   ├── FRED API 抓取流動性數據
   ├── CNN Fear&Greed API
   ├── Claude API（streaming，max_tokens=32000）
   ├── RS+VCP Screener（376支，純 yfinance，週末跳過）
   └── 產出 HTML → Email（Resend）+ GitHub Pages
```

### Repo 檔案結構
```
morning-briefing/
├── CLAUDE.md                    # 根目錄整體規則（Claude Code 自動讀取）
├── SYSTEM_BLUEPRINT.md          # 本文件
├── Watchlist_Tickers_CIK.xlsx   # 396支美股 watchlist（含產業分類）
├── trigger.py                   # Render Cron → GitHub API
├── requirements.txt
├── briefing/
│   ├── CLAUDE.md                # 程式碼細節（Claude Code 自動讀取）
│   ├── main.py                  # 日報主流程
│   ├── news_fetcher.py          # Perplexity + yfinance + FRED
│   ├── ai_processor.py          # Claude API streaming，輸出 JSON
│   ├── html_template.py         # JSON → HTML，所有區塊渲染
│   ├── email_sender.py          # Resend API（支援 Excel 附件）
│   ├── weekly_main.py           # 週報主流程
│   ├── weekly_fetcher.py        # 週報 Perplexity 查詢
│   ├── weekly_processor.py      # 週報 Claude 分析
│   └── weekly_template.py       # 週報 HTML
├── screener/
│   ├── screener.py              # RS+VCP 計算邏輯
│   ├── excel_exporter.py        # Excel 輸出（條件格式）
│   └── main.py                  # Screener 主流程 + GitHub Pages 發布
├── docs/
│   ├── briefing/                # 日報 HTML（多頁式）
│   ├── weekly/                  # 週報 HTML
│   └── screener/
│       ├── index.html           # Top 30 網頁
│       ├── latest.json          # 最新結果
│       └── history/             # 每日歷史 JSON（全部排名）
└── .github/workflows/
    ├── daily_briefing.yml       # workflow_dispatch only
    └── weekly_report.yml        # cron 55 21 * * 0
```

### GitHub Secrets
```
ANTHROPIC_API_KEY
PERPLEXITY_API_KEY
RESEND_API_KEY
TO_EMAIL
GH_PAT
```

---

## 三、市場數據架構（news_fetcher.py）

### 數據抓取規則
- 所有 ticker 用 `period="7d", interval="1d"`
- 取 `dropna()` 後 `iloc[-1]`（最新）和 `iloc[-2]`（前一日）計算漲跌
- 情緒歷史用 `period="10d"` 抓5日收盤值
- 分析用 NDX 現貨（^NDX），NQ 期貨已移除

### 固定指標
```
股票指數（9格）：^NDX、^GSPC、^SOX、^TWII、^GDAXI、VT、VO、BTC-USD
美股因子（6格）：FNGS(NYFANG)、VTV、VUG、MTUM、IWM、RSP/SPY比值、IWM/SPY比值
市場情緒：^VIX、^VIX9D、^SKEW、^VVIX、CNN Fear&Greed、MOVE（Perplexity）
原物料固定（6格）：BZ=F、CL=F、GC=F、SI=F、HG=F、ALI=F
原物料動態（2格）：從備選池選當天波動最大2個
債券（5格）：^IRX(2Y)、^TNX(10Y)、^TYX(30Y)、TLT、10Y-2Y利差（計算）
外匯固定（3格）：DX-Y.NYB、JPY=X、TWD=X，動態2格
信貸（4格）：HYG、LQD、BKLN、HYG/LQD比值（計算）
流動性（FRED）：RRPONTSYD(RRP)、NFCI、WTREGEN(TGA)、WRESBAL(準備金)
```

### Sector ETF 動態選池（選波動最大3個）
```
XLE、XLF、XLK、XLV、XLI、XLY、XLP、XLU、XLB、XLRE、XLC、XBI
```

### 反向指標（漲=紅）
VIX、VIX9D、VVIX、MOVE

### 情緒歷史趨勢
```python
sentiment_history = {
    "vix_5d": [...],
    "vvix_5d": [...],
    "vvix_trend": "連續回落/持續上升/震盪",
    "vvix_peak_days_ago": N,       # 關鍵：>= 2 才是第三階段訊號
    "vvix_peak_val": 數值,
    "vvix_peak_decline_pct": %,
}
# 第二層趨勢（只傳方向）：HYG、DXY、10Y、黃金、BTC、RSP/SPY、IWM/SPY
```

---

## 四、Perplexity 查詢架構

```python
# 並行執行
with ThreadPoolExecutor(max_workers=8) as executor:
    results = list(executor.map(_single_query, args_list))

# 參數
model = "sonar"
search_recency_filter = "day"  # 嚴格限制24小時
max_tokens = 800

# 查詢類型（共30+個）
1. 一般新聞查詢（約25個）
2. 固定深度查詢（2個）：半導體、AI架構
3. 動態深度查詢（3個）：元查詢先找今日最重要主題，再各自深挖
4. MOVE Index 查詢（1個）
5. 財報查詢（1個）
```

---

## 五、日報版面區塊順序（build_html）

```
1. masthead + summary（今日一句話）
2. alert bar
3. _market_strip()：指數→因子→情緒→原物料→債券→外匯→信貸→流動性
4. _index_factor_reading()（紫色區塊）
5. _sentiment_analysis()（情緒四部曲）
6. _market_pulse()（三層推論）
7. _daily_deep_dive()（2個主題）
8. top_stories（15條）
9. world_news（3條）
10. us_market_recap（盤前・盤中・盤後）
11. macro
12. geopolitical
13. ai_industry
14. regional_tech
15. fintech_crypto
16. system_status
17. tech_trends
18. startup_news
19. smart_money（最多3條）
20. earnings_preview
21. implied_trends（4個訊號，2週到3個月視野）
22. fun_fact
23. today_events
24. _screener_top30()（RS+VCP Top 30，週末不顯示）
25. footer
```

### 去重順序（最高優先級）
```
tech_trends → daily_deep_dive → top_stories → world_news →
macro → geopolitical → ai_industry → regional_tech →
fintech_crypto → startup_news → us_market_recap → smart_money
```

---

## 六、關鍵分析框架

### 情緒四部曲（sentiment_analysis）
```
第一階段：VIX<20 + SKEW>135 + VVIX平穩
第二階段：VIX>30 + VVIX>120飆升 + SKEW急跌
第三階段：VIX>35 + vvix_peak_days_ago>=2 + SKEW<120（力竭訊號）
          充分條件：VIX>40 + vvix_peak_decline_pct>10% + F&G<20
第四階段：VIX從高檔回落 + VVIX回到100 + 股市反彈

關鍵：peak_days_ago >= 2 是最重要條件
可靠性由信貸（HYG跌幅）和跨資產確認決定
```

### market_pulse 三層推論
```
第一層：跨資產背離識別
第二層：雙軌機制推論
  - 歷史類比（具體錨點）
  - 新模式可能性（AI時代/被動投資崛起讓歷史類比失效）
第三層：情境推演 + 下一個觀察點（可操作 watchlist）
```

### implied_trends
```
時間視野：2週到3個月
要求：引用 sentiment_history 和 second_layer_trends 的實際數據
目的：已有數據支撐但尚未被定價的甜蜜點
```

---

## 七、RS+VCP Screener 系統

### Watchlist
- 來源：Watchlist_Tickers_CIK.xlsx（優先）→ 硬編碼 fallback（374支）
- 有效標的：~376支（約20支已下市自動跳過）
- 產業分類：Technology/Consumer/Industrials/Financials/Energy/Healthcare/Materials

### RS Score（相對強度持續性）
```python
# 三個時間維度百分位排名
rs_1w  = 個股5日漲跌幅 vs 全watchlist 百分位
rs_4w  = 個股21日漲跌幅 vs 全watchlist 百分位
rs_13w = 個股63日漲跌幅 vs 全watchlist 百分位

# 加權平均
persistence = rs_1w * 0.2 + rs_4w * 0.3 + rs_13w * 0.5

# RS 趨勢加分/扣分
加速上升（rs_1w > rs_4w > rs_13w）：+5
穩定維持：+2
震盪：0
開始衰退（rs_1w < rs_4w < rs_13w）：-5

final_rs = min(100, persistence + trend_bonus)
```

### VCP Score（價格收縮形態）
```python
# 從基礎分50開始，近90日找局部高低點
評分項目1：收縮次數 2-4次（+15），1次（+5），>4次（+8）
評分項目2：回撤幅度遞減（+15）
           最後一次回撤 < 5%（+15），< 8%（+10），< 12%（+5）
評分項目3：成交量遞減（+10）
評分項目4：距前期高點 < 3%（+15），< 5%（+10），< 10%（+5），> 10%（-5）
評分項目5：ATR 收縮（ratio<0.6 +10，<0.8 +5）
vcp_score = max(0, min(100, vcp_score))
```

### Combined Score
```
Combined = RS_Score × 60% + VCP_Score × 40%
```

### 輸出
```
Email：Top 30 表格（含排名變化 ↑↓新進、產業標籤）
Excel 附件：
  Sheet1「完整排名」= 全部有效標的
  Sheet2「Top 30」= 前30精選
  Sheet3「說明」= 指標解釋
  條件格式：RS Score 和 Combined Score 紅→白→綠漸層
  RS Trend 顏色：加速上升綠/穩定維持藍/開始衰退紅
GitHub Pages：docs/screener/index.html（含產業分布橫條圖）
             docs/screener/history/{date}.json（全部排名）
週末不跑：weekday < 5 判斷
Screener 失敗：screener_result={} 日報繼續跑不受影響
```

### 排名變化對比
```python
# 讀取 docs/screener/history/ 最近一次 JSON
prev_rank - curr_rank > 0 → ↑N（綠色）
prev_rank - curr_rank < 0 → ↓N（紅色）
不在上次記錄 → 新進（藍色）
```

---

## 八、週報架構

### 十個主題
```
central_bank → liquidity → credit → options+weekly_sentiment →
ai_industry → semiconductor → earnings → macro → commodities → black_swan
```

### 與日報的差異
```
情緒歷史：period="60d", interval="1wk" 抓8週週線
第三階段判斷：vvix_peak_weeks_ago >= 2
漲跌：顯示週漲跌幅
標題：「本週主軸」
weekly_sentiment_analysis 輸出 week_conclusion（2句）
```

---

## 九、顏色規範

```
上漲：#0F6E56  下跌：#C0392B  中性：#888888
反向指標（漲=紅）：VIX、VIX9D、VVIX、MOVE

類別色塊：
股票指數  #1B3A5C    債券   #185FA5（背景 #F5F9FF）
美股因子  #7F77DD    外匯   #534AB7（背景 #F7F5FF）
市場情緒  #BA7517    信貸   #0F6E56（背景 #F3FBF7）
原物料    #854F0B    流動性  #085041（背景 #F0F9F5）
```

---

## 十、Prompt 設計決策與原因

### JSON schema 輸出
分離分析邏輯和呈現邏輯。`_validate()` 補預設值防止 KeyError，JSON 解析失敗只影響當天。

### tech_trends 去重優先最高
硬核訊號素材最稀缺，其他區塊有更多新聞可選。

### market_pulse 三層推論
第一層只是事實。雙軌機制（歷史類比+新模式）避免忽略 AI 時代結構差異。第三層的觀察點把分析轉化為可操作 watchlist。

### 情緒四部曲用數值條件
語意判斷在不同環境含義不同。peak_days_ago >= 2 是關鍵：今天見頂不是訊號，連續2天回落才代表機構力竭。歷史校驗：2020年3月和2018年12月符合，假底不符合。

### 5日歷史趨勢
市場底部是過程不是瞬間。連續回落2天 vs 今日才回落，意義完全不同。

### implied_trends 2週到3個月
今天的事其他區塊已有。太短=延伸新聞，太長=無數據支撐。

### 新聞區塊嚴禁行情數字
行情數字有獨立區塊。Perplexity 的行情數字不如 yfinance 可靠。

### 用 Perplexity 不用其他
search_recency_filter: "day" 嚴格24小時。Tavily days 參數不夠嚴格。

### RS Score 三個時間維度
只看63日是單一快照。三維度可看趨勢方向，加速上升的股票在反彈時往往是領頭羊。

### VCP Score 強調回撤幅度遞減
Minervini 核心：回撤幅度越來越小 + 量能越來越萎縮 = 賣壓耗盡，準備突破。

---

## 十一、API 成本與 Gemini 替換評估

### 現有成本
```
Claude API 日報   ~$6.0/月
Claude API 週報   ~$4.0/月
Perplexity API    ~$1.5/月
合計              ~$11.5/月
```

### Gemini 替換建議
```
絕對不換（品質關鍵）：
- market_pulse、sentiment_analysis、implied_trends
- 這三個是系統核心價值，需要 Claude 的推理深度

可以換（品質差異小，省 ~$3.5/月）：
- top_stories/world_news/geo/tech_trends/startup_news → Gemini Flash
- 主要是分類和摘要，Gemini Flash 足夠

考慮換（省 ~$2.5/月）：
- 週報分析 → Gemini 1.5 Pro，深度接近 Claude Sonnet

不可替換：
- Perplexity：搜尋工具，無法替代即時搜尋
- yfinance：免費數據，無替換必要
```

---

## 十二、常見問題解法

| 問題 | 解法 |
|---|---|
| JSON 解析失敗 | 確認 max_tokens=32000，streaming 模式 |
| 市場數據空白 | period="7d"，取 dropna() 後最後兩筆 |
| 週末數據空白 | period="7d" 自動取上一交易日 |
| GitHub Actions 超時 | timeout-minutes: 30 |
| 排程不跑 | git commit --allow-empty -m "resync" && git push |
| NYFANG ticker 錯誤 | 用 FNGS（不是 ^NFG） |
| NDX vs NQ | 分析用 ^NDX 現貨，NQ=F 有基差 |
| Screener 掛掉 | try/except 保護，日報繼續跑 |
| Watchlist Excel 找不到 | 自動 fallback 到硬編碼374支清單 |
| GitHub Pages 不更新 | 檢查 GH_PAT 權限和 docs/ commit |

---

## 十三、待完成事項

1. 觸發一次完整 daily_briefing workflow 做整合測試
2. 確認 Excel 附件和 Top 30 Email 區塊正常
3. 新聞整理區塊換 Gemini Flash（選項，省 ~$3.5/月）
4. 台股 Screener（0050 + 中型100 + 富櫃50 成分股，Top 15）

---

## 十四、新對話使用方式

把本文件貼在第一則訊息，說明本次要做的事，Claude 會自動理解整個系統架構。
