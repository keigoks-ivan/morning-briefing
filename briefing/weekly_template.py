"""
weekly_template.py
------------------
將週報 JSON 渲染成深度閱讀用 HTML。
"""

from datetime import datetime, timedelta
import pytz


THEME_ICON = {
    "central_bank": "🏦",
    "liquidity": "💧",
    "credit": "💳",
    "options": "📊",
    "ai_industry": "🤖",
    "semiconductor": "🔬",
    "earnings": "📈",
    "macro": "🌍",
    "commodities": "🛢️",
    "black_swan": "🦢",
}

THEME_LABEL = {
    "central_bank": "🏦 央行政策追蹤",
    "liquidity": "💧 流動性週報",
    "credit": "💳 信貸市場週報",
    "options": "📊 選擇權市場情緒",
    "ai_industry": "🤖 AI 產業發展",
    "semiconductor": "🔬 半導體供應鏈",
    "earnings": "📈 財報季追蹤",
    "macro": "🌍 全球景氣狀況",
    "commodities": "🛢️ 能源與大宗商品",
    "black_swan": "🦢 黑天鵝與灰犀牛",
}

THEME_ORDER = [
    "central_bank", "liquidity", "credit", "options",
    "ai_industry", "semiconductor", "earnings",
    "macro", "commodities", "black_swan",
]

SENTIMENT_COLOR = {"pos": "#1a7a4a", "neg": "#C0392B", "neu": "#888780"}


def _get_week_range() -> tuple[str, str, str]:
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    end = now
    start = end - timedelta(days=6)
    week_num = now.isocalendar()[1]
    return f"W{week_num}", start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def _header(theme_name: str, theme_key: str, week_label: str, start: str, end: str) -> str:
    icon = THEME_ICON.get(theme_key, "📊")
    return f'''
<div style="background:#1B3A5C;border-radius:8px 8px 0 0;padding:24px 28px;
            display:flex;justify-content:space-between;align-items:center;">
  <div>
    <div style="font-size:14px;letter-spacing:2px;text-transform:uppercase;
                color:rgba(255,255,255,0.6);margin-bottom:6px;">WEEKLY DEEP REPORT</div>
    <div style="font-family:Georgia,serif;font-size:28px;font-weight:700;
                color:#fff;">{icon} {theme_name}</div>
  </div>
  <div style="text-align:right;color:rgba(255,255,255,0.8);font-size:14px;line-height:1.8;">
    {week_label}<br>{start} — {end}
  </div>
</div>'''


