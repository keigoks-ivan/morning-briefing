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
        official=None, full_text_fetch=None):
    if jev is None:
        jev, _ = fx.fake_client()
    return evidence_layer.run_evidence_layer(
        data or fx.briefing_data(), rss or [], fx.watchlist(), news_quality or fx.news_quality(), fx.TODAY,
        data_dir, ledger=ledger if ledger is not None else fx.seed_ledger(),
        holdings_json=fx.holdings() if holdings == "default" else holdings,
        jev=jev, fetch=fx.no_fetch, sec_user_agent=None, official_fetch=official or fx.offline_sources,
        # 離線測試預設不抓全文（不連網）；只有 FullTextTests 會自己傳假的 full_text_fetch
        full_text_fetch=full_text_fetch or fx.no_fulltext)


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

    def test_adding_timing_question_leaves_stale_cache_entries_unused_not_crashed(self):
        """2026-09-23：新增 timing 題目後 request_hash 會變（見 jev_client.request_hash，questions
        本身進雜湊）。模擬舊快取（沒有 timing 這題的答案）：新的請求雜湊對不上，程式要當快取沒命中，
        正常發新請求，不能在 validate_response 或別處炸掉。"""
        def _stub_answers(qs: dict) -> dict:
            out = {}
            for qid, q in qs.items():
                if q["type"] == "score":
                    out[qid] = {"type": "score", "score": 1.0, "confidence": 0.5, "legend": {}, "probabilities": {}}
                elif q["type"] == "noul":
                    out[qid] = {"type": "noul", "noul": 0.5}
                else:
                    out[qid] = {"type": "choice", "choice": next(iter(q["criteria"])), "confidence": 0.9,
                                "probabilities": {}}
            return out

        old_qs = build_questions(0)
        del old_qs["timing"]   # 這一題還沒加進去以前的題目形狀
        stale_hash = request_hash("state", old_qs)
        stale_cache = {stale_hash: {"model": "jev-1.13.0", "answers": _stub_answers(old_qs), "usage": {}}}

        new_qs = build_questions(0)
        self.assertIn("timing", new_qs)
        sent = []

        def transport(body, key):
            req = json.loads(body)
            sent.append(req)
            return {"model": "jev-1.13.0", "answers": _stub_answers(req["questions"]), "usage": {"input_tokens": 20}}

        c = JevClient(api_key="k", cache=stale_cache, transport=transport)
        resp = c.ask("state", new_qs)
        self.assertIsNotNone(resp)             # 沒有因為舊快取形狀不合而炸掉
        self.assertFalse(resp["cached"])       # 沒誤用舊快取
        self.assertIn("timing", resp["answers"])
        self.assertEqual(len(sent), 1)         # 正常發了一次新請求
        self.assertIn(stale_hash, c.cache)     # 舊項目留著沒被清掉，但也不會被之後的請求誤用

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
        # 2026-09-23 排序改版：needs_review 一律不進 top（still 在 main 排序裡，只是被擠到 more）
        self.assertEqual(lanes_of(self.ev, it), ["more"])
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
        # 2026-09-23 排序改版：有派到任何研究的排在沒派到的前面，同層再比重要度分數
        self.assertLessEqual(len(self.ev["top"]), evidence_layer.TOP_SHOWN)
        first = next(x for x in self.ev["items"] if x["id"] == self.ev["top"][0])
        self.assertIn("South Korea", first["headline"])
        top_heads = " ".join(x["headline"] for x in self.ev["items"] if x["id"] in self.ev["top"])
        self.assertNotIn("Copilot", top_heads)
        self.assertNotIn("AMD", top_heads)
        # needs_review（SB Energy）一律不進 top，就算分數不低
        self.assertNotIn("SB Energy", top_heads)

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
                      "not a probability that any share price moves", "Other "):
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
            self.assertIsNone(it["timing"])
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

    def test_korea_bare_country_form_and_short_export_phrase_route(self):
        """2026-09-23 routing gap（live evidence_latest.json）：「Korea chip exports up 259% in
        September on AI memory demand」拿到零派送（沒有總經主題、研究主題、環節），同一天的
        「Korea's chip exports to Malaysia up 5.7x on HBM packaging demand」卻有派送。
        原因：countries.KR 只認 'South Korea'／"Korea's"／'Korean'，光講 'Korea' 配不到國家，
        於是 scoped 的 TRADE_DATA 就地取材式地退回預設 US（見 evidence_ledger.EntityMatcher.subjects）；
        theme_keywords.MemorySupercycle 也只收 'Korean chip exports'／"Korea's chip exports"
        兩種寫法，配不到 'Korea chip exports'。修法（都在 data/evidence_routing.json）：
        countries.KR 加 'Korea chip'；theme_keywords.MemorySupercycle 加 'Korea chip exports'。"""
        from evidence_ledger import EntityMatcher
        from evidence_routing import dd_index, public_holdings_view, route

        routing = load_routing()
        matcher = EntityMatcher(routing)
        headline = "Korea chip exports up 259% in September on AI memory demand"

        self.assertEqual(matcher.subjects(headline), ["TRADE_DATA@KR"])   # 不再誤配成 @US

        routes = route(headline, {}, {}, routing, dd_index([]), public_holdings_view(None), True, [],
                       subjects=matcher.subjects(headline), today=fx.TODAY)
        self.assertIn("MemorySupercycle", [t["key"] for t in routes["themes"]])

        # 既有的寫法（帶 's 的所有格）本來就配得到，這裡再確認沒有被改壞
        headline2 = "Korea's chip exports to Malaysia up 5.7x on HBM packaging demand"
        self.assertEqual(matcher.subjects(headline2), ["TRADE_DATA@KR"])

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


