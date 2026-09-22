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

## 日報語言：英文（2026-09-19 起）

日報輸出全面改英文。分界線是「**誰在看**」：

| 對象 | 語言 |
|---|---|
| 模型看的（三個 prompt、market_context、news_text 分段標題、關注清單區塊） | 英文 |
| 讀者看的（網頁區塊標題、tab、信件主旨、市場數據 label、引言） | 英文 |
| 持有人看的（終端 log、程式註解、本文件） | **維持中文** |

**素材本來就大多是英文**（Reuters／Bloomberg／FT／TechCrunch…），模型是沿用不是翻譯。真正需要轉寫的只有中文來源：MoneyDJ、中央社、工商時報、以及中文 GN 代理。prompt 的 LANGUAGE 段有專門規則：不要逐句翻、不要帶中文句型，公司一律用英文標準名（台積電→TSMC、聯發科→MediaTek、鴻海→Foxconn、聯準會→Federal Reserve），億／兆換成 B／T。

### 改英文時連帶重做的四件事（不是翻譯，是重寫）

1. **四道把關正則全部改英文**：`_MARKET_SENT_RE`（行情句）、`_INFERENCE_SENT_RE`（推論句）、`_MARKET_MOVE_FACT_RE`（個股波動要有 session 錨點）、`_FACT_ANCHOR_RE`。標題的「這不是行情、是事件數字」例外清單也同步改英文（contract price／pricing／revenue／exports／orders／shipments…）。
2. **斷句器 `_SENT_SPLIT_RE`（新）**：原本只認中文句號「。；;」。英文句點不算 → 一整段 body 被當成一句 → 只要有一句違規整段被刪光、條目再被 complete 檢查判死。現在補英文句界（句點＋空白＋大寫），零寬度切分，join 回去字元不變，`$1.42B` 不會被誤切。
3. **去重斷詞器 `_news_tokens`**：原本只抓大寫開頭專名＋中文 2-gram。中文一句產生數十個 2-gram，Jaccard 穩定；英文一句只剩三五個 token，兩則無關新聞共用 "The"／"EU" 就衝到 0.4 被誤判成同一事件。現在英文另抽一組「去虛詞的小寫實詞」(`_EN_WORD_RE`／`_EN_STOP`)。
4. **`_ACTION_GROUPS` 改成詞幹＋字界比對**：原本是中文固定詞硬塞幾個英文單字，`invests`／`invested` 配不上 `investment`。現在 `_ACTION_TERMS` + `_compile_action_terms()`：ASCII 詞尾補 `[a-z]*`、前面 `(?<![a-z])` 擋 around／urban 誤中。另新增 `pricing` 事件類型（半導體合約價原本在深挖與分類新聞之間配不起來）。

### 列舉值（prompt 與程式必須同步，改一邊會靜默掉條目）

- `industry_developments.category`：US earnings｜Semis and supply chain｜AI in production｜Global startups｜US sector moves｜Industry and finance
- `industry`：Semiconductors｜AI infrastructure｜Enterprise software and security｜Robotics and automation｜Healthcare and biotech｜Fintech｜Defense and aerospace｜Energy and logistics｜Other
- `fact_status`：reported｜completed｜approved｜signed｜filed｜scheduled｜in progress｜company guidance
- `development`：demand｜supply｜capacity｜technology｜pricing｜regulation｜competition｜capex｜M&A
- `regime.axes`：risk-on/risk-off/neutral、easing/tightening/neutral、suppressed/rising/extreme
- `vs_regime` 前綴：`Supports|` `Contradicts|` `Neutral|`（半形直線，不是全形「｜」）
- `regime.review.verdict`：carried over｜revised｜falsified｜no prior day
- `confidence` / `reliability`：high｜medium｜low
- `sentiment.stage`：Stage 1–4｜No clear signal
- `frontier_tech.stage`：lab result｜prototype｜pilot｜limited commercial｜full commercial｜fundraising
- `startup_news.deal.stage`：Seed｜Series A–D+｜Growth｜IPO filing｜M&A｜Fund close｜Shutdown｜Other；未揭露一律 `undisclosed`
- 財報 `category`：Financials｜Semiconductors｜Media and streaming｜Industrials and REITs｜Consumer｜Healthcare｜Energy｜Other
- 類別名刻意不含 `&`，避免 HTML 轉義與比對不一致

