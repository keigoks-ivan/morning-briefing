"""new_highs 測試：純合成資料，不連網。"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "briefing"))
for _mod in ("anthropic", "google", "google.genai", "google.genai.types"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

import new_highs as nhm  # noqa: E402
from new_highs import compute_new_highs, compute_track, fetch_log, merge_log  # noqa: E402
import html_template as ht  # noqa: E402

N = 300
IDX = pd.bdate_range(end="2026-10-06", periods=N)


def lab(t, name=None, sec="Tech", sub="Semis"):
    return {"ticker": t, "name": name or t + " Inc", "sector": sec, "sub_industry": sub}


def frame(cols):
    return pd.DataFrame(cols, index=IDX)


def rising(last_bump=1.0):
    s = np.linspace(10, 20, N)
    s[-1] = s[-2] + last_bump
    return s


class T(unittest.TestCase):
    def test_ath_strict(self):
        eq = np.linspace(10, 20, N); eq[-1] = eq[:-1].max()  # equal to prior max
        up = rising(1.0)
        r = compute_new_highs(frame({"EQ": eq, "UP": up}), {"EQ": lab("EQ"), "UP": lab("UP")})
        self.assertEqual([x["ticker"] for x in r["ath"]], ["UP"])
        self.assertEqual(r["high52"], [])  # equal-to-max is not a 52w new high either

    def test_prev_high_date(self):
        s = np.linspace(10, 20, N); s[-1] = 25
        r = compute_new_highs(frame({"A": s}), {"A": lab("A")})
        self.assertEqual(r["ath"][0]["prev_high_date"], IDX[-2].strftime("%Y-%m-%d"))
        self.assertAlmostEqual(r["ath"][0]["chg_pct"], (25 / s[-2] - 1) * 100, places=1)

    def test_52w_below_old_ath(self):
        s = np.full(N, 50.0)
        s[10] = 100.0            # old ATH, > 1y before last date
        s[-1] = 60.0             # above everything in last 365d
        s[-2] = 55.0
        r = compute_new_highs(frame({"B": s}), {"B": lab("B")})
        self.assertEqual(r["ath"], [])
        self.assertEqual(len(r["high52"]), 1)
        self.assertAlmostEqual(r["high52"][0]["pct_below_ath"], -40.0)

    def test_52w_excludes_ath(self):
        r = compute_new_highs(frame({"A": rising()}), {"A": lab("A")})
        self.assertEqual(len(r["ath"]), 1)
        self.assertEqual(r["high52"], [])

    def test_nan_last_date_is_no_data(self):
        s = rising().astype(float); s[-1] = np.nan
        r = compute_new_highs(frame({"A": s, "B": rising(), "C": rising()}),
                              {"A": lab("A"), "B": lab("B"), "C": lab("C")})
        self.assertEqual(r["no_data_n"], 1)
        self.assertEqual(r["evaluated_n"], 2)

    def test_short_history(self):
        s = np.full(N, np.nan); s[-100:] = np.linspace(5, 9, 100)
        r = compute_new_highs(frame({"S": s, "L": rising()}), {"S": lab("S"), "L": lab("L")})
        flags = {x["ticker"]: x["short_history"] for x in r["ath"]}
        self.assertTrue(flags["S"]); self.assertFalse(flags["L"])

    def test_share_class_merge(self):
        r = compute_new_highs(frame({"GOOGL": rising(), "GOOG": rising(2.0), "MSFT": rising()}),
                              {"GOOGL": lab("GOOGL", "Alphabet Inc. (Class A)"),
                               "GOOG": lab("GOOG", "Alphabet Inc. (Class C)"),
                               "MSFT": lab("MSFT", "Microsoft")})
        self.assertEqual(sorted(x["ticker"] for x in r["ath"]), ["GOOGL/GOOG", "MSFT"])

    def test_share_class_not_merged_when_only_one_qualifies(self):
        flat = np.full(N, 10.0)
        r = compute_new_highs(frame({"FOXA": rising(), "FOX": flat}),
                              {"FOXA": lab("FOXA", "Fox Corporation (Class A)"),
                               "FOX": lab("FOX", "Fox Corporation (Class B)")})
        self.assertEqual([x["ticker"] for x in r["ath"]], ["FOXA"])

    def test_renderer_states(self):
        self.assertIn("unavailable", ht._new_highs_section({"status": "unavailable", "reason": "x<y"}))
        self.assertIn("x&lt;y", ht._new_highs_section({"status": "unavailable", "reason": "x<y"}))
        empty = {"status": "ok", "as_of": "2026-10-06", "ath": [], "high52": [], "universe_n": 900, "evaluated_n": 900}
        h = ht._new_highs_section(empty)
        self.assertEqual(h.count("None today."), 3)
        self.assertIn("Tue 6 Oct", h)
        self.assertEqual(ht._new_highs_section({}), "")
        part = dict(empty, status="partial", evaluated_n=500)
        self.assertIn("Scanned 500 of 900", ht._new_highs_section(part))

    def test_renderer_rows_and_escape(self):
        r = compute_new_highs(frame({"A": rising(), "B": np.r_[np.full(N - 2, 50.0), 55.0, 60.0]}),
                              {"A": lab("A", "<b>Evil</b>", sub="Semis<script>"), "B": lab("B", sec="Health", sub="Bio")})
        r.update(status="ok", universe_n=2, universe_source="snapshot")
        r["ath"][0]["short_history"] = True
        h = ht._new_highs_section(r)
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;1y listed", h)
        self.assertIn("All-time high (", h)


def flat_then(last, n=N, base=100.0):
    s = np.full(n, base); s[-1] = last
    return s


class Part2(unittest.TestCase):
    def test_stray_later_bar_does_not_zero_everyone(self):
        df = frame({"A": rising(), "B": rising()})
        extra = pd.DataFrame({"A": [30.0]}, index=[IDX[-1] + pd.Timedelta(days=3)])
        r = compute_new_highs(pd.concat([df, extra]), {"A": lab("A"), "B": lab("B")})
        self.assertEqual(r["as_of"], IDX[-1].strftime("%Y-%m-%d"))
        self.assertEqual(r["evaluated_n"], 2)

    def test_new_lows_and_history(self):
        low = np.full(N, 100.0); low[-1] = 90.0            # new 52w low today
        hi = rising()
        eq = np.full(N, 100.0)                               # never low (equal)
        r = compute_new_highs(frame({"L": low, "H": hi, "E": eq}), {k: lab(k, sec="S" + k) for k in "LHE"})
        b = r["breadth"]
        self.assertEqual((b["highs"], b["lows"], b["net"]), (1, 1, 0))
        self.assertEqual(len(b["history"]), 10)
        self.assertEqual(b["history"][-1]["highs"], 1)
        # yesterday: H also rose (highs counted for every session of a monotone series), L flat -> no low
        self.assertEqual(b["history"][-2]["lows"], 0)
        self.assertEqual(list(b["lows_by_sector"]), ["SL"])

    def test_history_only_counts_tickers_with_close(self):
        s = np.full(N, np.nan); s[-3:] = [5.0, 6.0, 7.0]     # listed 3 sessions ago
        r = compute_new_highs(frame({"N": s, "H": rising()}), {"N": lab("N"), "H": lab("H")})
        self.assertEqual(r["breadth"]["history"][0]["highs"], 1)  # only H
        self.assertEqual(r["breadth"]["history"][-1]["highs"], 2)

    def test_near_bounds(self):
        cols = {"EXACT": flat_then(95.0), "OUT": flat_then(94.9), "ATH": flat_then(105.0),
                "EQ": flat_then(100.0), "IN": flat_then(99.0)}
        r = compute_new_highs(frame(cols), {k: lab(k) for k in cols})
        self.assertEqual(sorted(x["ticker"] for x in r["near_ath"]), ["EXACT", "IN"])
        self.assertEqual(r["near_ath"][0]["ticker"], "IN")   # closest first
        self.assertEqual([x["ticker"] for x in r["ath"]], ["ATH"])

    def test_sector_strength_delta_and_200d(self):
        # X: at ATH now, but 20 sessions ago was 50% below its high -> not near then
        x = np.full(N, 100.0); x[-21] = 50.0; x[-1] = 101.0
        y = np.full(N, 100.0)                                # equal to ATH both times -> near
        short = np.full(N, np.nan); short[-10:] = 10.0       # < 200 closes: excluded from 200d only
        r = compute_new_highs(frame({"X": x, "Y": y, "S": short}),
                              {"X": lab("X"), "Y": lab("Y"), "S": lab("S")})
        row = r["sectors"]["rows"][0]
        self.assertEqual(row["n"], 3)
        self.assertEqual(row["near_pct"], 100.0)
        # 20 sessions ago: X 50% of high (not near), Y near, S not listed yet -> 1/2 = 50% -> +50pp
        self.assertEqual(row["delta_pp"], 50.0)
        # 200d: X (100->101, avg~99.9 -> above), Y (equal avg -> not above); S excluded => 1/2
        self.assertEqual(row["above200_pct"], 50.0)

    def test_sub_industry_min_five(self):
        cols = {f"A{i}": flat_then(100.0 if i else 101.0) for i in range(5)}
        cols.update({f"B{i}": flat_then(101.0) for i in range(4)})
        labs = {k: lab(k, sub="Five" if k[0] == "A" else "Four") for k in cols}
        r = compute_new_highs(frame(cols), labs)
        subs = r["sectors"]["sub_industries"]
        self.assertEqual([x["sub_industry"] for x in subs], ["Five"])
        self.assertEqual((subs[0]["near"], subs[0]["n"]), (5, 5))

    def test_log_fetch_and_merge(self):
        R = lambda code, js=None: types.SimpleNamespace(
            status_code=code, json=lambda: js, raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError()) if code >= 400 else None)
        self.assertEqual(fetch_log(getter=lambda u: R(404)), ({}, "missing"))
        # log 404 while latest exists -> transient site problem, must not restart history
        self.assertEqual(fetch_log(getter=lambda u: R(404) if u.endswith("log.json") else R(200)),
                         (None, "error:LogMissingButLatestExists"))
        sess, st = fetch_log(getter=lambda u: R(500))
        self.assertIsNone(sess); self.assertTrue(st.startswith("error:"))
        def boom(u): raise ConnectionError()
        self.assertEqual(fetch_log(getter=boom)[1], "error:ConnectionError")
        ok = {"schema": "new-highs-log-v1", "sessions": {"2026-10-05": {"ath": ["A"]}}}
        self.assertEqual(fetch_log(getter=lambda u: R(200, ok))[1], "ok")
        m = merge_log(ok["sessions"], "2026-10-06", {"ath": ["B"]})
        self.assertEqual(list(m["sessions"]), ["2026-10-05", "2026-10-06"])
        m2 = merge_log(m["sessions"], "2026-10-06", {"ath": ["C"]})   # rerun overwrites
        self.assertEqual(len(m2["sessions"]), 2)
        self.assertEqual(m2["sessions"]["2026-10-06"]["ath"], ["C"])

    def test_run_does_not_write_log_when_fetch_errors(self):
        rows = [{"ticker": "A", "name": "A", "sector": "T", "sub_industry": "S"}]
        orig = (nhm.load_universe, nhm.download_closes, nhm.fetch_log)
        try:
            nhm.load_universe = lambda: (rows, "snapshot")
            nhm.download_closes = lambda syms: frame({"A": rising()})
            nhm.fetch_log = lambda: (None, "error:Timeout")
            r = nhm.run_new_highs()
            self.assertEqual(r["track"]["status"], "unavailable")
            self.assertIsNone(r["_log"])
            nhm.fetch_log = lambda: ({}, "missing")
            r = nhm.run_new_highs()
            self.assertEqual(r["track"]["status"], "ok")
            self.assertIn(r["as_of"], r["_log"]["sessions"])
        finally:
            nhm.load_universe, nhm.download_closes, nhm.fetch_log = orig

    def test_forward_returns_hand_computed(self):
        idx = pd.bdate_range("2026-01-05", periods=30)
        a = np.full(30, 100.0); a[5 + 5] = 110.0     # +10% at d+5
        b = np.full(30, 100.0); b[5 + 5] = 90.0      # -10%
        c = np.full(30, 100.0); c[5 + 5] = 100.0     # 0
        m = np.full(30, np.nan); m[5:] = 100.0
        m[5] = np.nan                                  # missing at d -> skipped
        cl = pd.DataFrame({"A": a, "B": b, "C": c, "M": m}, index=idx)
        d = idx[5].strftime("%Y-%m-%d")
        sess = {d: {"ath": ["A", "M"], "high52": ["B"], "near": [], "universe": ["A", "B", "C"]}}
        t = compute_track(sess, cl)
        h5 = t["horizons"][0]
        self.assertEqual(h5["n"], 1)
        self.assertAlmostEqual(h5["ath"], 0.10)          # M skipped
        self.assertAlmostEqual(h5["high52"], -0.10)
        self.assertIsNone(h5["near"])
        self.assertAlmostEqual(h5["base"], 0.0)          # mean(+10,-10,0)
        self.assertAlmostEqual(h5["ath_excess"], 0.10)
        self.assertEqual(h5["ath_hit"], 100.0); self.assertEqual(h5["high52_hit"], 0.0)
        self.assertEqual(t["horizons"][1]["n"], 1)       # 20 sessions after idx[5] still inside 30 rows
        self.assertEqual(t["horizons"][2]["n"], 0)       # 60 not matured
        self.assertTrue(t["matured_any"])

    def test_nothing_matured_estimates(self):
        cl = frame({"A": rising()})
        d = cl.index[-1].strftime("%Y-%m-%d")
        t = compute_track({d: {"ath": ["A"], "high52": [], "near": [], "universe": ["A"]}}, cl)
        self.assertFalse(t["matured_any"])
        self.assertEqual(t["est"]["5"], (cl.index[-1] + pd.offsets.BDay(5)).strftime("%Y-%m-%d"))

    def _full(self, n_near):
        near = [{"ticker": f"T{i}", "name": "n", "sector": "Tech" if i % 2 else "Energy", "sub_industry": "x",
                 "close": 1.0, "chg_pct": 0.5, "short_history": False, "pct_below_ath": -(i % 5) - 0.5}
                for i in range(n_near)]
        return {"status": "ok", "as_of": "2026-10-06", "ath": [], "high52": [], "near_ath": near,
                "universe_n": 9, "evaluated_n": 9,
                "breadth": {"highs": 3, "lows": 2, "net": 1, "lows_by_sector": {"Utilities": 2},
                            "history": [{"date": "2026-10-06", "highs": 3, "lows": 2}]},
                "sectors": {"rows": [{"sector": "Tech", "n": 5, "near_pct": 40.0, "delta_pp": None, "above200_pct": None}],
                            "sub_industries": [{"sub_industry": "Semis", "n": 5, "near": 2, "near_pct": 40.0}]},
                "track": {"status": "ok", "first_logged": "2026-10-06", "matured_any": False,
                          "est": {"5": "2026-10-13", "20": "2026-11-03"}, "horizons": []}}

    def test_renderer_part2(self):
        h = ht._new_highs_section(self._full(60), max_near=40)
        self.assertIn("52w highs <b", h)
        self.assertIn("New lows by sector: Utilities 2", h)
        self.assertIn("+20 more on the site", h)
        self.assertEqual(h.count("<b style=\"color:#222;\">T"), 40)
        self.assertNotIn("more on the site", ht._new_highs_section(self._full(60)))
        self.assertIn("collecting since 2026-10-06", h)
        self.assertIn("Strongest sub-industries: Semis 40% (2/5)", h)
        self.assertIn("n/a", h)
        self.assertIn("Equal-weight averages", h)

    def test_renderer_track_states(self):
        d = self._full(1)
        d["track"] = {"status": "unavailable", "reason": "log fetch error:Timeout"}
        h = ht._new_highs_section(d)
        self.assertIn("Track record unavailable (log fetch error:Timeout)", h)
        self.assertNotIn("Equal-weight", h)
        d["breadth"] = dict(d["breadth"], lows=0, lows_by_sector={})
        self.assertNotIn("New lows by sector", ht._new_highs_section(d))
        d["track"] = {"status": "ok", "first_logged": "2026-09-01", "matured_any": True, "est": {},
                      "horizons": [{"h": 5, "n": 3, "base": 0.01, "ath": 0.02, "ath_excess": 0.01, "ath_hit": 66.7,
                                    "high52": None, "high52_excess": None, "high52_hit": None,
                                    "near": 0.0, "near_excess": -0.01, "near_hit": 33.3}]}
        h = ht._new_highs_section(d)
        self.assertIn("+2.0%", h); self.assertIn("(67%)", h)
        self.assertIn("5d", h)


if __name__ == "__main__":
    unittest.main()
