"""html_template 版面重排測試（2026-09-23 新增，見 CLAUDE.md「市場頁精簡」段）。
只測純渲染函式，不連網、不呼叫付費 API。涵蓋：
- tab 順序與 trends.html 分頁改名
- Deep tech（tech_trends）從 trends.html 搬到 tech.html
- 市場頁移除的區塊（VOLATILITY REGIME／MARKET PULSE 三則跨指標訊號／歷史類比／vs regime）
  不再出現在畫面上
- news 頁 New evidence 精簡卡片＋收合 <details>
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _mod in ("anthropic", "google", "google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

import evidence_fixtures as fx  # noqa: E402  (side effect: puts briefing/ on sys.path)

import html_template  # noqa: E402

REGIME = {
    "call": "Risk-on with a liquidity tailwind",
    "axes": {
        "risk_appetite": {"state": "risk-on"},
        "liquidity": {"state": "easing"},
        "volatility": {"state": "suppressed"},
    },
    "contradicts": ["Credit spreads widened 8bps even as equities rallied"],
    "falsifiers": [
        {"metric": "VIX", "threshold": "closes above 22", "meaning": "would mean the vol regime broke"},
        {"metric": "HYG", "threshold": "falls more than 1% in a day", "meaning": "would mean credit stress"},
        {"metric": "10Y yield", "threshold": "rises above 4.5%", "meaning": "would mean rates repricing"},
    ],
    "for_w52_engine": "No pressure on the gate this week; no action required",
    "confidence": "high",
    "confidence_reason": "All three axes agree and data is complete",
    "review": {
        "yesterday_call": "Risk-on, liquidity easing",
        "verdict": "carried over",
        "falsifier_check": [
            {"metric": "VIX", "threshold": "22", "today_value": "14.2", "hit": False},
            {"metric": "HYG", "threshold": "-1%", "today_value": "+0.2%", "hit": False},
        ],
        "note": "Call unchanged; both falsifiers held.",
    },
}
SENTIMENT_ANALYSIS = {"stage": "Stage 1", "credit_status": "ok"}
MARKET_PULSE = {
    "hidden_risk": "Credit spreads quietly widening while equities ignore it.",
    "hidden_opportunity": "Small caps setting up for a breadth catch-up.",
    "key_level_to_watch": "NDX 20,500",
}
INDEX_FACTOR_READING = {
    "market_structure": "Breadth is widening (RSP/SPY +0.3%, IWM/SPY +0.5%) while megacap tech lags NDX; a genuine rally.",
}
TECH_TRENDS = [{
    "label": "Advanced packaging", "label_type": "arch",
    "headline": "HBM3E contract prices rise on tight supply",
    "summary": "Contract prices for HBM3E rose 20% QoQ as CoWoS capacity stays booked through 2026.",
    "sub_items": [{"key": "Pricing", "val": "+20% QoQ"}],
    "chips": [{"text": "Watch", "type": "watch"}],
    "source": "TrendForce", "source_date": "2026-09-22",
}]


def market_data(regime=None, market_pulse=None, index_factor_reading=None, sentiment_analysis=None) -> dict:
    return {
        "date": "test",
        "regime": regime if regime is not None else REGIME,
        "market_data": {},
        "market_pulse": market_pulse if market_pulse is not None else MARKET_PULSE,
        "index_factor_reading": index_factor_reading if index_factor_reading is not None else INDEX_FACTOR_READING,
        "sentiment_analysis": sentiment_analysis if sentiment_analysis is not None else SENTIMENT_ANALYSIS,
    }


class TabOrderTests(unittest.TestCase):
    def test_tab_order_matches_spec(self):
        keys = [k for k, _label, _href in html_template._TAB_PAGES]
        self.assertEqual(keys, ["index", "screener", "tw_screener", "news", "geo", "tech",
                                "trends", "misc", "startup", "trading"])

    def test_trends_tab_renamed(self):
        labels = {k: label for k, label, _href in html_template._TAB_PAGES}
        self.assertEqual(labels["trends"], "Startups & frontier")


class DeepTechMovedTests(unittest.TestCase):
    def test_tech_html_contains_deep_tech(self):
        data = {"date": "test", "ai_industry": [], "regional_tech": {}, "fintech_crypto": [],
                "tech_trends": TECH_TRENDS}
        page = html_template.build_tech_html(data)
        self.assertIn("Deep tech", page)
        self.assertIn("HBM3E contract prices", page)

    def test_trends_html_no_longer_has_deep_tech(self):
        data = {"date": "test", "frontier_tech": [], "startup_news": [], "weekend_reads": [],
                "smart_money": {}, "tech_trends": TECH_TRENDS}
        page = html_template.build_trends_html(data)
        self.assertNotIn("Deep tech", page)
        self.assertNotIn("HBM3E contract prices", page)


class MarketPageTrimTests(unittest.TestCase):
    """2026-09-23 精簡：市場頁刪掉重複／不再顯示的區塊，見 CLAUDE.md。"""

    def test_removed_blocks_absent(self):
        page = html_template.build_index_html(market_data())
        for gone in ("VOLATILITY REGIME", "MARKET PULSE", "Historical analogue", "New pattern",
                     "vs regime", "Dominant theme", "Reliability:"):
            self.assertNotIn(gone, page)

    def test_todays_call_chips_present(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("TODAY", page)
        self.assertIn("Risk appetite", page)
        self.assertIn("risk-on", page)
        self.assertIn("Liquidity", page)
        self.assertIn("easing", page)
        self.assertIn("Volatility", page)
        self.assertIn("suppressed", page)
        # stage + credit folded into the volatility chip
        self.assertIn("Stage 1", page)
        self.assertIn("credit ok", page)

    def test_single_contradiction_only(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("Biggest contradiction", page)
        self.assertIn("Credit spreads widened", page)
        self.assertNotIn("Confirms", page)

    def test_falsifier_table_has_no_meaning_column(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("What would prove this call wrong", page)
        self.assertIn("closes above 22", page)
        # meaning text must not leak onto the page (still generated in JSON, just not rendered)
        self.assertNotIn("would mean the vol regime broke", page)

    def test_confidence_reason_not_rendered(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("Confidence", page)
        self.assertNotIn("All three axes agree", page)

    def test_yesterdays_call_compact(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("Yesterday", page)
        self.assertIn("carried over", page)
        self.assertIn("Call unchanged", page)

    def test_market_structure_and_hidden_lines(self):
        page = html_template.build_index_html(market_data())
        self.assertIn("Market structure", page)
        self.assertIn("Breadth is widening", page)
        self.assertIn("Hidden risk", page)
        self.assertIn("Hidden opportunity", page)
        self.assertIn("Key level", page)
        self.assertIn("NDX 20,500", page)

    def test_empty_regime_renders_nothing(self):
        self.assertEqual(html_template._regime_block({}, SENTIMENT_ANALYSIS), "")

    def test_email_consistent_with_page(self):
        data = market_data()
        data.update({"daily_summary": "", "alert": "", "top_stories": [], "watchlist_news": [],
                     "industry_developments": [], "daily_deep_dive": [], "world_news": [], "macro": [],
                     "geopolitical": [], "ai_industry": [], "regional_tech": {}, "fintech_crypto": [],
                     "system_status": {}, "tech_trends": [], "frontier_tech": [], "startup_news": [],
                     "weekend_reads": [], "smart_money": {}, "earnings_preview": [],
                     "earnings_deep_analysis": {}, "implied_trends": [], "fun_fact": {},
                     "us_market_recap": {}, "today_events": []})
        email = html_template.build_html(data)
        for gone in ("VOLATILITY REGIME", "MARKET PULSE", "Historical analogue", "vs regime"):
            self.assertNotIn(gone, email)
        self.assertIn("Risk appetite", email)
        self.assertIn("Stage 1", email)


class EvidenceSectionCompactTests(unittest.TestCase):
    """news 頁 New evidence 精簡卡片：只顯示 top（<=5），detail 收進卡片自己的一個 <details>，
    more／low_priority／unjudged 合併成一個 collapsed 區塊。"""

    def _item(self, id_, headline, cls="new_fact", block="top_stories"):
        return {
            "id": id_, "block": block, "kind": "company", "headline": headline,
            "source": "Reuters", "source_date": "2026-09-22", "published_at": "", "event_date": "2026-09-22",
            "date_basis": "published", "period": "", "companies": [], "topics": [],
            "figures": [], "classification": {"class": cls, "display": "New fact", "jev_label": cls,
                                               "confidence": 0.9, "by": "jev", "reasons": [], "notes": []},
            "stage": None, "timing": None, "attribution": None, "importance": {"score": 0.8},
            "variables": {"direct": [], "indirect": []}, "last_known": [], "new_today": "First reported today.",
            "transmission": [], "potential_impact": None, "unconfirmed": [],
            "evidence_basis": {"code": "headline_summary", "display": "Headline only"},
            "primary_check": {"checked": [], "gaps": [], "official": {"matched": [], "nearby": [], "checked": []}},
            "article_check": {"status": "not_attempted"}, "routes": {"dd": [], "themes": [], "macro": [],
                                                                     "clock": False, "regime": [], "pending": [],
                                                                     "holdings": []},
            "sources": [], "also_in": [], "lane": "main" if cls != "known_restatement" else "low",
            "status": {"code": "logged", "display": "Logged"}, "request_hash": None,
        }

    def test_top_cards_compact_and_detail_collapsed(self):
        top_items = [self._item(f"t{i}", f"Top headline {i}") for i in range(3)]
        more_items = [self._item(f"m{i}", f"More headline {i}") for i in range(2)]
        ev = {
            "items": top_items + more_items,
            "top": [it["id"] for it in top_items], "more": [it["id"] for it in more_items],
            "low_priority": [], "unjudged": [], "jev": {"status": "judged", "reason": ""},
            "ledger": {"available": True}, "quality": {},
        }
        page = html_template._evidence_section(ev)
        self.assertIn('id="evidence"', page)
        for it in top_items:
            self.assertIn(it["headline"], page)
        self.assertIn("First reported today.", page)          # one-line why-new visible
        self.assertIn("More detail", page)                    # collapsed per-card detail
        self.assertIn("<details", page)
        self.assertIn("Other 2 items", page)                  # more+low+unjudged merged into one group
        self.assertNotIn("More new items", page)               # old separate group titles gone
        self.assertNotIn("Low priority: known facts", page)

    def test_no_evidence_message_when_nothing(self):
        ev = {"items": [], "top": [], "more": [], "low_priority": [], "unjudged": [],
             "jev": {"status": "judged", "reason": ""}, "ledger": {"available": True}, "quality": {}}
        page = html_template._evidence_section(ev)
        self.assertIn("No new fundamental evidence", page)


if __name__ == "__main__":
    unittest.main()
