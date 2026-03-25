"""
html_template.py
----------------
將 ai_processor.py 輸出的 JSON 轉為 HTML Email。

版面順序：
  masthead → daily_summary → alert → 市場數據 → 核心要聞
  → 總經 → AI產業動態 → 地緣政治 → 全球科技 → Fintech/加密
  → 系統狀態 → 硬核科技趨勢 → 新創產業 → 本週財報預告
  → 隱含趨勢 → 財經冷知識 → 今日行程 → footer
"""

from datetime import datetime
import pytz


SENTIMENT_COLOR = {"pos": "#1a7a4a", "neg": "#C0392B", "neu": "#888780"}

TAG_STYLE = {
    "macro": "background:#EBF2FA;color:#185FA5;",
    "geo":   "background:#FCF0EC;color:#993C1D;",
    "tech":  "background:#EAF3DE;color:#3B6D11;",
    "cb":    "background:#F0EDF8;color:#534AB7;",
}

CHIP_STYLE = {
    "up":    "background:#EAF3DE;color:#3B6D11;",
    "risk":  "background:#FCF0EC;color:#993C1D;",
    "watch": "background:#F0EDF8;color:#534AB7;",
    "new":   "background:#E1F5EE;color:#0F6E56;",
    "amber": "background:#FAF0DA;color:#854F0B;",
}

IMPORTANCE_BADGE = {
    "high":   "background:#FEF3CD;color:#856404;font-size:12px;padding:1px 6px;border-radius:3px;",
    "medium": "",
}

ACCENT_COLOR = {
    "robotics": "#1D9E75", "arch": "#7F77DD", "infra_ai": "#378ADD",
    "science": "#BA7517", "defense": "#639922", "ai_gov": "#378ADD",
    "health": "#1D9E75", "fintech": "#D4537E", "cyber": "#D85A30", "other": "#888780",
}

LABEL_TAG_STYLE = {
    "robotics":  "background:#E1F5EE;color:#0F6E56;",
    "arch":      "background:#F0EDF8;color:#534AB7;",
    "infra_ai":  "background:#EBF2FA;color:#185FA5;",
    "science":   "background:#FAF0DA;color:#854F0B;",
    "other":     "background:#EBF2FA;color:#185FA5;",
}

STARTUP_TAG_STYLE = {
    "defense": "background:#EAF3DE;color:#3B6D11;",
    "ai":      "background:#EBF2FA;color:#185FA5;",
    "health":  "background:#E1F5EE;color:#0F6E56;",
    "fintech": "background:#FBEAF0;color:#993556;",
    "other":   "background:#EBF2FA;color:#185FA5;",
}

REGION_LABEL = {
    "taiwan": "🇹🇼 台灣", "japan": "🇯🇵 日本",
    "us": "🇺🇸 美國", "malaysia": "🇲🇾 馬來西亞",
    "korea": "🇰🇷 韓國", "china": "🇨🇳 中國", "europe": "🇪🇺 歐洲",
}

REGION_COLOR = {
    "taiwan": "#185FA5", "japan": "#C0392B",
    "us": "#1a7a4a", "malaysia": "#854F0B",
    "korea": "#1a7a4a", "china": "#C0392B", "europe": "#534AB7",
}

BASE_CSS = """
* { box-sizing:border-box; margin:0; padding:0; }
body { font-family:Arial,sans-serif; max-width:720px; margin:0 auto;
       padding:24px 20px; color:#222; background:#fff; }
.section { margin-bottom:28px; }
.section-label { font-size:13px; letter-spacing:1.8px; text-transform:uppercase;
                 font-weight:500; color:#888; border-bottom:0.5px solid #e0e0e0;
                 padding-bottom:5px; margin-bottom:14px; display:flex;
                 justify-content:space-between; align-items:center; }
.importance-high { background:#FEF3CD; color:#856404; font-size:12px;
                   padding:1px 6px; border-radius:3px; font-weight:500; }
"""


def _source_line(source: str, source_date: str) -> str:
    if not source and not source_date:
        return ""
    parts = []
    if source_date:
        parts.append(source_date)
    if source:
        parts.append(source)
    text = " · ".join(parts)
    return f'''<div style="font-size:13px;color:#aaa;margin-top:4px;">{text}</div>'''


def _importance_badge(importance: str) -> str:
    if importance == "high":
        return '''<span style="background:#FEF3CD;color:#856404;font-size:12px;padding:1px 6px;border-radius:3px;font-weight:500;margin-left:6px;">重要</span>'''
    return ""


