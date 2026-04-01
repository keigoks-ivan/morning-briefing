import os
import sys
import base64
from datetime import datetime
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.screener import run_screener
from screener.excel_exporter import export_to_excel

def main():
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    # 執行 Screener
    df = run_screener()
    if df.empty:
        print("✗ Screener 無結果，跳過")
        return

    # 輸出 Excel
    output_path = f"/tmp/RS_Screener_{today}.xlsx"
    export_to_excel(df, output_path)

    # 讀取 Excel 轉 base64
    with open(output_path, "rb") as f:
        excel_b64 = base64.b64encode(f.read()).decode()

    # 儲存結果供日報使用
    import json
    top30 = df.head(30).to_dict(orient="records")

    result = {
        "date": today,
        "total_screened": len(df),
        "top30": top30,
        "excel_b64": excel_b64,
        "excel_filename": f"RS_Screener_{today}.xlsx",
    }

    with open("/tmp/screener_result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False)

    print(f"\n✓ Screener 完成：{len(df)} 支，Top 30 已儲存")
    print(f"  Top 5：{', '.join(df.head(5)['Ticker'].tolist())}")

if __name__ == "__main__":
    main()
