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


SENTIMENT_COLOR = {"pos": "#0F6E56", "neg": "#C0392B", "neu": "#888"}

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
    "us": "#0F6E56", "malaysia": "#854F0B",
    "korea": "#0F6E56", "china": "#C0392B", "europe": "#534AB7",
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


def _mkt_row(items: list[dict], extra_tags: dict | None = None, max_per_row: int = 6) -> str:
    """Render table rows of market cells, max_per_row items per <tr>."""
    if not items:
        return ""
    html = ""
    for i, it in enumerate(items):
        if i % max_per_row == 0:
            if i > 0:
                html += "</tr>"
            html += "<tr>"
        tag = (extra_tags or {}).get(i, "")
        html += _mkt_cell(it, extra_tag=tag)
    html += "</tr>"
    return html


def _wrap_cells_in_rows(cells_html: str, max_per_row: int = 6) -> str:
    """Split pre-built <td>...</td> cells into <tr> rows with max_per_row each."""
    import re
    tds = re.findall(r'<td.*?</td>', cells_html, re.DOTALL)
    if not tds:
        return ""
    html = ""
    for i, td in enumerate(tds):
        if i % max_per_row == 0:
            if i > 0:
                html += "</tr>"
            html += "<tr>"
        html += td
    html += "</tr>"
    return html


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


