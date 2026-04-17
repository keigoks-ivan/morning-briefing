"""
mac_runner/orchestrate.py
-------------------------
Phase 2-4: 在 Mac mini 上協調整個 pre-briefing pipeline。

流程：
  1. 執行 fetch_raw_data.py → /tmp/raw_data.json
  2. 並行跑多個 Claude Code 任務（daily 跑 3 個、weekly 跑 1 個覆蓋全部主題）
  3. 合併結果 → full_data.json
  4. 驗證 schema → 若合法，寫到 docs/briefing/full_data.json
  5. git add/commit/push

設計考量：
- 任何一個 Claude Code 任務失敗 → 該區塊留空，不阻斷其他
- Schema 驗證失敗 → 不寫 full_data.json，讓 GitHub Actions 自動 fallback
- 全部成功 → push 到 GitHub，GitHub Actions 撿起來用

Claude Code 認證：
- 依賴 `claude login` 留在 keychain 的 OAuth token
- 失效時 orchestrate.py 會抓到 exit code 非 0，log 錯誤

用法：
  python orchestrate.py --mode daily
  python orchestrate.py --mode weekly
  python orchestrate.py --mode auto          # 週日 → weekly
  python orchestrate.py --mode daily --only earnings   # 只跑單一任務（debug 用）
  python orchestrate.py --mode daily --no-push         # 跑完不推（本機測試）
"""
from __future__ import annotations

import os
import sys
import json
import shutil
import argparse
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytz

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAC_RUNNER = os.path.join(REPO_ROOT, "mac_runner")
PROMPTS_DIR = os.path.join(MAC_RUNNER, "prompts")
OUT_DIR = os.path.join(REPO_ROOT, "docs", "briefing")
RAW_PATH = "/tmp/raw_data.json"

sys.path.insert(0, MAC_RUNNER)
from validate_schema import validate

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(MAC_RUNNER, ".env.local"))
    load_dotenv(os.path.join(REPO_ROOT, ".env"))
except ImportError:
    pass


# ── Claude Code 相關 ────────────────────────────────────────

CLAUDE_BIN = shutil.which("claude") or os.path.expanduser("~/.claude/local/claude")
CLAUDE_MAX_TURNS_DAILY = 40       # news/earnings 需要大量 WebSearch
CLAUDE_MAX_TURNS_ANALYSIS = 15    # analysis 搜尋少
CLAUDE_MAX_TURNS_WEEKLY = 50      # weekly 10 主題一起


def _run_claude_code(prompt_path: str, max_turns: int, label: str) -> dict:
    """
    呼叫 claude -p 非互動式模式，回傳解析後的 JSON。
    失敗會 raise。
    """
    if not os.path.exists(CLAUDE_BIN):
        raise RuntimeError(f"claude CLI not found at {CLAUDE_BIN}. Run `claude login` first.")

    with open(prompt_path, "r", encoding="utf-8") as f:
        prompt = f.read()

    cmd = [
        CLAUDE_BIN,
        "-p", prompt,
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,WebSearch,WebFetch,Bash",
        "--dangerously-skip-permissions",
    ]

    print(f"  → [{label}] invoking Claude Code (max_turns={max_turns})...")
    t0 = datetime.now()

    # 不設 timeout —— Claude Code 可能跑 5-10 分鐘；launchd 層級會有整體 timeout
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = (datetime.now() - t0).total_seconds()

    if proc.returncode != 0:
        err_tail = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"[{label}] claude exited {proc.returncode} after {elapsed:.0f}s — {err_tail}")

    # --output-format json 回傳一個 JSON envelope
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"[{label}] failed to parse envelope JSON: {e}\nstdout[:500]={proc.stdout[:500]}")

    if envelope.get("is_error"):
        raise RuntimeError(f"[{label}] envelope is_error=true: {envelope.get('result','')[:300]}")

    result_text = envelope.get("result", "")

    # Claude 可能用 markdown fence 包裹 JSON
    result_text = result_text.strip()
    if result_text.startswith("```"):
        result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    # 抓大括號內容（容錯：前後有閒話也不影響）
    lo = result_text.find("{")
    hi = result_text.rfind("}") + 1
    if lo == -1 or hi <= lo:
        raise RuntimeError(f"[{label}] no JSON object found in result: {result_text[:300]}")
    json_text = result_text[lo:hi]

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"[{label}] result JSON parse error: {e}\njson_text[:500]={json_text[:500]}")

    cost_hint = envelope.get("total_cost_usd", 0)
    print(f"  ✓ [{label}] done in {elapsed:.0f}s (cost hint: ${cost_hint:.4f} — should be $0 on Max)")
    return data


