"""事件判斷層（evidence_layer）離線測試。不呼叫付費 API、不連網、不寄信。

2026-09-22 早報六個案例的驗收：
- TSMC 白埔：先前已知是規畫，新增的是動工；不能說 CoWoS 產能已增加
- NVIDIA × SB Energy：分清這筆與 8/17 那筆；直接影響是資本投入／電力布局，不是 GPU 訂單
- 韓國晶片出口創高：產業出貨觀察，不能歸因到單一公司的 AI 營收
- SoftBank 發債：AI 融資與信用風險，不是已完成的 GPU 採購
- AMD 市值破兆：估值／行情訊號，不更新需求假設
- Microsoft Copilot 3,000 萬席：7 月已公布，今天重述不算新證據
"""

from __future__ import annotations

import json
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
from evidence_ledger import Ledger, extract_event_date, extract_figures  # noqa: E402
from evidence_questions import VARIABLES, build_questions  # noqa: E402
from evidence_routing import load_routing, public_holdings_view, sec_check  # noqa: E402
from jev_client import JevClient, request_hash, validate_response  # noqa: E402


def run(jev=None, ledger=None, data=None, rss=None, news_quality=None, data_dir=None, holdings="default",
        official=None):
    if jev is None:
        jev, _ = fx.fake_client()
    return evidence_layer.run_evidence_layer(
        data or fx.briefing_data(), rss or [], fx.watchlist(), news_quality or fx.news_quality(), fx.TODAY,
        data_dir, ledger=ledger if ledger is not None else fx.seed_ledger(),
        holdings_json=fx.holdings() if holdings == "default" else holdings,
        jev=jev, fetch=fx.no_fetch, sec_user_agent=None, official_fetch=official or fx.offline_sources)


def item(ev, fragment):
    hits = [it for it in ev["items"] if fragment in it["headline"]]
    assert len(hits) == 1, f"{fragment}: {len(hits)} items"
    return hits[0]


def lanes_of(ev, it):
    return [lane for lane in ("top", "more", "low_priority", "unjudged") if it["id"] in ev[lane]]


def direct_vars(it):
    return {v["var"] for v in it["variables"]["direct"]}