def _j(novelty=("new_fact", 0.95), stage="reported_result", variables=None):
    """規則 A／B 測試用的最小 Jev 判斷（interpret() 的輸出形狀），不連 API。"""
    return {"novelty": {"label": novelty[0], "confidence": novelty[1]},
            "stage": {"label": stage, "confidence": 0.9},
            "attribution": {"label": "named_media_report", "confidence": 0.9},
            "importance": {"score": 2.0, "confidence": 0.8},
            "variables": variables or {}, "parties": {}}


class StaleEventRuleTests(unittest.TestCase):
    """規則 A（2026-09-23）：事件日期本身過舊（>3 天），程式比 Jev 的新舊判斷更可信。
    案例對應 2026-09-23 真實早報的 Fed 升息 bug：event_date 2026-09-16、7 天前的事，
    Jev 卻答 new_fact 0.97，先前紀錄裡明明就有 09-16／09-17 記過同一次升息。"""

    def test_stale_event_with_matching_prior_is_restated(self):
        cand = {"companies": [], "subjects": ["FED"], "headline_figures": ["pct:4"], "figures": ["pct:4"],
                "text": "Fed hikes 25bp to 3.75-4.00%, more tightening signaled",
                "event_date": "2026-09-16", "date_basis": "stated"}
        priors = [{"companies": [], "subjects": ["FED"], "figures": ["pct:3.75", "pct:4"],
                   "event_date": "2026-09-16", "first_seen": "2026-09-16",
                   "sources": [{"source": "Financial Times"}]}]
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.97)), priors, True, "2026-09-23")
        self.assertEqual(final["class"], "known_restatement")
        self.assertEqual(final["lane"], "low")
        notes = " ".join(final["notes"])
        self.assertIn("Event dated 2026-09-16", notes)
        self.assertIn("already recorded on 2026-09-16", notes)
        self.assertIn("Financial Times", notes)

    def test_stale_event_without_matching_prior_needs_review(self):
        cand = {"companies": ["ACME"], "subjects": [], "headline_figures": [], "figures": [],
                "text": "Acme announces new product", "event_date": "2026-09-10", "date_basis": "stated"}
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.9)), [], True, "2026-09-23")
        self.assertEqual(final["class"], "needs_review")
        self.assertIn("Event dated 2026-09-10, 13 days ago; no earlier record found", final["reasons"])

    def test_future_dated_event_is_not_treated_as_stale(self):
        cand = {"companies": ["ACME"], "subjects": [], "headline_figures": [], "figures": [],
                "text": "Acme to hold a summit", "event_date": "2026-09-24", "date_basis": "stated"}
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.9)), [], True, "2026-09-23")
        self.assertEqual(final["class"], "new_fact")
        self.assertEqual(final["reasons"], [])

    def test_published_date_basis_uses_the_same_stale_check_as_stated(self):
        # extract_event_date() 給的 date_basis 沒寫明日期時是 published，規則 A 要照樣適用
        cand = {"companies": ["ACME"], "subjects": [], "headline_figures": ["n:1e+06"], "figures": ["n:1e+06"],
                "text": "Acme reports results", "event_date": "2026-09-14", "date_basis": "published"}
        priors = [{"companies": ["ACME"], "subjects": [], "figures": ["n:1e+06"],
                   "event_date": "2026-09-15", "first_seen": "2026-09-15", "sources": [{"source": "Reuters"}]}]
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.9)), priors, True, "2026-09-23")
        self.assertEqual(final["class"], "known_restatement")


