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
                if qid in ("novelty", "stage", "attribution"):
                    label, conf = case.get(qid, [opts[-1], 0.5])
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


def news_quality(failed_feeds: tuple = ()) -> dict:
    feeds = {f"Feed {i}": {"status": "ok", "entries": 10, "kept": 5, "blocked": 0} for i in range(8)}
    for name in failed_feeds:
        feeds[name] = {"status": "error", "entries": 0, "kept": 0, "blocked": 0, "error": "URLError"}
    return {"total_before_dedup": 353, "total_after_dedup": 313, "total_after_cap": 313,
            "blocked_by_whitelist": 332, "duplicate_removed": 40, "feeds": feeds}


ALL_VARS = [v for v, _, _ in VARIABLES]
