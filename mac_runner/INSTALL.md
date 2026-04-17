# Mac mini 端安裝

在你的 Mac mini 上跑一次下面流程即可。

## 前置條件

```bash
# Claude Code CLI（用 Max plan 認證）
npm install -g @anthropic-ai/claude-code
claude login
# 瀏覽器開 OAuth，完成後 token 進 keychain

# Python 依賴
cd ~/Desktop/morning-briefing/morning-briefing
pip3 install -r requirements.txt
```

## 安裝 launchd

```bash
cd ~/Desktop/morning-briefing/morning-briefing

# 1. 複製 plist 到 LaunchAgents
cp mac_runner/com.ivan.morningbriefing.plist ~/Library/LaunchAgents/

# 2. 載入（立即生效，明早 05:55 會跑）
launchctl load ~/Library/LaunchAgents/com.ivan.morningbriefing.plist

# 3. 驗證
launchctl list | grep morningbriefing
# 應該看到類似：  -  0  com.ivan.morningbriefing
```

## 手動測試（推薦先跑一次驗證）

### 只跑 Phase 1（抓免費數據）

```bash
python3 mac_runner/fetch_raw_data.py --mode daily
cat /tmp/raw_data.json | head -30
```

### 只跑一個 Claude Code 任務（debug 某個 prompt）

```bash
python3 mac_runner/orchestrate.py --mode daily --only earnings --no-push
# 輸出 docs/briefing/full_data.json，但不推 GitHub
```

### 跑完整 pipeline 但不推

```bash
python3 mac_runner/orchestrate.py --mode auto --no-push
```

### 完整跑 + push（正式）

```bash
bash mac_runner/run_daily.sh
# 或手動觸發 launchd：
launchctl kickstart -k gui/$(id -u)/com.ivan.morningbriefing
```

## Render cron 需手動改

GitHub Actions 的 weekly 已經改成 TW 06:15，但**日報**是透過 Render Cron Job → `trigger.py` 觸發。

到 Render Dashboard 把日報 cron 從 `21:55 UTC` 改成 `22:15 UTC`（= TW 06:15）。

不改的話，GHA 會在 05:55 啟動（Mac 同時間也在跑）→ 看到舊檔案 → fallback 跑 API。功能還是正常，只是沒享受到 Mac 跑出來的結果。

## 看 log

```bash
tail -100 ~/Library/Logs/morning-briefing/runner.out
tail -100 ~/Library/Logs/morning-briefing/runner.err
```

## 停用 / 恢復

```bash
# 出差暫停
launchctl unload ~/Library/LaunchAgents/com.ivan.morningbriefing.plist

# 回來恢復
launchctl load ~/Library/LaunchAgents/com.ivan.morningbriefing.plist
```

停用期間 GHA 會自動 fallback 到 API 版本，briefing 照常發送。

## Claude Code token 失效怎麼辦

幾個月一次可能會出現。症狀：log 裡 `claude exited non-zero` 且訊息提到 authentication。

```bash
claude login
# 重新 OAuth 即可，不用改任何設定
```

## 路徑常量（若搬 repo 要改）

- `run_daily.sh` 裡的 `REPO="..."`
- `com.ivan.morningbriefing.plist` 裡的 `ProgramArguments`
- `com.ivan.morningbriefing.plist` 裡的 log 路徑