class FigureOverlapEntityTests(unittest.TestCase):
    """規則 B（2026-09-23）：_figure_overlap 只能算「該筆先前紀錄也跟候選共享公司或主題」的數字。
    案例對應 2026-09-23 真實早報：AMD 市值破兆撞到不相干的國庫券回購公告，兩邊都只是剛好有「1 trillion」。"""

    def test_figure_overlap_ignored_without_shared_entity(self):
        cand = {"companies": ["AMD"], "subjects": [], "headline_figures": ["n:1e+12"], "figures": ["n:1e+12"],
                "text": "AMD tops $1 trillion market cap", "event_date": "2026-09-22", "date_basis": "stated"}
        priors = [{"companies": [], "subjects": ["YIELDS@US"], "figures": ["n:1e+12"],
                   "event_date": "2026-09-09", "first_seen": "2026-09-09", "sources": [{"source": "CNBC"}]}]
        overlap = evidence_layer._figure_overlap(cand, priors)
        self.assertEqual(overlap, {"all_seen": False, "seen": []})
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.9)), priors, True, "2026-09-22")
        self.assertEqual(final["class"], "new_fact")

    def test_figure_overlap_still_counts_with_shared_company(self):
        cand = {"companies": ["MSFT"], "subjects": [], "headline_figures": ["n:3e+07"], "figures": ["n:3e+07"],
                "text": "Microsoft 365 Copilot tops 30 million paid seats",
                "event_date": "2026-09-21", "date_basis": "published"}
        priors = [{"companies": ["MSFT"], "subjects": [], "figures": ["n:3e+07"],
                   "event_date": "2026-07-30", "first_seen": "2026-07-30", "sources": [{"source": "DD report"}]}]
        overlap = evidence_layer._figure_overlap(cand, priors)
        self.assertTrue(overlap["all_seen"])
        self.assertEqual(overlap["seen"][0]["figure"], "30 million")

    def test_bare_percent_figure_without_entity_does_not_trigger_followon_review(self):
        # 文中雖然有「additional」，但唯一撞到的數字（4%）是跟不相干主題（OIL）的舊紀錄撞到的，
        # 不該被拿來當「同一件事被追加報導」的證據
        cand = {"companies": [], "subjects": ["FED"], "headline_figures": ["pct:4"], "figures": ["pct:4"],
                "text": "Fed hikes to 4%, with additional tightening flagged",
                "event_date": "2026-09-22", "date_basis": "stated"}
        priors = [{"companies": [], "subjects": ["OIL"], "figures": ["pct:4"],
                   "event_date": "2026-09-15", "first_seen": "2026-09-15", "sources": [{"source": "Reuters"}]}]
        overlap = evidence_layer._figure_overlap(cand, priors)
        self.assertEqual(overlap["seen"], [])
        final = evidence_layer.decide(cand, _j(novelty=("new_fact", 0.9)), priors, True, "2026-09-22")
        self.assertEqual(final["class"], "new_fact")
        self.assertNotIn("calls it additional", " ".join(final["reasons"]))


class RankingTests(unittest.TestCase):
    """規則 C（2026-09-23）：main 區排序、needs_review 不進 top。"""

    @staticmethod
    def _item(cls, block="top_stories", imp=2.0, basis="headline_summary", routes=None):
        return {"classification": {"class": cls}, "block": block, "importance": {"score": imp},
                "evidence_basis": {"code": basis}, "routes": routes or {"dd": [], "holdings": [], "themes": []}}

    def test_needs_review_ranks_after_new_fact_regardless_of_importance(self):
        review = self._item("needs_review", imp=3.0)
        new_fact = self._item("new_fact", imp=1.0)
        self.assertEqual(sorted([review, new_fact], key=evidence_layer._rank_key), [new_fact, review])

    def test_any_research_route_outranks_unrouted_despite_lower_importance(self):
        dd_routed = self._item("new_fact", imp=1.0, routes={"dd": [{"ticker": "TSM"}], "holdings": [], "themes": []})
        theme_only = self._item("new_fact", imp=2.0, routes={"dd": [], "holdings": [], "themes": [{"key": "X"}]})
        macro_only = self._item("new_fact", imp=3.0, routes={"dd": [], "holdings": [], "themes": [], "macro": [{"key": "M"}]})
        nothing = self._item("new_fact", imp=3.0, routes={"dd": [], "holdings": [], "themes": []})
        ordered = sorted([nothing, dd_routed, theme_only, macro_only], key=evidence_layer._rank_key)
        # 有派到研究的一層，層內照重要度；DD 不再壓過主題／總經
        self.assertEqual(ordered, [macro_only, theme_only, dd_routed, nothing])

    def test_needs_review_never_lands_in_top_end_to_end(self):
        # 09-22 案例：SB Energy 是 needs_review、重要度分數也不低，照樣要被擠到 more
        ev, _ = run()
        it = item(ev, "SB Energy")
        self.assertNotIn(it["id"], ev["top"])
        self.assertIn(it["id"], ev["more"])

    def test_timing_does_not_affect_ranking(self):
        # 2026-09-23：timing 是 display-only，兩則除了 timing 以外完全相同的項目排序要一樣
        a = self._item("new_fact", imp=2.0)
        a["timing"] = {"label": "this_quarter", "display": "This quarter", "confidence": 0.9}
        b = self._item("new_fact", imp=2.0)
        b["timing"] = {"label": "beyond_three_years", "display": "More than 3 years out", "confidence": 0.9}
        self.assertEqual(evidence_layer._rank_key(a), evidence_layer._rank_key(b))


