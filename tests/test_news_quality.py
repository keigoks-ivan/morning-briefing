import os
import json
import sys
import types as module_types
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "briefing"))

# The system Python used for fast unit tests does not install the production
# fallback SDKs. These tests exercise pure helpers only, so lightweight import
# stubs keep the suite offline and cannot mask runtime calls.
sys.modules.setdefault("anthropic", module_types.ModuleType("anthropic"))
google_module = sys.modules.setdefault("google", module_types.ModuleType("google"))
genai_module = sys.modules.setdefault("google.genai", module_types.ModuleType("google.genai"))
genai_types_module = sys.modules.setdefault("google.genai.types", module_types.ModuleType("google.genai.types"))
google_module.genai = genai_module
genai_module.types = genai_types_module
try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    sys.modules["requests"] = module_types.ModuleType("requests")
try:
    import feedparser  # noqa: F401
except ModuleNotFoundError:
    feedparser_module = module_types.ModuleType("feedparser")
    feedparser_module.parse = lambda _url: module_types.SimpleNamespace(entries=[])
    sys.modules["feedparser"] = feedparser_module
try:
    import pytz  # noqa: F401
except ModuleNotFoundError:
    pytz_module = module_types.ModuleType("pytz")
    pytz_module.timezone = lambda _name: timezone.utc
    pytz_module.utc = timezone.utc
    sys.modules["pytz"] = pytz_module

import ai_processor
import html_template
import news_fetcher
from source_registry import (
    canonicalize_source,
    normalize_url,
    render_source_whitelist,
)


class SourceRegistryTests(unittest.TestCase):
    def test_aliases_and_domains_are_canonicalized(self):
        self.assertEqual(canonicalize_source("Reuters (GN)"), "Reuters")
        self.assertEqual(canonicalize_source("Focus Taiwan"), "中央社")
        self.assertEqual(canonicalize_source("", "https://www.reuters.com/world/story"), "Reuters")
        self.assertEqual(
            canonicalize_source("Reuters", "https://news.google.com/rss/articles/abc"),
            "Reuters",
        )

    def test_blacklisted_and_unknown_sources_are_rejected(self):
        self.assertIsNone(canonicalize_source("Seeking Alpha"))
        self.assertIsNone(canonicalize_source("Yahoo Finance"))
        self.assertIsNone(canonicalize_source("Unknown Blog"))
        self.assertIsNone(canonicalize_source("", "https://feedburner.com/unknown-feed"))
        self.assertIsNone(canonicalize_source("Reuters", "https://example-blog.test/fake"))

    def test_multiple_sources_and_tracking_url(self):
        self.assertEqual(
            canonicalize_source("DIGITIMES／TrendForce／CNBC"),
            "DIGITIMES／TrendForce／CNBC",
        )
        self.assertEqual(
            normalize_url("https://Reuters.com/world/test/?utm_source=x&b=2&a=1#top"),
            "https://reuters.com/world/test?a=1&b=2",
        )
        self.assertNotIn("Seeking Alpha", render_source_whitelist())