# ── Phase 1: fetch raw data ─────────────────────────────────

def run_phase1(mode: str) -> dict:
    print(f"\n[Phase 1] Fetching raw data ({mode})...")
    cmd = [sys.executable, os.path.join(MAC_RUNNER, "fetch_raw_data.py"),
           "--mode", mode, "--out", RAW_PATH]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        raise RuntimeError("fetch_raw_data.py failed")
    print(proc.stdout.rstrip())

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Phase 2: Claude Code tasks ──────────────────────────────

def run_phase2_daily(only: str | None) -> dict[str, dict]:
    """回傳 {task_key: json_data}"""
    tasks = {
        "news":     (os.path.join(PROMPTS_DIR, "news.md"),     CLAUDE_MAX_TURNS_DAILY),
        "analysis": (os.path.join(PROMPTS_DIR, "analysis.md"), CLAUDE_MAX_TURNS_ANALYSIS),
        "earnings": (os.path.join(PROMPTS_DIR, "earnings.md"), CLAUDE_MAX_TURNS_DAILY),
    }
    if only:
        if only not in tasks:
            raise ValueError(f"--only {only} not in {list(tasks)}")
        tasks = {only: tasks[only]}

    # 並行跑
    print(f"\n[Phase 2] Claude Code tasks: {list(tasks)}")
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(_run_claude_code, path, turns, key): key
            for key, (path, turns) in tasks.items()
            if os.path.exists(path)
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception as e:
                errors[key] = str(e)
                print(f"  ✗ [{key}] failed: {e}")

    # 被跳過的 prompt 檔（未存在）— 給出清楚 log
    for key, (path, _) in tasks.items():
        if not os.path.exists(path):
            print(f"  ⚠ [{key}] prompt file missing: {path} — will produce empty section")

    return results, errors


def run_phase2_weekly(only: str | None) -> tuple[dict[str, dict], dict[str, str]]:
    tasks = {
        "weekly": (os.path.join(PROMPTS_DIR, "weekly.md"), CLAUDE_MAX_TURNS_WEEKLY),
    }
    if only and only != "weekly":
        raise ValueError("--only for weekly mode must be 'weekly' or omitted")

    print(f"\n[Phase 2] Claude Code task: weekly (single task covering all themes)")
    results = {}
    errors = {}
    for key, (path, turns) in tasks.items():
        if not os.path.exists(path):
            errors[key] = f"prompt file missing: {path}"
            print(f"  ✗ [{key}] prompt file missing: {path}")
            continue
        try:
            results[key] = _run_claude_code(path, turns, key)
        except Exception as e:
            errors[key] = str(e)
            print(f"  ✗ [{key}] failed: {e}")

    return results, errors


# ── Phase 3: merge + validate ───────────────────────────────

def merge_daily(raw: dict, parts: dict[str, dict]) -> dict:
    news = dict(parts.get("news", {}) or {})
    analysis = dict(parts.get("analysis", {}) or {})
    earnings = parts.get("earnings", {}) or {}

    # analysis 輸出的 market_data 只有 move_index，要把它併進 raw 的完整 market_data，
    # 而不是讓 **analysis 的 spread 直接覆蓋掉完整的 market_data
    market_data = dict(raw.get("market_data", {}))
    analysis_md = analysis.pop("market_data", None)
    if isinstance(analysis_md, dict):
        move_index = analysis_md.get("move_index")
        if move_index:
            market_data["move_index"] = move_index

    # news 不應輸出 market_data，若有就丟棄
    news.pop("market_data", None)

    out = {
        "generated_at": raw["generated_at"],
        "date": raw["date_tw"],
        "date_us_et": raw.get("date_us_et", ""),
        "market_data": market_data,
        # news：直接拍平到頂層
        **news,
        # analysis：直接拍平到頂層（market_data 已在上面獨立處理，剩下是 daily_summary/alert/market_pulse/…）
        **analysis,
        # earnings 放到 earnings_deep_analysis
        "earnings_deep_analysis": earnings if earnings else {
            "has_content": False, "companies": [], "industry_trends": [],
            "winners": [], "losers": [], "contradictions": [],
            "conclusion": "", "window": "", "overview": ""
        },
        # 從 raw 轉出的 preview
        "earnings_preview": _build_preview(raw.get("today_earnings", [])),
        # 確保關鍵欄位至少為 default
    }

    # 若 analysis 失敗 → 補 default 讓 schema 能過
    out.setdefault("market_pulse", {"cross_asset_signals": [], "dominant_theme": "",
                                     "hidden_risk": "", "hidden_opportunity": "",
                                     "key_level_to_watch": "", "historical_analog": "",
                                     "new_pattern": ""})
    out.setdefault("sentiment_analysis", {"stage": "無明確訊號", "stage_name": "正常市場",
                                           "one_line": "", "reliability": "中"})
    out.setdefault("top_stories", [])

    return out