class TimingQuestionTests(unittest.TestCase):
    """2026-09-23 新增的窄問題「timing」：主要事實何時實際生效，display-only，供之後校準
    （不進 _rank_key、不進 decide、不進 route，見 evidence_layer.py 組裝 item["timing"] 處的註解）。"""

    def test_timing_present_on_item_and_ledger_record(self):
        # 沒特別覆寫劇本時，FakeJev 對 timing 的預設答案是 ("unclear", 0.5)
        ev, led = run()
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(it["timing"], {"label": "unclear", "display": "Timing unclear", "confidence": 0.5})
        rec = next(r for r in led.records if r["fact_key"] == it["fact_key"])
        self.assertEqual(rec["timing"], "unclear")

    def test_timing_confident_label_shows_mapped_display(self):
        jev, _ = fx.fake_client({"Kaohsiung packaging park": {"timing": ["one_to_three_years", 0.8]}})
        ev, led = run(jev=jev)
        it = item(ev, "Kaohsiung packaging park")
        self.assertEqual(it["timing"], {"label": "one_to_three_years", "display": "1–3 years out", "confidence": 0.8})
        rec = next(r for r in led.records if r["fact_key"] == it["fact_key"])
        self.assertEqual(rec["timing"], "one_to_three_years")

    def test_timing_low_confidence_displays_as_unclear_but_keeps_raw_label(self):
        # 信心 < 0.5：畫面顯示「Timing unclear」，但原始 label／confidence 照實存放供校準用
        jev, _ = fx.fake_client({"AMD market cap tops": {"timing": ["already_in_effect", 0.3]}})
        ev, _ = run(jev=jev)
        it = item(ev, "AMD market cap tops")
        self.assertEqual(it["timing"]["label"], "already_in_effect")
        self.assertEqual(it["timing"]["confidence"], 0.3)
        self.assertEqual(it["timing"]["display"], "Timing unclear")

    def test_timing_does_not_change_classification_or_lane(self):
        # 同一則新聞，timing 給不同答案，classification／lane 都不能變
        base, _ = run()
        base_it = item(base, "Kaohsiung packaging park")
        jev, _ = fx.fake_client({"Kaohsiung packaging park": {"timing": ["beyond_three_years", 0.95]}})
        changed, _ = run(jev=jev)
        changed_it = item(changed, "Kaohsiung packaging park")
        self.assertEqual(base_it["classification"]["class"], changed_it["classification"]["class"])
        self.assertEqual(lanes_of(base, base_it), lanes_of(changed, changed_it))
        self.assertEqual(base["top"], changed["top"])

    def test_timing_shown_next_to_stage_on_news_page(self):
        # 2026-09-23：_ev_item 已經拆成 _ev_top_card（精簡卡片，卡片內的收合 <details> 仍然
        # 是既有的 _ev_row_detail，stage／timing 顯示位置沒變，見 CLAUDE.md）
        jev, _ = fx.fake_client({"Kaohsiung packaging park": {"timing": ["one_to_three_years", 0.8]}})
        ev, _ = run(jev=jev)
        row = html_template._ev_top_card(item(ev, "Kaohsiung packaging park"))
        self.assertIn("stage: Construction started", row)
        self.assertIn("timing: 1–3 years out", row)


_SBE_RSS = [{"title": "Nvidia to buy more SB Energy shares before IPO", "summary": "Nvidia will buy $1.5 billion more.",
            "link": "https://fixture.invalid/sb-energy", "source": "Bloomberg", "published": "2026-09-21 21:40",
            "alternate_sources": ["Reuters"], "watch": ["NVDA"]}]


