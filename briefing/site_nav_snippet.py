"""Canonical InvestMQuest site header (imq-nav) — shared nav snippet.

synced from financial-analysis-bot/scripts/site_nav.py — do not edit by hand.

Each NAV_BLOCK_* is the byte-identical output of
site_nav.full_nav_block(group, item) (style + <header class="imq-nav-root">
+ dropdown script) and must be inserted immediately after the <body...> tag
of every emitted page.

To re-sync after the canonical nav changes, regenerate each literal with:
    python3 -c "import sys; sys.path.insert(0, '<financial-analysis-bot>/scripts'); \\
        import site_nav; print(site_nav.full_nav_block('market', 'week'))"
(and the 'earn' variant; BRIEF uses full_nav_block('market', None)).

Synced 2026-07-07（整站 IA v2：三群 研究/市場/工具 → 四群 選股/研究/市場/系統；
每日簡報已暫停自 nav 選單移除，NAV_BLOCK_BRIEF 改為 ('market', None) 僅群高亮）。
2026-07-09 補：市場群加入「總經深度報告」(/macro/)，BRIEF/WEEK/EARN 三塊皆已同步。
2026-07-10 補：市場群加入「市場監測」(/monitor/)，BRIEF/WEEK/EARN 三塊皆已同步。
2026-07-10 補：選股主控台整併——精選清單／Pipeline 漏斗／決策引擎三條收斂進
/cockpit/ 單一入口（標籤改「選股主控台」），下拉自 9 條瘦身為 6 條，BRIEF/WEEK/EARN 三塊皆已同步。
"""

