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


MKT_CHG_COLOR = {"pos": "#0F6E56", "neg": "#C0392B", "neu": "#888"}


def _mkt_cell(item: dict, extra_tag: str = "") -> str:
    """Render one market data cell (table-based, email-safe)."""
    d = item.get("dir", "neu")
    color = MKT_CHG_COLOR.get(d, "#888")
    is_dyn = item.get("is_dynamic", False)
    dyn_html = ('<span style="font-size:9px;color:#C0392B;font-weight:600;'
                'position:absolute;top:4px;right:6px;">動態</span>') if is_dyn else ""
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;'
            f'position:relative;">'
            f'{dyn_html}'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">{item.get("label","—")}</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">'
            f'{item.get("val","—")}</div>'
            f'<div style="font-size:12px;color:{color};">{item.get("chg","—")}</div>'
            f'{extra_tag}'
            f'</td>')


def _mkt_row(items: list[dict], extra_tags: dict | None = None) -> str:
    """Render a table row of market cells. extra_tags maps index → html tag string."""
    cells = ""
    for i, it in enumerate(items):
        tag = (extra_tags or {}).get(i, "")
        cells += _mkt_cell(it, extra_tag=tag)
    return f'<tr>{cells}</tr>'


def _mkt_section_label(text: str, color: str) -> str:
    return (f'<tr><td colspan="99" style="padding:12px 10px 6px 10px;">'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<div style="width:3px;height:12px;background:{color};border-radius:1px;"></div>'
            f'<span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;'
            f'font-weight:600;color:#888;">{text}</span>'
            f'</div></td></tr>')


def _fg_cell(item: dict) -> str:
    """Fear & Greed cell with conditional background."""
    val_str = item.get("val", "—")
    bg = "#fff"
    try:
        score = int(val_str)
        if score <= 25:
            bg = "#FFF0F0"
        elif score <= 45:
            bg = "#FFF8F0"
        elif score <= 55:
            bg = "#fff"
        elif score <= 75:
            bg = "#F0FFF4"
        else:
            bg = "#E8F8EE"
    except (ValueError, TypeError):
        pass
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;'
            f'background:{bg};">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">Fear&Greed</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">'
            f'{val_str}</div>'
            f'<div style="font-size:12px;color:#888;">{item.get("chg","—")}</div>'
            f'</td>')


def _sentiment_extra_tags(items: list[dict]) -> dict:
    """Build extra warning tags for sentiment row items by index."""
    tags = {}
    for i, it in enumerate(items):
        label = it.get("label", "")
        val_str = it.get("val", "—").replace(",", "")
        try:
            num = float(val_str)
        except (ValueError, TypeError):
            continue
        if "SKEW" in label and num > 140:
            tags[i] = '<div style="font-size:9px;color:#854F0B;font-weight:600;margin-top:2px;">尾部風險</div>'
        elif "VVIX" in label and num > 120:
            tags[i] = '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">高波動</div>'
    return tags


def _move_cell(move: dict) -> str:
    """MOVE Index as a table cell."""
    val = move.get("val", "—")
    if val == "—":
        return (f'<td style="padding:8px 10px;vertical-align:top;">'
                f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
                f'color:#888;margin-bottom:3px;">MOVE</div>'
                f'<div style="font-size:18px;font-weight:500;color:#888;">—</div>'
                f'</td>')
    color = "#888"
    try:
        num = float(str(val).replace(",", ""))
        if num > 120:
            color = "#C0392B"
        elif num >= 80:
            color = "#854F0B"
        else:
            color = "#0F6E56"
    except (ValueError, TypeError):
        pass
    interp = move.get("interpretation", "")
    interp_html = f'<div style="font-size:9px;color:#555;margin-top:2px;">{interp}</div>' if interp else ""
    return (f'<td style="padding:8px 10px;vertical-align:top;">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">MOVE</div>'
            f'<div style="font-size:18px;font-weight:500;color:{color};">{val}</div>'
            f'{interp_html}'
            f'</td>')


