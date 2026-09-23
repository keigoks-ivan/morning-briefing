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
- `briefing/evidence_sources.py`：一手來源（官方 RSS、證交所與櫃買中心重大訊息、東證 TDnet 適時開示、官方網域的 Google News site: 查詢、當事公司新聞稿）
- `briefing/evidence_fulltext.py`（2026-09-23 新增）：抓候選新聞的全文，只抓排序最前面 12 則。Google News 轉址連結（news.google.com/rss/articles/...）用 `googlenewsdecoder` 解成出版方網址，正文用 `trafilatura` 抽取；抓不到就試下一個網址，付費牆網域（ft.com／bloomberg.com／wsj.com／nikkei.com 等）直接跳過不發請求，抽出正文不到 400 字也當失敗。全文只在這次執行的記憶體裡用，用完即丟
- `briefing/gdelt_source.py`（2026-09-23 新增）：第二個候選來源，查 GDELT DOC 2.0，找早報自己 RSS 以外的公司專屬新聞
- `briefing/ideas_layer.py`（2026-09-23 新增，同日晚加早報外掃描）：把新事實／進度更新、以及去重後新聞池裡早報自己沒選中的相關新聞，比對到 `ideas.json` 的查核點，逐則批次問 Jev 支持／推翻／無關，寫 `docs/briefing/data/idea_hits.json`；詳見本節下方「投資想法／查核點」
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
- 事件日期比今天早超過 3 天算「過舊」；未來日期不算，例如後天才開的高峰會。過舊又能在候選事件日期前後 2 天內找到共享公司或主題的先前紀錄，程式直接判重述，不管 Jev 怎麼答；過舊卻找不到，送複核。2026-09-23：7 天前的 Fed 升息被 Jev 判成新事實（0.97），9/16、9/17 其實早就記過。
- 數字比對（`_figure_overlap`）只算「先前那筆紀錄也跟候選共享公司或主題」的數字，不相干事實撞到同一個數字不算重述證據。2026-09-23：AMD 市值破兆撞到國庫券回購公告裡的「1 trillion」，兩邊沒有共同的公司或主題。
- `top` 排序（`_rank_key`）先比新事實／進度更新在不在待複核前面，再比有沒有派到任何研究（DD、系統持倉、研究主題、總經報告、產業環節都算，不分高低），再比重要度分數、一手來源、區塊優先序；`needs_review` 一律不進 `top`。2026-09-23 前只比重要度分數，待複核的項目混進過 top，具體新聞（TSMC A14、Hanmi FC Bonder）反而被籠統的總經新聞擠到 more。DD 不高於主題：回放時 DD 優先會讓 Apple 健身手環擠掉產業級消息。
- 日股一手來源是東證 TDnet 適時開示（`tdnet_disclosure`，`evidence_sources._load_tdnet`）：逐日抓清單頁（今天＋往回 3 個平日），一頁 100 則、不滿一頁就是當天最後一頁，日本假日頁沒有公告列，判 empty 不是 error。代號比對走 `evidence_layer._jp_codes`（東證 4 碼代號，獨立於台股代號，避免兩邊代號剛好同號誤配）。標題是日文，跟英文新聞用字很難對上，大多停在「附近有公告」；數字比對不受影響，「10億」這類日文單位已經在 `extract_figures` 的既有換算表裡，能跟英文的 billion 對上。韓國 DART（dart.fss.or.kr）還沒接，缺 API key，先不做。
- 全文只給 Jev 判斷、給程式比對官方來源的數字與關鍵詞用，絕對不寫進任何輸出檔（`evidence_{date}.json`／`evidence_latest.json`／`evidence_ledger.json`／`jev_cache`）。`jev_cache` 本來就只存 `answers`／`usage`，不存 Jev 收到的 state，所以全文不會經這條路徑落地。網頁與輸出檔對外只留：解出來的網址、網域、字數、抓取狀態（ok／paywalled／failed／no_url），最多兩句、合計 300 字以內、含關鍵數字的引句。抓到全文的證據基礎升級為 `full_article`（排在 `primary_document` 與 `headline_summary` 之間）；付費牆與抓失敗會在「尚未證實」寫清楚是哪個網域擋住、還是抓不到，不會再說「只讀了標題」。