def _iwm_spy_tag(factors: list[dict]) -> str:
    """IWM/SPY ratio tag: up = risk-on small caps, down = large-cap dominance."""
    for it in factors:
        if it.get("label", "") == "IWM/SPY 小型":
            chg = _parse_chg_pct(it.get("chg", ""))
            if chg is not None and chg > 0:
                return '<div style="font-size:9px;color:#0F6E56;font-weight:600;margin-top:2px;">小型股強</div>'
            elif chg is not None and chg < 0:
                return '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">大型股主導</div>'
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

    # NYFANG tag + RSP/SPY tag + IWM/SPY tag — attach to factor cells
    nyfang_extra = _nyfang_tag(factors, indices)
    rsp_spy_extra = _rsp_spy_tag(factors)
    iwm_spy_extra = _iwm_spy_tag(factors)
    factor_tags = {}
    for i, it in enumerate(factors_fixed):
        if it.get("label", "") == "NYFANG":
            factor_tags[i] = nyfang_extra
        elif it.get("label", "") == "RSP/SPY":
            factor_tags[i] = rsp_spy_extra
        elif it.get("label", "") == "IWM/SPY 小型":
            factor_tags[i] = iwm_spy_extra

    # Sentiment cells
    sent_cells = ""
    for i, it in enumerate(sent_no_fg):
        tag = sent_tags.get(i, "")
        sent_cells += _mkt_cell(it, extra_tag=tag)
    sent_cells += _move_cell(move_index)
    sent_cells += _fg_cell(fg_item)

    # Bond cells with special 10Y-2Y spread styling
    # Check for yield curve inversion
    us2y_val = us10y_val = None
    for it in bonds:
        try:
            v = float(it.get("val", "—").replace(",", "").replace("%", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        if it.get("label", "") == "美2Y":
            us2y_val = v
        elif it.get("label", "") == "美10Y":
            us10y_val = v
    inversion_warning = ""
    if us2y_val is not None and us10y_val is not None and us2y_val > us10y_val:
        inversion_warning = ('<span style="font-size:9px;color:#C0392B;font-weight:600;'
                             'margin-left:8px;">⚠ 殖利率倒掛</span>')

    bond_cells = ""
    for it in bonds:
        label = it.get("label", "")
        if label == "10Y-2Y":
            # Special styling for spread
            val_str = it.get("val", "—")
            try:
                spread_num = float(val_str.replace("%", ""))
            except (ValueError, TypeError):
                spread_num = 0
            if spread_num < -0.1:
                val_color = "#C0392B"
                tag = '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">倒掛⚠</div>'
            elif spread_num > 0.1:
                val_color = "#0F6E56"
                tag = '<div style="font-size:9px;color:#0F6E56;font-weight:600;margin-top:2px;">正常</div>'
            else:
                val_color = "#854F0B"
                tag = '<div style="font-size:9px;color:#854F0B;font-weight:600;margin-top:2px;">趨平</div>'
            d = it.get("dir", "neu")
            chg_color = MKT_CHG_COLOR.get(d, "#888")
            bond_cells += (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;">'
                           f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
                           f'color:#888;margin-bottom:3px;">{label}</div>'
                           f'<div style="font-size:18px;font-weight:500;color:{val_color};margin-bottom:2px;">'
                           f'{val_str}</div>'
                           f'<div style="font-size:12px;color:{chg_color};">{it.get("chg","—")}</div>'
                           f'{tag}</td>')
        else:
            bond_cells += _mkt_cell(it)
    # FX row (purple bg) — dynamic FX get "今日波動" tag
    fx_cells = ""
    for it in fx:
        if it.get("is_dynamic"):
            dyn_tag = ('<div style="font-size:9px;color:#534AB7;font-weight:600;'
                       'margin-top:2px;">今日波動</div>')
            fx_cells += _mkt_cell(it, extra_tag=dyn_tag)
        else:
            fx_cells += _mkt_cell(it)
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
    {_mkt_section_label("流動性", "#0F6E56")}
    <tr>{liq_cells}</tr>
    {assess_bar}'''

    # Data date notice for weekends/holidays
    data_date = market_data.get("data_date", "")
    date_notice = ""
    if data_date:
        from datetime import date as _date_cls
        try:
            parts = data_date.split("-")
            d = _date_cls(int(parts[0]), int(parts[1]), int(parts[2]))
            today = _date_cls.today()
            if d < today:
                date_notice = (f'<span style="font-size:11px;color:#888;font-weight:400;">'
                               f'數據截至 {data_date}（最近交易日）</span>')
        except (ValueError, IndexError):
            pass

    return f'''
<div class="section">
  <div class="section-label">市場即時數據{date_notice}</div>
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
    {_wrap_cells_in_rows(sent_cells, 6)}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_mkt_section_label("原物料", "#854F0B")}
    {_mkt_row(commodities_fixed)}
    {_mkt_row(commodities_dynamic) if commodities_dynamic else ""}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    <tr><td colspan="99" style="padding:12px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#185FA5;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">債券</span>
        {inversion_warning}
      </div></td></tr>
    {_wrap_cells_in_rows(bond_cells, 6).replace('<tr>', '<tr style="background:#EBF2FA;">')}
    <tr><td colspan="99" style="padding:8px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#534AB7;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">外匯</span>
      </div></td></tr>
    {_wrap_cells_in_rows(fx_cells, 6).replace('<tr>', '<tr style="background:#F7F5FF;">')}
    <tr><td colspan="99" style="padding:8px 10px 6px 10px;">
      <div style="display:flex;align-items:center;gap:6px;">
        <div style="width:3px;height:12px;background:#0F6E56;border-radius:1px;"></div>
        <span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;font-weight:600;color:#888;">信貸</span>
      </div></td></tr>
    {_wrap_cells_in_rows(credit_cells, 6).replace('<tr>', '<tr style="background:#E8F5EE;">')}
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
                  f'<div style="border-left:3px solid #0F6E56;padding:8px 12px;background:#fff;">'
                  f'<div style="font-size:12px;font-weight:600;color:#0F6E56;margin-bottom:4px;">潛在機會</div>'
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


def _index_factor_reading(ifr: dict) -> str:
    """Render the index_factor_reading block."""
    if not ifr:
        return ""
    # Check if all fields are empty
    if not any(ifr.get(k) for k in ("market_breadth", "style_rotation", "sector_signal",
                                     "nyfang_signal", "momentum_read", "key_insight")):
        return ""

    def _ifr_cell(title_text, content):
        return (f'<td width="25%" style="vertical-align:top;padding:8px 10px;'
                f'border-right:0.5px solid #EEE;">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;'
                f'color:#888;margin-bottom:4px;">{title_text}</div>'
                f'<div style="font-size:13px;color:#333;line-height:1.6;">{content}</div></td>')

    row1 = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr>{_ifr_cell("市場寬度", ifr.get("market_breadth", ""))}'
            f'{_ifr_cell("風格輪動", ifr.get("style_rotation", ""))}'
            f'{_ifr_cell("SECTOR訊號", ifr.get("sector_signal", ""))}'
            f'{_ifr_cell("科技巨頭", ifr.get("nyfang_signal", ""))}</tr></table>')

    momentum = ifr.get("momentum_read", "")
    mom_html = ""
    if momentum:
        mom_html = (f'<div style="padding-top:8px;border-top:0.5px solid #EEE;margin-top:8px;">'
                    f'<span style="font-size:10px;color:#888;">動能 ▶ </span>'
                    f'<span style="font-size:13px;color:#333;">{momentum}</span></div>')

    key = ifr.get("key_insight", "")
    key_html = ""
    if key:
        key_html = (f'<div style="background:#534AB7;border-radius:4px;padding:8px 12px;margin-top:8px;">'
                    f'<div style="font-size:13px;font-weight:500;color:#fff;">▶ {key}</div></div>')

    return f'''
<div style="display:flex;gap:0;margin-top:8px;">
  <div style="width:4px;background:#7F77DD;border-radius:2px 0 0 2px;flex-shrink:0;"></div>
  <div style="background:#F8F7FE;border-radius:0 6px 6px 0;padding:10px 14px;flex:1;">
    {row1}
    {mom_html}
    {key_html}
  </div>
</div>'''