class FullTextTests(unittest.TestCase):
    """2026-09-23 新增：evidence_fulltext 併進 evidence_layer 之後的行為（basis 升級、
    unconfirmed 說法、article_check 只放安全欄位、全文絕不進輸出檔）。full_text_fetch
    全部用假函式注入，不連網、不呼叫真的 googlenewsdecoder／trafilatura。"""

    def _ft_fetch(self, outcome):
        def fetch(cands):
            return {c["cid"]: outcome for c in cands if "SB Energy" in c["headline"]}
        return fetch

    def test_successful_full_text_upgrades_basis_and_clears_headline_only_note(self):
        outcome = {"status": "ok", "url": "https://www.reuters.com/technology/nvidia-sb-energy",
                  "domain": "reuters.com", "word_count": 900,
                  "excerpt": "Nvidia said it would invest an additional $1.5 billion in SB Energy. " * 20,
                  "quotes": ["Nvidia said it would invest an additional $1.5 billion in SB Energy."],
                  "figures": ["n:1.5e+09"]}
        ev, _ = run(rss=_SBE_RSS, full_text_fetch=self._ft_fetch(outcome))
        it = item(ev, "SB Energy")
        self.assertEqual(it["evidence_basis"]["code"], "full_article")
        self.assertIn("reuters.com", it["evidence_basis"]["display"])
        self.assertEqual(it["article_check"], {"status": "ok", "url": outcome["url"], "domain": "reuters.com",
                                                "word_count": 900, "quotes": outcome["quotes"]})
        self.assertNotIn("excerpt", it["article_check"])
        notes = " ".join(it["unconfirmed"])
        self.assertNotIn("Only the headline and feed summary were read", notes)

    def test_official_match_still_wins_over_full_article(self):
        # official.match 在全文抓取之後另外跑，對到官方來源要留在 primary_document，不能被全文蓋掉
        fed_url = "https://www.federalreserve.gov/feeds/press_all.xml"
        xml = ("<rss><channel><item><title>St. Louis Fed President Musalem: additional interest rate increases likely "
               "necessary to bring inflation back to target</title><link>https://fixture.invalid/fed/musalem</link>"
               "<pubDate>Mon, 21 Sep 2026 14:00:00 GMT</pubDate><description>Remarks on inflation and interest rate "
               "increases.</description></item></channel></rss>")

        def official_fetch(url, timeout=15):
            return (xml, "ok") if url == fed_url else fx.offline_sources(url)

        def ft_fetch(cands):
            outcome = {"status": "ok", "url": "https://www.reuters.com/x", "domain": "reuters.com",
                      "word_count": 500, "excerpt": "text " * 200, "quotes": [], "figures": []}
            return {c["cid"]: outcome for c in cands if "Musalem" in c["headline"]}

        ev, _ = run(official=official_fetch, full_text_fetch=ft_fetch)
        it = item(ev, "Fed's Musalem")
        self.assertEqual(it["evidence_basis"]["code"], "primary_document")
        self.assertIn("Federal Reserve press releases", it["evidence_basis"]["display"])

    def test_paywalled_full_text_names_the_outlet(self):
        outcome = {"status": "paywalled", "url": "https://www.ft.com/content/x", "domain": "ft.com"}
        ev, _ = run(rss=_SBE_RSS, full_text_fetch=self._ft_fetch(outcome))
        it = item(ev, "SB Energy")
        self.assertEqual(it["evidence_basis"]["code"], "headline_summary")   # 沒升級
        self.assertEqual(it["article_check"]["status"], "paywalled")
        notes = " ".join(it["unconfirmed"])
        self.assertIn("paywalled", notes)
        self.assertIn("ft.com", notes)

    def test_failed_full_text_gives_a_reason_not_silence(self):
        outcome = {"status": "failed", "url": "https://fixture.invalid/sb-energy", "domain": "fixture.invalid"}
        ev, _ = run(rss=_SBE_RSS, full_text_fetch=self._ft_fetch(outcome))
        it = item(ev, "SB Energy")
        notes = " ".join(it["unconfirmed"])
        self.assertIn("could not be fetched", notes)

    def test_candidate_not_attempted_keeps_original_headline_only_note(self):
        ev, _ = run(rss=_SBE_RSS, full_text_fetch=fx.no_fulltext)
        it = item(ev, "SB Energy")
        self.assertEqual(it["article_check"], {"status": "not_attempted"})
        notes = " ".join(it["unconfirmed"])
        self.assertIn("Only the headline and feed summary were read", notes)

    def test_full_text_reaches_jev_state_but_never_reaches_any_output_file(self):
        marker = "FULLTEXT_MARKER_" + ("Q" * 40)
        excerpt = (f"{marker} Nvidia invests an additional $1.5 billion in SB Energy for AI power capacity. ") * 40
        outcome = {"status": "ok", "url": "https://www.reuters.com/technology/nvidia-sb-energy",
                  "domain": "reuters.com", "word_count": 900, "excerpt": excerpt[:3000],
                  "quotes": ["Nvidia invests an additional $1.5 billion in SB Energy."], "figures": ["n:1.5e+09"]}

        jev, fake = fx.fake_client()
        orig_transport = jev.transport
        captured = {}

        def spy(body, api_key):
            req = json.loads(body)
            captured[req["state"]["today"]["headline"]] = req["state"]
            return orig_transport(body, api_key)
        jev.transport = spy

        ev, ledger = run(jev=jev, rss=_SBE_RSS, full_text_fetch=self._ft_fetch(outcome))
        it = item(ev, "SB Energy")

        state = next(s for h, s in captured.items() if "SB Energy" in h)
        self.assertIn(marker, state["today"]["full_text"])

        self.assertNotIn(marker, json.dumps(ev, ensure_ascii=False))
        self.assertNotIn("excerpt", it["article_check"])
        with tempfile.TemporaryDirectory() as td:
            written = evidence_layer.save_outputs(ev, ledger, Path(td), fx.TODAY)
            for fn in written:
                content = (Path(td) / fn).read_text(encoding="utf-8")
                self.assertNotIn(marker, content)
                self.assertNotIn("excerpt", content)


