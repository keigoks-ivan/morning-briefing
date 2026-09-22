"""evidence_sources.py 離線測試：TDnet（東證適時開示）一手來源。

不連網、不呼叫付費 API。tests/fixtures/tdnet/ 放的是 2026-09-18（一般交易日，238 則公告，
本檔只留前 12 則）與 2026-09-22（日本假日，無公告）兩份實抓快照，parse_tdnet 直接對著這兩份
原始 HTML 測；OfficialSources 的測試用假 fetch_text 讀本機快照，不打真的網路。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "briefing"))

from evidence_ledger import extract_figures  # noqa: E402
from evidence_sources import OfficialSources, parse_tdnet  # noqa: E402

FX = Path(__file__).resolve().parent / "fixtures" / "tdnet"
BUSY_DAY = FX / "I_list_001_20260918.html"
HOLIDAY = FX / "I_list_001_20260922.html"


class TestParseTdnet(unittest.TestCase):
    def test_real_snapshot_parses_rows(self):
        items = parse_tdnet(BUSY_DAY.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 12)
        first = items[0]
        self.assertEqual(first["date"], "2026-09-18")
        self.assertEqual(first["company_code"], "3905")
        self.assertEqual(first["market"], "JP")
        self.assertEqual(first["link"], "https://www.release.tdnet.info/inbs/140120260918538994.pdf")
        self.assertIn("大口受注", first["title"])
        self.assertTrue(first["company_name"])

    def test_5char_code_with_letter_truncates_to_4char_base(self):
        # 264A0 → 264A（第 5 碼是檢查碼）
        items = parse_tdnet(BUSY_DAY.read_text(encoding="utf-8"))
        codes = {it["company_code"] for it in items}
        self.assertIn("264A", codes)
        self.assertTrue(all(len(c) == 4 for c in codes))

    def test_holiday_page_has_no_rows(self):
        self.assertEqual(parse_tdnet(HOLIDAY.read_text(encoding="utf-8")), [])

    def test_empty_text_does_not_error(self):
        self.assertEqual(parse_tdnet(""), [])
        self.assertEqual(parse_tdnet(None), [])


def _fetch_from(mapping: dict):
    """假 fetch_text：只認得 mapping 裡的網址，其他一律 missing（不連網）。"""
    def fetch(url: str, timeout: int = 15):
        if url in mapping:
            return mapping[url].read_text(encoding="utf-8"), "ok"
        return None, "error:offline test"
    return fetch


TDNET_SPEC = {
    "tdnet_disclosure": {
        "label": "TDnet timely disclosure (Tokyo Stock Exchange)",
        "kind": "tdnet_html",
        "base_url": "https://www.release.tdnet.info/inbs/",
        "lookback_days": 1,
        "max_pages_per_day": 10,
        "covers": ["*JP"],
    }
}


class TestOfficialSourcesTdnet(unittest.TestCase):
    def test_busy_day_status_ok_and_in_summary(self):
        fetch = _fetch_from({
            "https://www.release.tdnet.info/inbs/I_list_001_20260918.html": BUSY_DAY,
        })
        official = OfficialSources(TDNET_SPEC, fetch_text=fetch, today="2026-09-18")
        official.prefetch()
        self.assertEqual(official.status["tdnet_disclosure"]["status"], "ok")
        self.assertEqual(official.status["tdnet_disclosure"]["items"], 12)
        summary = official.summary()
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(summary["empty"], [])
        self.assertEqual(summary["failed"], {})

    def test_holiday_status_is_empty_not_error(self):
        fetch = _fetch_from({
            "https://www.release.tdnet.info/inbs/I_list_001_20260922.html": HOLIDAY,
        })
        official = OfficialSources(TDNET_SPEC, fetch_text=fetch, today="2026-09-22")
        official.prefetch()
        self.assertEqual(official.status["tdnet_disclosure"]["status"], "empty")
        self.assertEqual(official.status["tdnet_disclosure"]["items"], 0)
        self.assertIn("tdnet_disclosure", official.summary()["empty"])

    def test_no_page_reachable_is_error_gap_not_silence(self):
        official = OfficialSources(TDNET_SPEC, fetch_text=_fetch_from({}), today="2026-09-18")
        official.prefetch()
        self.assertEqual(official.status["tdnet_disclosure"]["status"], "error")
        self.assertIn("tdnet_disclosure", official.summary()["failed"])


class TestTdnetCodeMatching(unittest.TestCase):
    """cand 的數字或用字對上 TDnet 標題 → matched；只是同代號同天 → nearby；
    代號沒在 jp_codes 裡 → 不列（就算剛好跟 tw_codes 撞號也不誤配，見 evidence_sources.match）。"""

    def _official_with_row(self, code: str, title: str, date: str = "2026-09-18") -> OfficialSources:
        official = OfficialSources(TDNET_SPEC, fetch_text=lambda u, timeout=15: (None, "missing"), today=date)
        official.items["tdnet_disclosure"] = [{
            "title": title, "link": "https://www.release.tdnet.info/inbs/test.pdf", "date": date,
            "summary": "", "outlet": "", "company_code": code, "company_name": "テスト株式会社", "market": "JP",
        }]
        official.status["tdnet_disclosure"] = {"status": "ok", "items": 1, "label": "TDnet timely disclosure"}
        return official

    def test_shared_figure_upgrades_to_matched(self):
        # 「10億円」＝10 * 1e8 = 1e9，跟英文候選的 $1 billion 用同一套 extract_figures 正規化，兩邊會對上
        official = self._official_with_row("6920", "10億円の第三者割当増資を実施")
        cand = {"figures": extract_figures("raised $1 billion in a new offering"), "tokens": set(),
                "event_date": "2026-09-18"}
        result = official.match(cand, entity_keys=set(), names=["Lasertec"], tw_codes=set(), today="2026-09-18",
                                 jp_codes={"6920"})
        self.assertEqual(result["nearby"], [])
        self.assertEqual(len(result["matched"]), 1)
        self.assertIn("shared figure", result["matched"][0]["why"])

    def test_no_shared_figure_is_nearby_only(self):
        official = self._official_with_row("6920", "人事異動に関するお知らせ")
        cand = {"figures": extract_figures("announces new product roadmap"), "tokens": set(),
                "event_date": "2026-09-18"}
        result = official.match(cand, entity_keys=set(), names=["Lasertec"], tw_codes=set(), today="2026-09-18",
                                 jp_codes={"6920"})
        self.assertEqual(result["matched"], [])
        self.assertEqual(len(result["nearby"]), 1)
        self.assertEqual(result["nearby"][0]["why"], "same company filing near the date")

    def test_code_not_in_jp_codes_is_skipped(self):
        official = self._official_with_row("6920", "10億円の第三者割当増資を実施")
        cand = {"figures": extract_figures("raised $1 billion"), "tokens": set(), "event_date": "2026-09-18"}
        result = official.match(cand, entity_keys=set(), names=[], tw_codes=set(), today="2026-09-18",
                                 jp_codes={"9984"})  # 6920 不在候選的日股代號裡
        self.assertEqual(result["matched"], [])
        self.assertEqual(result["nearby"], [])

    def test_tw_code_collision_does_not_leak_into_jp_match(self):
        # TDnet 代號剛好跟台股代號撞號：只認 jp_codes，不能因為 tw_codes 有同號就誤配。
        # jp_codes 給一個不相關的代號（讓 *JP 來源照常被判定為 relevant），tw_codes 才放撞號的 6920。
        official = self._official_with_row("6920", "10億円の第三者割当増資を実施")
        cand = {"figures": extract_figures("raised $1 billion"), "tokens": set(), "event_date": "2026-09-18"}
        result = official.match(cand, entity_keys=set(), names=[], tw_codes={"6920"}, today="2026-09-18",
                                 jp_codes={"9984"})
        self.assertEqual(result["matched"], [])
        self.assertEqual(result["nearby"], [])


if __name__ == "__main__":
    unittest.main()