def merge_weekly(raw: dict, parts: dict[str, dict]) -> dict:
    weekly = parts.get("weekly", {}) or {}
    out = {
        "generated_at": raw["generated_at"],
        "date": raw["date_tw"],
        "market_data": raw.get("market_data", {}),
        **weekly,
    }
    # schema 要求的 default
    out.setdefault("week_theme", "")
    out.setdefault("weekly_market_pulse", {})
    out.setdefault("weekly_sentiment_analysis", {})
    return out


def _build_preview(today_earnings: list[dict]) -> list[dict]:
    """把 yfinance earnings 轉為 earnings_preview 格式"""
    out = []
    for e in today_earnings:
        out.append({
            "company": e.get("ticker", ""),
            "ticker": e.get("ticker", ""),
            "report_time": e.get("time", "after-close"),
            "eps_estimate": "",
            "revenue_estimate": "",
            "what_to_watch": "",
            "yfinance_confirmed": True,
        })
    return out


# ── Phase 4: write + commit + push ──────────────────────────

def write_and_push(full_data: dict, mode: str, do_push: bool) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    filename = "full_data.json" if mode == "daily" else "weekly_full_data.json"
    out_path = os.path.join(OUT_DIR, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[Phase 3] Wrote {out_path} ({os.path.getsize(out_path):,} bytes)")

    if not do_push:
        print("  → --no-push flag set, skipping git")
        return

    print(f"\n[Phase 4] git add + commit + push...")
    tz = pytz.timezone("Asia/Taipei")
    stamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    commit_msg = f"mac: {mode} data {stamp}"

    def _git(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", REPO_ROOT] + args, capture_output=True, text=True)

    _git(["add", out_path])
    status = _git(["diff", "--cached", "--quiet"])
    if status.returncode == 0:
        print("  → no changes to commit")
        return

    r = _git(["commit", "-m", commit_msg])
    if r.returncode != 0:
        raise RuntimeError(f"git commit failed: {r.stderr}")
    r = _git(["push"])
    if r.returncode != 0:
        raise RuntimeError(f"git push failed: {r.stderr}")
    print(f"  ✓ pushed as '{commit_msg}'")


# ── Main ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "weekly", "auto"], default="auto")
    parser.add_argument("--only", help="只跑單一任務（news/analysis/earnings/weekly），debug 用")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    tz_tw = pytz.timezone("Asia/Taipei")
    mode = args.mode
    if mode == "auto":
        mode = "weekly" if datetime.now(tz_tw).weekday() == 6 else "daily"

    print(f"=== orchestrate.py mode={mode} ===")

    # Phase 1
    try:
        raw = run_phase1(mode)
    except Exception as e:
        print(f"✗ Phase 1 failed: {e}")
        sys.exit(1)

    # Phase 2
    if mode == "daily":
        parts, errors = run_phase2_daily(args.only)
    else:
        parts, errors = run_phase2_weekly(args.only)

    if errors:
        print(f"\n⚠ Phase 2 partial failure ({len(errors)} tasks):")
        for k, v in errors.items():
            print(f"  - {k}: {v[:200]}")

    if not parts:
        print("✗ Phase 2 produced nothing — not writing full_data.json (GHA will fallback)")
        sys.exit(2)

    # Phase 3 — merge + validate
    if mode == "daily":
        full_data = merge_daily(raw, parts)
    else:
        full_data = merge_weekly(raw, parts)

    ok, schema_errors = validate(full_data, mode=mode)
    if not ok:
        print(f"\n✗ Schema validation failed ({len(schema_errors)} errors):")
        for e in schema_errors:
            print(f"  - {e}")
        print("   → not writing full_data.json (GHA will fallback)")
        # 儲存到 /tmp 供 debug
        debug_path = f"/tmp/full_data_rejected_{mode}.json"
        with open(debug_path, "w") as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"   → debug output: {debug_path}")
        sys.exit(3)

    print(f"\n✓ Schema valid ({mode})")

    # Phase 4
    write_and_push(full_data, mode, do_push=not args.no_push)

    print("\n✓ orchestrate.py done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⚠ interrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=sys.stderr)
        raise