class GdeltIntegrationTests(unittest.TestCase):
    """2026-09-23 新增：GDELT 候選（briefing/gdelt_source.py）餵進 run_evidence_layer。
    這裡只測整合（block、quality、渲染），gdelt_source.py 自己的查詢／限流／過濾邏輯見
    test_gdelt_source.py；一律不連網（gdelt_fetch 用假的或直接不傳）。"""

    def test_gdelt_candidates_flow_through_and_render_badge(self):
        import gdelt_source

        def fake_gdelt_fetch(routing, matcher, dd, holdings, dedup_titles, today, max_kept=8, **kw):
            title = "Hanmi Semiconductor wins new HBM packaging order worth $120 million"
            art = {"title": title, "url": "https://example.com/hanmi", "domain": "example.com",
                  "companies": matcher.match(title), "figures": ["n:1.2e+08"], "seendate": "20260922T090000Z"}
            cand = gdelt_source.make_candidate(art, matcher, today)
            return [cand], {"enabled": True, "requests_sent": 1, "ok": 1, "rate_limited": 0,
                            "articles_seen": 1, "kept": 1, "kept_titles": [title]}

        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, gdelt_fetch=fake_gdelt_fetch)

        gdelt_items = [it for it in ev["items"] if it["block"] == "gdelt"]
        self.assertEqual(len(gdelt_items), 1)
        self.assertEqual(gdelt_items[0]["source"], "example.com")
        self.assertEqual(ev["quality"]["gdelt"]["kept"], 1)
        self.assertLessEqual(len(ev["items"]), evidence_layer.MAX_CANDIDATES)

        page = html_template._evidence_section(ev)
        self.assertIn("Found via GDELT", page)

    def test_gdelt_disabled_by_default_when_not_configured(self):
        ev, _ = run()   # run() 不傳 gdelt_fetch
        # slots_used=0：2026-09-24 起 GDELT／sitemap 共用保留名額，_merge_reserved_candidates
        # 一律補這個欄位（見 evidence_layer.py），沒配置時自然是 0。
        self.assertEqual(ev["quality"]["gdelt"], {"enabled": False, "reason": "not configured", "slots_used": 0})
        self.assertEqual([it for it in ev["items"] if it["block"] == "gdelt"], [])

    def test_gdelt_failure_does_not_break_the_briefing(self):
        def boom(*a, **k):
            raise RuntimeError("gdelt down")

        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, gdelt_fetch=boom)
        self.assertFalse(ev["quality"]["gdelt"]["enabled"])
        self.assertIn("error", ev["quality"]["gdelt"])
        self.assertTrue(ev["items"])   # 早報既有候選照樣判斷完成，不被 GDELT 拖垮