def _credit_cell(item: dict) -> str:
    """Credit cell — HYG/LQD ratio gets special direction arrows."""
    d = item.get("dir", "neu")
    color = MKT_CHG_COLOR.get(d, "#888")
    label = item.get("label", "—")
    chg = item.get("chg", "—")
    # HYG/LQD ratio: ↑ = spread narrowing (green), ↓ = spread widening (red)
    if label == "HYG/LQD" and chg != "—":
        if "▲" in chg:
            chg = chg.replace("▲", "↑利差收窄")
            color = "#0F6E56"
        elif "▼" in chg:
            chg = chg.replace("▼", "↓利差擴大")
            color = "#C0392B"
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">{label}</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">'
            f'{item.get("val","—")}</div>'
            f'<div style="font-size:12px;color:{color};">{chg}</div>'
            f'</td>')


def _vix9d_tag(sentiment: list[dict]) -> str:
    """Compare VIX9D vs VIX and return a tag."""
    vix_val = vix9d_val = None
    for it in sentiment:
        label = it.get("label", "")
        try:
            v = float(it.get("val", "—").replace(",", ""))
        except (ValueError, TypeError):
            continue
        if label == "VIX":
            vix_val = v
        elif label == "VIX9D":
            vix9d_val = v
    if vix_val is None or vix9d_val is None:
        return ""
    diff = vix9d_val - vix_val
    if abs(diff) < 1:
        return ""
    if diff < 0:
        return '<div style="font-size:9px;color:#888;font-weight:600;margin-top:2px;">短期恐慌</div>'
    return '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">持續風險</div>'


def _parse_chg_pct(chg_str: str) -> float | None:
    """Parse a change string like '▲ 1.23%' or '▼ 0.45%' into a signed float."""
    try:
        s = chg_str.replace("▲", "").replace("▼", "").replace("%", "").strip()
        val = float(s)
        if "▼" in chg_str:
            val = -abs(val)
        return val
    except (ValueError, TypeError):
        return None


def _nyfang_tag(factors: list[dict], indices: list[dict]) -> str:
    """Compare NYFANG vs NDX spot change and return a tag."""
    ndx_chg = nyfang_chg = None
    for it in indices:
        if it.get("label", "") == "NDX":
            ndx_chg = _parse_chg_pct(it.get("chg", ""))
    for it in factors:
        if it.get("label", "") == "NYFANG":
            nyfang_chg = _parse_chg_pct(it.get("chg", ""))
    if ndx_chg is None or nyfang_chg is None:
        return ""
    if ndx_chg < 0 and nyfang_chg < ndx_chg:
        return '<div style="font-size:9px;color:#854F0B;font-weight:600;margin-top:2px;">科技巨頭領跌</div>'
    if ndx_chg < 0 and nyfang_chg > ndx_chg:
        return '<div style="font-size:9px;color:#0F6E56;font-weight:600;margin-top:2px;">巨頭相對抗跌</div>'
    return ""


def _rsp_spy_tag(factors: list[dict]) -> str:
    """RSP/SPY ratio tag: up = market broadening, down = concentration."""
    for it in factors:
        if it.get("label", "") == "RSP/SPY":
            chg = _parse_chg_pct(it.get("chg", ""))
            if chg is not None and chg > 0:
                return '<div style="font-size:9px;color:#0F6E56;font-weight:600;margin-top:2px;">市場變寬</div>'
            elif chg is not None and chg < 0:
                return '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">市場集中</div>'
    return ""


def _nfci_cell(item: dict) -> str:
    """NFCI cell with conditional background."""
    val_str = item.get("val", "—")
    bg = "#fff"
    label_tag = ""
    try:
        num = float(val_str)
        if num > 0.5:
            bg = "#FFF0F0"
            label_tag = '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">金融條件偏緊</div>'
        elif num > 0:
            bg = "#FFF8F0"
            label_tag = '<div style="font-size:9px;color:#854F0B;font-weight:600;margin-top:2px;">略偏緊</div>'
        elif num > -0.5:
            bg = "#fff"
        else:
            bg = "#F0FFF4"
            label_tag = '<div style="font-size:9px;color:#0F6E56;font-weight:600;margin-top:2px;">金融條件寬鬆</div>'
    except (ValueError, TypeError):
        pass
    d = item.get("dir", "neu")
    color = MKT_CHG_COLOR.get(d, "#888")
    date_str = item.get("date", "")
    date_html = f'<div style="font-size:9px;color:#aaa;margin-top:1px;">{date_str}</div>' if date_str else ""
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;'
            f'background:{bg};">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">{item.get("label","NFCI")}</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">{val_str}</div>'
            f'<div style="font-size:12px;color:{color};">{item.get("chg","—")}</div>'
            f'{label_tag}{date_html}'
            f'</td>')


