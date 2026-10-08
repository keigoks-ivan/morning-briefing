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


class NewsBySectorTests(unittest.TestCase):
    """news 頁依產業分區（2026-10-08，見 CLAUDE.md「news 頁依產業分區」）。"""

    @staticmethod
    def _it(headline, sector=None, importance="medium", **kw):
        d = {"headline": headline, "body": f"Body of {headline}.", "source": "Reuters",
             "source_date": "2026-10-08", "importance": importance, **kw}
        if sector:
            d["sector"] = sector
        return d

    def _data(self):
        it = self._it
        return {
            "date": "2026-10-08",
            "top_stories": [it(f"Top story {n}", "AI and semiconductors") for n in range(1, 8)],
            "industry_developments": [
                it("Chipmaker raises capex", None, industry="Semiconductors", category="US earnings",
                   evidence="Capex up 20%", unknowns="Timing"),
                it("Utility signs nuclear deal", None, industry="Energy and logistics")],
            "macro": [it("Fed holds rates", None), it("CPI cools", None, importance="high")],
            "geopolitical": [it("New tariffs announced", None)],
            "regional_tech": {"us": [it("US software merger", "Software and internet")],
                              "china": [it("China chip subsidy", "Policy and regulation")],
                              "taiwan": [it("Taiwan packaging plant", "AI and semiconductors")],
                              "asean": [it("Vietnam data centre", "AI and semiconductors")]},
        }

    def test_normalize_sector_inference(self):
        from sector import normalize_sector
        it = self._it
        self.assertEqual(normalize_sector("industry_developments", it("x", industry="Semiconductors")), "AI and semiconductors")
        self.assertEqual(normalize_sector("industry_developments", it("x", industry="Enterprise software and security")), "Software and internet")
        self.assertEqual(normalize_sector("industry_developments", it("Port strike", industry="Energy and logistics")),
                         "Industrials, defense and logistics")
        self.assertEqual(normalize_sector("industry_developments", it("Grid operator buys LNG cargoes", industry="Energy and logistics")),
                         "Energy and power")
        self.assertEqual(normalize_sector("industry_developments", it("x", industry="Fintech")), "Finance and macro")
        self.assertEqual(normalize_sector("macro", it("anything")), "Finance and macro")
        self.assertEqual(normalize_sector("fintech_crypto", it("anything")), "Finance and macro")
        self.assertEqual(normalize_sector("geopolitical", it("anything")), "Policy and regulation")
        self.assertEqual(normalize_sector("ai_industry", it("anything")), "AI and semiconductors")
        self.assertEqual(normalize_sector("world_news", it("FDA approves new drug")), "Healthcare and biotech")
        self.assertEqual(normalize_sector("world_news", it("Local festival draws crowds")), "Other")
        # 合法值（含 & 寫法）保留；不合法值改走推定
        self.assertEqual(normalize_sector("macro", it("x", "Energy and power")), "Energy and power")
        self.assertEqual(normalize_sector("macro", it("x", "Healthcare & biotech")), "Healthcare and biotech")
        self.assertEqual(normalize_sector("macro", it("x", "Cryptids")), "Finance and macro")

    def test_news_page_grouping(self):
        page = html_template.build_news_html(self._data())
        top = page.split("By sector")[0]
        rest = page.split("By sector", 1)[1]
        for n in range(1, 6):
            self.assertIn(f"Top story {n}", top)
            self.assertEqual(page.count(f"Top story {n}<"), 1)     # 只出現一次，不在 sector 區重複
        for n in (6, 7):
            self.assertIn(f"Top story {n}", rest)
            self.assertNotIn(f"Top story {n}", top)
        for slug in ("ai-semis", "energy", "finance-macro", "policy", "software"):
            self.assertIn(f'id="sector-{slug}"', page)
        for slug in ("healthcare", "consumer", "industrials", "other"):   # 空 sector 不顯示
            self.assertNotIn(f'id="sector-{slug}"', page)
        # 固定順序
        self.assertLess(page.index('id="sector-ai-semis"'), page.index('id="sector-energy"'))
        self.assertLess(page.index('id="sector-energy"'), page.index('id="sector-software"'))
        self.assertLess(page.index('id="sector-software"'), page.index('id="sector-finance-macro"'))
        self.assertLess(page.index('id="sector-finance-macro"'), page.index('id="sector-policy"'))
        # 組內 high 先
        fm = page[page.index('id="sector-finance-macro"'):page.index('id="sector-policy"')]
        self.assertLess(fm.index("CPI cools"), fm.index("Fed holds rates"))
        # region：us 在 sector 區，其他四組在 region 區
        self.assertIn("US software merger", rest.split("By region")[0])
        region = rest.split("By region", 1)[1]
        for slug in ("china", "jp-kr-tw", "india-em"):
            self.assertIn(f'id="region-{slug}"', page)
        self.assertNotIn('id="region-europe"', page)
        self.assertIn("China chip subsidy", region)
        self.assertIn("Vietnam data centre", region)
        self.assertNotIn("US software merger", region)
        self.assertIn("More detail", page)                         # industry_developments 多出欄位收合

    def test_email_digest_max_two_and_anchors(self):
        data = self._data()
        data["regional_tech"]["china"] = [self._it(f"China item {n}") for n in range(4)]
        digest = html_template._news_email_sector_digest(data)
        import re
        for block in digest.split('<div style="padding:8px 0;border-bottom')[1:]:
            self.assertLessEqual(block.count("news.html#"), 2)
        self.assertIn("news.html#sector-ai-semis", digest)
        self.assertIn("news.html#region-china", digest)
        self.assertNotIn("news.html#sector-healthcare", digest)
        self.assertRegex(digest, r"All \d+ stories by sector")
        self.assertNotIn("flex", digest)
        # build_html 用兩段取代舊的八段
        full = html_template.build_html(data)
        self.assertIn("Today&#39;s most important", full)
        self.assertIn("More by sector", full)
        self.assertNotIn("Fed holds rates</div>", full.split("More by sector")[0])

    def test_deep_card_why_it_matters_fallback(self):
        card = html_template._deep_card
        base = self._it("Headline A", "Finance and macro")
        c1 = card({**base, "why_it_matters": "WHY-1", "confirmed_impact": "CONF-1", "evidence": "EVID-1"}, "macro", {})
        self.assertIn("WHY-1", c1)
        self.assertNotIn("CONF-1", c1)
        c2 = card({**base, "confirmed_impact": "CONF-1", "evidence": "EVID-1"}, "macro", {})
        self.assertIn("CONF-1", c2)
        self.assertNotIn("EVID-1", c2)
        c3 = card({**base, "evidence": "EVID-1"}, "macro", {})
        self.assertIn("EVID-1", c3)
        c4 = card(base, "macro", {})
        self.assertNotIn("Why it matters", c4)
        self.assertIn("Touches", c4)
        self.assertIn("no linked research", c4)
        self.assertIn("headline and summary only", c4)

    def test_deep_card_touches_and_full_text_flag(self):
        item = self._it("Headline B", "AI and semiconductors",
                        watchlist_refs=[{"ticker": "2330.TW", "impact": "Capex raises orders"}])
        ev_item = {"block": "top_stories", "headline": "Headline B", "also_in": [],
                   "routes": {"dd": [{"ticker": "NVDA", "path": "/dd/nvda.html"}],
                              "themes": [{"key": "AI capex", "path": "/id/ai.html"}], "macro": []},
                   "article_check": {"status": "ok"}, "ideas": []}
        idx = html_template._ev_card_index({"items": [ev_item]})
        out = html_template._deep_card(item, "top_stories", idx, {})
        self.assertIn("DD NVDA", out)
        self.assertIn("/id/ai.html", out)
        self.assertIn("2330.TW", out)
        self.assertIn("full text read", out)
        self.assertNotIn("no linked research", out)


if __name__ == "__main__":
    unittest.main()


class ParseJsonControlCharTests(unittest.TestCase):
    def test_literal_newline_and_tab_inside_string_are_accepted(self):
        import ai_processor
        raw = '{"top_stories": [{"headline": "Yields hit\\n19-year high", "body": "a\\tb"}]}'
        raw = raw.replace("\\n", "\n").replace("\\t", "\t")
        out = ai_processor._parse_json(raw)
        self.assertEqual(out["top_stories"][0]["headline"], "Yields hit\n19-year high")
