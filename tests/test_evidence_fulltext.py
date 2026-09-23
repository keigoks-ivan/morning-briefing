"""evidence_fulltext（2026-09-23 新增）離線測試。不連網、不呼叫真的 Google News 解碼或
trafilatura 抓取（除了一個直接測 trafilatura 抽字的案例，那個只餵字串，不連網）。"""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "briefing"))

import evidence_fulltext as eft  # noqa: E402


def cand(cid, headline="", rss=None, headline_figures=None):
    return {"cid": cid, "headline": headline, "rss": rss or [], "headline_figures": headline_figures or []}


class DomainAndPaywallTests(unittest.TestCase):
    def test_domain_of_strips_www_port_and_userinfo(self):
        self.assertEqual(eft.domain_of("https://www.example.com/a/b"), "example.com")
        self.assertEqual(eft.domain_of("https://example.com:443/x"), "example.com")
        self.assertEqual(eft.domain_of("https://user:pass@sub.example.com/x"), "sub.example.com")
        self.assertEqual(eft.domain_of("not a url"), "")

    def test_paywall_matches_domain_and_subdomain_not_lookalikes(self):
        self.assertTrue(eft.is_paywalled("https://www.ft.com/content/x"))
        self.assertTrue(eft.is_paywalled("https://asia.nikkei.com/x"))
        self.assertFalse(eft.is_paywalled("https://www.cnbc.com/x"))
        self.assertFalse(eft.is_paywalled("https://notft.com/x"))


class ResolveUrlTests(unittest.TestCase):
    def test_non_google_news_url_passes_through_untouched(self):
        url = "https://www.reuters.com/technology/x"
        self.assertEqual(eft.resolve_url(url, decode=lambda u: "should not be called"), url)

    def test_google_news_url_uses_decoder_result(self):
        gn = "https://news.google.com/rss/articles/abc123"
        self.assertEqual(eft.resolve_url(gn, decode=lambda u: "https://publisher.example.com/story"),
                         "https://publisher.example.com/story")

    def test_decoder_failure_or_none_falls_back_to_original_url(self):
        gn = "https://news.google.com/rss/articles/abc123"
        self.assertEqual(eft.resolve_url(gn, decode=lambda u: None), gn)

        def boom(u):
            raise RuntimeError("network down")
        self.assertEqual(eft.resolve_url(gn, decode=boom), gn)


class WindowAndQuoteTests(unittest.TestCase):
    def test_short_text_returned_unchanged(self):
        text = "Company X raised $3.5 billion for a new plant."
        self.assertEqual(eft.window_around_headline(text, "Company X raises $3.5 billion"), text)

    def test_long_text_windows_around_headline_anchor(self):
        filler = "Unrelated background paragraph about the industry in general. " * 100
        anchor_sentence = "Company X confirmed it raised $3.5 billion in the bond sale on Monday."
        text = filler + anchor_sentence + (" More detail follows about financing terms." * 50)
        self.assertGreater(len(text), eft.EXCERPT_CHARS)
        window = eft.window_around_headline(text, "Company X raises $3.5 billion for new plant",
                                             limit=eft.EXCERPT_CHARS)
        self.assertLessEqual(len(window), eft.EXCERPT_CHARS)
        self.assertIn("$3.5 billion", window)

    def test_no_anchor_found_falls_back_to_head_of_text(self):
        text = "x" * (eft.EXCERPT_CHARS + 500)
        window = eft.window_around_headline(text, "No numbers or names here", limit=eft.EXCERPT_CHARS)
        self.assertEqual(window, text[:eft.EXCERPT_CHARS])

    def test_quotes_pick_sentences_with_headline_figure_and_cap_total_length(self):
        text = ("Nothing to see here. Company X raised $3.5 billion in a bond sale on Monday. "
                "Unrelated filler sentence follows. The $3.5 billion deal was the largest of the year.")
        headline_figs = ["n:3.5e+09"]
        quotes = eft.quotes_with_figures(text, headline_figs, limit_total=eft.QUOTE_CHARS)
        self.assertLessEqual(sum(len(q) for q in quotes), eft.QUOTE_CHARS)
        self.assertLessEqual(len(quotes), 2)
        self.assertTrue(any("3.5 billion" in q for q in quotes))

    def test_no_headline_figures_means_no_quotes(self):
        self.assertEqual(eft.quotes_with_figures("Some text with $1 billion in it.", []), [])