market 資料 label 也全改英文（SOX／TAIEX／Gold／US 10Y／IWM/SPY／Bank reserves／Fear & Greed…），趨勢字串改 `rising steadily`／`falling steadily`／`choppy`，流動性評估改 `Liquidity easing/tightening/neutral`。`html_template` 與 `weekly_template` 的 label 比對已同步。

### 刻意沒改英文的三塊

1. **`site_nav_snippet.py`（整站共用導覽列）**——檔頭寫明 do not edit by hand，是從 `financial-analysis-bot/scripts/site_nav.py` 同步來的，整個 research.investmquest.com 共用。改了會弄壞其他中文頁。
2. **`data/trading_systems.json` / `data/startup_frameworks.json`（100 篇手寫長文，約 10 萬字）**——Founders／Systems 兩個分頁內容仍是中文。tab 與頁面外框已英文。
3. **Screener 相關頁面的資料欄位**（`rs_trend`、地區名等，來自 `screener/` 子系統）。

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

## 收件人與寄件網域（2026-09-19 未完成）

**現況**：`TO_EMAIL` secret＝`keigoks@gmail.com,jiehperngyu@gmail.com`，但實際只有第一個收得到。
原因是寄件人仍是 Resend 共用測試寄件人 `onboarding@resend.dev`，該模式只准寄給 Resend 帳號本人。
2026-09-19 實測 Resend 回 403：`You can only send testing emails to your own email address (keigoks@gmail.com)`。
`email_sender.send_email()` 偵測到多收件人被退就自動改寄第一位並印出原因，所以日報信不會因此斷掉。

**要讓第二個信箱收到，回到電腦前依序做**：

1. https://resend.com/domains 登入 → Add Domain → 填 **`send.investmquest.com`**
   - ⚠ 刻意用子網域，不要用根網域。根網域已有 `v=spf1 +a +mx +ip4:85.187.128.56 include:spf.a2hosting.com ~all`
     與 `MX mail.investmquest.com`；一個網域只能有一筆 SPF，動它有機率讓現有信箱進垃圾信。
2. Resend 會給一組 DNS 紀錄（SPF TXT／DKIM TXT／回郵 MX）。DNS 在 **A2 Hosting**（ns1–4.a2hosting.com），
   到 A2 cPanel → **Zone Editor** → `investmquest.com` → 逐筆新增。只新增 `send.` 底下的，別碰既有 SPF／MX。
3. 回 Resend 按 **Verify**（通常幾分鐘到一小時）。
4. 設 secret：`gh secret set FROM_EMAIL`，值填 `Morning Briefing <briefing@send.investmquest.com>`。
   workflow 已經在傳這個變數，程式已經接好，**不用改任何一行碼**。
5. 下一份日報兩個信箱就會直接收到（不是轉寄）。