def _rrp_cell(item: dict) -> str:
    """RRP cell with date display."""
    d = item.get("dir", "neu")
    color = MKT_CHG_COLOR.get(d, "#888")
    date_str = item.get("date", "")
    date_html = f'<div style="font-size:9px;color:#aaa;margin-top:1px;">{date_str}</div>' if date_str else ""
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">{item.get("label","RRP餘額")}</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">{item.get("val","—")}</div>'
            f'<div style="font-size:12px;color:{color};">{item.get("chg","—")}</div>'
            f'{date_html}'
            f'</td>')


def _market_strip(market_data: dict) -> str:
    indices = market_data.get("indices", [])
    factors = market_data.get("factors", [])
    sentiment = market_data.get("sentiment", [])
    move_index = market_data.get("move_index", {"val": "—", "interpretation": ""})
    commodities_raw = market_data.get("commodities", {})
    if isinstance(commodities_raw, dict):
        commodities_fixed = commodities_raw.get("fixed", [])
        commodities_dynamic = commodities_raw.get("dynamic", [])
    else:
        commodities_fixed = commodities_raw
        commodities_dynamic = []
    bonds = market_data.get("bonds", [])
    fx = market_data.get("fx", [])
    credit = market_data.get("credit", [])
    liquidity = market_data.get("liquidity", [])

    # Separate fixed factors vs dynamic sectors
    factors_fixed = [f for f in factors if not f.get("is_dynamic")]
    factors_dynamic = [f for f in factors if f.get("is_dynamic")]

    # Separate Fear&Greed from sentiment list
    sent_no_fg = []
    fg_item = {"label": "Fear&Greed", "val": "—", "chg": "—", "dir": "neu"}
    for it in sentiment:
        if it.get("label", "") == "Fear&Greed":
            fg_item = it
        else:
            sent_no_fg.append(it)

    # VIX9D vs VIX tag — attach to VIX9D cell
    vix9d_extra = _vix9d_tag(sent_no_fg)
    sent_tags = _sentiment_extra_tags(sent_no_fg)
    for i, it in enumerate(sent_no_fg):
        if it.get("label", "") == "VIX9D":
            existing = sent_tags.get(i, "")
            sent_tags[i] = existing + vix9d_extra
            break

    # NYFANG tag + RSP/SPY tag — attach to factor cells
    nyfang_extra = _nyfang_tag(factors, indices)
    rsp_spy_extra = _rsp_spy_tag(factors)
    factor_tags = {}
    for i, it in enumerate(factors_fixed):
        if it.get("label", "") == "NYFANG":
            factor_tags[i] = nyfang_extra
        elif it.get("label", "") == "RSP/SPY":
            factor_tags[i] = rsp_spy_extra

    # Sentiment cells
    sent_cells = ""
    for i, it in enumerate(sent_no_fg):
        tag = sent_tags.get(i, "")
        sent_cells += _mkt_cell(it, extra_tag=tag)
    sent_cells += _move_cell(move_index)
    sent_cells += _fg_cell(fg_item)

    # Bond row (blue bg)
    bond_cells = "".join(
        _mkt_cell(it) for it in bonds
    )
    # FX row (purple bg)
    fx_cells = "".join(
        _mkt_cell(it) for it in fx
    )
    # Credit row (green bg)
    credit_cells = "".join(_credit_cell(it) for it in credit)

    # Liquidity cells + assessment bar
    liq_cells = ""
    for it in liquidity:
        if it.get("label", "") == "NFCI":
            liq_cells += _nfci_cell(it)
        else:
            liq_cells += _rrp_cell(it)

    liq_assess = market_data.get("liquidity_assessment", {})
    assess_label = liq_assess.get("label", "—")
    assess_color = liq_assess.get("color", "neu")
    assess_score = liq_assess.get("score", 0)
    assess_signals = liq_assess.get("signals", [])
    if assess_color == "pos":
        assess_bg = "#E8F8EE"
        assess_text_color = "#0F6E56"
        assess_icon = "✓"
    elif assess_color == "neg":
        assess_bg = "#FFF0F0"
        assess_text_color = "#C0392B"
        assess_icon = "⚠"
    else:
        assess_bg = "#f7f7f5"
        assess_text_color = "#888"
        assess_icon = ""
    signal_tags = " ".join(
        f'<span style="font-size:9px;background:#fff;padding:1px 5px;border-radius:2px;'
        f'color:#555;margin-left:4px;">{s}</span>' for s in assess_signals
    )
    score_sign = f"+{assess_score}" if assess_score > 0 else str(assess_score)
    assess_bar = (f'<tr><td colspan="99" style="background:{assess_bg};padding:8px 12px;">'
                  f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                  f'<div><span style="font-size:13px;font-weight:600;color:{assess_text_color};">'
                  f'{assess_label} {assess_icon}</span>{signal_tags}</div>'
                  f'<span style="font-size:12px;font-weight:600;color:{assess_text_color};">'
                  f'{score_sign}</span>'
                  f'</div></td></tr>')

    liq_section = ""
    if liquidity:
        liq_section = f'''
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_mkt_section_label("流動性", "#1a7a4a")}
    <tr>{liq_cells}</tr>
    {assess_bar}'''

    return f'''
<div class="section">
  <div class="section-label">市場即時數據</div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#fff;border:0.5px solid #e8e8e8;border-radius:8px;
                overflow:hidden;border-collapse:collapse;">
    {_mkt_section_label("股票指數", "#1B3A5C")}
    {_mkt_row(indices)}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_mkt_section_label("美股市場因子", "#7F77DD")}
    {_mkt_row(factors_fixed, extra_tags=factor_tags)}
    {_mkt_row(factors_dynamic) if factors_dynamic else ""}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_mkt_section_label("市場情緒", "#BA7517")}
    <tr>{sent_cells}</tr>
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_mkt_section_label("原物料", "#854F0B")}
    {_mkt_row(commodities_fixed)}
    {_mkt_row(commodities_dynamic) if commodities_dynamic else ""}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    <tr><td colspan="99" style="padding:12px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#185FA5;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">債券</span>
      </div></td></tr>
    <tr style="background:#EBF2FA;">{bond_cells}</tr>
    <tr><td colspan="99" style="padding:8px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#534AB7;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">外匯</span>
      </div></td></tr>
    <tr style="background:#F0EDF8;">{fx_cells}</tr>
    <tr><td colspan="99" style="padding:8px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#0F6E56;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">信貸</span>
      </div></td></tr>
    <tr style="background:#E8F5EE;">{credit_cells}</tr>
    {liq_section}
  </table>
</div>'''