# group='market', item=None  (daily briefing pages, /briefing/ — 簡報項已自選單移除)
NAV_BLOCK_BRIEF = """<style id="imq-nav-style">
.imq-nav-root{background:linear-gradient(135deg,#081832 0%,#173564 100%);padding:.7rem 20px;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.12);position:sticky;top:0;z-index:1000;font-family:'Inter','Noto Sans TC',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.imq-nav-inner{max-width:1140px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.imq-logo{font-weight:700;color:#fff !important;text-decoration:none !important;font-size:15px;letter-spacing:-.02em;flex-shrink:0;background:none !important;padding:0 !important}
.imq-logo:hover{color:#fff !important;text-decoration:none !important}
.imq-logo span{color:#d4b576}
.imq-menu{display:flex;align-items:center;gap:.15rem;flex-wrap:wrap;margin:0;padding:0;list-style:none}
.imq-menu > a,.imq-dd-btn{color:rgba(255,255,255,.7) !important;font-size:.8rem;font-weight:500;padding:.42rem .72rem;border-radius:6px;transition:all .15s;background:none;border:0;font-family:inherit;cursor:pointer;text-decoration:none !important;display:inline-flex;align-items:center;gap:.28rem;line-height:1.2;letter-spacing:0}
.imq-menu > a:hover,.imq-dd-btn:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-menu > a.active,.imq-dd.active > .imq-dd-btn{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-dd{position:relative;display:inline-block}
.imq-dd-menu{display:none;position:absolute;top:100%;left:0;background:#0d2244;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.35rem 0;min-width:180px;box-shadow:0 10px 28px rgba(0,0,0,.3);z-index:1001}
.imq-dd:hover .imq-dd-menu,.imq-dd:focus-within .imq-dd-menu,.imq-dd.open .imq-dd-menu{display:block}
.imq-dd-menu a{display:block;padding:.55rem 1rem;color:rgba(255,255,255,.75) !important;font-size:.78rem;text-decoration:none !important;white-space:nowrap;transition:all .12s;font-weight:500}
.imq-dd-menu a:hover{color:#fff !important;background:rgba(184,146,74,.20)}
.imq-dd-menu a.active{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-caret{font-size:.6rem;opacity:.7;margin-top:1px}
.imq-subnav{background:#081832;padding:.45rem 20px;font-family:'Inter','Noto Sans TC',-apple-system,sans-serif}
.imq-subnav-inner{max-width:1140px;margin:0 auto;display:flex;gap:.3rem;flex-wrap:wrap}
.imq-subnav a{color:rgba(255,255,255,.55) !important;font-size:.74rem;font-weight:500;padding:.28rem .6rem;border-radius:5px;text-decoration:none !important}
.imq-subnav a:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-subnav a.active{color:#fff !important;background:rgba(184,146,74,.30);font-weight:600}
@media(max-width:768px){
  .imq-nav-root{padding:.55rem 12px}
  .imq-nav-inner{gap:.4rem}
  .imq-menu{width:100%;justify-content:flex-start;gap:.1rem}
  .imq-menu > a,.imq-dd-btn{font-size:.74rem;padding:.32rem .5rem}
  .imq-dd-menu{position:static;display:none;min-width:auto;box-shadow:none;background:rgba(255,255,255,.04);border:none;padding:.1rem 0 .3rem 1rem;margin:.1rem 0}
  .imq-dd.open .imq-dd-menu{display:block}
}
</style>
<header class="imq-nav-root">
  <div class="imq-nav-inner">
    <a class="imq-logo" href="/">InvestMQuest<span>.</span> Research</a>
    <nav class="imq-menu">
      <a href="/">首頁</a>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">選股<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/cockpit/">選股主控台</a>
          <a href="/dd-screener/">DD Screener</a>
          <a href="/research/momentum-5/">Momentum-5</a>
          <a href="/qgm/">QGM 美股</a>
          <a href="/qgm-tw/">QGM 台股</a>
          <a href="/screeners.html">RS+VCP Screener</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">研究<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/research/">個股 DD</a>
          <a href="/research/synthesis/">期望落差綜合研判</a>
          <a href="/comparisons/">多股對比</a>
          <a href="/id/">產業深度 ID</a>
          <a href="/id/tier_matrix.html">Tier Matrix</a>
          <a href="/supply-chain/">供應鏈地圖</a>
        </div>
      </div>
      <div class="imq-dd active">
        <button type="button" class="imq-dd-btn">市場<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/earnings/">財報分析</a>
          <a href="/catalyst/">催化劑日曆</a>
          <a href="/monitor/">市場監測</a>
          <a href="/markets.html">Markets</a>
          <a href="/sectors.html">Sectors</a>
          <a href="/crowding/">擁擠交易監測</a>
          <a href="/rotation/">產業輪動</a>
          <a href="/regime/">大類資產 regime</a>
          <a href="/macro/">總經深度報告</a>
          <a href="/weekly/">週報</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">系統<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/long-track-smh/">長線訊號 SMH</a>
          <a href="/long-track-tw/">台股長線</a>
          <a href="/turtle-sleeve/">商品 Sleeve</a>
          <a href="/backtest/">量化回測</a>
          <a href="/tools/">期貨部位計算機</a>
          <a href="/cache/">Data Cache</a>
        </div>
      </div>
      <a href="/mental-models/">心智模型</a>
      <a href="/how-to.html">使用說明</a>
    </nav>
  </div>
</header>
<script>(function(){document.querySelectorAll('.imq-dd-btn').forEach(function(btn){btn.addEventListener('click',function(e){e.preventDefault();var dd=btn.closest('.imq-dd');document.querySelectorAll('.imq-dd.open').forEach(function(d){if(d!==dd)d.classList.remove('open')});dd.classList.toggle('open')})});document.addEventListener('click',function(e){if(!e.target.closest('.imq-dd'))document.querySelectorAll('.imq-dd.open').forEach(function(d){d.classList.remove('open')})});})();</script>"""