**試過但走不通的路**：Gmail 自動轉寄。新增轉寄地址時 Google 擋下來（`An error occurred with the secure
Google verification`）——那是機器人偵測，不繞。而且就算加成功，確認信要 `jiehperngyu@gmail.com` 本人去點。

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
- 素材兩層：① `RSS_FEEDS`（news_fetcher.py）多來源 feed 並行抓，抓取端先以 `source_registry.py` 做來源正規化與白名單硬驗證，再以 URL／近似標題去重並 round-robin 保留各來源覆蓋，總上限 310；② `PERPLEXITY_QUERIES` 共 18 題，涵蓋資料中心基礎設施、醫療生技、企業軟體／資安、工業自動化／國防航太，並把 AI 題聚焦具名產業導入、把機構持倉題改為有事實催化劑的美股類股／大型股波動。深挖不再先跑 meta-query，固定並行 2 題；MOVE 另算 1 次。WSJ／Nikkei 官方 RSS 已停更，不要加回。
- prompt 原則仍是「寧缺勿濫」：核心要聞與產業發展有軟目標但不是硬性最低值，地區沒素材留 `[]`；`{today}`／`{cutoff_date}`（`_news_date_window()`：平日回看 2 天、週一 3 天）為硬規則；同一事件整份 JSON 只能出現一次；top_stories 前 3–5 條必須是指數部相關（tag「指數部」）；白名單擴充（AP／BBC／CNN Business／TrendForce／CoinDesk／The Block／Crunchbase／Focus Taiwan／Yonhap／Korea Herald／Caixin），黑名單加 Seeking Alpha／Yahoo 轉載／Motley Fool／Benzinga。regional_tech 的 `malaysia` 改為 `asean`（東南亞）。
- 後處理（ai_processor.py，`process_news` 內、`_validate` 前）：`_sanitize_news()` 會再次硬驗證 canonical 白名單、移除過期與行情句；`_dedup_news()` 以日期＋實體＋事件動作＋數字判斷事件。核心要聞是主卡，重複的關注清單內容併為「對關注股的影響」，深度內容標為「延伸深挖」並移除重複現況段。品質統計寫入 `news_quality_latest.json`。
- **關注清單新聞 `watchlist_news`（2026-08-17 晚新增）**：來源＝DD Screener universe `research.investmquest.com/dd-screener/latest.json`（`fetch_dd_watchlist()`，約 250 檔，含 moat_grade／pass_count）。`tag_watchlist()` 在 RSS 條目標 `★關注[ticker]`（公司名／別名不分大小寫，裸 ticker 只認全大寫，避免 APP→App 誤標；別名表 `_TICKER_ALIASES`）。prompt 用 `_watchlist_block()` 分兩組：**優先組＝S 級全部＋A 級 pass_count≥3**（約 60 檔）、其他組只有重大事件（財報／指引、重大訂單、併購、監管、CEO、產品線）才收；只寫公司自身事件、每家一條、上限 8、嚴禁行情句。渲染 `_watchlist_news_section`（news 頁核心要聞之後、email 同位置）。
- **分類事實新聞 `industry_developments`（2026-09-10 調整）**：分為美股財報、科技與半導體產業鏈、AI 產業應用、全球新創、美股類股與波動個股、全球多產業與財經六類；六類都掃描，素材充足時整區目標 12–16 條、每類最多 4 條、整區最多 18 條，AI 應用有料時優先保留 3–4 條。每條以 `evidence`／`fact_status`／`unknowns` 呈現已確認事實；同義事實狀態會正規化，缺少重複的 evidence／unknowns 欄位時可從有事實錨點的 body 安全補值，不再整條誤刪。`confirmed_impact` 最多一個來源支持的直接影響句；不得用預測、投資建議或舊聞湊數。與核心要聞及其他新聞區塊去重，渲染在 news 頁與 email 的核心要聞之後。
- **新創與技術前緣（2026-09-19 擴充，起因＝持有人指出日報過度偏二級市場與金融）**：
  - 素材端加 18 個 RSS feed（新創／創投：TechCrunch Venture・TechCrunch Startups・Crunchbase News・Sifted・Tech in Asia (GN)・Wired 商業科技・Startup Funding (GN)；技術前緣：IEEE Spectrum・IEEE Robotics・MIT Tech Review・Quanta Magazine・Nature 新聞・Science 新聞・New Scientist・SpaceNews・The Quantum Insider・Ars Science・Frontier Tech (GN)），`RSS_TOTAL_CAP` 310→400。
  - `PERPLEXITY_QUERIES` 18→22：新創融資細節（輪次／金額／估值／投資人）、新創生態結構（down round・關門・併購・新基金）、技術前緣里程碑（量子・核融合・機器人・腦機・太空・新型運算・電池材料・合成生物）、可商轉的同儕審查研究。
  - `startup_news` 上限 4→8，每條多 `deal`（stage／amount／valuation／investors／hq）與 `why`；渲染 `_deal_line()`，「未揭露」的估值與投資人不佔版面。
  - **新區塊 `frontier_tech`（技術前緣）**：走新聞模型（不是分析模型），欄位 field／field_type／who／body／stage／why，最多 5 條、至少涵蓋 3 個不同 field。渲染 `_frontier_tech()`（trends 頁 Deep tech 之後、email 同位置）。因為前緣研究本來就慢，`_sanitize_news` 對它**不做**過期過濾（同 tech_trends），時間窗由 prompt 的 72 小時規則控制。
  - source_registry 新增 Sifted／Tech in Asia／IEEE Spectrum／Quanta Magazine／New Scientist／SpaceNews／The Quantum Insider（新 group「前緣科技」），並給既有的 Wired／Ars Technica／MIT Tech Review／Nature／Science 補上 `frontier` topic。