def _market_pulse(pulse: dict) -> str:
    signals = pulse.get("cross_asset_signals", [])
    dominant = pulse.get("dominant_theme", "")
    hidden_risk = pulse.get("hidden_risk", "")
    hidden_opp = pulse.get("hidden_opportunity", "")
    key_level = pulse.get("key_level_to_watch", "")
    if not signals and not dominant:
        return ""

    # Dominant theme banner
    dom_html = ""
    if dominant:
        dom_html = f'''
<div style="background:#1B3A5C;color:#fff;border-radius:4px;padding:8px 14px;margin-bottom:10px;
            font-size:14px;font-weight:600;">
  今日主軸：{dominant}
</div>'''

    # Cross-asset signals
    sig_html = ""
    for i, sig in enumerate(signals):
        separator = 'border-bottom:0.5px solid #e0e0e0;' if i < len(signals) - 1 else ''
        sig_html += f'''
<div style="padding:10px 0;{separator}">
  <div style="font-size:15px;font-weight:600;color:#1B3A5C;margin-bottom:4px;">{sig.get("signal","")}</div>
  <div style="font-size:13px;color:#555;line-height:1.65;margin-bottom:4px;">{sig.get("detail","")}</div>
  <div style="font-size:12px;color:#888;font-style:italic;line-height:1.5;">{sig.get("implication","")}</div>
</div>'''

    # Risk + Opportunity side by side
    risk_td = ""
    if hidden_risk:
        risk_td = (f'<td width="50%" style="vertical-align:top;padding-right:5px;">'
                   f'<div style="border-left:3px solid #854F0B;padding:8px 12px;background:#fff;">'
                   f'<div style="font-size:12px;font-weight:600;color:#854F0B;margin-bottom:4px;">潛在風險</div>'
                   f'<div style="font-size:13px;color:#555;line-height:1.6;">{hidden_risk}</div>'
                   f'</div></td>')
    else:
        risk_td = '<td width="50%"></td>'
    opp_td = ""
    if hidden_opp:
        opp_td = (f'<td width="50%" style="vertical-align:top;padding-left:5px;">'
                  f'<div style="border-left:3px solid #1a7a4a;padding:8px 12px;background:#fff;">'
                  f'<div style="font-size:12px;font-weight:600;color:#1a7a4a;margin-bottom:4px;">潛在機會</div>'
                  f'<div style="font-size:13px;color:#555;line-height:1.6;">{hidden_opp}</div>'
                  f'</div></td>')
    else:
        opp_td = '<td width="50%"></td>'

    bottom_html = ""
    if hidden_risk or hidden_opp:
        bottom_html = f'''
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;border-collapse:collapse;">
  <tr>{risk_td}{opp_td}</tr>
</table>'''

    # Key level + historical analog + new pattern
    key_html = ""
    if key_level:
        key_html = f'''
<div style="background:#FEF9E7;border-radius:4px;padding:8px 14px;margin-top:10px;
            font-size:13px;color:#856404;">
  <span style="font-weight:600;">關鍵價位：</span>{key_level}
</div>'''

    hist_analog = pulse.get("historical_analog", "")
    new_pat = pulse.get("new_pattern", "")
    analog_html = ""
    if hist_analog or new_pat:
        parts = []
        if hist_analog:
            parts.append(f'<span style="color:#534AB7;">歷史類比：</span>{hist_analog}')
        if new_pat:
            parts.append(f'<span style="color:#854F0B;">新模式：</span>{new_pat}')
        analog_html = f'''
<div style="font-size:12px;color:#555;line-height:1.5;margin-top:8px;padding-top:8px;
            border-top:0.5px solid #e8e8e8;">
  {"　｜　".join(parts)}
</div>'''

    return f'''
<div class="section">
  <div style="background:#f7f7f5;border-radius:8px;border:0.5px solid #e8e8e8;padding:14px 18px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;
                margin-bottom:10px;padding-bottom:6px;border-bottom:0.5px solid #e8e8e8;">
      <span style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;
                   font-weight:500;color:#888;">市場脈絡</span>
      <span style="font-size:12px;color:#888;">跨指標訊號分析</span>
    </div>
    {dom_html}
    {sig_html}
    {bottom_html}
    {key_html}
    {analog_html}
  </div>
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
        deep_analysis = item.get("deep_analysis", "")
        structural_signal = item.get("structural_signal", "")
        bull_case = item.get("bull_case", "")
        bear_case = item.get("bear_case", "")
        implication = item.get("implication", "")
        source = item.get("source", "")
        source_date = item.get("source_date", "")
        source_text = f"{source_date} · {source}" if source and source_date else (source_date or source)

        # 1. Header: theme tag + headline + source
        header_html = f'''