class SitemapIntegrationTests(unittest.TestCase):
    """2026-09-24 新增：sitemap 候選（briefing/sitemap_source.py）餵進 run_evidence_layer。
    這裡只測整合（block、quality、渲染、跟 GDELT 共用保留名額），sitemap_source.py 自己的抓取／
    解析／篩選邏輯見 test_sitemap_source.py；一律不連網（sitemap_fetch 用假的或直接不傳）。"""

    def _fake_sitemap_fetch(self, title="TrendForce says DRAM contract prices rise 12% this quarter",
                            **quality_overrides):
        import sitemap_source

        def fetch(routing, matcher, dd, holdings, dedup_titles, today, max_kept=8, **kw):
            item = {"title": title, "url": "https://example.com/trendforce-dram", "source_name": "TrendForce",
                   "companies": matcher.match(title), "figures": ["pct:12"],
                   "published_iso": "2026-09-22T09:00:00Z", "priority": False, "has_figure": True,
                   "title_from_slug": False}
            cand = sitemap_source.make_candidate(item, matcher, today)
            pool = sitemap_source.to_pool_items([item])
            quality = {"enabled": True, "sources": {"TrendForce": {"status": "ok", "items_seen": 1, "items_recent": 1}},
                      "items_seen_total": 1, "items_recent_total": 1, "matched": 1, "kept": 1,
                      "kept_titles": [title], "pool_size": 1}
            quality.update(quality_overrides)
            return ([cand], pool, quality) if max_kept > 0 else ([], pool, quality)
        return fetch

    def test_sitemap_candidates_flow_through_and_render_badge(self):
        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, sitemap_fetch=self._fake_sitemap_fetch())

        sm_items = [it for it in ev["items"] if it["block"] == "sitemap"]
        self.assertEqual(len(sm_items), 1)
        self.assertEqual(sm_items[0]["source"], "TrendForce")
        self.assertEqual(ev["quality"]["sitemap"]["kept"], 1)
        self.assertEqual(ev["quality"]["sitemap"]["slots_used"], 1)
        self.assertLessEqual(len(ev["items"]), evidence_layer.MAX_CANDIDATES)

        page = html_template._evidence_section(ev)
        self.assertIn("Found via sitemap", page)

    def test_sitemap_disabled_by_default_when_not_configured(self):
        ev, _ = run()   # run() 不傳 sitemap_fetch
        self.assertEqual(ev["quality"]["sitemap"], {"enabled": False, "reason": "not configured", "slots_used": 0})
        self.assertEqual([it for it in ev["items"] if it["block"] == "sitemap"], [])

    def test_sitemap_failure_does_not_break_the_briefing(self):
        def boom(*a, **k):
            raise RuntimeError("sitemap down")

        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, sitemap_fetch=boom)
        self.assertFalse(ev["quality"]["sitemap"]["enabled"])
        self.assertIn("error", ev["quality"]["sitemap"])
        self.assertTrue(ev["items"])   # 早報既有候選照樣判斷完成，不被 sitemap 拖垮

    def test_sitemap_pool_reaches_wide_scan_even_with_zero_evidence_slots(self):
        # 早報候選＋GDELT 用光名額（用假的 gdelt_fetch 一次吃光 slots），sitemap 仍要把全部近期
        # 項目餵進早報外掃描（見 CLAUDE.md「Sitemap 候選」段）；用一個含查核點關鍵詞的標題，
        # 讓早報外掃描（ideas_layer._wide_scan）真的比對到、寫進 ev["ideas"]["wide_scan"]。
        import gdelt_source

        # 每則主題不同（不是同一句模板只換一個數字）：news_fetcher._near_same_title 的 Jaccard
        # 門檻是 0.82，個位數編號在 _title_tokens 的正則（[a-z0-9][a-z0-9.\-]{1,}，至少 2 字元）
        # 底下根本不算一個 token，模板式編號標題會被誤判成彼此近似而被去重，讓 gdelt 填不滿
        # slots；每個主題換一組不同公司＋不同環節詞，才能保證 20 則都是各自獨立的候選。
        FILLER_TOPICS = [
            "Broadcom custom silicon backlog", "Nvidia data center GPU shipments",
            "Micron DRAM pricing trends", "Qualcomm smartphone chip demand",
            "Marvell networking silicon orders", "Texas Instruments analog chip supply",
            "Analog Devices industrial sensor sales", "Applied Materials equipment orders",
            "Lam Research etch tool backlog", "KLA inspection tool demand",
            "ASML lithography system orders", "Intel foundry capacity expansion",
            "Samsung memory chip output", "Western Digital storage shipments",
            "Seagate hard drive demand", "Cisco networking equipment orders",
            "Dell server shipments this quarter", "Oracle cloud infrastructure spending",
            "IBM mainframe system orders", "Corning optical fiber demand",
            "Coherent laser component orders", "Teradyne test equipment backlog",
        ]

        def gdelt_fill_all_slots(routing, matcher, dd, holdings, dedup_titles, today, max_kept=8, **kw):
            # priority=True／has_figure=True：跟 _match_score 同一個 tuple 排序鍵最高分，保證每個
            # gdelt filler 都排在 sitemap 那則（has_figure=True 但 priority=False）前面，穩定排序
            # 下 gdelt 會先佔滿全部名額（見 evidence_layer._merge_reserved_candidates 的註解）。
            cands = []
            for i in range(max_kept):
                title = f"{FILLER_TOPICS[i % len(FILLER_TOPICS)]} rises sharply, new industry data shows"
                art = {"title": title, "url": f"https://example.com/filler-{i}", "domain": "example.com",
                      "companies": matcher.match(title), "figures": ["pct:10"], "seendate": "20260922T010000Z",
                      "priority": True, "has_figure": True}
                cands.append(gdelt_source.make_candidate(art, matcher, today))
            return cands, {"enabled": True, "kept": len(cands)}

        sitemap_fetch = self._fake_sitemap_fetch(
            title="SK hynix and Samsung lock in higher HBM4 contract price deals for 2027 supply")
        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, gdelt_fetch=gdelt_fill_all_slots,
            sitemap_fetch=sitemap_fetch, ideas=fx.sample_ideas())

        self.assertEqual([it for it in ev["items"] if it["block"] == "sitemap"], [])   # 沒搶到 evidence 名額
        self.assertEqual(ev["quality"]["sitemap"]["slots_used"], 0)
        self.assertEqual(ev["ideas"]["wide_scan"]["sitemap_pool_size"], 1)


class MergeReservedCandidatesTests(unittest.TestCase):
    """2026-09-24 新增：GDELT／sitemap 候選共用剩下名額的排序與去重
    （evidence_layer._merge_reserved_candidates），不繞經 run_evidence_layer 直接測。"""

    def _cand(self, headline, *, priority=False, has_figure=False, published_at="2026-09-22T01:00:00Z",
             block="gdelt"):
        return {"headline": headline, "block": block, "_match_priority": priority,
               "_match_has_figure": has_figure, "published_at": published_at}

    def test_gdelt_empty_lets_sitemap_fill_all_slots(self):
        sitemap = [self._cand("A", block="sitemap"), self._cand("B", block="sitemap")]
        kept = evidence_layer._merge_reserved_candidates([], sitemap, slots=5)
        self.assertEqual([c["headline"] for c in kept], ["A", "B"])

    def test_sitemap_empty_lets_gdelt_fill_all_slots(self):
        gdelt = [self._cand("A"), self._cand("B")]
        kept = evidence_layer._merge_reserved_candidates(gdelt, [], slots=5)
        self.assertEqual([c["headline"] for c in kept], ["A", "B"])

    def test_higher_match_strength_from_either_source_ranks_first(self):
        gdelt = [self._cand("GDELT plain", priority=False, has_figure=False)]
        sitemap = [self._cand("Sitemap priority with figure", priority=True, has_figure=True, block="sitemap")]
        kept = evidence_layer._merge_reserved_candidates(gdelt, sitemap, slots=5)
        self.assertEqual(kept[0]["headline"], "Sitemap priority with figure")

    def test_result_capped_at_slots(self):
        gdelt = [self._cand(f"G{i}") for i in range(3)]
        sitemap = [self._cand(f"S{i}", block="sitemap") for i in range(3)]
        kept = evidence_layer._merge_reserved_candidates(gdelt, sitemap, slots=2)
        self.assertEqual(len(kept), 2)

    def test_zero_slots_returns_empty(self):
        self.assertEqual(evidence_layer._merge_reserved_candidates([self._cand("A")], [], slots=0), [])

    def test_cross_source_near_duplicate_titles_keep_only_the_higher_ranked_one(self):
        gdelt = [self._cand("TSMC posts 34% revenue growth in August", priority=True, has_figure=True)]
        sitemap = [self._cand("TSMC posts 34 pct revenue growth in August", block="sitemap")]
        kept = evidence_layer._merge_reserved_candidates(gdelt, sitemap, slots=5)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["block"], "gdelt")


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


