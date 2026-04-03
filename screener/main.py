import os
import sys
import base64
import json
from datetime import datetime
from collections import Counter
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.screener import run_screener, pick_top_candidates, fetch_fundamentals, TICKER_SECTOR, run_sector_screener, run_global_screener
from screener.tw_screener import run_tw_screener
from screener.excel_exporter import export_to_excel


def publish_to_github_pages(df, today: str):
    """把 Screener 結果發布到 docs/screener/ 目錄"""
    import pandas as pd

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    screener_dir = os.path.join(repo_root, "docs", "screener")
    history_dir = os.path.join(screener_dir, "history")
    os.makedirs(history_dir, exist_ok=True)

    # 1. 儲存今日 JSON（全部排名，供歷史比較用）
    all_records = df[["Rank", "Ticker", "Sector", "RS_Score", "rs_trend", "Contraction_Score",
                       "Combined_Score", "Price", "vs_200MA_pct",
                       "Rank_Change", "Rank_Change_Str"]].to_dict(orient="records")

    history_path = os.path.join(history_dir, f"{today}.json")
    with open(history_path, "w") as f:
        json.dump({"date": today, "total": len(df), "data": all_records}, f)

    # 2. 更新 latest.json
    with open(os.path.join(screener_dir, "latest.json"), "w") as f:
        json.dump({"date": today, "total": len(df), "data": all_records}, f)

    # 3. 產出 index.html
    top30 = df.head(30)

    # 產業分布統計
    sector_counts = Counter(top30["Sector"].tolist())
    max_count = max(sector_counts.values()) if sector_counts else 1
    sector_bars = ""
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        bar_width = int(count / max_count * 200)
        sector_bars += f"""
        <div style="display:flex;align-items:center;gap:8px;margin:3px 0;">
          <span style="width:100px;font-size:12px;color:#666;text-align:right;">{sector}</span>
          <div style="width:{bar_width}px;height:14px;background:#1B3A5C;border-radius:2px;"></div>
          <span style="font-size:12px;font-weight:500;color:#333;">{count}</span>
        </div>"""

    rows = ""
    for _, row in top30.iterrows():
        trend_color = {
            "加速上升": "#0F6E56", "穩定維持": "#1B3A5C",
            "開始衰退": "#C0392B", "震盪": "#888888"
        }.get(row.get("rs_trend", ""), "#888888")

        vs_ma = row.get("vs_200MA_pct")
        vs_ma_str = f"+{vs_ma:.1f}%" if vs_ma and vs_ma > 0 else (f"{vs_ma:.1f}%" if vs_ma else "—")
        vs_ma_color = "#0F6E56" if vs_ma and vs_ma > 0 else "#C0392B"

        rank_str = row.get("Rank_Change_Str", "—")
        if rank_str.startswith("↑"):
            rank_change_html = f'<span style="color:#0F6E56;font-size:11px;">{rank_str}</span>'
        elif rank_str.startswith("↓"):
            rank_change_html = f'<span style="color:#C0392B;font-size:11px;">{rank_str}</span>'
        elif rank_str == "新進":
            rank_change_html = '<span style="background:#EBF2FA;color:#185FA5;font-size:10px;padding:1px 4px;border-radius:2px;">新進</span>'
        else:
            rank_change_html = '<span style="color:#BBB;font-size:11px;">—</span>'

        rs_color = "#0F6E56" if row["RS_Score"] >= 80 else "#BA7517" if row["RS_Score"] >= 60 else "#C0392B"

        rows += f"""
        <tr>
          <td>{int(row['Rank'])}</td>
          <td>{rank_change_html}</td>
          <td style="font-weight:500;color:#1B3A5C;">{row['Ticker']}<br><span style="font-size:10px;color:#AAA;">{row.get('Sector','')}</span></td>
          <td style="font-weight:500;color:{rs_color};">{row['RS_Score']:.0f}</td>
          <td style="color:{trend_color};font-size:12px;">{row.get('rs_trend','')}</td>
          <td style="color:#534AB7;">{row['Contraction_Score']:.0f}</td>
          <td style="font-weight:500;">{row['Combined_Score']:.0f}</td>
          <td>${row['Price']:.2f}</td>
          <td style="color:{vs_ma_color};">{vs_ma_str}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>RS + VCP Screener — {today}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #333; }}
  h1 {{ font-size: 20px; color: #1B3A5C; margin-bottom: 4px; }}
  .meta {{ font-size: 13px; color: #888; margin-bottom: 24px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #1B3A5C; color: white; padding: 8px 10px; text-align: center; font-weight: 500; }}
  td {{ padding: 7px 10px; text-align: center; border-bottom: 0.5px solid #F0F0F0; }}
  tr:hover {{ background: #F8F9FC; }}
  .sector-dist {{ margin: 16px 0 24px; padding: 16px; background: #FAFBFD; border-radius: 8px; border: 0.5px solid #E8E8E8; }}
  .sector-dist h3 {{ font-size: 13px; color: #666; margin-bottom: 10px; }}
</style>
</head><body>
<h1>RS + VCP Screener</h1>
<div class="meta">{today} · {len(df)} 支篩選 · Top 30</div>

<div class="sector-dist">
  <h3>Top 30 產業分布</h3>
  {sector_bars}
</div>

<table>
  <tr>
    <th>排名</th><th>變化</th><th>代號</th><th>RS</th><th>RS Trend</th>
    <th>VCP</th><th>綜合</th><th>股價</th><th>vs 200MA</th>
  </tr>
  {rows}
</table>
<p style="font-size:11px;color:#BBB;margin-top:20px;">
  RS Score：63日漲跌幅百分位 · VCP Score：價格收縮形態分數 · 綜合 = RS×60% + VCP×40%
</p>
</body></html>"""

    with open(os.path.join(screener_dir, "index.html"), "w") as f:
        f.write(html)

    print(f"  ✓ GitHub Pages 發布：docs/screener/index.html")