**GDELT 候選（2026-09-23 新增）**：早報自己的候選只來自約 60 個 RSS 來源，個股專屬新聞常常漏接。`gdelt_source.py` 另外用公司名組 OR 查詢查 GDELT DOC 2.0，公司名優先序是 DD 已有報告／系統持倉在前，研究主題成員在後；`sourcelang:english`，一次最多 20 個請求，限流一次／5 秒（超過回 HTTP 429＋純文字訊息，程式判斷後等 5 秒重試一次，再不行就放棄那一題；連續 3 題都被擋就整段收手，記 `stopped_reason: rate_limited_3_in_a_row`）。查詢字元上限（`MAX_QUERY_CHARS`）先用保守值 1200：2026-09-23 本機測太多次，IP 被封，，隔了 20～90 秒還是 429，沒能實測出 GDELT 真正的上限，之後常態性因為太長被拒再收窄。標題要點到一家研究公司、而且有帶單位的數字或主題／環節辨識詞才留；跟既有新聞卡或 RSS 標題近似的丟掉，黑名單網域（`source_registry.is_blacklisted`）丟掉；每天最多留 10 則，排序先看公司在不在 DD／持倉，再看有沒有數字，最後比新舊。候選的 `block` 叫 `gdelt`，`BLOCK_PRIORITY` 裡優先序全早報最低；`MAX_CANDIDATES` 24→30，留 8 個名額給 GDELT（配合 `JevClient` 預設每次執行 30 個請求的上限，讓保留的名額都問得到 Jev；估算單則輸入 token 沒有明顯變化，400,000 上限還很有餘裕）。`run_evidence_layer` 新增 `gdelt_fetch` 參數，預設 `None`（不查、不連網，測試安全）；`main.py` 傳 `gdelt_fetch=fetch_gdelt_candidates` 才真的查。GDELT 掛掉、逾時、被限流都包一層 try/except，不影響早報，記在 `quality["gdelt"]`（`requests_sent`／`ok`／`rate_limited`／`articles_seen`／`kept`）與 `source_quality_*.json`。news 頁每則 GDELT 候選旁邊有「Found via GDELT (not in the briefing's feeds)」標籤（`html_template._ev_item`）。

**timing 窄問題（2026-09-23 新增）**：`build_questions` 每則都多問一題 `timing`——主要事實何時真的對營運／總經產生效果，不是何時被公布。六個選項：already_in_effect／this_quarter／within_12_months／one_to_three_years／beyond_three_years／unclear，判斷只看 `today` 裡寫明的日期或期間，沒寫就答 unclear，不用猜。答案存在 `item["timing"]`（`{label, display, confidence}`，未判斷時是 `None`）與 ledger `rec["timing"]`（只存 label）；畫面顯示在 news 頁證據列 stage 旁邊（`html_template._ev_item`／`_ev_row_detail`）。信心低於 0.5 一律顯示「Timing unclear」，但原始 label 照實存放，不因信心低被改寫。目前純粹供之後校準用：不進 `_rank_key` 排序、不進 `decide` 分類、不進 `route` 派送，之後校準完才會決定要不要接進判斷規則。多問一題會讓 Jev 請求雜湊變（`request_hash` 把 `questions` 也算進去），舊的 `jev_cache` 項目自然對不上新雜湊、不會被誤用也不會讓程式炸掉，只是那筆要重新問一次；單則多花約 300 input token。

**韓國出口統計配不到研究主題的坑（2026-09-23 修）**：live 版 `evidence_latest.json` 裡「Korea chip exports up 259%…」零派送，同一天「Korea's chip exports to Malaysia up 5.7x…」卻有派送。原因是 `data/evidence_routing.json` 的 `countries.KR` 只認 South Korea／Korea's／Korean，光講 Korea 配不到國家，scoped 的 TRADE_DATA 主題就退回預設美國；`theme_keywords.MemorySupercycle` 也只收 Korean chip exports／Korea's chip exports 兩種寫法。修法：`countries.KR` 加一筆 `Korea chip`，`theme_keywords.MemorySupercycle` 加一筆 `Korea chip exports`。沒有直接加裸的 `Korea`，避免跟 North Korea 的新聞撞在一起。

**DD／研究主題不再更新時**：這一層照常運作，判斷新舊用的是每天累積的事實紀錄，不是報告。每個 DD、研究主題、總經報告連結旁邊標報告日期；超過 120 天標 older report；另標「報告之後紀錄裡又多了幾則新事實」（+N new since）。報告成了基準線，每天的紀錄是它的後續。

**Secrets（兩個都選填）**：`TYPESAFE_API_KEY`（沒有就只標未判斷，不花錢）、`SEC_USER_AGENT`（SEC 要求帶聯絡方式；沒有就跳過查核並標成缺口）。

**成本**：2026-09-22 十則實測約 6.5 萬 input token，約 0.0027 美元。官方來源約 35 個請求、3 秒，不花錢。每次執行上限 30 個請求、40 萬 token（`JevClient` 參數）。2026-09-23 加全文後估算：最多 12 則、每則附最多 3,000 字全文摘要，抓不滿 12 則就更少，粗抓（4 字元約 1 token）增加約 9,000 token，多花不到 0.0004 美元，離 40 萬上限還很有餘裕。2026-09-23 `MAX_CANDIDATES` 24→30 之後最多也是 30 個請求，還在上限內；GDELT 另外算，不花 Jev 的錢，20 個請求＋限流間隔約 100～150 秒。

**測試**：`python3.12 -m pytest -q tests`（不呼叫付費 API）。離線重播 9/22 案例：`python3.12 tests/evidence_offline_replay.py --out /tmp/evidence_replay --mode fake`（`--mode nokey` 看沒金鑰的畫面）。fake 模式用的是測試劇本，不是真實 Jev 輸出。官方來源在測試裡讀 `tests/fixtures/official_20260922/` 的快照，不連網；TDnet 另外測，快照在 `tests/fixtures/tdnet/`（`tests/test_evidence_sources.py`）。全文抓取（`briefing/evidence_fulltext.py`）測試在 `tests/test_evidence_fulltext.py`（假 http_get／解碼函式，不連網）與 `tests/test_evidence_layer.py` 的 `FullTextTests`（斷言全文不會出現在任何輸出檔裡）。 GDELT：`tests/test_gdelt_source.py` 測查詢組裝、限流偵測與重試、標題過濾與排序、候選形狀；`tests/test_evidence_layer.py` 的 `GdeltIntegrationTests` 測 `gdelt_fetch` 參數怎麼接進 `run_evidence_layer`（假的 fetch、預設不查、掛掉不連累早報）。

**週度自動校準（`briefing/evidence_calibration.py`，2026-09-23 新增）**：不找人標記，每週自動回頭檢查
Jev 這週的判斷準不準，真相來自事後的紀錄與市場結果，Sonnet 二次意見只是參考。只寫建議，**永遠不自動
改任何門檻**，門檻要不要改由持有人自己決定。三個檢查：
1. 事後新舊回查——Jev 這週標「新事實／進度更新」的每一則，用「跑完這週之後」更完整的
   `evidence_ledger.json` 重新比對（比活動層當下的比對更嚴、更徹底），看有沒有更早的紀錄；也看後來
   有沒有紀錄把它當先前事實引用（`prior_refs`），當成新事實確實存在過的正面證據。依 Jev 信心分
   0.6–0.8／0.8–0.9／0.9–1.0 三區，算事後發現是舊聞的佔比，建議 `NOVELTY_MIN_CONF`（佔比≤10% 的
   最低信心區間）。
2. 重要度對結果——有 ticker 的新聞看事件日／隔一交易日相對市場基準（美股 SPY、.TW 用 0050.TW、.T
   用 ^N225、.KS 用 ^KS11）的異常報酬，超過該檔過去 60 天日報酬標準差 2 倍才算有反應；另外看後續
   3 天紀錄庫有沒有再被提到、有沒有補到官方來源。報告會明講「股價有沒有反應，不等於這則新聞重不
   重要」。
3. Sonnet 二次意見——同樣的窄問題（新舊、階段、直接影響哪些變數）再問一次 Claude Sonnet，走
   Claude Code CLI headless（跟 `news_fetcher._claude_search` 同一種呼叫方式，不開任何工具，模型
   `sonnet`），跟 Jev 的答案比對出分歧率；每週最多問 60 則，**完全不呼叫付費的 Jev API**。CLI 不可用
   就整條跳過、原因寫進報告。
輸入：網站上的 `evidence_{date}.json`（最近 7 天）與 `evidence_ledger.json`。輸出：
`docs/briefing/data/calibration_{date}.json`／`calibration_latest.json`＋可讀頁面
`docs/briefing/calibration.html`（繁體中文，跟日報網頁同一套樣式）。全文只在組給 Sonnet 的提示裡臨時
用一次，絕不寫進任何輸出檔（同 `evidence_fulltext.py` 的版權規則）。樣本少於 30 則時報告會說樣本太
小、不建議數字。排程：`.github/workflows/evidence_calibration.yml`，週日 22:00 UTC（台灣週一 06:00，
早報之前）＋ `workflow_dispatch`，沿用 `CLAUDE_CODE_OAUTH_TOKEN`（不需要 `TYPESAFE_API_KEY`），發布方式
跟 `daily_briefing.yml` 一樣 clone `financial-analysis-bot` 寫回 `docs/briefing/`，不寄信。測試：
`tests/test_evidence_calibration.py`，全部假 fetch／yfinance／CLI，含一則專門斷言全文不會出現在
`run_calibration` 或 HTML 輸出裡的 `CopyrightTests`。

**檢查④：投資想法校準（2026-09-23 晚新增）**：同一支程式、同一次執行多算一段，不是另開排程。
`collect_week_idea_pairs` 把這週每天 `evidence_{date}.json` 裡每一對 (新聞, 查核點) 判斷攤平成
一列，**含 unrelated**（早報候選在 `items[].ideas`，早報外的在 `ideas.wide_pairs`；只收
supports／refutes／unrelated，unjudged 代表沒真的問過 Jev，不算）。三件事：① 依 (idea,
checkpoint) 算無關佔比——佔比達 50%、樣本數至少 5 則才建議「這個查核點關鍵詞可能太寬」（例：
`cp3 keywords too loose: 70% unrelated`），**只建議，永遠不動 `ideas.json`**；② 同一組
supports_if／refutes_if 判準再問一次 Sonnet（沿用跟檢查③同一支 CLI 呼叫機制），算跟 Jev 的
一致率、列出分歧；③ 每個 idea／checkpoint 分早報候選、早報外各幾則。渲染在
`calibration.html` 多一節「投資想法校準」（`evidence_calibration._ideas_calibration_section`）。
測試：`tests/test_evidence_calibration.py` 的 `CollectIdeaPairsTests`／`AggregateIdeaHitsTests`／
`IdeaSecondOpinionTests`／`RunIdeaCalibrationIntegrationTests`。ideas.json 讀不到（沒部署、本機
沒設 `IDEAS_JSON_PATH`）這節就整段標未讀到、不擋其餘三個檢查。

**投資想法／查核點（`briefing/ideas_layer.py`，2026-09-23 新增，同日晚擴充早報外掃描＋
逐則批次問法＋到期提醒）**：想法定義（每個想法底下的查核點：companies／keywords／themes／
supports_if／refutes_if／選填的 `due`）另外維護在 financial-analysis-bot，發布在
`https://research.investmquest.com/ideas/ideas.json`（目前 2 個想法、17 個查核點）。載入順序：
env `IDEAS_JSON_PATH`（本機檔案，開發／測試用）→ 站上網址（沒部署會 404，跟其他抓取失敗一樣
一律當「跳過」，標 `ideas.status="unavailable"`，早報照出）→ 都沒有就整步跳過。

跑在 `run_evidence_layer` 的 items 全部組好之後，包自己的 try/except（`evidence_layer.py`
④），失敗只讓 `ideas` 標 unavailable，不連累事件判斷層其餘輸出。比對規則
（程式，不用模型，`ideas_layer.match_checkpoints`，不分早報候選／早報外，同一支函式）：
(a) 候選公司在 checkpoint.companies 裡（路由對照表認不得的公司，用 checkpoint.company_names
列名稱，文中出現就算），且文中（headline+summary，不含全文）出現至少一個 checkpoint 關鍵詞；
或 (b) 文中出現兩個以上不同關鍵詞（單複數算同一個，bond／bonds 不算兩個），或一個三個字以上
的關鍵詞片語，或（checkpoint.themes 有一個主題被既有主題派送確認，且文中出現至少一個關鍵詞）。

兩個候選來源，各自每天最多問 Jev 8 則新聞（`MAX_BRIEFING_IDEA_ITEMS`／`MAX_WIDE_IDEA_ITEMS`，
合計 `IDEA_ITEM_BUDGET=16`，`JevClient(max_requests=MAX_CANDIDATES + IDEA_ITEM_BUDGET + 2)`）：
① **早報候選**——只比對這次判成「新事實」或「進度更新」的項目（跟能進 `top` 的分類同一組）。
② **早報外掃描（`ideas_layer._wide_scan`，2026-09-23 晚新增）**——早報候選只來自約 60 個 RSS
來源精選出的一小部分（24～30 則被 Jev 判斷），漏接的個股專屬消息（HBM 合約價、Cloudflare bot
management 這類）永遠進不了事件判斷層。這一步對 `run_evidence_layer` 收到的 `rss_items`
去重後完整新聞池（main.py 傳 `moneydj_news`，約 300～400 則，**已經是既有參數，不用改
main.py**）裡「還沒被早報候選用到」的每一則（用網址比對排除），只跑 `match_checkpoints`
（英文關鍵詞比對，不問模型；純中文新聞比對不到，只計入 `chinese_count`，不另做中文比對），
比對到的再套四道程式新舊把關：事件日期（`published`）比今天早超過 3 天跳過；
`ledger.find_prior`（沿用既有 ledger 查詢，不是另造規則）找到「先前紀錄跟這則共享公司／主題
且共享數字」就跳過；同網址或正規化後同標題已經在 `idea_hits.json` 歷史裡出現過就跳過；標題
跟任一則早報候選（`match_checkpoints` 對到的候選，不限已分類的）近似（跟
`news_fetcher._near_same_title` 同一套演算法另外抄一份，見 `ideas_layer._near_same_headline`
檔頭說明——不直接 import news_fetcher，那支掛 feedparser／requests，會讓這一層被
`evidence_layer.py` 在模組層級 import 到、拖累沒裝這些套件的測試環境）就跳過。早報外掃描永遠
不進 `items`／`top`／DD 派送／ledger 新事實，只影響 `ideas` 輸出與 `idea_hits.json`。

兩組候選各自依「規則 (a) 公司命中優先 → 不同關鍵詞數 → 越新越前面」排序（`_item_rank_key`）
取前 8。**逐則批次問法（2026-09-23 晚改，取代舊版每對 (item, checkpoint) 各發一個請求）**：
一則新聞命中幾個查核點，就在同一次 Jev 請求裡問完（`jev.ask` 本來就支援一次問多題），題目 id
是 `"{idea_id}::{checkpoint_id}"`；沒被排進 8 則名額的仍記一筆 `unjudged`，不是沒比對到。
Jev 只答窄 Choice（`evidence_questions.build_idea_question`）：supports／refutes／unrelated，
criteria 直接用 ideas.json 的 supports_if／refutes_if，不選股、不下結論。早報候選的 state 給
headline／summary，全文（如果已經被 `evidence_fulltext` 抓到）也一併給；早報外一律只給
headline／summary（`evidence_basis: "headline_summary"`，不抓全文）——兩者都只在這次執行的
記憶體裡用，絕不寫進任何輸出檔，跟 `evidence_fulltext.py` 同一條版權規則。沿用同一個 `jev`
（快取與預算共用）；沒有 `TYPESAFE_API_KEY`、API 失敗、預算用完都一律標 `unjudged`，不補答案。

輸出：① 每則 evidence item 加 `ideas: [{idea, checkpoint, label, verdict, confidence,
summary}]`（含 `unrelated`；`summary` 是早報自己組的短摘要，不是全文，給週度校準的 Sonnet 二次
意見當材料）。② `ideas` 摘要區塊多 `wide_scan`（`pool_size`／`already_in_candidates`／
`chinese_count`／`matched_items`／`skipped_by_reason`／`asked_items`）與 `wide_pairs`（早報外
每一對含 unrelated 的完整判斷，只給週度校準用，news 頁不直接渲染這份，渲染走下一段的
`idea_hits.json`）。③ 跨日累加檔 `docs/briefing/data/idea_hits.json`（`idea-hits-v1`）：每列
多 `origin`（`"briefing"`／`"wide"`）與（早報外才有的）`evidence_basis`，其餘欄位不變（date／
idea／checkpoint／verdict／confidence／headline／source／url／event_date／fact_key／
evidence_id／by），只收 supports／refutes／unjudged（unrelated 不進累加檔）。合併規則
（`ideas_layer._merge_hits`）不變：同一天重跑整批換掉、(fact_key 或 evidence_id, idea,
checkpoint) 去重、history 404＝空清單／其他錯誤標 unavailable、只留 365 天。

渲染：news 頁「今天動到的想法」（`html_template._ideas_section`）：早報外命中多一個灰色
「早報外」標籤＋「只讀到標題與摘要」字樣。同一個區塊底部加「**未來 7 天到期的查核點**」
（Task 3，2026-09-23 晚新增；`_due_soon`／`_due_soon_block`）：讀 ideas.json 各查核點選填的
`due: [{date, label, approx}]`（沒有這個欄位就沒有提醒，程式不會噴錯），只顯示
[今天, 今天+7天] 範圍內的，approx 加「約」字首，每行連到 `想法網址#checkpoint_id`；沒有任何
到期就整個群組不顯示。Email 摘要（`html_template._ideas_email_summary`）多一行只在**2 天內**
到期時才顯示（`_ideas_due_email_line`），不需要今天有命中也會顯示；今天有命中才照舊各想法
各一行「想法：X N 則（支持 A、推翻 B）」。

測試：`tests/test_ideas_layer.py`（假 Jev、不連網），涵蓋載入順序、比對規則 (a)/(b)、逐則批次
問法（一個請求多題）、早報候選與早報外各自的 8 則上限、早報外四道把關各自的獨立測試
（`WideScanTests`）、`idea_hits.json` 的合併／去重／冪等／history／保留天數、`due` 攤平與渲染
（`CatalogDueTests`／`DueSoonTests`）、news 頁與 email 的渲染。離線重播
（`tests/evidence_offline_replay.py`，合成的早報外新聞池見 `evidence_fixtures.wide_rss_pool`）
可以拿真實 ideas.json（`IDEAS_JSON_PATH=~/financial-analysis-bot/docs/ideas/ideas.json`）示範
早報外掃描的比對結果。company key 目前不是每個都在 `evidence_routing.json`／
`evidence_routing_auto.json` 裡（例如 NBIS、5274.TW），對不到的公司單純讓規則 (a) 用不到，
規則 (b) 的關鍵詞／主題比對不受影響；ideas.json 本身不歸這一層管，不要在這裡改。**已知的鬆
關鍵詞（只是觀察，沒有動 ideas.json）**：cp2「per hour」單獨一個字太寬（GPU 定價以外的任何
「每小時」都可能撞到，靠另一個關鍵詞一起出現才會真的命中，但仍值得之後校準留意）；cp3
「contract price」不限半導體記憶體，油品／航運合約價的新聞理論上也會撞到；cp5「capex」／
「capital expenditure」是任何公司財報都可能出現的字，全靠另一個關鍵詞或公司命中把關；cp6
「loan」／「loans」是泛用財經詞。這些會不會真的造成雜訊，留給「投資想法校準」的無關佔比
（見上方「週度自動校準」段檢查④）觀察幾週後判斷，不在這次任務裡動 ideas.json。

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