class JevContractTests(unittest.TestCase):
    """題目與回應格式要對上官方文件（docs.typesafe.ai/api，2026-09-22 查證）。"""

    def test_questions_use_only_documented_types_and_shapes(self):
        qs = build_questions(3)
        self.assertEqual({q["type"] for q in qs.values()}, {"choice", "score", "noul"})
        for qid, q in qs.items():
            self.assertIn("instructions", q)
            if q["type"] == "choice":
                self.assertIsInstance(q["criteria"], dict)
                self.assertLessEqual(len(q["criteria"]), 255)
            if q["type"] == "score":
                self.assertTrue(2 <= len(q["criteria"]) <= 10)
        # 一則新聞可以影響多個變數：每個變數一題，不是單一 Choice
        self.assertEqual(sum(1 for k in qs if k.startswith("var_")), len(VARIABLES))
        # 題目不請 Jev 產生公司名或預測股價
        text = json.dumps(qs).lower()
        for banned in ("share price will", "should we buy", "probability that the stock", "name the company"):
            self.assertNotIn(banned, text)

    def test_novelty_offers_the_five_required_outcomes(self):
        crit = build_questions(0)["novelty"]["criteria"]
        self.assertEqual(set(crit), {"new_fact", "known_restatement", "progress_update",
                                     "market_move_only", "insufficient_evidence"})
        stages = set(build_questions(0)["stage"]["criteria"])
        for s in ("plan_or_intent", "filing_or_offering", "agreement_signed", "construction_started",
                  "production_or_launch", "shipped_or_delivered"):
            self.assertIn(s, stages)
        links = set(build_questions(0)["var_capex"]["criteria"])
        self.assertEqual(links, {"direct", "indirect", "none"})

    def test_response_validation_matches_documented_examples(self):
        qs = {"is_urgent": {"type": "noul", "instructions": "x"},
              "department": {"type": "choice", "instructions": "x", "criteria": {"billing": "", "technical": "", "sales": ""}},
              "frustration": {"type": "score", "instructions": "x", "criteria": ["Calm", "Frustrated", "Very angry"]}}
        doc = {"model": "jev-1.13.0", "answers": {
            "is_urgent": {"type": "noul", "noul": 0.95},
            "department": {"type": "choice", "choice": "billing",
                           "probabilities": {"billing": 0.88, "technical": 0.12, "sales": 0.0}, "confidence": 0.81},
            "frustration": {"type": "score", "score": 1.05, "legend": {"0": "Calm", "1": "Frustrated", "2": "Very angry"},
                            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05}, "confidence": 0.92}},
            "usage": {"input_tokens": 318, "output_tokens": 34}}
        self.assertTrue(validate_response(doc, qs))
        bad = json.loads(json.dumps(doc))
        bad["answers"]["department"]["choice"] = "legal"     # 不在選項裡
        self.assertFalse(validate_response(bad, qs))
        del doc["answers"]["is_urgent"]
        self.assertFalse(validate_response(doc, qs))

    def test_client_caches_by_request_and_never_sends_without_key(self):
        qs = {"q": {"type": "noul", "instructions": "x"}}
        sent = []

        def transport(body, key):
            sent.append(json.loads(body))
            return {"model": "jev-1.13.0", "answers": {"q": {"type": "noul", "noul": 0.7}}, "usage": {"input_tokens": 10}}

        cache = {}
        c = JevClient(api_key="SECRET-KEY-123", cache=cache, transport=transport)
        self.assertEqual(c.ask("s", qs)["answers"]["q"]["noul"], 0.7)
        self.assertTrue(c.ask("s", qs)["cached"])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["model"], "jev-1.13.0")
        self.assertEqual(set(sent[0]), {"state", "model", "questions"})
        self.assertIn(request_hash("s", qs), cache)
        self.assertNotIn("SECRET-KEY-123", json.dumps(cache))   # key 不進快取
        self.assertIsNone(JevClient(api_key=None, transport=transport).ask("other", qs))
        self.assertEqual(len(sent), 1)

    def test_client_failure_and_budget_return_none(self):
        qs = {"q": {"type": "noul", "instructions": "x"}}
        c = JevClient(api_key="k", transport=lambda b, k: (_ for _ in ()).throw(RuntimeError("HTTP 500")))
        self.assertIsNone(c.ask("s", qs))
        self.assertEqual(c.stats["failures"], 1)
        c2 = JevClient(api_key="k", max_requests=0, transport=lambda b, k: {})
        self.assertIsNone(c2.ask("s", qs))
        self.assertEqual(c2.stats["skipped_budget"], 1)
        c3 = JevClient(api_key="k", transport=lambda b, k: {"answers": {"q": {"type": "choice"}}})
        self.assertIsNone(c3.ask("s", qs))   # 格式不對：不採用


class LedgerRuleTests(unittest.TestCase):
    def test_figures_normalise_across_languages(self):
        self.assertEqual(extract_figures("突破3000萬"), extract_figures("30 million paid seats"))
        self.assertEqual(extract_figures("投資15億美元"), extract_figures("an additional $1.5 billion"))
        self.assertEqual(extract_figures("$34.12 billion"), extract_figures("$34.1 billion"))
        self.assertEqual(extract_figures("in 2026 on September 1-20"), [])

    def test_event_date_is_computed_by_code(self):
        self.assertEqual(extract_event_date("broke ground on September 21", "2026-09-21")["event_date"], "2026-09-21")
        d = extract_event_date("exports between September 1-20", "2026-09-21")
        self.assertEqual((d["event_date"], d["period"]), ("2026-09-20", "2026-09-01..2026-09-20"))
        self.assertEqual(extract_event_date("meeting on October 28-29", "2026-09-21"), {})

    def test_todays_records_are_never_treated_as_prior(self):
        led = Ledger([{"fact_key": "f1", "first_seen": fx.TODAY, "companies": ["MSFT"], "figures": ["n:3e+07"],
                       "terms": ["copilot"], "tokens": []}])
        self.assertEqual(led.find_prior(["MSFT"], ["n:3e+07"], ["copilot"], set(), fx.TODAY), [])