- **本週值得讀 `weekend_reads`（同日新增）**：從 The Economist／FT 等 `weekly`／`longform` feed 挑最多 3 篇長文，欄位 title／source／source_date／why／link；sanitize 不做過期過濾。渲染 `_weekend_reads_section`（trends 頁 tech_trends 之後、email 同位置）。
- 想加 RSS：先在 `source_registry.py` 加 canonical 名稱、別名、網域與 topics，再在 `RSS_FEEDS` 加一行 tuple；`GEMINI_SYSTEM_PROMPT` 的白名單會由 registry 自動產生。

**新聞搜尋層（news_fetcher.py，2026-08-17 同日改制）**：Perplexity 已停用（帳號當日全面 429，持有人決定不再付費）。所有搜尋走 `_llm_search()` → 主＝Claude Code headless `--allowed-tools WebSearch`、模型 `haiku`（最便宜，搜尋只是找資料），單題失敗會立即重試一次；備援＝Perplexity（僅在 workflow 傳 `PERPLEXITY_API_KEY` 時啟用，目前註解掉）。換模型：`NEWS_SEARCH_MODEL`；單次逾時：`NEWS_SEARCH_TIMEOUT`（預設 240 秒）。來源網址由模型在答案末尾 `SOURCES:` 區塊列出、解析後以 registry 網域白名單再過濾。`_fetch_dynamic_deep_topics()` 是死碼（無呼叫端），仍寫死 Perplexity，勿誤用。

---

## 事件判斷層：今日新增證據（2026-09-22 新增）

目的：每天回答四件事。今天的新聞裡，哪些是過去紀錄沒有的事實；影響哪個經濟變數；該派給哪份 DD、哪個研究主題、哪個系統持倉；還有什麼沒證實。

**分工**
- 程式：挑候選（沿用 `process_news` 去重後的新聞卡）、對回 RSS 條目拿網址與發布時間、公司與總經主題辨識、數字正規化（30 million＝30M＝3000萬）、日期、找先前紀錄、一手來源查核、派送、「尚未證實」的提醒文字、冪等寫入、來源品質統計。
- Jev（TypeSafe `jev-1.13.0`，釘版本）：只答預先定義選項的窄問題，題目在 `evidence_questions.py`。新舊、事實階段、每個經濟變數各一題（一則新聞可同時影響多個變數）、方向、重要度、出處類型、候選公司是否當事人。公司新聞問 10 個公司變數；總經新聞問 9 個總經變數（通膨、成長、就業、政策利率、債券殖利率、匯率、信用與流動性、貿易、財政）加市場估值；兩者都有就兩組都問。
- Jev 不做：買賣判斷、改寫投資結論、產生公司名或論述。畫面上的「classification confidence」是分類把握度，不是股價機率，頁面有明寫。

**檔案**
- `briefing/evidence_layer.py`：主流程與判斷規則（`decide`、`unconfirmed_notes`）
- `briefing/evidence_questions.py`：題目與答案解讀
- `briefing/evidence_ledger.py`：跨日事實紀錄、數字正規化、找先前紀錄
- `briefing/evidence_routing.py`：DD／研究主題／總經報告／系統持倉派送、可能受影響的產業、SEC 查核
- `briefing/evidence_sources.py`：一手來源（官方 RSS、證交所與櫃買中心重大訊息、官方網域的 Google News site: 查詢、當事公司新聞稿）
- `briefing/jev_client.py`：HTTP 客戶端，含快取與每次執行的請求上限
- `data/evidence_routing.json`：人工對照表。人工環節、91 個研究主題的英文辨識詞、27 個總經主題與國家、國別對應的指數部部位、官方來源清單。
- `data/evidence_routing_auto.json`：自動產生，不要手改。來自 financial-analysis-bot 的研究主題（ID）成員與角色欄公司名、總經報告（MACRO）的關鍵指標。重建：`python3 briefing/evidence_build_data.py routing --fab ~/financial-analysis-bot`
- `data/evidence_seed_ledger.json`：先前已知的種子，來自每檔最新 DD 摘要與過去 60 天已發布早報（含總經新聞）；用 `python3 briefing/evidence_build_data.py seed --fab ~/financial-analysis-bot --days 60` 重建

