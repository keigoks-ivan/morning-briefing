"""shadow_judge（影子判斷，2026-10-10 新增）離線測試。不呼叫 Jev、不呼叫 Claude CLI、不連網。
假 Jev 用 evidence_fixtures 的劇本，Sonnet 用假的 judge_call。"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _mod in ("anthropic", "google", "google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

import evidence_fixtures as fx  # noqa: E402

import evidence_layer  # noqa: E402
import shadow_compare as sc  # noqa: E402
import shadow_judge as sj  # noqa: E402
from evidence_ledger import EntityMatcher  # noqa: E402
from evidence_questions import build_questions  # noqa: E402
from evidence_routing import load_routing  # noqa: E402

SECRET = "ZQX-shadow-fulltext-marker-7731"


def run_with_shadow(full_text_fetch=None):
    jobs: list = []
    jev, _ = fx.fake_client()
    ev, ledger = evidence_layer.run_evidence_layer(
        fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
        ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
        sec_user_agent=None, official_fetch=fx.offline_sources,
        full_text_fetch=full_text_fetch or fx.no_fulltext, shadow_jobs=jobs)
    return ev, ledger, jobs


def mirror_jev(jobs):
    """假 Sonnet：把同一則 Jev 的答案換成「各選項機率」回傳（noul → true/false）。"""
    by_headline = {jb["state"]["today"]["headline"]: jb["jev_answers"] for jb in jobs}

    def call(system_prompt, user_prompt):
        req = json.loads(user_prompt)
        out = []
        for it in req["items"]:
            ans = by_headline[it["state"]["today"]["headline"]]
            dist = {}
            for qid in it["question_ids"]:
                a = ans[qid]
                if a["type"] == "noul":
                    dist[qid] = {"true": a["noul"], "false": 1 - a["noul"]}
                elif a["type"] == "choice":
                    dist[qid] = a["probabilities"]
                else:
                    lvl = str(int(round(a["score"])))
                    dist[qid] = {lvl: 1.0}
            out.append({"id": it["id"], "answers": dist})
        return {"items": out}
    return call


class CollectTests(unittest.TestCase):
    def test_jobs_collected_without_touching_result(self):
        ev, _, jobs = run_with_shadow()
        self.assertEqual(len(jobs), len(ev["items"]))
        self.assertEqual({jb["cand"]["cid"] for jb in jobs}, {it["id"] for it in ev["items"]})
        self.assertNotIn("shadow", ev)
        for jb in jobs:
            self.assertEqual(set(jb["questions"]), set(jb["jev_answers"]))

    def test_default_none_collects_nothing(self):
        jev, _ = fx.fake_client()
        ev, _ = evidence_layer.run_evidence_layer(
            fx.briefing_data(), [], fx.watchlist(), fx.news_quality(), fx.TODAY, None,
            ledger=fx.seed_ledger(), holdings_json=fx.holdings(), jev=jev, fetch=fx.no_fetch,
            sec_user_agent=None, official_fetch=fx.offline_sources, full_text_fetch=fx.no_fulltext)
        self.assertTrue(ev["items"])


class RunShadowTests(unittest.TestCase):
    def test_mirrored_answers_reproduce_jev_decisions(self):
        _, ledger, jobs = run_with_shadow()
        res = sj.run_shadow(jobs, fx.TODAY, ledger.available, judge_call=mirror_jev(jobs), last_date="2099-12-31")
        self.assertEqual(res["status"], "judged")
        self.assertEqual(res["stats"]["judged"], len(jobs))
        for row in res["items"]:
            j, s = row["jev"], row["shadow"]
            for k in ("class", "lane", "direct", "indirect"):
                self.assertEqual(j[k], s[k], f"{row['headline']}: {k}")
            for k in ("novelty", "stage", "timing", "attribution"):   # 劇本機率總和不是剛好 1，信心比到小數兩位
                self.assertEqual(j[k][0], s[k][0], f"{row['headline']}: {k}")
                self.assertAlmostEqual(j[k][1], s[k][1], places=2)

    def test_failed_batch_marks_only_its_items(self):
        _, ledger, jobs = run_with_shadow()
        good = mirror_jev(jobs)
        first_id = jobs[0]["cand"]["cid"]

        def flaky(system_prompt, user_prompt):
            if first_id in [it["id"] for it in json.loads(user_prompt)["items"]]:
                raise RuntimeError("claude CLI exited 1: " + SECRET)
            return good(system_prompt, user_prompt)

        orig = sj.MAX_BATCH_CHARS
        sj.MAX_BATCH_CHARS = 1   # 每則自成一批
        try:
            res = sj.run_shadow(jobs, fx.TODAY, ledger.available, judge_call=flaky, last_date="2099-12-31")
        finally:
            sj.MAX_BATCH_CHARS = orig
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["stats"]["batch_errors"], ["RuntimeError"])
        bad = [r for r in res["items"] if r["shadow"] is None]
        self.assertEqual([r["id"] for r in bad], [first_id])
        self.assertEqual(bad[0]["shadow_error"], "missing")
        self.assertNotIn(SECRET, json.dumps(res))

    def test_window_end_skips_and_writes_nothing(self):
        _, ledger, jobs = run_with_shadow()
        calls = []
        res = sj.run_shadow(jobs, "2026-10-25", ledger.available,
                            judge_call=lambda s, u: calls.append(1), last_date="2026-10-24")
        self.assertEqual(res["status"], "skipped")
        self.assertEqual(calls, [])
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sj.save_shadow(res, d, "2026-10-25"))
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_full_text_reaches_prompt_but_never_the_file(self):
        def ft(cands):
            return {c["cid"]: {"status": "ok", "url": "https://www.reuters.com/x", "domain": "reuters.com",
                               "word_count": 500, "excerpt": f"{SECRET} body text. " * 10,
                               "quotes": [], "figures": []} for c in cands[:1]}
        _, ledger, jobs = run_with_shadow(full_text_fetch=ft)
        prompts = []
        mirror = mirror_jev(jobs)

        def spy(system_prompt, user_prompt):
            prompts.append(user_prompt)
            return mirror(system_prompt, user_prompt)

        res = sj.run_shadow(jobs, fx.TODAY, ledger.available, judge_call=spy, last_date="2099-12-31")
        self.assertTrue(any(SECRET in p for p in prompts))
        with tempfile.TemporaryDirectory() as d:
            fn = sj.save_shadow(res, d, fx.TODAY)
            self.assertEqual(fn, f"shadow_judge_{fx.TODAY}.json")
            self.assertNotIn(SECRET, (Path(d) / fn).read_text(encoding="utf-8"))


class CompareTests(unittest.TestCase):
    def rows(self, judge_factory):
        ev, ledger, jobs = run_with_shadow()
        res = sj.run_shadow(jobs, fx.TODAY, ledger.available, judge_call=judge_factory(jobs), last_date="2099-12-31")
        ev_by_id = {it["id"]: it for it in ev["items"]}
        rows = [{**it, "date": fx.TODAY, "evidence": {**ev_by_id[it["id"]], "date": fx.TODAY}} for it in res["items"]]
        return rows, ledger.records

    def test_mirror_agrees_everywhere(self):
        rows, records = self.rows(mirror_jev)
        out = sc.compare(rows, records, EntityMatcher(load_routing()))
        self.assertEqual(out["n_both"], len(rows))
        self.assertEqual(out["lane"]["agree"], 1.0)
        self.assertEqual(out["labels"]["novelty"]["agree"], 1.0)
        self.assertEqual(out["direct_vars"]["exact"], 1.0)
        self.assertEqual(out["hindsight"]["novelty_splits"], [])
        self.assertEqual(out["hindsight"]["checked"], len(rows))

    def test_flipped_novelty_shows_up_as_split(self):
        def flip(jobs):
            mirror = mirror_jev(jobs)
            new_ids = {jb["cand"]["cid"] for jb in jobs
                       if jb["jev_answers"]["novelty"]["choice"] in ("new_fact", "progress_update")}

            def call(system_prompt, user_prompt):
                out = mirror(system_prompt, user_prompt)
                for it in out["items"]:
                    if it["id"] in new_ids:
                        it["answers"]["novelty"] = {"known_restatement": 0.8, "new_fact": 0.2}
                return out
            return call
        rows, records = self.rows(flip)
        out = sc.compare(rows, records, EntityMatcher(load_routing()))
        splits = out["hindsight"]["novelty_splits"]
        self.assertTrue(splits)
        self.assertTrue(all(s["sonnet"] == "known_restatement" for s in splits))
        self.assertLess(out["labels"]["novelty"]["agree"], 1.0)
        self.assertIn("Sonnet", sc._fmt(out, [{"date": fx.TODAY, "status": "judged", "items": len(rows),
                                                "seconds": 1.0, "batch_errors": []}]))


class ConvertTests(unittest.TestCase):
    QS = build_questions(1, ["demand"])

    def full(self):
        return {"novelty": {"new_fact": 0.7, "progress_update": 0.3},
                "stage": {"agreement_signed": 1},
                "importance": {"2": 0.5, "3": 0.5},
                "attribution": {"company_statement": 1},
                "timing": {"already_in_effect": 1},
                "var_demand": {"direct": 80, "none": 20},     # 百分比也能正規化
                "dir_demand": {"up": 1},
                "party_0": {"true": 0.9, "false": 0.1}}

    def test_conversion_shapes(self):
        a = sj.to_jev_answers(self.full(), self.QS)
        self.assertEqual(a["novelty"]["choice"], "new_fact")
        self.assertAlmostEqual(a["novelty"]["confidence"], 0.7)
        self.assertEqual(a["importance"]["score"], 2.5)
        self.assertAlmostEqual(a["var_demand"]["confidence"], 0.8)
        self.assertAlmostEqual(a["party_0"]["noul"], 0.9)

    def test_missing_question_or_unknown_options_rejected(self):
        raw = self.full()
        del raw["timing"]
        self.assertIsNone(sj.to_jev_answers(raw, self.QS))
        raw = self.full()
        raw["stage"] = {"not_an_option": 1}
        self.assertIsNone(sj.to_jev_answers(raw, self.QS))
        self.assertIsNone(sj.to_jev_answers(None, self.QS))


if __name__ == "__main__":
    unittest.main()