class Acceptance20260922Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev, cls.ledger = run()

    def test_tsmc_baipu_is_progress_not_capacity(self):
        it = item(self.ev, "Kaohsiung packaging park")
        self.assertEqual(it["classification"]["class"], "progress_update")
        self.assertEqual(it["stage"]["label"], "construction_started")
        self.assertIn("2026-09-02", [p["date"] for p in it["last_known"]])
        self.assertTrue(any("白埔" in p["text"] for p in it["last_known"]))
        self.assertNotIn("supply_capacity", direct_vars(it))
        notes = " ".join(it["unconfirmed"])
        self.assertIn("not added capacity", notes)
        self.assertIn("CoWoS", notes)
        self.assertIn("TSM", [d["ticker"] for d in it["routes"]["dd"]])
        self.assertIn("AdvancedPackaging", [t["key"] for t in it["routes"]["themes"]])

    def test_nvidia_sb_energy_separates_new_from_earlier_investment(self):
        it = item(self.ev, "SB Energy")
        self.assertEqual([p["date"] for p in it["last_known"]], ["2026-08-17"])
        self.assertIn("1.5 billion", it["last_known"][0]["shared_figures"])
        # 同一個金額 8/17 已出現：不自動算新證據，送複核並講清楚要查什麼
        self.assertEqual(it["classification"]["class"], "needs_review")
        self.assertIn("2026-08-17", " ".join(it["classification"]["reasons"]))
        self.assertEqual(lanes_of(self.ev, it), ["top"])
        self.assertIn("capex", direct_vars(it))
        self.assertNotIn("demand", direct_vars(it))
        self.assertIn("does not show more GPU orders", " ".join(it["unconfirmed"]))
        self.assertIn("Data-centre power and energy", [s["label"] for s in it["routes"]["segments"]])

    def test_korea_exports_is_industry_shipments_not_company_revenue(self):
        it = item(self.ev, "South Korea semiconductor exports")
        self.assertEqual(it["classification"]["class"], "new_fact")
        self.assertEqual(direct_vars(it), {"shipments"})
        self.assertEqual(it["routes"]["dd"], [])
        self.assertIn("cannot be attributed to any single company's revenue", " ".join(it["unconfirmed"]))
        self.assertEqual(it.get("period"), "2026-09-01..2026-09-20")

    def test_softbank_bond_is_financing_not_gpu_purchase(self):
        it = item(self.ev, "SoftBank launches")
        self.assertEqual(it["classification"]["class"], "new_fact")
        self.assertEqual(it["stage"]["label"], "filing_or_offering")
        self.assertIn("financing", direct_vars(it))
        self.assertNotIn("capex", direct_vars(it))
        notes = " ".join(it["unconfirmed"])
        self.assertIn("not priced or closed", notes)
        self.assertIn("no completed GPU or compute purchase", notes)
        # OpenAI 是否當事人不確定 → 待審，不猜
        self.assertIn("OPENAI", [p["key"] for p in it["routes"]["pending"]])

    def test_amd_market_cap_is_low_priority_price_signal(self):
        it = item(self.ev, "AMD market cap tops")
        self.assertEqual(it["classification"]["class"], "market_move_only")
        self.assertEqual(lanes_of(self.ev, it), ["low_priority"])
        self.assertIsNone(it["potential_impact"])
        self.assertIn("does not update demand", " ".join(it["unconfirmed"]))
        # 關注清單那張同事件卡併進來，不重複判斷
        self.assertEqual(len([x for x in self.ev["items"] if "AMD" in x["headline"]]), 1)
        self.assertEqual(it["also_in"][0]["block"], "watchlist_news")

    def test_copilot_restatement_is_not_new_evidence(self):
        it = item(self.ev, "Copilot tops 30 million")
        self.assertEqual(it["classification"]["class"], "known_restatement")
        self.assertEqual(lanes_of(self.ev, it), ["low_priority"])
        self.assertEqual(it["last_known"][0]["date"], "2026-07-30")
        self.assertIn("First recorded on 2026-07-30", " ".join(it["unconfirmed"]))
        self.assertEqual(self.ev["ledger"]["restated"], 1)

    def test_main_block_order_and_limits(self):
        self.assertLessEqual(len(self.ev["top"]), evidence_layer.TOP_SHOWN)
        first = next(x for x in self.ev["items"] if x["id"] == self.ev["top"][0])
        self.assertIn("South Korea", first["headline"])
        top_heads = " ".join(x["headline"] for x in self.ev["items"] if x["id"] in self.ev["top"])
        self.assertNotIn("Copilot", top_heads)
        self.assertNotIn("AMD", top_heads)

    def test_potential_impact_lists_industries_without_price_calls(self):
        it = item(self.ev, "Kaohsiung packaging park")
        pi = it["potential_impact"]
        self.assertIn("Semiconductor equipment", [k["segment"] for k in pi["knock_on"]])
        self.assertTrue(all(k["status"] == "Possible, not confirmed" for k in pi["knock_on"]))
        self.assertIn("not of any share price", pi["note"])

    def test_news_page_and_email_rendering(self):
        data = fx.briefing_data()
        data["evidence_layer"] = self.ev
        data["date"] = "test"
        news = html_template.build_news_html(data)
        a = news.find('id="evidence"')
        b = news.find('<div class="section-label">Top stories</div>')
        self.assertTrue(0 < a < b)
        for label in ("Last known", "New today", "Direct impact", "Possible transmission",
                      "Not yet confirmed", "Sources", "classification confidence",
                      "not a probability that any share price moves", "Low priority"):
            self.assertIn(label, news)
        self.assertNotIn("no impact", news.lower())
        email = html_template.build_html(data)
        self.assertIn("news.html#evidence", email)
        self.assertNotIn("<details", email)
        digest = email[email.find(">New evidence<"):email.find("Details, sources")]
        self.assertEqual(digest.count("• "), 3)