**流程**：`main.py` 在 `process_news` 之後、產生 HTML 之前呼叫 `run_evidence_layer`，整段包在 try 裡，出錯只讓這一區塊標未判斷。輸出寫到 `docs/briefing/data/`：`evidence_ledger.json`（跨日紀錄，一筆一行）、`evidence_{date}.json`／`evidence_latest.json`（當日判斷，含 Jev 快取）、`source_quality_{date}.json`／`source_quality_latest.json`。發布步驟原本就會複製 `data/*.json` 到網站，隔天從 `research.investmquest.com/briefing/data/` 抓回來。

**幾條不能鬆的規則**
- 同一天重跑：今天寫入的紀錄不算「先前已知」；同名檔覆寫；同樣的請求從快取拿，不重付。
- 標題數字同公司早就記錄過、文中沒有 additional／another 這類字眼：程式判重述，Jev 說新也不採用。有追加字眼就送複核。2026-09-22 真 Jev 實測把 Copilot 3,000 萬席判成新事實，就是靠這條擋下。
- 前一天的紀錄抓不到：不准標「新」，一律待複核。
- 沒有 `TYPESAFE_API_KEY`、API 失敗、預算用完：全部標未判斷，不補答案，不派 DD。
- 來源抓不到時寫「沒讀到」，不寫沒有影響。`news_fetcher._fetch_one_feed` 逐來源記錄 ok／empty／error。
- 持倉只讀公開的 `/pm/holdings.json`（系統組合），不讀、不輸出任何未公開的券商持倉。
- 「市場估值」只列直接影響。實測 Jev 會把幾乎每則新聞都標成間接影響估值，沒有資訊量。
- 研究主題要「當事公司是成員，而且文中點到該主題的辨識詞」才確認；公司在主題裡但文中沒點到，進待審。沒有當事公司時，要兩個辨識詞，或一個三個字以上的明確片語（data center permits）。
- 一手來源分兩級：內容對上（數字或用字重疊）才升級成「官方文件已對到」；同公司、同日期但內容沒對上，只列為「附近有公告」。當事公司新聞稿只收標題開頭是該公司名的，別家新聞稿順帶提到的不算。
- 總經提醒由程式加：官員發言不是決策、市場定價不是預測、部分月份資料、初值常修正、談判不是協議、預測不是結果、政策決定要看官方公告。

**DD／研究主題不再更新時**：這一層照常運作，判斷新舊用的是每天累積的事實紀錄，不是報告。每個 DD、研究主題、總經報告連結旁邊標報告日期；超過 120 天標 older report；另標「報告之後紀錄裡又多了幾則新事實」（+N new since）。報告成了基準線，每天的紀錄是它的後續。

**Secrets（兩個都選填）**：`TYPESAFE_API_KEY`（沒有就只標未判斷，不花錢）、`SEC_USER_AGENT`（SEC 要求帶聯絡方式；沒有就跳過查核並標成缺口）。

**成本**：2026-09-22 十則實測約 6.5 萬 input token，約 0.0027 美元。官方來源約 35 個請求、3 秒，不花錢。每次執行上限 30 個請求、40 萬 token（`JevClient` 參數）。

**測試**：`python3.12 -m pytest -q tests`（不呼叫付費 API）。離線重播 9/22 案例：`python3.12 tests/evidence_offline_replay.py --out /tmp/evidence_replay --mode fake`（`--mode nokey` 看沒金鑰的畫面）。fake 模式用的是測試劇本，不是真實 Jev 輸出。官方來源在測試裡讀 `tests/fixtures/official_20260922/` 的快照，不連網。

