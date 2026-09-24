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
                elif "::" in qid:   # 想法／查核點的窄問題，qid 是 "idea_id::checkpoint_id"（見
                                    # ideas_layer.py 2026-09-23 晚改的逐則批次問法，一個 qid 對一個查核點）
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


# ── 想法判斷步驟的假 Claude CLI（2026-09-24 新增，取代舊版 FakeJev 問想法查核點那條路） ────
def fake_judge_call(verdict_by=None, default_verdict: str = "supports", default_reason: str = "測試理由",
                    fail: bool = False, calls: list | None = None):
    """回一個符合 ideas_layer.run_ideas_step(judge_call=...) 形狀的假函式：
    (system_prompt, user_prompt) -> {"verdicts": [...]}。verdict_by：{(item_id, idea_id,
    checkpoint_id): verdict} 覆寫，其餘用 default_verdict。fail=True 模擬整批判斷失敗（呼叫端
    要把涵蓋的 (item, checkpoint) 全部退回 candidate）。calls（可選，傳一個 list 進來）會被
    追加每次呼叫解析出來的 payload，方便測試檢查一次請求裡帶了哪些候選／查核點。"""
    verdict_by = verdict_by or {}

    def call(system_prompt: str, user_prompt: str) -> dict:
        payload = json.loads(user_prompt)
        if calls is not None:
            calls.append(payload)
        if fail:
            raise RuntimeError("claude CLI exited 1: boom")
        out = []
        for it in payload.get("items", []):
            for cp in it.get("checkpoints", []):
                key = (it["id"], cp["idea"], cp["checkpoint"])
                verdict = verdict_by.get(key, default_verdict)
                out.append({"id": it["id"], "idea": cp["idea"], "checkpoint": cp["checkpoint"],
                           "verdict": verdict, "reason_zh": default_reason})
        return {"verdicts": out}
    return call


def no_fulltext_dict(cands, **kwargs):
    """給 ideas_layer.run_ideas_step(full_text_fetch=...) 用的假全文抓取：離線測試預設不抓
    （跟 evidence_fixtures.no_fulltext 給事件判斷層本體用的是同一個精神，只是回傳形狀要對到
    evidence_fulltext.fetch_fulltext 的 {cid: outcome} 形狀）。"""
    return {}


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


def wide_rss_pool(today: str = TODAY) -> list[dict]:
    """離線重播用的合成「早報外」新聞池（briefing/ideas_layer.py 的早報外掃描，2026-09-23 晚
    新增）。不是真實抓到的新聞——刻意把 ideas.json 真實查核點（HBM 合約價、Cloudflare bot
    management…）的關鍵詞寫進標題，示範早報外掃描抓不抓得到；也刻意放一則過舊、一則純中文，
    示範程式把關會怎麼擋。跟 evidence_20260922_briefing.json 的早報候選是分開的兩份素材，
    early-report headlines 那邊不會出現這些標題。"""
    from datetime import datetime, timedelta
    d = datetime.strptime(today, "%Y-%m-%d")

    def ago(days: int) -> str:
        return (d - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    return [
        {"title": "SK Hynix and Samsung lock in higher HBM4 contract price deals for 2027 supply",
         "summary": "Both memory makers are said to have raised HBM4 contract prices for next year's allocations amid tight DRAM supply.",
         "link": "https://example.com/wide/hbm-contract-price", "source": "DigiTimes",
         "published": ago(0)},
        {"title": "Cloudflare expands signed bot management for verified AI shopping agents",
         "summary": "The network operator says its bot management product now issues verified-agent signatures so merchants can tell legitimate AI shopping agents from scrapers.",
         "link": "https://example.com/wide/cloudflare-bot-management", "source": "The Register",
         "published": ago(0)},
        {"title": "GE Vernova says gas turbine and transformer backlog now stretches past 2029",
         "summary": "Grid interconnection queues are lengthening as utilities wait longer for turbines and transformers, GE Vernova's CEO said on an investor call.",
         "link": "https://example.com/wide/ge-vernova-backlog", "source": "Reuters",
         "published": ago(0)},
        {"title": "Shopify expands agentic commerce checkout tools as AI agent shopping grows",
         "summary": "Shopify is rolling out agentic commerce APIs so AI agent checkout flows can complete purchases on merchant sites directly.",
         "link": "https://example.com/wide/shopify-agentic-commerce", "source": "TechCrunch",
         "published": ago(0)},
        {"title": "Micron quietly agrees new DRAM contract price deal, terms still pending",
         "summary": "A memory contract price deal for next quarter was reportedly agreed last week, though final terms are not yet disclosed.",
         "link": "https://example.com/wide/micron-old-contract-price", "source": "Nikkei Asia",
         "published": ago(6)},   # 過舊（>3 天）：應該被 stale_event 擋下
        {"title": "美光調漲第四季存儲器報價，客戶下單意願轉強",
         "summary": "美光近期調漲多項存儲器產品報價，市場人士指出下游客戶下單意願明顯轉強，出貨動能可望延續至明年。",
         "link": "https://example.com/wide/micron-zh", "source": "MoneyDJ",
         "published": ago(0)},   # 純中文：英文關鍵詞比對不到，只計入 chinese_count
        {"title": "Regional weather roundup: mild temperatures expected across the northeast",
         "summary": "No major weather disruptions are expected this week, forecasters said.",
         "link": "https://example.com/wide/weather", "source": "AP",
         "published": ago(0)},   # 對照組：跟任何查核點都無關，應該完全比對不到
    ]


def news_quality(failed_feeds: tuple = ()) -> dict:
    feeds = {f"Feed {i}": {"status": "ok", "entries": 10, "kept": 5, "blocked": 0} for i in range(8)}
    for name in failed_feeds:
        feeds[name] = {"status": "error", "entries": 0, "kept": 0, "blocked": 0, "error": "URLError"}
    return {"total_before_dedup": 353, "total_after_dedup": 313, "total_after_cap": 313,
            "blocked_by_whitelist": 332, "duplicate_removed": 40, "feeds": feeds}


ALL_VARS = [v for v, _, _ in VARIABLES]
