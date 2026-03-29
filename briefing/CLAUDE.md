# CLAUDE.md — briefing/

## 檔案職責
main.py → 日報主流程，串接所有模組
news_fetcher.py → Perplexity 查詢 + yfinance 行情 + FRED 流動性
ai_processor.py → Claude API streaming，輸出 JSON，含 _validate 預設值
html_template.py → JSON → HTML，所有區塊渲染函式
email_sender.py → Resend API 寄信
weekly_main.py → 週報主流程
weekly_fetcher.py → 週報 Perplexity 查詢
weekly_processor.py → 週報 Claude 分析
weekly_template.py → 週報 HTML 渲染

## 市場數據規則
- 所有 ticker 用 period="7d", interval="1d"
- 取 dropna() 後 iloc[-1]（最新）和 iloc[-2]（前一日）計算漲跌
- 漲跌格式：▲/▼ X.XX%，美10Y用bps（▲/▼ Xbps）
- 反向指標（漲=紅）：VIX、VIX9D、VVIX、MOVE
- NDX 現貨（^NDX）用於分析，NQ 期貨已移除
- NYFANG ticker = FNGS（不是 ^NFG）

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

## 情緒歷史趨勢
- VIX/VVIX/SKEW/VIX9D 用 period="10d" 抓5日歷史
- 計算：趨勢方向（連續回落/持續上升/震盪）、見頂天數、峰值回落幅度
- 第三階段判斷：vvix_peak_days_ago >= 2 且 VIX > 35 且 SKEW < 120
- 第二層趨勢（只傳方向）：HYG、DXY、10Y、黃金、BTC、RSP/SPY、IWM/SPY

## 顏色規範
上漲：#0F6E56，下跌：#C0392B，中性：#888888
類別色塊：股票#1B3A5C、因子#7F77DD、情緒#BA7517、原物料#854F0B
債券#185FA5、外匯#534AB7、信貸#0F6E56、流動性#085041

## HTML 排版規則
- 全部用 table 排版（Email 客戶端相容性）
- 不用 CSS Grid 或 Flexbox
- JSON 數值用英文格式（不用中文億/兆，用 B/T）

## 日報 build_html 區塊順序
1.masthead+summary 2.alert 3._market_strip 4._index_factor_reading
5._sentiment_analysis 6._market_pulse 7._daily_deep_dive
8.top_stories 9.world_news 10.us_market_recap 11.macro
12.geopolitical 13.ai_industry 14.regional_tech 15.fintech_crypto
16.system_status 17.tech_trends 18.startup_news 19.smart_money
20.earnings_preview 21.implied_trends 22.fun_fact 23.today_events 24.footer

## 去重順序（最高優先級）
tech_trends → daily_deep_dive → top_stories → world_news →
macro → geopolitical → ai_industry → regional_tech →
fintech_crypto → startup_news → us_market_recap → smart_money

## 週報主題順序
central_bank → liquidity → credit → options →
ai_industry → semiconductor → earnings → macro → commodities → black_swan