# group='market', item='week'  (weekly report pages, /weekly/)
NAV_BLOCK_WEEK = """<style id="imq-nav-style">
.imq-nav-root{background:linear-gradient(135deg,#081832 0%,#173564 100%);padding:.7rem 20px;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.12);position:sticky;top:0;z-index:1000;font-family:'Inter','Noto Sans TC',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.imq-nav-inner{max-width:1140px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.imq-logo{font-weight:700;color:#fff !important;text-decoration:none !important;font-size:15px;letter-spacing:-.02em;flex-shrink:0;background:none !important;padding:0 !important}
.imq-logo:hover{color:#fff !important;text-decoration:none !important}
.imq-logo span{color:#d4b576}
.imq-menu{display:flex;align-items:center;gap:.15rem;flex-wrap:wrap;margin:0;padding:0;list-style:none}
.imq-menu > a,.imq-dd-btn{color:rgba(255,255,255,.7) !important;font-size:.8rem;font-weight:500;padding:.42rem .72rem;border-radius:6px;transition:all .15s;background:none;border:0;font-family:inherit;cursor:pointer;text-decoration:none !important;display:inline-flex;align-items:center;gap:.28rem;line-height:1.2;letter-spacing:0}
.imq-menu > a:hover,.imq-dd-btn:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-menu > a.active,.imq-dd.active > .imq-dd-btn{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-dd{position:relative;display:inline-block}
.imq-dd-menu{display:none;position:absolute;top:100%;left:0;background:#0d2244;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.35rem 0;min-width:180px;box-shadow:0 10px 28px rgba(0,0,0,.3);z-index:1001}
.imq-dd:hover .imq-dd-menu,.imq-dd:focus-within .imq-dd-menu,.imq-dd.open .imq-dd-menu{display:block}
.imq-dd-menu a{display:block;padding:.55rem 1rem;color:rgba(255,255,255,.75) !important;font-size:.78rem;text-decoration:none !important;white-space:nowrap;transition:all .12s;font-weight:500}
.imq-dd-menu a:hover{color:#fff !important;background:rgba(184,146,74,.20)}
.imq-dd-menu a.active{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-caret{font-size:.6rem;opacity:.7;margin-top:1px}
.imq-subnav{background:#081832;padding:.45rem 20px;font-family:'Inter','Noto Sans TC',-apple-system,sans-serif}
.imq-subnav-inner{max-width:1140px;margin:0 auto;display:flex;gap:.3rem;flex-wrap:wrap}
.imq-subnav a{color:rgba(255,255,255,.55) !important;font-size:.74rem;font-weight:500;padding:.28rem .6rem;border-radius:5px;text-decoration:none !important}
.imq-subnav a:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-subnav a.active{color:#fff !important;background:rgba(184,146,74,.30);font-weight:600}
@media(max-width:768px){
  .imq-nav-root{padding:.55rem 12px}
  .imq-nav-inner{gap:.4rem}
  .imq-menu{width:100%;justify-content:flex-start;gap:.1rem}
  .imq-menu > a,.imq-dd-btn{font-size:.74rem;padding:.32rem .5rem}
  .imq-dd-menu{position:static;display:none;min-width:auto;box-shadow:none;background:rgba(255,255,255,.04);border:none;padding:.1rem 0 .3rem 1rem;margin:.1rem 0}
  .imq-dd.open .imq-dd-menu{display:block}
}
</style>
<header class="imq-nav-root">
  <div class="imq-nav-inner">
    <a class="imq-logo" href="/">InvestMQuest<span>.</span> Research</a>
    <nav class="imq-menu">
      <a href="/">首頁</a>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">選股<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/cockpit/">選股主控台</a>
          <a href="/dd-screener/">DD Screener</a>
          <a href="/research/momentum-5/">Momentum-5</a>
          <a href="/qgm/">QGM 美股</a>
          <a href="/qgm-tw/">QGM 台股</a>
          <a href="/screeners.html">RS+VCP Screener</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">研究<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/research/">個股 DD</a>
          <a href="/research/synthesis/">期望落差綜合研判</a>
          <a href="/comparisons/">多股對比</a>
          <a href="/id/">產業深度 ID</a>
          <a href="/id/tier_matrix.html">Tier Matrix</a>
          <a href="/supply-chain/">供應鏈地圖</a>
        </div>
      </div>
      <div class="imq-dd active">
        <button type="button" class="imq-dd-btn">市場<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/earnings/">財報分析</a>
          <a href="/catalyst/">催化劑日曆</a>
          <a href="/monitor/">市場監測</a>
          <a href="/markets.html">Markets</a>
          <a href="/sectors.html">Sectors</a>
          <a href="/crowding/">擁擠交易監測</a>
          <a href="/rotation/">產業輪動</a>
          <a href="/regime/">大類資產 regime</a>
          <a href="/macro/">總經深度報告</a>
          <a href="/weekly/" class="active">週報</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">系統<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/long-track-smh/">長線訊號 SMH</a>
          <a href="/long-track-tw/">台股長線</a>
          <a href="/turtle-sleeve/">商品 Sleeve</a>
          <a href="/backtest/">量化回測</a>
          <a href="/tools/">期貨部位計算機</a>
          <a href="/cache/">Data Cache</a>
        </div>
      </div>
      <a href="/mental-models/">心智模型</a>
      <a href="/how-to.html">使用說明</a>
    </nav>
  </div>
</header>
<script>(function(){document.querySelectorAll('.imq-dd-btn').forEach(function(btn){btn.addEventListener('click',function(e){e.preventDefault();var dd=btn.closest('.imq-dd');document.querySelectorAll('.imq-dd.open').forEach(function(d){if(d!==dd)d.classList.remove('open')});dd.classList.toggle('open')})});document.addEventListener('click',function(e){if(!e.target.closest('.imq-dd'))document.querySelectorAll('.imq-dd.open').forEach(function(d){d.classList.remove('open')})});})();</script>"""

