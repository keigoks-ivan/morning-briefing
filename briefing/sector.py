"""
sector.py
---------
news 頁「依產業分區」用的 sector 列舉值與推定規則（2026-10-08，見 CLAUDE.md）。
html_template 與 ai_processor 共用；不依賴任何網路／模型套件。
"""
from __future__ import annotations

import re

SECTORS = [
    "AI and semiconductors",
    "Energy and power",
    "Industrials, defense and logistics",
    "Healthcare and biotech",
    "Consumer and retail",
    "Software and internet",
    "Finance and macro",
    "Policy and regulation",
]
OTHER_SECTOR = "Other"

SECTOR_SLUGS = {
    "AI and semiconductors": "ai-semis",
    "Energy and power": "energy",
    "Industrials, defense and logistics": "industrials",
    "Healthcare and biotech": "healthcare",
    "Consumer and retail": "consumer",
    "Software and internet": "software",
    "Finance and macro": "finance-macro",
    "Policy and regulation": "policy",
    OTHER_SECTOR: "other",
}

# casefold + 去空白／標點後比對，容忍模型把 "and" 寫成 "&" 或加逗號
_SECTOR_ALIASES = {re.sub(r"[^a-z]", "", s.casefold().replace("&", "and")): s for s in SECTORS}
_SECTOR_ALIASES["other"] = OTHER_SECTOR

_INDUSTRY_TO_SECTOR = {
    "semiconductors": "AI and semiconductors",
    "ai infrastructure": "AI and semiconductors",
    "enterprise software and security": "Software and internet",
    "robotics and automation": "Industrials, defense and logistics",
    "defense and aerospace": "Industrials, defense and logistics",
    "energy and logistics": "Industrials, defense and logistics",
    "healthcare and biotech": "Healthcare and biotech",
    "fintech": "Finance and macro",
}

_ENERGY_RE = re.compile(r"\b(power|grid|utility|utilities|nuclear|solar|lng|oil|gas|electricity|wind|reactor|crude)\b", re.I)

# 標題／內文關鍵字（順序即優先序）
_KEYWORD_RULES = [
    ("Policy and regulation", re.compile(
        r"\b(tariffs?|export controls?|sanctions?|regulat\w*|antitrust|election|ban|lawsuit|congress|senate|"
        r"white house|commission|ruling|court)\b", re.I)),
    ("Finance and macro", re.compile(
        r"\b(fed|federal reserve|ecb|boj|central bank|rate cut|rate hike|interest rates?|inflation|cpi|yields?|"
        r"treasury|bond|currency|yen|dollar|euro|credit|bank|banks|crypto|bitcoin|stablecoin|gdp|payrolls|fintech)\b",
        re.I)),
    ("Energy and power", re.compile(
        r"\b(power|grid|utility|utilities|nuclear|solar|lng|oil|natural gas|electricity|wind|reactor|crude|opec)\b",
        re.I)),
    ("AI and semiconductors", re.compile(
        r"\b(chips?|semiconductors?|nvidia|tsmc|hbm|gpu|foundry|wafer|asml|data cent(?:er|re)s?|openai|"
        r"ai infrastructure|artificial intelligence|\bai\b)\b", re.I)),
    ("Healthcare and biotech", re.compile(
        r"\b(fda|drug|biotech|pharma\w*|clinical|vaccine|hospital|therapy|medical)\b", re.I)),
    ("Industrials, defense and logistics", re.compile(
        r"\b(defense|defence|aerospace|shipping|rail|freight|logistics|robot\w*|airline|boeing|drone|missile|"
        r"manufactur\w*|factory)\b", re.I)),
    ("Software and internet", re.compile(
        r"\b(software|saas|cloud|cybersecurity|security|app|platform|search|social media|internet|browser)\b", re.I)),
    ("Consumer and retail", re.compile(
        r"\b(retail\w*|consumer|apparel|restaurant|e-commerce|ecommerce|walmart|amazon|spending|brand|autos?|"
        r"electric vehicles?|ev)\b", re.I)),
]


def _clean(value) -> str:
    return re.sub(r"[^a-z]", "", str(value or "").casefold().replace("&", "and"))


def normalize_sector(block: str, item: dict) -> str:
    """回傳合法 sector（SECTORS 之一或 'Other'）。sector 缺或不合法時依 block／industry／關鍵字推定。"""
    item = item if isinstance(item, dict) else {}
    valid = _SECTOR_ALIASES.get(_clean(item.get("sector")))
    if valid:
        return valid
    headline = str(item.get("headline") or "")
    if block == "industry_developments":
        industry = re.sub(r"\s+", " ", str(item.get("industry") or "")).strip().casefold()
        mapped = _INDUSTRY_TO_SECTOR.get(industry)
        if mapped == "Industrials, defense and logistics" and industry == "energy and logistics":
            if _ENERGY_RE.search(headline):
                return "Energy and power"
        if mapped:
            return mapped
    elif block in ("macro", "fintech_crypto"):
        return "Finance and macro"
    elif block == "geopolitical":
        return "Policy and regulation"
    elif block == "ai_industry":
        return "AI and semiconductors"
    text = f"{headline} {item.get('body') or ''}"
    head_only = headline
    for scope in (head_only, text):
        for sector, rx in _KEYWORD_RULES:
            if rx.search(scope):
                return sector
    return OTHER_SECTOR
