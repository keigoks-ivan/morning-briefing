"""
evidence_questions.py
---------------------
事件判斷層問 Jev 的題目（全部預先定義選項），以及把答案轉成程式可用的欄位。

分工（2026-09-22 定）：
- Jev 只回答「今天這段文字裡寫了什麼」：新舊、事實階段、每個經濟變數是否被直接提到、
  方向、重要度、出處類型、候選公司是不是當事人。
- Jev 不回答：公司名（程式給候選）、會不會漲、該不該買、投資論述。
- 一則新聞可以同時影響多個變數：每個變數各問一題 Choice，不用單一 Choice 逼選一個。
- 題目用英文（Jev 英文最準）；state 裡的舊中文紀錄照原文帶，程式另附正規化後的數字。
"""

from __future__ import annotations

# 變數 id、讀者看的名稱、給 Jev 的定義
VARIABLES = [
    ("demand", "Demand",
     "Demand: orders, bookings, customer purchases, users or paid seats, end-market sales"),
    ("supply_capacity", "Supply and capacity",
     "Supply and capacity: production capacity or output that is in operation, plant or line capacity, supply availability, shortages"),
    ("shipments", "Shipments",
     "Shipments: units or value shipped, exported or delivered during a past period"),
    ("price", "Price",
     "Price: selling prices, contract prices, average selling prices, price increases or cuts"),
    ("cost", "Cost",
     "Cost: input costs, unit costs, energy, labour or interest costs"),
    ("capex", "Capex",
     "Capital spending: money committed to plants, data centres, equipment, construction, or equity stakes in infrastructure companies"),
    ("financing", "Financing",
     "Financing: debt or equity raised or being sought, bond sales, loans, credit ratings and credit risk"),
    ("competition", "Competition",
     "Competition: market share, rival products, customers switching suppliers, new entrants"),
    ("market_valuation", "Market valuation",
     "Market valuation: share prices, market capitalisation, valuation multiples"),
    ("rates_policy", "Rates and policy",
     "Rates and policy: interest rates, central-bank decisions, tariffs, export controls, subsidies, regulation"),
]
# 2026-09-22：總經新聞用自己的一組變數（同一則也可以兩組都問，見 evidence_layer.candidate_kind）
MACRO_VARIABLES = [
    ("inflation", "Inflation",
     "Inflation: consumer or producer prices, wage growth, inflation expectations"),
    ("growth", "Growth",
     "Growth and activity: GDP, output, retail sales, business surveys, industrial production"),
    ("labor", "Labour market",
     "Labour market: payrolls, unemployment, jobless claims, hiring"),
    ("policy_rate", "Policy rate",
     "Policy rate: a central bank's interest-rate decisions, its guidance on future rate moves, or its balance-sheet policy"),
    ("bond_yields", "Bond yields",
     "Bond yields: government bond yields and borrowing costs in bond markets"),
    ("fx", "Currencies",
     "Currencies: exchange rates, dollar strength, currency intervention"),
    ("credit_liquidity", "Credit and liquidity",
     "Credit and liquidity: credit spreads, bank lending, bank reserves, funding markets"),
    ("trade", "Trade and tariffs",
     "Trade: exports, imports, tariffs, export controls, trade agreements or talks"),
    ("fiscal", "Fiscal",
     "Fiscal: government spending, deficits, taxes, government debt issuance"),
]
VAR_LABEL = {v: label for v, label, _ in VARIABLES + MACRO_VARIABLES}
_VAR_DEF = {v: d for v, _, d in VARIABLES + MACRO_VARIABLES}
COMPANY_VAR_IDS = [v for v, _, _ in VARIABLES]
MACRO_VAR_IDS = [v for v, _, _ in MACRO_VARIABLES] + ["market_valuation"]

NOVELTY_DISPLAY = {
    "new_fact": "New evidence",
    "progress_update": "Progress update",
    "known_restatement": "Known, restated",
    "market_move_only": "Market move only",
    "insufficient_evidence": "Insufficient evidence",
}
STAGE_DISPLAY = {
    "plan_or_intent": "Plan or intent",
    "filing_or_offering": "Filed or offering launched",
    "agreement_signed": "Agreed or signed",
    "construction_started": "Construction started",
    "production_or_launch": "In production or launched",
    "shipped_or_delivered": "Shipped or delivered",
    "completed_or_closed": "Completed or closed",
    "reported_result": "Company-reported result",
    "official_statistic": "Official statistic",
    "market_price_only": "Market price only",
    "policy_decision": "Policy decision taken",
    "official_comment": "Official comment, no decision",
    "forecast_or_estimate": "Forecast or estimate",
    "unclear": "Unclear",
}
STAGE_ORDER = ["plan_or_intent", "filing_or_offering", "agreement_signed", "construction_started",
               "production_or_launch", "shipped_or_delivered", "completed_or_closed"]
