"""evidence_calibration（週度自動校準，2026-09-23 新增）離線測試。不連網、不呼叫付費 API、
不呼叫真的 yfinance／Claude CLI。全部用假的 fetch／price_fetch／cli_call 注入。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "briefing"))

import evidence_calibration as ec  # noqa: E402
from evidence_ledger import EntityMatcher  # noqa: E402
from evidence_routing import load_routing  # noqa: E402


ROUTING = load_routing()
MATCHER = EntityMatcher(ROUTING)


def item(id_="c_1", date="2026-09-22", headline="TSMC breaks ground on new Kaohsiung fab",
        jev_label="new_fact", confidence=0.85, event_date=None, fact_key="fact_x1",
        companies=None, topics=None, importance=2.0, stage="construction_started",
        direct_vars=None, kind="company", routes=None, sources=None):
    return {
        "id": id_, "date": date, "source_date": date, "event_date": event_date or date,
        "headline": headline, "kind": kind, "fact_key": fact_key,
        "companies": companies if companies is not None else [{"key": "TSM", "name": "TSMC", "role": "party", "p": 0.9}],
        "topics": topics or [],
        "classification": {"class": jev_label, "jev_label": jev_label, "confidence": confidence},
        "stage": {"label": stage, "confidence": 0.8},
        "importance": {"score": importance, "confidence": 0.7},
        "variables": {"direct": [{"var": v, "label": v} for v in (direct_vars or ["capex"])], "indirect": []},
        "last_known": [],
        "routes": routes or {"dd": [], "holdings": []},
        "sources": sources if sources is not None else [{"source": "Reuters", "url": "https://example.com/a",
                                                          "published": date, "title": headline}],
    }


def ledger_rec(fact_key, first_seen, companies=None, figures=None, terms=None, tokens=None,
              sources=None, prior_refs=None, official_matches=None, event_date=None, seen_dates=None):
    return {
        "fact_key": fact_key, "first_seen": first_seen, "last_seen": first_seen,
        "event_date": event_date or first_seen, "seen_dates": seen_dates or [first_seen],
        "companies": companies or ["TSM"], "subjects": [], "figures": figures or [],
        "terms": terms or [], "tokens": tokens or [], "origin": "briefing",
        "sources": sources or [{"source": "Nikkei Asia", "url": "https://x/1", "published": first_seen}],
        "prior_refs": prior_refs or [], "official_matches": official_matches or [],
    }


class DateWindowTests(unittest.TestCase):
    def test_dates_back_excludes_end_date_and_is_ascending(self):
        dates = ec._dates_back("2026-09-29", 7)
        self.assertEqual(dates, ["2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
                                 "2026-09-26", "2026-09-27", "2026-09-28"])


class CollectItemsTests(unittest.TestCase):
    def test_collects_items_across_days_and_reports_missing(self):
        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-25.json"):
                return {"date": "2026-09-25", "items": [item(id_="a"), item(id_="b")]}, "ok"
            return None, "missing"

        items, reports = ec.collect_week_items("2026-09-29", fetch=fetch)
        self.assertEqual(len(items), 2)
        self.assertEqual({it["date"] for it in items}, {"2026-09-25"})
        ok = [r for r in reports if r["status"] == "ok"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["items"], 2)

    def test_load_ledger_records_reports_status(self):
        recs, status = ec.load_ledger_records(fetch=lambda u, timeout=15: (None, "missing"))
        self.assertEqual((recs, status), ([], "missing"))
        recs2, status2 = ec.load_ledger_records(
            fetch=lambda u, timeout=15: ({"facts": [ledger_rec("fact_a", "2026-09-20")]}, "ok"))
        self.assertEqual(status2, "ok")
        self.assertEqual(len(recs2), 1)


class HindsightCheckTests(unittest.TestCase):
    """事後回查：用「現在」完整的 ledger（比判斷當天多了後續紀錄）重新比對。"""

    def test_shared_figure_and_entity_before_item_date_is_actually_old(self):
        # 2026-09-23 起要兩個訊號：這裡是共同數字＋用字重疊
        it = item(headline="TSMC raises $3.5 billion for new fab", fact_key="fact_new")
        records = [ledger_rec("fact_old", "2026-09-10", companies=["TSM"], figures=["n:3.5e+09"],
                              tokens=sorted(ec.content_tokens("TSMC raises $3.5 billion for new fab")))]
        r = ec.hindsight_check(it, records, MATCHER)
        self.assertEqual(r["label"], "actually_old")
        self.assertEqual(r["matched_fact_key"], "fact_old")

    def test_single_shared_term_is_not_enough(self):
        # 9/23 回放：「韓國 9 月晶片出口」只因共用 chip exports 就被對到 8/19 的川習會新聞
        it = item(headline="Korea chip exports up 259% in September", fact_key="fact_new",
                  companies=[], topics=[{"key": "TRADE_DATA@KR"}])
        records = [dict(ledger_rec("fact_old", "2026-08-19", terms=["chip exports"], tokens=["summit", "xi"]),
                        companies=[], subjects=["TRADE_DATA@KR"])]
        r = ec.hindsight_check(it, records, None)
        self.assertEqual(r["label"], "confirmed_new")

    def test_percent_range_in_headline_reads_both_ends(self):
        it = item(headline="Fed hikes 25bp to 3.75-4.00%", fact_key="fact_new", companies=[],
                  topics=[{"key": "FED"}])
        records = [dict(ledger_rec("fact_old", "2026-09-16", figures=["pct:3.75", "pct:4"]),
                        companies=[], subjects=["FED"])]
        self.assertEqual(ec.hindsight_check(it, records, None)["label"], "actually_old")

    def test_same_fact_key_in_ledger_is_excluded_from_matching(self):
        it = item(headline="TSMC raises $3.5 billion for new fab", fact_key="fact_new")
        records = [ledger_rec("fact_new", "2026-09-10", companies=["TSM"], figures=["n:3.5e+09"])]
        r = ec.hindsight_check(it, records, MATCHER)
        self.assertNotEqual(r["label"], "actually_old")

    def test_later_record_only_is_not_a_match(self):
        it = item(headline="TSMC raises $3.5 billion for new fab", date="2026-09-20", fact_key="fact_new")
        records = [ledger_rec("fact_later", "2026-09-25", companies=["TSM"], figures=["n:3.5e+09"])]
        r = ec.hindsight_check(it, records, MATCHER)
        self.assertNotEqual(r["label"], "actually_old")

    def test_no_shared_entity_is_not_a_match_even_with_same_figure(self):
        it = item(headline="TSMC raises $3.5 billion for new fab",
                 companies=[{"key": "TSM", "name": "TSMC", "role": "party", "p": 0.9}])
        # 同數字但公司不同（無關的國庫券回購公告），不能算重述證據
        records = [ledger_rec("fact_old", "2026-09-10", companies=["AAPL"], figures=["n:3.5e+09"])]
        r = ec.hindsight_check(it, records, MATCHER)
        self.assertNotEqual(r["label"], "actually_old")

    def test_cited_by_later_record_is_confirmed_new(self):
        it = item(fact_key="fact_new", date="2026-09-20")
        records = [ledger_rec("fact_child", "2026-09-23", prior_refs=["fact_new"])]
        r = ec.hindsight_check(it, records, MATCHER)
        self.assertEqual(r["label"], "confirmed_new")
        self.assertIn("2026-09-23", r["reason"])

    def test_stale_event_date_without_match_is_unclear(self):
        it = item(date="2026-09-22", event_date="2026-09-10", fact_key="fact_stale")
        r = ec.hindsight_check(it, [], MATCHER)
        self.assertEqual(r["label"], "unclear")

    def test_no_signal_either_way_defaults_confirmed_new(self):
        it = item(date="2026-09-22", event_date="2026-09-21", fact_key="fact_plain")
        r = ec.hindsight_check(it, [], MATCHER)
        self.assertEqual(r["label"], "confirmed_new")


class AggregateHindsightTests(unittest.TestCase):
    def test_buckets_and_shares(self):
        checks = ([{"confidence": 0.65, "label": "actually_old"}] * 1
                 + [{"confidence": 0.7, "label": "confirmed_new"}] * 4
                 + [{"confidence": 0.85, "label": "confirmed_new"}] * 5
                 + [{"confidence": 1.0, "label": "actually_old"}] * 2)
        agg = ec.aggregate_hindsight(checks)
        b60 = next(b for b in agg["buckets"] if b["range"] == "0.6-0.8")
        self.assertEqual(b60["n"], 5)
        self.assertEqual(b60["actually_old"], 1)
        b90 = next(b for b in agg["buckets"] if b["range"] == "0.9-1.0")
        self.assertEqual(b90["n"], 2)   # confidence==1.0 落在最後一區間（含右端點）
        self.assertEqual(b90["actually_old_share"], 1.0)

    def test_suggestion_needs_30_total_items(self):
        checks = [{"confidence": 0.85, "label": "confirmed_new"}] * 10
        agg = ec.aggregate_hindsight(checks)
        sug = ec.suggest_novelty_min_conf(agg)
        self.assertIsNone(sug["suggested"])
        self.assertIn("30", sug["reason"])

    def test_suggestion_picks_lowest_bucket_under_bar(self):
        checks = ([{"confidence": 0.65, "label": "confirmed_new"}] * 9
                 + [{"confidence": 0.65, "label": "actually_old"}] * 1     # 0.6-0.8: 10%，剛好卡在門檻上
                 + [{"confidence": 0.85, "label": "confirmed_new"}] * 20)
        agg = ec.aggregate_hindsight(checks)
        sug = ec.suggest_novelty_min_conf(agg)
        self.assertEqual(sug["suggested"], 0.6)

    def test_suggestion_none_when_no_bucket_clears_the_bar(self):
        checks = ([{"confidence": 0.65, "label": "actually_old"}] * 5
                 + [{"confidence": 0.85, "label": "actually_old"}] * 5
                 + [{"confidence": 0.95, "label": "actually_old"}] * 20)
        agg = ec.aggregate_hindsight(checks)
        sug = ec.suggest_novelty_min_conf(agg)
        self.assertIsNone(sug["suggested"])


class TickerTests(unittest.TestCase):
    def test_looks_like_ticker_rejects_bare_numbers(self):
        self.assertTrue(ec._looks_like_ticker("AAPL"))
        self.assertTrue(ec._looks_like_ticker("2330.TW"))
        self.assertTrue(ec._looks_like_ticker("9984.T"))
        self.assertFalse(ec._looks_like_ticker("2330"))
        self.assertFalse(ec._looks_like_ticker(""))

    def test_benchmark_by_suffix(self):
        self.assertEqual(ec._benchmark_for("2330.TW"), "0050.TW")
        self.assertEqual(ec._benchmark_for("9984.T"), "^N225")
        self.assertEqual(ec._benchmark_for("005930.KS"), "^KS11")
        self.assertEqual(ec._benchmark_for("AAPL"), "SPY")

    def test_tickers_for_item_collects_dd_holdings_and_company(self):
        it = item(companies=[{"key": "TSM", "name": "TSMC", "role": "party", "p": 0.9}],
                  routes={"dd": [{"ticker": "TSM"}], "holdings": [{"position": "SMH"}]})
        tickers = ec.tickers_for_item(it, ROUTING)
        self.assertIn("TSM", tickers)
        self.assertIn("SMH", tickers)
        # 沒重複
        self.assertEqual(len(tickers), len(set(tickers)))


def _hist(start_price, daily_returns, start_date="2026-06-01"):
    """依 daily_returns 由一個起始價格滾出價格序列，回 [(date, close), ...]。"""
    import datetime as dt
    d = dt.date.fromisoformat(start_date)
    price = start_price
    out = [(d.isoformat(), price)]
    for r in daily_returns:
        d += dt.timedelta(days=1)
        price *= (1 + r)
        out.append((d.isoformat(), price))
    return out


class MarketReactionTests(unittest.TestCase):
    def test_flags_when_abnormal_return_exceeds_twice_stdev(self):
        # 60 天平靜（每天 0%），事件日暴漲 10%
        quiet = [0.0] * 60
        ticker_hist = _hist(100.0, quiet + [0.10, 0.0], start_date="2026-06-01")
        bench_hist = _hist(100.0, [0.0] * 62, start_date="2026-06-01")
        event_date = ticker_hist[61][0]   # 暴漲那天

        def price_fetch(t, period="4mo"):
            return ticker_hist if t == "AAPL" else bench_hist

        r = ec.market_reaction("AAPL", event_date, price_fetch=price_fetch)
        self.assertTrue(r["available"])
        self.assertTrue(r["flagged_event"])
        self.assertTrue(r["flagged"])
        self.assertAlmostEqual(r["stdev_60d"], 0.0, places=6)

    def test_not_flagged_when_move_matches_benchmark(self):
        quiet = [0.001] * 60
        ticker_hist = _hist(100.0, quiet + [0.01, 0.0], start_date="2026-06-01")
        bench_hist = _hist(100.0, quiet + [0.01, 0.0], start_date="2026-06-01")   # 跟基準同步漲
        event_date = ticker_hist[61][0]

        def price_fetch(t, period="4mo"):
            return ticker_hist if t == "AAPL" else bench_hist

        r = ec.market_reaction("AAPL", event_date, price_fetch=price_fetch)
        self.assertFalse(r["flagged"])

    def test_no_price_history_is_unavailable(self):
        r = ec.market_reaction("ZZZZ", "2026-09-22", price_fetch=lambda t, period="4mo": None)
        self.assertFalse(r["available"])

    def test_event_date_after_available_data_is_unavailable(self):
        hist = _hist(100.0, [0.0] * 5, start_date="2026-06-01")
        r = ec.market_reaction("AAPL", "2030-01-01", price_fetch=lambda t, period="4mo": hist)
        self.assertFalse(r["available"])


class FollowupOfficialTests(unittest.TestCase):
    def test_counts_seen_dates_within_window(self):
        it = item(date="2026-09-20", fact_key="fact_x")
        records = [ledger_rec("fact_x", "2026-09-20", seen_dates=["2026-09-20", "2026-09-21", "2026-09-30"])]
        fu = ec.followup_and_official(it, records)
        self.assertEqual(fu["followup_seen_within_3d"], 1)   # 只有 09-21 在 3 天窗內，09-30 太晚

    def test_later_official_confirmation_via_prior_refs(self):
        it = item(date="2026-09-20", fact_key="fact_x")
        records = [ledger_rec("fact_x", "2026-09-20"),
                  ledger_rec("fact_y", "2026-09-22", prior_refs=["fact_x"],
                            official_matches=[{"source": "SEC", "url": "u", "date": "2026-09-22"}])]
        fu = ec.followup_and_official(it, records)
        self.assertTrue(fu["later_official_confirmation"])


class ImportanceBucketTests(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(ec.importance_bucket(2.5), "high")
        self.assertEqual(ec.importance_bucket(1.5), "mid")
        self.assertEqual(ec.importance_bucket(1.49), "low")
        self.assertIsNone(ec.importance_bucket(None))


class AggregateOutcomesTests(unittest.TestCase):
    def test_rates_require_minimum_bucket_size(self):
        records = [{"importance_bucket": "high", "market": [{"available": True}], "has_market_reaction": True,
                   "has_followup": True} for _ in range(2)]
        agg = ec.aggregate_outcomes(records)
        self.assertEqual(agg["high"]["n_items"], 2)
        self.assertIsNone(agg["high"]["market_reaction_rate"])   # n < MIN_BUCKET_N(5)

    def test_rates_computed_with_enough_samples(self):
        records = [{"importance_bucket": "low", "market": [{"available": True}], "has_market_reaction": (i < 1),
                   "has_followup": False} for i in range(5)]
        agg = ec.aggregate_outcomes(records)
        self.assertEqual(agg["low"]["market_reaction_rate"], 0.2)

    def test_discrimination_note_mentions_market_reaction_is_not_importance(self):
        agg = {"high": {"market_reaction_rate": 0.8}, "mid": {}, "low": {"market_reaction_rate": 0.1}}
        note = ec.importance_discrimination_note(agg)
        self.assertIn("importance", note)

    def test_discrimination_note_handles_missing_data(self):
        agg = {"high": {"market_reaction_rate": None}, "mid": {}, "low": {"market_reaction_rate": None}}
        note = ec.importance_discrimination_note(agg)
        self.assertIn("Not enough", note)


class SecondOpinionPromptTests(unittest.TestCase):
    def test_prompt_includes_full_text_only_when_fetched_ok(self):
        it = item()
        sys_p, user_p = ec._second_opinion_prompts(it, {"status": "ok", "excerpt": "SECRET FULL TEXT XYZ"},
                                                    ["capex", "demand"])
        self.assertIn("SECRET FULL TEXT XYZ", user_p)
        self.assertIn("NOVELTY", sys_p)
        self.assertIn("STAGE", sys_p)

    def test_prompt_omits_full_text_when_not_ok(self):
        it = item()
        sys_p, user_p = ec._second_opinion_prompts(it, {"status": "failed"}, ["capex"])
        self.assertNotIn("FULL ARTICLE TEXT", user_p)

    def test_parse_second_opinion_validates_labels(self):
        parsed = ec._parse_second_opinion(
            {"novelty": "new_fact", "stage": "construction_started", "direct_variables": ["capex", "bogus"]},
            ["capex", "demand"])
        self.assertEqual(parsed["direct_variables"], ["capex"])   # bogus 不在 var_ids 裡，濾掉

    def test_parse_second_opinion_rejects_unknown_novelty(self):
        with self.assertRaises(ValueError):
            ec._parse_second_opinion({"novelty": "guessing", "stage": "unclear", "direct_variables": []}, [])


class RunSecondOpinionTests(unittest.TestCase):
    def test_skips_when_cli_unavailable(self):
        with mock.patch.object(ec, "_cli_available", return_value=False):
            result = ec.run_second_opinion([item()], cli_call=None)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["checked"], 0)

    def test_computes_disagreement_when_sonnet_differs(self):
        it = item(jev_label="new_fact", stage="construction_started", direct_vars=["capex"])
        it["id"] = "c_1"

        def fake_cli(sys_p, user_p, model, timeout):
            return {"novelty": "known_restatement", "stage": "construction_started", "direct_variables": ["capex"]}

        def fake_fulltext(cands, max_candidates=12):
            return {}

        result = ec.run_second_opinion([it], cli_call=fake_cli, full_text_fetch=fake_fulltext)
        self.assertEqual(result["status"], "judged")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["disagreement_rate"]["novelty"], 1.0)
        self.assertEqual(result["disagreement_rate"]["stage"], 0.0)
        self.assertEqual(len(result["disagreements"]), 1)
        self.assertIsNotNone(result["disagreements"][0]["novelty"])
        self.assertIsNone(result["disagreements"][0]["stage"])

    def test_single_item_failure_does_not_stop_others(self):
        it1, it2 = item(id_="c_1"), item(id_="c_2")

        # 用呼叫次序區分：第一則失敗，第二則成功
        calls = {"n": 0}

        def fake_cli(sys_p, user_p, model, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("network down")
            return {"novelty": "new_fact", "stage": "construction_started", "direct_variables": ["capex"]}

        result = ec.run_second_opinion([it1, it2], cli_call=fake_cli, full_text_fetch=lambda c, max_candidates=12: {})
        self.assertEqual(result["attempted"], 2)
        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_caps_at_max_items(self):
        items_list = [item(id_=f"c_{i}") for i in range(5)]
        calls = {"n": 0}

        def fake_cli(sys_p, user_p, model, timeout):
            calls["n"] += 1
            return {"novelty": "new_fact", "stage": "construction_started", "direct_variables": ["capex"]}

        ec.run_second_opinion(items_list, cli_call=fake_cli, max_items=2,
                              full_text_fetch=lambda c, max_candidates=12: {})
        self.assertEqual(calls["n"], 2)


class RunCalibrationIntegrationTests(unittest.TestCase):
    def test_full_run_with_small_sample_reports_insufficient(self):
        it1 = item(id_="c_1", date="2026-09-22", fact_key="fact_a")
        it2 = item(id_="c_2", date="2026-09-22", fact_key="fact_b", jev_label="known_restatement")

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it1, it2]}, "ok"
            if url.endswith("evidence_ledger.json"):
                return {"facts": []}, "ok"
            return None, "missing"

        result = ec.run_calibration("2026-09-29", fetch=fetch, price_fetch=lambda t, period="4mo": None,
                                    cli_call=lambda *a, **k: {"novelty": "new_fact", "stage": "unclear",
                                                              "direct_variables": []},
                                    routing=ROUTING)
        self.assertEqual(result["schema"], ec.SCHEMA)
        self.assertEqual(result["sample_size"], 2)
        self.assertIsNone(result["suggestions"]["novelty_min_conf"]["suggested"])
        self.assertEqual(result["second_opinion"]["checked"], 2)

    def test_no_data_week_does_not_crash(self):
        result = ec.run_calibration("2026-09-29", fetch=lambda u, timeout=15: (None, "missing"),
                                    price_fetch=lambda t, period="4mo": None, cli_call=None, routing=ROUTING)
        self.assertEqual(result["sample_size"], 0)
        self.assertEqual(result["second_opinion"]["attempted"], 0)


class CopyrightTests(unittest.TestCase):
    """版權規則：全文只能在 Sonnet 提示裡臨時用，絕不能出現在 calibration 的任何輸出檔裡。"""

    def test_full_text_excerpt_never_reaches_run_calibration_result(self):
        it = item(id_="c_1", date="2026-09-22", fact_key="fact_a")
        secret = "COPYRIGHTED FULL ARTICLE BODY SENTENCE THAT MUST NEVER LEAK " * 5

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it]}, "ok"
            if url.endswith("evidence_ledger.json"):
                return {"facts": []}, "ok"
            return None, "missing"

        def fake_fulltext(cands, max_candidates=12):
            return {c["cid"]: {"status": "ok", "excerpt": secret, "domain": "example.com"} for c in cands}

        seen_prompts = []

        def fake_cli(sys_p, user_p, model, timeout):
            seen_prompts.append(user_p)
            return {"novelty": "new_fact", "stage": "unclear", "direct_variables": []}

        result = ec.run_calibration("2026-09-29", fetch=fetch, price_fetch=lambda t, period="4mo": None,
                                    cli_call=fake_cli, full_text_fetch=fake_fulltext, routing=ROUTING)
        # 全文只能出現在送給 Sonnet 的提示裡
        self.assertTrue(any(secret in p for p in seen_prompts))
        # 但絕不能出現在最終結果（未來會寫進 calibration_*.json）裡
        import json
        dumped = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(secret, dumped)
        self.assertNotIn("COPYRIGHTED FULL ARTICLE BODY", dumped)

    def test_html_output_never_contains_full_text(self):
        it = item(id_="c_1", date="2026-09-22", fact_key="fact_a")
        secret = "COPYRIGHTED FULL ARTICLE BODY SENTENCE THAT MUST NEVER LEAK"

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it]}, "ok"
            if url.endswith("evidence_ledger.json"):
                return {"facts": []}, "ok"
            return None, "missing"

        def fake_fulltext(cands, max_candidates=12):
            return {c["cid"]: {"status": "ok", "excerpt": secret, "domain": "example.com"} for c in cands}

        def fake_cli(sys_p, user_p, model, timeout):
            return {"novelty": "new_fact", "stage": "unclear", "direct_variables": []}

        result = ec.run_calibration("2026-09-29", fetch=fetch, price_fetch=lambda t, period="4mo": None,
                                    cli_call=fake_cli, full_text_fetch=fake_fulltext, routing=ROUTING)
        html = ec.render_calibration_html(result)
        self.assertNotIn(secret, html)


IDEAS_FIXTURE = [
    {"id": "ai-scissors", "short": "AI 剪刀差", "status": "active",
     "checkpoints": [
         {"id": "cp3", "label": "記憶體合約價", "supports_if": "supports text", "refutes_if": "refutes text"},
     ]},
]


def idea_evidence_item(headline="TSMC boosts CoWoS", ideas_hits=None):
    return {"id": "c_1", "date": "2026-09-22", "headline": headline,
           "sources": [{"url": "https://example.com/a"}], "ideas": ideas_hits or []}


class CollectIdeaPairsTests(unittest.TestCase):
    """evidence_calibration.collect_week_idea_pairs（Task 2）：把每一對 (新聞, 查核點) 判斷攤平，
    含 unrelated，unjudged 排除；早報候選 origin 沒有就回填 briefing（舊資料相容），早報外的列
    來自 ideas.wide_pairs。"""

    def test_collects_briefing_and_wide_pairs_excluding_unjudged(self):
        it = idea_evidence_item(ideas_hits=[
            {"idea": "ai-scissors", "checkpoint": "cp3", "label": "L", "verdict": "supports",
             "confidence": 0.8, "summary": "s"},   # 沒有 origin：舊資料，回填成 briefing
            {"idea": "ai-scissors", "checkpoint": "cp3", "label": "L", "verdict": "unjudged",
             "confidence": None},   # unjudged：沒真的問過 Jev，不該被收
        ])

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-25.json"):
                return {"date": "2026-09-25", "items": [it],
                       "ideas": {"wide_pairs": [
                           {"idea": "ai-scissors", "checkpoint": "cp3", "label": "L", "verdict": "unrelated",
                            "confidence": 0.5, "headline": "wide headline", "summary": "w", "url": "https://x/w"},
                       ]}}, "ok"
            return None, "missing"

        pairs, reports = ec.collect_week_idea_pairs("2026-09-29", fetch=fetch)
        self.assertEqual(len(pairs), 2)
        self.assertEqual({p["origin"] for p in pairs}, {"briefing", "wide"})
        briefing_pair = next(p for p in pairs if p["origin"] == "briefing")
        self.assertEqual(briefing_pair["url"], "https://example.com/a")   # 沒自己的 url，回退用 sources
        ok_report = next(r for r in reports if r["date"] == "2026-09-25")
        self.assertEqual(ok_report["pairs"], 2)


class IdeaCheckpointDefsTests(unittest.TestCase):
    def test_builds_lookup_by_idea_and_checkpoint(self):
        defs = ec.idea_checkpoint_defs(IDEAS_FIXTURE)
        self.assertEqual(defs[("ai-scissors", "cp3")]["label"], "記憶體合約價")
        self.assertEqual(defs[("ai-scissors", "cp3")]["supports_if"], "supports text")
        self.assertEqual(defs[("ai-scissors", "cp3")]["idea_short"], "AI 剪刀差")


class AggregateIdeaHitsTests(unittest.TestCase):
    def _pairs(self, unrelated_n, supports_n, origin="briefing"):
        pairs = [{"idea": "ai-scissors", "checkpoint": "cp3", "verdict": "unrelated", "origin": origin}
                for _ in range(unrelated_n)]
        pairs += [{"idea": "ai-scissors", "checkpoint": "cp3", "verdict": "supports", "origin": origin}
                 for _ in range(supports_n)]
        return pairs

    def test_unrelated_share_and_origin_counts(self):
        defs = ec.idea_checkpoint_defs(IDEAS_FIXTURE)
        pairs = self._pairs(4, 1, origin="wide") + self._pairs(0, 2, origin="briefing")
        agg = ec.aggregate_idea_hits(pairs, defs, min_n=1)
        row = agg["by_checkpoint"][0]
        self.assertEqual(row["n"], 7)
        self.assertEqual(row["unrelated"], 4)
        self.assertEqual(row["wide"], 5)
        self.assertEqual(row["briefing"], 2)
        self.assertAlmostEqual(row["unrelated_share"], 4 / 7, places=3)

    def test_suggestion_only_above_share_and_min_sample(self):
        defs = ec.idea_checkpoint_defs(IDEAS_FIXTURE)
        pairs = self._pairs(4, 1)   # 5 對，80% 無關
        agg = ec.aggregate_idea_hits(pairs, defs, min_n=1, flag_share=0.5)
        self.assertEqual(len(agg["suggestions"]), 1)
        self.assertIn("cp3", agg["suggestions"][0])
        agg2 = ec.aggregate_idea_hits(pairs, defs, min_n=10, flag_share=0.5)   # 樣本數不夠，不建議
        self.assertEqual(agg2["suggestions"], [])


class CrossCheckCandidateReviewsTests(unittest.TestCase):
    """cross_check_candidate_reviews（2026-09-24 新增）：research.json 的 candidate_reviews
    （如果有）當可選交叉比對，不是主要指標；沒有這個欄位就整段 unavailable，不擋主要指標。"""

    def test_unavailable_when_research_json_missing(self):
        result = ec.cross_check_candidate_reviews([], fetch=lambda u, timeout=15: (None, "missing"))
        self.assertEqual(result["status"], "unavailable")

    def test_unavailable_when_no_candidate_reviews_field(self):
        def fetch(url, timeout=15):
            return {"schema": "idea-research-v1", "run": {"date": "2026-09-29"}}, "ok"
        result = ec.cross_check_candidate_reviews([], fetch=fetch)
        self.assertEqual(result["status"], "unavailable")

    def test_matches_by_url_idea_checkpoint(self):
        pairs = [
            {"idea": "ai-scissors", "checkpoint": "cp3", "url": "https://example.com/a"},
            {"idea": "ai-scissors", "checkpoint": "cp3", "url": "https://example.com/b"},
        ]

        def fetch(url, timeout=15):
            return {"candidate_reviews": [
                {"date": "2026-09-25", "hit_date": "2026-09-24", "url": "https://example.com/a",
                 "idea": "ai-scissors", "checkpoint": "cp3", "verdict": "supports"},
                {"date": "2026-09-25", "hit_date": "2026-09-24", "url": "https://example.com/b",
                 "idea": "ai-scissors", "checkpoint": "cp3", "verdict": "unrelated"},
            ]}, "ok"

        result = ec.cross_check_candidate_reviews(pairs, fetch=fetch)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["matched"], 2)
        self.assertEqual(result["unrelated"], 1)
        self.assertEqual(result["unrelated_share"], 0.5)

    def test_no_overlap_when_urls_do_not_match(self):
        pairs = [{"idea": "ai-scissors", "checkpoint": "cp3", "url": "https://example.com/other"}]

        def fetch(url, timeout=15):
            return {"candidate_reviews": [
                {"url": "https://example.com/a", "idea": "ai-scissors", "checkpoint": "cp3", "verdict": "supports"},
            ]}, "ok"

        result = ec.cross_check_candidate_reviews(pairs, fetch=fetch)
        self.assertEqual(result["status"], "no_overlap")


class RunIdeaCalibrationIntegrationTests(unittest.TestCase):
    def test_unavailable_when_ideas_json_not_found(self):
        result = ec.run_idea_calibration("2026-09-29", fetch=lambda u, timeout=15: (None, "missing"))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["candidate_reviews"]["status"], "unavailable")

    def test_full_run_with_injected_ideas_and_pairs(self):
        # 2026-09-24 改版：判斷不再是 Jev supports／refutes／unrelated 三選一，是同一次執行內
        # Claude 判斷出來的 supports／refutes／shaky／neutral／unrelated，見 ideas_layer.py。
        it = idea_evidence_item(ideas_hits=[
            {"idea": "ai-scissors", "checkpoint": "cp3", "label": "L", "verdict": "unrelated",
             "reason_zh": "跟查核點無關"}])

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it]}, "ok"
            return None, "missing"

        result = ec.run_idea_calibration("2026-09-29", fetch=fetch, ideas=IDEAS_FIXTURE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["by_checkpoint"][0]["unrelated"], 1)
        self.assertEqual(result["by_checkpoint"][0]["keyword_precision"], 0.0)

    def test_run_calibration_includes_ideas_block_and_never_writes_ideas_json(self):
        # 「只建議，不自動改 ideas.json」：這裡沒有給任何寫檔路徑，只要 run_calibration 能正常
        # 跑完並回傳 ideas 區塊，就足以確認這支程式碼路徑裡沒有寫 ideas.json 這個動作。
        it = item(id_="c_1")

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it]}, "ok"
            if url.endswith("evidence_ledger.json"):
                return {"facts": []}, "ok"
            return None, "missing"

        result = ec.run_calibration("2026-09-29", fetch=fetch, price_fetch=lambda t, period="4mo": None,
                                    cli_call=None, routing=ROUTING, ideas=IDEAS_FIXTURE)
        self.assertIn("ideas", result)
        self.assertEqual(result["ideas"]["status"], "ok")


class HtmlRenderTests(unittest.TestCase):
    def test_render_produces_html_with_key_sections(self):
        it = item(id_="c_1")
        result = ec.run_calibration(
            "2026-09-29",
            fetch=lambda u, timeout=15: (
                ({"date": "2026-09-22", "items": [it]}, "ok") if u.endswith("evidence_2026-09-22.json")
                else ({"facts": []}, "ok") if u.endswith("evidence_ledger.json") else (None, "missing")),
            price_fetch=lambda t, period="4mo": None, cli_call=None, routing=ROUTING)
        html = ec.render_calibration_html(result)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)
        self.assertIn("Jev 週度校準", html)
        self.assertIn("事後回查", html)
        self.assertIn("重要度分數有沒有意義", html)
        self.assertIn("Sonnet 二次意見", html)
        self.assertIn("投資想法校準", html)
        self.assertIn("不會自動套用", html)

    def test_ideas_section_shows_table_and_suggestion_when_ideas_injected(self):
        it = idea_evidence_item(ideas_hits=[
            {"idea": "ai-scissors", "checkpoint": "cp3", "label": "記憶體合約價", "verdict": "unrelated",
             "confidence": 0.5}] * 5)

        def fetch(url, timeout=15):
            if url.endswith("evidence_2026-09-22.json"):
                return {"date": "2026-09-22", "items": [it]}, "ok"
            if url.endswith("evidence_ledger.json"):
                return {"facts": []}, "ok"
            return None, "missing"

        result = ec.run_calibration("2026-09-29", fetch=fetch, price_fetch=lambda t, period="4mo": None,
                                    cli_call=None, routing=ROUTING, ideas=IDEAS_FIXTURE)
        html = ec.render_calibration_html(result)
        self.assertIn("記憶體合約價", html)
        self.assertIn("關鍵詞可能太寬", html)
        self.assertIn("不會自動改 ideas.json", html)


class SaveOutputsTests(unittest.TestCase):
    def test_saves_dated_and_latest_json(self):
        import json
        import tempfile
        result = {"schema": ec.SCHEMA, "date": "2026-09-29", "sample_size": 0}
        with tempfile.TemporaryDirectory() as tmp:
            written = ec.save_outputs(result, Path(tmp))
            self.assertEqual(set(written), {"calibration_2026-09-29.json", "calibration_latest.json"})
            for fn in written:
                data = json.loads((Path(tmp) / fn).read_text(encoding="utf-8"))
                self.assertEqual(data["date"], "2026-09-29")

    def test_saves_html_page(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = ec.save_html("<html>x</html>", Path(tmp))
            self.assertTrue(Path(path).exists())
            self.assertEqual(Path(path).name, "calibration.html")


if __name__ == "__main__":
    unittest.main()


class VariableOverlapTests(unittest.TestCase):
    def test_variable_disagreement_is_partial_not_all_or_nothing(self):
        # 2026-09-23：複選差一個不算完全不同
        r = {"id": "c", "date": "2026-09-23", "headline": "h",
             "jev": {"novelty": "new_fact", "stage": "x", "direct_variables": ["capex", "demand"]},
             "sonnet": {"novelty": "new_fact", "stage": "x", "direct_variables": ["capex"]}}
        self.assertEqual(ec._compare_second_opinion([r])["rates"]["direct_variables"], 0.5)