class BlockPriorityTests(unittest.TestCase):
    """2026-09-23 新增（Task 4）：tech_trends／startup_news 加入 BLOCK_PRIORITY，gdelt 仍最低；
    _card_text 認得 summary 欄位（tech_trends／startup_news 卡是 headline/summary 形狀，沒有
    body）；collect_cards 可以傳自訂 blocks（早報外掃描用）。見 CLAUDE.md。"""

    def test_tech_trends_and_startup_news_in_block_priority(self):
        prio = dict(evidence_layer.BLOCK_PRIORITY)
        self.assertIn("tech_trends", prio)
        self.assertIn("startup_news", prio)
        self.assertEqual(prio["tech_trends"], 0.35)
        self.assertEqual(prio["startup_news"], 0.3)

    def test_gdelt_remains_lowest_priority(self):
        prio = dict(evidence_layer.BLOCK_PRIORITY)
        self.assertEqual(prio["gdelt"], min(prio.values()))

    def test_card_text_falls_back_to_summary(self):
        card = {"headline": "HBM3E contract prices rise", "summary": "Prices rose 20% QoQ on tight supply."}
        text = evidence_layer._card_text(card)
        self.assertIn("HBM3E contract prices rise", text)
        self.assertIn("20% QoQ", text)

    def test_build_candidates_picks_up_tech_trends_card(self):
        from evidence_ledger import EntityMatcher
        routing = evidence_layer.load_routing()
        matcher = EntityMatcher(routing, {})
        data = {"tech_trends": [{"headline": "HBM3E contract prices rise 20% QoQ",
                                 "summary": "CoWoS capacity booked through 2026 as HBM3E demand outstrips supply."}]}
        cands = evidence_layer.build_candidates(data, [], matcher, fx.TODAY)
        self.assertTrue(any(c["block"] == "tech_trends" for c in cands))
        cand = next(c for c in cands if c["block"] == "tech_trends")
        self.assertIn("CoWoS", cand["text"])

    def test_collect_cards_accepts_custom_blocks(self):
        data = {"world_news": [{"headline": "A world news item"}],
               "top_stories": [{"headline": "A top story"}]}
        # default blocks (BLOCK_PRIORITY) does not include world_news
        default_cards = evidence_layer.collect_cards(data)
        self.assertFalse(any(b == "world_news" for b, _p, _c in default_cards))
        extra = evidence_layer.BLOCK_PRIORITY + [("world_news", 0.0)]
        wide_cards = evidence_layer.collect_cards(data, blocks=extra)
        self.assertTrue(any(b == "world_news" for b, _p, _c in wide_cards))


class WideScanCuratedCardsIntegrationTests(unittest.TestCase):
    """2026-09-23 新增（Task 4）：run_evidence_layer 把「沒進候選名額的既有新聞卡」（curated_pool）
    傳給 ideas_layer.run_ideas_step，早報外掃描（_wide_scan）真的看得到，不只看 RSS 池。"""

    def test_frontier_tech_card_reaches_wide_scan_when_not_a_candidate(self):
        data = fx.briefing_data()
        # frontier_tech 刻意不在 BLOCK_PRIORITY 裡（見 WIDE_SCAN_EXTRA_BLOCKS），永遠不會變成
        # 早報候選，只能靠早報外掃描的 curated_pool 才看得到。這則卡命中 sample_ideas() 的
        # cp-b1-two（規則 b：cowos／capacity 兩個不同關鍵詞）。
        data["frontier_tech"] = [{"headline": "CoWoS packaging capacity tightens as advanced substrate demand climbs",
                                  "body": "Foundries say CoWoS capacity remains fully booked into next year."}]
        jev, _fake = fx.fake_client(overrides={"CoWoS packaging capacity": {"idea_verdict": ["supports", 0.8]}})
        ev, _led = evidence_layer.run_evidence_layer(
            data, fx.wide_rss_pool(), fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, ideas=fx.sample_ideas())
        ws = ev["ideas"]["wide_scan"]
        self.assertGreaterEqual(ws.get("curated_pool_size", 0), 1)
        self.assertGreaterEqual(ws["matched_items"], 1)


if __name__ == "__main__":
    unittest.main()