<div style="display:flex;align-items:flex-start;gap:0;margin-bottom:14px;">
  <div style="width:4px;background:{color};border-radius:2px;flex-shrink:0;min-height:40px;margin-right:12px;"></div>
  <div style="flex:1;">
    <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <span style="font-size:12px;font-weight:600;padding:2px 8px;border-radius:3px;
                     color:#fff;background:{color};white-space:nowrap;">{theme}</span>
        <span style="font-size:18px;font-weight:600;color:#222;line-height:1.4;">{headline}</span>
      </div>
      <span style="font-size:11px;color:#aaa;white-space:nowrap;">{source_text}</span>
    </div>
  </div>
</div>'''

        # 2. Situation
        sit_html = ""
        if situation:
            sit_html = f'''
<div style="background:#F8F8F6;border-radius:6px;padding:12px 14px;margin-bottom:12px;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;
              color:#888;margin-bottom:6px;">現況</div>
  <div style="font-size:14px;color:#555;line-height:1.8;">{situation}</div>
</div>'''

        # 3. Key data table
        key_data = item.get("key_data", [])
        kd_html = ""
        if key_data:
            kd_rows = ""
            for kd in key_data:
                change_str = kd.get("change", "")
                is_pos = any(c in change_str for c in ["▲", "+", "上升", "增"])
                is_neg = any(c in change_str for c in ["▼", "-", "下降", "減", "跌"])
                val_bg = "#F0FFF4" if is_pos else ("#FFF0F0" if is_neg else "#fff")
                kd_rows += (f'<tr>'
                            f'<td style="padding:7px 10px;font-size:13px;color:#555;border-bottom:0.5px solid #f0f0f0;'
                            f'white-space:nowrap;">{kd.get("metric","")}</td>'
                            f'<td style="padding:7px 10px;font-size:16px;font-weight:600;color:#222;'
                            f'border-bottom:0.5px solid #f0f0f0;background:{val_bg};">{kd.get("value","")}</td>'
                            f'<td style="padding:7px 10px;font-size:13px;color:#555;'
                            f'border-bottom:0.5px solid #f0f0f0;">{change_str}</td>'
                            f'<td style="padding:7px 10px;font-size:12px;color:#888;'
                            f'border-bottom:0.5px solid #f0f0f0;">{kd.get("context","")}</td>'
                            f'</tr>')
            kd_html = f'''