def _sentiment_analysis(sa: dict) -> str:
    """Render the sentiment_analysis block."""
    if not sa or not sa.get("one_line"):
        return ""

    stage = sa.get("stage", "無明確訊號")
    stage_name = sa.get("stage_name", "正常市場")
    vix_reading = sa.get("vix_reading", "")
    vvix_reading = sa.get("vvix_reading", "")
    skew_reading = sa.get("skew_reading", "")
    fg_reading = sa.get("fear_greed_reading", "")
    credit_check = sa.get("credit_check", "")
    cross_asset = sa.get("cross_asset_confirm", "")
    key_div = sa.get("key_divergence", "")
    reliability = sa.get("reliability", "中")
    reliability_reason = sa.get("reliability_reason", "")
    one_line = sa.get("one_line", "")

    # Reliability color mapping
    rel_colors = {
        "高": {"bg": "#E8F8EE", "text": "#0F6E56", "dot": "#0F6E56"},
        "中": {"bg": "#FFF8F0", "text": "#854F0B", "dot": "#E67E22"},
        "低": {"bg": "#FFF0F0", "text": "#C0392B", "dot": "#C0392B"},
    }
    rc = rel_colors.get(reliability, rel_colors["中"])

    # Stage badge
    stage_html = (f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
                  f'<span style="font-size:13px;font-weight:600;color:#1B3A5C;background:#EBF2FA;'
                  f'padding:3px 10px;border-radius:4px;">{stage}</span>'
                  f'<span style="font-size:13px;color:#555;">{stage_name}</span></div>')

    # Row 1: VIX / VVIX / SKEW readings
    def _reading_cell(title_text, content):
        return (f'<td width="33%" style="vertical-align:top;padding:8px 10px;">'
                f'<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;'
                f'color:#888;margin-bottom:4px;">{title_text}</div>'
                f'<div style="font-size:13px;color:#333;line-height:1.5;">{content}</div></td>')

    row1 = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr>{_reading_cell("VIX 解讀", vix_reading)}'
            f'{_reading_cell("VVIX 解讀", vvix_reading)}'
            f'{_reading_cell("SKEW 解讀", skew_reading)}</tr></table>')

    # Row 2: Fear&Greed / Credit / Cross-asset
    row2 = (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:6px;border-top:0.5px solid #e8e8e8;">'
            f'<tr>{_reading_cell("FEAR&GREED 補充", fg_reading)}'
            f'{_reading_cell("信貸確認", credit_check)}'
            f'{_reading_cell("跨資產確認", cross_asset)}</tr></table>')

    # Key divergence
    div_html = ""
    if key_div:
        div_html = (f'<div style="font-size:13px;color:#555;line-height:1.5;padding:8px 10px;'
                    f'margin-top:6px;border-top:0.5px solid #e8e8e8;">'
                    f'<span style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;'
                    f'color:#888;">關鍵背離/一致性</span><br>{key_div}</div>')

    # Reliability row
    rel_html = (f'<div style="display:flex;align-items:center;gap:10px;padding:8px 10px;'
                f'margin-top:6px;border-top:0.5px solid #e8e8e8;">'
                f'<span style="font-size:12px;font-weight:600;padding:2px 8px;border-radius:3px;'
                f'background:{rc["bg"]};color:{rc["text"]};">可靠性：{reliability}</span>'
                f'<span style="font-size:13px;color:#888;">{reliability_reason}</span></div>')

    # One-line conclusion with reliability dot
    one_html = (f'<div style="background:#1B3A5C;border-radius:4px;padding:10px 14px;margin-top:10px;'
                f'display:flex;align-items:center;gap:10px;">'
                f'<div style="width:10px;height:10px;border-radius:50%;background:{rc["dot"]};'
                f'flex-shrink:0;"></div>'
                f'<div style="font-size:14px;color:#fff;line-height:1.6;">{one_line}</div></div>')

    return f'''
<div class="section">
  <div style="background:#f7f7f5;border-radius:8px;border:0.5px solid #e8e8e8;padding:14px 18px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;
                margin-bottom:10px;padding-bottom:6px;border-bottom:0.5px solid #e8e8e8;">
      <span style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;
                   font-weight:500;color:#888;">情緒四部曲分析</span>
      <span style="font-size:12px;color:#888;">VIX·VVIX·SKEW·信貸·跨資產</span>
    </div>
    {stage_html}
    {row1}
    {row2}
    {div_html}
    {rel_html}
    {one_html}
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
            confirm_html = '<span style="font-size:11px;color:#0F6E56;">● 已確認</span>'
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
    return f'''
