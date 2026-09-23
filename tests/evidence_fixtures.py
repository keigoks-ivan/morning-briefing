"""離線驗收共用：2026-09-22 早報案例、公開持倉、DD universe、假 Jev（測試不呼叫付費 API）。"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT / "briefing"))

from evidence_ledger import Ledger  # noqa: E402
from evidence_questions import VARIABLES  # noqa: E402
from jev_client import JevClient  # noqa: E402

TODAY = "2026-09-22"


def load(name: str) -> dict:
    return json.loads((FX / name).read_text(encoding="utf-8"))


def briefing_data() -> dict:
    d = load("evidence_20260922_briefing.json")
    return {k: v for k, v in d.items() if not k.startswith("_")}


def watchlist() -> list[dict]:
    return load("evidence_dd_universe.json")["watchlist"]


def holdings() -> dict:
    return {k: v for k, v in load("evidence_public_holdings.json").items() if not k.startswith("_")}


def seed_ledger() -> Ledger:
    payload = json.loads((ROOT / "data" / "evidence_seed_ledger.json").read_text(encoding="utf-8"))
    return Ledger.from_json(payload, True, "seed (offline test)")


def _choice(label: str, conf: float, options: list[str]) -> dict:
    rest = [o for o in options if o != label]
    other = round((1 - conf) / max(1, len(rest)), 4)
    return {"type": "choice", "choice": label, "confidence": conf,
            "probabilities": {o: (conf if o == label else other) for o in options}}


class FakeJev:
    """假的 transport：依 state.today.headline 找劇本，回完整的 API 形狀答案。"""

    def __init__(self, overrides: dict | None = None, fail: bool = False):
        self.script = load("evidence_20260922_fake_jev.json")
        self.cases = copy.deepcopy(self.script["cases"])
        for k, v in (overrides or {}).items():
            self.cases.setdefault(k, {}).update(v)
        self.fail = fail
        self.calls = 0

    def __call__(self, body: bytes, api_key: str) -> dict:
        self.calls += 1
        if self.fail:
            raise RuntimeError("HTTP 503")
        req = json.loads(body.decode("utf-8"))
        state, questions = req["state"], req["questions"]
        headline = state["today"]["headline"]
        case = next((v for k, v in self.cases.items() if k in headline), None) or {}
        answers = {}
        for qid, q in questions.items():
            if q["type"] == "noul":
                i = int(qid.split("_")[1])
                name = state["candidate_companies"][i]
                answers[qid] = {"type": "noul", "noul": (case.get("parties") or {}).get(name, 0.1)}
            elif q["type"] == "score":
                score, conf = case.get("importance", [1.0, 0.5])
                answers[qid] = {"type": "score", "score": score, "confidence": conf,
                                "legend": {str(i): c for i, c in enumerate(q["criteria"])},
                                "probabilities": {str(i): 0.25 for i in range(len(q["criteria"]))}}
            else:
                opts = list(q["criteria"])
                if qid in ("novelty", "stage", "attribution", "timing"):
                    label, conf = case.get(qid, [opts[-1], 0.5])
                elif qid == "verdict":   # 2026-09-23：投資想法查核點的窄問題（見 ideas_layer.py）
                    label, conf = case.get("idea_verdict", [opts[-1], 0.5])
                elif qid.startswith("var_"):
                    v = (case.get("vars") or {}).get(qid[4:])
                    label, conf = (v[0], v[1]) if v else ("none", 0.9)
                elif qid.startswith("dir_"):
                    v = (case.get("vars") or {}).get(qid[4:])
                    label, conf = (v[2], 0.8) if v else ("mixed_or_unclear", 0.7)
                else:
                    label, conf = opts[-1], 0.5
                answers[qid] = _choice(label, conf, opts)
        return {"model": self.script["model"], "answers": answers,
                "usage": {"input_tokens": len(body) // 4, "output_tokens": 0}}


def fake_client(overrides: dict | None = None, fail: bool = False, cache: dict | None = None) -> tuple[JevClient, FakeJev]:
    fake = FakeJev(overrides, fail)
    return JevClient(api_key="test-key-not-real", cache=cache if cache is not None else {}, transport=fake), fake


def no_fetch(url: str, timeout: int = 15):
    return None, "missing"


_OFFICIAL_DIR = FX / "official_20260922"
_OFFICIAL_INDEX = json.loads((_OFFICIAL_DIR / "index.json").read_text(encoding="utf-8"))["urls"]


def offline_sources(url: str, timeout: int = 15):
    """官方來源的離線快照（2026-09-22 晚間實抓）；快照裡沒有的網址當作抓取失敗。"""
    fn = _OFFICIAL_INDEX.get(url)
    if not fn:
        return None, "error:offline test"
    return (_OFFICIAL_DIR / fn).read_text(encoding="utf-8"), "ok"


def all_sources_down(url: str, timeout: int = 15):
    return None, "error:ConnectionError"


def no_fulltext(cands):
    """離線測試預設：不抓全文（不連網）。每則候選都當作沒試過（not_attempted）。"""
    return {}


def sample_ideas() -> list[dict]:
    """想法／查核點層（ideas_layer.py）測試用的小型 ideas.json，不是真實資料。查核點刻意各自
    只踩一條比對規則，方便測試分開驗證（見 tests/test_ideas_layer.py）。"""
    return [
        {
            "id": "ai-scissors", "short": "AI 剪刀差", "url": "/ideas/ai-scissors.html", "status": "active",
            "checkpoints": [
                {"id": "cp-a-only", "label": "只靠規則 (a)：當事公司＋一個關鍵詞", "companies": ["TSM"],
                 "keywords": ["cowos"], "themes": [],
                 "supports_if": "The news reports CoWoS capacity expanding.",
                 "refutes_if": "The news reports CoWoS capacity being cut back."},
                {"id": "cp-b1-two", "label": "只靠規則 (b)：兩個不同關鍵詞", "companies": [],
                 "keywords": ["cowos", "capacity"], "themes": [],
                 "supports_if": "The news reports CoWoS capacity expanding.",
                 "refutes_if": "The news reports CoWoS capacity being cut back."},
                {"id": "cp-b1-phrase", "label": "只靠規則 (b)：一個三個字以上的關鍵詞片語", "companies": [],
                 "keywords": ["technology validation lab"], "themes": [],
                 "supports_if": "The news reports a new technology validation lab.",
                 "refutes_if": "The news reports a technology validation lab being cancelled."},
                {"id": "cp-b2-theme", "label": "只靠規則 (b)：主題已確認＋一個關鍵詞", "companies": [],
                 "keywords": ["packaging"], "themes": ["AdvancedPackaging"],
                 "supports_if": "The news reports packaging activity increasing.",
                 "refutes_if": "The news reports packaging activity decreasing."},
                {"id": "cp-no-match", "label": "不該被比對到：關鍵詞不在任何候選文字裡", "companies": ["NBIS"],
                 "keywords": ["quantum computing breakthrough"], "themes": [],
                 "supports_if": "The news reports a quantum computing breakthrough.",
                 "refutes_if": "The news reports a quantum computing setback."},
                {"id": "cp-financing", "label": "資料中心融資（靠關鍵詞數量，非當事公司）", "companies": ["ORCL"],
                 "keywords": ["bond", "bonds", "debt", "financing"], "themes": ["AIDataCenter"],
                 "supports_if": "The news reports data centre or AI financing being raised successfully.",
                 "refutes_if": "The news reports data centre or AI financing failing or being pulled."},
            ],
        },
        {
            "id": "dormant-idea", "short": "已下架的想法", "url": "/ideas/dormant.html", "status": "retired",
            "checkpoints": [
                {"id": "cp-retired", "label": "不該被比對到：想法已下架", "companies": ["TSM"],
                 "keywords": ["cowos", "capacity"], "themes": ["AdvancedPackaging"],
                 "supports_if": "x", "refutes_if": "y"},
            ],
        },
    ]


def news_quality(failed_feeds: tuple = ()) -> dict:
    feeds = {f"Feed {i}": {"status": "ok", "entries": 10, "kept": 5, "blocked": 0} for i in range(8)}
    for name in failed_feeds:
        feeds[name] = {"status": "error", "entries": 0, "kept": 0, "blocked": 0, "error": "URLError"}
    return {"total_before_dedup": 353, "total_after_dedup": 313, "total_after_cap": 313,
            "blocked_by_whitelist": 332, "duplicate_removed": 40, "feeds": feeds}


ALL_VARS = [v for v, _, _ in VARIABLES]