class RobustnessTests(unittest.TestCase):
    def test_copilot_blocked_even_if_classifier_says_new(self):
        # 2026-09-22 真 Jev 實測就是這樣答錯（new_fact 0.79）：程式用「標題數字 7/30 已記錄、沒有追加字眼」擋下
        jev, _ = fx.fake_client({"Copilot tops 30 million": {"novelty": ["new_fact", 0.79]}})
        ev, _ = run(jev=jev)
        it = item(ev, "Copilot tops 30 million")
        self.assertEqual(it["classification"]["class"], "known_restatement")
        self.assertEqual(it["classification"]["jev_label"], "new_fact")
        self.assertIn("2026-07-30", " ".join(it["classification"]["notes"]))
        self.assertEqual(lanes_of(ev, it), ["low_priority"])

    def test_same_figure_with_follow_on_wording_goes_to_review_not_restatement(self):
        it = item(run()[0], "SB Energy")
        self.assertEqual(it["classification"]["class"], "needs_review")
        self.assertIn("calls it additional", " ".join(it["classification"]["reasons"]))

    def test_valuation_is_never_listed_as_indirect(self):
        jev, _ = fx.fake_client({"South Korea semiconductor exports": {"vars": {
            "shipments": ["direct", 0.92, "up"], "market_valuation": ["indirect", 0.9, "up"],
            "competition": ["indirect", 0.55, "up"]}}})
        it = item(run(jev=jev)[0], "South Korea semiconductor exports")
        self.assertEqual([v["var"] for v in it["variables"]["indirect"]], [])

    def test_low_confidence_goes_to_review(self):
        jev, _ = fx.fake_client({"South Korea semiconductor exports": {"novelty": ["new_fact", 0.41]}})
        ev, _ = run(jev=jev)
        it = item(ev, "South Korea semiconductor exports")
        self.assertEqual(it["status"]["code"], "needs_review")
        self.assertIn("Low classification confidence", it["status"]["display"])

    def test_missing_key_keeps_briefing_and_marks_unjudged(self):
        ev, _ = run(jev=JevClient(api_key=None, cache={}))
        self.assertEqual(ev["jev"]["status"], "unavailable")
        self.assertTrue(ev["items"])
        for it in ev["items"]:
            self.assertEqual(it["classification"]["class"], "not_judged")
            self.assertIsNone(it["stage"])
            self.assertIsNone(it["classification"]["confidence"])
            self.assertEqual(it["variables"], {"direct": [], "indirect": []})
            self.assertEqual(it["routes"]["dd"], [])            # 沒驗證當事人就不派 DD
        self.assertEqual(ev["top"], [])
        data = fx.briefing_data()
        data["evidence_layer"] = ev
        data["date"] = "test"
        pages = html_template.build_all_pages(data)
        self.assertIn("Not classified today: TYPESAFE_API_KEY not set", pages["news.html"])
        self.assertNotIn("New evidence<", pages["news.html"].split('id="evidence"')[1].split("Top stories")[0])
        self.assertIn("Not classified today", html_template.build_html(data))

    def test_api_failure_marks_unjudged_without_fake_answers(self):
        jev, fake = fx.fake_client(fail=True)
        ev, _ = run(jev=jev)
        self.assertEqual(ev["jev"]["status"], "unavailable")
        self.assertTrue(all(it["classification"]["class"] == "not_judged" for it in ev["items"]))
        self.assertGreater(fake.calls, 0)

    def test_unavailable_ledger_blocks_new_labels(self):
        ev, _ = run(ledger=Ledger([], available=False, origin_note="ledger unavailable (error:ConnectionError)"))
        it = item(ev, "South Korea semiconductor exports")
        self.assertEqual(it["classification"]["class"], "needs_review")
        self.assertIn("could not be loaded", " ".join(it["unconfirmed"]))

    def test_same_day_rerun_is_idempotent_and_does_not_pay_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            jev1, fake1 = fx.fake_client()
            ev1, led1 = run(jev=jev1, data_dir=tmp)
            evidence_layer.save_outputs(ev1, led1, tmp, fx.TODAY)
            n_records = len(led1.records)
            saved = json.loads((tmp / "evidence_ledger.json").read_text())
            led2 = Ledger.from_json(saved, True, "reloaded")
            cache = evidence_layer.load_jev_cache(fx.TODAY, tmp, fetch=fx.no_fetch)
            jev2, fake2 = fx.fake_client(cache=cache)
            ev2, led2 = run(jev=jev2, ledger=led2, data_dir=tmp)
            evidence_layer.save_outputs(ev2, led2, tmp, fx.TODAY)
            self.assertEqual(fake2.calls, 0)                      # 全部命中快取，不重付
            self.assertEqual(len(led2.records), n_records)        # 沒有重複寫入
            self.assertEqual(ev2["ledger"]["inserted"], 0)
            self.assertEqual([i["classification"]["class"] for i in ev1["items"]],
                             [i["classification"]["class"] for i in ev2["items"]])
            self.assertEqual(len(list(tmp.glob("evidence_2026-09-22*.json"))), 1)
            copilot = [r for r in led2.records if r.get("seed_kind") == "dd" and "MSFT" in r["claim"]][0]
            self.assertEqual(copilot["seen_dates"].count(fx.TODAY), 1)

    def test_only_public_holdings_fields_are_used(self):
        ev, _ = run()
        text = json.dumps(ev, ensure_ascii=False)
        self.assertNotIn("final_weight_pct", text)
        self.assertNotIn('"score": 71', text)
        public = public_holdings_view(fx.holdings())
        allowed = set(public["index"]) | set(public["seats"])
        used = {h["position"] for it in ev["items"] for h in it["routes"]["holdings"]}
        self.assertTrue(used)
        self.assertTrue(used <= allowed)
        ev2, _ = run(holdings=None)
        self.assertEqual([h for it in ev2["items"] for h in it["routes"]["holdings"]], [])
        self.assertEqual(ev2["holdings_source"]["kind"], "public system portfolio (/pm/holdings.json)")

    def test_failed_source_is_shown_as_gap_not_as_no_change(self):
        ev, _ = run(news_quality=fx.news_quality(failed_feeds=("Korea Tech (GN)", "DIGITIMES")))
        self.assertEqual(ev["quality"]["feeds_failed"], ["DIGITIMES", "Korea Tech (GN)"])
        self.assertLess(ev["quality"]["feed_success_rate"], 1)
        empty = {k: [] for k in ("top_stories", "industry_developments", "watchlist_news")}
        ev_empty, _ = run(data=empty, news_quality=fx.news_quality(failed_feeds=("Korea Tech (GN)",)))
        page = html_template._evidence_section(ev_empty)
        self.assertIn("Sources not read today", page)
        self.assertIn("Korea Tech (GN)", page)
        self.assertNotIn("no impact", page.lower())

    def test_rss_match_brings_url_and_publish_time(self):
        rss = [{"title": "Nvidia to buy more SB Energy shares before IPO", "summary": "Nvidia will buy $1.5 billion more.",
                "link": "https://fixture.invalid/sb-energy", "source": "Bloomberg", "published": "2026-09-21 21:40",
                "alternate_sources": ["Reuters"], "watch": ["NVDA"]}]
        ev, _ = run(rss=rss)
        it = item(ev, "SB Energy")
        self.assertEqual(it["sources"][0]["url"], "https://fixture.invalid/sb-energy")
        self.assertEqual(it["published_at"], "2026-09-21 21:40")
        self.assertEqual(it["evidence_basis"]["code"], "headline_summary")

    def test_sec_check_reports_filings_without_claiming_a_match(self):
        routing = load_routing()
        skipped = sec_check(["NVDA"], routing, "2026-09-21", fx.TODAY, None, lambda u, a: {})
        self.assertEqual(skipped["checked"][0]["status"], "skipped")
        payload = {"filings": {"recent": {"form": ["8-K", "4"], "filingDate": ["2026-09-19", "2026-09-20"],
                                          "accessionNumber": ["0001045810-26-000100", "x"],
                                          "primaryDocument": ["nvda-8k.htm", "y"]}}}
        ok = sec_check(["NVDA", "SOFTBANK"], routing, "2026-09-21", fx.TODAY, "test-agent", lambda u, a: payload)
        self.assertEqual(ok["checked"][0]["filings"][0]["form"], "8-K")
        self.assertIn("000104581026000100", ok["checked"][0]["filings"][0]["url"])
        self.assertEqual(ok["gaps"][0]["company"], "SOFTBANK")
        failed = sec_check(["NVDA"], routing, "2026-09-21", fx.TODAY, "ua",
                           lambda u, a: (_ for _ in ()).throw(ConnectionError()))
        self.assertEqual(failed["checked"][0]["status"], "failed")