<div class="section">
  <div style="background:#f7f7f5;border-radius:8px;border:0.5px solid #e8e8e8;padding:16px 18px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;
                margin-bottom:14px;padding-bottom:8px;border-bottom:0.5px solid #e8e8e8;">
      <span style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;
                   font-weight:500;color:#888;">隱含趨勢分析</span>
      <span style="font-size:13px;color:#888;">整合所有數據萃取的結構性訊號</span>
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:10px;">
      <tr>
        <td width="50%" style="vertical-align:top;">{_trend_card(trends[0]) if len(trends)>0 else ""}</td>
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
    # Data sources tags
    sources = t.get("data_sources", [])
    src_tags = " ".join(
        f'<span style="font-size:8px;background:#F0F0EE;padding:2px 6px;border-radius:3px;'
        f'color:#555;">{s}</span>' for s in sources[:3]
    )
    src_html = f'<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;">{src_tags}</div>' if src_tags else ""

    # Trend continuity
    tc = t.get("trend_continuity", "")
    tc_html = ""
    if tc:
        tc_html = (f'<div style="border-left:2px dashed #BA7517;padding-left:8px;margin-top:8px;">'
                   f'<div style="font-size:10px;color:#888;">趨勢持續性：</div>'
                   f'<div style="font-size:12px;color:#888;font-style:italic;line-height:1.5;">{tc}</div></div>')

    # Historical analog + new factor side by side
    hist = t.get("historical_analog", "")
    nf = t.get("new_factor", "")
    bottom_html = ""
    if hist or nf:
        hist_td = (f'<td width="50%" style="vertical-align:top;padding-right:5px;">'
                   f'<div style="border-left:2px dashed #aaa;padding-left:8px;">'
                   f'<div style="font-size:10px;color:#888;">歷史類比</div>'
                   f'<div style="font-size:12px;color:#555;font-style:italic;line-height:1.5;">{hist}</div>'
                   f'</div></td>') if hist else '<td width="50%"></td>'
        nf_td = (f'<td width="50%" style="vertical-align:top;padding-left:5px;">'
                 f'<div style="border-left:2px solid #BA7517;padding-left:8px;">'
                 f'<div style="font-size:10px;color:#BA7517;">新模式因素</div>'
                 f'<div style="font-size:12px;color:#555;line-height:1.5;">{nf}</div>'
                 f'</div></td>') if nf else '<td width="50%"></td>'
        bottom_html = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                       f'style="border-collapse:collapse;margin-top:8px;"><tr>{hist_td}{nf_td}</tr></table>')

    # Implication
    impl = t.get("implication", "")
    impl_html = ""
    if impl:
        impl_html = (f'<div style="margin-top:8px;background:#FEF9E7;padding:8px 10px;border-radius:4px;">'
                     f'<span style="font-size:10px;color:#854F0B;">投資含義 ▸ </span>'
                     f'<span style="font-size:13px;color:#555;line-height:1.6;">{impl}</span></div>')

    return f'''<div style="background:#fff;border-radius:6px;border:0.5px solid #e8e8e8;padding:14px 16px;">
  <div style="display:flex;align-items:baseline;gap:8px;margin-bottom:4px;">
    <span style="font-family:Georgia,serif;font-size:28px;color:#222;line-height:1;">{t.get("num","")}</span>
    <span style="font-size:15px;font-weight:500;color:#222;line-height:1.4;">{t.get("title","")}</span>
  </div>
  {src_html}
  {tc_html}
  <div style="font-size:13px;color:#555;line-height:1.8;margin-top:8px;">{t.get("desc","")}</div>
  {bottom_html}
  {impl_html}
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
    "liquidity": "#0F6E56",
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
        move_color = "#0F6E56" if "▲" in move or "+" in move else "#C0392B"

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


def _screener_top30(screener_result: dict) -> str:
    if not screener_result or not screener_result.get("top30"):
        return ""

    top30 = screener_result["top30"]
    date = screener_result.get("date", "")
    total = screener_result.get("total_screened", 0)

    rows = ""
    for item in top30:
        rs = item.get("RS_Score", 0)
        con = item.get("Contraction_Score", 0)
        combined = item.get("Combined_Score", 0)
        vs_ma = item.get("vs_200MA_pct")
        sector = item.get("Sector", "")

        # RS Score 顏色
        if rs >= 80:
            rs_color = "#0F6E56"
        elif rs >= 60:
            rs_color = "#BA7517"
        else:
            rs_color = "#C0392B"

        vs_ma_str = f"+{vs_ma:.1f}%" if vs_ma and vs_ma > 0 else (f"{vs_ma:.1f}%" if vs_ma else "—")
        vs_ma_color = "#0F6E56" if vs_ma and vs_ma > 0 else "#C0392B"

        # 排名變化
        rank_str = item.get("Rank_Change_Str", "—")
        if isinstance(rank_str, str) and rank_str.startswith("↑"):
            rank_change_html = f'<span style="color:#0F6E56;font-size:11px;">{rank_str}</span>'
        elif isinstance(rank_str, str) and rank_str.startswith("↓"):
            rank_change_html = f'<span style="color:#C0392B;font-size:11px;">{rank_str}</span>'
        elif rank_str == "新進":
            rank_change_html = '<span style="background:#EBF2FA;color:#185FA5;font-size:9px;padding:1px 3px;border-radius:2px;">新進</span>'
        else:
            rank_change_html = '<span style="color:#BBB;">—</span>'

        rows += f"""
        <tr>
          <td style="text-align:center;padding:6px 8px;font-size:12px;color:#888;">{item.get('Rank','')}</td>
          <td style="text-align:center;padding:6px 4px;">{rank_change_html}</td>
          <td style="padding:6px 8px;font-size:13px;font-weight:500;color:#1B3A5C;">{item.get('Ticker','')}<br><span style="font-size:10px;color:#AAA;font-weight:400;">{sector}</span></td>
          <td style="text-align:center;padding:6px 8px;font-size:13px;font-weight:500;color:{rs_color};">{rs:.0f}</td>
          <td style="text-align:center;padding:6px 8px;font-size:13px;color:#534AB7;">{con:.0f}</td>
          <td style="text-align:center;padding:6px 8px;font-size:13px;font-weight:500;">{combined:.0f}</td>
          <td style="text-align:center;padding:6px 8px;font-size:13px;">${item.get('Price',0):.2f}</td>
          <td style="text-align:center;padding:6px 8px;font-size:12px;color:{vs_ma_color};">{vs_ma_str}</td>
        </tr>"""

    return f"""
    <div style="margin:20px 0;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <div style="width:4px;height:14px;background:#1B3A5C;border-radius:2px;"></div>
        <span style="font-size:10px;letter-spacing:2px;text-transform:uppercase;color:#666;font-weight:500;">RS + VCP SCREENER</span>
        <span style="font-size:10px;color:#BBB;margin-left:auto;">{date} · {total} 支篩選</span>
      </div>
      <table width="100%" style="border-collapse:collapse;border:0.5px solid #E8E8E8;border-radius:8px;overflow:hidden;">
        <tr style="background:#1B3A5C;">
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">排名</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">變化</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:left;">代號</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">RS</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">VCP</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">綜合</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">股價</th>
          <th style="padding:8px;font-size:10px;color:#fff;font-weight:500;text-align:center;">vs 200MA</th>
        </tr>
        {rows}
      </table>
    </div>"""


def _footer() -> str:
    return '''
