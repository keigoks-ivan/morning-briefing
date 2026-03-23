"""
weekly_template.py
------------------
將週報 JSON 渲染成深度閱讀用 HTML。
"""

from datetime import datetime, timedelta
import pytz


THEME_ICON = {
    "ai_industry": "🤖",
    "semiconductor": "🔬",
    "macro": "🌍",
    "black_swan": "🦢",
}


def _get_week_range() -> tuple[str, str, str]:
    """Return (week_label, start_date, end_date) for the current week."""
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)
    end = now
    start = end - timedelta(days=6)
    week_num = now.isocalendar()[1]
    return (
        f"W{week_num}",
        start.strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )


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
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:14px;">深度分析</div>
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
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:14px;">法說會重點</div>
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
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:14px;">分析師觀點</div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border:1px solid #e8e8e8;border-radius:6px;overflow:hidden;border-collapse:collapse;">
    <thead>
      <tr style="background:#f7f7f5;">
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;
                   font-weight:500;letter-spacing:0.5px;">機構</th>
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;
                   font-weight:500;letter-spacing:0.5px;">觀點</th>
        <th style="padding:10px 14px;font-size:13px;color:#888;text-align:left;
                   font-weight:500;letter-spacing:0.5px;">評級/目標價</th>
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
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:10px;">觀察清單影響</div>
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
  <div style="font-size:13px;letter-spacing:1.8px;text-transform:uppercase;
              font-weight:500;color:#888;margin-bottom:12px;">{title}</div>
  <div>{tags}</div>
</div>'''


def _footer(start: str, end: str) -> str:
    return f'''
<div style="font-size:13px;color:#aaa;border-top:1px solid #e8e8e8;
            padding-top:14px;margin-top:8px;display:flex;justify-content:space-between;">
  <span>本份報告涵蓋 {start} 至 {end}</span>
  <span>AI 輔助分析 · 僅供參考</span>
</div>'''


def build_weekly_html(data: dict, theme_key: str) -> str:
    week_label, start, end = _get_week_range()
    theme_name = data.get("theme", theme_key)

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
{_signal_change(data.get("signal_change",""))}
{_deep_analysis(data.get("deep_analysis",[]))}
{_earnings_calls(data.get("earnings_calls",[]))}
{_analyst_views(data.get("analyst_views",[]))}
{_watchlist_impact(data.get("watchlist_impact",""))}
{_tag_list("下週催化劑", data.get("next_week_catalysts",[]), "#E1F5EE", "#0F6E56")}
{_tag_list("風險警示", data.get("risk_flags",[]), "#FCF0EC", "#993C1D")}
{_footer(start, end)}
</div>
</body>
</html>"""
