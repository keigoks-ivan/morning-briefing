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


_TSMC_TEXT = ("TSMC rallies equipment and material suppliers into Kaohsiung packaging park. Taiwan broke ground "
             "on the Baipu advanced packaging industrial park in Kaohsiung, anchored by TSMC facilities "
             "including a technology validation lab and CoWoS tool validation mini-loop. TrendForce reports "
             "TSMC is also reportedly eyeing an AUO site for CoPoS capacity.")


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

    def test_cap_of_eight_pairs_per_day_rest_stay_unjudged(self):
        checkpoints = [{"id": f"cp{i}", "label": f"test{i}", "companies": [], "keywords": ["cowos", "capacity"],
                        "themes": [], "supports_if": "s", "refutes_if": "r"} for i in range(12)]
        ideas = [{"id": "many-checkpoints", "short": "多查核點", "url": "/x", "status": "active",
                 "checkpoints": checkpoints}]
        ev, _ = run(ideas=ideas)
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(len(it["ideas"]), 12)
        judged = [h for h in it["ideas"] if h["confidence"] is not None]
        unjudged = [h for h in it["ideas"] if h["verdict"] == "unjudged"]
        self.assertEqual(len(judged), ideas_layer.MAX_IDEA_PAIRS)
        self.assertEqual(len(unjudged), 12 - ideas_layer.MAX_IDEA_PAIRS)
        self.assertEqual(ev["ideas"]["matched_pairs"], 12)
        self.assertEqual(ev["ideas"]["asked"], ideas_layer.MAX_IDEA_PAIRS)

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

        idea_reqs = [r for r in captured if "verdict" in r.get("questions", {})]
        self.assertTrue(idea_reqs)
        self.assertTrue(any(marker in json.dumps(r["state"]) for r in idea_reqs))
        self.assertNotIn(marker, json.dumps(ev, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as td:
            written = evidence_layer.save_outputs(ev, ledger, Path(td), fx.TODAY)
            self.assertIn("idea_hits.json", written)
            for fn in written:
                self.assertNotIn(marker, (Path(td) / fn).read_text(encoding="utf-8"))


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


if __name__ == "__main__":
    unittest.main()
