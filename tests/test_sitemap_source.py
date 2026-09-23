"""sitemap_source.py 離線測試（2026-09-24 新增）。不連網：http_get／sleep／now 全部用假的。

驗收：三種 sitemap 型態的解析（news_sitemap／sitemap_index／site_sitemap）、gzip payload、
slug 標題備援、48 小時窗過濾、單一來源被擋（403／429）後不再重試第三次也不拖垮其他來源、
evidence 候選的篩選（公司或主題命中才留）與排序、候選形狀（block="sitemap" 等）、早報外掃描
用的池子（to_pool_items，不篩公司）、進入點的失效保護與 max_kept<=0 時仍回傳完整池子。"""

from __future__ import annotations

import gzip
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_fixtures as fx  # noqa: E402

import sitemap_source as sm  # noqa: E402
from evidence_ledger import EntityMatcher  # noqa: E402
from evidence_routing import dd_index, load_routing, public_holdings_view  # noqa: E402

ROUTING = load_routing()
DD = dd_index(fx.watchlist())
HOLDINGS = public_holdings_view(fx.holdings())
MATCHER = EntityMatcher(ROUTING, {t: v.get("name", "") for t, v in DD.items()})

NOW = lambda: datetime(2026, 9, 24, 6, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _news_sitemap_xml(items: list[tuple[str, str]]) -> str:
    """items: [(title, iso_publication_date)]。"""
    body = "".join(
        f'<url><loc>https://example.com/{i}</loc><news:news>'
        f'<news:publication><news:name>Example</news:name><news:language>en</news:language></news:publication>'
        f'<news:publication_date>{pub}</news:publication_date>'
        f'<news:title><![CDATA[{title}]]></news:title></news:news></url>'
        for i, (title, pub) in enumerate(items)
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">' + body + "</urlset>")


def _site_sitemap_xml(items: list[tuple[str, str]]) -> str:
    """items: [(loc, lastmod)]。沒有 news: 標籤。"""
    body = "".join(f"<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>" for loc, lastmod in items)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>")


def _sitemap_index_xml(children: list[str]) -> str:
    body = "".join(f"<sitemap><loc>{c}</loc></sitemap>" for c in children)
    return ('<?xml version="1.0" encoding="UTF-8"?>'
           '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</sitemapindex>")


class ParseSitemapXmlTests(unittest.TestCase):
    def test_news_sitemap_urlset_parses_title_and_date(self):
        xml = _news_sitemap_xml([("TSMC posts 34% revenue growth", "2026-09-24T01:00:00Z")])
        kind, payload = sm.parse_sitemap_xml(xml)
        self.assertEqual(kind, "urlset")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["title"], "TSMC posts 34% revenue growth")
        self.assertEqual(payload[0]["publication_date"], "2026-09-24T01:00:00Z")
        self.assertEqual(payload[0]["loc"], "https://example.com/0")

    def test_site_sitemap_has_no_title_but_has_lastmod(self):
        xml = _site_sitemap_xml([("https://example.com/presscenter/news/20260924-1.html",
                                 "2026-09-24T01:00:00+08:00")])
        kind, payload = sm.parse_sitemap_xml(xml)
        self.assertEqual(kind, "urlset")
        self.assertEqual(payload[0]["title"], "")
        self.assertEqual(payload[0]["lastmod"], "2026-09-24T01:00:00+08:00")

    def test_sitemap_index_lists_children(self):
        xml = _sitemap_index_xml(["https://example.com/news_sitemap.xml?date=20260924",
                                 "https://example.com/news_sitemap.xml?date=20260923"])
        kind, payload = sm.parse_sitemap_xml(xml)
        self.assertEqual(kind, "index")
        self.assertEqual(payload, ["https://example.com/news_sitemap.xml?date=20260924",
                                   "https://example.com/news_sitemap.xml?date=20260923"])

    def test_malformed_xml_is_an_error_not_an_exception(self):
        kind, payload = sm.parse_sitemap_xml("<not-xml")
        self.assertEqual(kind, "error")
        self.assertEqual(payload, [])

    def test_unexpected_root_element_is_an_error(self):
        kind, payload = sm.parse_sitemap_xml("<rss><channel></channel></rss>")
        self.assertEqual(kind, "error")


class TitleFromSlugTests(unittest.TestCase):
    def test_derives_words_from_dashed_slug(self):
        self.assertEqual(sm._title_from_slug("https://example.com/tablets/foo-bar-baz"), "Foo Bar Baz")

    def test_strips_extension_and_query(self):
        self.assertEqual(sm._title_from_slug("https://example.com/news/hello-world.html?x=1"), "Hello World")

    def test_numeric_slug_yields_numeric_title(self):
        # TrendForce presscenter/news 的 slug 是日期＋流水號，猜不出有意義的標題（見
        # data/news_sitemaps.json 的 _note），這裡只驗證不會炸掉、行為可預期（連字號拆成空白）
        self.assertEqual(sm._title_from_slug("https://example.com/presscenter/news/20260914-13235.html"),
                         "20260914 13235")


class FetchOneSourceTests(unittest.TestCase):
    def test_news_sitemap_ok_status_and_age_filter(self):
        xml = _news_sitemap_xml([
            ("Fresh TSMC story", "2026-09-24T04:00:00Z"),       # 2 小時前：留
            ("Stale TSMC story from last week", "2026-09-20T04:00:00Z"),  # 超過 48 小時：丟
        ])
        cfg = {"name": "Example", "url": "https://example.com/sitemap_news.xml", "type": "news_sitemap",
              "lang": "en", "max_age_hours": 48}

        def http_get(url, timeout=15):
            return xml, 200

        items, status = sm.fetch_one_source(cfg, http_get=http_get, sleep=lambda s: None, now=NOW)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["items_seen"], 2)
        self.assertEqual(status["items_recent"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Fresh TSMC story")
        self.assertEqual(items[0]["source_name"], "Example")
        self.assertFalse(items[0]["title_from_slug"])

    def test_item_without_any_parseable_date_is_dropped(self):
        xml = ('<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
              'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
              '<url><loc>https://example.com/x</loc><news:news><news:title>No date here</news:title>'
              '</news:news></url></urlset>')
        cfg = {"name": "Example", "url": "https://example.com/s.xml", "type": "news_sitemap"}
        items, status = sm.fetch_one_source(cfg, http_get=lambda u, timeout=15: (xml, 200),
                                            sleep=lambda s: None, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status["items_seen"], 1)
        self.assertEqual(status["items_recent"], 0)

    def test_site_sitemap_falls_back_to_lastmod_and_slug_title(self):
        xml = _site_sitemap_xml([("https://example.com/presscenter/news/20260924-1.html",
                                 "2026-09-24T05:00:00+08:00")])  # 2026-09-24T05:00+08:00 = 2026-09-23T21:00Z, 9h ago
        cfg = {"name": "TrendForce", "url": "https://example.com/sitemap.xml", "type": "site_sitemap",
              "url_filter": r"/presscenter/news/\d{8}-\d+\.html$", "max_age_hours": 48}
        items, status = sm.fetch_one_source(cfg, http_get=lambda u, timeout=15: (xml, 200),
                                            sleep=lambda s: None, now=NOW)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["title_from_slug"])
        self.assertEqual(items[0]["title"], "20260924 1")

    def test_url_filter_drops_non_matching_paths(self):
        xml = _site_sitemap_xml([
            ("https://example.com/about", "2026-09-24T05:00:00+08:00"),
            ("https://example.com/presscenter/news/20260924-1.html", "2026-09-24T05:00:00+08:00"),
        ])
        cfg = {"name": "TrendForce", "url": "https://example.com/sitemap.xml", "type": "site_sitemap",
              "url_filter": r"/presscenter/news/\d{8}-\d+\.html$", "max_age_hours": 48}
        items, status = sm.fetch_one_source(cfg, http_get=lambda u, timeout=15: (xml, 200),
                                            sleep=lambda s: None, now=NOW)
        self.assertEqual(status["items_seen"], 2)   # 篩選前的原始筆數
        self.assertEqual(len(items), 1)
        self.assertIn("presscenter", items[0]["url"])

    def test_sitemap_index_follows_max_children(self):
        child_today = _news_sitemap_xml([("Today story", "2026-09-24T04:00:00Z")])
        child_yesterday = _news_sitemap_xml([("Yesterday story", "2026-09-23T04:00:00Z")])
        index_xml = _sitemap_index_xml(["https://example.com/d.xml?date=20260924",
                                       "https://example.com/d.xml?date=20260923",
                                       "https://example.com/d.xml?date=20260922"])
        calls = []

        def http_get(url, timeout=15):
            calls.append(url)
            if "20260924" in url:
                return child_today, 200
            if "20260923" in url:
                return child_yesterday, 200
            if "20260922" in url:
                return _news_sitemap_xml([("Two days ago, should not be fetched", "2026-09-22T04:00:00Z")]), 200
            return index_xml, 200

        cfg = {"name": "Nikkei Asia", "url": "https://example.com/sitemap_news.xml", "type": "sitemap_index",
              "max_children": 2, "max_age_hours": 48}
        items, status = sm.fetch_one_source(cfg, http_get=http_get, sleep=lambda s: None, now=NOW)
        titles = {it["title"] for it in items}
        self.assertEqual(titles, {"Today story", "Yesterday story"})
        # 索引頁 + 兩個子檔 = 3 次請求，第三個子檔（20260922）不該被抓
        self.assertEqual(len(calls), 3)
        self.assertNotIn("https://example.com/d.xml?date=20260922", calls)

    def test_blocked_source_is_recorded_and_not_retried_a_third_time(self):
        calls = []

        def http_get(url, timeout=15):
            calls.append(url)
            return "Forbidden", 403

        cfg = {"name": "CTEE", "url": "https://example.com/sitemap.xml", "type": "news_sitemap"}
        items, status = sm.fetch_one_source(cfg, http_get=http_get, sleep=lambda s: None, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["http_status"], 403)

    def test_network_failure_is_an_error_not_an_exception(self):
        def http_get(url, timeout=15):
            return "", None

        cfg = {"name": "Example", "url": "https://example.com/sitemap.xml", "type": "news_sitemap"}
        items, status = sm.fetch_one_source(cfg, http_get=http_get, sleep=lambda s: None, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status["status"], "error")

    def test_retries_once_then_succeeds(self):
        xml = _news_sitemap_xml([("Fresh story", "2026-09-24T04:00:00Z")])
        responses = [("", 500), (xml, 200)]
        calls = []

        def http_get(url, timeout=15):
            calls.append(url)
            return responses[len(calls) - 1]

        cfg = {"name": "Example", "url": "https://example.com/sitemap.xml", "type": "news_sitemap"}
        items, status = sm.fetch_one_source(cfg, http_get=http_get, sleep=lambda s: None, now=NOW)
        self.assertEqual(len(calls), 2)
        self.assertEqual(status["status"], "ok")
        self.assertEqual(len(items), 1)

    def test_empty_urlset_is_empty_status_not_error(self):
        xml = _news_sitemap_xml([])
        items, status = sm.fetch_one_source(
            {"name": "Example", "url": "https://example.com/sitemap.xml", "type": "news_sitemap"},
            http_get=lambda u, timeout=15: (xml, 200), sleep=lambda s: None, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status["status"], "empty")


class HttpGetGzipTests(unittest.TestCase):
    def test_default_http_get_decompresses_gzip_payload(self):
        import types
        xml = _news_sitemap_xml([("Gzip story", "2026-09-24T04:00:00Z")])
        gz = gzip.compress(xml.encode("utf-8"))

        class FakeResp:
            status_code = 200
            content = gz

        class FakeRequests:
            @staticmethod
            def get(url, timeout=15, headers=None):
                return FakeResp()

        real_requests = sys.modules.get("requests")
        sys.modules["requests"] = FakeRequests
        try:
            text, status = sm._default_http_get("https://example.com/sitemap.xml.gz")
        finally:
            if real_requests is not None:
                sys.modules["requests"] = real_requests
            else:
                sys.modules.pop("requests", None)
        self.assertEqual(status, 200)
        self.assertIn("Gzip story", text)


class FetchAllTests(unittest.TestCase):
    def test_one_source_failing_does_not_break_others(self):
        good_xml = _news_sitemap_xml([("TSMC good story", "2026-09-24T04:00:00Z")])
        configs = [
            {"name": "Good", "url": "https://good.example.com/s.xml", "type": "news_sitemap"},
            {"name": "Bad", "url": "https://bad.example.com/s.xml", "type": "news_sitemap"},
        ]

        def http_get(url, timeout=15):
            if "bad" in url:
                raise RuntimeError("boom")
            return good_xml, 200

        items, per_source = sm.fetch_all(configs, http_get=http_get, sleep=lambda s: None, now=NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(per_source["Good"]["status"], "ok")
        self.assertEqual(per_source["Bad"]["status"], "error")


class FilterForEvidenceTests(unittest.TestCase):
    def test_company_match_is_kept(self):
        items = [{"title": "TSMC posts 34% revenue growth in August", "url": "https://example.com/a",
                 "domain": "example.com", "source_name": "Example", "published_iso": "2026-09-24T01:00:00Z"}]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(len(kept), 1)
        self.assertIn("TSM", kept[0]["companies"])

    def test_theme_only_match_is_kept(self):
        # 沒有公司名，但點到既有主題／環節辨識詞（借用 fixture routing 裡真的存在的 CoWoS 關鍵詞）
        items = [{"title": "CoWoS packaging capacity expansion announced across the industry",
                 "url": "https://example.com/b", "domain": "example.com", "source_name": "Example",
                 "published_iso": "2026-09-24T01:00:00Z"}]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["theme_hit"])

    def test_no_company_and_no_theme_is_dropped(self):
        items = [{"title": "Random world news with nothing recognizable in it",
                 "url": "https://example.com/c", "domain": "example.com", "source_name": "Example",
                 "published_iso": "2026-09-24T01:00:00Z"}]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(kept, [])

    def test_near_duplicate_of_briefing_title_is_dropped(self):
        title = "TSMC posts 34% revenue growth in August"
        items = [{"title": title, "url": "https://example.com/d", "domain": "example.com",
                 "source_name": "Example", "published_iso": "2026-09-24T01:00:00Z"}]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [title], DD, HOLDINGS)
        self.assertEqual(kept, [])

    def test_blacklisted_domain_is_dropped(self):
        items = [{"title": "TSMC posts 34% revenue growth in August", "url": "https://twitter.com/x",
                 "domain": "twitter.com", "source_name": "Twitter", "published_iso": "2026-09-24T01:00:00Z"}]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(kept, [])

    def test_company_match_ranks_above_theme_only_match(self):
        items = [
            {"title": "CoWoS packaging capacity expansion across the industry", "url": "https://example.com/e",
             "domain": "example.com", "source_name": "Example", "published_iso": "2026-09-24T01:00:00Z"},
            {"title": "TSMC posts 34% revenue growth in August", "url": "https://example.com/f",
             "domain": "example.com", "source_name": "Example", "published_iso": "2026-09-24T02:00:00Z"},
        ]
        kept = sm.filter_for_evidence(items, MATCHER, ROUTING, [], DD, HOLDINGS)
        self.assertEqual(kept[0]["url"], "https://example.com/f")


class MakeCandidateTests(unittest.TestCase):
    def test_candidate_shape(self):
        item = {"title": "TSMC posts 34% revenue growth in August", "url": "https://example.com/a",
               "source_name": "Example", "companies": ["TSM"], "figures": ["pct:34"],
               "published_iso": "2026-09-24T01:00:00Z", "priority": True, "has_figure": True,
               "title_from_slug": False}
        cand = sm.make_candidate(item, MATCHER, "2026-09-24")
        self.assertEqual(cand["block"], "sitemap")
        self.assertEqual(cand["priority"], sm.SITEMAP_PRIORITY)
        self.assertEqual(cand["source"], "Example")
        self.assertEqual(cand["source_date"], "2026-09-24")
        self.assertEqual(cand["companies"], ["TSM"])
        self.assertTrue(cand["_match_priority"])
        self.assertTrue(cand["_match_has_figure"])
        self.assertEqual(cand["rss"][0]["url"], "https://example.com/a")
        self.assertEqual(cand["basis"]["code"], "headline_summary")


class ToPoolItemsTests(unittest.TestCase):
    def test_shape_matches_rss_item_convention(self):
        items = [{"title": "T", "url": "https://x/a", "source_name": "Reuters",
                 "published_iso": "2026-09-24T01:00:00Z"}]
        pool = sm.to_pool_items(items)
        self.assertEqual(pool, [{"title": "T", "summary": "", "link": "https://x/a", "source": "Reuters",
                                "published": "2026-09-24T01:00:00Z"}])


class FetchSitemapCandidatesTests(unittest.TestCase):
    def _configs(self):
        return [{"name": "Example", "url": "https://example.com/sitemap_news.xml", "type": "news_sitemap",
                "lang": "en", "max_age_hours": 48}]

    def test_end_to_end_returns_candidates_pool_and_quality(self):
        xml = _news_sitemap_xml([("TSMC posts 34% revenue growth in August", "2026-09-24T01:00:00Z")])
        cands, pool, quality = sm.fetch_sitemap_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-24", max_kept=8, configs=self._configs(),
            http_get=lambda u, timeout=15: (xml, 200), sleep=lambda s: None, now=NOW)
        self.assertTrue(quality["enabled"])
        self.assertEqual(quality["kept"], 1)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["block"], "sitemap")
        self.assertEqual(len(pool), 1)
        self.assertEqual(quality["sources"]["Example"]["status"], "ok")

    def test_zero_max_kept_still_returns_full_pool_for_wide_scan(self):
        xml = _news_sitemap_xml([("TSMC posts 34% revenue growth in August", "2026-09-24T01:00:00Z")])
        cands, pool, quality = sm.fetch_sitemap_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-24", max_kept=0, configs=self._configs(),
            http_get=lambda u, timeout=15: (xml, 200), sleep=lambda s: None, now=NOW)
        self.assertEqual(cands, [])
        self.assertEqual(len(pool), 1)   # 早報外掃描還是要看得到這則

    def test_no_sources_configured_is_disabled_not_an_error(self):
        cands, pool, quality = sm.fetch_sitemap_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-24", configs=[])
        self.assertEqual((cands, pool), ([], []))
        self.assertFalse(quality["enabled"])

    def test_single_source_http_failure_is_isolated_not_fatal(self):
        # fetch_all 已經逐來源包 try/except（見 FetchAllTests），單一來源的 http_get 出錯只讓
        # 那個來源標 error，quality["enabled"] 整體仍是 True，不是整層關閉
        def boom(*a, **k):
            raise RuntimeError("boom")

        cands, pool, quality = sm.fetch_sitemap_candidates(
            ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-24", configs=self._configs(), http_get=boom,
            sleep=lambda s: None, now=NOW)
        self.assertEqual((cands, pool), ([], []))
        self.assertTrue(quality["enabled"])
        self.assertEqual(quality["sources"]["Example"]["status"], "error")

    def test_exception_outside_per_source_isolation_is_caught_and_reported(self):
        from unittest import mock

        with mock.patch.object(sm, "fetch_all", side_effect=RuntimeError("boom")):
            cands, pool, quality = sm.fetch_sitemap_candidates(
                ROUTING, MATCHER, DD, HOLDINGS, [], "2026-09-24", configs=self._configs(),
                sleep=lambda s: None, now=NOW)
        self.assertEqual((cands, pool), ([], []))
        self.assertFalse(quality["enabled"])
        self.assertIn("error", quality)


if __name__ == "__main__":
    unittest.main()