<div style="font-size:12px;color:#aaa;border-top:0.5px solid #e8e8e8;
            padding-top:12px;margin-top:4px;display:flex;justify-content:space-between;">
  <span>Perplexity · Claude Sonnet · yfinance</span>
  <span>AI輔助整理 · 僅供參考</span>
</div>'''


_TAB_PAGES = [
    ("index",    "市場數據",    "index.html"),
    ("news",     "要聞・深度",  "news.html"),
    ("geo",      "地緣・國際",  "geo.html"),
    ("tech",     "科技・AI",    "tech.html"),
    ("trends",   "新創・趨勢",  "trends.html"),
    ("misc",     "財報・冷知識", "misc.html"),
    ("screener", "Screener",    "screener.html"),
]


def _page_wrapper(page: str, date: str, content: str, title: str) -> str:
    """把內容包成完整 HTML 頁面，含 Tab 導航"""
    tabs = ""
    for key, label, href in _TAB_PAGES:
        if key == page:
            style = ("display:inline-block;padding:12px 18px;font-size:13px;font-weight:500;"
                     "color:#1B3A5C;border-bottom:3px solid #1B3A5C;text-decoration:none;"
                     "white-space:nowrap;background:#F0F4F8;")
        else:
            style = ("display:inline-block;padding:12px 18px;font-size:13px;color:#666;"
                     "border-bottom:3px solid transparent;text-decoration:none;white-space:nowrap;")
        tabs += f'<a href="{href}" style="{style}">{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — 每日財經晨報 {date}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:Arial,sans-serif; max-width:800px; margin:0 auto; background:#fff; color:#333; }}
a {{ color:inherit; }}
.sticky-nav {{ position:sticky; top:0; z-index:100; }}
.nav-tabs {{ display:flex; overflow-x:auto; -webkit-overflow-scrolling:touch; }}
.nav-tabs::-webkit-scrollbar {{ display:none; }}
{BASE_CSS}
</style>
</head>
<body>
<div class="sticky-nav">
  <div style="background:#1B3A5C;padding:12px 20px;display:flex;justify-content:space-between;align-items:center;">
    <div>
      <div style="font-size:9px;letter-spacing:2px;color:rgba(255,255,255,0.6);text-transform:uppercase;margin-bottom:2px;">Morning Briefing</div>
      <div style="font-size:18px;font-weight:500;color:#fff;">每日財經晨報</div>
    </div>
    <div style="font-size:11px;color:rgba(255,255,255,0.7);">{date}</div>
  </div>
  <div style="background:#fff;border-bottom:1px solid #E8E8E8;display:flex;overflow-x:auto;padding:0 8px;-webkit-overflow-scrolling:touch;" class="nav-tabs">{tabs}</div>
</div>
<div style="padding:16px 16px 40px;">
{content}
</div>
</body>
</html>"""


def build_index_html(data: dict) -> str:
    """首頁：市場數據"""
    date = data.get("date", "")
    content = ""
    if data.get("alert"):
        content += _alert(data["alert"])
    content += _market_strip(data.get("market_data", {}))
    content += _index_factor_reading(data.get("index_factor_reading", {}))
    content += _sentiment_analysis(data.get("sentiment_analysis", {}))
    content += _market_pulse(data.get("market_pulse", {}))
    return _page_wrapper("index", date, content, "市場數據")


def build_news_html(data: dict) -> str:
    """要聞・深度"""
    date = data.get("date", "")
    content = _news_section("核心要聞", data.get("top_stories", []))
    content += _daily_deep_dive(data.get("daily_deep_dive", []))
    return _page_wrapper("news", date, content, "要聞・深度")


def build_geo_html(data: dict) -> str:
    """地緣・國際"""
    date = data.get("date", "")
    content = _world_news(data.get("world_news", []))
    content += _geopolitical_section(data.get("geopolitical", []))
    content += _news_section("總經動態", data.get("macro", []))
    return _page_wrapper("geo", date, content, "地緣・國際")


def build_tech_html(data: dict) -> str:
    """科技・AI"""
    date = data.get("date", "")
    ai_tag = {"macro": "background:#EBF2FA;color:#185FA5;", "tech": "background:#EAF3DE;color:#3B6D11;"}
    content = _news_section("AI 産業動態", data.get("ai_industry", []), ai_tag)
    content += _regional_tech_section(data.get("regional_tech", {}))
    content += _fintech_crypto_section(data.get("fintech_crypto", []))
    return _page_wrapper("tech", date, content, "科技・AI")


def build_trends_html(data: dict) -> str:
    """新創・趨勢"""
    date = data.get("date", "")
    content = _tech_trends(data.get("tech_trends", []))
    content += _startup_news(data.get("startup_news", []))
    content += _smart_money(data.get("smart_money", {}))
    return _page_wrapper("trends", date, content, "新創・趨勢")


def build_misc_html(data: dict) -> str:
    """財報・冷知識"""
    date = data.get("date", "")
    content = _us_market_recap(data.get("us_market_recap", {}))
    content += _earnings_preview(data.get("earnings_preview", []))
    content += _implied_trends(data.get("implied_trends", []))
    content += _fun_fact(data.get("fun_fact", {}))
    content += _today_events(data.get("today_events", []))
    return _page_wrapper("misc", date, content, "財報・冷知識")


def build_screener_html(data: dict, screener_result: dict = None) -> str:
    """Screener"""
    date = data.get("date", "")
    sr = screener_result or {}
    content = _screener_top30(sr)
    if not content:
        content = '<div style="padding:40px;text-align:center;color:#888;font-size:14px;">今日 Screener 數據尚未產出</div>'
    return _page_wrapper("screener", date, content, "Screener")


def build_all_pages(data: dict, screener_result: dict = None) -> dict:
    """產出所有頁面，回傳 {filename: html_content} dict"""
    sr = screener_result or {}
    return {
        "index.html":    build_index_html(data),
        "news.html":     build_news_html(data),
        "geo.html":      build_geo_html(data),
        "tech.html":     build_tech_html(data),
        "trends.html":   build_trends_html(data),
        "misc.html":     build_misc_html(data),
        "screener.html": build_screener_html(data, sr),
    }


def build_html(data: dict, screener_result: dict = None) -> str:
    """向後相容：產出單頁完整 HTML（供 Email 使用）"""
    tz  = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz).strftime("%Y年%m月%d日 %H:%M TST")

    ai_tag = {"macro": "background:#EBF2FA;color:#185FA5;", "tech": "background:#EAF3DE;color:#3B6D11;"}
    ai_section = _news_section("AI 産業動態", data.get("ai_industry", []), ai_tag)
    sr = screener_result or {}

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
{_index_factor_reading(data.get("index_factor_reading", {}))}
{_market_pulse(data.get("market_pulse", {}))}
{_sentiment_analysis(data.get("sentiment_analysis", {}))}
{_news_section("核心要聞", data.get("top_stories",[]))}
{_daily_deep_dive(data.get("daily_deep_dive", []))}
{_world_news(data.get("world_news", []))}
{_news_section("總經動態", data.get("macro",[]))}
{_geopolitical_section(data.get("geopolitical",[]))}
{ai_section}
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
{_screener_top30(sr)}
{_footer()}
</body>
</html>"""
