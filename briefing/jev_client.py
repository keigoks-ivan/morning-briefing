"""
jev_client.py
-------------
TypeSafe System One（Jev）最小 HTTP 客戶端，給早報的事件判斷層用。

介面依 2026-09-22 查證的官方文件（docs.typesafe.ai/api）與 financial-analysis-bot
scripts/jev/probe.py 實際跑過的回應：
  POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer $TYPESAFE_API_KEY
  body   {"state": ..., "model": "jev-1.13.0", "questions": {id: {type, instructions, criteria}}}
  回應   {"model", "answers": {id: {...}}, "usage": {"input_tokens", "output_tokens"}}
  noul   → {"type": "noul", "noul": p}
  choice → {"type": "choice", "choice", "probabilities", "confidence"}
  score  → {"type": "score", "score", "legend", "probabilities", "confidence"}

設計原則：
- 沒 key、HTTP 失敗、回應格式不對 → 回 None，由呼叫端標「未判斷」，絕不補假答案。
- 同樣的 (model, state, questions) 只付一次錢：請求雜湊當快取鍵，快取由呼叫端保存（跨重跑）。
- 每次執行有請求數與 token 上限，超過就停止呼叫（剩下的標未判斷）。
- key 只從環境變數或 ~/.config/typesafe/api_key 讀，永不寫進 log、快取或輸出檔。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # 釘版本：門檻是對這一版調的，別名 jev-latest 會漂
PRICE_PER_MTOK = 0.042  # 官方 2026-09 價格：只收輸入 token
HTTP_TIMEOUT = 30
_RETRY_STATUS = {429, 529}


def get_api_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    key_file = Path.home() / ".config" / "typesafe" / "api_key"
    try:
        return key_file.read_text().strip() or None
    except OSError:
        return None


def request_hash(state, questions, model: str = MODEL) -> str:
    body = json.dumps({"model": model, "state": state, "questions": questions},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def estimate_tokens(obj) -> int:
    # 粗估（約 4 字元／token），只用來擋預算，不是帳單
    return len(json.dumps(obj, ensure_ascii=False)) // 4


def validate_response(resp, questions: dict) -> bool:
    """回應要有每一題、型別對、choice 選項在 criteria 裡；任何一點不對就整包不用。"""
    if not isinstance(resp, dict) or not isinstance(resp.get("answers"), dict):
        return False
    answers = resp["answers"]
    for qid, q in questions.items():
        a = answers.get(qid)
        if not isinstance(a, dict) or a.get("type") != q.get("type"):
            return False
        if q["type"] == "noul":
            if not isinstance(a.get("noul"), (int, float)):
                return False
        elif q["type"] == "choice":
            if a.get("choice") not in (q.get("criteria") or {}):
                return False
            if not isinstance(a.get("confidence"), (int, float)):
                return False
        elif q["type"] == "score":
            if not isinstance(a.get("score"), (int, float)) or not isinstance(a.get("confidence"), (int, float)):
                return False
    return True


class JevClient:
    """一次早報執行用一個實例。cache 由呼叫端傳入（dict：request_hash → response）。"""

    def __init__(self, api_key: str | None = None, cache: dict | None = None,
                 max_requests: int = 30, max_input_tokens: int = 400_000,
                 transport=None, model: str = MODEL):
        self.api_key = api_key
        self.cache = cache if cache is not None else {}
        self.max_requests = max_requests
        self.max_input_tokens = max_input_tokens
        self.transport = transport or self._http_post
        self.model = model
        self.stats = {"requests_sent": 0, "cache_hits": 0, "failures": 0, "skipped_budget": 0,
                      "input_tokens": 0, "est_cost_usd": 0.0, "errors": []}

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _http_post(self, body: bytes, api_key: str) -> dict:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        last = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                last = RuntimeError(f"HTTP {e.code}")
                if e.code in _RETRY_STATUS and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise last
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = RuntimeError(f"network: {type(e).__name__}")
                if attempt < 2:
                    time.sleep(1)
                    continue
                raise last
        raise last or RuntimeError("unknown")

    def ask(self, state, questions: dict) -> dict | None:
        """回 {"model", "answers", "usage", "request_hash", "cached"}；失敗回 None。"""
        h = request_hash(state, questions, self.model)
        hit = self.cache.get(h)
        if isinstance(hit, dict) and validate_response(hit, questions):
            self.stats["cache_hits"] += 1
            return {**hit, "request_hash": h, "cached": True}
        if not self.api_key:
            return None
        est = estimate_tokens({"state": state, "questions": questions})
        if (self.stats["requests_sent"] >= self.max_requests
                or self.stats["input_tokens"] + est > self.max_input_tokens):
            self.stats["skipped_budget"] += 1
            return None
        body = json.dumps({"state": state, "model": self.model, "questions": questions},
                          ensure_ascii=False).encode("utf-8")
        self.stats["requests_sent"] += 1
        try:
            resp = self.transport(body, self.api_key)
        except Exception as e:  # noqa: BLE001 — 任何失敗都只記錄類型，不帶 key
            self.stats["failures"] += 1
            self.stats["errors"].append(str(e)[:120])
            return None
        if not validate_response(resp, questions):
            self.stats["failures"] += 1
            self.stats["errors"].append("malformed response")
            return None
        used = int((resp.get("usage") or {}).get("input_tokens") or est)
        self.stats["input_tokens"] += used
        self.stats["est_cost_usd"] = round(self.stats["input_tokens"] / 1e6 * PRICE_PER_MTOK, 6)
        slim = {"model": resp.get("model", self.model), "answers": resp["answers"],
                "usage": resp.get("usage", {})}
        self.cache[h] = slim
        return {**slim, "request_hash": h, "cached": False}
