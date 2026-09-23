"""gdelt_source.py 離線測試（2026-09-23 新增）。不呼叫真正的 GDELT API：http_get／sleep／now
全部用假的。驗收：查詢組裝（優先序、字元上限、請求上限）、限流偵測與重試一次、過濾規則
（要點到研究公司、且有數字或主題／環節辨識詞；黑名單網域丟掉；跟既有標題近似的丟掉）、
排序（DD／持倉公司優先 → 有數字優先 → 新的優先）、候選形狀（block="gdelt" 等）。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_fixtures as fx  # noqa: E402

import gdelt_source as gd  # noqa: E402
from evidence_ledger import EntityMatcher  # noqa: E402
from evidence_routing import dd_index, load_routing, public_holdings_view  # noqa: E402

ROUTING = load_routing()
DD = dd_index(fx.watchlist())
HOLDINGS = public_holdings_view(fx.holdings())
MATCHER = EntityMatcher(ROUTING, {t: v.get("name", "") for t, v in DD.items()})


def _clock(step: float = 0.01):
    state = {"t": 0.0}

    def now():
        state["t"] += step
        return state["t"]
    return now


class QueryBuildingTests(unittest.TestCase):
    def test_distinctive_filter_drops_short_or_cjk_or_generic_names(self):
        self.assertFalse(gd._distinctive_name("AI"))
        self.assertFalse(gd._distinctive_name("WPP"))
        self.assertFalse(gd._distinctive_name("世芯"))
        self.assertFalse(gd._distinctive_name(""))
        self.assertTrue(gd._distinctive_name("Hanmi Semiconductor"))
        self.assertTrue(gd._distinctive_name("SK hynix"))

    def test_company_universe_prioritises_dd_and_holdings_over_theme_members(self):
        names = gd.company_universe(ROUTING, DD, HOLDINGS, MATCHER)
        self.assertTrue(names)
        tsmc_idx = next(i for i, n in enumerate(names) if "TSM" in n or "Taiwan Semiconductor" in n)
        self.assertLess(tsmc_idx, 5)   # TSM 在 fixture DD universe 裡，要排很前面

    def test_queries_respect_char_and_request_budget(self):
        queries = gd.build_queries(ROUTING, DD, HOLDINGS, MATCHER, max_requests=5, max_query_chars=200)
        self.assertLessEqual(len(queries), 5)
        for q in queries:
            self.assertLessEqual(len(q), 200)
            self.assertIn("sourcelang:english", q)
            self.assertTrue(q.startswith("("))

    def test_no_query_when_no_distinctive_names(self):
        empty_matcher = EntityMatcher({"companies": {}}, {})
        queries = gd.build_queries({"companies": {}, "auto_companies": {}, "themes": {}}, {}, {}, empty_matcher)
        self.assertEqual(queries, [])


class FetchRawArticlesTests(unittest.TestCase):
    def test_rate_limit_is_detected_and_retried_once(self):
        rate_limit_body = ("Please limit requests to one every 5 seconds or contact "
                           "kalev.leetaru5@gmail.com for larger queries.")
        ok_body = json.dumps({"articles": [{"title": "TSMC revenue jumps 34% on AI chip demand",
                                            "url": "https://example.com/a", "domain": "example.com",
                                            "seendate": "20260923T010000Z"}]})
        responses = [(rate_limit_body, 429), (ok_body, 200)]
        calls = []

        def http_get(url, timeout=20):
            calls.append(url)
            return responses[len(calls) - 1]

        waits = []
        articles, quality = gd.fetch_raw_articles(
            ['("TSMC") sourcelang:english'], http_get=http_get, sleep=waits.append, now=_clock())
        self.assertEqual(len(calls), 2)
        self.assertEqual(quality["requests_sent"], 2)
        self.assertEqual(quality["rate_limited"], 1)
        self.assertEqual(quality["ok"], 1)
        self.assertEqual(len(articles), 1)
        self.assertIn(gd.RATE_LIMIT_SECONDS, waits)

    def test_gives_up_after_one_retry_still_rate_limited(self):
        rate_limit_body = "Please limit requests to one every 5 seconds."

        def http_get(url, timeout=20):
            return (rate_limit_body, 429)

        articles, quality = gd.fetch_raw_articles(
            ['("TSMC") sourcelang:english'], http_get=http_get, sleep=lambda s: None, now=_clock())
        self.assertEqual(articles, [])
        self.assertEqual(quality["requests_sent"], 2)
        self.assertEqual(quality["rate_limited"], 1)
        self.assertEqual(quality["http_errors"], 1)
        self.assertEqual(quality["ok"], 0)

    def test_stops_after_three_blocked_queries_in_a_row(self):
        # 2026-09-23：IP 被封時不要把 20 個查詢都試完
        def http_get(url, timeout=20):
            return ("Please limit requests to one every 5 seconds.", 429)

        queries = [f'("Co{i}") sourcelang:english' for i in range(10)]
        articles, quality = gd.fetch_raw_articles(queries, http_get=http_get, sleep=lambda s: None, now=_clock())
        self.assertEqual(articles, [])
        self.assertEqual(quality["requests_sent"], 6)   # 3 個查詢 × （原請求＋重試一次）
        self.assertEqual(quality["stopped_reason"], "rate_limited_3_in_a_row")

    def test_network_failure_is_recorded_not_raised(self):
        def http_get(url, timeout=20):
            return ("", None)

        articles, quality = gd.fetch_raw_articles(
            ['("TSMC") sourcelang:english'], http_get=http_get, sleep=lambda s: None, now=_clock())
        self.assertEqual(articles, [])
        self.assertEqual(quality["network_errors"], 1)

    def test_stops_when_wall_time_budget_exceeded(self):
        calls = []

        def http_get(url, timeout=20):
            calls.append(url)
            return (json.dumps({"articles": []}), 200)

        times = iter([0.0, 200.0, 200.0, 200.0])
        articles, quality = gd.fetch_raw_articles(
            ['("A") sourcelang:english', '("B") sourcelang:english', '("C") sourcelang:english'],
            http_get=http_get, sleep=lambda s: None, now=lambda: next(times), wall_time_budget=150.0)
        self.assertEqual(calls, [])
        self.assertEqual(quality.get("stopped_reason"), "wall_time_budget")


class FilterAndRankTests(unittest.TestCase):
    def test_requires_company_match_and_figure_or_theme_keyword(self):
        arts = [
            {"title": "Random world news with no research company named", "url": "https://reuters.com/a",
             "domain": "reuters.com", "seendate": "20260923T010000Z"},
            {"title": "TSMC executives visit a supplier's headquarters", "url": "https://example.com/b",
             "domain": "example.com", "seendate": "20260923T010000Z"},
            {"title": "TSMC posts 34% revenue growth in August", "url": "https://example.com/c",
             "domain": "example.com", "seendate": "20260923T020000Z"},
        ]
        kept = gd.filter_and_rank(arts, MATCHER, ROUTING, [], DD, HOLDINGS, max_kept=10)
        titles = {k["title"] for k in kept}
        self.assertNotIn(arts[0]["title"], titles)
        self.assertNotIn(arts[1]["title"], titles)
        self.assertIn(arts[2]["title"], titles)

    def test_blacklisted_domain_is_dropped(self):
        arts = [{"title": "TSMC revenue jumps 20% on AI chip demand", "url": "https://twitter.com/x",
                "domain": "twitter.com", "seendate": "20260923T010000Z"}]
        self.assertEqual(gd.filter_and_rank(arts, MATCHER, ROUTING, [], DD, HOLDINGS), [])

    def test_drops_near_duplicate_of_existing_briefing_title(self):
        title = "TSMC revenue jumps 20% on AI chip demand"
        arts = [{"title": title, "url": "https://example.com/x", "domain": "example.com",
                "seendate": "20260923T010000Z"}]
        self.assertEqual(gd.filter_and_rank(arts, MATCHER, ROUTING, [title], DD, HOLDINGS), [])

    def test_drops_near_duplicate_within_gdelt_results_and_dedups_url(self):
        arts = [
            {"title": "TSMC revenue jumps 20% on AI chip demand", "url": "https://example.com/1",
             "domain": "example.com", "seendate": "20260923T010000Z"},
            {"title": "TSMC revenue jumps 20 pct on AI chip demand", "url": "https://example.com/2",
             "domain": "example.com", "seendate": "20260923T020000Z"},
        ]
        kept = gd.filter_and_rank(arts, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(len(kept), 1)

    def test_orders_priority_company_first_then_figure_then_recency(self):
        # SK hynix（000660.KS）不在 fixture 的 DD／持倉清單；TSM 在。
        arts = [
            {"title": "SK hynix reports 12% increase in memory chip shipments", "url": "https://example.com/1",
             "domain": "example.com", "seendate": "20260923T060000Z"},
            {"title": "TSMC announces roadmap update with no figures mentioned here today", "url": "https://example.com/2",
             "domain": "example.com", "seendate": "20260923T010000Z"},
            {"title": "TSMC revenue jumps 34% on AI chip demand", "url": "https://example.com/3",
             "domain": "example.com", "seendate": "20260923T030000Z"},
        ]
        kept = gd.filter_and_rank(arts, MATCHER, ROUTING, [], DD, HOLDINGS, max_kept=10)
        titles = [k["title"] for k in kept]
        # TSM 有數字的那則（DD 公司 + 有數字）要排第一
        self.assertEqual(titles[0], "TSMC revenue jumps 34% on AI chip demand")
        self.assertTrue(kept[0]["priority"])
        self.assertTrue(kept[0]["has_figure"])

    def test_max_kept_caps_results(self):
        titles = [
            "TSMC posts 12% revenue growth this quarter",
            "SK hynix raises HBM output by 18% this year",
            "Samsung Electronics chip division profit up 25%",
            "Micron Technology ships 9% more DRAM units",
            "Broadcom custom silicon backlog grows 40%",
        ]
        arts = [{"title": t, "url": f"https://example.com/{i}", "domain": "example.com",
                "seendate": "20260923T010000Z"} for i, t in enumerate(titles)]
        kept = gd.filter_and_rank(arts, MATCHER, ROUTING, [], DD, HOLDINGS, max_kept=2)
        self.assertEqual(len(kept), 2)


class MakeCandidateTests(unittest.TestCase):
    def test_candidate_shape_matches_block_source_and_rss(self):
        art = {"title": "TSMC revenue jumps 34% on AI chip demand", "url": "https://example.com/a",
               "domain": "example.com", "companies": ["TSM"], "figures": ["pct:34"],
               "seendate": "20260923T013000Z"}
        cand = gd.make_candidate(art, MATCHER, "2026-09-23")
        self.assertEqual(cand["block"], "gdelt")
        self.assertEqual(cand["source"], "example.com")
        self.assertEqual(cand["source_date"], "2026-09-23")
        self.assertEqual(cand["rss"], [{"source": "example.com", "title": art["title"], "summary": "",
                                        "url": "https://example.com/a", "published": "2026-09-23T01:30:00Z",
                                        "also_in": []}])
        self.assertEqual(cand["companies"], ["TSM"])
        self.assertIn("TSM", cand["companies"])

    def test_seendate_parses_to_iso_and_blank_on_bad_input(self):
        self.assertEqual(gd._seendate_to_iso("20260923T013000Z"), "2026-09-23T01:30:00Z")
        self.assertEqual(gd._seendate_to_iso(""), "")
        self.assertEqual(gd._seendate_to_iso("garbage"), "")


class FetchGdeltCandidatesTests(unittest.TestCase):
    def test_end_to_end_with_fake_transport_returns_candidates_and_quality(self):
        ok_body = json.dumps({"articles": [
            {"title": "TSMC revenue jumps 34% on AI chip demand", "url": "https://example.com/a",
             "domain": "example.com", "seendate": "20260923T013000Z"},
        ]})

        def http_get(url, timeout=20):
            return (ok_body, 200)

        cands, quality = gd.fetch_gdelt_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-23", max_kept=8, max_requests=3,
            http_get=http_get, sleep=lambda s: None, now=_clock())
        self.assertTrue(quality["enabled"])
        self.assertGreaterEqual(quality["requests_sent"], 1)
        self.assertEqual(quality["kept"], 1)
        self.assertEqual(quality["kept_titles"], ["TSMC revenue jumps 34% on AI chip demand"])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["block"], "gdelt")

    def test_zero_slots_short_circuits_without_a_request(self):
        calls = []

        def http_get(url, timeout=20):
            calls.append(url)
            return ("{}", 200)

        cands, quality = gd.fetch_gdelt_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-23", max_kept=0,
            http_get=http_get, sleep=lambda s: None, now=_clock())
        self.assertEqual(cands, [])
        self.assertFalse(quality["enabled"])
        self.assertEqual(calls, [])

    def test_exception_is_caught_and_reported_not_raised(self):
        def boom(*a, **k):
            raise RuntimeError("boom")

        cands, quality = gd.fetch_gdelt_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-23", max_kept=8, http_get=boom,
            sleep=lambda s: None, now=_clock())
        self.assertEqual(cands, [])
        self.assertFalse(quality["enabled"])
        self.assertIn("error", quality)


if __name__ == "__main__":
    unittest.main()