def main():
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # 執行 Screener
    df = run_screener()
    if df.empty:
        print("✗ Screener 無結果，跳過")
        return

    # 今日精選
    picks = pick_top_candidates(df)
    pick_tickers = [v.get("Ticker", "") for v in picks.values() if v]
    print(f"  今日精選：{', '.join(pick_tickers)}")

    # Sector & Global RS 排名
    print("\n[Sector Screener] 執行美股類股 RS 排名...")
    sector_ranking = run_sector_screener()
    print(f"  ✓ Sector: {len(sector_ranking)} 個")

    print("[Global Screener] 執行全球指數 RS 排名...")
    global_ranking = run_global_screener()
    print(f"  ✓ Global: {len(global_ranking)} 個")

    # 台股 Screener
    print("\n[TW Screener] 執行台股 RS + VCP 排名...")
    tw_df, tw_picks = run_tw_screener()
    tw_top30 = tw_df.head(30).to_dict(orient="records") if not tw_df.empty else []
    print(f"  ✓ TW: {len(tw_df)} 支")

    # 輸出 Excel（含 Sector & Global sheets）
    output_path = f"/tmp/RS_Screener_{today}.xlsx"
    export_to_excel(df, output_path, sector_ranking=sector_ranking, global_ranking=global_ranking)

    # 讀取 Excel 轉 base64
    with open(output_path, "rb") as f:
        excel_b64 = base64.b64encode(f.read()).decode()

    # 查詢 Top 30 基本面數據
    top30_tickers = df.head(30)["Ticker"].tolist()
    print("\n[基本面] 查詢 Top 30 基本面數據...")
    fundamentals = fetch_fundamentals(top30_tickers)

    # 儲存結果供日報使用（合併基本面數據）
    top30 = df.head(30).to_dict(orient="records")
    for item in top30:
        fund = fundamentals.get(item["Ticker"], {})
        item.update(fund)

    result = {
        "date": today,
        "total_screened": len(df),
        "top30": top30,
        "top_picks": picks,
        "sector_ranking": sector_ranking,
        "global_ranking": global_ranking,
        "tw_top30": tw_top30,
        "tw_picks": tw_picks,
        "tw_total": len(tw_df),
        "excel_b64": excel_b64,
        "excel_filename": f"RS_Screener_{today}.xlsx",
    }

    with open("/tmp/screener_result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)

    # 發布到 GitHub Pages
    publish_to_github_pages(df, today)

    # Git commit & push docs/screener/
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.system(
        f'cd {repo_root} && git add docs/screener/ '
        f'&& git commit -m "Screener update {today} [skip ci]" '
        f'&& git push'
    )

    print(f"\n✓ Screener 完成：{len(df)} 支，Top 30 已儲存")
    print(f"  Top 5：{', '.join(df.head(5)['Ticker'].tolist())}")


if __name__ == "__main__":
    main()