ATTRIBUTION_DISPLAY = {
    "company_statement": "Company statement",
    "filing_or_official_data": "Filing or official data",
    "named_media_report": "Media report",
    "unnamed_sources": "Unnamed sources",
    "commentary_or_analysis": "Commentary",
    "official_statement": "Official's statement",
}
# 2026-09-23 新增：只記錄供之後校準用，不進排序／分道／分類／派送規則，見 evidence_layer.py 的用法註解
TIMING_DISPLAY = {
    "already_in_effect": "Already in effect",
    "this_quarter": "This quarter",
    "within_12_months": "Within 12 months",
    "one_to_three_years": "1–3 years out",
    "beyond_three_years": "More than 3 years out",
    "unclear": "Timing unclear",
}

_NOVELTY = {
    "type": "choice",
    "instructions": {
        "question": (
            "Compare `today` with `prior_records`. `prior_records` are facts about the same companies or economic topics that were "
            "recorded before today; an empty list means nothing related was recorded. Judge only what `today` "
            "states as fact, and ignore its opinions, analysis and forecasts. What does `today` add?"
        ),
        "note": "`prior_records[].figures` lists each record's figures in one normalised form, so 30 million and 30M are the same number. Some prior records are written in Chinese.",
    },
    "criteria": {
        "new_fact": "`today` states a fact (a transaction, figure, decision, data release, filing or result) that is not in `prior_records`, including a second, separate transaction between parties that dealt before, or a data release for a new period",
        "progress_update": "`today` says that a plan, project or process already in `prior_records` reached a later stage, such as construction starting on a planned site or approval of a filed application",
        "known_restatement": "`today` repeats a fact or figure already in `prior_records`, without a new figure, a new transaction, or a later stage",
        "market_move_only": "`today` only reports share-price, index, bond-yield or market-value moves and gives no new fact about businesses or the economy",
        "insufficient_evidence": "`today` is too vague to tell what happened: no named party, figure or action, or it only relays unnamed speculation",
    },
}

_STAGE = {
    "type": "choice",
    "instructions": (
        "What is the most advanced stage that `today` states as already reached for its main business fact? "
        "Choose the stage actually reached, not a stage that is planned for later."
    ),
    "criteria": {
        "plan_or_intent": "Only a plan, target, intention, memorandum or consideration; nothing signed, filed or started",
        "filing_or_offering": "An application, registration or filing was submitted, or a bond or share offering was launched but not yet priced or closed",
        "agreement_signed": "A deal, investment or order was agreed or signed, or a purchase is under way but not stated as completed",
        "construction_started": "Ground was broken or construction or installation began; nothing is producing yet",
        "production_or_launch": "Production, a service or a product is running or on sale",
        "shipped_or_delivered": "Goods were shipped or delivered during a stated past period",
        "completed_or_closed": "A transaction closed, money was raised and settled, or an acquisition completed",
        "reported_result": "The company reported financial or operating figures for a past period",
        "official_statistic": "A government body or official agency published statistics for a past period",
        "market_price_only": "Only share-price, index or market-value moves",
        "policy_decision": "A central bank, government or regulator decided or put into effect a measure, such as a rate change, a tariff or a rule",
        "official_comment": "An official gave a view, guidance or a warning; no decision was taken",
        "forecast_or_estimate": "A forecast, projection or estimate about the future by a company, agency or analyst",
        "unclear": "`today` does not make the stage clear",
    },
}

_IMPORTANCE = {
    "type": "score",
    "instructions": "How material is the business fact in `today` to the revenue, costs, capacity or funding of the companies or industry involved?",
    "criteria": [
        "No business fact: only a share-price move, a restated old figure, or commentary",
        "A small or routine detail for one company, such as a minor product update or a small deal",
        "A material fact for one company, such as a multi-billion-dollar investment, a plant starting construction, or a large financing",
        "A material fact for a whole industry segment or several major companies, such as national export data, an industry-wide price change, or a major policy decision",
    ],
}

_ATTRIBUTION = {
    "type": "choice",
    "instructions": "Who is the stated source of the main fact in `today`?",
    "criteria": {
        "company_statement": "The company itself announced or confirmed it",
        "official_statement": "A named government, central-bank or regulatory official said it",
        "filing_or_official_data": "A regulatory filing, court record, or government or agency statistics",
        "named_media_report": "A named news outlet reports it, citing documents or named people",
        "unnamed_sources": "It relies on unnamed people, 'people familiar with the matter', or 'reportedly'",
        "commentary_or_analysis": "It is an analyst's, columnist's or market commentator's view",
    },
}