def _masthead(now_str: str) -> str:
    return f'''
<div style="border-bottom:2px solid #1B3A5C;padding-bottom:12px;
            margin-bottom:16px;display:flex;justify-content:space-between;
            align-items:flex-end;">
  <div>
    <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;
                color:#888;margin-bottom:4px;">MORNING BRIEFING</div>
    <div style="font-family:Georgia,serif;font-size:26px;font-weight:700;
                color:#1B3A5C;">每日財經晨報</div>
  </div>
  <div style="font-size:13px;color:#888;text-align:right;line-height:1.8;">
    Ivan's Financial Daily<br>US · Asia · Europe · NQ100<br>
    <span style="color:#1B3A5C;font-weight:500;">{now_str}</span>
  </div>
</div>'''


def _daily_summary(text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="background:#1B3A5C;color:#fff;border-radius:6px;padding:12px 16px;
            margin-bottom:16px;font-size:16px;font-weight:500;line-height:1.5;">
  📌 {text}
</div>'''


def _alert(text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="background:#FFF8F0;border-left:3px solid #C0392B;border-radius:0 6px 6px 0;
            padding:10px 14px;margin-bottom:16px;">
  <div style="font-size:15px;font-weight:500;color:#222;">⚡ {text}</div>
</div>'''


def _market_cell_from_item(item: dict) -> str:
    color = SENTIMENT_COLOR.get(item.get("dir", "neu"), "#888")
    label = item.get("label", "—")
    return f'''<td style="background:#fff;padding:10px 12px;border-right:1px solid #e8e8e8;
                border-bottom:1px solid #e8e8e8;vertical-align:top;width:20%;">
  <div style="font-size:11px;letter-spacing:0.8px;text-transform:uppercase;
              color:#888;margin-bottom:4px;">{label}</div>
  <div style="font-size:17px;font-weight:500;color:#222;margin-bottom:2px;">{item.get("val","—")}</div>
  <div style="font-size:13px;color:{color};">{item.get("chg","—")}</div>
</td>'''


def _market_table(items: list[dict]) -> str:
    cells = "".join(_market_cell_from_item(it) for it in items)
    return f'''<table width="100%" cellpadding="0" cellspacing="0"
         style="border:1px solid #e8e8e8;border-radius:6px;overflow:hidden;border-collapse:collapse;">
    <tr>{cells}</tr>
  </table>'''


def _market_strip(market_data: dict) -> str:
    fixed = market_data.get("fixed", [])
    fear_greed = market_data.get("fear_greed", {"val": "—", "chg": "—", "dir": "neu"})
    dynamic = market_data.get("dynamic", [])

    # Build lookup by key for fixed items
    fixed_by_key = {it.get("key", ""): it for it in fixed}
    def _get(key, fallback_label="—"):
        return fixed_by_key.get(key, {"label": fallback_label, "val": "—", "chg": "—", "dir": "neu"})

    # Row 1: NQ100, S&P 500, 費半, VIX, 台灣加權
    row1 = [_get("nq100", "NQ100"), _get("sp500", "S&P500"), _get("sox", "費半"),
            _get("vix", "VIX"), _get("twii", "台灣加權")]

    # Row 2: Brent油, 黃金, 白銀, 銅, DXY
    row2 = [_get("brent", "Brent油"), _get("gold", "黃金"), _get("silver", "白銀"),
            _get("copper", "銅"), _get("dxy", "DXY")]

    # Row 3: 美10Y, BTC, CNN Fear&Greed + dynamic (2-3)
    fg_item = {"label": "Fear&Greed", "val": fear_greed.get("val", "—"),
               "chg": fear_greed.get("chg", "—"), "dir": fear_greed.get("dir", "neu")}
    row3_base = [_get("us10y", "美10Y"), _get("btc", "BTC"), fg_item]
    # Add dynamic picks (up to 2 to fill 5 cells)
    for d in dynamic[:2]:
        row3_base.append(d)
    # Pad to 5 if needed
    while len(row3_base) < 5:
        row3_base.append({"label": "—", "val": "—", "chg": "—", "dir": "neu"})

    return f'''
<div class="section">
  <div class="section-label">市場即時數據</div>
  {_market_table(row1)}
  <div style="height:8px;"></div>
  {_market_table(row2)}
  <div style="height:8px;"></div>
  {_market_table(row3_base)}
</div>'''


def _news_section(title: str, items: list, tag_style_map: dict | None = None) -> str:
    if not items:
        return ""
    rows = ""
    for s in items:
        importance = s.get("importance", "medium")
        badge = _importance_badge(importance)
        tag = s.get("tag", "")
        tag_type = s.get("tag_type", "macro")
        ts = (tag_style_map or TAG_STYLE).get(tag_type, TAG_STYLE["macro"])
        source_html = _source_line(s.get("source",""), s.get("source_date",""))
        rows += f'''
<div style="padding:12px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:5px;">
    <div style="font-size:16px;font-weight:500;color:#222;line-height:1.5;flex:1;">
      {s.get("headline","")}{badge}
    </div>
    <span style="font-size:12px;font-weight:500;padding:2px 7px;border-radius:3px;
                 white-space:nowrap;{ts}">{tag}</span>
  </div>
  <div style="font-size:15px;color:#555;line-height:1.65;">{s.get("body","")}</div>
  {source_html}
</div>'''
    return f'''
<div class="section">
  <div class="section-label">{title}</div>{rows}
</div>'''


def _geopolitical_section(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for s in items:
        importance = s.get("importance", "medium")
        badge = _importance_badge(importance)
        region = s.get("region", "其他")
        source_html = _source_line(s.get("source",""), s.get("source_date",""))
        rows += f'''
<div style="display:grid;grid-template-columns:3px 1fr;gap:12px;
            padding:11px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="background:#D85A30;border-radius:2px;"></div>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;">
      <div style="font-size:16px;font-weight:500;color:#222;flex:1;">{s.get("headline","")}{badge}</div>
      <span style="font-size:12px;font-weight:500;padding:2px 7px;border-radius:3px;
                   white-space:nowrap;background:#FCF0EC;color:#993C1D;">{region}</span>
    </div>
    <div style="font-size:15px;color:#555;line-height:1.65;">{s.get("body","")}</div>
    {source_html}
  </div>
</div>'''
    return f'''
<div class="section">
  <div class="section-label">地緣政治風險</div>{rows}
</div>'''


def _regional_tech_section(regional: dict) -> str:
    content = ""
    for region in ["taiwan", "japan", "us", "malaysia", "korea", "china", "europe"]:
        items = regional.get(region, [])
        if not items:
            continue
        label = REGION_LABEL.get(region, region)
        color = REGION_COLOR.get(region, "#888")
        rows = ""
        for s in items:
            badge = _importance_badge(s.get("importance","medium"))
            source_html = _source_line(s.get("source",""), s.get("source_date",""))
            rows += f'''
<div style="padding:8px 0;border-bottom:0.5px solid #f5f5f5;">
  <div style="font-size:15px;font-weight:500;color:#222;margin-bottom:3px;">{s.get("headline","")}{badge}</div>
  <div style="font-size:14px;color:#555;line-height:1.6;">{s.get("body","")}</div>
  {source_html}
</div>'''
        content += f'''
<div style="margin-bottom:16px;">
  <div style="font-size:13px;font-weight:500;color:{color};letter-spacing:1px;
              border-left:3px solid {color};padding-left:8px;margin-bottom:8px;">{label}</div>
  {rows}
</div>'''
    if not content:
        return ""
    return f'''
<div class="section">
  <div class="section-label">全球科技產業動態</div>{content}
</div>'''


def _fintech_crypto_section(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for s in items:
        badge = _importance_badge(s.get("importance","medium"))
        tag = s.get("tag", "Fintech")
        tag_colors = {
            "Crypto": "background:#F0EDF8;color:#534AB7;",
            "DeFi":   "background:#F0EDF8;color:#534AB7;",
            "Stablecoin": "background:#F0EDF8;color:#534AB7;",
        }
        ts = tag_colors.get(tag, "background:#FBEAF0;color:#993556;")
        source_html = _source_line(s.get("source",""), s.get("source_date",""))
        rows += f'''
<div style="padding:11px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;">
    <div style="font-size:16px;font-weight:500;color:#222;flex:1;">{s.get("headline","")}{badge}</div>
    <span style="font-size:12px;font-weight:500;padding:2px 7px;border-radius:3px;
                 white-space:nowrap;{ts}">{tag}</span>
  </div>
  <div style="font-size:15px;color:#555;line-height:1.65;">{s.get("body","")}</div>
  {source_html}
</div>'''
    return f'''
<div class="section">
  <div class="section-label">Fintech · 加密貨幣</div>{rows}
</div>'''


def _status_grid(status: dict) -> str:
    def cell(item, is_fixed):
        bg = "#f7f7f5" if is_fixed else "#fff"
        dot_color = "#888" if is_fixed else "#7F77DD"
        val_color = SENTIMENT_COLOR.get(item.get("sentiment","neu"), "#888")
        return f'''
<div style="padding:10px 12px;border-right:0.5px solid #e8e8e8;
            border-bottom:0.5px solid #e8e8e8;background:{bg};">
  <div style="font-size:12px;color:#888;margin-bottom:3px;display:flex;align-items:center;gap:4px;">
    <span style="width:5px;height:5px;border-radius:50%;background:{dot_color};
                 display:inline-block;"></span>{item.get("name","")}
  </div>
  <div style="font-size:16px;font-weight:500;color:{val_color};">{item.get("val","")}</div>
  <div style="font-size:13px;color:#888;margin-top:2px;">{item.get("sub","")}</div>
</div>'''
    fixed = "".join(cell(i, True) for i in status.get("fixed",[]))
    dynamic = "".join(cell(i, False) for i in status.get("dynamic",[]))
    return f'''
<div class="section">
  <div class="section-label">系統狀態評估
    <span style="font-size:12px;color:#888;font-weight:400;letter-spacing:0;">
      <span style="width:5px;height:5px;border-radius:50%;background:#888;display:inline-block;margin-right:3px;"></span>固定
      <span style="width:5px;height:5px;border-radius:50%;background:#7F77DD;display:inline-block;margin:0 3px 0 8px;"></span>動態
    </span>
  </div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border:0.5px solid #e8e8e8;border-radius:8px;overflow:hidden;border-collapse:collapse;">
    <tr>{fixed}</tr>
    <tr>{dynamic}</tr>
  </table>
</div>'''


def _tech_trends(trends: list) -> str:
    if not trends:
        return ""
    items = ""
    for t in trends:
        accent = ACCENT_COLOR.get(t.get("label_type","other"), "#888")
        ts = LABEL_TAG_STYLE.get(t.get("label_type","other"), LABEL_TAG_STYLE["other"])
        sub_rows = "".join(f'''
<div style="display:grid;grid-template-columns:95px 1fr;gap:8px;font-size:14px;margin-bottom:4px;">
  <span style="color:#888;font-weight:500;">{sub.get("key","")}</span>
  <span style="color:#222;line-height:1.55;">{sub.get("val","")}</span>
</div>''' for sub in t.get("sub_items",[]))
        chips = "".join(f'''<span style="font-size:12px;font-weight:500;padding:2px 8px;border-radius:3px;
                     {CHIP_STYLE.get(c.get("type","watch"),CHIP_STYLE["watch"])}">{c.get("text","")}</span> '''
                        for c in t.get("chips",[]))
        source_html = _source_line(t.get("source",""), t.get("source_date",""))
        items += f'''
<div style="display:grid;grid-template-columns:3px 1fr;gap:12px;padding:14px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="background:{accent};border-radius:2px;"></div>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:6px;">
      <div style="font-size:16px;font-weight:500;color:#222;line-height:1.45;flex:1;">{t.get("headline","")}</div>
      <span style="font-size:12px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;{ts}">{t.get("label","")}</span>
    </div>
    <div style="font-size:15px;color:#555;line-height:1.7;margin-bottom:8px;">{t.get("summary","")}</div>
    <div style="border-top:0.5px solid #f0f0f0;padding-top:8px;margin-bottom:6px;">{sub_rows}</div>
    <div style="display:flex;flex-wrap:wrap;gap:5px;">{chips}</div>
    {source_html}
  </div>
</div>'''
    return f'''
<div class="section">
  <div class="section-label">硬核科技趨勢</div>{items}
</div>'''


def _startup_news(startups: list) -> str:
    if not startups:
        return ""
    items = ""
    for s in startups:
        accent = ACCENT_COLOR.get(s.get("accent","other"), "#888")
        ts = STARTUP_TAG_STYLE.get(s.get("tag_type","other"), STARTUP_TAG_STYLE["other"])
        badge = _importance_badge(s.get("importance","medium"))
        source_html = _source_line(s.get("source",""), s.get("source_date",""))
        items += f'''
<div style="display:grid;grid-template-columns:3px 1fr;gap:12px;padding:10px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="background:{accent};border-radius:2px;"></div>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;">
      <div style="font-size:16px;font-weight:500;color:#222;flex:1;">{s.get("headline","")}{badge}</div>
      <span style="font-size:12px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;{ts}">{s.get("tag","")}</span>
    </div>
    <div style="font-size:15px;color:#555;line-height:1.6;">{s.get("summary","")}</div>
    {source_html}
  </div>
</div>'''
    return f'''
<div class="section">
  <div class="section-label">新創產業發展</div>{items}
</div>'''


DIRECTION_STYLE = {
    "bullish":  "background:#E1F5EE;color:#0F6E56;",
    "bearish":  "background:#FCF0EC;color:#993C1D;",
    "neutral":  "background:#e8e8e8;color:#555;",
}
TYPE_LABEL = {"options": "選擇權", "block": "大宗交易", "etf_flow": "ETF資金流"}


def _smart_money(data: dict) -> str:
    if not data or not data.get("has_signals", False):
        return ""
    signals = data.get("signals", [])[:3]
    if not signals:
        return ""

    summary = data.get("summary", "")
    summary_html = ""
    if summary:
        summary_html = f'''<div style="background:#FEF3CD;border-radius:4px;padding:8px 14px;
            font-size:14px;font-weight:500;color:#856404;line-height:1.5;margin-bottom:10px;">
      📌 {summary}</div>'''

    rows = ""
    for s in signals:
        d = s.get("direction", "neutral")
        d_style = DIRECTION_STYLE.get(d, DIRECTION_STYLE["neutral"])
        d_label = {"bullish": "看多", "bearish": "看空", "neutral": "中性"}.get(d, d)
        t = s.get("type", "")
        t_label = TYPE_LABEL.get(t, t)
        rows += f'''
<div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:0.5px solid #f0f0f0;flex-wrap:wrap;">
  <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;{d_style}">{d_label}</span>
  <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;background:#F0EDF8;color:#534AB7;white-space:nowrap;">{t_label}</span>
  <span style="font-size:15px;font-weight:600;color:#222;">{s.get("ticker","")}</span>
  <span style="font-size:14px;color:#555;flex:1;">{s.get("description","")}</span>
  <span style="font-size:12px;color:#888;white-space:nowrap;">{s.get("significance","")}</span>
</div>'''

    return f'''
<div class="section">
  <div class="section-label">機構異動訊號</div>
  {summary_html}{rows}
</div>'''


REPORT_TIME_STYLE = {
    "before-open":    ("background:#FAF0DA;color:#854F0B;", "開盤前"),
    "after-close":    ("background:#1B3A5C;color:#fff;",    "收盤後"),
    "during-market":  ("background:#EBF2FA;color:#185FA5;", "盤中"),
}


def _earnings_preview(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for e in items:
        rt = e.get("report_time", "after-close")
        rt_style, rt_label = REPORT_TIME_STYLE.get(rt, REPORT_TIME_STYLE["after-close"])

        confirmed = e.get("yfinance_confirmed", False)
        if confirmed:
            confirm_html = '<span style="font-size:11px;color:#1a7a4a;">● 已確認</span>'
        else:
            confirm_html = '<span style="font-size:11px;color:#aaa;">● 待確認</span>'

        eps = e.get("eps_estimate", "")
        rev = e.get("revenue_estimate", "")
        estimates_html = ""
        if eps or rev:
            parts = []
            if eps:
                parts.append(f"EPS預期: {eps}")
            if rev:
                parts.append(f"營收預期: {rev}")
            estimates_html = f'<div style="font-size:13px;color:#888;margin-top:2px;">{" · ".join(parts)}</div>'

        wtw = e.get("what_to_watch", "")
        wtw_html = f'<div style="font-size:13px;color:#555;margin-top:4px;">🔍 {wtw}</div>' if wtw else ""

        rows += f'''
<div style="padding:10px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
    <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;{rt_style}">{rt_label}</span>
    <span style="font-size:16px;font-weight:600;color:#222;">{e.get("company","")}</span>
    <span style="font-size:14px;color:#888;">{e.get("ticker","")}</span>
    {confirm_html}
  </div>
  {estimates_html}
  {wtw_html}
</div>'''
    return f'''
<div class="section">
  <div class="section-label">今日財報預告</div>{rows}
</div>'''


def _implied_trends(trends: list) -> str:
    if not trends:
        return ""
    cards = "".join(f'''
<div style="background:#fff;border-radius:6px;border:0.5px solid #e8e8e8;padding:14px 16px;">
  <div style="font-family:Georgia,serif;font-size:24px;color:#222;line-height:1;margin-bottom:5px;">{t.get("num","")}</div>
  <div style="font-size:15px;font-weight:500;color:#222;margin-bottom:5px;line-height:1.4;">{t.get("title","")}</div>
  <div style="font-size:14px;color:#555;line-height:1.65;">{t.get("desc","")}</div>
  <div style="border-top:0.5px solid #f0f0f0;margin-top:8px;padding-top:7px;
              font-size:14px;color:#555;line-height:1.55;">
    <span style="font-size:12px;font-weight:500;color:#888;">投資含義 ▸ </span>{t.get("implication","")}
  </div>
</div>''' for t in trends)
    return f'''
<div class="section">
  <div style="background:#f7f7f5;border-radius:8px;border:0.5px solid #e8e8e8;padding:16px 18px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;
                margin-bottom:14px;padding-bottom:8px;border-bottom:0.5px solid #e8e8e8;">
      <span style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;
                   font-weight:500;color:#888;">隱含趨勢分析</span>
      <span style="font-size:13px;color:#888;">綜合今日所有新聞萃取的結構性訊號</span>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:10px;">
      <tr>
        <td width="50%" style="vertical-align:top;">{trends[0] and _trend_card(trends[0]) if len(trends)>0 else ""}</td>
        <td width="50%" style="vertical-align:top;">{_trend_card(trends[1]) if len(trends)>1 else ""}</td>
      </tr>
      <tr>
        <td width="50%" style="vertical-align:top;">{_trend_card(trends[2]) if len(trends)>2 else ""}</td>
        <td width="50%" style="vertical-align:top;">{_trend_card(trends[3]) if len(trends)>3 else ""}</td>
      </tr>
    </table>
  </div>
</div>'''


def _trend_card(t: dict) -> str:
    return f'''<div style="background:#fff;border-radius:6px;border:0.5px solid #e8e8e8;padding:14px 16px;">
  <div style="font-family:Georgia,serif;font-size:24px;color:#222;line-height:1;margin-bottom:5px;">{t.get("num","")}</div>
  <div style="font-size:15px;font-weight:500;color:#222;margin-bottom:5px;line-height:1.4;">{t.get("title","")}</div>
  <div style="font-size:14px;color:#555;line-height:1.65;">{t.get("desc","")}</div>
  <div style="border-top:0.5px solid #f0f0f0;margin-top:8px;padding-top:7px;
              font-size:14px;color:#555;line-height:1.55;">
    <span style="font-size:12px;font-weight:500;color:#888;">投資含義 ▸ </span>{t.get("implication","")}
  </div>
</div>'''


def _fun_fact(fact: dict) -> str:
    if not fact or not fact.get("title"):
        return ""
    return f'''
<div class="section">
  <div class="section-label">財經冷知識</div>
  <div style="background:#FFFBEA;border-radius:6px;padding:14px 16px;">
    <div style="font-size:16px;font-weight:500;color:#222;margin-bottom:6px;">💡 {fact.get("title","")}</div>
    <div style="font-size:15px;color:#555;line-height:1.65;margin-bottom:8px;">{fact.get("content","")}</div>
    <div style="font-size:14px;color:#888;border-top:0.5px solid #f0e6c0;padding-top:8px;">
      📎 {fact.get("connection","")}
    </div>
  </div>
</div>'''


DEEP_DIVE_COLOR = {
    "semiconductor": "#378ADD",
    "ai_arch": "#7F77DD",
    "liquidity": "#1a7a4a",
    "energy": "#854F0B",
    "spotlight": "#C0392B",
}


def _daily_deep_dive(items: list) -> str:
    if not items:
        return ""
    cards = ""
    for item in items:
        theme_type = item.get("theme_type", "spotlight")
        color = DEEP_DIVE_COLOR.get(theme_type, "#C0392B")
        theme = item.get("theme", "")
        headline = item.get("headline", "")
        situation = item.get("situation", "")
        structural_signal = item.get("structural_signal", "")
        implication = item.get("implication", "")
        source_html = _source_line(item.get("source", ""), item.get("source_date", ""))

        # key_data table
        key_data = item.get("key_data", [])
        kd_rows = ""
        for kd in key_data:
            kd_rows += f'''<tr>
  <td style="padding:6px 10px;font-size:13px;color:#555;white-space:nowrap;">{kd.get("metric","")}</td>
  <td style="padding:6px 10px;font-size:13px;font-weight:600;color:#222;">{kd.get("value","")}</td>
  <td style="padding:6px 10px;font-size:13px;color:#555;">{kd.get("change","")}</td>
  <td style="padding:6px 10px;font-size:13px;color:#888;">{kd.get("context","")}</td>
</tr>'''
        kd_html = ""
        if kd_rows:
            kd_html = f'''<table width="100%" cellpadding="0" cellspacing="0"
  style="background:#f7f7f5;border-radius:4px;border-collapse:collapse;margin:10px 0;">
  {kd_rows}
</table>'''

        signal_html = ""
        if structural_signal:
            signal_html = f'''<div style="border-left:3px solid #378ADD;padding:8px 12px;margin:10px 0;background:#f8fafd;">
  <div style="font-size:12px;font-weight:500;color:#378ADD;margin-bottom:4px;">結構性訊號</div>
  <div style="font-size:14px;color:#555;line-height:1.6;">{structural_signal}</div>
</div>'''

        impl_html = ""
        if implication:
            impl_html = f'''<div style="border-left:3px solid #1a7a4a;padding:8px 12px;margin:10px 0;background:#f5faf7;">
  <div style="font-size:12px;font-weight:500;color:#1a7a4a;margin-bottom:4px;">投資含義</div>
  <div style="font-size:14px;color:#555;line-height:1.6;">{implication}</div>
</div>'''

        cards += f'''
<div style="border:1px solid #e8e8e8;border-radius:6px;padding:16px 18px;margin-bottom:14px;
            border-left:4px solid {color};">
  <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
    <span style="font-size:12px;font-weight:500;padding:2px 8px;border-radius:3px;
                 color:#fff;background:{color};">{theme}</span>
    <span style="font-size:16px;font-weight:600;color:#222;line-height:1.4;">{headline}</span>
  </div>
  <div style="font-size:14px;color:#555;line-height:1.65;">{situation}</div>
  {kd_html}
  {signal_html}
  {impl_html}
  {source_html}
</div>'''

    return f'''
<div class="section">
  <div class="section-label">每日深度聚焦</div>
  <div style="border:1px solid #e0e0e0;border-radius:8px;padding:16px;background:#fafafa;">
    {cards}
  </div>
</div>'''


def _world_news(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for s in items[:3]:
        importance = s.get("importance", "medium")
        badge = _importance_badge(importance)
        region = s.get("region", "")
        tag = s.get("tag", "")
        source_html = _source_line(s.get("source", ""), s.get("source_date", ""))
        rows += f'''
<div style="padding:11px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px;">
    <div style="font-size:16px;font-weight:500;color:#222;flex:1;line-height:1.5;">{s.get("headline","")}{badge}</div>
    <div style="display:flex;gap:4px;flex-shrink:0;">
      <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;background:#1B3A5C;color:#fff;">{region}</span>
      <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;background:#e8e8e8;color:#555;">{tag}</span>
    </div>
  </div>
  <div style="font-size:15px;color:#555;line-height:1.65;">{s.get("body","")}</div>
  {source_html}
</div>'''
    return f'''
<div class="section">
  <div class="section-label">國際新聞</div>{rows}
</div>'''


SESSION_STYLE = {
    "pre-market":  "background:#e8e8e8;color:#555;",
    "market":      "background:#EBF2FA;color:#185FA5;",
    "after-hours": "background:#1B3A5C;color:#fff;",
}
SESSION_LABEL = {
    "pre-market": "盤前",
    "market": "盤中",
    "after-hours": "盤後",
}


def _session_tag(session: str) -> str:
    style = SESSION_STYLE.get(session, SESSION_STYLE["market"])
    label = SESSION_LABEL.get(session, session)
    return f'<span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;white-space:nowrap;{style}">{label}</span>'


def _us_market_recap(recap: dict) -> str:
    if not recap or not recap.get("has_events", False):
        return ""

    summary = recap.get("summary", "")
    summary_html = ""
    if summary:
        summary_html = f'''
<div style="background:#FEF3CD;border-radius:4px;padding:10px 14px;margin-bottom:14px;
            font-size:15px;font-weight:500;color:#856404;line-height:1.6;">
  📌 {summary}
</div>'''

    # Earnings cards
    earnings_html = ""
    for e in recap.get("earnings", []):
        bm = e.get("beat_miss", "")
        if bm == "beat":
            bm_style = "background:#E1F5EE;color:#0F6E56;"
        elif bm == "miss":
            bm_style = "background:#FCF0EC;color:#993C1D;"
        else:
            bm_style = "background:#e8e8e8;color:#555;"
        bm_label = bm.upper() if bm else "—"

        move = e.get("after_hours_move", "")
        move_color = "#1a7a4a" if "▲" in move or "+" in move else "#C0392B"

        earnings_html += f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:6px;padding:14px 16px;margin-bottom:10px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
    {_session_tag(e.get("session","market"))}
    <span style="font-size:16px;font-weight:600;color:#222;">{e.get("company","")}</span>
    <span style="font-size:14px;color:#888;">{e.get("ticker","")}</span>
    <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;{bm_style}">{bm_label}</span>
  </div>
  <div style="display:flex;gap:0;margin-bottom:8px;">
    <div style="width:4px;background:#1B3A5C;border-radius:2px;flex-shrink:0;"></div>
    <div style="padding:8px 12px;font-size:15px;color:#555;line-height:1.65;font-style:italic;flex:1;">
      {e.get("key_line","")}</div>
  </div>
  <div style="font-size:20px;font-weight:600;color:{move_color};margin-bottom:4px;">{move}</div>
  <div style="font-size:13px;color:#888;line-height:1.5;">{e.get("why_it_matters","")}</div>
</div>'''

    # Other events
    events_html = ""
    for ev in recap.get("other_events", []):
        events_html += f'''
<div style="padding:10px 0;border-bottom:0.5px solid #f0f0f0;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;">
    {_session_tag(ev.get("session","market"))}
    <span style="font-size:11px;font-weight:500;padding:2px 7px;border-radius:3px;
                 background:#F0EDF8;color:#534AB7;">{ev.get("event","")}</span>
    <span style="font-size:15px;font-weight:600;color:#222;">{ev.get("company","")}</span>
  </div>
  <div style="font-size:15px;color:#555;line-height:1.65;margin-bottom:2px;">{ev.get("key_line","")}</div>
  <div style="font-size:13px;color:#888;">{ev.get("market_impact","")}</div>
</div>'''

    return f'''
<div class="section">
  <div class="section-label">昨日美股重點（盤前・盤中・盤後）</div>
  {summary_html}
  {earnings_html}
  {events_html}
</div>'''


def _today_events(events: list) -> str:
    if not events:
        return ""
    rows = "".join(f'''
<div style="display:flex;gap:14px;padding:9px 0;border-bottom:0.5px solid #f0f0f0;align-items:baseline;">
  <div style="font-size:14px;font-weight:500;color:#888;min-width:72px;">{e.get("time","")}</div>
  <div>
    <div style="font-size:16px;color:#222;">{e.get("event","")}</div>
    <div style="font-size:13px;color:#888;margin-top:2px;">{e.get("note","")}</div>
  </div>
</div>''' for e in events)
    return f'''
<div class="section">
  <div class="section-label">今日重要行程</div>{rows}
</div>'''


def _footer() -> str:
    return '''
<div style="font-size:12px;color:#aaa;border-top:0.5px solid #e8e8e8;
            padding-top:12px;margin-top:4px;display:flex;justify-content:space-between;">
  <span>Perplexity · Claude Sonnet · yfinance</span>
  <span>AI輔助整理 · 僅供參考</span>
</div>'''


def build_html(data: dict) -> str:
    tz  = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz).strftime("%Y年%m月%d日 %H:%M TST")

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{BASE_CSS}</style>
</head>
<body>
{_masthead(now)}
{_daily_summary(data.get("daily_summary",""))}
{_alert(data.get("alert",""))}
{_market_strip(data.get("market_data", {}))}
{_news_section("核心要聞", data.get("top_stories",[]))}
{_daily_deep_dive(data.get("daily_deep_dive", []))}
{_world_news(data.get("world_news", []))}
{_news_section("總經動態", data.get("macro",[]))}
{_geopolitical_section(data.get("geopolitical",[]))}
{_news_section("AI 産業動態", data.get("ai_industry",[]), {"macro":"background:#EBF2FA;color:#185FA5;","tech":"background:#EAF3DE;color:#3B6D11;"})}
{_regional_tech_section(data.get("regional_tech", {}))}
{_fintech_crypto_section(data.get("fintech_crypto",[]))}
{_status_grid(data.get("system_status", {}))}
{_tech_trends(data.get("tech_trends",[]))}
{_startup_news(data.get("startup_news",[]))}
{_smart_money(data.get("smart_money", {}))}
{_earnings_preview(data.get("earnings_preview",[]))}
{_implied_trends(data.get("implied_trends",[]))}
{_fun_fact(data.get("fun_fact", {}))}
{_us_market_recap(data.get("us_market_recap", {}))}
{_today_events(data.get("today_events",[]))}
{_footer()}
</body>
</html>"""
