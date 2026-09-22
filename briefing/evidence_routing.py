"""
evidence_routing.py
-------------------
「變數／供應鏈環節 → DD／研究主題 → 持倉」派送，全部是明確對照規則，不問模型。

三件事分開：
- DD universe（dd-screener latest.json）：在清單內不代表持有。dd_status=="dd" 才有 DD 報告。
- 研究主題（ID 報告）：由環節對照（data/evidence_routing.json 的 segments→themes）。
- 持倉：只讀公開的系統組合 /pm/holdings.json（指數部 ETF＋個股席位）。
  這不是券商實際持倉；程式不讀、也不輸出任何未公開的持倉資料。

不確定的關聯一律進 pending（待審），不猜。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from evidence_questions import VAR_LABEL

ROUTING_PATH = Path(__file__).resolve().parents[1] / "data" / "evidence_routing.json"
PUBLIC_HOLDINGS_URL = "https://research.investmquest.com/pm/holdings.json"
PARTY_YES = 0.70
PARTY_NO = 0.35
THEMES_PER_SEGMENT = 2

SEC_FORMS = {"8-K", "6-K", "10-Q", "10-K", "20-F", "S-1", "F-1", "424B2", "424B3", "424B4", "424B5",
             "SC 13D", "SC 13G", "425"}
SEC_WINDOW_DAYS = 5


def load_routing(path: Path | None = None) -> dict:
    return json.loads(Path(path or ROUTING_PATH).read_text(encoding="utf-8"))


# ── 公開持倉（系統組合） ──────────────────────────────────────────────────
def public_holdings_view(holdings_json: dict | None) -> dict:
    """只取公開 holdings.json 裡本來就有的欄位：指數部元件 ticker、個股席位 ticker＋席別。"""
    view = {"available": False, "index": {}, "seats": {}, "as_of": ""}
    if not isinstance(holdings_json, dict):
        return view
    view["available"] = True
    view["as_of"] = str(holdings_json.get("as_of") or "")
    for comp in ((holdings_json.get("index_sleeve") or {}).get("components") or []):
        t = str(comp.get("ticker") or "")
        if t:
            view["index"][t] = {"market": comp.get("market", "")}
    sleeve = holdings_json.get("stock_sleeve") or {}
    for key, seat in (("core_seats", "core"), ("sat_seats", "satellite")):
        for s in sleeve.get(key) or []:
            t = str(s.get("ticker") or "")
            if t:
                view["seats"][t] = seat
    return view


# ── DD universe ───────────────────────────────────────────────────────────
def dd_index(watchlist: list[dict] | None) -> dict:
    out = {}
    for w in watchlist or []:
        t = str(w.get("ticker") or "")
        if t:
            out[t] = {"dd_status": w.get("dd_status") or "", "dd_path": w.get("dd_path") or "",
                      "dd_date": w.get("dd_date") or "", "name": w.get("name") or t}
    return out


def _company_tickers(key: str, routing: dict) -> list[str]:
    """對照表 key → 可能出現在 DD／持倉的 ticker（TSM 也對 2330.TW／2330）。"""
    spec = (routing.get("companies") or {}).get(key) or {}
    tickers = [key] if spec.get("ticker", key) == key else []
    if spec.get("ticker"):
        tickers.append(spec["ticker"])
    for other, ospec in (routing.get("companies") or {}).items():
        if isinstance(ospec, dict) and ospec.get("same_as") == key:
            tickers.append(other)
    if key == "TSM":
        tickers.append("2330")
    return [t for t in dict.fromkeys(tickers) if t]


def _keyword_hits(text: str, keywords: list[str]) -> list[str]:
    folded = (text or "").casefold()
    return [k for k in keywords if k.casefold() in folded]


def route(text: str, parties: dict, pending_parties: dict, routing: dict, dd: dict,
          holdings: dict, judged: bool, matched_companies: list[str]) -> dict:
    """parties: {company_key: p}（Jev 判定為當事人，p≥PARTY_YES）
    pending_parties: {company_key: p}（PARTY_NO≤p<PARTY_YES）
    judged=False（沒有 Jev）時，程式比對到的公司全部當作「未驗證」進待審。"""
    segs = {k: v for k, v in (routing.get("segments") or {}).items() if not k.startswith("_")}
    out = {"segments": [], "dd": [], "themes": [], "holdings": [], "pending": []}

    party_keys = list(parties) if judged else []
    if not judged:
        for key in matched_companies:
            out["pending"].append({"kind": "company", "key": key,
                                   "reason": "Company matched by name only; not verified as a party (no classification today)"})
    for key, p in pending_parties.items():
        out["pending"].append({"kind": "company", "key": key,
                               "reason": f"Unclear whether it is a party to the fact (party probability {p:.2f})"})

    # 環節：要有關鍵字；當事公司在該環節內＝確認，否則要兩個以上不同關鍵字，只有一個就待審
    accepted = []
    for seg_id, spec in segs.items():
        hits = _keyword_hits(text, spec.get("keywords") or [])
        members = set(spec.get("companies") or [])
        party_in = [k for k in party_keys if k in members]
        if hits and (party_in or len(hits) >= 2):
            accepted.append(seg_id)
            out["segments"].append({"id": seg_id, "label": spec.get("label", seg_id),
                                    "basis": ("party+keyword" if party_in else "keywords"),
                                    "keywords": hits[:4]})
        elif hits:
            out["pending"].append({"kind": "segment", "key": seg_id,
                                   "reason": f"Keyword match only ('{hits[0]}'); link to {spec.get('label', seg_id)} not confirmed"})

    # DD：只給當事公司
    for key in party_keys:
        for t in _company_tickers(key, routing):
            info = dd.get(t)
            if not info:
                continue
            if info.get("dd_status") == "dd" and info.get("dd_path"):
                out["dd"].append({"ticker": t, "company": key, "path": info["dd_path"], "date": info.get("dd_date", "")})
            else:
                out["dd"].append({"ticker": t, "company": key, "path": "", "date": "", "note": "In screener universe, no DD yet"})
            break

    # 研究主題：由已確認的環節帶出
    themes = routing.get("themes") or {}
    seen = set()
    for seg_id in accepted:
        for th in (segs[seg_id].get("themes") or [])[:THEMES_PER_SEGMENT]:
            if th in seen:
                continue
            seen.add(th)
            meta = themes.get(th) or {}
            out["themes"].append({"key": th, "segment": seg_id, "path": meta.get("path", ""),
                                  "label": meta.get("label") or th})

    # 持倉：只用公開系統組合裡真的有的部位
    if holdings.get("available"):
        for key in party_keys:
            for t in _company_tickers(key, routing):
                if t in holdings["seats"]:
                    out["holdings"].append({"position": t, "kind": f"System seat ({holdings['seats'][t]})",
                                            "via": "company"})
                    break
        exposure = {k: v for k, v in (routing.get("holdings_exposure") or {}).items() if not k.startswith("_")}
        for sleeve, spec in exposure.items():
            if sleeve not in holdings["index"]:
                continue
            via = None
            if any(k in (spec.get("companies") or []) for k in party_keys):
                via = "company in index"
            elif any(s in (spec.get("segments") or []) for s in accepted):
                via = "segment in index"
            if via:
                out["holdings"].append({"position": sleeve, "kind": "Index sleeve", "via": via})
    return out


# ── 可能受影響的產業與公司（2026-09-22：使用者要看產業／個股潛在影響，不限 DD） ──
_ARROW = {"up": "↑", "down": "↓"}
# 只有這些「實體」變數會往上下游傳；股價、利率本身不往下推產業名單
_PROPAGATING = ("capex", "financing", "demand", "shipments", "supply_capacity", "price")


def potential_impact(routes: dict, direct_vars: list[dict], parties: dict, routing: dict,
                     name_of) -> dict:
    """產業環節＋公司名單全部來自對照表；方向只標「經濟變數」的方向，不是股價方向。
    direct_vars: [{"var", "label", "direction"}]（Jev 判定為直接影響、信心過門檻的）"""
    segs = routing.get("segments") or {}
    trans = routing.get("transmission") or {}
    var_txt = ", ".join(f"{v['label']} {_ARROW.get(v.get('direction'), '')}".strip() for v in direct_vars)
    accepted = [s["id"] for s in routes.get("segments") or []]
    direct, knock = [], []
    for seg_id in accepted:
        spec = segs.get(seg_id) or {}
        members = [k for k in parties if k in (spec.get("companies") or [])]
        direct.append({"segment": spec.get("label", seg_id), "companies": [name_of(k) for k in members],
                       "variables": var_txt})
    movers = [v for v in direct_vars if v["var"] in _PROPAGATING]
    if movers:
        via_var = movers[0]["var"]
        via = next(iter(trans.get(via_var) or []), None)
        target = VAR_LABEL.get(via[0], via[0]) if via else ""
        seen = set(accepted)
        for seg_id in accepted:
            for nxt in (segs.get(seg_id) or {}).get("knock_on") or []:
                if nxt in seen or nxt not in segs:
                    continue
                seen.add(nxt)
                nspec = segs[nxt]
                knock.append({
                    "segment": nspec.get("label", nxt),
                    "companies": [name_of(k) for k in (nspec.get("companies") or [])][:5],
                    "via": (f"via {movers[0]['label']} → {target}" if via else f"via {movers[0]['label']}"),
                    "status": "Possible, not confirmed",
                })
    return {"direct": direct, "knock_on": knock[:3],
            "note": "Arrows show the direction of the economic variable, not of any share price."}


# ── 一手來源檢查（SEC EDGAR） ─────────────────────────────────────────────
def sec_check(company_keys: list[str], routing: dict, event_date: str, today: str,
              user_agent: str | None, http_get_json, cik_extra: dict | None = None,
              cache: dict | None = None) -> dict:
    """對已接 SEC 的當事公司，列出事件日前後的申報。只列「有這份申報」，不宣稱內容已對上主張。
    沒設 SEC_USER_AGENT、網路失敗都如實回報，不當成「沒有申報」。"""
    pcfg = (routing.get("primary_sources") or {}).get("companies") or {}
    result = {"checked": [], "gaps": []}
    cache = cache if cache is not None else {}
    try:
        lo = (datetime.strptime((event_date or today)[:10], "%Y-%m-%d") - timedelta(days=SEC_WINDOW_DAYS)).date().isoformat()
    except ValueError:
        lo = today
    for key in company_keys:
        spec = pcfg.get(key)
        if not spec:
            continue
        if spec.get("connected") != "sec":
            result["gaps"].append({"company": key, "source": spec.get("label", ""), "reason": "not connected"})
            continue
        cik = str(spec.get("cik") or (cik_extra or {}).get(key) or "").lstrip("0")
        if not cik:
            result["gaps"].append({"company": key, "source": "SEC EDGAR", "reason": "CIK unknown"})
            continue
        if not user_agent:
            result["checked"].append({"company": key, "source": "SEC EDGAR", "status": "skipped",
                                      "reason": "SEC_USER_AGENT not set"})
            continue
        if cik not in cache:
            try:
                cache[cik] = {"ok": True, "data": http_get_json(
                    f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json", user_agent)}
            except Exception as e:  # noqa: BLE001
                cache[cik] = {"ok": False, "error": type(e).__name__}
        got = cache[cik]
        if not got["ok"]:
            result["checked"].append({"company": key, "source": "SEC EDGAR", "status": "failed",
                                      "reason": got["error"]})
            continue
        recent = ((got["data"] or {}).get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        filings = []
        for i, form in enumerate(forms):
            fdate = (recent.get("filingDate") or [""] * len(forms))[i]
            if form in SEC_FORMS and lo <= fdate <= today:
                acc = (recent.get("accessionNumber") or [""] * len(forms))[i]
                doc = (recent.get("primaryDocument") or [""] * len(forms))[i]
                url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
                       if acc and doc else "")
                filings.append({"form": form, "date": fdate, "url": url})
        result["checked"].append({"company": key, "source": "SEC EDGAR", "status": "ok",
                                  "window": f"{lo}..{today}", "filings": filings[:3]})
    return result


def segment_gaps(segment_ids: list[str], routing: dict) -> list[dict]:
    scfg = (routing.get("primary_sources") or {}).get("segments") or {}
    return [{"segment": s, "source": scfg[s].get("label", ""), "reason": "not connected"}
            for s in segment_ids if s in scfg and not scfg[s].get("connected")]
