"""
mac_runner/validate_schema.py
-----------------------------
驗證 full_data.json / weekly_full_data.json 的 schema 完整性。

用於兩個地方：
  1. mac_runner/orchestrate.py — 決定要不要寫出 full_data.json
  2. briefing/main.py try_load_mac_data() — 決定要不要 fallback 回 API pipeline

使用：
    from validate_schema import validate
    ok, errors = validate(data, mode="daily")

或 CLI：
    python validate_schema.py /tmp/full_data.json --mode daily
"""

import sys
import json
import argparse


# ── 必要頂層欄位 ────────────────────────────────────────────
DAILY_REQUIRED = [
    "generated_at",
    "date",
    "market_data",
    "top_stories",
    "market_pulse",
    "sentiment_analysis",
]

WEEKLY_REQUIRED = [
    "generated_at",
    "date",
    "market_data",
    "week_theme",           # 週報主軸
    "weekly_market_pulse",
    "weekly_sentiment_analysis",
]

# ── 型別 ───────────────────────────────────────────────────
DAILY_FIELD_TYPES = {
    "generated_at": str,
    "date": str,
    "market_data": dict,
    "top_stories": list,
    "market_pulse": dict,
    "sentiment_analysis": dict,
    "earnings_deep_analysis": dict,
    "earnings_preview": list,
    "macro": list,
    "ai_industry": list,
    "regional_tech": dict,
    "fintech_crypto": list,
    "geopolitical": list,
    "world_news": list,
    "startup_news": list,
    "tech_trends": list,
    "daily_deep_dive": list,
    "us_market_recap": dict,
    "today_events": list,
    "fun_fact": dict,
    "system_status": dict,
    "index_factor_reading": dict,
    "smart_money": dict,
    "daily_summary": str,
    "alert": str,
}

WEEKLY_FIELD_TYPES = {
    "generated_at": str,
    "date": str,
    "market_data": dict,
    "week_theme": str,
    "weekly_market_pulse": dict,
    "weekly_sentiment_analysis": dict,
    "central_bank": (list, dict),
    "liquidity": (list, dict),
    "credit": (list, dict),
    "options": (list, dict),
    "ai_industry": (list, dict),
    "semiconductor": (list, dict),
    "earnings": (list, dict),
    "macro": (list, dict),
    "commodities": (list, dict),
    "black_swan": (list, dict),
}

# ── market_data 必要子欄位（非空 list）──────────────────────
MARKET_DATA_SUBFIELDS = ["indices", "sentiment"]


def validate(data: dict, mode: str = "daily") -> tuple[bool, list[str]]:
    """
    Returns (ok, errors).
    mode: "daily" | "weekly"
    """
    errors = []

    if not isinstance(data, dict):
        return False, [f"root is not dict (got {type(data).__name__})"]

    required = DAILY_REQUIRED if mode == "daily" else WEEKLY_REQUIRED
    field_types = DAILY_FIELD_TYPES if mode == "daily" else WEEKLY_FIELD_TYPES

    # 必要欄位存在
    for f in required:
        if f not in data:
            errors.append(f"missing required field: {f}")
        elif data[f] is None:
            errors.append(f"required field is None: {f}")

    # 型別檢查
    for f, t in field_types.items():
        if f in data and data[f] is not None:
            if not isinstance(data[f], t):
                expected = t.__name__ if isinstance(t, type) else str(t)
                errors.append(
                    f"field {f} has wrong type: expected {expected}, "
                    f"got {type(data[f]).__name__}"
                )

    # market_data 子欄位
    md = data.get("market_data")
    if isinstance(md, dict):
        for sub in MARKET_DATA_SUBFIELDS:
            val = md.get(sub)
            if not isinstance(val, list) or len(val) == 0:
                errors.append(f"market_data.{sub} missing or empty")

    return (len(errors) == 0), errors


def check_freshness(data: dict, max_age_minutes: int = 20) -> tuple[bool, str]:
    """
    檢查 generated_at 是否在 max_age_minutes 內。
    Returns (fresh, reason).
    """
    from datetime import datetime
    import pytz

    ts_str = data.get("generated_at", "")
    if not ts_str:
        return False, "missing generated_at"

    try:
        ts = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError) as e:
        return False, f"cannot parse generated_at ({ts_str!r}): {e}"

    if ts.tzinfo is None:
        ts = pytz.timezone("Asia/Taipei").localize(ts)

    now = datetime.now(ts.tzinfo)
    age_min = (now - ts).total_seconds() / 60

    if age_min > max_age_minutes:
        return False, f"{age_min:.0f}min old (threshold={max_age_minutes}min)"
    if age_min < -5:
        return False, f"future timestamp ({age_min:.0f}min)"

    return True, f"{age_min:.0f}min old"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to JSON file")
    parser.add_argument("--mode", choices=["daily", "weekly"], default="daily")
    parser.add_argument("--check-freshness", action="store_true",
                        help="Also check generated_at freshness")
    parser.add_argument("--max-age", type=int, default=20,
                        help="Max age in minutes (default 20)")
    args = parser.parse_args()

    with open(args.path, "r", encoding="utf-8") as f:
        data = json.load(f)

    ok, errors = validate(data, mode=args.mode)

    if ok:
        print(f"✓ Schema valid ({args.mode})")
    else:
        print(f"✗ Schema invalid ({args.mode}) — {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")

    if args.check_freshness:
        fresh, reason = check_freshness(data, max_age_minutes=args.max_age)
        if fresh:
            print(f"✓ Fresh: {reason}")
        else:
            print(f"✗ Stale: {reason}")
            ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