class MacroAndCoverageTests(unittest.TestCase):
    """2026-09-22 追加：總經新聞、非半導體公司、政策新聞、一手來源、舊報告標記。"""

    @classmethod
    def setUpClass(cls):
        cls.ev, cls.ledger = run()

    def test_fed_official_comment_routes_to_macro_reports_not_a_decision(self):
        it = item(self.ev, "Fed's Musalem")
        self.assertEqual(it["kind"], "macro")
        self.assertEqual([x["key"] for x in it["topics"]], ["FED"])
        self.assertEqual(it["stage"]["label"], "official_comment")
        self.assertIn("policy_rate", direct_vars(it))
        slugs = {m["slug"]: m for m in it["routes"]["macro"]}
        self.assertIn("USEconomy", slugs)
        self.assertIn("聯邦基金利率／SEP", slugs["USEconomy"]["kill_metrics"])
        self.assertEqual(it["routes"]["regime"], ["liquidity"])
        self.assertEqual({h["position"] for h in it["routes"]["holdings"]}, {"QQQ", "SMH"})
        self.assertTrue(all(h["via"] == "country exposure (US)" for h in it["routes"]["holdings"]))
        notes = " ".join(it["unconfirmed"])
        self.assertIn("not a policy decision", notes)
        self.assertIn("Market-implied odds", notes)
        # 9/16 那次升息是先前已知（總經主題也能找到舊紀錄）
        self.assertIn("2026-09-16", [p["date"] for p in it["last_known"]])
        self.assertEqual(it["status"]["code"], "routed")

    def test_trade_talks_are_not_an_agreement(self):
        it = item(self.ev, "Bessent and He Lifeng")
        self.assertEqual(it["kind"], "mixed")
        self.assertIn("TARIFFS", [x["key"] for x in it["topics"]])
        self.assertEqual(it["routes"]["dd"], [])      # 晚宴出席的公司不是當事人
        self.assertIn("not an agreement in force", " ".join(it["unconfirmed"]))
        self.assertEqual({m["slug"] for m in it["routes"]["macro"]}, {"USEconomy", "ChinaEconomy"})

    def test_uncovered_company_is_logged_honestly(self):
        it = item(self.ev, "Paramount settles")
        self.assertEqual(it["routes"]["dd"], [])
        self.assertEqual(it["routes"]["themes"], [])
        self.assertEqual(it["status"]["display"], "Logged; no research link")

    def test_policy_news_routes_by_specific_phrase(self):
        it = item(self.ev, "Texas governor halts")
        self.assertEqual([t["key"] for t in it["routes"]["themes"]], ["AIDataCenter"])
        self.assertIn("effective date and scope are not confirmed", " ".join(it["unconfirmed"]))

    def test_korea_partial_month_and_revision_notes(self):
        notes = " ".join(item(self.ev, "South Korea semiconductor exports")["unconfirmed"])
        self.assertIn("Partial-month data", notes)
        self.assertIn("often revised", notes)

    def test_non_semis_names_come_from_research_themes(self):
        from evidence_ledger import EntityMatcher
        m = EntityMatcher(load_routing())
        self.assertEqual(m.match("Delta Air Lines raised guidance; the delta variant spread"), ["DAL"])
        self.assertEqual(m.match("Visa and Mastercard settle an interchange suit"), ["V", "MA"])
        self.assertEqual(m.match("new H-1B visa rules"), [])
        self.assertEqual(m.subjects("China's CPI rose while U.S. retail sales fell"), ["CPI@CN", "RETAIL_SALES@US"])
        self.assertNotIn("ASML", m.match("EUV tools are scarce"))

    def test_reports_show_age_and_new_facts_since(self):
        wl = [dict(w) for w in fx.watchlist()]
        for w in wl:
            if w["ticker"] == "TSM":
                w["dd_date"] = "2026-03-01"
        led = fx.seed_ledger()
        led.records.append({"fact_key": "fact_after_dd", "origin": "briefing", "first_seen": "2026-06-01",
                            "novelty": "new_fact", "companies": ["TSM"], "parties": ["TSM"], "themes": ["AdvancedPackaging"]})
        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(fx.briefing_data(), [], wl, fx.news_quality(), fx.TODAY, None,
                                                  ledger=led, holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
                                                  sec_user_agent=None, official_fetch=fx.offline_sources)
        dd = item(ev, "Kaohsiung packaging park")["routes"]["dd"][0]
        self.assertTrue(dd["stale"])
        self.assertGreaterEqual(dd["age_days"], 200)
        self.assertEqual(dd["new_since"], 1)
        page = html_template._evidence_section(ev)
        self.assertIn("older report", page)
        self.assertIn("+1 new since", page)

    def test_official_release_upgrades_evidence_when_it_matches(self):
        fed_url = "https://www.federalreserve.gov/feeds/press_all.xml"
        xml = ("<rss><channel><item><title>St. Louis Fed President Musalem: additional interest rate increases likely "
               "necessary to bring inflation back to target</title><link>https://fixture.invalid/fed/musalem</link>"
               "<pubDate>Mon, 21 Sep 2026 14:00:00 GMT</pubDate><description>Remarks on inflation and interest rate "
               "increases.</description></item></channel></rss>")

        def fetch(url, timeout=15):
            return (xml, "ok") if url == fed_url else fx.offline_sources(url)

        ev, _ = run(official=fetch)
        it = item(ev, "Fed's Musalem")
        self.assertEqual(it["evidence_basis"]["code"], "primary_document")
        self.assertIn("Federal Reserve press releases", it["evidence_basis"]["display"])
        self.assertEqual(it["primary_check"]["official"]["matched"][0]["url"], "https://fixture.invalid/fed/musalem")

    def test_same_company_filing_is_nearby_not_matched(self):
        rows = [{"發言日期": "1150921", "出表日期": "1150922", "公司代號": "2330", "公司名稱": "台積電",
                 "主旨 ": "公告本公司董事會決議事項", "說明": "董事會通過資本預算", "事實發生日": "1150921"}]

        def fetch(url, timeout=15):
            if url.endswith("t187ap04_L"):
                return json.dumps(rows, ensure_ascii=False), "ok"
            return fx.offline_sources(url)

        it = item(run(official=fetch)[0], "Kaohsiung packaging park")
        off = it["primary_check"]["official"]
        self.assertEqual(off["matched"], [])
        self.assertEqual(off["nearby"][0]["why"], "same company filing near the date")
        self.assertNotEqual(it["evidence_basis"]["code"], "primary_document")

    def test_failed_official_sources_are_gaps_not_silence(self):
        ev, _ = run(official=fx.all_sources_down)
        it = item(ev, "Fed's Musalem")
        gaps = [g for g in it["primary_check"]["gaps"] if g["reason"].startswith("not read today")]
        self.assertTrue(gaps)
        self.assertIn("Federal Reserve press releases", [g["source"] for g in gaps])
        self.assertTrue(ev["quality"]["official_sources"]["failed"])
        page = html_template._evidence_section(ev)
        self.assertIn("Official sources not read today", page)
        self.assertNotIn("no impact", page.lower())


class FeedStatusTests(unittest.TestCase):
    def test_feed_errors_are_recorded_per_source(self):
        import news_fetcher
        feeds = [("Good feed", "https://a.invalid", 5, 24), ("Broken feed", "https://b.invalid", 5, 24)]

        def parse(url):
            if "a.invalid" in url:
                return types.SimpleNamespace(entries=[{"title": "Story", "link": "https://www.reuters.com/x",
                                                       "summary": "s"}], bozo=False)
            return types.SimpleNamespace(entries=[], bozo=True, bozo_exception=ConnectionError("down"))

        with mock.patch.object(news_fetcher, "RSS_FEEDS", feeds), \
                mock.patch.object(news_fetcher.feedparser, "parse", side_effect=parse):
            news_fetcher.fetch_rss_news()
        q = news_fetcher.get_last_rss_quality()
        self.assertEqual(q["feeds"]["Broken feed"]["status"], "error")
        self.assertEqual(q["feeds"]["Good feed"]["status"], "ok")
        self.assertEqual(q["feed_success_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
