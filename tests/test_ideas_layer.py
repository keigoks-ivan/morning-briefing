"""投資想法／查核點層（briefing/ideas_layer.py）離線測試。不呼叫付費 API、不連網、不寄信。

涵蓋：載入順序（IDEAS_JSON_PATH → fetch → 跳過）、比對規則 (a)/(b)、跟 run_evidence_layer
的整合（分類篩選、Jev 未判斷、每天 8 對上限）、idea_hits.json 的合併／去重／冪等／保留天數、
news 頁與 email 摘要的渲染。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _mod in ("anthropic", "google", "google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

import evidence_fixtures as fx  # noqa: E402

import evidence_layer  # noqa: E402
import html_template  # noqa: E402
import ideas_layer  # noqa: E402
from evidence_ledger import EntityMatcher, Ledger  # noqa: E402


def run(jev=None, ideas="default", fetch=None, hits_fetch=None):
    if jev is None:
        jev, _ = fx.fake_client()
    ideas_arg = fx.sample_ideas() if ideas == "default" else ideas
    return evidence_layer.run_evidence_layer(
        fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
        ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev,
        fetch=fetch or fx.no_fetch, sec_user_agent=None, official_fetch=fx.offline_sources,
        full_text_fetch=fx.no_fulltext, ideas=ideas_arg)


def item(ev, fragment):
    hits = [it for it in ev["items"] if fragment in it["headline"]]
    assert len(hits) == 1, f"{fragment}: {len(hits)} items"
    return hits[0]


class LoadIdeasTests(unittest.TestCase):
    def test_local_path_loads_ideas(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ideas.json"
            p.write_text(json.dumps({"ideas": fx.sample_ideas()}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"IDEAS_JSON_PATH": str(p)}):
                ideas, status = ideas_layer.load_ideas(fx.no_fetch)
            self.assertEqual(status, "ok")
            self.assertEqual([i["id"] for i in ideas], ["ai-scissors", "dormant-idea"])

    def test_local_path_missing_file_is_unavailable(self):
        with mock.patch.dict(os.environ, {"IDEAS_JSON_PATH": "/nonexistent/ideas.json"}):
            ideas, status = ideas_layer.load_ideas(fx.no_fetch)
        self.assertEqual((ideas, status), ([], "unavailable"))

    def test_fetch_used_when_no_env_var(self):
        def fetch(url, timeout=15):
            self.assertEqual(url, ideas_layer.IDEAS_URL)
            return {"ideas": fx.sample_ideas()}, "ok"
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEAS_JSON_PATH", None)
            ideas, status = ideas_layer.load_ideas(fetch)
        self.assertEqual(status, "ok")
        self.assertEqual(len(ideas), 2)

    def test_fetch_404_is_unavailable_not_yet_deployed(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEAS_JSON_PATH", None)
            ideas, status = ideas_layer.load_ideas(fx.no_fetch)   # no_fetch 回 (None, "missing")
        self.assertEqual((ideas, status), ([], "unavailable"))

    def test_fetch_error_is_unavailable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEAS_JSON_PATH", None)
            ideas, status = ideas_layer.load_ideas(fx.all_sources_down)
        self.assertEqual((ideas, status), ([], "unavailable"))


class LoadResearchTests(unittest.TestCase):
    """docs/ideas/data/research.json（另一個雲端 routine idea-watch-auto 產出的「深入查核」結果，
    2026-09-23 晚新增）跟 load_ideas 同一種載入慣例，這裡照同一套情境測。"""

    SAMPLE = {"schema": "idea-research-v1", "run": {"date": "2026-09-22", "status": "ok"},
             "status": {}, "entries": [], "changes": []}

    def test_local_path_loads_research(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "research.json"
            p.write_text(json.dumps(self.SAMPLE), encoding="utf-8")
            with mock.patch.dict(os.environ, {"IDEA_RESEARCH_JSON_PATH": str(p)}):
                data, status = ideas_layer.load_research(fx.no_fetch)
            self.assertEqual(status, "ok")
            self.assertEqual(data["run"]["date"], "2026-09-22")

    def test_local_path_missing_file_is_unavailable(self):
        with mock.patch.dict(os.environ, {"IDEA_RESEARCH_JSON_PATH": "/nonexistent/research.json"}):
            data, status = ideas_layer.load_research(fx.no_fetch)
        self.assertEqual((data, status), (None, "unavailable"))

    def test_fetch_used_when_no_env_var(self):
        def fetch(url, timeout=15):
            self.assertEqual(url, ideas_layer.RESEARCH_URL)
            return self.SAMPLE, "ok"
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEA_RESEARCH_JSON_PATH", None)
            data, status = ideas_layer.load_research(fetch)
        self.assertEqual(status, "ok")
        self.assertEqual(data["run"]["date"], "2026-09-22")

    def test_fetch_404_is_unavailable_not_yet_deployed(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEA_RESEARCH_JSON_PATH", None)
            data, status = ideas_layer.load_research(fx.no_fetch)
        self.assertEqual((data, status), (None, "unavailable"))

    def test_fetch_error_is_unavailable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEA_RESEARCH_JSON_PATH", None)
            data, status = ideas_layer.load_research(fx.all_sources_down)
        self.assertEqual((data, status), (None, "unavailable"))


_TSMC_TEXT = ("TSMC rallies equipment and material suppliers into Kaohsiung packaging park. Taiwan broke ground "
             "on the Baipu advanced packaging industrial park in Kaohsiung, anchored by TSMC facilities "
             "including a technology validation lab and CoWoS tool validation mini-loop. TrendForce reports "
             "TSMC is also reportedly eyeing an AUO site for CoPoS capacity.")


class CatalogDueTests(unittest.TestCase):
    """ideas_layer._catalog 攤平 due 欄位（Task 3）：只收 active 想法，缺 due 也不炸。"""

    def test_catalog_carries_due_dates_for_active_idea_only(self):
        ideas = [
            {"id": "a", "short": "A", "url": "/a", "status": "active",
             "checkpoints": [{"id": "cp1", "label": "L1",
                              "due": [{"date": "2026-10-01", "label": "E1", "approx": True}]}]},
            {"id": "b", "short": "B", "url": "/b", "status": "retired",
             "checkpoints": [{"id": "cp1", "label": "L1",
                              "due": [{"date": "2026-10-01", "label": "不該出現", "approx": False}]}]},
            {"id": "c", "short": "C", "url": "/c", "status": "active",
             "checkpoints": [{"id": "cp1", "label": "L1"}]},   # 沒有 due 欄位
        ]
        catalog = ideas_layer._catalog(ideas)
        self.assertEqual(len(catalog["a"]["due"]), 1)
        self.assertEqual(catalog["a"]["due"][0]["label"], "E1")
        self.assertEqual(catalog["a"]["due"][0]["checkpoint"], "cp1")
        self.assertEqual(catalog["b"]["due"], [])
        self.assertEqual(catalog["c"]["due"], [])


class MatchingRuleTests(unittest.TestCase):
    """規則見 CLAUDE.md「投資想法」段；查核點刻意各踩一條規則，見 evidence_fixtures.sample_ideas。"""

    IDEAS = fx.sample_ideas()

    def _ids(self, company_keys=(), themes=()):
        matched = ideas_layer.match_checkpoints(_TSMC_TEXT, list(company_keys), list(themes), self.IDEAS)
        return {cp["id"] for _, cp, _ in matched}

    def test_rule_a_company_plus_one_keyword(self):
        self.assertIn("cp-a-only", self._ids(company_keys=["TSM"]))

    def test_rule_a_fails_without_company_or_second_signal(self):
        self.assertNotIn("cp-a-only", self._ids())

    def test_rule_b_two_distinct_keywords_no_company_needed(self):
        self.assertIn("cp-b1-two", self._ids())

    def test_rule_b_one_three_word_phrase_no_company_needed(self):
        self.assertIn("cp-b1-phrase", self._ids())

    def test_rule_b_theme_confirmed_plus_one_keyword(self):
        self.assertNotIn("cp-b2-theme", self._ids())
        self.assertIn("cp-b2-theme", self._ids(themes=["AdvancedPackaging"]))

    def test_no_match_when_keyword_absent_from_text(self):
        self.assertNotIn("cp-no-match", self._ids(company_keys=["NBIS"]))

    def test_inactive_idea_never_matches_even_with_full_signal(self):
        matched = ideas_layer.match_checkpoints(_TSMC_TEXT, ["TSM"], ["AdvancedPackaging"], self.IDEAS)
        self.assertFalse(any(idea["id"] == "dormant-idea" for idea, _, _ in matched))


class IdeasIntegrationTests(unittest.TestCase):
    """跟 run_evidence_layer 的整合：分類篩選、Jev 未判斷、每天 8 對上限、全文不落地。"""

    def test_progress_update_item_gets_matched_checkpoints(self):
        ev, _ = run()
        it = item(ev, "Kaohsiung packaging park")
        ids = {h["checkpoint"] for h in it["ideas"]}
        self.assertEqual(ids, {"cp-a-only", "cp-b1-two", "cp-b1-phrase", "cp-b2-theme"})
        for h in it["ideas"]:
            self.assertIn(h["verdict"], ("supports", "refutes", "unrelated", "unjudged"))
            self.assertEqual(h["idea"], "ai-scissors")
            self.assertTrue(h["label"])

    def test_excluded_classes_get_no_ideas_even_with_matching_keywords(self):
        # SB Energy=needs_review, AMD=market_move_only, Copilot=known_restatement：都不是
        # new_fact／progress_update，就算關鍵詞對得上也不該被比對到（跟能進 top 的分類同一組）
        ideas = [{"id": "catch-all", "short": "測試", "url": "/x", "status": "active",
                 "checkpoints": [{"id": "cp-catch", "label": "test", "companies": [],
                                  "keywords": ["trillion", "additional", "copilot"], "themes": [],
                                  "supports_if": "s", "refutes_if": "r"}]}]
        ev, _ = run(ideas=ideas)
        for frag in ("SB Energy", "AMD market cap tops", "Copilot tops 30 million"):
            self.assertEqual(item(ev, frag)["ideas"], [], frag)

    def test_jev_budget_exhausted_keeps_match_as_unjudged(self):
        # 沒有 key 的話連主分類都會是 not_judged（進不了新事實／進度更新，就沒有想法可比對），
        # 所以這裡改用「主分類問完剛好把預算用完」模擬想法層自己被擋預算的情況：fixture 有 6 則
        # 候選（各問一次 Jev），max_requests=6 讓後面想法查核點的請求全部被預算擋下。
        fake = fx.FakeJev()
        jev = evidence_layer.JevClient(api_key="test-key-not-real", cache={}, transport=fake, max_requests=6)
        ev, _ = run(jev=jev)
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(it["classification"]["class"], "progress_update")   # 主分類正常問完
        self.assertTrue(it["ideas"])
        for h in it["ideas"]:
            self.assertEqual(h["verdict"], "unjudged")
            self.assertIsNone(h["confidence"])

    def test_no_ideas_configured_marks_step_unavailable(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("IDEAS_JSON_PATH", None)
            ev, _ = run(ideas=None, fetch=fx.no_fetch)
        self.assertEqual(ev["ideas"]["status"], "unavailable")
        for it in ev["items"]:
            self.assertEqual(it["ideas"], [])
        # 就算沒讀到 ideas.json，idea_hits.json 還是要重新整理（今天沒有新列）並寫出
        self.assertIsNotNone(ev["idea_hits"])
        self.assertEqual(ev["idea_hits"]["hits"], [])

    def test_all_checkpoints_matched_by_one_item_are_batched_into_one_request(self):
        # 2026-09-23 晚改成逐則批次問法：一則新聞命中幾個查核點，就在同一次 Jev 請求裡問完，
        # 不是每對 (item, checkpoint) 各一個請求，所以一則新聞就算命中 12 個查核點也不會被
        # 「每天 8 對」卡住——會卡的是「每天最多幾則新聞」（見 ItemCapTests）。
        checkpoints = [{"id": f"cp{i}", "label": f"test{i}", "companies": [], "keywords": ["cowos", "capacity"],
                        "themes": [], "supports_if": "s", "refutes_if": "r"} for i in range(12)]
        ideas = [{"id": "many-checkpoints", "short": "多查核點", "url": "/x", "status": "active",
                 "checkpoints": checkpoints}]
        jev, fake = fx.fake_client()
        ev, _ = run(ideas=ideas, jev=jev)
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(len(it["ideas"]), 12)
        for h in it["ideas"]:
            self.assertIsNotNone(h["confidence"])
            self.assertNotEqual(h["verdict"], "unjudged")
        self.assertEqual(ev["ideas"]["matched_pairs"], 12)
        self.assertEqual(ev["ideas"]["asked"], 1)   # 一則新聞，一個請求（不是 12 個請求）

    def test_ideas_step_failure_does_not_break_evidence_layer(self):
        def boom(fetch):
            raise RuntimeError("ideas step down")
        with mock.patch.object(ideas_layer, "load_ideas", boom):
            ev, _ = run(ideas=None, fetch=fx.no_fetch)
        self.assertEqual(ev["ideas"]["status"], "unavailable")
        self.assertIn("ideas step error", ev["ideas"]["reason"])
        self.assertTrue(ev["items"])   # 其餘事件判斷層照常
        for it in ev["items"]:
            self.assertEqual(it["ideas"], [])

    def test_full_text_reaches_idea_jev_state_but_never_persisted(self):
        marker = "IDEA_FULLTEXT_MARKER_" + ("Q" * 30)

        def ft_fetch(cands):
            out = {}
            for c in cands:
                if "Kaohsiung packaging park" in c["headline"]:
                    out[c["cid"]] = {"status": "ok", "url": "https://example.com/x", "domain": "example.com",
                                     "word_count": 500, "excerpt": (f"{marker} more CoWoS capacity text ") * 20,
                                     "quotes": [], "figures": []}
            return out

        jev, _fake = fx.fake_client()
        orig_transport = jev.transport
        captured = []

        def spy(body, api_key):
            captured.append(json.loads(body))
            return orig_transport(body, api_key)
        jev.transport = spy

        ev, ledger = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, full_text_fetch=ft_fetch,
            ideas=fx.sample_ideas())

        idea_reqs = [r for r in captured if any("::" in qid for qid in r.get("questions", {}))]
        self.assertTrue(idea_reqs)
        self.assertTrue(any(marker in json.dumps(r["state"]) for r in idea_reqs))
        self.assertNotIn(marker, json.dumps(ev, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as td:
            written = evidence_layer.save_outputs(ev, ledger, Path(td), fx.TODAY)
            self.assertIn("idea_hits.json", written)
            for fn in written:
                self.assertNotIn(marker, (Path(td) / fn).read_text(encoding="utf-8"))


class BatchingTests(unittest.TestCase):
    """一則新聞命中多個查核點，Jev 只收到一個請求、裡面有多題（2026-09-23 晚改的逐則批次問法）。"""

    def test_one_jev_request_carries_all_matched_checkpoints_for_the_item(self):
        jev, fake = fx.fake_client()
        orig_transport = jev.transport
        captured = []

        def spy(body, api_key):
            captured.append(json.loads(body))
            return orig_transport(body, api_key)
        jev.transport = spy

        ev, _ = run(jev=jev)   # fx.sample_ideas() 的 ai-scissors 對 Kaohsiung 候選命中 4 個查核點
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(len(it["ideas"]), 4)
        idea_reqs = [r for r in captured
                    if "Kaohsiung packaging park" in (r.get("state", {}).get("today", {}).get("headline", ""))
                    and any("::" in qid for qid in r.get("questions", {}))]
        self.assertEqual(len(idea_reqs), 1)   # 4 個查核點只發了 1 個請求
        self.assertEqual(len(idea_reqs[0]["questions"]), 4)   # 該請求裡有 4 題


class ItemCapTests(unittest.TestCase):
    """每天最多幾則新聞問 Jev（不是每對 (item, checkpoint)），見 ideas_layer.run_ideas_step。"""

    IDEA = [{"id": "cap-test", "short": "上限測試", "url": "/x", "status": "active",
            "checkpoints": [{"id": "cp1", "label": "test", "companies": [], "keywords": ["alpha", "beta"],
                             "themes": [], "supports_if": "s", "refutes_if": "r"}]}]

    def _briefing_item(self, i: int) -> tuple[dict, dict]:
        cid = f"c{i}"
        headline = f"Alpha beta story number {i} about nothing in particular"
        it = {"id": cid, "headline": headline, "classification": {"class": "new_fact"},
             "companies": [], "routes": {}, "event_date": fx.TODAY, "source_date": fx.TODAY, "source": "Reuters"}
        cand = {"cid": cid, "headline": headline,
               "text": "Alpha and beta both appear in this story's body text.",
               "source": "Reuters", "source_date": fx.TODAY, "rss": []}
        return it, cand

    def test_briefing_item_cap_leaves_the_rest_unjudged(self):
        items, cand_by_id = [], {}
        for i in range(10):
            it, cand = self._briefing_item(i)
            items.append(it)
            cand_by_id[it["id"]] = cand
        jev, _fake = fx.fake_client()
        result = ideas_layer.run_ideas_step(items, cand_by_id, jev, fx.TODAY, ideas=self.IDEA,
                                            fetch=fx.no_fetch)
        judged_items = [it for it in items if it["ideas"] and it["ideas"][0]["confidence"] is not None]
        unjudged_items = [it for it in items if it["ideas"] and it["ideas"][0]["confidence"] is None]
        self.assertEqual(len(judged_items), ideas_layer.MAX_BRIEFING_IDEA_ITEMS)
        self.assertEqual(len(unjudged_items), 10 - ideas_layer.MAX_BRIEFING_IDEA_ITEMS)
        self.assertEqual(result["matched_pairs"], 10)
        self.assertEqual(result["asked"], ideas_layer.MAX_BRIEFING_IDEA_ITEMS)
        for it in unjudged_items:
            self.assertEqual(it["ideas"][0]["verdict"], "unjudged")

    def test_wide_item_cap_matches_max_wide_idea_items(self):
        ideas = self.IDEA
        matcher = EntityMatcher({})
        ledger = Ledger([])
        pool = []
        for i in range(10):
            pool.append({"title": f"Alpha beta wide story {i}", "summary": "alpha and beta both mentioned here",
                        "link": f"https://example.com/wide{i}", "source": "Wire", "published": f"{fx.TODAY} 09:00"})
        jev, _fake = fx.fake_client()
        result = ideas_layer.run_ideas_step([], {}, jev, fx.TODAY, ideas=ideas, fetch=fx.no_fetch,
                                            matcher=matcher, rss_items=pool, ledger=ledger)
        ws = result["wide_scan"]
        self.assertEqual(ws["pool_size"], 10)
        self.assertEqual(ws["matched_items"], 10)
        self.assertEqual(ws["asked_items"], ideas_layer.MAX_WIDE_IDEA_ITEMS)


class WideScanTests(unittest.TestCase):
    """早報外掃描的程式把關（ideas_layer._wide_scan），直接測，不繞經 run_evidence_layer。"""

    # 兩個關鍵詞（不靠公司辨識，因為測試用的是空 routing 的 EntityMatcher，見 _matcher）：
    # 規則 (b) 兩個不同關鍵詞就算命中，見 ideas_layer.match_checkpoints。
    IDEAS = [{"id": "wide-idea", "short": "早報外測試", "url": "/x", "status": "active",
             "checkpoints": [{"id": "cp1", "label": "test", "companies": ["TSM"],
                              "keywords": ["cowos", "capacity"],
                              "themes": [], "supports_if": "s", "refutes_if": "r"}]}]

    def _matcher(self):
        # 最小 routing：只認得 TSM（別名 TSMC），讓靠公司辨識的把關（ledger_known_figure）有
        # 東西可以比對；規則 (a)／(b) 的查核點命中本身不靠這個，靠 self.IDEAS 的兩個關鍵詞。
        return EntityMatcher({"companies": {"TSM": {"name": "TSMC", "aliases": ["TSMC"]}}})

    def test_pool_item_already_used_by_a_briefing_candidate_is_excluded(self):
        pool = [{"title": "TSMC boosts CoWoS capacity again", "summary": "", "link": "https://x/a",
                "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        cand_by_id = {"c1": {"headline": "TSMC boosts CoWoS", "rss": [{"url": "https://x/a"}]}}
        cands, stats = ideas_layer._wide_scan(pool, cand_by_id, self._matcher(), Ledger([]), self.IDEAS,
                                              fx.TODAY, [])
        self.assertEqual(stats["already_in_candidates"], 1)
        self.assertEqual(cands, [])

    def test_chinese_item_is_counted_but_not_matched(self):
        pool = [{"title": "台積電傳出下修財測，市場關注後續影響", "summary": "法人表示需求動能轉弱。",
                "link": "https://x/b", "published": f"{fx.TODAY} 09:00", "source": "MoneyDJ"}]
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [])
        self.assertEqual(stats["chinese_count"], 1)
        self.assertEqual(stats["matched_items"], 0)
        self.assertEqual(cands, [])

    def test_stale_event_older_than_three_days_is_skipped(self):
        from datetime import datetime, timedelta
        old = (datetime.strptime(fx.TODAY, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d %H:%M")
        pool = [{"title": "TSMC expands CoWoS capacity lines further", "summary": "", "link": "https://x/c",
                "published": old, "source": "Reuters"}]
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [])
        self.assertEqual(stats["matched_items"], 1)
        self.assertEqual(stats["skipped_by_reason"]["stale_event"], 1)
        self.assertEqual(cands, [])

    def test_ledger_known_figure_for_shared_company_is_skipped(self):
        pool = [{"title": "TSMC adds 30 million units of CoWoS capacity", "summary": "",
                "link": "https://x/d", "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        prior = {"fact_key": "fact_x", "first_seen": "2026-09-10", "companies": ["TSM"], "subjects": [],
                "figures": ["n:3e+07"], "terms": [], "tokens": []}
        ledger = Ledger([prior])
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), ledger, self.IDEAS, fx.TODAY, [])
        self.assertEqual(stats["matched_items"], 1)
        self.assertEqual(stats["skipped_by_reason"]["ledger_known_figure"], 1)
        self.assertEqual(cands, [])

    def test_duplicate_of_idea_hits_history_by_url_is_skipped(self):
        pool = [{"title": "TSMC ramps another CoWoS capacity expansion", "summary": "", "link": "https://x/e",
                "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        history = [{"url": "https://x/e", "headline": "different headline"}]
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, history)
        self.assertEqual(stats["skipped_by_reason"]["hits_history_duplicate"], 1)
        self.assertEqual(cands, [])

    def test_near_duplicate_of_briefing_headline_is_skipped(self):
        headline = "TSMC rallies equipment and material suppliers into Kaohsiung packaging park"
        cand_by_id = {"c1": {"headline": headline, "rss": []}}
        # 標題完全相同（真實世界更常見的是不同媒體改幾個字轉述同一則），保證正規化後的鍵相等，
        # 不必依賴字詞 Jaccard 門檻的邊界值
        pool = [{"title": headline, "summary": "cowos capacity", "link": "https://x/f",
                "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        cands, stats = ideas_layer._wide_scan(pool, cand_by_id, self._matcher(), Ledger([]), self.IDEAS,
                                              fx.TODAY, [])
        self.assertEqual(stats["skipped_by_reason"]["near_dup_briefing"], 1)
        self.assertEqual(cands, [])

    def test_clean_item_passes_every_gate(self):
        pool = [{"title": "TSMC expands CoWoS packaging capacity at new site", "summary": "",
                "link": "https://x/g", "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [])
        self.assertEqual(len(cands), 1)
        self.assertEqual(stats["matched_items"], 1)
        self.assertEqual(sum(stats["skipped_by_reason"].values()), 0)

    # ── curated_cards（2026-09-23 新增，Task 4）：既有新聞卡（tech_trends／frontier_tech…），
    # 不是 RSS 池，evidence_layer.run_evidence_layer 已經排除掉變成候選的卡才傳進來 ──────
    def test_curated_card_is_included_and_matched(self):
        curated = [{"headline": "TSMC expands CoWoS packaging capacity for next-gen substrates",
                   "summary": "", "source": "TrendForce", "source_date": fx.TODAY}]
        cands, stats = ideas_layer._wide_scan([], {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [],
                                              curated_cards=curated)
        self.assertEqual(stats["curated_pool_size"], 1)
        self.assertEqual(stats["pool_size"], 1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["headline"], curated[0]["headline"])

    def test_curated_card_reuses_stale_event_gate(self):
        from datetime import datetime, timedelta
        old_date = (datetime.strptime(fx.TODAY, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
        curated = [{"headline": "TSMC expands CoWoS capacity lines further at a new site",
                   "body": "", "source": "TrendForce", "source_date": old_date}]
        cands, stats = ideas_layer._wide_scan([], {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [],
                                              curated_cards=curated)
        self.assertEqual(stats["matched_items"], 1)
        self.assertEqual(stats["skipped_by_reason"]["stale_event"], 1)
        self.assertEqual(cands, [])

    def test_curated_cards_default_to_empty_and_do_not_change_existing_behaviour(self):
        pool = [{"title": "TSMC expands CoWoS packaging capacity at new site", "summary": "",
                "link": "https://x/g", "published": f"{fx.TODAY} 09:00", "source": "Reuters"}]
        cands, stats = ideas_layer._wide_scan(pool, {}, self._matcher(), Ledger([]), self.IDEAS, fx.TODAY, [])
        self.assertEqual(stats["curated_pool_size"], 0)
        self.assertEqual(stats["pool_size"], 1)
        self.assertEqual(len(cands), 1)

    def test_curated_card_as_pool_item_shape(self):
        card = {"headline": "  A headline  ", "summary": "Some summary", "source": "TrendForce",
               "source_date": "2026-09-20"}
        pool_item = ideas_layer._curated_card_as_pool_item(card)
        self.assertEqual(pool_item, {"title": "A headline", "summary": "Some summary", "link": "",
                                     "source": "TrendForce", "published": "2026-09-20"})
        # body 欄位（frontier_tech 用 body 不是 summary）也要被接住
        card2 = {"headline": "H", "body": "B text"}
        self.assertEqual(ideas_layer._curated_card_as_pool_item(card2)["summary"], "B text")


class HitsFileTests(unittest.TestCase):
    """idea_hits.json 的合併：冪等、同日去重、history 抓不到時的兩種情況、365 天保留。"""

    def test_merge_replaces_todays_rows_idempotently(self):
        def hits_fetch(url):
            return {"hits": [
                {"date": "2026-09-21", "idea": "x", "checkpoint": "cp1", "verdict": "supports",
                 "confidence": 0.8, "evidence_id": "e1"},
                {"date": "2026-09-22", "idea": "x", "checkpoint": "cp1", "verdict": "refutes",
                 "confidence": 0.5, "evidence_id": "e-old"},
            ]}, "ok"
        today_rows = [{"date": "2026-09-22", "idea": "x", "checkpoint": "cp1", "verdict": "supports",
                       "confidence": 0.9, "evidence_id": "e-new"}]
        merged = ideas_layer._merge_hits(hits_fetch, "2026-09-22", today_rows)
        self.assertEqual(merged["history"], "ok")
        dates = [r["date"] for r in merged["hits"]]
        self.assertEqual(dates.count("2026-09-22"), 1)
        self.assertIn("2026-09-21", dates)
        self.assertEqual([r for r in merged["hits"] if r["date"] == "2026-09-22"][0]["evidence_id"], "e-new")

    def test_dedup_within_same_day_by_fact_key_idea_checkpoint(self):
        rows = [
            {"date": "2026-09-22", "idea": "x", "checkpoint": "cp1", "verdict": "supports",
             "confidence": 0.9, "evidence_id": "e1", "fact_key": "fk1"},
            {"date": "2026-09-22", "idea": "x", "checkpoint": "cp1", "verdict": "refutes",
             "confidence": 0.4, "evidence_id": "e1", "fact_key": "fk1"},
        ]
        merged = ideas_layer._merge_hits(lambda url: (None, "missing"), "2026-09-22", rows)
        self.assertEqual(len(merged["hits"]), 1)
        self.assertEqual(merged["hits"][0]["verdict"], "supports")

    def test_missing_file_404_starts_empty_history_ok(self):
        merged = ideas_layer._merge_hits(lambda url: (None, "missing"), "2026-09-22", [])
        self.assertEqual(merged["history"], "ok")
        self.assertEqual(merged["hits"], [])

    def test_fetch_error_marks_history_unavailable_and_does_not_fabricate_old_rows(self):
        today_rows = [{"date": "2026-09-22", "idea": "x", "checkpoint": "cp1", "verdict": "supports",
                       "confidence": 0.9, "evidence_id": "e1"}]
        merged = ideas_layer._merge_hits(lambda url: (None, "error:ConnectionError"), "2026-09-22", today_rows)
        self.assertEqual(merged["history"], "unavailable")
        self.assertEqual(len(merged["hits"]), 1)

    def test_prunes_rows_older_than_365_days(self):
        def hits_fetch(url):
            return {"hits": [{"date": "2025-01-01", "idea": "x", "checkpoint": "cp1", "verdict": "supports",
                              "confidence": 0.9, "evidence_id": "old"}]}, "ok"
        merged = ideas_layer._merge_hits(hits_fetch, "2026-09-22", [])
        self.assertEqual(merged["hits"], [])

    def test_unrelated_verdicts_are_dropped_from_hits_file(self):
        jev, _ = fx.fake_client({"TSMC rallies": {"idea_verdict": ["unrelated", 0.9]}})
        ev, _ = run(jev=jev)
        it = item(ev, "Kaohsiung packaging park")
        self.assertTrue(any(h["verdict"] == "unrelated" for h in it["ideas"]))  # 留在當天 JSON 供校準
        hit_ids = {(r["evidence_id"], r["checkpoint"]) for r in ev["idea_hits"]["hits"]}
        for h in it["ideas"]:
            if h["verdict"] == "unrelated":
                self.assertNotIn((it["id"], h["checkpoint"]), hit_ids)   # 但不進累加檔


class RenderingTests(unittest.TestCase):
    def test_unavailable_status_renders_muted_line(self):
        page = html_template._ideas_section({"ideas": {"status": "unavailable"}})
        self.assertIn("今天動到的想法", page)
        self.assertIn("想法清單沒讀到", page)

    def test_no_hits_today_renders_muted_line_with_link(self):
        ev = {"date": "2026-09-22", "ideas": {"status": "ok", "catalog": {}}, "idea_hits": {"hits": []}}
        page = html_template._ideas_section(ev)
        self.assertIn("今天沒有新證據動到任何想法", page)
        self.assertIn("https://research.investmquest.com/ideas/", page)

    def test_hits_today_grouped_by_idea_with_badges_and_links(self):
        ev = {
            "date": "2026-09-22",
            "ideas": {"status": "ok", "catalog": {
                "ai-scissors": {"short": "AI 剪刀差", "url": "/ideas/ai-scissors.html",
                                "checkpoints": {"cp1": "先進封裝產能"}}}},
            "idea_hits": {"hits": [
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "supports",
                 "confidence": 0.85, "headline": "TSMC packaging ramps", "url": "https://example.com/a"},
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "refutes",
                 "confidence": 0.7, "headline": "TSMC packaging slows", "url": "https://example.com/b"},
                {"date": "2026-09-21", "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "supports",
                 "confidence": 0.9, "headline": "yesterday, should not show", "url": "https://example.com/c"},
            ]},
        }
        page = html_template._ideas_section(ev)
        self.assertIn("AI 剪刀差", page)
        self.assertIn("https://research.investmquest.com/ideas/ai-scissors.html", page)
        self.assertIn("（2 則）", page)
        self.assertIn("支持", page)
        self.assertIn("推翻", page)
        self.assertIn("先進封裝產能", page)
        self.assertIn("TSMC packaging ramps", page)
        self.assertNotIn("yesterday, should not show", page)

    def test_email_summary_line_present_when_hits(self):
        ev = {
            "date": "2026-09-22",
            "ideas": {"status": "ok", "catalog": {"ai-scissors": {"short": "AI 剪刀差"}}},
            "idea_hits": {"hits": [
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "supports"},
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp2", "verdict": "refutes"},
            ]},
        }
        self.assertIn("想法：AI 剪刀差 2 則（支持 1、推翻 1）", html_template._ideas_email_summary(ev))

    def test_email_summary_empty_when_no_hits(self):
        ev = {"date": "2026-09-22", "ideas": {"status": "ok", "catalog": {}}, "idea_hits": {"hits": []}}
        self.assertEqual(html_template._ideas_email_summary(ev), "")

    def test_email_summary_empty_when_unavailable(self):
        self.assertEqual(html_template._ideas_email_summary({"ideas": {"status": "unavailable"}}), "")

    def test_news_page_places_ideas_section_above_evidence_section(self):
        ev, _ = run()
        data = fx.briefing_data()
        data["evidence_layer"] = ev
        data["date"] = "test"
        news = html_template.build_news_html(data)
        a = news.find("今天動到的想法")
        b = news.find('id="evidence"')
        self.assertTrue(0 <= a < b)

    def test_wide_origin_hit_shows_muted_tag_and_basis(self):
        ev = {
            "date": "2026-09-22",
            "ideas": {"status": "ok", "catalog": {
                "ai-scissors": {"short": "AI 剪刀差", "url": "/ideas/ai-scissors.html",
                                "checkpoints": {"cp3": "記憶體合約價"}, "due": []}}},
            "idea_hits": {"hits": [
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp3", "verdict": "supports",
                 "confidence": 0.8, "headline": "HBM contract prices rise again",
                 "url": "https://example.com/hbm", "origin": "wide"},
            ]},
        }
        page = html_template._ideas_section(ev)
        self.assertIn("早報外", page)
        self.assertIn("只讀到標題與摘要", page)
        self.assertIn("HBM contract prices rise again", page)

    def test_briefing_origin_hit_has_no_wide_tag(self):
        ev = {
            "date": "2026-09-22",
            "ideas": {"status": "ok", "catalog": {
                "ai-scissors": {"short": "AI 剪刀差", "url": "/ideas/ai-scissors.html",
                                "checkpoints": {"cp3": "記憶體合約價"}, "due": []}}},
            "idea_hits": {"hits": [
                {"date": "2026-09-22", "idea": "ai-scissors", "checkpoint": "cp3", "verdict": "supports",
                 "confidence": 0.8, "headline": "Micron raises DRAM prices",
                 "url": "https://example.com/dram", "origin": "briefing"},
            ]},
        }
        page = html_template._ideas_section(ev)
        self.assertNotIn("早報外", page)
        self.assertNotIn("只讀到標題與摘要", page)


class IdeaResearchRenderingTests(unittest.TestCase):
    """深入查核（research.json，另一個雲端 routine idea-watch-auto，2026-09-23 晚新增，Task C）
    在 news 頁與 email 摘要的渲染：正常渲染／run.date 不是今天（stale）／完全讀不到（missing）
    三種情境都要顧到，任一種都不能讓其餘內容跟著壞掉。"""

    CATALOG = {"ai-scissors": {"short": "AI 剪刀差", "url": "/ideas/ai-scissors.html",
                               "checkpoints": {"cp1": "AI 營收成長跑贏降價", "cp2": "GPU 雲租金"}}}
    TODAY = "2026-09-24"

    def _ev(self, idea_research=None, hits=None):
        return {"date": self.TODAY, "ideas": {"status": "ok", "catalog": self.CATALOG},
               "idea_hits": {"hits": hits or []}, "idea_research": idea_research}

    def test_renders_entries_and_changes_for_today(self):
        research = {"status": "ok", "data": {
            "run": {"date": self.TODAY, "status": "ok"},
            "entries": [
                {"date": self.TODAY, "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "supports",
                 "summary": "OpenRouter 用量續創高", "kind": "search"},
                {"date": "2026-09-23", "idea": "ai-scissors", "checkpoint": "cp1", "verdict": "supports",
                 "summary": "昨天的紀錄，不該當今天的", "kind": "search"},
            ],
            "changes": [
                {"date": self.TODAY, "idea": "ai-scissors", "checkpoint": "cp2", "keystone": True,
                 "from": "supports", "to": "refutes", "reason": "CoreWeave 新約降價 6%"},
            ],
        }}
        page = html_template._ideas_section(self._ev(idea_research=research))
        self.assertIn("深入查核", page)
        self.assertIn("OpenRouter 用量續創高", page)
        self.assertIn("主動搜尋", page)
        self.assertNotIn("昨天的紀錄，不該當今天的", page)
        self.assertIn("★", page)
        self.assertIn("查核點 2", page)
        self.assertIn("支持 → 推翻", page)
        self.assertIn("CoreWeave 新約降價 6%", page)

    def test_keystone_refutes_rendered_in_red(self):
        research = {"status": "ok", "data": {
            "run": {"date": self.TODAY, "status": "ok"}, "entries": [],
            "changes": [{"date": self.TODAY, "idea": "ai-scissors", "checkpoint": "cp2", "keystone": True,
                        "from": "supports", "to": "refutes", "reason": "x"}],
        }}
        page = html_template._ideas_section(self._ev(idea_research=research))
        self.assertIn("color:#A32D2D", page)

    def test_stale_run_shows_muted_line_and_no_entries(self):
        research = {"status": "ok", "data": {
            "run": {"date": "2026-09-23", "status": "ok"},
            "entries": [{"date": "2026-09-23", "idea": "ai-scissors", "checkpoint": "cp1",
                        "verdict": "supports", "summary": "不該出現：run 不是今天", "kind": "search"}],
            "changes": [],
        }}
        page = html_template._ideas_section(self._ev(idea_research=research))
        self.assertIn("今天的深入查核尚未完成，顯示 2026-09-23 的狀態", page)
        self.assertNotIn("不該出現：run 不是今天", page)

    def test_missing_research_does_not_break_page(self):
        page = html_template._ideas_section(self._ev(idea_research=None))
        self.assertIn("今天動到的想法", page)
        self.assertIn("今天沒有新證據動到任何想法", page)
        self.assertNotIn("深入查核", page)

    def test_missing_research_status_unavailable_does_not_break_page(self):
        page = html_template._ideas_section(self._ev(idea_research={"status": "unavailable", "data": None}))
        self.assertIn("今天動到的想法", page)
        self.assertNotIn("深入查核", page)

    def test_entries_group_shown_even_without_briefing_hits_today(self):
        research = {"status": "ok", "data": {
            "run": {"date": self.TODAY, "status": "ok"},
            "entries": [{"date": self.TODAY, "idea": "ai-scissors", "checkpoint": "cp1",
                        "verdict": "shaky", "summary": "只有深入查核，沒有早報命中", "kind": "earnings"}],
            "changes": [],
        }}
        page = html_template._ideas_section(self._ev(idea_research=research))
        self.assertNotIn("今天沒有新證據動到任何想法", page)
        self.assertIn("只有深入查核，沒有早報命中", page)
        self.assertIn("財報", page)
        self.assertIn("動搖", page)

    def test_email_line_only_when_changes_today(self):
        research = {"status": "ok", "data": {
            "run": {"date": self.TODAY, "status": "ok"}, "entries": [],
            "changes": [{"date": self.TODAY, "idea": "ai-scissors", "checkpoint": "cp2", "keystone": True,
                        "from": "supports", "to": "shaky", "reason": "x"}],
        }}
        line = html_template._ideas_email_summary(self._ev(idea_research=research))
        self.assertIn("查核點狀態變化：AI 剪刀差 1 項（查核點 2 支持→動搖）", line)

    def test_email_line_empty_when_no_changes_today(self):
        research = {"status": "ok", "data": {"run": {"date": self.TODAY, "status": "ok"},
                                             "entries": [], "changes": []}}
        self.assertEqual(html_template._ideas_email_summary(self._ev(idea_research=research)), "")

    def test_email_line_empty_when_research_missing(self):
        self.assertEqual(html_template._ideas_email_summary(self._ev(idea_research=None)), "")


class DueSoonTests(unittest.TestCase):
    """未來 7 天到期的查核點（Task 3，2026-09-23 晚新增）：程式只認 ideas.json 的 due 欄位，
    沒有這個欄位（舊查核點、或使用者還沒補）要照常運作，不噴錯。"""

    CATALOG = {
        "ai-scissors": {"short": "AI 剪刀差", "url": "/ideas/ai-scissors.html",
                        "checkpoints": {"cp2": "GPU 雲租金"},
                        "due": [
                            {"date": "2026-09-24", "label": "Nebius 新價生效", "approx": False,
                             "checkpoint": "cp2", "checkpoint_label": "GPU 雲租金"},
                            {"date": "2026-10-15", "label": "太遠了不該出現", "approx": True,
                             "checkpoint": "cp2", "checkpoint_label": "GPU 雲租金"},
                            {"date": "2026-09-20", "label": "已經過期不該出現", "approx": False,
                             "checkpoint": "cp2", "checkpoint_label": "GPU 雲租金"},
                        ]},
        "no-due-field": {"short": "沒有 due 欄位", "url": "/ideas/x.html", "checkpoints": {}},
    }
    TODAY = "2026-09-22"

    def test_filters_to_next_seven_days_inclusive_of_today(self):
        due = html_template._due_soon(self.CATALOG, self.TODAY)
        self.assertEqual([d["label"] for d in due], ["Nebius 新價生效"])

    def test_missing_due_field_does_not_error(self):
        due = html_template._due_soon({"no-due-field": self.CATALOG["no-due-field"]}, self.TODAY)
        self.assertEqual(due, [])

    def test_news_page_shows_due_group_with_approx_prefix_and_anchor_link(self):
        ev = {"date": self.TODAY, "ideas": {"status": "ok", "catalog": self.CATALOG},
             "idea_hits": {"hits": []}}
        page = html_template._ideas_section(ev)
        self.assertIn("未來 7 天到期的查核點", page)
        self.assertIn("Nebius 新價生效", page)
        self.assertIn("/ideas/ai-scissors.html#cp2", page)
        self.assertNotIn("太遠了不該出現", page)
        self.assertNotIn("已經過期不該出現", page)

    def test_due_group_hidden_when_nothing_due(self):
        ev = {"date": "2026-01-01", "ideas": {"status": "ok", "catalog": self.CATALOG},
             "idea_hits": {"hits": []}}
        page = html_template._ideas_section(ev)
        self.assertNotIn("未來 7 天到期的查核點", page)

    def test_email_summary_line_only_when_due_within_two_days(self):
        ev_due = {"date": self.TODAY, "ideas": {"status": "ok", "catalog": self.CATALOG},
                  "idea_hits": {"hits": []}}
        line = html_template._ideas_email_summary(ev_due)
        self.assertIn("查核點即將到期", line)
        self.assertIn("Nebius 新價生效", line)

        far_catalog = {"ai-scissors": {"short": "AI 剪刀差", "url": "/x", "checkpoints": {},
                                       "due": [{"date": "2026-10-15", "label": "太遠", "approx": True,
                                               "checkpoint": "cp2", "checkpoint_label": "x"}]}}
        ev_far = {"date": self.TODAY, "ideas": {"status": "ok", "catalog": far_catalog},
                 "idea_hits": {"hits": []}}
        self.assertEqual(html_template._ideas_email_summary(ev_far), "")


if __name__ == "__main__":
    unittest.main()


def test_company_names_count_as_party():
    ideas = [{"id": "x", "status": "active", "checkpoints": [
        {"id": "cp", "companies": ["NBIS"], "company_names": ["nebius"], "keywords": ["gpu prices"], "themes": []}]}]
    out = ideas_layer.match_checkpoints("Nebius raises GPU prices again", [], [], ideas)
    assert [cp["id"] for _, cp, _ in out] == ["cp"]


def test_plural_pair_is_one_keyword():
    ideas = [{"id": "x", "status": "active", "checkpoints": [
        {"id": "cp", "companies": [], "keywords": ["bond", "bonds"], "themes": []}]}]
    assert ideas_layer.match_checkpoints("Treasury bond yields jump as bonds sell off", [], [], ideas) == []