# 2026-09-23 新增：主要事實何時實際對營運／總經產生效果（不是何時被公布）。目前只顯示、不進任何判斷規則。
_TIMING = {
    "type": "choice",
    "instructions": (
        "When does the main business or economic fact in `today` actually take effect, not when it was "
        "announced? Judge only from dates or periods `today` states. A plan with a stated start date uses "
        "that date. A plant or line said to begin production in a stated quarter or year uses that period. "
        "A rate, price or rule already in force is 'already in effect'. Do not guess a timeline `today` does "
        "not state; choose 'unclear' instead."
    ),
    "criteria": {
        "already_in_effect": "The effect is already in force: a decision has taken effect, a plant is already producing, a rate, price or rule already applies",
        "this_quarter": "`today` states the effect starts, ships or lands within the current calendar quarter",
        "within_12_months": "`today` states or clearly implies a start date beyond this quarter but within about a year",
        "one_to_three_years": "`today` states a start date, completion date or milestone one to three years out, such as a plant slated to begin production in a stated later year",
        "beyond_three_years": "`today` states a start date, completion date or milestone more than three years out",
        "unclear": "`today` states no date, period or stage from which the timing of the effect can be judged",
    },
}


def _var_question(var_id: str, definition: str) -> dict:
    return {
        "type": "choice",
        "instructions": {
            "variable": definition,
            "question": (
                "How does what `today` states as fact bear on `variable`? Ignore forecasts, opinions and "
                "'could', 'may' or 'suggests' statements."
            ),
        },
        "criteria": {
            "direct": "`today` states as fact a change in `variable` itself for the companies or industry involved",
            "indirect": (
                "`today` does not state a change in `variable`, but it states a concrete fact and describes the one "
                "step by which that fact will change `variable` for these companies, for example a bond sale said to "
                "pay for chip purchases, or a plant under construction that will add capacity. A general effect that "
                "almost any business news could have on `variable` does not count"
            ),
            "none": "`today` gives no basis for a change in `variable`",
        },
    }


def _dir_question(var_id: str, definition: str) -> dict:
    return {
        "type": "choice",
        "instructions": {
            "variable": definition,
            "question": "If `today` bears on `variable`, which way does it push `variable` for the companies or industry involved?",
        },
        "criteria": {
            "up": "More, higher, or larger",
            "down": "Less, lower, or smaller",
            "mixed_or_unclear": "Mixed, unclear, or `today` does not bear on `variable`",
        },
    }


def _party_question(i: int) -> dict:
    return {
        "type": "noul",
        "instructions": (
            f"In `today`, is `candidate_companies[{i}]` itself a party to the main business fact (it invests or is "
            "invested in, builds, sells, buys, raises money, or reports the figures), rather than only being "
            "mentioned for comparison, background, or a share-price move?"
        ),
        "criteria": {
            "true": "The company is one of the parties that did or received the main business action",
            "false": "The company is only mentioned for comparison, background, or its share price",
        },
    }


def build_questions(n_companies: int, var_ids: list[str] | None = None) -> dict:
    """var_ids：要問哪些變數（預設公司那組）。每個變數一題 Choice＋一題方向。
    timing：每則都問（公司與總經都要），2026-09-23 新增，見 _TIMING 註解。"""
    qs = {"novelty": _NOVELTY, "stage": _STAGE, "importance": _IMPORTANCE, "attribution": _ATTRIBUTION,
          "timing": _TIMING}
    for var_id in var_ids or COMPANY_VAR_IDS:
        definition = _VAR_DEF[var_id]
        qs[f"var_{var_id}"] = _var_question(var_id, definition)
        qs[f"dir_{var_id}"] = _dir_question(var_id, definition)
    for i in range(n_companies):
        qs[f"party_{i}"] = _party_question(i)
    return qs


def interpret(answers: dict, company_keys: list[str], *, var_min_conf: float) -> dict:
    """Jev 原始答案 → 結構化判斷。不做任何「最終分類」，那是 evidence_layer 的規則。"""
    def choice(qid):
        a = answers.get(qid) or {}
        return {"label": a.get("choice"), "confidence": round(float(a.get("confidence") or 0), 3),
                "probabilities": a.get("probabilities") or {}}

    variables = {}
    for var_id, label in VAR_LABEL.items():
        if f"var_{var_id}" not in answers:
            continue   # 這一則沒問這個變數
        link = choice(f"var_{var_id}")
        direction = choice(f"dir_{var_id}")
        variables[var_id] = {
            "label": label,
            "link": link["label"] if link["confidence"] >= var_min_conf else "uncertain",
            "raw_link": link["label"],
            "confidence": link["confidence"],
            "direction": direction["label"],
            "dir_confidence": direction["confidence"],
        }
    imp = answers.get("importance") or {}
    parties = {}
    for i, key in enumerate(company_keys):
        a = answers.get(f"party_{i}") or {}
        if isinstance(a.get("noul"), (int, float)):
            parties[key] = round(float(a["noul"]), 3)
    return {
        "novelty": choice("novelty"),
        "stage": choice("stage"),
        "timing": choice("timing"),
        "attribution": choice("attribution"),
        "importance": {"score": round(float(imp.get("score") or 0), 2),
                       "confidence": round(float(imp.get("confidence") or 0), 3)},
        "variables": variables,
        "parties": parties,
    }