# group='market', item='earn'  (earnings pages, /earnings/)
NAV_BLOCK_EARN = """<style id="imq-nav-style">
.imq-nav-root{background:linear-gradient(135deg,#081832 0%,#173564 100%);padding:.7rem 20px;font-size:13px;box-shadow:0 1px 3px rgba(0,0,0,.12);position:sticky;top:0;z-index:1000;font-family:'Inter','Noto Sans TC',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.imq-nav-inner{max-width:1140px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}
.imq-logo{font-weight:700;color:#fff !important;text-decoration:none !important;font-size:15px;letter-spacing:-.02em;flex-shrink:0;background:none !important;padding:0 !important}
.imq-logo:hover{color:#fff !important;text-decoration:none !important}
.imq-logo span{color:#d4b576}
.imq-menu{display:flex;align-items:center;gap:.15rem;flex-wrap:wrap;margin:0;padding:0;list-style:none}
.imq-menu > a,.imq-dd-btn{color:rgba(255,255,255,.7) !important;font-size:.8rem;font-weight:500;padding:.42rem .72rem;border-radius:6px;transition:all .15s;background:none;border:0;font-family:inherit;cursor:pointer;text-decoration:none !important;display:inline-flex;align-items:center;gap:.28rem;line-height:1.2;letter-spacing:0}
.imq-menu > a:hover,.imq-dd-btn:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-menu > a.active,.imq-dd.active > .imq-dd-btn{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-dd{position:relative;display:inline-block}
.imq-dd-menu{display:none;position:absolute;top:100%;left:0;background:#0d2244;border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:.35rem 0;min-width:180px;box-shadow:0 10px 28px rgba(0,0,0,.3);z-index:1001}
.imq-dd:hover .imq-dd-menu,.imq-dd:focus-within .imq-dd-menu,.imq-dd.open .imq-dd-menu{display:block}
.imq-dd-menu a{display:block;padding:.55rem 1rem;color:rgba(255,255,255,.75) !important;font-size:.78rem;text-decoration:none !important;white-space:nowrap;transition:all .12s;font-weight:500}
.imq-dd-menu a:hover{color:#fff !important;background:rgba(184,146,74,.20)}
.imq-dd-menu a.active{color:#fff !important;background:rgba(184,146,74,.26);font-weight:600}
.imq-caret{font-size:.6rem;opacity:.7;margin-top:1px}
.imq-subnav{background:#081832;padding:.45rem 20px;font-family:'Inter','Noto Sans TC',-apple-system,sans-serif}
.imq-subnav-inner{max-width:1140px;margin:0 auto;display:flex;gap:.3rem;flex-wrap:wrap}
.imq-subnav a{color:rgba(255,255,255,.55) !important;font-size:.74rem;font-weight:500;padding:.28rem .6rem;border-radius:5px;text-decoration:none !important}
.imq-subnav a:hover{color:#fff !important;background:rgba(255,255,255,.08)}
.imq-subnav a.active{color:#fff !important;background:rgba(184,146,74,.30);font-weight:600}
@media(max-width:768px){
  .imq-nav-root{padding:.55rem 12px}
  .imq-nav-inner{gap:.4rem}
  .imq-menu{width:100%;justify-content:flex-start;gap:.1rem}
  .imq-menu > a,.imq-dd-btn{font-size:.74rem;padding:.32rem .5rem}
  .imq-dd-menu{position:static;display:none;min-width:auto;box-shadow:none;background:rgba(255,255,255,.04);border:none;padding:.1rem 0 .3rem 1rem;margin:.1rem 0}
  .imq-dd.open .imq-dd-menu{display:block}
}
</style>
<header class="imq-nav-root">
  <div class="imq-nav-inner">
    <a class="imq-logo" href="/">InvestMQuest<span>.</span> Research</a>
    <nav class="imq-menu">
      <a href="/">首頁</a>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">選股<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/cockpit/">選股主控台</a>
          <a href="/dd-screener/">DD Screener</a>
          <a href="/research/momentum-5/">Momentum-5</a>
          <a href="/qgm/">QGM 美股</a>
          <a href="/qgm-tw/">QGM 台股</a>
          <a href="/screeners.html">RS+VCP Screener</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">研究<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/research/">個股 DD</a>
          <a href="/research/synthesis/">期望落差綜合研判</a>
          <a href="/comparisons/">多股對比</a>
          <a href="/id/">產業深度 ID</a>
          <a href="/id/tier_matrix.html">Tier Matrix</a>
          <a href="/supply-chain/">供應鏈地圖</a>
        </div>
      </div>
      <div class="imq-dd active">
        <button type="button" class="imq-dd-btn">市場<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/earnings/" class="active">財報分析</a>
          <a href="/catalyst/">催化劑日曆</a>
          <a href="/monitor/">市場監測</a>
          <a href="/markets.html">Markets</a>
          <a href="/sectors.html">Sectors</a>
          <a href="/crowding/">擁擠交易監測</a>
          <a href="/rotation/">產業輪動</a>
          <a href="/regime/">大類資產 regime</a>
          <a href="/macro/">總經深度報告</a>
          <a href="/weekly/">週報</a>
        </div>
      </div>
      <div class="imq-dd">
        <button type="button" class="imq-dd-btn">系統<span class="imq-caret">▾</span></button>
        <div class="imq-dd-menu">
          <a href="/long-track-smh/">長線訊號 SMH</a>
          <a href="/long-track-tw/">台股長線</a>
          <a href="/turtle-sleeve/">商品 Sleeve</a>
          <a href="/backtest/">量化回測</a>
          <a href="/tools/">期貨部位計算機</a>
          <a href="/cache/">Data Cache</a>
        </div>
      </div>
      <a href="/mental-models/">心智模型</a>
      <a href="/how-to.html">使用說明</a>
    </nav>
  </div>
</header>
<script>(function(){document.querySelectorAll('.imq-dd-btn').forEach(function(btn){btn.addEventListener('click',function(e){e.preventDefault();var dd=btn.closest('.imq-dd');document.querySelectorAll('.imq-dd.open').forEach(function(d){if(d!==dd)d.classList.remove('open')});dd.classList.toggle('open')})});document.addEventListener('click',function(e){if(!e.target.closest('.imq-dd'))document.querySelectorAll('.imq-dd.open').forEach(function(d){d.classList.remove('open')})});})();</script>"""
