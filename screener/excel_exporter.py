import pandas as pd
import openpyxl
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
from datetime import datetime
import pytz

# RS Trend 顏色對照
RS_TREND_COLORS = {
    "加速上升": "0F6E56",
    "穩定維持": "1B3A5C",
    "開始衰退": "C0392B",
    "震盪":     "888888",
}

def export_to_excel(df: pd.DataFrame, output_path: str) -> str:
    """把 Screener 結果輸出成格式化 Excel"""

    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    wb = openpyxl.Workbook()

    # ── Sheet 1：完整排名 ──────────────────────────────────────
    ws = wb.active
    ws.title = f"Screener_{today}"

    headers = [
        "Rank", "Ticker", "RS Score", "RS Trend", "RS 1w", "RS 4w", "RS 13w",
        "VCP Score", "VCP Pullbacks", "Last Pullback %", "Dist from High %",
        "Combined Score", "Price", "vs 200MA %", "ATR Contraction %", "Volume Ratio"
    ]

    df_cols = [
        "Rank", "Ticker", "RS_Score", "rs_trend", "rs_1w", "rs_4w", "rs_13w",
        "Contraction_Score", "vcp_pullback_count", "last_pullback_pct", "dist_from_high_pct",
        "Combined_Score", "Price", "vs_200MA_pct", "ATR_Contraction_pct", "Volume_Ratio_10d_60d"
    ]

    col_widths = [6, 8, 10, 12, 8, 8, 8, 10, 14, 14, 14, 14, 10, 10, 16, 14]

    # 標題列樣式
    header_fill = PatternFill(start_color="1B3A5C", end_color="1B3A5C", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 數據行
    for row_idx, row in df.iterrows():
        excel_row = row_idx + 2
        for col_idx, col in enumerate(df_cols, 1):
            val = row.get(col, None)
            cell = ws.cell(row=excel_row, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="center")

            # 數字格式
            if col == "Price":
                cell.number_format = '$#,##0.00'
            elif col in ["RS_Score", "Contraction_Score", "Combined_Score", "rs_1w", "rs_4w", "rs_13w"]:
                cell.number_format = '0.0'
            elif col in ["vs_200MA_pct", "ATR_Contraction_pct", "last_pullback_pct", "dist_from_high_pct"]:
                cell.number_format = '0.0"%"'
            elif col == "Volume_Ratio_10d_60d":
                cell.number_format = '0.00"x"'

            # RS Trend 欄位顏色
            if col == "rs_trend" and val:
                trend_color = RS_TREND_COLORS.get(str(val), "888888")
                cell.font = Font(color=trend_color, bold=True)

            # 交替行底色
            if excel_row % 2 == 0:
                # 保留 rs_trend 的字體顏色
                if col == "rs_trend" and val:
                    trend_color = RS_TREND_COLORS.get(str(val), "888888")
                    cell.font = Font(color=trend_color, bold=True)
                cell.fill = PatternFill(start_color="F5F8FC", end_color="F5F8FC", fill_type="solid")

    # 條件格式：RS Score（C欄）綠紅漸層
    last_row = len(df) + 1
    ws.conditional_formatting.add(
        f"C2:C{last_row}",
        ColorScaleRule(
            start_type="min", start_color="C0392B",
            mid_type="percentile", mid_value=50, mid_color="FFFFFF",
            end_type="max", end_color="0F6E56",
        )
    )

    # 條件格式：Combined Score（L欄）
    ws.conditional_formatting.add(
        f"L2:L{last_row}",
        ColorScaleRule(
            start_type="min", start_color="C0392B",
            mid_type="percentile", mid_value=50, mid_color="FFFFFF",
            end_type="max", end_color="0F6E56",
        )
    )

    # 欄寬
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # 凍結首行
    ws.freeze_panes = "A2"

    # ── Sheet 2：Top 30 精選 ───────────────────────────────────
    ws2 = wb.create_sheet("Top 30")

    top30_fill = PatternFill(start_color="0F6E56", end_color="0F6E56", fill_type="solid")

    for col_idx, header in enumerate(headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=header)
        cell.fill = top30_fill
        cell.font = Font(color="FFFFFF", bold=True, size=11)
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in df.head(30).iterrows():
        excel_row = row_idx + 2
        for col_idx, col in enumerate(df_cols, 1):
            val = row.get(col, None)
            cell = ws2.cell(row=excel_row, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="center")
            if col == "Price":
                cell.number_format = '$#,##0.00'
            elif col in ["RS_Score", "Contraction_Score", "Combined_Score", "rs_1w", "rs_4w", "rs_13w"]:
                cell.number_format = '0.0'
            elif col in ["vs_200MA_pct", "ATR_Contraction_pct", "last_pullback_pct", "dist_from_high_pct"]:
                cell.number_format = '0.0"%"'
            elif col == "Volume_Ratio_10d_60d":
                cell.number_format = '0.00"x"'
            if col == "rs_trend" and val:
                trend_color = RS_TREND_COLORS.get(str(val), "888888")
                cell.font = Font(color=trend_color, bold=True)

    for i, width in enumerate(col_widths, 1):
        ws2.column_dimensions[get_column_letter(i)].width = width

    ws2.freeze_panes = "A2"

    # ── Sheet 3：說明 ──────────────────────────────────────────
    ws3 = wb.create_sheet("說明")

    explanation = [
        ("RS Score（相對強度）", True),
        ("- RS 1w/4w/13w：個股在各時間段的漲跌幅百分位排名（0-100）", False),
        ("- RS Trend：加速上升 = 短期RS > 中期RS > 長期RS（最強訊號）", False),
        ("- RS Score = 加權平均 + 趨勢加分/扣分", False),
        ("", False),
        ("VCP Score（價格收縮形態）", True),
        ("- VCP Pullbacks：近90日內的回撤次數（2-4次最理想）", False),
        ("- Last Pullback %：最後一次回撤幅度（越小越好，< 5% 為佳）", False),
        ("- Dist from High %：目前距前期高點距離（越小越接近突破點）", False),
        ("- ATR Contraction %：近10日ATR vs 近60日ATR的收縮幅度", False),
        ("", False),
        ("Combined Score = RS Score × 60% + VCP Score × 40%", True),
        ("", False),
        ("理想的買點特徵：", True),
        ("RS Score > 80 + RS Trend = 加速上升", False),
        ("VCP Pullbacks = 2-3次", False),
        ("Last Pullback % < 5%", False),
        ("Dist from High % < 3%", False),
        ("Volume Ratio < 0.8（量能萎縮）", False),
    ]

    title_font = Font(bold=True, size=12, color="1B3A5C")
    body_font = Font(size=11, color="333333")

    for row_idx, (text, is_title) in enumerate(explanation, 1):
        cell = ws3.cell(row=row_idx, column=1, value=text)
        cell.font = title_font if is_title else body_font

    ws3.column_dimensions["A"].width = 60

    wb.save(output_path)
    print(f"  ✓ Excel 輸出：{output_path}")
    return output_path
