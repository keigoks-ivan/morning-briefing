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
        self.assertEqual(canonicalize_source("Focus Taiwan"), "CNA")
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

    def test_base_search_keeps_twenty_two_broad_queries(self):
        queries = news_fetcher.PERPLEXITY_QUERIES
        self.assertEqual(len(queries), 22)
        combined = " ".join(queries).casefold()
        self.assertIn("startup financing detail", combined)
        self.assertIn("startup ecosystem structural news", combined)
        self.assertIn("frontier technology milestones", combined)
        self.assertIn("peer-reviewed research", combined)
        self.assertIn("credit and liquidity", combined)
        self.assertIn("global trade, shipping", combined)
        self.assertIn("healthcare", combined)
        self.assertIn("data-center infrastructure", combined)
        self.assertIn("enterprise software, cybersecurity", combined)
        self.assertIn("industrial automation, robotics", combined)
        self.assertIn("ai application deployments", combined)
        self.assertIn("us sector and large-cap stock movers", combined)
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
        self.assertEqual(items[0]["source"], "CNA")

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
    def test_industry_prompt_uses_six_fact_categories_and_quality_fields(self):
        prompt = ai_processor.GEMINI_SYSTEM_PROMPT + ai_processor.GEMINI_USER_PROMPT_TEMPLATE
        self.assertIn("industry_developments", prompt)
        for category in (
            "US earnings", "Semis and supply chain", "AI in production",
            "Global startups", "US sector moves", "Industry and finance",
        ):
            self.assertIn(category, prompt)
        self.assertIn('"evidence"', prompt)
        self.assertIn('"fact_status"', prompt)
        self.assertIn('"confirmed_impact"', prompt)
        self.assertIn('"unknowns"', prompt)
        self.assertIn("Target 12-16 across the block, maximum 18", prompt)
        analysis_prompt = ai_processor.CLAUDE_USER_PROMPT_TEMPLATE
        self.assertIn("tech_trends: 3-4 entries when the material supports it, maximum 4", analysis_prompt)
        self.assertIn("daily_deep_dive: at most 1 theme", analysis_prompt)
        rendered = ai_processor.GEMINI_USER_PROMPT_TEMPLATE.format(
            today="2026-09-09",
            cutoff_date="2026-09-08",
            last_session="2026-09-08",
            watchlist_count=0,
            watchlist_block="(none)",
            news_text="material",
            earnings_context="",
        )
        self.assertIn('"industry_developments": [', rendered)

    def test_sanitize_enforces_allowlist(self):
        data = {
            "top_stories": [
                {"headline": "Allowed", "body": "Event body", "source": "Reuters", "source_date": "2026-09-09"},
                {"headline": "Blocked", "body": "Event body", "source": "Random Blog", "source_date": "2026-09-09"},
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

    def test_fact_news_requires_complete_fields_and_caps_each_category(self):
        def fact_item(headline, industry="Semiconductors",
                      evidence="TSMC announced a $1B investment on Sept 9.",
                      category="Semis and supply chain"):
            return {
                "category": category,
                "industry": industry,
                "headline": headline,
                "body": "TSMC announced $1B of added capacity.",
                "evidence": evidence,
                "fact_status": "reported",
                "development": "capacity",
                "value_chain": "equipment to foundry to customer",
                "market_move": "",
                "confirmed_impact": "The company said the new capacity serves existing customers.",
                "unknowns": "Production start date undisclosed.",
                "source": "Reuters",
                "source_date": "2026-09-09",
            }

        data = {"industry_developments": [
            fact_item("Event 1"), fact_item("Event 2", "AI infrastructure"),
            fact_item("Event 3", "Enterprise software and security"),
            fact_item("Event 4", "Robotics and automation"),
            fact_item("Event 5", "Healthcare and biotech"), fact_item("No evidence", evidence=""),
        ]}
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual(len(data["industry_developments"]), 4)
        self.assertEqual(stats["industry_quality"], 2)

    def test_fact_news_normalizes_category_and_trims_inference(self):
        data = {"industry_developments": [{
            "category": "AI in Production",
            "industry": "Enterprise software and security",
            "headline": "Hospital signs an AI deployment contract",
            "body": "A hospital signed a $10M contract. Investors should watch the growth from here.",
            "evidence": "Contract signed Sept 9, worth $10M.",
            "fact_status": "agreed",
            "development": "demand",
            "value_chain": "model vendor to hospital",
            "market_move": "",
            "confirmed_impact": "The vendor stands to benefit as valuations re-rate.",
            "unknowns": "Seat count undisclosed.",
            "source": "Reuters",
            "source_date": "2026-09-09",
        }]}
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual(data["industry_developments"][0]["category"], "AI in production")
        self.assertEqual(data["industry_developments"][0]["fact_status"], "signed")
        self.assertEqual(data["industry_developments"][0]["body"], "A hospital signed a $10M contract.")
        self.assertEqual(data["industry_developments"][0]["confirmed_impact"], "")
        self.assertEqual(stats["inference_trimmed"], 2)

    def test_fact_news_recovers_evidence_and_unknowns_from_factual_body(self):
        data = {"industry_developments": [{
            "category": "Global startups",
            "industry": "Fintech",
            "headline": "Startup closes a Series A",
            "body": "FinCo closed a $25M Series A on Sept 9.",
            "evidence": "",
            "fact_status": "completed",
            "development": "capex",
            "value_chain": "",
            "market_move": "",
            "confirmed_impact": "",
            "unknowns": "",
            "source": "Reuters",
            "source_date": "2026-09-09",
        }]}
        ai_processor._sanitize_news(data, "2026-09-08")
        item = data["industry_developments"][0]
        self.assertEqual(item["evidence"], "FinCo closed a $25M Series A on Sept 9.")
        self.assertEqual(item["unknowns"], "Nothing else outstanding in the material.")

    def test_market_move_is_stripped_from_evidence_but_kept_in_market_move(self):
        """evidence／confirmed_impact 不得夾帶行情句；market_move 那一欄才是放漲跌的。"""
        base = {
            "category": "Industry and finance",
            "industry": "Other",
            "headline": "Volkswagen cuts full-year profit outlook",
            "body": "Volkswagen warned full-year profit will take a hit of up to EUR10 billion on weak China operations.",
            "evidence": "EUR10 billion profit impact disclosed September 18, 2026; shares fell as much as 7%.",
            "fact_status": "company guidance",
            "development": "demand",
            "value_chain": "",
            "market_move": "",
            "confirmed_impact": "",
            "unknowns": "Restructuring detail undisclosed.",
            "source": "Reuters",
            "source_date": "2026-09-18",
        }
        data = {"industry_developments": [dict(base)]}
        stats = ai_processor._sanitize_news(data, "2026-09-17")
        item = data["industry_developments"][0]
        self.assertNotIn("shares fell", item["evidence"])
        self.assertIn("EUR10 billion profit impact", item["evidence"])
        self.assertEqual(stats["market_sent"], 1)

        mover = {**base, "category": "US sector moves",
                 "evidence": "Guidance cut announced Sept 18.",
                 "market_move": "Shares fell 7.1% in the regular session."}
        data = {"industry_developments": [mover]}
        ai_processor._sanitize_news(data, "2026-09-17")
        self.assertEqual(len(data["industry_developments"]), 1)
        self.assertEqual(data["industry_developments"][0]["market_move"],
                         "Shares fell 7.1% in the regular session.")

    def test_stock_mover_fact_requires_exact_move_and_session(self):
        base = {
            "category": "US sector moves",
            "industry": "Enterprise software and security",
            "headline": "Company issues full-year guidance",
            "body": "The company guided full-year revenue to $2B.",
            "evidence": "Full-year revenue guidance of $2B announced Sept 9.",
            "fact_status": "company guidance",
            "development": "demand",
            "value_chain": "",
            "confirmed_impact": "",
            "unknowns": "Actual full-year revenue still to be reported.",
            "source": "Reuters",
            "source_date": "2026-09-09",
        }
        data = {"industry_developments": [
            {**base, "market_move": "Closed up 8.2% in the last US session."},
            {**base, "headline": "Another company guides", "market_move": "Shares rose noticeably."},
        ]}
        stats = ai_processor._sanitize_news(data, "2026-09-08")
        self.assertEqual(len(data["industry_developments"]), 1)
        self.assertEqual(stats["industry_quality"], 1)

    def test_watchlist_duplicate_is_merged_into_primary(self):
        data = {
            "top_stories": [{
                "headline": "Nvidia invests in MediaTek to deepen AI chip work",
                "body": "Nvidia invested $3.5B in MediaTek to co-develop AI chips.",
                "source_date": "2026-09-09",
            }],
            "watchlist_news": [{
                "ticker": "NVDA",
                "headline": "Nvidia takes a stake in MediaTek",
                "body": "The $3.5B investment widens Nvidia's Asian supply-chain footprint.",
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
                "headline": "TSMC expands advanced packaging capacity",
                "body": "TSMC will raise CoWoS capacity by 50%.",
                "source_date": "2026-09-09",
            }],
            "industry_developments": [{
                "industry": "Semiconductors",
                "headline": "TSMC to raise CoWoS capacity by 50%",
                "body": "TSMC is expanding advanced packaging, lifting capacity by 50%.",
                "development": "capacity",
                "source_date": "2026-09-09",
            }],
        }
        ai_processor._dedup_news(data)
        self.assertEqual(len(data["top_stories"]), 1)
        self.assertEqual(data["industry_developments"], [])

    def test_deep_dive_becomes_extension_but_different_event_survives(self):
        data = {
            "top_stories": [{
                "headline": "TSMC and ASML bring in High NA EUV tools",
                "body": "The two will deploy $400M-a-unit tools, targeting volume production in 2030.",
                "source_date": "2026-09-09",
            }],
            "ai_industry": [{
                "headline": "ASML expands its German service centre",
                "body": "ASML is investing $2B to add repair capacity.",
                "source_date": "2026-09-09",
            }],
            "daily_deep_dive": [{
                "theme": "High NA EUV supply chain",
                "headline": "TSMC adopts ASML's newest tool",
                "situation": "TSMC and ASML are deploying $400M-a-unit High NA EUV tools, targeting volume production in 2030.",
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
            "headline": "Meta invests $1B in an AI startup",
            "body": "Meta took a $1B stake in the startup.",
            "source_date": "2026-09-09",
        })
        acquisition = ai_processor._event_features({
            "headline": "Meta acquires a $1B data centre",
            "body": "Meta acquired another data centre for $1B.",
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
            "date": "2026-09-09 06:15 TST",
            "top_stories": [{
                "headline": "Nvidia invests in MediaTek to deepen AI chip work",
                "body": "Nvidia invested $3.5B in MediaTek.",
                "tag": "Index book",
                "tag_type": "tech",
                "source": "Reuters",
                "source_date": "2026-09-09",
                "watchlist_refs": [{"ticker": "NVDA", "impact": "Widens its Asian supply-chain footprint."}],
            }],
        }
        rendered = html_template.build_news_html(data)
        self.assertEqual(rendered.count("Nvidia invests in MediaTek to deepen AI chip work"), 1)
        self.assertIn("What it means for the watchlist", rendered)
        self.assertIn("NVDA", rendered)

    def test_fact_news_renders_category_and_evidence_fields(self):
        rendered = html_template.build_news_html({
            "date": "2026-09-09 06:15 TST",
            "industry_developments": [{
                "category": "Semis and supply chain",
                "industry": "AI infrastructure",
                "headline": "Data-centre power orders widen",
                "body": "Vertiv won a $2B order.",
                "evidence": "Vertiv announced a $2B order on Sept 9.",
                "fact_status": "reported",
                "development": "demand",
                "value_chain": "generation to power management to data centre",
                "market_move": "",
                "confirmed_impact": "The company will expand its delivery schedule.",
                "unknowns": "Customer name undisclosed.",
                "source": "Reuters",
                "source_date": "2026-09-09",
                "importance": "high",
            }],
        })
        self.assertIn("Industry developments", rendered)
        self.assertIn("Semis and supply chain", rendered)
        self.assertIn("Evidence", rendered)
        self.assertIn("Value chain", rendered)
        self.assertIn("Confirmed impact", rendered)
        self.assertIn("Unknowns", rendered)


if __name__ == "__main__":
    unittest.main()