class FetchOrchestrationTests(unittest.TestCase):
    """全部走假的 http_get／decode，不連網、不呼叫真的 trafilatura。"""

    def setUp(self):
        self.extract_patch = mock.patch.object(eft, "_extract_text")
        self.extract = self.extract_patch.start()
        self.addCleanup(self.extract_patch.stop)

    def test_candidate_with_no_rss_urls_is_no_url(self):
        out = eft.fetch_fulltext([cand("c1")], http_get=lambda u: (None, "error"))
        self.assertEqual(out["c1"]["status"], "no_url")

    def test_paywalled_domain_is_skipped_without_fetching(self):
        calls = []

        def http_get(url):
            calls.append(url)
            return "<html>full text</html>", "ok"

        c = cand("c1", rss=[{"url": "https://www.wsj.com/articles/x"}])
        out = eft.fetch_fulltext([c], http_get=http_get)
        self.assertEqual(out["c1"]["status"], "paywalled")
        self.assertEqual(out["c1"]["domain"], "wsj.com")
        self.assertEqual(calls, [])   # 付費牆網域不發請求

    def test_falls_through_to_next_url_when_first_extract_is_too_short(self):
        self.extract.side_effect = ["short stub", "x" * 800]
        c = cand("c1", headline="Big number", headline_figures=["n:3.5e+09"],
                 rss=[{"url": "https://a.example.com/1"}, {"url": "https://b.example.com/2"}])
        out = eft.fetch_fulltext([c], http_get=lambda u: ("<html/>", "ok"))
        self.assertEqual(out["c1"]["status"], "ok")
        self.assertEqual(out["c1"]["url"], "https://b.example.com/2")
        self.assertEqual(out["c1"]["domain"], "b.example.com")

    def test_success_returns_word_count_excerpt_and_quotes(self):
        text = "Company X raised $3.5 billion for a new plant. " * 20
        self.extract.return_value = text
        c = cand("c1", headline="Company X raises $3.5 billion", headline_figures=["n:3.5e+09"],
                 rss=[{"url": "https://a.example.com/1"}])
        out = eft.fetch_fulltext([c], http_get=lambda u: ("<html/>", "ok"))["c1"]
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["word_count"], len(text.split()))
        self.assertIn("excerpt", out)
        self.assertTrue(out["quotes"])
        self.assertLessEqual(sum(len(q) for q in out["quotes"]), eft.QUOTE_CHARS)

    def test_all_urls_fail_is_failed_not_paywalled(self):
        self.extract.return_value = None
        c = cand("c1", rss=[{"url": "https://a.example.com/1"}, {"url": "https://b.example.com/2"}])
        out = eft.fetch_fulltext([c], http_get=lambda u: ("<html/>", "ok"))["c1"]
        self.assertEqual(out["status"], "failed")

    def test_fetch_error_tries_next_url(self):
        self.extract.return_value = "y" * 800

        def http_get(url):
            if url.endswith("/1"):
                return None, "error:Timeout"
            return "<html/>", "ok"

        c = cand("c1", rss=[{"url": "https://a.example.com/1"}, {"url": "https://b.example.com/2"}])
        out = eft.fetch_fulltext([c], http_get=http_get)["c1"]
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["url"], "https://b.example.com/2")

    def test_only_first_max_candidates_are_attempted(self):
        self.extract.return_value = "z" * 800
        cands = [cand(f"c{i}", rss=[{"url": f"https://a.example.com/{i}"}]) for i in range(15)]
        out = eft.fetch_fulltext(cands, http_get=lambda u: ("<html/>", "ok"), max_candidates=12)
        self.assertEqual(len(out), 12)
        self.assertEqual(set(out), {f"c{i}" for i in range(12)})

    def test_wall_timeout_marks_slow_candidates_as_failed_without_waiting(self):
        def slow_get(url):
            time.sleep(2)
            return "<html/>", "ok"

        c = cand("c1", rss=[{"url": "https://a.example.com/1"}])
        t0 = time.time()
        out = eft.fetch_fulltext([c], http_get=slow_get, wall_timeout=0.1)["c1"]
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.5)   # 沒有真的等滿 2 秒
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out.get("reason"), "timeout")


class RealTrafilaturaSmokeTest(unittest.TestCase):
    """只餵靜態字串，不連網：確認真的 trafilatura 套件裝得上、抽得出主文。"""

    def test_extract_text_pulls_article_body_from_static_html(self):
        html = """<html><head><title>t</title></head><body><article>
        <h1>Company X raises $3.5 billion for new plant</h1>
        <p>Company X said on Monday it raised $3.5 billion in a bond sale to fund a new plant in Arizona.
        The company said the facility will begin production in 2028 and will employ 4,000 workers once
        fully operational, citing continued growth in demand from data center customers.</p>
        </article></body></html>"""
        text = eft._extract_text(html)
        self.assertIsNotNone(text)
        self.assertGreater(len(text), eft.MIN_CHARS - 200)
        self.assertIn("3.5 billion", text)


if __name__ == "__main__":
    unittest.main()
