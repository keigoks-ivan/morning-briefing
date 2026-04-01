import pandas as pd
import openpyxl
from openpyxl.styles import (
    PatternFill, Font, Alignment, Border, Side
)
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule
from datetime import datetime
import pytz

def export_to_excel(df: pd.DataFrame, output_path: str) -> str:
    """把 Screener 結果輸出成格式化 Excel"""

    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    wb = openpyxl.Workbook()

    # ── Sheet 1：完整排名 ──────────────────────────────────────
    ws = wb.active
    ws.title = f"Screener_{today}"

    # 標題行
    headers = [
        "Rank", "Ticker", "RS Score", "Contraction Score", "Combined Score",
        "Price", "Return 63d %", "vs SPY 63d %", "vs 200MA %",
        "ATR Contraction %", "Price Range 10d %", "Volume Ratio 10d/60d"
    ]

    col_map = {
        "Rank": "A", "Ticker": "B", "RS Score": "C", "Contraction Score": "D",
        "Combined Score": "E", "Price": "F", "Return 63d %": "G",
        "vs SPY 63d %": "H", "vs 200MA %": "I",
        "ATR Contraction %": "J", "Price Range 10d %": "K", "Volume Ratio 10d/60d": "L"
    }

    # 標題列樣式
    header_fill = PatternFill(start_color="1B3A5C", end_color="1B3A5C", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 數據行
    df_cols = [
        "Rank", "Ticker", "RS_Score", "Contraction_Score", "Combined_Score",
        "Price", "Return_63d", "vs_SPY_63d", "vs_200MA_pct",
        "ATR_Contraction_pct", "Price_Range_10d_pct", "Volume_Ratio_10d_60d"
    ]

    for row_idx, row in df.iterrows():
        excel_row = row_idx + 2
        for col_idx, col in enumerate(df_cols, 1):
            val = row.get(col, None)
            cell = ws.cell(row=excel_row, column=col_idx, value=val)
            cell.alignment = Alignment(horizontal="center")

            # 數字格式
            if col == "Price":
                cell.number_format = '$#,##0.00'
            elif col in ["RS_Score", "Contraction_Score", "Combined_Score"]:
                cell.number_format = '0.0'
            elif col in ["Return_63d", "vs_SPY_63d", "vs_200MA_pct", "ATR_Contraction_pct", "Price_Range_10d_pct"]:
                cell.number_format = '0.00"%"'
            elif col == "Volume_Ratio_10d_60d":
                cell.number_format = '0.00"x"'

            # 交替行底色
            if excel_row % 2 == 0:
                cell.fill = PatternFill(start_color="F5F8FC", end_color="F5F8FC", fill_type="solid")

    # 條件格式：RS Score（C欄）綠紅漸層
    rs_col = "C"
    last_row = len(df) + 1
    ws.conditional_formatting.add(
        f"{rs_col}2:{rs_col}{last_row}",
        ColorScaleRule(
            start_type="min", start_color="C0392B",  # 紅
            mid_type="percentile", mid_value=50, mid_color="FFFFFF",  # 白
            end_type="max", end_color="0F6E56",  # 綠
        )
    )

    # 條件格式：Combined Score（E欄）
    ws.conditional_formatting.add(
        f"E2:E{last_row}",
        ColorScaleRule(
            start_type="min", start_color="C0392B",
            mid_type="percentile", mid_value=50, mid_color="FFFFFF",
            end_type="max", end_color="0F6E56",
        )
    )

    # 欄寬
    col_widths = [6, 8, 10, 16, 14, 8, 12, 12, 10, 16, 16, 18]
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
            elif col in ["RS_Score", "Contraction_Score", "Combined_Score"]:
                cell.number_format = '0.0'

    for i, width in enumerate(col_widths, 1):
        ws2.column_dimensions[get_column_letter(i)].width = width

    ws2.freeze_panes = "A2"

    wb.save(output_path)
    print(f"  ✓ Excel 輸出：{output_path}")
    return output_path