def _week_summary(text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="background:#FEF3CD;padding:14px 28px;font-size:17px;font-weight:500;
            color:#856404;line-height:1.6;">
  📌 {text}
</div>'''


def _signal_change(text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="margin:24px 0;">
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:12px;">本週關鍵變化</div>
  <div style="display:flex;gap:0;">
    <div style="width:4px;background:#378ADD;border-radius:2px;flex-shrink:0;"></div>
    <div style="background:#EBF2FA;border-radius:0 6px 6px 0;padding:16px 20px;
                font-size:16px;color:#222;line-height:1.8;flex:1;">{text}</div>
  </div>
</div>'''


def _section_label(title: str) -> str:
    return f'''<div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:14px;">{title}</div>'''


def _text_block(title: str, text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="margin:24px 0;">
  {_section_label(title)}
  <div style="font-size:16px;color:#222;line-height:1.8;">{text}</div>
</div>'''


def _info_card(title: str, text: str, border_color: str = "#378ADD") -> str:
    if not text:
        return ""
    return f'''
<div style="margin:20px 0;">
  {_section_label(title)}
  <div style="display:flex;gap:0;">
    <div style="width:4px;background:{border_color};border-radius:2px;flex-shrink:0;"></div>
    <div style="background:#f7f7f5;border-radius:0 6px 6px 0;padding:16px 20px;
                font-size:16px;color:#222;line-height:1.8;flex:1;">{text}</div>
  </div>
</div>'''


def _kv_card(title: str, items: dict, bg: str = "#f7f7f5") -> str:
    if not items:
        return ""
    rows = ""
    for k, v in items.items():
        if not v:
            continue
        rows += f'''
<div style="display:flex;gap:12px;padding:8px 0;border-bottom:0.5px solid #e8e8e8;">
  <div style="font-size:14px;font-weight:500;color:#888;min-width:120px;">{k}</div>
  <div style="font-size:15px;color:#222;line-height:1.7;flex:1;">{v}</div>
</div>'''
    if not rows:
        return ""
    return f'''
<div style="margin:20px 0;">
  {_section_label(title)}
  <div style="background:{bg};border-radius:6px;padding:14px 18px;">{rows}</div>
</div>'''


def _deep_analysis(items: list) -> str:
    if not items:
        return ""
    cards = ""
    for item in items:
        evidence_items = "".join(
            f'<div style="padding:6px 0;font-size:15px;color:#555;line-height:1.7;">• {e}</div>'
            for e in item.get("evidence", [])
        )
        cards += f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:8px;padding:20px 24px;
            margin-bottom:16px;">
  <div style="font-size:18px;font-weight:600;color:#222;margin-bottom:12px;
              line-height:1.5;">{item.get("title","")}</div>
  <div style="font-size:16px;color:#333;line-height:1.8;margin-bottom:16px;">
    {item.get("content","")}
  </div>
  <div style="background:#f7f7f5;border-radius:6px;padding:14px 18px;margin-bottom:14px;">
    <div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;
                color:#888;font-weight:500;margin-bottom:8px;">EVIDENCE</div>
    {evidence_items}
  </div>
  <div style="display:flex;gap:0;">
    <div style="width:3px;background:#1a7a4a;border-radius:2px;flex-shrink:0;"></div>
    <div style="padding:10px 14px;font-size:15px;color:#1a7a4a;line-height:1.7;flex:1;">
      <span style="font-weight:600;">投資含義：</span>{item.get("implication","")}
    </div>
  </div>
</div>'''
    return f'''
<div style="margin:24px 0;">
  {_section_label("深度分析")}
  {cards}
</div>'''


def _earnings_calls(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for item in items:
        rows += f'''
<div style="display:flex;gap:0;margin-bottom:12px;">
  <div style="width:4px;background:#1B3A5C;border-radius:2px;flex-shrink:0;"></div>
  <div style="padding:12px 16px;border:1px solid #e8e8e8;border-left:none;
              border-radius:0 6px 6px 0;flex:1;">
    <div style="font-size:16px;font-weight:600;color:#222;margin-bottom:6px;">
      {item.get("company","")}</div>
    <div style="font-size:15px;color:#555;line-height:1.7;font-style:italic;
                margin-bottom:6px;">"{item.get("key_quotes","")}"</div>
    <div style="font-size:14px;color:#888;line-height:1.6;">
      {item.get("what_it_means","")}</div>
  </div>
</div>'''
    return f'''
<div style="margin:24px 0;">
  {_section_label("法說會重點")}
  {rows}
</div>'''


def _analyst_views(items: list) -> str:
    if not items:
        return ""
    rows = ""
    for item in items:
        tc = item.get("target_change", "")
        tc_html = f'<span style="color:#1a7a4a;font-weight:500;">{tc}</span>' if tc else "—"
        rows += f'''
<tr style="border-bottom:1px solid #f0f0f0;">
  <td style="padding:12px 14px;font-size:15px;font-weight:500;color:#222;
             white-space:nowrap;vertical-align:top;">{item.get("firm","")}</td>
  <td style="padding:12px 14px;font-size:15px;color:#555;line-height:1.7;
             vertical-align:top;">{item.get("view","")}</td>
  <td style="padding:12px 14px;font-size:15px;vertical-align:top;
             white-space:nowrap;">{tc_html}</td>
</tr>'''
    return f'''
<div style="margin:24px 0;">
  {_section_label("分析師觀點")}
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border:1px solid #e8e8e8;border-radius:6px;overflow:hidden;border-collapse:collapse;">
    <thead>
      <tr style="background:#f7f7f5;">
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;font-weight:500;">機構</th>
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;font-weight:500;">觀點</th>
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;font-weight:500;">評級/目標價</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>'''


def _watchlist_impact(text: str) -> str:
    if not text:
        return ""
    return f'''
<div style="margin:24px 0;background:#f7f7f5;border-radius:6px;padding:16px 20px;">
  {_section_label("觀察清單影響")}
  <div style="font-size:16px;color:#222;line-height:1.8;">{text}</div>
</div>'''


def _tag_list(title: str, items: list, bg: str, color: str) -> str:
    if not items:
        return ""
    tags = "".join(
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'font-size:14px;font-weight:500;padding:6px 14px;border-radius:4px;'
        f'margin:0 8px 8px 0;line-height:1.6;">{item}</span>'
        for item in items
    )
    return f'''
<div style="margin:20px 0;">
  {_section_label(title)}
  <div>{tags}</div>
</div>'''


def _footer(start: str, end: str) -> str:
    return f'''
<div style="font-size:13px;color:#aaa;border-top:1px solid #e8e8e8;
            padding-top:14px;margin-top:8px;display:flex;justify-content:space-between;">
  <span>本份報告涵蓋 {start} 至 {end}</span>
  <span>AI 輔助分析 · 僅供參考</span>
</div>'''


# ──── Theme-specific body renderers ────

def _body_generic(data: dict) -> str:
    return (
        _signal_change(data.get("signal_change", ""))
        + _deep_analysis(data.get("deep_analysis", []))
        + _earnings_calls(data.get("earnings_calls", []))
        + _analyst_views(data.get("analyst_views", []))
        + _watchlist_impact(data.get("watchlist_impact", ""))
        + _tag_list("下週催化劑", data.get("next_week_catalysts", []), "#E1F5EE", "#0F6E56")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_earnings(data: dict) -> str:
    if not data.get("has_earnings", False):
        return '<div style="margin:24px 0;font-size:16px;color:#888;">本週無重要財報公布。</div>'

    results = data.get("earnings_results", [])
    rows = ""
    for r in results:
        bm = r.get("beat_miss", "")
        bm_color = "#1a7a4a" if bm == "beat" else ("#C0392B" if bm == "miss" else "#888")
        rows += f'''
<tr style="border-bottom:1px solid #f0f0f0;">
  <td style="padding:10px 12px;font-weight:600;color:#222;font-size:15px;">{r.get("company","")} <span style="color:#888;font-weight:400;">({r.get("ticker","")})</span></td>
  <td style="padding:10px 12px;font-size:14px;color:#555;">EPS: {r.get("eps_actual","")} vs {r.get("eps_estimate","")}</td>
  <td style="padding:10px 12px;font-size:14px;color:#555;">Rev: {r.get("revenue_actual","")} vs {r.get("revenue_estimate","")}</td>
  <td style="padding:10px 12px;font-size:14px;font-weight:600;color:{bm_color};">{bm.upper()}</td>
  <td style="padding:10px 12px;font-size:14px;color:#555;">{r.get("guidance","")}</td>
</tr>
<tr style="border-bottom:1px solid #e8e8e8;">
  <td colspan="5" style="padding:6px 12px 12px;font-size:14px;color:#555;line-height:1.6;">
    💡 {r.get("key_insight","")} · 股價：{r.get("stock_reaction","")}
  </td>
</tr>'''

    table = ""
    if rows:
        table = f'''
<div style="margin:24px 0;">
  {_section_label("財報結果")}
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border:1px solid #e8e8e8;border-radius:6px;overflow:hidden;border-collapse:collapse;">
    <thead>
      <tr style="background:#f7f7f5;">
        <th style="padding:10px 12px;font-size:13px;color:#888;text-align:left;font-weight:500;">公司</th>
        <th style="padding:10px 12px;font-size:13px;color:#888;text-align:left;font-weight:500;">EPS</th>
        <th style="padding:10px 12px;font-size:13px;color:#888;text-align:left;font-weight:500;">營收</th>
        <th style="padding:10px 12px;font-size:13px;color:#888;text-align:left;font-weight:500;">結果</th>
        <th style="padding:10px 12px;font-size:13px;color:#888;text-align:left;font-weight:500;">展望</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>'''

    return (
        table
        + _text_block("產業趨勢", data.get("sector_trends", ""))
        + _tag_list("下週財報預告", data.get("next_week_earnings", []), "#EBF2FA", "#185FA5")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_options(data: dict) -> str:
    vix = data.get("vix_data", {})
    pc = data.get("put_call", {})

    vix_card = _kv_card("VIX 數據", {
        "VIX Spot": vix.get("vix_spot", ""),
        "VIX 3M": vix.get("vix_3m", ""),
        "期限結構": vix.get("term_structure", ""),
        "VVIX": vix.get("vvix", ""),
    })
    vix_interp = _info_card("VIX 解讀", vix.get("interpretation", ""), "#534AB7")

    pc_card = _kv_card("Put/Call Ratio", {
        "QQQ P/C Ratio": pc.get("qqq_ratio", ""),
        "本週趨勢": pc.get("trend", ""),
        "訊號": pc.get("signal", ""),
    })
    pc_interp = _info_card("P/C 解讀", pc.get("interpretation", ""), "#378ADD")

    return (
        vix_card + vix_interp + pc_card + pc_interp
        + _text_block("偏斜與機構部位", data.get("skew_positioning", ""))
        + _text_block("Gamma 環境", data.get("gamma_environment", ""))
        + _tag_list("關鍵價位", data.get("key_levels", []), "#F0EDF8", "#534AB7")
        + _info_card("NQ100 綜合判斷", data.get("nq_signal", ""), "#1B3A5C")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_commodities(data: dict) -> str:
    energy = data.get("energy", {})
    metals = data.get("metals", {})

    energy_html = _text_block("油市分析", energy.get("oil_analysis", ""))
    energy_html += _tag_list("油價驅動因素", energy.get("key_drivers", []), "#FAF0DA", "#854F0B")
    if energy.get("opec_update"):
        energy_html += _info_card("OPEC 動態", energy.get("opec_update", ""), "#854F0B")
    if energy.get("nat_gas"):
        energy_html += _text_block("天然氣", energy.get("nat_gas", ""))

    metals_html = _text_block("黃金分析", metals.get("gold_analysis", ""))
    metals_html += _text_block("工業金屬", metals.get("industrial_metals", ""))
    if metals.get("key_signal"):
        metals_html += _info_card("金屬景氣訊號", metals.get("key_signal", ""), "#854F0B")

    return (
        energy_html + metals_html
        + _text_block("農產品", data.get("agriculture", ""))
        + _info_card("通膨與景氣訊號", data.get("macro_signal", ""), "#1B3A5C")
        + _tag_list("下週催化劑", data.get("next_week_catalysts", []), "#E1F5EE", "#0F6E56")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_central_bank(data: dict) -> str:
    fed = data.get("fed", {})

    # Hawkish/Dovish indicator
    shift = fed.get("hawkish_dovish_shift", 0)
    try:
        shift_val = int(shift)
        if shift_val > 0:
            shift_label = f"偏鷹 +{shift_val}"
            shift_color = "#C0392B"
        elif shift_val < 0:
            shift_label = f"偏鴿 {shift_val}"
            shift_color = "#1a7a4a"
        else:
            shift_label = "中性 0"
            shift_color = "#888"
    except (ValueError, TypeError):
        shift_label = str(shift)
        shift_color = "#888"

    fed_card = _kv_card("聯準會", {
        "重要表態": fed.get("key_statements", ""),
        "利率機率變化": fed.get("rate_probability", ""),
        "下次 FOMC": fed.get("next_meeting", ""),
        f'鷹鴿指標 <span style="color:{shift_color};font-weight:600;">{shift_label}</span>': "",
    })

    # Other central banks
    other_cb = data.get("other_cb", [])
    cb_rows = ""
    for cb in other_cb:
        cb_rows += f'''
<div style="display:flex;gap:0;margin-bottom:10px;">
  <div style="width:3px;background:#534AB7;border-radius:2px;flex-shrink:0;"></div>
  <div style="padding:10px 14px;flex:1;">
    <div style="font-size:15px;font-weight:600;color:#222;margin-bottom:4px;">{cb.get("bank","")}</div>
    <div style="font-size:15px;color:#555;line-height:1.7;">{cb.get("action","")}</div>
    <div style="font-size:14px;color:#888;margin-top:4px;">{cb.get("implication","")}</div>
  </div>
</div>'''
    cb_section = ""
    if cb_rows:
        cb_section = f'<div style="margin:24px 0;">{_section_label("其他央行")}{cb_rows}</div>'

    return (
        fed_card + cb_section
        + _text_block("利率市場定價", data.get("rate_market", ""))
        + _info_card("NQ100 估值影響", data.get("nq_implication", ""), "#1B3A5C")
        + _tag_list("下週央行事件", data.get("next_week_events", []), "#E1F5EE", "#0F6E56")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_credit(data: dict) -> str:
    sd = data.get("spread_data", {})
    spread_card = _kv_card("利差數據", {
        "HYG 週報酬": sd.get("hyg_weekly_return", ""),
        "LQD 週報酬": sd.get("lqd_weekly_return", ""),
        "HYG/LQD 比值變化": sd.get("hyg_lqd_ratio_change", ""),
        "利差方向": sd.get("spread_direction", ""),
    })
    spread_interp = _info_card("利差解讀", sd.get("interpretation", ""), "#378ADD")

    return (
        spread_card + spread_interp
        + _text_block("信貸條件", data.get("credit_conditions", ""))
        + _text_block("壓力訊號", data.get("stress_signals", ""))
        + _info_card("領先指標讀數", data.get("leading_indicator", ""), "#1B3A5C")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


def _body_liquidity(data: dict) -> str:
    nfci = data.get("nfci", {})
    nfci_card = _kv_card("NFCI（國家金融條件指數）", {
        "最新值": nfci.get("latest_value", ""),
        "上週值": nfci.get("prev_week", ""),
        "週變化": nfci.get("week_change", ""),
        "4 週趨勢": nfci.get("4week_trend", ""),
    })
    nfci_interp = _info_card("NFCI 解讀", nfci.get("interpretation", ""), "#378ADD")
    nfci_hist = _text_block("歷史定位", nfci.get("historical_context", ""))

    fed_liq = data.get("fed_liquidity", {})
    fed_card = _kv_card("Fed 流動性", {
        "資產負債表": fed_liq.get("balance_sheet", ""),
        "逆回購 (RRP)": fed_liq.get("rrp", ""),
        "銀行準備金": fed_liq.get("reserves", ""),
    })

    return (
        nfci_card + nfci_interp + nfci_hist + fed_card
        + _text_block("綜合流動性訊號", data.get("liquidity_signal", ""))
        + _info_card("NQ100 影響", data.get("nq_implication", ""), "#1B3A5C")
        + _tag_list("風險警示", data.get("risk_flags", []), "#FCF0EC", "#993C1D")
    )


BODY_RENDERERS = {
    "earnings": _body_earnings,
    "options": _body_options,
    "commodities": _body_commodities,
    "central_bank": _body_central_bank,
    "credit": _body_credit,
    "liquidity": _body_liquidity,
}


# ──── Index page components ────

WK_CHG_COLOR = {"pos": "#0F6E56", "neg": "#C0392B", "neu": "#888"}


def _wk_cell(item: dict, extra_tag: str = "") -> str:
    d = item.get("dir", "neu")
    color = WK_CHG_COLOR.get(d, "#888")
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


def _wk_row(items: list[dict]) -> str:
    cells = "".join(_wk_cell(it) for it in items)
    return f'<tr>{cells}</tr>'


def _wk_section_label(text: str, color: str) -> str:
    return (f'<tr><td colspan="99" style="padding:12px 10px 6px 10px;">'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<div style="width:3px;height:12px;background:{color};border-radius:1px;"></div>'
            f'<span style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;'
            f'font-weight:600;color:#888;">{text}</span>'
            f'</div></td></tr>')


def _wk_fg_cell(item: dict) -> str:
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


def _wk_move_cell(move: dict) -> str:
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


def _wk_credit_cell(item: dict) -> str:
    d = item.get("dir", "neu")
    color = WK_CHG_COLOR.get(d, "#888")
    label = item.get("label", "—")
    chg = item.get("chg", "—")
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


def _wk_nfci_cell(item: dict) -> str:
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
    color = WK_CHG_COLOR.get(d, "#888")
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


def _wk_rrp_cell(item: dict) -> str:
    d = item.get("dir", "neu")
    color = WK_CHG_COLOR.get(d, "#888")
    date_str = item.get("date", "")
    date_html = f'<div style="font-size:9px;color:#aaa;margin-top:1px;">{date_str}</div>' if date_str else ""
    return (f'<td style="padding:8px 10px;border-right:0.5px solid #f0f0f0;vertical-align:top;">'
            f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:#888;margin-bottom:3px;">{item.get("label","RRP餘額")}</div>'
            f'<div style="font-size:18px;font-weight:500;color:#222;margin-bottom:2px;">{item.get("val","—")}</div>'
            f'<div style="font-size:12px;color:{color};">{item.get("chg","—")}</div>'
            f'{date_html}'
            f'</td>')


def _index_market_strip(market_data: dict) -> str:
    indices = market_data.get("indices", [])
    factors = market_data.get("factors", [])
    sentiment = market_data.get("sentiment", [])
    move_index = market_data.get("move_index", {"val": "—", "interpretation": ""})
    commodities = market_data.get("commodities", [])
    bonds = market_data.get("bonds", [])
    fx = market_data.get("fx", [])
    credit = market_data.get("credit", [])
    liquidity = market_data.get("liquidity", [])

    # Separate Fear&Greed from sentiment
    sent_no_fg = []
    fg_item = {"label": "Fear&Greed", "val": "—", "chg": "—", "dir": "neu"}
    for it in sentiment:
        if it.get("label", "") == "Fear&Greed":
            fg_item = it
        else:
            sent_no_fg.append(it)

    # Sentiment extra tags (SKEW/VVIX + VIX9D comparison)
    sent_tags = {}
    vix_val = vix9d_val = None
    for it in sent_no_fg:
        try:
            v = float(it.get("val", "—").replace(",", ""))
        except (ValueError, TypeError):
            continue
        if it.get("label", "") == "VIX":
            vix_val = v
        elif it.get("label", "") == "VIX9D":
            vix9d_val = v
    for i, it in enumerate(sent_no_fg):
        val_str = it.get("val", "—").replace(",", "")
        try:
            num = float(val_str)
        except (ValueError, TypeError):
            continue
        label = it.get("label", "")
        if "SKEW" in label and num > 140:
            sent_tags[i] = '<div style="font-size:9px;color:#854F0B;font-weight:600;margin-top:2px;">尾部風險</div>'
        elif "VVIX" in label and num > 120:
            sent_tags[i] = '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">高波動</div>'
        elif label == "VIX9D" and vix_val is not None and vix9d_val is not None:
            diff = vix9d_val - vix_val
            if diff < -1:
                sent_tags[i] = '<div style="font-size:9px;color:#888;font-weight:600;margin-top:2px;">短期恐慌</div>'
            elif diff > 1:
                sent_tags[i] = '<div style="font-size:9px;color:#C0392B;font-weight:600;margin-top:2px;">持續風險</div>'

    sent_cells = ""
    for i, it in enumerate(sent_no_fg):
        sent_cells += _wk_cell(it, extra_tag=sent_tags.get(i, ""))
    sent_cells += _wk_move_cell(move_index)
    sent_cells += _wk_fg_cell(fg_item)

    credit_cells = "".join(_wk_credit_cell(it) for it in credit)

    bond_fx_credit_cells = ""
    for it in bonds:
        bond_fx_credit_cells += _wk_cell(it)
    bond_fx_credit_cells += '<td style="width:1px;background:#e0e0e0;padding:0;"></td>'
    for it in fx:
        bond_fx_credit_cells += _wk_cell(it)
    bond_fx_credit_cells += '<td style="width:1px;background:#e0e0e0;padding:0;"></td>'
    bond_fx_credit_cells += credit_cells

    # Liquidity
    liq_cells = ""
    for it in liquidity:
        if it.get("label", "") == "NFCI":
            liq_cells += _wk_nfci_cell(it)
        else:
            liq_cells += _wk_rrp_cell(it)
    liq_section = ""
    if liquidity:
        liq_section = f'''
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_wk_section_label("流動性", "#1a7a4a")}
    <tr>{liq_cells}</tr>'''

    return f'''
<div style="margin-bottom:24px;">
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;border-bottom:0.5px solid #e0e0e0;
              padding-bottom:5px;margin-bottom:14px;">市場週度數據</div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:#fff;border:0.5px solid #e8e8e8;border-radius:8px;
                overflow:hidden;border-collapse:collapse;">
    {_wk_section_label("股票指數", "#1B3A5C")}
    {_wk_row(indices)}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_wk_section_label("美股市場因子", "#7F77DD")}
    {_wk_row(factors)}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_wk_section_label("市場情緒", "#BA7517")}
    <tr>{sent_cells}</tr>
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_wk_section_label("原物料", "#854F0B")}
    {_wk_row(commodities)}
    <tr><td colspan="99" style="border-bottom:0.5px solid #f0f0f0;"></td></tr>
    {_wk_section_label("債券 / 外匯 / 信貸", "#378ADD")}
    <tr>{bond_fx_credit_cells}</tr>
    {liq_section}
  </table>
</div>'''


def _index_market_pulse(pulse: dict) -> str:
    if not pulse:
        return ""
    signals = pulse.get("cross_asset_signals", pulse.get("observations", []))
    dominant = pulse.get("dominant_theme", "")
    hidden_risk = pulse.get("hidden_risk", "")
    hidden_opp = pulse.get("hidden_opportunity", "")
    key_level = pulse.get("key_level_to_watch", "")
    if not signals and not dominant:
        return ""

    dom_html = ""
    if dominant:
        dom_html = f'''
<div style="background:#1B3A5C;color:#fff;border-radius:4px;padding:8px 14px;margin-bottom:10px;
            font-size:14px;font-weight:600;">
  本週主軸：{dominant}
</div>'''

    sig_html = ""
    for i, sig in enumerate(signals):
        separator = 'border-bottom:0.5px solid #e0e0e0;' if i < len(signals) - 1 else ''
        sig_html += f'''
<div style="padding:10px 0;{separator}">
  <div style="font-size:15px;font-weight:600;color:#1B3A5C;margin-bottom:4px;">{sig.get("signal","")}</div>
  <div style="font-size:13px;color:#555;line-height:1.65;margin-bottom:4px;">{sig.get("detail","")}</div>
  <div style="font-size:12px;color:#888;font-style:italic;line-height:1.5;">{sig.get("implication","")}</div>
</div>'''

    risk_td = (f'<td width="50%" style="vertical-align:top;padding-right:5px;">'
               f'<div style="border-left:3px solid #854F0B;padding:8px 12px;background:#fff;">'
               f'<div style="font-size:12px;font-weight:600;color:#854F0B;margin-bottom:4px;">潛在風險</div>'
               f'<div style="font-size:13px;color:#555;line-height:1.6;">{hidden_risk}</div>'
               f'</div></td>') if hidden_risk else '<td width="50%"></td>'
    opp_td = (f'<td width="50%" style="vertical-align:top;padding-left:5px;">'
              f'<div style="border-left:3px solid #1a7a4a;padding:8px 12px;background:#fff;">'
              f'<div style="font-size:12px;font-weight:600;color:#1a7a4a;margin-bottom:4px;">潛在機會</div>'
              f'<div style="font-size:13px;color:#555;line-height:1.6;">{hidden_opp}</div>'
              f'</div></td>') if hidden_opp else '<td width="50%"></td>'

    bottom_html = ""
    if hidden_risk or hidden_opp:
        bottom_html = f'''
<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:10px;border-collapse:collapse;">
  <tr>{risk_td}{opp_td}</tr>
</table>'''

    key_html = ""
    if key_level:
        key_html = f'''
<div style="background:#FEF9E7;border-radius:4px;padding:8px 14px;margin-top:10px;
            font-size:13px;color:#856404;">
  <span style="font-weight:600;">關鍵價位：</span>{key_level}
</div>'''

    return f'''
<div style="margin-bottom:24px;">
  <div style="background:#f7f7f5;border-radius:8px;border:0.5px solid #e8e8e8;padding:14px 18px;">
    <div style="display:flex;justify-content:space-between;align-items:baseline;
                margin-bottom:10px;padding-bottom:6px;border-bottom:0.5px solid #e8e8e8;">
      <span style="font-size:12px;letter-spacing:1.8px;text-transform:uppercase;
                   font-weight:500;color:#888;">本週市場脈絡</span>
      <span style="font-size:12px;color:#888;">跨指標訊號分析</span>
    </div>
    {dom_html}
    {sig_html}
    {bottom_html}
    {key_html}
  </div>
</div>'''


def _index_theme_card(theme_key: str, data: dict, today: str) -> str:
    label = THEME_LABEL.get(theme_key, theme_key)
    summary = data.get("week_summary", "")
    signal = data.get("signal_change", "")
    catalysts = data.get("next_week_catalysts", [])
    risks = data.get("risk_flags", [])
    link = f"{today}-{theme_key}.html"

    # For earnings theme with no earnings, show minimal card
    if theme_key == "earnings" and not data.get("has_earnings", True):
        return f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:8px;
            padding:20px 22px;margin-bottom:16px;opacity:0.7;">
  <div style="font-size:18px;font-weight:600;color:#1B3A5C;margin-bottom:8px;">
    {label}</div>
  <div style="font-size:15px;color:#888;">本週無重要財報公布</div>
</div>'''

    summary_html = ""
    if summary:
        summary_html = f'''<div style="background:#FEF3CD;border-radius:4px;padding:10px 14px;
            font-size:15px;font-weight:500;color:#856404;line-height:1.6;margin-bottom:12px;">
      📌 {summary}</div>'''

    signal_html = ""
    if signal:
        signal_html = f'''<div style="font-size:14px;color:#555;line-height:1.7;margin-bottom:12px;">
      {signal}</div>'''

    # Some themes use next_week_events instead of next_week_catalysts
    if not catalysts:
        catalysts = data.get("next_week_events", [])
    if not catalysts:
        catalysts = data.get("next_week_earnings", [])

    catalyst_tags = "".join(
        f'<span style="display:inline-block;background:#E1F5EE;color:#0F6E56;'
        f'font-size:12px;font-weight:500;padding:4px 10px;border-radius:3px;'
        f'margin:0 6px 6px 0;">{c}</span>'
        for c in catalysts[:3]
    )
    risk_tags = "".join(
        f'<span style="display:inline-block;background:#FCF0EC;color:#993C1D;'
        f'font-size:12px;font-weight:500;padding:4px 10px;border-radius:3px;'
        f'margin:0 6px 6px 0;">{r}</span>'
        for r in risks[:3]
    )

    tags_html = ""
    if catalyst_tags or risk_tags:
        tags_html = f'<div style="margin-bottom:12px;">{catalyst_tags}{risk_tags}</div>'

    return f'''
<div style="background:#fff;border:1px solid #e8e8e8;border-radius:8px;
            padding:20px 22px;margin-bottom:16px;">
  <div style="font-size:18px;font-weight:600;color:#1B3A5C;margin-bottom:12px;">
    {label}</div>
  {summary_html}
  {signal_html}
  {tags_html}
  <a href="{link}" style="display:inline-block;background:#1B3A5C;color:#fff;
     font-size:14px;font-weight:500;padding:8px 20px;border-radius:5px;
     text-decoration:none;">閱讀完整報告 →</a>
</div>'''


def _index_archive(weekly_dir: str, current_date: str) -> str:
    import os
    entries: dict[str, list[tuple[str, str]]] = {}
    for fname in sorted(os.listdir(weekly_dir), reverse=True):
        if fname == "index.html" or not fname.endswith(".html"):
            continue
        parts = fname.replace(".html", "").split("-", 3)
        if len(parts) == 4:
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            theme_key = parts[3]
            entries.setdefault(date_str, []).append((theme_key, fname))

    entries.pop(current_date, None)

    if not entries:
        return ""

    rows = ""
    for date_str in sorted(entries.keys(), reverse=True):
        links = ""
        for theme_key, fname in sorted(entries[date_str]):
            lbl = THEME_LABEL.get(theme_key, theme_key)
            links += (f'<a href="{fname}" style="display:inline-block;background:#EBF2FA;'
                      f'color:#185FA5;font-size:13px;font-weight:500;padding:5px 12px;'
                      f'border-radius:4px;text-decoration:none;margin:0 6px 6px 0;">{lbl}</a>')
        rows += f'''
<div style="padding:14px 0;border-bottom:1px solid #f0f0f0;">
  <div style="font-size:15px;font-weight:600;color:#222;margin-bottom:8px;">{date_str}</div>
  <div>{links}</div>
</div>'''

    return f'''
<div style="margin-top:28px;">
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;border-bottom:0.5px solid #e0e0e0;
              padding-bottom:5px;margin-bottom:14px;">歷史週報</div>
  {rows}
</div>'''


def build_weekly_index(
    theme_data: dict[str, dict],
    market_data: dict,
    today: str,
    start: str,
    end: str,
    weekly_dir: str,
    market_pulse: dict | None = None,
) -> str:
    cards = "".join(
        _index_theme_card(key, theme_data.get(key, {}), today)
        for key in THEME_ORDER
    )
    archive = _index_archive(weekly_dir, today)
    pulse_html = _index_market_pulse(market_pulse) if market_pulse else ""

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>每週深度週報</title>
</head>
<body style="font-family:Arial,sans-serif;max-width:720px;margin:0 auto;padding:24px 20px;color:#222;">
<div style="border-bottom:2px solid #1B3A5C;padding-bottom:12px;margin-bottom:20px;
            display:flex;justify-content:space-between;align-items:flex-end;">
  <div>
    <div style="font-size:12px;letter-spacing:1.5px;text-transform:uppercase;color:#888;
                margin-bottom:4px;">WEEKLY DEEP REPORTS</div>
    <div style="font-family:Georgia,serif;font-size:26px;font-weight:700;color:#1B3A5C;">
      每週深度週報</div>
  </div>
  <div style="font-size:13px;color:#888;text-align:right;">
    {start} — {end}
  </div>
</div>
{_index_market_strip(market_data)}
{pulse_html}
{cards}
{archive}
<div style="font-size:12px;color:#aaa;border-top:1px solid #e8e8e8;padding-top:12px;margin-top:20px;">
  AI 輔助分析 · 僅供參考
</div>
</body>
</html>"""


# ──── Main HTML builder ────

def build_weekly_html(data: dict, theme_key: str) -> str:
    week_label, start, end = _get_week_range()
    theme_name = data.get("theme", theme_key)

    renderer = BODY_RENDERERS.get(theme_key, _body_generic)
    body = renderer(data)

    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{theme_name} — 深度週報 {week_label}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:Arial,sans-serif; max-width:780px; margin:0 auto;
       padding:24px 20px; color:#222; background:#fff; }}
</style>
</head>
<body>
{_header(theme_name, theme_key, week_label, start, end)}
{_week_summary(data.get("week_summary",""))}
<div style="padding:0 4px;">
{body}
{_footer(start, end)}
</div>
</body>
</html>"""