---

## 分析骨架：主軸先行（regime-first，2026-08-17 改制）

分析區塊（`CLAUDE_SYSTEM_PROMPT` / `CLAUDE_USER_PROMPT_TEMPLATE`）不再是「每個區塊各自解讀」，而是先立主軸再讓各區塊對主軸表態：

- JSON 頂層新增 `regime`：`call`（一句有方向的市場狀態）／`axes`（risk_appetite・liquidity・volatility 各 state＋evidence，證據要有實數）／`confirms`／`contradicts`（沒有反證要說為什麼可疑）／`falsifiers`（metric＋threshold＋meaning，具體門檻）／`for_w52_engine`（只講週線閘門與波動率環境，**不下買賣指令**）／`confidence`＋`confidence_reason`。
- `market_pulse`、`index_factor_reading`、`sentiment_analysis` 各多一個 `vs_regime`：格式「支持｜／反對｜／中性｜ ＋ 一句話」，必須把矛盾點講出來。
- 渲染：`html_template._regime_block()`（放在 alert 之後、market_strip 之前，email 與 index 頁都有）＋ `_vs_regime_line()`（三個區塊底部一行）。`_validate` 有預設值，模型漏寫時區塊直接不顯示、不炸。
- 人設已改成持有人真實系統（W52 × 自適應波動率 cap 1.5，QQQ/SMH、0050/2330），不是泛泛的「資深分析師」。中文句子標點一律全形。
- **昨日主軸驗證（2026-08-17 晚新增）**：main.py 每天把 `{date, regime, daily_summary, alert, market_context}` 存到 `docs/briefing/data/regime_{date}.json` ＋ `regime_latest.json`（workflow 一併複製到網站）；隔天 `news_fetcher.fetch_prev_regime()` 從 `research.investmquest.com/briefing/data/regime_latest.json` 抓回，`_build_market_context(prev_regime=…)` 把昨日 call／證偽條件塞進分析 prompt，模型填 `regime.review`（`yesterday_call`／`verdict`＝延續・修正・被證偽・無前日資料／`falsifier_check[]`＝metric・threshold・today_value・hit／`note`）。渲染在 `_regime_block` 底部（verdict 色塊＋每條證偽條件 ✓／✕ chip）；`無前日資料` 時不顯示。第一次上線那天一定是無前日資料，屬正常。

---

## 檔案職責

### 日報
main.py → 日報主流程，串接所有模組
news_fetcher.py → 新聞素材（`RSS_FEEDS` 多來源 RSS＋Google News 代理；`_llm_search`：Claude Code Haiku＋WebSearch 主、Perplexity 備援）+ yfinance 行情 + FRED 流動性
source_registry.py → 新聞來源 canonical 名稱、別名、網域、分級、topics 與黑名單（唯一來源 registry）
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

1.masthead+summary 2.alert 2b._regime_block（今日主軸＋底部昨日主軸驗證） 3._market_strip 4._index_factor_reading
5._sentiment_analysis 6._market_pulse 7._daily_deep_dive
7b._evidence_email_digest（今日新增證據，只放三行摘要＋連結；news 頁則是完整的 `_evidence_section`，排在 Top stories 之前）
8.top_stories 8b._watchlist_news_section（關注清單動態） 9.world_news 10.us_market_recap 11.macro
12.geopolitical 13.ai_industry 14.regional_tech 15.fintech_crypto
16.system_status（System status） 17.tech_trends（Deep tech） 17b._frontier_tech（Frontier tech） 18.startup_news（Startups） 18b._weekend_reads_section（Weekend reads） 19.smart_money
20.earnings_preview 21.implied_trends 22.fun_fact 23.today_events 24.footer

---

## 日報去重順序（最高優先級）

top_stories → macro → geopolitical → world_news → ai_industry →
regional_tech → fintech_crypto → startup_news → frontier_tech；watchlist_news 與
daily_deep_dive 若命中同事件則分別併為影響註記與延伸深挖，不另建主卡。

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
