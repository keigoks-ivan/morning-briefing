"""
weekly_fetcher.py
-----------------
使用 Perplexity API 搜尋四個深度主題的過去7天新聞。
"""

import os
import requests
from datetime import datetime
import pytz


WEEKLY_THEMES = {
    "ai_industry": {
        "name": "AI 產業發展",
        "queries": [
            "AI industry major developments this week funding acquisitions products. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC",
            "Large language model AI research breakthroughs this week. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC",
            "AI infrastructure data center investment this week. Sources: Bloomberg Reuters TechCrunch The Information Wired Ars Technica CNBC",
            "AI earnings results analyst reports this week Nvidia Microsoft Google. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "AI regulation policy developments this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "Earnings call transcripts AI commentary this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
        ],
    },
    "semiconductor": {
        "name": "半導體供應鏈",
        "queries": [
            "Semiconductor supply chain news this week TSMC Samsung ASML. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia TSMC Samsung official",
            "Chip demand inventory cycle update this week. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia",
            "Semiconductor capital expenditure fab expansion this week. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia",
            "Advanced packaging HBM memory supply demand this week. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia",
            "Semiconductor analyst reports price target changes this week. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia",
            "Earnings call semiconductor commentary this week. Sources: Bloomberg Reuters Digitimes SemiAnalysis EE Times Nikkei Asia",
        ],
    },
    "macro": {
        "name": "全球景氣狀況",
        "queries": [
            "Global economy indicators this week GDP inflation employment. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB",
            "Central bank Fed ECB BOJ policy signals this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB",
            "PMI manufacturing services data this week global. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB",
            "Credit markets high yield investment grade spreads this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "Consumer spending retail sales economic data this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC Federal Reserve ECB",
            "Recession probability leading indicators this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
        ],
    },
    "black_swan": {
        "name": "黑天鵝與灰犀牛",
        "queries": [
            "Geopolitical risk escalation this week tail risk. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs",
            "Financial system stress signals this week credit banking. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "Known but ignored risks gray rhino economic this week. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs",
            "Unexpected market events volatility spike this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "Systemic risk indicators this week. Sources: Bloomberg Reuters Financial Times WSJ CNBC",
            "Black swan potential events emerging risks this week. Sources: Bloomberg Reuters Financial Times WSJ Foreign Affairs",
        ],
    },
}


def fetch_weekly_news(theme_key: str) -> list[dict]:
    """Fetch weekly news for a specific theme."""
    theme = WEEKLY_THEMES[theme_key]
    api_key = os.environ["PERPLEXITY_API_KEY"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    tz = pytz.timezone("Asia/Taipei")
    today = datetime.now(tz).strftime("%Y-%m-%d")

    results = []
    for query in theme["queries"]:
        try:
            payload = {
                "model": "sonar",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Today is {today} Taiwan time (UTC+8). "
                            "Report on developments from the past 7 days. "
                            "Include specific numbers, dates, company names, and source names. "
                            "Provide detailed analysis, not just headlines. "
                            "Never include ESG, sustainability, or green energy related news."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                "search_recency_filter": "week",
                "return_citations": True,
                "max_tokens": 1200,
            }
            resp = requests.post(
                "https://api.perplexity.ai/chat/completions",
                headers=headers, json=payload, timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            results.append({"query": query, "answer": answer, "sources": citations[:5]})
            print(f"  ✓ [{theme_key}] {query[:60]}... ({len(citations)} sources)")
        except Exception as e:
            print(f"  ✗ [{theme_key}] {query[:60]}... — {e}")
            results.append({"query": query, "answer": "", "sources": []})

    return results
