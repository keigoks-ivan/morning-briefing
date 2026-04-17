#!/bin/bash
# mac_runner/run_daily.sh
# ----------------------
# launchd 入口：每天 TW 05:55 觸發。
# 自動選 daily/weekly 模式（auto by weekday），跑完 orchestrate 並 push。
#
# 退出碼：
#   0 = 成功推上 full_data.json（GitHub Actions 會用 Mac 資料）
#   1 = Phase 1 失敗
#   2 = Phase 2 全部失敗（無 JSON 可合併）
#   3 = Schema 驗證失敗
#   其他 = 其他錯誤
# 不論何種失敗 → GitHub Actions 偵測到 missing/stale/invalid → 自動 fallback。

set -uo pipefail

REPO="/Users/ivanchang/Desktop/morning-briefing/morning-briefing"
LOG_DIR="$HOME/Library/Logs/morning-briefing"
mkdir -p "$LOG_DIR"

# 從 shell rc 帶進 PATH（launchd 起始 env 很乾淨，需要手動來源）
if [ -f "$HOME/.zshrc" ]; then
    # shellcheck disable=SC1091
    source "$HOME/.zshrc" 2>/dev/null || true
fi

# 確保 claude CLI 能被找到（npm global install 的路徑）
export PATH="$HOME/.claude/local:/opt/homebrew/bin:/usr/local/bin:$PATH"

TS=$(date +"%Y-%m-%d %H:%M:%S %Z")
echo "=== $TS | run_daily.sh start ==="
echo "PATH=$PATH"
echo "PWD=$REPO"

# 先 git pull 確保拿到最新 repo 狀態（萬一 prompt 或程式被本機或 GHA 改過）
cd "$REPO" || { echo "✗ cannot cd to $REPO"; exit 10; }

if ! git pull --ff-only origin main >> "$LOG_DIR/runner.out" 2>> "$LOG_DIR/runner.err"; then
    echo "⚠ git pull failed or has merge conflicts — continuing with local state"
fi

# 跑 orchestrate（auto 模式自己判斷 daily/weekly）
PYTHON="${PYTHON:-/usr/bin/python3}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3)"
fi

echo "Using python: $PYTHON"
echo "Using claude: $(command -v claude 2>/dev/null || echo MISSING)"

"$PYTHON" "$REPO/mac_runner/orchestrate.py" --mode auto
EXIT=$?

TS_END=$(date +"%Y-%m-%d %H:%M:%S %Z")
echo "=== $TS_END | run_daily.sh end (exit=$EXIT) ==="
exit $EXIT