class RssQualityTests(unittest.TestCase):
    def _item(self, title, link, source="Reuters", published="2026-09-09 06:00"):
        return {
            "title": title,
            "summary": "具體摘要內容",
            "link": link,
            "source": source,
            "published": published,
            "topics": ["macro"],
        }

    def test_rss_dedup_uses_url_and_near_title(self):
        items = [
            self._item("Fed signals a rate pause after CPI", "https://reuters.com/a?utm_source=x"),
            self._item("Fed signals a rate pause after CPI", "https://reuters.com/a"),
            self._item("TSMC raises advanced packaging capacity", "https://reuters.com/b"),
        ]
        kept, removed = news_fetcher._dedup_rss_items(items)
        self.assertEqual(len(kept), 2)
        self.assertEqual(removed, 1)

    def test_deep_dive_has_two_calls_and_no_meta_query(self):
        calls = []

        def fake_query(args):
            calls.append(args)
            return {"query": args[0], "answer": "ok", "sources": []}

        with mock.patch.object(news_fetcher, "_perplexity_query", side_effect=fake_query):
            result = news_fetcher.fetch_deep_dive_news()
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(args[4] == "deep-fixed" for args in calls))
        self.assertEqual(result["dynamic"], [])

    def test_base_search_keeps_eighteen_broad_queries(self):
        queries = news_fetcher.PERPLEXITY_QUERIES
        self.assertEqual(len(queries), 18)
        combined = " ".join(queries).casefold()
        self.assertIn("credit and liquidity", combined)
        self.assertIn("global trade, shipping", combined)
        self.assertIn("healthcare", combined)
        self.assertIn("data-center infrastructure", combined)
        self.assertIn("enterprise software, cybersecurity", combined)
        self.assertIn("industrial automation, robotics", combined)
        self.assertIn("earnings", combined)

    def test_google_news_source_variant_falls_back_to_specific_feed_label(self):
        entry = {
            "title": "Test story - Reuters News",
            "link": "https://news.google.com/rss/articles/abc",
            "source": {"title": "Reuters News"},
            "summary": "Details",
        }
        with mock.patch.object(
            news_fetcher.feedparser,
            "parse",
            return_value=module_types.SimpleNamespace(entries=[entry]),
        ):
            items, blocked = news_fetcher._fetch_one_feed(
                ("Reuters (GN)", "https://news.google.com/rss/search?q=x", 5, 24)
            )
        self.assertEqual(blocked, 0)
        self.assertEqual(items[0]["source"], "Reuters")

    def test_curated_direct_feed_can_use_allowlisted_feed_identity(self):
        entry = {
            "title": "Central News Agency finance story",
            "link": "https://feeds.feedburner.com/item/abc",
            "summary": "Details",
        }
        with mock.patch.object(
            news_fetcher.feedparser,
            "parse",
            return_value=module_types.SimpleNamespace(entries=[entry]),
        ):
            items, blocked = news_fetcher._fetch_one_feed(
                ("中央社 財經", "https://feeds.feedburner.com/rsscna/finance", 5, 24)
            )
        self.assertEqual(blocked, 0)
        self.assertEqual(items[0]["source"], "中央社")

    def test_search_citation_urls_are_hard_filtered(self):
        result = {
            "answer": "ok",
            "sources": ["https://reuters.com/a", "https://example-blog.test/b"],
        }
        with mock.patch.object(news_fetcher, "_claude_code_available", return_value=True), \
             mock.patch.object(news_fetcher, "_claude_search", return_value=result):
            filtered = news_fetcher._llm_search("system", "query")
        self.assertEqual(filtered["sources"], ["https://reuters.com/a"])

    def test_search_retries_once_before_fallback(self):
        success = {"answer": "ok", "sources": ["https://reuters.com/a"]}
        with mock.patch.object(news_fetcher, "_claude_code_available", return_value=True), \
             mock.patch.object(
                 news_fetcher, "_claude_search", side_effect=[RuntimeError("temporary"), success]
             ) as search:
            result = news_fetcher._llm_search("system", "query")
        self.assertEqual(search.call_count, 2)
        self.assertEqual(result["answer"], "ok")

    def test_news_search_cli_uses_oauth_not_api_credentials(self):
        completed = module_types.SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"subtype": "success", "result": "answer\nSOURCES: none"}),
            stderr="",
        )
        with mock.patch.dict(os.environ, {
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
            "ANTHROPIC_API_KEY": "paid",
            "ANTHROPIC_AUTH_TOKEN": "paid-token",
            "ANTHROPIC_BASE_URL": "https://example.test",
        }, clear=False), \
             mock.patch.object(news_fetcher.shutil, "which", return_value="/usr/bin/claude"), \
             mock.patch.object(news_fetcher.subprocess, "run", return_value=completed) as run:
            news_fetcher._claude_search("system", "query", "test")
        cli_env = run.call_args.kwargs["env"]
        self.assertEqual(cli_env["CLAUDE_CODE_OAUTH_TOKEN"], "oauth")
        self.assertNotIn("ANTHROPIC_API_KEY", cli_env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", cli_env)
        self.assertNotIn("ANTHROPIC_BASE_URL", cli_env)


class AiQualityTests(unittest.TestCase):
    def test_industry_prompt_uses_soft_target_and_quality_fields(self):
        prompt = ai_processor.GEMINI_SYSTEM_PROMPT + ai_processor.GEMINI_USER_PROMPT_TEMPLATE
        self.assertIn("industry_developments", prompt)
        self.assertIn("目標 10–14 條", prompt)
        self.assertIn("value_chain", prompt)
        self.assertIn("why_it_matters", prompt)
        rendered = ai_processor.GEMINI_USER_PROMPT_TEMPLATE.format(
            today="2026-09-09",
            cutoff_date="2026-09-08",
            last_session="2026-09-08",
            watchlist_count=0,
            watchlist_block="（無）",
            news_text="material",
            earnings_context="",
        )
        self.assertIn('"industry_developments": [', rendered)

    def test_sanitize_enforces_allowlist(self):
        data = {
            "top_stories": [
                {"headline": "合法", "body": "事件內容", "source": "路透社", "source_date": "2026-09-09"},
                {"headline": "不合法", "body": "事件內容", "source": "Random Blog", "source_date": "2026-09-09"},
            ]
        }
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual([item["source"] for item in data["top_stories"]], ["Reuters"])
        self.assertEqual(stats["invalid_source"], 1)

    def test_sanitize_rejects_allowlisted_name_with_unknown_link_domain(self):
        data = {
            "weekend_reads": [{
                "title": "Fake Reuters link",
                "why": "test",
                "source": "Reuters",
                "source_date": "2026-09-09",
                "link": "https://example-blog.test/fake",
            }]
        }
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual(data["weekend_reads"], [])
        self.assertEqual(stats["invalid_source"], 1)

    def test_industry_quality_requires_complete_fields_and_caps_each_industry(self):
        def industry_item(headline, why="改變未來供需。"):
            return {
                "industry": "半導體",
                "headline": headline,
                "body": "TSMC宣布新增$1B產能。",
                "development": "產能",
                "value_chain": "設備→晶圓代工→客戶",
                "why_it_matters": why,
                "source": "Reuters",
                "source_date": "2026-09-09",
            }

        data = {"industry_developments": [
            industry_item("事件1"), industry_item("事件2"), industry_item("事件3"),
            industry_item("缺少中期含義", why=""),
        ]}
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual(len(data["industry_developments"]), 2)
        self.assertEqual(stats["industry_quality"], 2)

    def test_watchlist_duplicate_is_merged_into_primary(self):
        data = {
            "top_stories": [{
                "headline": "Nvidia投資MediaTek強化AI晶片合作",
                "body": "Nvidia投資MediaTek $3.5B，雙方合作開發AI晶片。",
                "source_date": "2026-09-09",
            }],
            "watchlist_news": [{
                "ticker": "NVDA",
                "headline": "Nvidia入股MediaTek",
                "body": "這項$3.5B投資擴大Nvidia在亞洲供應鏈的布局。",
                "source_date": "2026-09-09",
            }],
        }
        stats = ai_processor._dedup_news(data)
        self.assertEqual(data["watchlist_news"], [])
        self.assertEqual(data["top_stories"][0]["watchlist_refs"][0]["ticker"], "NVDA")
        self.assertEqual(stats["watchlist_refs_merged"], 1)

    def test_industry_duplicate_does_not_repeat_top_story(self):
        data = {
            "top_stories": [{
                "headline": "TSMC擴先進封裝產能",
                "body": "TSMC將CoWoS產能擴大50%。",
                "source_date": "2026-09-09",
            }],
            "industry_developments": [{
                "industry": "半導體",
                "headline": "TSMC將CoWoS產能擴大50%",
                "body": "TSMC擴先進封裝產能，產能增加50%。",
                "development": "產能",
                "source_date": "2026-09-09",
            }],
        }
        ai_processor._dedup_news(data)
        self.assertEqual(len(data["top_stories"]), 1)
        self.assertEqual(data["industry_developments"], [])

    def test_deep_dive_becomes_extension_but_different_event_survives(self):
        data = {
            "top_stories": [{
                "headline": "台積電與ASML導入High NA EUV設備",
                "body": "雙方合作導入單價$400M設備，規劃2030年量產。",
                "source_date": "2026-09-09",
            }],
            "ai_industry": [{
                "headline": "ASML擴建德國服務中心",
                "body": "ASML投資$2B擴充維修產能。",
                "source_date": "2026-09-09",
            }],
            "daily_deep_dive": [{
                "theme": "High NA EUV供應鏈",
                "headline": "ASML新設備獲台積電採用",
                "situation": "台積電與ASML合作導入單價$400M的High NA EUV設備，規劃2030年量產。",
                "key_data": [],
                "source_date": "2026-09-09",
            }],
        }
        ai_processor._dedup_news(data)
        self.assertEqual(len(data["top_stories"]), 1)
        self.assertEqual(len(data["ai_industry"]), 1)
        self.assertEqual(data["daily_deep_dive"][0]["event_role"], "deep_extension")
        self.assertEqual(data["daily_deep_dive"][0]["situation"], "")

    def test_same_company_and_amount_with_different_actions_survive(self):
        investment = ai_processor._event_features({
            "headline": "Meta投資AI新創$1B",
            "body": "Meta以$1B入股新創公司。",
            "source_date": "2026-09-09",
        })
        acquisition = ai_processor._event_features({
            "headline": "Meta收購數據中心$1B",
            "body": "Meta以$1B收購另一座數據中心。",
            "source_date": "2026-09-09",
        })
        self.assertFalse(ai_processor._same_event(investment, acquisition))

    def test_entity_aliases_use_token_boundaries(self):
        features = ai_processor._event_features({"headline": "Metadata standard released"})
        self.assertNotIn("meta", features["entities"])

    def test_cli_env_never_passes_api_credentials(self):
        with mock.patch.dict(os.environ, {
            "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
            "ANTHROPIC_API_KEY": "paid",
            "ANTHROPIC_AUTH_TOKEN": "paid-token",
            "ANTHROPIC_BASE_URL": "https://example.test",
        }, clear=False):
            env = ai_processor._cli_env()
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "oauth")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)
        self.assertNotIn("ANTHROPIC_BASE_URL", env)

    def test_merged_watchlist_reference_renders_on_primary_card(self):
        data = {
            "date": "2026年09月09日 06:15 TST",
            "top_stories": [{
                "headline": "Nvidia投資MediaTek強化AI晶片合作",
                "body": "Nvidia投資MediaTek $3.5B。",
                "tag": "指數部",
                "tag_type": "tech",
                "source": "Reuters",
                "source_date": "2026-09-09",
                "watchlist_refs": [{"ticker": "NVDA", "impact": "擴大亞洲供應鏈布局。"}],
            }],
        }
        rendered = html_template.build_news_html(data)
        self.assertEqual(rendered.count("Nvidia投資MediaTek強化AI晶片合作"), 1)
        self.assertIn("對關注股的影響", rendered)
        self.assertIn("NVDA", rendered)

    def test_industry_development_renders_value_chain_and_horizon(self):
        rendered = html_template.build_news_html({
            "date": "2026年09月09日 06:15 TST",
            "industry_developments": [{
                "industry": "AI基礎設施",
                "headline": "資料中心電力訂單擴大",
                "body": "Vertiv取得$2B訂單。",
                "development": "需求",
                "value_chain": "發電設備→電力管理→資料中心",
                "why_it_matters": "交期延長將推高產能利用率。",
                "source": "Reuters",
                "source_date": "2026-09-09",
                "importance": "high",
            }],
        })
        self.assertIn("產業發展追蹤", rendered)
        self.assertIn("產業鏈", rendered)
        self.assertIn("6–18 個月", rendered)


if __name__ == "__main__":
    unittest.main()
