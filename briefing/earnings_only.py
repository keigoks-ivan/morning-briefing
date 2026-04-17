"""
earnings_only.py
----------------
只跑深度財報分析 pipeline，輸出獨立測試頁 earnings_test.html。
不會影響線上 misc.html。

執行流程：
  1. Perplexity 3 組財報查詢（~$0.02）
  2. fetch_market_data（yfinance，免費，供 market_context）
  3. Claude Sonnet 4.6 財報分析（~$0.09）
  4. 渲染獨立頁面到 docs/briefing/earnings_test.html

用於：iterate earnings prompt/邏輯時，不用跑完整 pipeline（省時省錢）。
"""

import os
import sys
import json
from datetime import datetime
import pytz

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from news_fetcher import fetch_earnings_deep_dive, fetch_market_data
from ai_processor import (
    _build_earnings_raw_text,
    _call_claude_earnings_analysis,
    _build_market_context,
)
from html_template import _earnings_deep_analysis, _page_wrapper


def main() -> None:
    print("=" * 50)
    print("Earnings-Only Test Pipeline")
    print("=" * 50)

    # 1. 抓 Perplexity 財報資料 + 市場數據（用於 market_context）
    print("\n[1/3] Fetching earnings + market data...")
    earnings_deep_dive = fetch_earnings_deep_dive()
    market_data = fetch_market_data()

    earnings_raw_text = _build_earnings_raw_text(earnings_deep_dive)
    market_context = _build_market_context(market_data, [], "") if market_data else ""

    with open("/tmp/earnings_raw.txt", "w") as f:
        f.write(earnings_raw_text or "(empty)")
    print(f"      earnings_raw_text: {len(earnings_raw_text)} chars")

    # 2. Claude Sonnet 4.6 分析
    print("\n[2/3] Running Claude earnings analysis...")
    try:
        result = _call_claude_earnings_analysis(earnings_raw_text, market_context)
    except Exception as e:
        print(f"      ✗ Claude failed: {e}")
        result = {"has_content": False, "companies": [], "industry_trends": [],
                  "winners": [], "losers": [], "contradictions": [],
                  "conclusion": f"分析失敗：{e}", "window": "", "overview": ""}

    with open("/tmp/earnings_result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 摘要輸出到 log
    print(f"\n  has_content: {result.get('has_content')}")
    print(f"  window: {result.get('window', '')}")
    print(f"  overview: {result.get('overview', '')}")
    print(f"  companies: {len(result.get('companies', []))}")
    for c in result.get("companies", []):
        print(f"    - {c.get('ticker','?'):10} {c.get('name','')[:40]:40}  {c.get('result_tag','')}")
    print(f"  industries: {len(result.get('industry_trends', []))}")
    print(f"  winners:    {len(result.get('winners', []))}")
    print(f"  losers:     {len(result.get('losers', []))}")
    print(f"  contradict: {len(result.get('contradictions', []))}")

    # 3. 渲染獨立測試頁
    print("\n[3/3] Rendering earnings_test.html...")
    tz = pytz.timezone("Asia/Taipei")
    date_str = datetime.now(tz).strftime("%Y年%m月%d日 %H:%M TST")

    if result.get("has_content"):
        content = _earnings_deep_analysis(result)
    else:
        content = (
            '<div style="padding:40px;text-align:center;color:#888;font-size:14px;">'
            '本次窗口無符合條件的重要財報（has_content=False）<br>'
            f'<span style="font-size:12px;color:#aaa;">{result.get("conclusion","")}</span>'
            '</div>'
        )

    # 加一個除錯區塊：顯示 window / 成本 / 時間戳
    debug_html = f'''
<div style="margin-top:30px;padding:14px 18px;background:#F8F8F6;border-radius:8px;
            font-size:11px;color:#888;line-height:1.7;font-family:monospace;">
  <div>Generated: {date_str}</div>
  <div>Raw data: /tmp/earnings_raw.txt（{len(earnings_raw_text)} chars）</div>
  <div>Result JSON: /tmp/earnings_result.json</div>
  <div>This is a test page — does NOT affect production misc.html</div>
</div>'''

    page = _page_wrapper("misc", date_str, content + debug_html, "財報分析測試")

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    docs_dir = os.path.join(repo_root, "docs", "briefing")
    os.makedirs(docs_dir, exist_ok=True)
    test_path = os.path.join(docs_dir, "earnings_test.html")
    with open(test_path, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"      Saved to {test_path} ({len(page):,} chars)")

    print("\n✓ Done. View at https://research.investmquest.com/briefing/earnings_test.html\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