<div style="margin-bottom:12px;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;
              color:#888;margin-bottom:6px;">關鍵數據</div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border:0.5px solid #e8e8e8;border-radius:4px;border-collapse:collapse;overflow:hidden;">
    {kd_rows}
  </table>
</div>'''

        # 4. Deep analysis
        analysis_html = ""
        if deep_analysis:
            analysis_html = f'''
<div style="margin-bottom:12px;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;
              color:#1B3A5C;margin-bottom:6px;">深度分析</div>
  <div style="border-left:3px solid #1B3A5C;padding:8px 12px;background:#f8fafd;">
    <div style="font-size:14px;color:#555;line-height:1.8;">{deep_analysis}</div>
  </div>
</div>'''

        # 5. Structural signal
        signal_html = ""
        if structural_signal:
            signal_html = f'''
<div style="margin-bottom:12px;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;
              color:#7F77DD;margin-bottom:6px;">結構性訊號</div>
  <div style="border-left:3px solid #7F77DD;padding:8px 12px;">
    <div style="font-size:13px;color:#555;line-height:1.7;font-style:italic;">{structural_signal}</div>
  </div>
</div>'''

        # 6. Bull/Bear side by side
        bull_bear_html = ""
        if bull_case or bear_case:
            bull_td = (f'<td width="50%" style="vertical-align:top;padding-right:5px;">'
                       f'<div style="background:#F0FFF4;border-radius:4px;padding:10px 12px;">'
                       f'<div style="font-size:10px;font-weight:600;color:#0F6E56;margin-bottom:4px;">'
                       f'樂觀情境 ▲</div>'
                       f'<div style="font-size:13px;color:#555;line-height:1.65;">{bull_case}</div>'
                       f'</div></td>') if bull_case else '<td width="50%"></td>'
            bear_td = (f'<td width="50%" style="vertical-align:top;padding-left:5px;">'
                       f'<div style="background:#FFF0F0;border-radius:4px;padding:10px 12px;">'
                       f'<div style="font-size:10px;font-weight:600;color:#C0392B;margin-bottom:4px;">'
                       f'悲觀情境 ▼</div>'
                       f'<div style="font-size:13px;color:#555;line-height:1.65;">{bear_case}</div>'
                       f'</div></td>') if bear_case else '<td width="50%"></td>'
            bull_bear_html = f'''
<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:12px;border-collapse:collapse;">
  <tr>{bull_td}{bear_td}</tr>
</table>'''

        # 7. Implication
        impl_html = ""
        if implication:
            impl_html = f'''
<div style="background:#FEF9E7;border-radius:4px;border-left:3px solid #BA7517;padding:10px 12px;">
  <div style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;
              color:#BA7517;margin-bottom:4px;">投資含義</div>
  <div style="font-size:14px;color:#555;line-height:1.7;">{implication}</div>
</div>'''

        cards += f'''
<div style="border:0.5px solid #e8e8e8;border-radius:8px;padding:18px 20px;margin-bottom:20px;
            background:#fff;">
  {header_html}
  {sit_html}
  {kd_html}
  {analysis_html}
  {signal_html}
  {bull_bear_html}
  {impl_html}
</div>'''

    return f'''
<div class="section">
  <div class="section-label">每日深度聚焦
    <span style="font-size:12px;color:#888;font-weight:400;letter-spacing:0;">
      今日最值得深挖的兩個主題</span>
  </div>
  {cards}
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
{_market_pulse(data.get("market_pulse", {}))}
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
