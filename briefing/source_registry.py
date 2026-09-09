"""Canonical source allowlist shared by news collection and rendering.

The briefing used to keep source names in several prompts and query strings.
This module is the single executable allowlist: collectors normalize to these
names and the final model output is checked against the same registry.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _source(canonical, aliases, domains, tier, group, topics):
    return {
        "canonical": canonical,
        "aliases": aliases,
        "domains": domains,
        "tier": tier,
        "group": group,
        "topics": topics,
    }


SOURCE_REGISTRY = {
    "bloomberg": _source("Bloomberg", ["Bloomberg (GN)"], ["bloomberg.com"], "A", "通訊社／財經", ["macro", "markets", "geopolitics", "ai", "semiconductor"]),
    "reuters": _source("Reuters", ["Reuters (GN)", "路透", "路透社"], ["reuters.com"], "A", "通訊社／財經", ["macro", "markets", "geopolitics", "ai", "semiconductor"]),
    "financial_times": _source("Financial Times", ["FT", "FT Markets", "FT Tech", "FT Asia"], ["ft.com"], "A", "通訊社／財經", ["macro", "markets", "geopolitics", "ai", "regional_europe"]),
    "wsj": _source("WSJ", ["The Wall Street Journal", "WSJ (GN)"], ["wsj.com"], "A", "通訊社／財經", ["macro", "markets", "ai"]),
    "cnbc": _source("CNBC", ["CNBC Top", "CNBC Tech"], ["cnbc.com"], "A", "通訊社／財經", ["macro", "markets", "ai"]),
    "barrons": _source("Barron's", ["Barrons", "Barron's (GN)"], ["barrons.com"], "B", "通訊社／財經", ["markets"]),
    "economist": _source("The Economist", ["The Economist (GN)", "Economist"], ["economist.com"], "B", "通訊社／財經", ["macro", "geopolitics", "longform"]),
    "axios": _source("Axios", [], ["axios.com"], "B", "通訊社／財經", ["macro", "geopolitics", "ai"]),
    "politico": _source("Politico", ["Politico (GN)"], ["politico.com"], "B", "通訊社／財經", ["geopolitics", "policy"]),
    "ap": _source("AP", ["Associated Press", "AP News"], ["apnews.com"], "A", "通訊社／財經", ["macro", "geopolitics"]),
    "bbc": _source("BBC", ["BBC News"], ["bbc.com", "bbc.co.uk"], "A", "通訊社／財經", ["macro", "geopolitics"]),
    "cnn_business": _source("CNN Business", [], ["cnn.com"], "B", "通訊社／財經", ["macro", "markets"]),
    "techcrunch": _source("TechCrunch", [], ["techcrunch.com"], "B", "科技", ["ai", "startup", "enterprise_ai"]),
    "the_information": _source("The Information", [], ["theinformation.com"], "B", "科技", ["ai", "enterprise_ai", "longform"]),
    "wired": _source("Wired", [], ["wired.com"], "B", "科技", ["ai", "longform"]),
    "ars_technica": _source("Ars Technica", [], ["arstechnica.com"], "B", "科技", ["ai", "longform"]),
    "mit_tech_review": _source("MIT Technology Review", ["MIT Tech Review"], ["technologyreview.com"], "B", "科技", ["ai", "longform"]),
    "crunchbase": _source("Crunchbase", ["Crunchbase News"], ["crunchbase.com"], "B", "科技", ["startup"]),
    "stat": _source("STAT News", ["STAT", "STAT News (GN)"], ["statnews.com"], "B", "醫療／生技", ["healthcare_ai"]),
    "endpoints": _source("Endpoints News", ["Endpoints", "Endpoints (GN)"], ["endpts.com"], "B", "醫療／生技", ["healthcare_ai"]),
    "fierce_biotech": _source("Fierce Biotech", ["Fierce Biotech (GN)"], ["fiercebiotech.com"], "B", "醫療／生技", ["healthcare_ai"]),
    "fierce_healthcare": _source("Fierce Healthcare", [], ["fiercehealthcare.com"], "B", "醫療／生技", ["healthcare_ai"]),
    "nature": _source("Nature", [], ["nature.com"], "A", "醫療／生技", ["healthcare_ai", "science"]),
    "science": _source("Science", [], ["science.org"], "A", "醫療／生技", ["healthcare_ai", "science"]),
    "nejm": _source("NEJM", ["New England Journal of Medicine"], ["nejm.org"], "A", "醫療／生技", ["healthcare_ai", "science"]),
    "jama": _source("JAMA", [], ["jamanetwork.com"], "A", "醫療／生技", ["healthcare_ai", "science"]),
    "fda": _source("FDA", ["U.S. FDA", "US FDA"], ["fda.gov"], "A", "醫療／生技", ["healthcare_ai", "policy"]),
    "digitimes": _source("DIGITIMES", ["Digitimes"], ["digitimes.com"], "B", "半導體／亞洲", ["semiconductor", "regional_asia"]),
    "trendforce": _source("TrendForce", ["TrendForce (GN)"], ["trendforce.com"], "B", "半導體／亞洲", ["semiconductor", "regional_asia"]),
    "semianalysis": _source("SemiAnalysis", [], ["semianalysis.com"], "B", "半導體／亞洲", ["semiconductor", "longform"]),
    "semiconductor_engineering": _source("Semiconductor Engineering", [], ["semiengineering.com"], "B", "半導體／亞洲", ["semiconductor"]),
    "ee_times": _source("EE Times", [], ["eetimes.com"], "B", "半導體／亞洲", ["semiconductor"]),
    "nikkei_asia": _source("Nikkei Asia", ["Nikkei Asia (GN)"], ["asia.nikkei.com"], "A", "半導體／亞洲", ["semiconductor", "regional_asia"]),
    "scmp": _source("South China Morning Post", ["SCMP", "SCMP Tech"], ["scmp.com"], "B", "半導體／亞洲", ["regional_asia", "ai"]),
    "cna": _source("中央社", ["Focus Taiwan", "Focus Taiwan／中央社", "CNA", "中央社 財經"], ["cna.com.tw", "focustaiwan.tw"], "A", "半導體／亞洲", ["regional_asia", "macro", "semiconductor"]),
    "moneydj": _source("MoneyDJ", ["MoneyDJ 國際財經", "MoneyDJ 台股", "MoneyDJ 科技產業", "MoneyDJ (GN)"], ["moneydj.com"], "B", "半導體／亞洲", ["markets", "regional_asia", "semiconductor"]),
    "ctee": _source("工商時報", ["工商時報 (GN)", "Commercial Times"], ["ctee.com.tw"], "B", "半導體／亞洲", ["macro", "regional_asia", "semiconductor"]),
    "yonhap": _source("Yonhap", ["Yonhap News Agency"], ["yna.co.kr"], "A", "半導體／亞洲", ["regional_asia", "semiconductor"]),
    "korea_herald": _source("Korea Herald", [], ["koreaherald.com"], "B", "半導體／亞洲", ["regional_asia", "semiconductor"]),
    "korea_joongang": _source("Korea JoongAng Daily", [], ["koreajoongangdaily.joins.com"], "B", "半導體／亞洲", ["regional_asia", "semiconductor"]),
    "caixin": _source("Caixin", [], ["caixinglobal.com"], "B", "半導體／亞洲", ["regional_asia", "macro"]),
    "coindesk": _source("CoinDesk", [], ["coindesk.com"], "B", "加密", ["fintech_crypto"]),
    "the_block": _source("The Block", [], ["theblock.co"], "B", "加密", ["fintech_crypto"]),
    "foreign_affairs": _source("Foreign Affairs", [], ["foreignaffairs.com"], "B", "政策／智庫", ["geopolitics", "longform"]),
    "rand": _source("RAND", ["RAND Corporation"], ["rand.org"], "B", "政策／智庫", ["geopolitics", "longform"]),
    "brookings": _source("Brookings", ["Brookings Institution"], ["brookings.edu"], "B", "政策／智庫", ["macro", "geopolitics", "longform"]),
    "fed": _source("Federal Reserve", ["Fed", "Federal Reserve Board"], ["federalreserve.gov"], "A", "政策／智庫", ["macro", "policy"]),
    "ecb": _source("ECB", ["European Central Bank"], ["ecb.europa.eu"], "A", "政策／智庫", ["macro", "policy"]),
    "boj": _source("BOJ", ["Bank of Japan"], ["boj.or.jp"], "A", "政策／智庫", ["macro", "policy"]),
    "bis": _source("BIS", ["Bank for International Settlements"], ["bis.org"], "A", "政策／智庫", ["macro", "policy"]),
    "imf": _source("IMF", ["International Monetary Fund"], ["imf.org"], "A", "政策／智庫", ["macro", "policy"]),
    "sec": _source("SEC", ["U.S. SEC", "US SEC"], ["sec.gov"], "A", "政策／智庫", ["policy", "markets"]),
    "fred": _source("FRED", ["Federal Reserve Economic Data"], ["fred.stlouisfed.org"], "A", "政策／智庫", ["macro"]),
    "gartner": _source("Gartner", [], ["gartner.com"], "B", "機構", ["ai", "enterprise_ai"]),
    "idc": _source("IDC", ["International Data Corporation"], ["idc.com"], "B", "機構", ["ai", "enterprise_ai"]),
    "mckinsey": _source("McKinsey", ["McKinsey & Company"], ["mckinsey.com"], "B", "機構", ["ai", "enterprise_ai", "longform"]),
    "goldman": _source("Goldman Sachs", ["Goldman"], ["goldmansachs.com"], "B", "機構", ["markets", "macro"]),
    "jpmorgan": _source("JP Morgan", ["JPMorgan", "JPMorgan Chase"], ["jpmorgan.com"], "B", "機構", ["markets", "macro"]),
    "barchart": _source("Barchart", [], ["barchart.com"], "B", "機構", ["markets"]),
    "earnings_whispers": _source("Earnings Whispers", [], ["earningswhispers.com"], "B", "機構", ["earnings"]),
}

BLACKLIST_TERMS = (
    "youtube", "tiktok", "twitter", "reddit", "facebook", "instagram",
    "medium", "substack", "pr newswire", "businesswire", "business wire",
    "globenewswire", "seeking alpha", "yahoo finance", "motley fool",
    "benzinga", "infoq",
)

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def _norm_name(value: str) -> str:
    value = re.sub(r"\s*\(gn\)\s*$", "", value or "", flags=re.I)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.casefold())


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


_ALIAS_TO_ID = {}
for _source_id, _spec in SOURCE_REGISTRY.items():
    for _name in [_spec["canonical"], *_spec["aliases"]]:
        _ALIAS_TO_ID[_norm_name(_name)] = _source_id


def source_from_domain(url: str) -> str | None:
    host = _host(url)
    if not host or host == "news.google.com":
        return None
    for source_id, spec in SOURCE_REGISTRY.items():
        if any(_domain_matches(host, domain) for domain in spec["domains"]):
            return source_id
    return None


def is_blacklisted(name: str = "", url: str = "") -> bool:
    haystack = f"{name} {_host(url)}".casefold()
    return any(term in haystack for term in BLACKLIST_TERMS)


def _canonicalize_one(name: str, url: str = "") -> str | None:
    if is_blacklisted(name, url):
        return None
    name_id = _ALIAS_TO_ID.get(_norm_name(name))
    domain_id = source_from_domain(url)
    host = _host(url)
    if host and host != "news.google.com" and not domain_id:
        return None
    if name_id and domain_id and name_id != domain_id:
        return None
    source_id = name_id or domain_id
    return SOURCE_REGISTRY[source_id]["canonical"] if source_id else None


def canonicalize_source(name: str, url: str = "") -> str | None:
    """Return canonical allowlisted source name(s), otherwise ``None``."""
    parts = [
        p.strip()
        for p in re.split(r"\s*(?:／|/|、|,|\band\b)\s*", name or "", flags=re.I)
        if p.strip()
    ]
    if len(parts) <= 1:
        return _canonicalize_one(name, url)
    canonical = []
    for part in parts:
        value = _canonicalize_one(part)
        if not value:
            return None
        if value not in canonical:
            canonical.append(value)
    return "／".join(canonical) if canonical else None


def is_allowed_source(name: str, url: str = "") -> bool:
    return canonicalize_source(name, url) is not None


def source_id_for(name: str, url: str = "") -> str | None:
    canonical = canonicalize_source(name, url)
    if not canonical or "／" in canonical:
        return None
    return _ALIAS_TO_ID.get(_norm_name(canonical))


def source_topics(name: str, url: str = "") -> list[str]:
    source_id = source_id_for(name, url)
    return list(SOURCE_REGISTRY[source_id]["topics"]) if source_id else []


def source_tier(name: str, url: str = "") -> str:
    source_id = source_id_for(name, url)
    return SOURCE_REGISTRY[source_id]["tier"] if source_id else "C"


def allowed_source_names(topics: list[str] | None = None) -> list[str]:
    wanted = set(topics or [])
    return [
        spec["canonical"]
        for spec in SOURCE_REGISTRY.values()
        if not wanted or wanted.intersection(spec["topics"])
    ]


def render_source_whitelist() -> str:
    groups = {}
    for spec in SOURCE_REGISTRY.values():
        groups.setdefault(spec["group"], []).append(spec["canonical"])
    return "\n".join(f"{group}：{'、'.join(names)}" for group, names in groups.items())


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_PARAMS
    ]
    host = (parts.hostname or "").casefold()
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme.casefold(), host, parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))
