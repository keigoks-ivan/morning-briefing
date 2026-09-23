"""
ai_processor.py
---------------
三個區塊（分析 / 新聞 / 財報深度分析）並行生成結構化 JSON。

模型路由（2026-08-17 改制）：
  主要   Claude Code CLI headless（`claude -p`）→ 走 Max 訂閱，不耗 API 額度
  備援1  Gemini（Pro 分析 / Flash 新聞）→ 需 GEMINI_API_KEY
  備援2  Anthropic API SDK → 需 ANTHROPIC_API_KEY

Claude Code 路徑需要 `CLAUDE_CODE_OAUTH_TOKEN`（本機 `claude setup-token` 產生，
存成 GitHub secret）。任一層失敗自動往下掉，所以日報不會因訂閱認證問題斷掉。
"""

import os
import json
import hashlib
import shutil
import subprocess
import anthropic
from google import genai
from google.genai import types
from concurrent.futures import ThreadPoolExecutor, as_completed

from source_registry import canonicalize_source, render_source_whitelist


# ═══════════════════════════════════════════════════════════════
# Claude Code CLI（headless）— 主要路徑，走 Max 訂閱
# ═══════════════════════════════════════════════════════════════

# 用最新 Sonnet。要換模型設環境變數 CLAUDE_CODE_MODEL 即可（"sonnet" 也是有效別名）。
CLAUDE_CODE_MODEL = os.environ.get("CLAUDE_CODE_MODEL", "claude-sonnet-5")
# 逾時要留足夠餘裕給 Gemini fallback 在 workflow timeout 內跑完（三條並行）。
CLAUDE_CODE_TIMEOUT = int(os.environ.get("CLAUDE_CODE_TIMEOUT", "900"))
# 分析／財報兩條的思考預算（新聞整理固定 0）。0 = 關。
CLAUDE_CODE_THINKING = int(os.environ.get("CLAUDE_CODE_THINKING", "8000"))


# claude -p 是「代理人」不是「補全 API」：素材不足時它會停下來反問、要求上網、拒絕湊數
# （實測 3 條假新聞就觸發）。這段附加指令把它釘回無人值守 pipeline 的角色。
_PIPELINE_GUARD = """
[EXECUTION ENVIRONMENT — HIGHEST PRIORITY]
You are running inside an unattended automated pipeline. Nobody will read a question from you or reply to you.
- Output exactly one valid JSON object, from `{` to `}`, with no preamble, heading, or markdown code fence.
- Never ask a question, never offer options, never request more material, never explain why you cannot do something.
- When material is thin: fill what the material supports and leave the rest as empty arrays `[]` or empty strings `""`. Never invent a story, a source, or a number to fill space.
- Do not use any tools. Do not browse.
"""


# Claude Code CLI 若同時看到 ANTHROPIC_API_KEY 與 OAuth token，會優先用 API key
# 計費到 Console（2026-08-17 實際被扣款才發現）。CLI 子程序一律拿掉 API 相關變數，
# 只留 CLAUDE_CODE_OAUTH_TOKEN，確保走月租；SDK 備援仍用 os.environ 裡的 key。
_API_ENV_KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def _cli_env() -> dict:
    env = dict(os.environ)
    for k in _API_ENV_KEYS:
        env.pop(k, None)
    return env


# 2026-09-19：`claude -p` 會讀跑它那台機器的 user／project 設定（~/.claude/CLAUDE.md、
# output style）。本機試跑時 Haiku 因此用中文作答、語氣也跟著跑掉——日報改英文後這是
# 會安靜污染輸出的坑。`--restricted` 讓子程序忽略這些設定檔，順便拿掉 Bash 等
# 執行工具（pipeline 本來就不該給）。舊版 CLI 不認這個旗標，所以偵測一次再決定用不用。
_RESTRICTED_FLAG: "bool | None" = None


def _supports_restricted(cli: str) -> bool:
    """偵測一次 `--restricted` 是否可用，結果快取。"""
    global _RESTRICTED_FLAG
    if _RESTRICTED_FLAG is None:
        try:
            out = subprocess.run([cli, "-p", "--help"], capture_output=True, text=True, timeout=30)
            _RESTRICTED_FLAG = "--restricted" in (out.stdout or "") + (out.stderr or "")
        except Exception:
            _RESTRICTED_FLAG = False
        if not _RESTRICTED_FLAG:
            print("  ⚠ claude CLI 不支援 --restricted，子程序會沿用本機設定")
    return _RESTRICTED_FLAG


def _call_claude_code(system_prompt: str, user_prompt: str, label: str,
                      thinking_tokens: int = 0) -> dict:
    """用 Claude Code CLI 跑一次 prompt，回傳解析好的 JSON dict。

    `--allowed-tools ""` 讓它純文字生成不動工具（這三個任務都只是把輸入轉成
    JSON，不需要讀檔或上網）。thinking 預設關（實測開著會拖到 8 分鐘以上，
    這類「整理成 JSON」任務不需要）。失敗一律 raise，讓上層 fallback 接手。
    """
    cli = shutil.which("claude")
    if not cli:
        raise RuntimeError("claude CLI not found on PATH")
    if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("CLAUDE_CODE_USE_LOCAL_AUTH")):
        raise RuntimeError("CLAUDE_CODE_OAUTH_TOKEN not set")

    env = _cli_env()
    env["MAX_THINKING_TOKENS"] = str(thinking_tokens)

    # 月租是唯一主路徑（Gemini 已停用），所以這裡自己重試兩次再放棄，
    # 免得一次網路抖動就讓整個區塊空掉。JSON 解析也在迴圈內——2026-08-17 首跑
    # 新聞區塊回了 262 token 的散文而非 JSON（素材因 Perplexity 429 極少），
    # 重試時把「上次回的不是 JSON」釘進去再打一次。
    max_attempts = 3
    last_bad_head = ""
    for attempt in range(1, max_attempts + 1):
        guard = _PIPELINE_GUARD
        if last_bad_head:
            guard += ("\n[YOUR LAST ATTEMPT BROKE THE RULES] It began with: \"" + last_bad_head +
                      "\" — that is not JSON. This time the first character must be `{`, with no explanation. "
                      "If the material is thin, emit the JSON skeleton with every field empty.\n")
        cmd = [
            cli, "-p",
            "--output-format", "json",
            "--model", CLAUDE_CODE_MODEL,
            "--system-prompt", system_prompt + "\n" + guard,
            "--allowed-tools", "",
        ]
        if _supports_restricted(cli):
            cmd.insert(2, "--restricted")
        print(f"  → [{label} / Claude Code] Calling {CLAUDE_CODE_MODEL} "
              f"(Max 訂閱, thinking={thinking_tokens}, attempt {attempt}/{max_attempts})...")
        try:
            proc = subprocess.run(
                cmd,
                input=user_prompt,
                capture_output=True,
                text=True,
                timeout=CLAUDE_CODE_TIMEOUT,
                cwd="/tmp",
                env=env,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude CLI exited {proc.returncode}: {(proc.stderr or proc.stdout)[:300]}"
                )
            envelope = json.loads(proc.stdout)
            if envelope.get("is_error") or envelope.get("subtype") != "success":
                raise RuntimeError(f"claude CLI error envelope: {str(envelope)[:300]}")
            raw_text = envelope.get("result") or ""
            if not raw_text.strip():
                raise RuntimeError("claude CLI returned empty result")

            usage = envelope.get("usage", {}) or {}
            in_tok = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0) \
                + usage.get("cache_read_input_tokens", 0)
            out_tok = usage.get("output_tokens", 0)
            # 訂閱制不另計費；印出的 cost 是 API 等價參考值，不是實際帳單。
            notional = envelope.get("total_cost_usd", 0.0)
            print(f"  → [{label} / Claude Code] tokens: in={in_tok:,} out={out_tok:,} "
                  f"(訂閱制，API 等價 ${notional:.4f})")
            with open(f"/tmp/claude_code_{label.lower().replace(' ', '_')}_raw.txt", "w") as f:
                f.write(raw_text)

            try:
                return _parse_json(raw_text)
            except json.JSONDecodeError as e:
                last_bad_head = raw_text.strip().replace("\n", " ")[:80]
                raise RuntimeError(f"non-JSON reply (head: {last_bad_head!r}): {e.msg}")
        except Exception as e:
            if attempt == max_attempts:
                raise
            print(f"  ⚠ [{label} / Claude Code] attempt {attempt} failed ({str(e)[:160]}), retrying in 30s...")
            import time
            time.sleep(30)


def _cc_analysis(market_context: str, news_text: str) -> dict:
    """分析區塊 — Claude Code 主路徑。"""
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )
    return _call_claude_code(CLAUDE_SYSTEM_PROMPT, user_prompt, "Analysis",
                             thinking_tokens=CLAUDE_CODE_THINKING)


def _news_date_window() -> tuple[str, str]:
    """回 (今日台北日期, 允收起始日)。平日回看 2 天；週一回看到上週五（含週末幾乎沒新聞）。"""
    import pytz
    from datetime import datetime, timedelta
    now = datetime.now(pytz.timezone("Asia/Taipei"))
    back = 3 if now.weekday() == 0 else 2
    return now.strftime("%Y-%m-%d"), (now - timedelta(days=back)).strftime("%Y-%m-%d")


def _last_us_session_date() -> str:
    """台北早報跑的時間點，「剛結束的那個 US session」是哪一天（美東日期）。
    台北 D 日早上 → 美股最近收盤是 D-1；D-1 若落在週末就往回退到週五。"""
    import pytz
    from datetime import datetime, timedelta
    d = datetime.now(pytz.timezone("Asia/Taipei")).date() - timedelta(days=1)
    while d.weekday() >= 5:            # 5=六 6=日
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _watchlist_block(watchlist: list[dict] | None) -> tuple[str, int]:
    """關注清單 → 兩組文字：
    【優先組】S 級全部＋A 級且 QGM 4 條件通過 ≥3；【其他組】剩下的。
    模型先從優先組挑，其他組只有重大事件才進。沒有清單回（「（無）」, 0）。"""
    if not watchlist:
        return "(none)", 0
    order = {"S": 0, "A": 1, "B": 2, "C": 3}

    def _tok(w):
        t = str(w.get("ticker", "")).strip()
        g = str(w.get("grade", "") or "")
        pc = w.get("pass_count")
        name = str(w.get("name", "") or "")
        extra = f"={name}" if name and name.upper() != t.upper() and len(name) <= 24 else ""
        pcs = f"/{pc}" if isinstance(pc, int) else ""
        return f"{t}({g}{pcs}){extra}"

    pri, rest = [], []
    for w in sorted(watchlist, key=lambda w: (order.get(str(w.get("grade", "")), 9), -(w.get("pass_count") or 0), str(w.get("ticker", "")))):
        if not str(w.get("ticker", "")).strip():
            continue
        g = str(w.get("grade", "") or "")
        pc = w.get("pass_count") or 0
        (pri if (g == "S" or (g == "A" and pc >= 3)) else rest).append(_tok(w))
    text = (f"[PRIORITY GROUP | {len(pri)} names, format ticker(moat grade/QGM passes)]\n{' '.join(pri)}\n"
            f"[OTHER GROUP | {len(rest)} names, major events only]\n{' '.join(rest)}")
    return text, len(pri) + len(rest)


def _cc_news(news_text: str, earnings_context: str, watchlist: list[dict] | None = None) -> dict:
    """新聞區塊 — Claude Code 主路徑。"""
    today, cutoff = _news_date_window()
    wl_text, wl_n = _watchlist_block(watchlist)
    user_prompt = GEMINI_USER_PROMPT_TEMPLATE.format(
        news_text=news_text,
        earnings_context=earnings_context,
        today=today,
        cutoff_date=cutoff,
        last_session=_last_us_session_date(),
        watchlist_block=wl_text,
        watchlist_count=wl_n,
    )
    return _call_claude_code(GEMINI_SYSTEM_PROMPT, user_prompt, "News")


def _cc_earnings(earnings_raw_text: str, market_context: str) -> dict:
    """財報深度分析 — Claude Code 主路徑。無當日財報時直接跳過，不燒額度。"""
    if not _has_earnings_content(earnings_raw_text):
        print("  ⚠ [Earnings Analysis] 當日無實質財報資料，跳過 LLM 呼叫")
        return {"has_content": False, "companies": [], "industry_trends": [],
                "winners": [], "losers": [], "contradictions": [],
                "conclusion": "", "window": "", "overview": ""}

    user_prompt = EARNINGS_ANALYSIS_USER_TEMPLATE.format(
        earnings_raw_text=earnings_raw_text,
        market_context=market_context or "(none)",
    )
    return _call_claude_code(EARNINGS_ANALYSIS_SYSTEM_PROMPT, user_prompt, "Earnings",
                             thinking_tokens=CLAUDE_CODE_THINKING)


DYNAMIC_STATUS_OPTIONS = """
Dynamic dimensions available (pick the 3 most relevant today):
- Fed stance, ECB stance, BOJ stance
- Geopolitical oil risk, semiconductor supply chain, China tech risk
- Earnings season progress, US dollar / DXY, yen
- Credit spreads, IPO / market sentiment, regulatory policy risk
- MYR rate, Taiwan market technicals
"""

# ═══════════════════════════════════════════════════════════════
# Gemini Prompt — 新聞整理區塊
# ═══════════════════════════════════════════════════════════════

GEMINI_SYSTEM_PROMPT = """
You are a financial news editor writing for a systematic investor. The reader's core position is an index book
(QQQ / SMH / 0050 / 2330, run by a weekly-trend x volatility engine) plus single names in the US and Taiwan.
Your job: extract, summarise and classify news from the search results and RSS headlines below, and emit strict JSON.

[FIRST PRINCIPLE: BETTER SHORT THAN PADDED]
- Every block gives you a CEILING, not a floor. If the material cannot carry it, write fewer items or leave the array empty.
  **Never pad with old news, numberless generalities, or events recalled from your own memory.**
- An item qualifies only if all three hold: (a) it is genuinely in the material; (b) its source_date falls in the accepted window given below;
  (c) its body carries at least one concrete number or one named entity. Miss any one and drop it.
- You cannot browse. Anything not in the material does not exist.

[DATE RULES — HARD]
- Accept only items whose source_date is on or after the cutoff date (given in the user message). Each RSS line is timestamped and
  search results carry dates in the text; take source_date (YYYY-MM-DD) from there.
- Material that is plainly an older event (last week's data, last month's earnings, last year's policy) does not become today's news
  just because a search result mentions it.
- If you cannot establish a date: drop the item.
- Material tagged as weekly/commentary (The Economist, for example) never becomes a news item in any block. Use it for tech_trends,
  fun_fact, or one sentence of background at the end of another item's body (it does not get its own source_date).

[LANGUAGE — HIGHEST PRIORITY]
1. Write everything in English. No Chinese characters anywhere in the output.
2. Write as a native English-language desk would: short declarative sentences in the register of a sell-side morning note.
   No marketing adjectives, no rhetorical questions, no metaphors, no "it is worth noting that".
3. Most of the material below is already in English — reuse the source's own phrasing and idiom rather than restating it.
4. A few sources are Chinese-language (MoneyDJ, CNA, Commercial Times, and some Google News items). For those, write the item the way an
   English-language wire would have written it in the first place — do not translate phrase by phrase, and do not carry over Chinese
   sentence shapes. Use the standard English name for every company and institution: 台積電 is TSMC, 聯發科 is MediaTek, 鴻海 is Foxconn,
   聯準會 is the Federal Reserve, 央行 is Taiwan's central bank. Convert 億/兆 to the English scale ($1.42B, $1.42T).
5. Keep tickers and technical terms in their standard form (2330.TW, 6857.T, CoWoS, HBM3E).
6. Straight ASCII punctuation throughout.

[CROSS-BLOCK DEDUPLICATION — HARD]
- One event (the same company doing the same thing, however the wording, angle or numbers differ) may appear **once in the whole JSON** —
  across top_stories, industry_developments, macro, geopolitical, world_news, ai_industry, regional_tech, fintech_crypto,
  startup_news, frontier_tech and us_market_recap.
- Priority: top_stories picks first; industry_developments then picks from unused material; every other block gets only what the first two left.
- "A different angle" is not an excuse: Nvidia investing in some company appears once, not once in top_stories, again in ai_industry,
  and again in regional_tech.us.
- The same event also may not repeat across regions (a TSMC event goes in taiwan or japan, not both).

[top_stories ORDERING]
- The first 3-5 items must be events with direct impact on the index book (QQQ / SMH / 0050 / 2330): semiconductor supply chain
  (TSMC / Nvidia / ASML / memory contract prices), AI capex, Fed or central bank path, tariffs and export controls, oil supply shocks.
  Set tag to "Index book" for these.
- Other important news comes after. Startup funding, gaming and payment M&A do not enter top_stories unless the size or impact is extreme.

[SOURCE ALLOWLIST — use only these canonical names; skip any item whose material carries a different source]
__SOURCE_WHITELIST__
[SOURCE BLOCKLIST — never use] YouTube, TikTok, Twitter/X, Reddit, Facebook, Instagram, personal blogs, Medium, Substack (other than the outlets listed above), PR Newswire, BusinessWire, GlobeNewswire, Seeking Alpha, Yahoo Finance syndication, Motley Fool, Benzinga, InfoQ

[WATCHLIST NEWS (watchlist_news)]
- The user message carries a WATCHLIST (tickers from the DD universe, with moat grade). Find events about **the company itself**
  (earnings, guidance, orders, products, M&A, regulation, management) — not sector commentary, not peer news.
- Items marked with a star and a ticker in the material are hints produced by code-level ticker matching; check those first, but also
  recognise company names yourself (TSM = TSMC = 2330.TW, Advantest = 6857.T, and so on).
- **Pick what matters, not everything that is mentioned.** At most 8 items, ordered by importance (things that change the fundamental
  read on the company go first):
  1. Pick from the PRIORITY GROUP first (grade S, or grade A with 3 or more QGM conditions passed);
  2. The OTHER GROUP qualifies only on a major event: earnings or guidance revision, a major order or customer change, M&A,
     regulation or litigation, CEO change, a significant product-line change. Routine PR, analyst ratings and small contracts do not count;
  3. One item per company (pick the most significant).
- The ticker field must match the WATCHLIST spelling (2330.TW, 6857.T). If the event is already in top_stories, write only one sentence
  on what it means for that company and do not restate the background; post-processing merges it back into the main event.
- Empty array if there is nothing. Two genuinely important items means two items. No price or index moves in the text.

[AI BLOCK (ai_industry) COVERAGE]
- This block covers two things at once: (1) the AI industry itself (model releases, capex, data centres, compute deals);
  and (2) **AI in production**. When material exists, pick the most important item on each of the three axes below; when it does not,
  write nothing rather than padding:
  1. **Healthcare and biotech**: FDA clearances or withdrawals for AI devices and AI-discovered drugs, AI drug-discovery deals and
     their size, hospital or payer deployments, clinical results for AI tools, reimbursement and regulation.
  2. **Tech and enterprise**: named enterprise deployments with contract size, software vendors shipping AI agents or copilots,
     disclosed AI revenue or seat counts, robotics and autonomy in production.
  3. **Semiconductor supply chain**: advanced packaging (CoWoS / SoIC) allocation, HBM qualification and contract prices,
     substrate and equipment lead times, materials bottlenecks, export controls.
- Set tag to one of: "Healthcare", "Enterprise", "Supply chain", "AI industry".
- Same bar as everywhere: the body needs a concrete number or a named entity. Generic "AI will transform industry X" copy is dropped.
  A supply-chain item already used in top_stories may not repeat here.

[CLASSIFIED FACT NEWS (industry_developments)]
- This block adds high-quality volume. category must be exactly one of:
  "US earnings", "Semis and supply chain", "AI in production", "Global startups", "US sector moves", "Industry and finance".
- Lead with who or which institution, when, what they did, the key number, and the current status. The body states only what has
  happened or been announced. Company guidance, analyst estimates and unnamed-source claims must be attributed as such and never
  rewritten as settled fact.
- US earnings: only reported quarterly revenue, EPS and guidance versus estimates. No previews, no analyst guesses.
- Semis and supply chain: orders, capacity, pricing, qualification, lead times, process nodes, export controls — verifiable events.
- AI in production: named deployments, contracts or seat counts, AI revenue, FDA clearances or clinical results. Keep 3-4 items when the
  material supports it. Demos and marketing copy with no customer and no deployment evidence do not count.
- Global startups: funding size, round stage and investors; IPO or M&A terms; verifiable product milestones.
- US sector moves: requires a named event catalyst plus the exact move and session from the last completed US session.
  Never infer a cause from news that merely happened at the same time.
- Industry and finance: concrete events in finance, energy, logistics, industrials, consumer, healthcare, defence and major policy.
- Scan all six categories. When the material is rich, target 12-16 items across the block, maximum 18, maximum 4 per category.
  A category with no qualifying event is 0 — never pad with old news or inference.
- evidence lists the key numbers, dates and status. fact_status must reflect the actual stage in the material. confirmed_impact is at most
  one sentence and only for a direct impact the source itself confirms. unknowns states what has not been disclosed or is still unverified.
- Banned: "worth watching", "set to benefit", "long-term positive/negative", "room to run", "investors should", "buy/sell", "price target",
  and any other inference or investment advice.

[LAST US SESSION (us_market_recap) — HARD RULES]
- Only earnings and events released on the **last US session** (the user message gives the exact date): pre-market, regular hours and
  after-hours all belong to that day.
- Every entry must carry `report_date`, and it must equal that date. **An earnings item with no explicit release date in the material is
  dropped** — never fill it from memory. Pulling in the prior day, last week or last quarter is the worst error you can make here.
- Wording like "the next morning" or "continued higher the following day" means the item is not from that session. Drop it.
- `summary` covers events only (who reported what, better or worse than estimates, guidance direction). **No index levels or index moves.**
  A single stock's after-hours reaction goes only in `after_hours_move`.
- If nothing was reported that day, use `earnings: []` and `has_events: false`. Do not fill space with old earnings.

[NEWS CONTENT RULES]
- Events only: company actions, policy, M&A, product launches, personnel, data releases.
- Facts first: the opening sentence names the entity, the date or quarter, what happened, and a verifiable number. At most one sentence of
  direct impact per item, and the material must support it. Do not extend into scenarios or forecasts.
- **No market-move narration.** No stock moves, index levels or index changes, crypto prices, futures moves, or phrasing like
  "climbed to $X" / "held above $X". Prices are presented in a separate block from real yfinance data. A post-earnings after-hours
  reaction belongs only in us_market_recap.after_hours_move.
- Exclude ESG content.
- source_date is YYYY-MM-DD. source is the outlet name — never "media reports" or "wire reports".
- Numbers in English format: $1.42T.
- Return JSON only, with no preamble and no markdown code block.
"""
GEMINI_SYSTEM_PROMPT = GEMINI_SYSTEM_PROMPT.replace(
    "__SOURCE_WHITELIST__", render_source_whitelist()
)

GEMINI_USER_PROMPT_TEMPLATE = """
[TODAY, TAIPEI] {today}
[ACCEPT FROM] {cutoff_date} — reject any item whose source_date is earlier than this.
[LAST US SESSION] {last_session} — us_market_recap may only carry earnings and events released on this date (report_date must equal it).

[WATCHLIST] (ticker(moat grade), {watchlist_count} names)
{watchlist_block}

Today's news material (Haiku search summaries plus RSS headlines):
{news_text}

{earnings_context}

Emit the following JSON. Write every field in English.

{{{{
  "top_stories": [
    {{{{
      "headline": "Headline, max 14 words",
      "body": "2-3 sentences, must contain concrete numbers",
      "tag": "Short category label",
      "tag_type": "macro|geo|tech|cb",
      "source": "Canonical allowlisted outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "watchlist_news": [
    {{{{
      "ticker": "Exactly as written in the WATCHLIST",
      "headline": "Headline, max 12 words, about the company itself",
      "body": "2 sentences: what happened, and what it means for this company (with numbers)",
      "source": "Canonical allowlisted outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "weekend_reads": [
    {{{{
      "title": "Long-form headline, original wording",
      "source": "The Economist / Financial Times / ...",
      "source_date": "YYYY-MM-DD",
      "why": "One sentence: why it is worth the time, and how it touches the index book or the watchlist",
      "link": "The URL exactly as given in the material; empty string if none"
    }}}}
  ],

  "macro": [
    {{{{
      "headline": "Macro headline, max 12 words",
      "body": "2 sentences with concrete data",
      "tag": "Short category label",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "ai_industry": [
    {{{{
      "headline": "AI industry headline, max 12 words",
      "body": "2 sentences with concrete data and company names",
      "tag": "Healthcare|Enterprise|Supply chain|AI industry",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "industry_developments": [
    {{{{
      "category": "US earnings|Semis and supply chain|AI in production|Global startups|US sector moves|Industry and finance",
      "industry": "Semiconductors|AI infrastructure|Enterprise software and security|Robotics and automation|Healthcare and biotech|Fintech|Defense and aerospace|Energy and logistics|Other",
      "headline": "Factual headline, max 14 words",
      "body": "1-2 sentences: named entity, date or quarter, what happened, key numbers only",
      "evidence": "Key numbers, dates and announcement status, one sentence",
      "fact_status": "reported|completed|approved|signed|filed|scheduled|in progress|company guidance",
      "development": "demand|supply|capacity|technology|pricing|regulation|competition|capex|M&A",
      "value_chain": "Fill only when a specific value chain is named; otherwise empty string",
      "market_move": "Only for US sector moves: the move and session from the last US session. Empty string for every other category",
      "confirmed_impact": "Direct impact the source itself confirms, max 1 sentence; empty string if none",
      "unknowns": "What is undisclosed or still unverified; write \'Nothing outstanding\' if none",
      "source": "Canonical allowlisted outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "regional_tech": {{{{
    "taiwan":   [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "japan":    [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "us":       [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "asean":    [{{{{"headline": "Headline (Southeast Asia: Singapore / Malaysia / Vietnam / Indonesia data centres and supply chain)", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "korea":    [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "china":    [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}],
    "europe":   [{{{{"headline": "Headline", "body": "1-2 sentences", "source": "Outlet", "source_date": "YYYY-MM-DD", "importance": "high|medium"}}}}]
  }}}},

  "fintech_crypto": [
    {{{{
      "headline": "Fintech or crypto headline, max 12 words",
      "body": "2 sentences with concrete data",
      "tag": "Fintech|Crypto|DeFi|Stablecoin",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "geopolitical": [
    {{{{
      "headline": "Geopolitics headline, max 12 words",
      "body": "2 sentences including the direct market impact",
      "region": "Middle East|Taiwan Strait|US-China|Other",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "world_news": [
    {{{{
      "headline": "Headline, max 14 words",
      "body": "2-3 sentences",
      "region": "Region",
      "tag": "Short category label",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "startup_news": [
    {{{{
      "headline": "Headline, max 16 words. Say what the company does, not just that it raised money",
      "summary": "2 sentences: what the company does, and what the money or the event is for",
      "deal": {{{{
        "stage": "Seed|Series A|Series B|Series C|Series D+|Growth|IPO filing|M&A|Fund close|Shutdown|Other. Use Other for non-financing events",
        "amount": "Amount with currency, e.g. $120M. Write \'undisclosed\' if not disclosed",
        "valuation": "Post-money valuation. Write \'undisclosed\' if not disclosed",
        "investors": "Lead plus notable participants. Write \'undisclosed\' if not disclosed",
        "hq": "Headquarters, city and country"
      }}}},
      "why": "One sentence on why a public-markets investor should spend ten seconds on this: whose existing business it threatens, which demand it validates, or which listed company is the buyer or the rival",
      "tag": "Short category label",
      "tag_type": "defense|ai|health|fintech|other",
      "accent": "defense|ai_gov|health|fintech|cyber|other",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "frontier_tech": [
    {{{{
      "headline": "Headline, max 16 words, stating the result itself",
      "field": "Field name, e.g. Quantum computing, Fusion, Humanoid robotics, Brain-computer interfaces, Space, Novel compute, Batteries & materials, Synthetic biology",
      "field_type": "quantum|robotics|space|energy|biotech|compute|materials|other",
      "who": "The named organisation or company behind it",
      "body": "2-3 sentences on what was actually achieved. Must carry numbers (qubit count, energy gain, yield, throughput, precision, launch cadence)",
      "stage": "lab result|prototype|pilot|limited commercial|full commercial|fundraising",
      "why": "One sentence on why it is worth tracking: what was blocking it, and who is affected once it clears. No investment advice, no price forecasts",
      "source": "Canonical allowlisted outlet",
      "source_date": "YYYY-MM-DD",
      "importance": "high|medium"
    }}}}
  ],

  "us_market_recap": {{{{
    "has_events": true,
    "earnings": [
      {{{{
        "company": "Company name",
        "ticker": "Ticker",
        "beat_miss": "beat/miss/in-line",
        "key_line": "The single most important line, with numbers",
        "after_hours_move": "Share reaction",
        "why_it_matters": "Why it matters, one sentence",
        "session": "pre-market/market/after-hours",
        "report_date": "YYYY-MM-DD, the US Eastern date this result was actually released. Must equal the LAST US SESSION date",
        "source": "Outlet"
      }}}}
    ],
    "other_events": [],
    "summary": "One sentence summarising the session's results"
  }}}},

  "earnings_preview": [
    {{{{
      "company": "Company name",
      "ticker": "Ticker",
      "report_time": "before-open/after-close/during-market",
      "eps_estimate": "Consensus EPS",
      "revenue_estimate": "Consensus revenue",
      "what_to_watch": "The single most important question, one sentence",
      "yfinance_confirmed": true
    }}}}
  ],

  "today_events": [
    {{{{
      "time": "Time",
      "event": "Event name",
      "note": "Note"
    }}}}
  ],

  "fun_fact": {{{{
    "title": "Market trivia headline, max 10 words",
    "content": "3-4 sentences",
    "connection": "How it connects to today's news"
  }}}}
}}}}

[TARGETS AND CEILINGS — targets are not floors; write fewer or leave [] when material is thin]
- top_stories: target 8-10 when material supports it, maximum 12. The first 3-5 must be index-book relevant, tagged "Index book"
- industry_developments: scan all six categories. Target 12-16 across the block, maximum 18, maximum 4 per category. A thin category may be 0
- macro: maximum 5
- ai_industry: maximum 7 (cover the AI-in-production axes that have material; see the AI block rules)
- regional_tech: maximum 3 per region. **Leave a region as [] when it has no material for today** — do not force it
- fintech_crypto: maximum 4
- geopolitical: maximum 4
- startup_news: target 6-8 when material supports it, maximum 8. Private-company events; an acquisition counts only when a startup is being bought
- frontier_tech: target 3-5 when material supports it, maximum 5. Spread the fields — cover at least 3 different field values
- world_news: maximum 3 (no overlap with top_stories or geopolitical)
- watchlist_news: maximum 8 (events about the watchlist companies themselves; [] if none)
- weekend_reads: maximum 3, only from material tagged weekly/commentary or plainly long-form. Routine wire copy does not count. Copy the link verbatim from the material
- today_events: maximum 5 real calendar items
- fun_fact: optional. If there is no reliable piece of trivia connected to today's news, return empty strings for title, content and connection

Six solid top_stories beat twelve where half are stale or duplicated. Self-check before emitting: is every source_date on or after the accept-from date?
Does any event appear in two blocks? Does any body narrate a price move?

Other rules:
- earnings_preview covers what is about to be released in the NEXT US session (yfinance-confirmed dates); us_market_recap covers what was released in the session that just closed. They are strictly mutually exclusive.
- Write everything in English. No Chinese characters anywhere in the output.
"""

# ═══════════════════════════════════════════════════════════════
# Claude Prompt — 分析區塊
# ═══════════════════════════════════════════════════════════════

CLAUDE_SYSTEM_PROMPT = """
You are a financial analyst serving a professional systematic investor.
The reader's live book: the index sleeve runs a "W52 x adaptive volatility" engine (US: QQQ/SMH; Taiwan: 0050/2330;
a single weekly W52 gate decides in or out, volatility sets exposure between 0% and 150%), plus a single-stock sleeve,
with a standing interest in AI infrastructure and semiconductors.
This is a weekly-cadence, low-turnover system. The briefing exists to show him the environment and warn him early if the
gate is at risk — not to give him something to trade every day.
You produce the ANALYSIS blocks only; a separate model handles the news blocks.

JSON format rules:
- Numbers in English format: $1.42T
- Return JSON only, with no preamble and no markdown code block
- Write every field in English. No Chinese characters anywhere in the output
- Plain professional English, short declarative sentences, no metaphors, no marketing adjectives

market_data rules:
- market_data uses the real numbers from market_context verbatim; do not alter them
- move_index.val comes from the news search results
- If the search results carry no MOVE Index, set val to "-"

regime rules — this is the spine of the whole analysis. Write it first; every other block must take a position on it.
Only call, the three axis states and confidence reach the page (as a one-line chip); axes evidence, confidence_reason and
falsifiers.meaning are still written to the JSON because tomorrow's prompt reads them back — write them briefly, not for display:
- call: one sentence on the state of the market today. It must have a direction. No fence-sitting ("mixed", "wait and see")
- axes: risk appetite, liquidity and volatility each get a state (risk-on/risk-off/neutral, easing/tightening/neutral,
  suppressed/rising/extreme). Ground every state in at least two real numbers from market_context while you reason
- contradicts: exactly one observation against the call, citing numbers. If you genuinely cannot find one, write "No clear
  counter-evidence" and say in the same sentence why that itself is suspicious (agreement with no counter-evidence usually
  means crowding or a data blind spot)
- falsifiers: exactly 3 entries of "which number appearing would mean the call is wrong". metric is an observable indicator
  name and threshold is a specific value ("VIX closes above 22", "HYG falls more than 1% in a day"). meaning is one sentence
  for tomorrow's prompt, not shown on today's page. Never write something unverifiable like "if the market weakens"
- for_w52_engine: one sentence for the W52 operator — describe only whether this week's weekly gate is under threat and whether volatility is
  approaching a band that would change exposure. Issue no buy, sell, add or trim instruction. If there is no risk, write
  "No pressure on the gate this week; no action required"
- confidence is high, medium or low. confidence_reason is one sentence for tomorrow's prompt, not shown on today's page.
  Never "high" when the three axes conflict or data is missing
- review (yesterday's call): if market_context carries a PREVIOUS CALL, check yesterday's falsifiers one by one. Fill today_value from today's
  real market_context numbers; hit is true only when the number actually crossed the threshold. verdict is one of:
  "carried over" (no falsifier hit, call direction unchanged), "revised" (not falsified but the call clearly needs changing),
  "falsified" (at least one falsifier hit). note is one sentence on how today's call differs from yesterday's and why.
  With no PREVIOUS CALL, set verdict to "no prior day" and leave the rest empty. Never set every hit to false to make it look clean — a hit is a hit

market_pulse rules — only hidden_risk, hidden_opportunity and key_level_to_watch reach the page, one line each:
- Equity index analysis uses NDX (^NDX), the prior US official close
- hidden_risk and hidden_opportunity are each one sentence, non-obvious, citing a number
- key_level_to_watch uses an NDX level, one short phrase
- Use hedged language where the evidence is hedged; do not output obvious observations

sentiment_analysis rules — only used to classify today's volatility stage and credit status; both are shown as a compact
chip on the regime card ("Volatility <axes.volatility.state> (<stage>, credit <credit_status>)"), not as long-form text:

[FOUR-STAGE LOGIC]
Stage 1 (calm before the storm): VIX < 20 + SKEW > 135 + VVIX flat
Stage 2 (break starts): VIX > 30 and rising fast + VVIX > 120 and spiking + SKEW dropping sharply
Stage 3 (bottoming signal): VIX > 40 or sustained high + VVIX has peaked and is falling + SKEW below 115
Stage 4 (reversal confirmed): VIX falling from the high + VVIX back near 100 + equities rebounding

[TIME DIMENSION — uses 5 days of history]

Precise Stage 3 test:
Necessary: (1) VIX today > 35, (2) VVIX has fallen from its peak for 2 or more days (vvix_peak_days_ago >= 2), (3) SKEW < 120
Sufficient (on top of necessary): VIX today > 40, VVIX down more than 10% from its peak (vvix_peak_decline_pct > 10), Fear&Greed < 20
Necessary met but not sufficient, or both met: either way, stage = "Stage 3"

Stage 2 versus Stage 3:
- vvix_peak_days_ago <= 1 (peaked today or yesterday) -> Stage 2
- vvix_peak_days_ago >= 2 (peaked two or more days ago) with VIX still high -> Stage 3

[CREDIT STATUS]
credit_status is "ok" when HYG is down less than 1% and LQD is stable (not a systemic panic).
credit_status is "stress" when HYG is down 1% or more, or LQD is falling alongside HYG (mild or systemic credit stress —
both map to "stress"; the page only has room for a binary read).

index_factor_reading rules — market_structure is the only field, 1-2 sentences merging every reading below into one
stance, citing at most 2-3 total figures. Do not list the readings separately; take a position on what they mean together:
- Breadth: RSP/SPY rising = equal weight beating cap weight = widening. IWM/SPY rising = small caps beating large caps =
  risk appetite rising. Both rising = genuine widening; both falling = high concentration; RSP/SPY up but IWM/SPY down =
  partial widening (mid caps strong, small caps weak)
- Style rotation: VTV falling less than VUG = money moving to value (defensive); VTV falling more than VUG = growth chased
- Sector signal: what the day's biggest-moving sector says about where industry money is going
- Megacap tech: NYFANG down more than NDX = megacap tech leading the decline; less than NDX = megacaps relatively resilient
- Momentum: MTUM versus NDX. MTUM resilient = momentum names still bid; MTUM leading down = momentum breaking
- Take a stance, not both sides, and name the single most important structural feature of the US session

Yield curve:
- 10Y-2Y below zero = inverted, historically a 6-18 month recession lead indicator
- Re-steepening out of inversion (bear steepening) is often more dangerous than the inversion itself: it means the front end is
  dropping fast (emergency Fed cuts)
- A widening 30Y-10Y spread means long-run inflation expectations are rising

smart_money rules:
- Only real institutional block or options activity reported today by a credible source
- Maximum 3 entries. With no credible source, output nothing
"""

CLAUDE_USER_PROMPT_TEMPLATE = """
Live market data for today (authoritative — do not guess around it):
{market_context}

Summary of today's financial news searches (context for the analysis):
{news_text}

Emit the following JSON, in English, containing the analysis blocks only:

{{
  "daily_summary": "The single most important sentence about today, max 16 words",
  "alert": "The highest-priority warning, one sentence. Empty string if there is nothing major",

  "regime": {{
    "call": "What state the market is in today, max 10 words, with a direction",
    "axes": {{
      "risk_appetite": {{"state": "risk-on/risk-off/neutral"}},
      "liquidity":     {{"state": "easing/tightening/neutral"}},
      "volatility":    {{"state": "suppressed/rising/extreme"}}
    }},
    "contradicts": ["The single most important observation against the call, citing numbers. If none, write 'No clear counter-evidence' and say why that is suspicious"],
    "falsifiers": [
      {{"metric": "Indicator name", "threshold": "Specific value", "meaning": "What it would mean the call got wrong, one sentence (for tomorrow's prompt, not shown today)"}}
    ],
    "for_w52_engine": "One sentence for the W52 operator (gate and volatility risk only, no buy or sell instruction)",
    "confidence": "high/medium/low",
    "confidence_reason": "One sentence (for tomorrow's prompt, not shown today)",
    "review": {{
      "yesterday_call": "Yesterday's call verbatim; empty string if none",
      "verdict": "carried over/revised/falsified/no prior day",
      "falsifier_check": [
        {{"metric": "Yesterday's indicator", "threshold": "Yesterday's threshold", "today_value": "Today's real number", "hit": false}}
      ],
      "note": "One sentence: how today's call carries over from or departs from yesterday's, and why"
    }}
  }},

  "market_data": {{
    "move_index": {{"val": "MOVE Index value, taken from the news search results", "interpretation": "One sentence"}}
  }},

  "market_pulse": {{
    "hidden_risk": "Non-obvious risk, one sentence",
    "hidden_opportunity": "Non-obvious opportunity, one sentence",
    "key_level_to_watch": "Key level, quoted on NDX"
  }},

  "index_factor_reading": {{
    "market_structure": "1-2 sentences merging breadth, style rotation, sector signal, megacap tech and momentum into one stance"
  }},

  "sentiment_analysis": {{
    "stage": "Stage 1/Stage 2/Stage 3/Stage 4/No clear signal",
    "credit_status": "ok/stress"
  }},

  "daily_deep_dive": [
    {{
      "theme": "Theme name",
      "theme_type": "semiconductor/ai_arch/liquidity/energy/spotlight",
      "headline": "The single most important sentence on this theme today, max 14 words",
      "situation": "The facts as they stand, 3-4 sentences, clearly separating announcements, guidance and estimates",
      "key_data": [
        {{"metric": "Indicator", "value": "Value", "change": "Change", "context": "What it means, one sentence"}}
      ],
      "deep_analysis": "Analysis, 2-3 sentences, explicitly marked as analysis rather than settled fact",
      "structural_signal": "Structural signal, one sentence",
      "bull_case": "Bull case, one sentence",
      "bear_case": "Bear case, one sentence",
      "implication": "Implication grounded in the known facts, one sentence, no buy or sell advice",
      "source": "Outlet",
      "source_date": "YYYY-MM-DD"
    }}
  ],

  "tech_trends": [
    {{
      "label": "Sub-field label",
      "label_type": "robotics|arch|infra_ai|science|other",
      "headline": "Headline, max 18 words",
      "summary": "2-3 sentences with concrete numbers and technical terms",
      "sub_items": [
        {{"key": "Technical dimension", "val": "Specifics"}},
        {{"key": "Technical dimension", "val": "Specifics"}},
        {{"key": "Technical dimension", "val": "Specifics"}}
      ],
      "chips": [{{"text": "Label", "type": "up|risk|watch|new|amber"}}],
      "source": "Outlet",
      "source_date": "YYYY-MM-DD"
    }}
  ],

  "system_status": {{
    "fixed": [
      {{"name": "W52 gate environment", "val": "State", "sub": "QQQ/SMH weekly trend and the volatility environment, no instruction", "sentiment": "pos|neg|neu"}},
      {{"name": "VIX level", "val": "Value plus warning", "sub": "Note", "sentiment": "pos|neg|neu"}},
      {{"name": "AI fundamentals", "val": "Assessment", "sub": "Note", "sentiment": "pos|neg|neu"}}
    ],
    "dynamic": [
      {{"name": "Dynamic dimension", "val": "State", "sub": "Note", "sentiment": "pos|neg|neu"}}
    ]
  }},

  "smart_money": {{
    "has_signals": true,
    "signals": [
      {{
        "type": "options/block/etf_flow",
        "ticker": "Ticker",
        "description": "One sentence describing the flow, with numbers",
        "direction": "bullish/bearish/neutral",
        "significance": "Why it is worth noting, one sentence"
      }}
    ],
    "summary": "The overall direction of today's institutional flow, one sentence"
  }}
}}

Notes:
0. Write regime first and think it through; it is the spine every other block reasons from. Expose contradictions; do not smooth them over
1. system_status.dynamic is exactly 3 entries, chosen from: {dynamic_options}
2. tech_trends: 3-4 entries when the material supports it, maximum 4, with exactly 3 sub_items each
3. daily_deep_dive: at most 1 theme, the single best-evidenced one across all of today's news material and the two fixed deep-dive queries.
   Leave it as [] when the facts are not there
4. smart_money: maximum 3, and nothing at all without a credible source
5. Write everything in English. No Chinese characters anywhere in the output
"""


# ═══════════════════════════════════════════════════════════════
# Gemini Pro Prompt — 深度財報分析區塊
# ═══════════════════════════════════════════════════════════════

EARNINGS_ANALYSIS_SYSTEM_PROMPT = """
You are an earnings analyst serving a professional systematic investor.
From the raw "US earnings released in the past 24 hours (between two briefings)" material below, analyse only companies that are
both important AND have actually reported, and produce a deep read.

[WINDOW — STRICTLY 24 HOURS]
The window runs from the previous briefing (yesterday 05:55 Taipei = 17:55 US ET the day before) to this one
(today 05:55 Taipei = 17:55 US ET today). Those 24 hours correspond to the US trading session that just closed:
17:55 ET on the previous business day to 17:55 ET today.
Accept only results actually released inside this window. Anything outside it, before or after, is excluded.

[LANGUAGE]
- Write everything in English. No Chinese characters anywhere in the output
- Plain professional English, short declarative sentences, no marketing adjectives

[HIGHEST PRIORITY: EXCLUDE PREVIEWS AND ANALYST-EXPECTATION PIECES]
Accept only companies that have actually reported. If the raw material carries any of the following for a company, exclude it outright:
- "expected to report", "will report", "is set to announce", "ahead of earnings"
- "analysts expect", "consensus forecasts", "Wall Street expects"
- "earnings preview", "what to watch", "what to expect"
- "scheduled for ... after the close", "scheduled for ... before the open"
- any future-tense framing at all

Include only with evidence of an actual release:
- "reported Q1 EPS of $X", "posted revenue of $Y", "Q1 results announced"
- "beat / missed / in line with estimates" (as a post-release comparison)
- "the company said / disclosed / reported in its release"
- CEO or CFO remarks actually made on the earnings call (not a pre-announcement)

If you cannot tell a preview from an actual release, exclude it. Under-report rather than invent.

[WHICH EARNINGS MATTER — STRICT]
A company must have actually reported AND meet at least one of:
1. Large cap, market value $40B or more
2. A bellwether (S&P 500 top 100, NDX top 30, a Dow constituent)
3. An industry proxy (semis: NVDA/TSMC/ASML/AMD/AVGO/MU/SK hynix; banks: JPM/BAC/C/MS/GS/WFC;
   cloud and software: MSFT/AMZN/GOOGL/ORCL/CRM; consumer: AAPL/WMT/COST/HD/MCD/KO/PEP;
   healthcare: JNJ/UNH/LLY/PFE/ABBV; industrials: CAT/DE/GE/BA; energy: XOM/CVX; payments: V/MA; media: NFLX/DIS)
4. It bears on a live thesis (AI infrastructure chain, Fed policy transmission, consumer credit, geopolitical supply chain)
5. The print contained a surprise: a large beat or miss, a sharp guidance revision, a CEO change, an announced acquisition

Always exclude:
- Small caps (under $10B) unless they are the only public read on their niche
- Mid caps ($10B-$40B) unless the print carried one of the surprises above
- Path-dependent beats (a mortgage REIT beating by a few cents on schedule)
- Thin material (one passing line with no EPS or revenue numbers)

If nothing in the batch qualifies (actually reported AND important), set has_content to false, leave companies, industry_trends,
winners, losers and contradictions as empty arrays, and leave conclusion empty.

[CONTENT — THE DETAIL IS THE POINT]
- State facts calmly. No flourishes, no emotive language
- Every point carries concrete numbers (EPS, revenue, gross margin, segment share, share reaction in percent)
- When a one-off item (acquisition dilution, a break fee, restructuring charges) distorts headline EPS, say so and work out the clean number
- An industry "imply" must not restate the headline: it is an inference about what happens next if the signal holds
- Winners and losers: consider the divergence between the fundamental winner and the share-price loser (ASML printing well but trading down)
- Contradictions: look first at FICC differences between peers, beat-but-fell or miss-but-rose, cautious talk alongside aggressive capex,
  macro worry alongside a volume surge

[JSON FORMAT]
- Return JSON only, with no markdown code block and no preamble
- Numbers in English format: $1.25B, YoY +17%
"""

EARNINGS_ANALYSIS_USER_TEMPLATE = """
Raw search results for important US earnings released in the past 24 hours (three deep queries):

{earnings_raw_text}

[LIVE MARKET DATA — for judging whether the share reaction is reasonable]
{market_context}

Emit the following JSON, in English:

{{{{
  "has_content": true,
  "window": "Window label, e.g. Apr 15-16 or past 24 hours",
  "overview": "One-sentence overview, max 14 words, naming the session's dominant theme",

  "companies": [
    {{{{
      "name": "Full company name",
      "ticker": "TICKER",
      "category": "Financials|Semiconductors|Media and streaming|Industrials and REITs|Consumer|Healthcare|Energy|Other",
      "result_tag": "beat|miss|mixed",
      "key_points": [
        "First point, with concrete numbers (EPS $X vs $Y est, revenue +Z% YoY)",
        "Second point",
        "Third point",
        "Fourth point (optional)"
      ],
      "weakness": "The weak spot or warning, one sentence, may be an empty string",
      "one_time_items": "One-off items and the clean number after excluding them, may be an empty string"
    }}}}
  ],

  "industry_trends": [
    {{{{
      "industry": "Industry name, e.g. Banks, Semiconductors",
      "core_trend": "The core trend, 2 sentences with concrete numeric evidence",
      "sub_signals": [
        "Sub-industry signal 1, with company names and numbers",
        "Sub-industry signal 2",
        "Sub-industry signal 3 (optional)"
      ],
      "imply": "What it implies for the industry, 2 sentences. Must be an inference, not a restatement"
    }}}}
  ],

  "winners": [
    {{{{
      "name": "Company",
      "ticker": "TICKER",
      "type": "fundamental winner|price winner|both",
      "reason": "Why, 2 sentences with numbers"
    }}}}
  ],

  "losers": [
    {{{{
      "name": "Company",
      "ticker": "TICKER",
      "type": "fundamental loser|price loser|both",
      "reason": "Why, 2 sentences with numbers"
    }}}}
  ],

  "contradictions": [
    {{{{
      "title": "What the contradiction is, max 12 words",
      "detail": "The two sides and the numbers behind them, 2 sentences",
      "read": "How to read it, one sentence"
    }}}}
  ],

  "conclusion": "Conclusion, 3-5 sentences, naming the 2-3 core themes of this earnings batch, with inference"
}}}}

[QUANTITY — BETTER SHORT THAN PADDED]
- companies: maximum 10, and only names that clear the importance test. If only 2-3 matter today, write 2-3. Do not pad
- industry_trends: cover at least 2 industries; if only 1 has material, write 1; if fewer than 2 companies can be grouped, leave it empty
- winners / losers: 1-4 each; if there is no clear loser, leave it empty
- contradictions: 0-4; when there is no genuine contradiction, leave it empty rather than invent one
- conclusion: an integrated inference, not a list. If too few important prints, one or two sentences is fine

If nothing in the past 24 hours clears the importance test (a weekend, a holiday, or a small-cap-only day), set has_content to false,
leave every array empty, and leave conclusion empty.
"""


def build_news_text(raw_news: list[dict], moneydj_news: list[dict] | None = None, deep_dive_news: list[dict] | None = None) -> str:
    parts = []
    for item in raw_news:
        parts.append(f"## {item['query']}")
        if item.get("answer"):
            parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"source: {src}")
        parts.append("")

    if moneydj_news:
        # 2026-08-17 晚起是多來源 RSS（news_fetcher.RSS_FEEDS），依 feed 分組給模型
        parts.append("## RSS headlines (per source, past 24-72h; each line = time | source | title | summary)")
        by_feed: dict[str, list] = {}
        for item in moneydj_news:
            by_feed.setdefault(item.get("feed") or item.get("source", "RSS"), []).append(item)
        for feed, items in by_feed.items():
            weekly = any(it.get("weekly") for it in items)
            note = "; weekly/commentary: background or tech_trends material only, never a news item" if weekly else ""
            parts.append(f"### {feed} ({len(items)} items{note})")
            for item in items:
                summ = f"｜{item['summary']}" if item.get("summary") else ""
                watch = f"*WATCHLIST[{','.join(item['watch'])}] " if item.get("watch") else ""
                link = f"｜URL: {item['link']}" if item.get("link") and (item.get("weekly") or item.get("longform")) else ""
                parts.append(f"- {watch}{item.get('published','')}｜{item.get('source','')}｜{item['title']}{summ}{link}")
            parts.append("")

    if deep_dive_news:
        # Support both old list format and new dict format
        if isinstance(deep_dive_news, dict):
            fixed_deep = deep_dive_news.get("fixed", [])
            dynamic_deep = deep_dive_news.get("dynamic", [])
        else:
            fixed_deep = deep_dive_news
            dynamic_deep = []

        if fixed_deep:
            parts.append("## Deep-dive search results - fixed topics (for the daily_deep_dive block)")
            for item in fixed_deep:
                parts.append(f"### [deep-fixed] {item.get('query', '')[:60]}")
                if item.get("answer"):
                    parts.append(item["answer"])
                for src in item.get("sources", []):
                    parts.append(f"source: {src}")
                parts.append("")

        if dynamic_deep:
            parts.append("## Deep-dive search results - today's dynamic topics (for the daily_deep_dive block)")
            for item in dynamic_deep:
                parts.append(f"### [deep-dynamic] focus: {item.get('topic', '')}")
                if item.get("result"):
                    parts.append(item["result"])
                for src in item.get("sources", []):
                    parts.append(f"source: {src}")
                parts.append("")

    return "\n".join(parts)


def _build_market_context(market_data: dict, today_earnings: list | None, move_index_raw: str, prev_regime: dict | None = None) -> str:
    """把 market_data 格式化成文字，供 Claude 分析用"""
    def _fmt_items(items):
        return ", ".join(f"{it['label']}: {it.get('val','—')} {it.get('chg','—')}" for it in items)

    indices_str = _fmt_items(market_data.get("indices", []))
    factors_list = market_data.get("factors", [])
    static_factors = [f for f in factors_list if not f.get("is_dynamic")]
    dynamic_factors = [f for f in factors_list if f.get("is_dynamic")]
    factors_str = _fmt_items(static_factors)
    top_sectors = ", ".join(f["label"] for f in dynamic_factors)
    sentiment_str = _fmt_items(market_data.get("sentiment", []))
    move_index_str = move_index_raw if move_index_raw else "no data"
    commodities_data = market_data.get("commodities", {})
    if isinstance(commodities_data, dict):
        all_commodities = commodities_data.get("fixed", []) + commodities_data.get("dynamic", [])
    elif isinstance(commodities_data, list):
        all_commodities = commodities_data
    else:
        all_commodities = []
    commodities_str = _fmt_items(all_commodities)
    bonds_str = _fmt_items(market_data.get("bonds", []))
    fx_str = _fmt_items(market_data.get("fx", []))
    credit_str = _fmt_items(market_data.get("credit", []))

    liquidity_items = market_data.get("liquidity", [])
    liq_parts = []
    for li in liquidity_items:
        date_str = f" ({li['date']})" if li.get("date") else ""
        liq_parts.append(f"{li['label']}: {li.get('val','—')} {li.get('chg','—')}{date_str}")
    liquidity_str = ", ".join(liq_parts) if liq_parts else "no data"

    lines = []
    lines.append(f"[EQUITY INDICES] {indices_str}")
    lines.append(f"[US FACTORS] {factors_str} (today's biggest-moving sectors: {top_sectors})")
    rsp_spy_val = rsp_spy_chg = iwm_spy_val = iwm_spy_chg = "—"
    for f in static_factors:
        if f.get("label") == "RSP/SPY":
            rsp_spy_val, rsp_spy_chg = f.get("val", "—"), f.get("chg", "—")
        elif f.get("label") == "IWM/SPY":
            iwm_spy_val, iwm_spy_chg = f.get("val", "—"), f.get("chg", "—")
    lines.append(f"[BREADTH] RSP/SPY ratio: {rsp_spy_val} ({rsp_spy_chg}); IWM/SPY ratio: {iwm_spy_val} ({iwm_spy_chg})")
    lines.append(f"[SENTIMENT] {sentiment_str}")
    lines.append(f"[MOVE INDEX] {move_index_str} (from web search)")

    # 昨日主軸（供 regime.review 驗證用；來源＝前一份日報存檔的 regime）
    if prev_regime and isinstance(prev_regime.get("regime"), dict) and prev_regime["regime"].get("call"):
        rg = prev_regime["regime"]
        lines.append("")
        lines.append(f"[PREVIOUS CALL ({prev_regime.get('date','prior day')})] call: {rg.get('call','')}")
        lines.append(f"  confidence: {rg.get('confidence','')} | {rg.get('confidence_reason','')}")
        lines.append(f"  for the W52 engine: {rg.get('for_w52_engine','')}")
        fals = rg.get("falsifiers") or []
        if fals:
            lines.append("  yesterday's falsifiers (check each against today's real numbers and fill regime.review.falsifier_check):")
            for f in fals:
                if isinstance(f, dict):
                    lines.append(f"    - {f.get('metric','')}: {f.get('threshold','')} -> {f.get('meaning','')}")
        if prev_regime.get("daily_summary"):
            lines.append(f"  yesterday's one-liner: {prev_regime['daily_summary'][:120]}")
    lines.append(f"[COMMODITIES] {commodities_str}")
    lines.append(f"[BONDS] {bonds_str}")
    lines.append(f"[FX] {fx_str}")
    lines.append(f"[CREDIT] {credit_str}")
    lines.append(f"[LIQUIDITY] {liquidity_str}")
    liq_assess = market_data.get("liquidity_assessment", {})
    if liq_assess:
        lines.append(f"[LIQUIDITY COMPOSITE] {liq_assess.get('label','')} (score {liq_assess.get('score',0)}; signals: {', '.join(liq_assess.get('signals', []))})")

    sh = market_data.get("sentiment_history", {})
    if sh:
        def _fmt_5d(entries):
            return " → ".join(f"{e['val']}" for e in entries) if entries else "—"
        lines.append(f"[SENTIMENT — 5-DAY TREND]")
        lines.append(f"VIX last 5 days: {_fmt_5d(sh.get('vix_5d', []))} (trend {sh.get('vix_trend','choppy')}, peaked {sh.get('vix_peak_days_ago',0)} days ago)")
        lines.append(f"VVIX last 5 days: {_fmt_5d(sh.get('vvix_5d', []))} (trend {sh.get('vvix_trend','choppy')}, peaked at {sh.get('vvix_peak_val',0)} {sh.get('vvix_peak_days_ago',0)} days ago, now {sh.get('vvix_peak_decline_pct',0):.1f}% off the peak)")
        lines.append(f"SKEW last 5 days: {_fmt_5d(sh.get('skew_5d', []))} (trend {sh.get('skew_trend','choppy')})")

    slt = market_data.get("second_layer_trends", {})
    if slt:
        lines.append(f"[SECOND-LAYER TREND DIRECTION]")
        lines.append(f"HYG credit: {slt.get('hyg_trend','choppy')} | DXY: {slt.get('dxy_trend','choppy')} | US 10Y: {slt.get('us10y_trend','choppy')}")
        lines.append(f"Gold: {slt.get('gold_trend','choppy')} | BTC: {slt.get('btc_trend','choppy')}")
        lines.append(f"RSP/SPY breadth: {slt.get('rsp_spy_trend','choppy')} | IWM/SPY small caps: {slt.get('iwm_spy_trend','choppy')}")

    if today_earnings:
        lines.append("\n[yfinance-confirmed earnings due in the NEXT US session]")
        for e in today_earnings:
            lines.append(f"{e['ticker']} ({e.get('time','—')})")
    else:
        lines.append("\n[yfinance-confirmed earnings due in the NEXT US session] none")

    return "\n".join(lines)


def _parse_json(raw_text: str) -> dict:
    """從 API 回應文字中解析 JSON，含自動修復"""
    import re
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        text = text[start:end]

    # 第一次嘗試直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 修復常見 JSON 問題
    # 1. 移除 trailing commas（}, ] 前的逗號）
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # 2. 修復缺少逗號：}\n{ 或 ]\n[ 或 "\n"
    text = re.sub(r'"\s*\n\s*"', '",\n"', text)
    text = re.sub(r'}\s*\n\s*{', '},\n{', text)
    text = re.sub(r']\s*\n\s*\[', '],\n[', text)
    # 3. 修復 }\n" 缺少逗號
    text = re.sub(r'}\s*\n\s*"', '},\n"', text)
    text = re.sub(r']\s*\n\s*"', '],\n"', text)

    return json.loads(text)


def _call_gemini_pro(market_context: str, news_text: str) -> dict:
    """呼叫 Gemini 2.5 Pro（分析區塊，主要模型）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set, falling back to Claude")

    client = genai.Client(api_key=api_key)
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )

    print("  → [Gemini Pro] Calling API (analysis sections)...")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=CLAUDE_SYSTEM_PROMPT,
                    max_output_tokens=16000,
                    temperature=0.5,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=-1),
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s
                print(f"  ⚠ [Gemini Pro] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    raw_text = response.text
    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    # Gemini 2.5 Pro: input $1.25/MTok, output $10/MTok
    cost = in_tok / 1_000_000 * 1.25 + out_tok / 1_000_000 * 10
    print(f"  → [Gemini Pro] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/gemini_pro_raw.txt", "w") as f:
        f.write(raw_text)

    try:
        return _parse_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [Gemini Pro] JSON error at char {e.pos}: {e.msg}")
        raise


def _call_claude(market_context: str, news_text: str) -> dict:
    """呼叫 Claude API（分析區塊 fallback）"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        news_text=news_text,
        dynamic_options=DYNAMIC_STATUS_OPTIONS,
    )

    print("  → [Claude] Calling API (analysis sections, fallback)...")
    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        final_msg = stream.get_final_message()

    usage = final_msg.usage
    input_tok = usage.input_tokens
    output_tok = usage.output_tokens
    cost_input = input_tok / 1_000_000 * 3
    cost_output = output_tok / 1_000_000 * 15
    cost_total = cost_input + cost_output
    print(f"  → [Claude] tokens: in={input_tok:,} out={output_tok:,} cost=${cost_total:.4f}")

    with open("/tmp/claude_raw.txt", "w") as f:
        f.write(full_text)

    try:
        return _parse_json(full_text)
    except json.JSONDecodeError as e:
        print(f"  [Claude] JSON error at char {e.pos}: {e.msg}")
        raise


def _call_gemini(news_text: str, earnings_context: str, watchlist: list[dict] | None = None) -> dict:
    """呼叫 Gemini API（新聞區塊）"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  ⚠ GEMINI_API_KEY not set, skipping Gemini call")
        return {}

    client = genai.Client(api_key=api_key)

    today, cutoff = _news_date_window()
    wl_text, wl_n = _watchlist_block(watchlist)
    user_prompt = GEMINI_USER_PROMPT_TEMPLATE.format(
        news_text=news_text,
        earnings_context=earnings_context,
        today=today,
        cutoff_date=cutoff,
        last_session=_last_us_session_date(),
        watchlist_block=wl_text,
        watchlist_count=wl_n,
    )

    print("  → [Gemini] Calling API (news sections)...")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=GEMINI_SYSTEM_PROMPT,
                    max_output_tokens=16000,
                    temperature=0.5,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s
                print(f"  ⚠ [Gemini] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    raw_text = response.text
    # Token usage log
    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    # Gemini 2.5 Flash Preview: input $0.15/MTok, output $0.60/MTok (thinking off)
    cost = in_tok / 1_000_000 * 0.15 + out_tok / 1_000_000 * 0.60
    print(f"  → [Gemini] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/gemini_raw.txt", "w") as f:
        f.write(raw_text)

    try:
        return _parse_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [Gemini] JSON error at char {e.pos}: {e.msg}")
        raise


def _build_earnings_raw_text(earnings_deep_dive: list[dict] | None) -> str:
    """把 Perplexity 財報查詢結果組成文字。"""
    if not earnings_deep_dive:
        return ""
    parts = []
    for i, item in enumerate(earnings_deep_dive, 1):
        if not item.get("answer"):
            continue
        parts.append(f"## Query {i}: {item.get('query','')[:120]}")
        parts.append(item["answer"])
        for src in item.get("sources", []):
            parts.append(f"source: {src}")
        parts.append("")
    return "\n".join(parts)


def _has_earnings_content(earnings_raw_text: str) -> bool:
    """判斷 Perplexity 回傳是否含實質財報內容；若無直接跳過 LLM。"""
    if not earnings_raw_text or not earnings_raw_text.strip():
        return False
    text = earnings_raw_text.lower()
    # 內容太短 → 視為無
    if len(text) < 800:
        return False
    # 明確宣告無財報的字樣主導
    neg_phrases = [
        "no major earnings", "no significant earnings", "no earnings reports",
        "no earnings were released", "no notable earnings", "no us company earnings",
        "there are no earnings", "no earnings announcements",
    ]
    neg_hits = sum(text.count(p) for p in neg_phrases)
    # 關鍵字出現次數太少 → 視為無
    kw_count = text.count("eps") + text.count("revenue") + text.count("earnings") + text.count("reported")
    if kw_count < 4:
        return False
    # 否定字出現且關鍵字很稀 → 視為無
    if neg_hits >= 2 and kw_count < 10:
        return False
    return True


def _call_gemini_pro_earnings(earnings_raw_text: str, market_context: str) -> dict:
    """呼叫 Gemini 2.5 Pro 做深度財報分析（主要模型）。無當日財報時直接跳過。"""
    empty_stub = {"has_content": False, "companies": [], "industry_trends": [],
                  "winners": [], "losers": [], "contradictions": [],
                  "conclusion": "", "window": "", "overview": ""}

    if not _has_earnings_content(earnings_raw_text):
        print("  ⚠ [Earnings Analysis] 當日無實質財報資料，跳過 LLM 呼叫")
        return empty_stub

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set, falling back to Claude")

    client = genai.Client(api_key=api_key)
    user_prompt = EARNINGS_ANALYSIS_USER_TEMPLATE.format(
        earnings_raw_text=earnings_raw_text,
        market_context=market_context or "(none)",
    )

    print("  → [Earnings Analysis] Calling Gemini 2.5 Pro...")

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=EARNINGS_ANALYSIS_SYSTEM_PROMPT,
                    max_output_tokens=16000,
                    temperature=0.5,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=-1),
                ),
            )
            break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries - 1:
                wait = 30 * (2 ** attempt)  # 30s, 60s, 120s, 240s
                print(f"  ⚠ [Earnings Analysis / Gemini Pro] attempt {attempt+1} failed ({err_str[:80]}), retrying in {wait}s...")
                import time
                time.sleep(wait)
            else:
                raise

    raw_text = response.text
    usage = response.usage_metadata
    in_tok = usage.prompt_token_count
    out_tok = usage.candidates_token_count
    cost = in_tok / 1_000_000 * 1.25 + out_tok / 1_000_000 * 10
    print(f"  → [Earnings Analysis / Gemini Pro] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/gemini_pro_earnings_raw.txt", "w") as f:
        f.write(raw_text)

    try:
        return _parse_json(raw_text)
    except json.JSONDecodeError as e:
        print(f"  [Earnings Analysis / Gemini Pro] JSON error at char {e.pos}: {e.msg}")
        raise


def _call_claude_earnings_analysis(earnings_raw_text: str, market_context: str) -> dict:
    """呼叫 Claude Sonnet 4.6 做深度財報分析（fallback）。無當日財報時直接跳過。"""
    empty_stub = {"has_content": False, "companies": [], "industry_trends": [],
                  "winners": [], "losers": [], "contradictions": [],
                  "conclusion": "", "window": "", "overview": ""}

    if not _has_earnings_content(earnings_raw_text):
        print("  ⚠ [Earnings Analysis] 當日無實質財報資料，跳過 LLM 呼叫")
        return empty_stub

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_prompt = EARNINGS_ANALYSIS_USER_TEMPLATE.format(
        earnings_raw_text=earnings_raw_text,
        market_context=market_context or "(none)",
    )

    print("  → [Earnings Analysis] Calling Claude Sonnet 4.6 (fallback)...")

    full_text = ""
    with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=EARNINGS_ANALYSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            full_text += text
        final_msg = stream.get_final_message()

    usage = final_msg.usage
    in_tok = usage.input_tokens
    out_tok = usage.output_tokens
    cost = in_tok / 1_000_000 * 3 + out_tok / 1_000_000 * 15
    print(f"  → [Earnings Analysis] tokens: in={in_tok:,} out={out_tok:,} cost=${cost:.4f}")

    with open("/tmp/claude_earnings_raw.txt", "w") as f:
        f.write(full_text)

    try:
        return _parse_json(full_text)
    except json.JSONDecodeError as e:
        print(f"  [Earnings Analysis] JSON error at char {e.pos}: {e.msg}")
        raise


# ── 新聞後處理：去重 / 過期 / 行情句 / 簡繁與錯字 ─────────────────────────
import re as _re
from datetime import datetime as _dt, timedelta as _td

_NEWS_PRIMARY_BLOCKS = [
    "top_stories", "industry_developments", "macro", "geopolitical", "world_news", "ai_industry",
    "fintech_crypto", "startup_news", "frontier_tech",
]
_NEWS_LIST_BLOCKS = _NEWS_PRIMARY_BLOCKS + ["tech_trends", "daily_deep_dive"]

_FACT_CATEGORY_ALIASES = {
    "usearnings": "US earnings",
    "semisandsupplychain": "Semis and supply chain",
    "semiconductorsandsupplychain": "Semis and supply chain",
    "techandsemiconductorsupplychain": "Semis and supply chain",
    "aiinproduction": "AI in production",
    "globalstartups": "Global startups",
    "startups": "Global startups",
    "ussectormoves": "US sector moves",
    "ussectorsandsingle-stockmoves": "US sector moves",
    "industryandfinance": "Industry and finance",
    "globalindustryandfinance": "Industry and finance",
}
_FACT_STATUSES = {
    "reported", "completed", "approved", "signed", "filed", "scheduled", "in progress", "company guidance",
}
_FACT_STATUS_ALIASES = {
    "announced": "reported",
    "disclosed": "reported",
    "published": "reported",
    "released": "reported",
    "cleared": "approved",
    "authorised": "approved",
    "authorized": "approved",
    "agreed": "signed",
    "submitted": "filed",
    "applied": "filed",
    "planned": "scheduled",
    "ongoing": "in progress",
    "underway": "in progress",
    "guidance": "company guidance",
}
_INDUSTRY_ALIASES = {
    "semiconductors": "Semiconductors",
    "semiconductor": "Semiconductors",
    "aiinfrastructure": "AI infrastructure",
    "aidatacenters": "AI infrastructure",
    "aidatacentres": "AI infrastructure",
    "enterprisesoftwareandsecurity": "Enterprise software and security",
    "enterprisesoftware": "Enterprise software and security",
    "roboticsandautomation": "Robotics and automation",
    "roboticsandindustrialautomation": "Robotics and automation",
    "healthcareandbiotech": "Healthcare and biotech",
    "healthcare": "Healthcare and biotech",
    "fintech": "Fintech",
    "defenseandaerospace": "Defense and aerospace",
    "defenceandaerospace": "Defense and aerospace",
    "energyandlogistics": "Energy and logistics",
    "energy,transportandlogistics": "Energy and logistics",
    "other": "Other",
}
_INDUSTRY_DEVELOPMENT_TYPES = {
    "demand", "supply", "capacity", "technology", "pricing", "regulation", "competition", "capex", "M&A",
}

_MONEY_RE = _re.compile(r"\$\s?\d[\d,.]*\s?[BMTK]?|\d[\d,.]*\s?(?:億|兆|萬)")
_ENT_RE = _re.compile(r"[A-Z][A-Za-z0-9&.\-]{1,}")          # 英文專名／ticker
_CJK_RE = _re.compile(r"[\u4e00-\u9fff]")

_ENTITY_ALIASES = {
    "tsmc": ("tsmc", "台積電", "2330.tw", "tsm"),
    "nvidia": ("nvidia", "輝達", "nvda"),
    "mediatek": ("mediatek", "聯發科", "2454.tw"),
    "asml": ("asml",),
    "amazon": ("amazon", "aws", "amzn"),
    "qualcomm": ("qualcomm", "qcom"),
    "meta": ("meta", "facebook"),
    "federal_reserve": ("federal reserve", "fed", "聯準會"),
    "ecb": ("ecb", "歐洲央行"),
    "boj": ("boj", "日本央行", "日銀"),
}
_GENERIC_ENTITIES = {"ai", "us", "high", "na", "the", "and", "app", "tst"}
# 2026-09-19 日報改英文後重做：原本是中文固定詞（「投資」「併購」）硬塞幾個英文單字，
# 英文比對不到詞形變化——"invests"／"invested" 配不上 "investment"，同一則新聞就漏判。
# 改成「詞幹＋字界」：ASCII 詞尾補 [a-z]*（invest → invests/invested/investment/investor），
# 前面加 (?<![a-z]) 擋住 around／urban 這種誤中。中文詞保留（來源 RSS 仍有中文標題）。
_ACTION_TERMS = {
    "investment":  ("invest", "stake in", "equity stake", "warrant", "投資", "入股", "認股"),
    "launch":      ("launch", "unveil", "debut", "introduce", "roll out", "rollout",
                    "推出", "發布", "發表"),
    "adoption":    ("deploy", "adopt", "partner", "signed", "rolls out to",
                    "導入", "採用", "合作", "攜手"),
    "rates":       ("rate hike", "rate cut", "raise rates", "cut rates", "policy rate",
                    "升息", "降息", "利率決議"),
    "attack":      ("attack", "airstrike", "missile", "drone strike", "攻擊", "遇襲", "空襲"),
    "earnings":    ("earnings", "revenue", "guidance", "eps", "operating profit", "quarterly result",
                    "財報", "營收", "獲利", "指引"),
    "acquisition": ("acquire", "acquisition", "merger", "takeover", "buyout",
                    "併購", "收購", "合併"),
    "policy":      ("sanction", "tariff", "export control", "export ban", "restrict", "subsid",
                    "制裁", "禁令", "關稅", "出口管制"),
    "capacity":    ("capacity", "shortage", "sold out", "utilisation", "utilization",
                    "擴產", "產能", "供需缺口"),
    "funding":     ("funding round", "fundrais", "series a", "series b", "series c", "seed round",
                    "raised $", "融資", "募資"),
    # 原本沒有「價格」事件類型，半導體合約價這種日報核心題材在深挖與分類新聞之間配不起來
    "pricing":     ("contract price", "pricing", "price increase", "asp",
                    "合約價", "報價", "調價", "漲價"),
}


def _compile_action_terms(terms):
    patterns = []
    for term in terms:
        if _re.fullmatch(r"[a-z0-9 $.\-]+", term):
            patterns.append(r"(?<![a-z])" + _re.escape(term) + r"[a-z]*")
        else:
            patterns.append(_re.escape(term))
    return _re.compile("|".join(patterns), _re.I)


_ACTION_GROUPS = {action: _compile_action_terms(terms) for action, terms in _ACTION_TERMS.items()}

_EVENT_NUMBER_RE = _re.compile(r"\$?\d[\d,.]*(?:\s?(?:%|bps|b|m|t|億|兆|萬))?", _re.I)


# 2026-09-19 日報改英文後新增：原本的 token 只抓「大寫開頭的專名」＋中文 2-gram。
# 中文一句話會產生數十個 2-gram，Jaccard 穩定；英文一句只剩三五個專名，
# 兩則無關新聞很容易因為共用 "The"／"EU" 就衝到 0.4 以上被誤判成同一事件。
# 因此英文另外抽一組「去掉虛詞的小寫實詞」，把 token 集合撐回有意義的密度。
_EN_WORD_RE = _re.compile(r"[a-z][a-z0-9\-]{2,}")
_EN_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "its", "was", "were", "are",
    "has", "have", "had", "been", "will", "would", "said", "says", "than", "then",
    "into", "over", "under", "after", "before", "about", "also", "more", "most",
    "not", "but", "out", "off", "per", "own", "new", "now", "one", "two", "three",
    "year", "years", "day", "days", "week", "month", "quarter", "according",
}


def _news_tokens(text: str) -> set:
    """去重用 token：英文專名＋英文實詞＋金額＋中文 2-gram（都去掉高頻虛詞）。"""
    text = text or ""
    toks = {t.lower() for t in _ENT_RE.findall(text)} - _GENERIC_ENTITIES
    toks |= {w for w in _EN_WORD_RE.findall(text.lower()) if w not in _EN_STOP}
    toks |= {m.replace(" ", "") for m in _MONEY_RE.findall(text)}
    cjk = "".join(_CJK_RE.findall(text))
    stop = set("的了在是與和及或將於對為由到及並已再也仍等")
    toks |= {cjk[i:i+2] for i in range(len(cjk) - 1) if not (cjk[i] in stop or cjk[i+1] in stop)}
    return toks


def _is_dup(a: set, b: set) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    j = inter / len(a | b)
    return j >= 0.40


def _item_event_text(item: dict) -> str:
    parts = [
        item.get("headline", ""), item.get("title", ""), item.get("theme", ""),
        item.get("body", ""), item.get("summary", ""), item.get("situation", ""),
        item.get("evidence", ""), item.get("market_move", ""), item.get("confirmed_impact", ""),
    ]
    for datum in item.get("key_data", []) if isinstance(item.get("key_data"), list) else []:
        if isinstance(datum, dict):
            parts.extend(str(datum.get(key, "")) for key in ("metric", "value", "change"))
    return " ".join(str(part) for part in parts if part)[:900]


def _event_features(item: dict) -> dict:
    text = _item_event_text(item)
    folded = text.casefold()

    def _has_alias(alias: str) -> bool:
        alias = alias.casefold()
        if _re.fullmatch(r"[a-z0-9.\-]+", alias):
            return bool(_re.search(rf"(?<![a-z0-9]){_re.escape(alias)}(?![a-z0-9])", folded))
        return alias in folded

    entities = {
        canonical
        for canonical, aliases in _ENTITY_ALIASES.items()
        if any(_has_alias(alias) for alias in aliases)
    }
    entities |= {
        token.lower()
        for token in _ENT_RE.findall(text)
        if token.lower() not in _GENERIC_ENTITIES
    }
    actions = {
        action
        for action, pattern in _ACTION_GROUPS.items()
        if pattern.search(folded)
    }
    return {
        "tokens": _news_tokens(text),
        "entities": entities,
        "actions": actions,
        "numbers": {m.replace(" ", "").casefold() for m in _EVENT_NUMBER_RE.findall(text)},
        "date": str(item.get("source_date") or item.get("report_date") or ""),
    }


def _dates_near(a: str, b: str) -> bool:
    if not a or not b:
        return True
    try:
        return abs((_dt.strptime(a, "%Y-%m-%d") - _dt.strptime(b, "%Y-%m-%d")).days) <= 1
    except ValueError:
        return a == b


def _same_event(a: dict, b: dict) -> bool:
    if not _dates_near(a["date"], b["date"]):
        return False
    token_union = a["tokens"] | b["tokens"]
    similarity = len(a["tokens"] & b["tokens"]) / len(token_union) if token_union else 0
    if similarity >= 0.55:
        return True
    shared_entities = a["entities"] & b["entities"]
    if not shared_entities:
        return False
    if similarity >= 0.40:
        return True
    shared_actions = a["actions"] & b["actions"]
    shared_numbers = {
        number for number in a["numbers"] & b["numbers"]
        if not _re.fullmatch(r"(?:19|20)\d{2}", number)
    }
    if shared_actions and (shared_numbers or len(shared_entities) >= 2 or similarity >= 0.18):
        return True
    return False


def _event_id(item: dict, features: dict) -> str:
    title = item.get("headline") or item.get("title") or item.get("theme") or ""
    raw = "|".join([
        features["date"], ",".join(sorted(features["entities"])),
        ",".join(sorted(features["actions"])), "".join(_CJK_RE.findall(title))[:40],
    ])
    return "evt_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _dedup_news(data: dict) -> dict:
    """Keep one primary card per event and attach watchlist/deep-dive references."""
    seen: list[tuple[dict, dict]] = []
    removed = 0
    watchlist_merged = 0
    deep_extensions = 0

    def find_match(features: dict) -> dict | None:
        for existing_features, existing_item in seen:
            if _same_event(features, existing_features):
                return existing_item
        return None

    def keep_primary(item: dict) -> bool:
        nonlocal removed
        features = _event_features(item)
        if find_match(features):
            removed += 1
            return False
        item["event_id"] = _event_id(item, features)
        item["event_role"] = "primary"
        seen.append((features, item))
        return True

    for key in _NEWS_PRIMARY_BLOCKS:
        items = data.get(key, [])
        if isinstance(items, list):
            data[key] = [item for item in items if isinstance(item, dict) and keep_primary(item)]

    rt = data.get("regional_tech", {})
    if isinstance(rt, dict):
        for region, items in rt.items():
            if isinstance(items, list):
                rt[region] = [item for item in items if isinstance(item, dict) and keep_primary(item)]

    remaining_watchlist = []
    for item in data.get("watchlist_news", []) if isinstance(data.get("watchlist_news"), list) else []:
        if not isinstance(item, dict):
            continue
        features = _event_features(item)
        match = find_match(features)
        if not match:
            keep_primary(item)
            remaining_watchlist.append(item)
            continue
        match.setdefault("watchlist_refs", []).append({
            "ticker": item.get("ticker", ""),
            "impact": item.get("body", ""),
        })
        watchlist_merged += 1
    data["watchlist_news"] = remaining_watchlist

    deep_items = []
    for item in data.get("daily_deep_dive", []) if isinstance(data.get("daily_deep_dive"), list) else []:
        if not isinstance(item, dict):
            continue
        features = _event_features(item)
        match = find_match(features)
        if match:
            item["event_role"] = "deep_extension"
            item["related_event_id"] = match.get("event_id", "")
            item["situation"] = ""
            item["headline"] = f"Deep dive | {item.get('theme') or item.get('headline', '')}"
            deep_extensions += 1
        else:
            item["event_id"] = _event_id(item, features)
            item["event_role"] = "primary"
            seen.append((features, item))
        deep_items.append(item)
    data["daily_deep_dive"] = deep_items

    tech_items = []
    for item in data.get("tech_trends", []) if isinstance(data.get("tech_trends"), list) else []:
        if not isinstance(item, dict):
            continue
        if find_match(_event_features(item)):
            removed += 1
            continue
        keep_primary(item)
        tech_items.append(item)
    data["tech_trends"] = tech_items

    if removed or watchlist_merged or deep_extensions:
        print(
            f"  → dedup: 移除 {removed} 條、合併 {watchlist_merged} 條關注股、"
            f"標記 {deep_extensions} 條延伸深挖"
        )
    return {
        "event_duplicates_removed": removed,
        "watchlist_refs_merged": watchlist_merged,
        "deep_extensions": deep_extensions,
    }


# 常見簡體字／錯字（模型偶發），只做「一對一、不會誤傷」的替換
_ZH_FIX = {
    "晶圆": "晶圓", "腰斩": "腰斬", "规范": "規範", "软件": "軟體", "内存": "記憶體", "芯片": "晶片",
    "网络": "網路", "数据": "數據", "信息": "資訊", "视频": "影片", "服务器": "伺服器", "云计算": "雲端運算",
    "人工智能": "人工智慧", "机器人": "機器人", "汇率": "匯率", "债券": "債券", "关税": "關稅", "美联储": "聯準會",
    "货币": "貨幣", "投资": "投資", "亿": "億", "发布": "發布", "计划": "計畫", "产业": "產業", "产能": "產能",
    "通膀": "通膨", "澈洲": "澳洲", "籲募": "籌募", "籲備": "籌備", "籲資": "籌資", "産業": "產業", "産能": "產能",
}
_MARKET_SENT_RE = _re.compile(
    r"((?i:share price|shares|the stock|stocks|the index|indices|index futures|futures|Bitcoin|Ethereum"
    r"|Stoxx|Nasdaq|S&P|Dow|SOX index|TAIEX|crude|Brent|WTI|oil price|gold price|copper price"
    r"|the yield|yields|dollar index|DXY|the yen|Treasuries)"
    r"|(?<![A-Za-z])(?!CPI|PPI|GDP|PCE|PMI|ISM|NFP|EPS|ROE|FDA|SEC|IPO|CEO|CFO|AI|USD|EUR|JPY)[A-Z]{2,6}(?![A-Za-z]))"
    r"[^.;]{0,40}?(?i:\b(rose|fell|rallied|slumped|surged|plunged|climbed|dropped|gained|lost|jumped|sank"
    r"|tumbled|soared|slid|advanced|declined|closed up|closed down|ended up|ended down|is up|is down|was up|was down)\b)"
    r"[^.;]{0,12}?(\d[\d,.]*\s?%|\$\s?\d)"
)
_INFERENCE_SENT_RE = _re.compile(
    r"worth watching|bears watching|set to benefit|stands to benefit|poised to|well positioned to"
    r"|long-term positive|long-term negative|room to run|upside potential|bodes well"
    r"|investors should|we recommend|buy rating|sell rating|price target",
    _re.I,
)
_MARKET_MOVE_FACT_RE = _re.compile(
    r"(?=.*\d[\d,.]*\s?%)"
    r"(?=.*(?:pre-market|premarket|intraday|after-hours|afterhours|at the close|on the close"
    r"|regular session|last US session|during the session|on the day))",
    _re.I,
)
_FACT_ANCHOR_RE = _re.compile(
    r"\d|announced|reported|disclosed|published|approved|cleared|signed|filed|submitted"
    r"|completed|launched|deployed|guidance|earnings|revenue|EPS",
    _re.I,
)


def _fix_zh(text):
    if not isinstance(text, str) or not text:
        return text
    for a, b in _ZH_FIX.items():
        if a in text:
            text = text.replace(a, b)
    return text


# 2026-09-19 日報改英文後新增：原本斷句只認中文句號「。；;」，英文句點不算，
# 結果一整段英文 body 會被當成「一句」——只要裡面有一句行情句或推論句，整段被刪光，
# 條目再被 complete 檢查判死。這裡補上英文句界（句點＋空白＋大寫），零寬度切分，
# join 回去字元不變；"$1.42B" 這種小數點後面沒有空白，不會被誤切。
_SENT_SPLIT_RE = _re.compile(r"(?<=[。；;])|(?<=[.!?])(?=\s+[A-Z])")


def _strip_market_sentences(text: str):
    """砍掉含行情漲跌的句子（以。；分句）；回 (新文字, 是否有砍)。"""
    if not isinstance(text, str) or not text:
        return text, False
    parts = _SENT_SPLIT_RE.split(text)
    kept = [pt for pt in parts if not _MARKET_SENT_RE.search(pt)]
    if len(kept) == len(parts):
        return text, False
    return "".join(kept).strip(), True


def _strip_inference_sentences(text: str):
    """移除明顯投資推論句；保留可驗證事實與明確歸因內容。"""
    if not isinstance(text, str) or not text:
        return text, False
    parts = _SENT_SPLIT_RE.split(text)
    kept = [pt for pt in parts if not _INFERENCE_SENT_RE.search(pt)]
    if len(kept) == len(parts):
        return text, False
    return "".join(kept).strip(), True


def _sanitize_news(data: dict, cutoff_date: str) -> dict:
    """(1) 全部字串簡繁／錯字修正；(2) 新聞區塊：過期條目丟掉、行情句砍掉、標題含漲跌%整條丟掉。"""
    stats = {
        "stale": 0, "market_sent": 0, "market_head": 0,
        "recap_stale": 0, "invalid_source": 0, "industry_quality": 0,
        "inference_trimmed": 0,
    }

    def _walk_fix(obj):
        if isinstance(obj, dict):
            return {k: _walk_fix(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk_fix(v) for v in obj]
        return _fix_zh(obj)

    for k in list(data.keys()):
        if k == "market_data":
            continue
        data[k] = _walk_fix(data[k])

    def _clean_list(items: list, check_date: bool = True) -> list:
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            canonical_source = canonicalize_source(
                str(it.get("source") or ""),
                str(it.get("source_url") or it.get("link") or ""),
            )
            if not canonical_source:
                stats["invalid_source"] += 1
                continue
            it["source"] = canonical_source
            sd = str(it.get("source_date") or "")
            if check_date and _re.match(r"\d{4}-\d{2}-\d{2}$", sd) and sd < cutoff_date:
                stats["stale"] += 1
                continue
            head = it.get("headline") or it.get("title") or ""
            # 標題只在「有行情主詞（股價／指數／幣價／油價／ticker）＋漲跌％」才整條丟；
            # 合約價／營收／出口「大漲 X%」是事件數據，不是行情，要留（2026-09-19 隨日報改英文同步改英文詞）
            if _MARKET_SENT_RE.search(head) and not _re.search(
                r"contract price|contract prices|pricing|ASP|revenue|sales|exports|orders|shipments|bookings|backlog",
                head, _re.I):
                stats["market_head"] += 1
                continue
            # 2026-09-19 首份英文日報實測發現的既有漏洞（中文時期就在）：evidence 與
            # confirmed_impact 從來沒過行情句過濾，「shares fell as much as 7%」就這樣
            # 出現在 Evidence 欄。market_move 不列入——那一欄本來就是放漲跌的。
            for f in ("body", "summary", "why", "evidence", "confirmed_impact"):
                if f in it:
                    new, cut = _strip_market_sentences(it[f])
                    if cut:
                        stats["market_sent"] += 1
                        it[f] = new
            out.append(it)
        return out

    for key in _NEWS_LIST_BLOCKS + ["smart_money", "watchlist_news", "weekend_reads"]:
        if isinstance(data.get(key), list):
            data[key] = _clean_list(data[key], check_date=key not in ("tech_trends", "daily_deep_dive", "weekend_reads", "frontier_tech"))

    # 分類事實新聞不只信 prompt：類別、事實欄位、狀態與類別上限都做硬驗證。
    industry_kept = []
    category_counts = {}
    industry_counts = {}
    for item in data.get("industry_developments", []) if isinstance(data.get("industry_developments"), list) else []:
        raw_category = _re.sub(r"[\s／/]+", "", str(item.get("category") or "")).casefold()
        category = _FACT_CATEGORY_ALIASES.get(raw_category)
        raw_industry = _re.sub(r"[\s／/]+", "", str(item.get("industry") or "")).casefold()
        industry = _INDUSTRY_ALIASES.get(raw_industry)
        raw_fact_status = str(item.get("fact_status") or "").strip()
        fact_status = _FACT_STATUS_ALIASES.get(raw_fact_status, raw_fact_status)
        development_parts = [
            part for part in _re.split(r"[\s／/|,、]+", str(item.get("development") or "")) if part
        ]
        complete = all(str(item.get(field) or "").strip() for field in ("headline", "body"))
        evidence = str(item.get("evidence") or "").strip()
        body = str(item.get("body") or "").strip()
        has_fact_anchor = bool(_FACT_ANCHOR_RE.search(f"{body} {evidence}"))
        valid_development = bool(development_parts) and all(
            part in _INDUSTRY_DEVELOPMENT_TYPES for part in development_parts
        )
        market_move = str(item.get("market_move") or "").strip()
        valid_market_move = category != "US sector moves" or bool(
            _MARKET_MOVE_FACT_RE.search(market_move)
        )
        if (
            not category or not industry or fact_status not in _FACT_STATUSES or not complete
            or not has_fact_anchor or not valid_development or not valid_market_move
            or category_counts.get(category, 0) >= 4 or industry_counts.get(industry, 0) >= 4
        ):
            stats["industry_quality"] += 1
            continue
        for field in ("body", "confirmed_impact"):
            cleaned, cut = _strip_inference_sentences(str(item.get(field) or ""))
            if cut:
                stats["inference_trimmed"] += 1
                item[field] = cleaned
        if not str(item.get("body") or "").strip():
            stats["industry_quality"] += 1
            continue
        item["category"] = category
        item["industry"] = industry
        item["fact_status"] = fact_status
        item["evidence"] = evidence or _re.split(r"(?<=[。；;])", body, maxsplit=1)[0].strip()
        item["unknowns"] = str(item.get("unknowns") or "").strip() or "Nothing else outstanding in the material."
        item["development"] = "／".join(development_parts)
        category_counts[category] = category_counts.get(category, 0) + 1
        industry_counts[industry] = industry_counts.get(industry, 0) + 1
        industry_kept.append(item)
        if len(industry_kept) >= 18:
            break
    data["industry_developments"] = industry_kept
    rt = data.get("regional_tech")
    if isinstance(rt, dict):
        for region, items in rt.items():
            if isinstance(items, list):
                rt[region] = _clean_list(items)
    # us_market_recap：只留「上一個 US session」公布的財報（沒有日期或日期不符一律丟）
    recap = data.get("us_market_recap")
    if isinstance(recap, dict):
        if isinstance(recap.get("other_events"), list):
            recap["other_events"] = _clean_list(recap["other_events"], check_date=False)
    if isinstance(recap, dict) and isinstance(recap.get("earnings"), list):
        session = _last_us_session_date()
        kept = []
        for it in recap["earnings"]:
            if not isinstance(it, dict):
                continue
            canonical_source = canonicalize_source(
                str(it.get("source") or ""), str(it.get("source_url") or "")
            )
            if not canonical_source:
                stats["invalid_source"] += 1
                continue
            it["source"] = canonical_source
            rd = str(it.get("report_date") or "")
            if not _re.match(r"\d{4}-\d{2}-\d{2}$", rd) or rd != session:
                stats["recap_stale"] += 1
                continue
            kept.append(it)
        recap["earnings"] = kept
        if isinstance(recap.get("summary"), str):
            new_sum, cut = _strip_market_sentences(recap["summary"])
            if cut:
                recap["summary"] = new_sum
                stats["market_sent"] += 1
        if not kept and not recap.get("other_events"):
            recap["has_events"] = False

    if any(stats.values()):
        print(
            f"  → sanitize: 過期 {stats['stale']}、非白名單 {stats['invalid_source']}、"
            f"行情標題 {stats['market_head']}、行情句 {stats['market_sent']}、"
            f"產業品質 {stats['industry_quality']}、推論句 {stats['inference_trimmed']}、"
            f"昨日美股非當日財報 {stats['recap_stale']}"
        )
    return stats


def process_news(raw_news: list[dict], market_data: dict | None = None, today_earnings: list | None = None, moneydj_news: list[dict] | None = None, deep_dive_news: list[dict] | None = None, move_index_raw: str = "", earnings_deep_dive: list[dict] | None = None, prev_regime: dict | None = None, watchlist: list[dict] | None = None, news_quality: dict | None = None) -> dict:
    news_text = build_news_text(raw_news, moneydj_news, deep_dive_news)

    market_context = ""
    if market_data:
        market_context = _build_market_context(market_data, today_earnings, move_index_raw, prev_regime)

    # 財報上下文（給 Gemini 用）— 下一個 US session 即將發布
    earnings_lines = []
    if today_earnings:
        earnings_lines.append("[yfinance-confirmed earnings due in the NEXT US session]")
        for e in today_earnings:
            earnings_lines.append(f"{e['ticker']} ({e.get('time','—')})")
        earnings_lines.append("Set yfinance_confirmed=true for these; false for anything else.")
    earnings_context = "\n".join(earnings_lines)

    # 深度財報 Perplexity 原始資料（給 Gemini Pro 做分析用）
    earnings_raw_text = _build_earnings_raw_text(earnings_deep_dive)

    # ── 並行呼叫（三條都是 Claude Code 主、Gemini/API 備援）：分析 + 新聞 + 深度財報 ──
    analysis_data = {}
    gemini_data = {}
    earnings_analysis_data = {}

    def _call_analysis_with_fallback():
        """Claude Code（Max 訂閱）為主 → Gemini Pro → Claude API"""
        try:
            return _cc_analysis(market_context, news_text)
        except Exception as e:
            print(f"  ⚠ [Analysis / Claude Code] failed: {e}, falling back to Gemini Pro...")
        try:
            return _call_gemini_pro(market_context, news_text)
        except Exception as e:
            print(f"  ⚠ [Gemini Pro] failed: {e}, falling back to Claude API...")
            return _call_claude(market_context, news_text)

    def _call_news_with_fallback():
        """Claude Code（Max 訂閱）為主 → Gemini Flash"""
        try:
            return _cc_news(news_text, earnings_context, watchlist)
        except Exception as e:
            print(f"  ⚠ [News / Claude Code] failed: {e}, falling back to Gemini Flash...")
            return _call_gemini(news_text, earnings_context, watchlist)

    def _call_earnings_with_fallback():
        """Claude Code（Max 訂閱）為主 → Gemini Pro → Claude API；空 stub 也往下掉"""
        try:
            result = _cc_earnings(earnings_raw_text, market_context)
            if not (_has_earnings_content(earnings_raw_text)
                    and (not result.get("has_content") or not result.get("companies"))):
                return result
            print("  ⚠ [Earnings Analysis / Claude Code] returned empty stub despite valid input, falling back to Gemini Pro...")
        except Exception as e:
            print(f"  ⚠ [Earnings Analysis / Claude Code] failed: {e}, falling back to Gemini Pro...")

        try:
            result = _call_gemini_pro_earnings(earnings_raw_text, market_context)
        except Exception as e:
            print(f"  ⚠ [Earnings Analysis / Gemini Pro] failed: {e}, falling back to Claude Sonnet 4.6...")
            return _call_claude_earnings_analysis(earnings_raw_text, market_context)

        # Gemini Pro 傾向嚴格解讀排除規則，有時輸入有實質內容卻回空 stub。
        # 只有在確定輸入有料（passed _has_earnings_content）時才 fallback。
        if _has_earnings_content(earnings_raw_text):
            empty_result = (
                not result.get("has_content")
                or not result.get("companies")
            )
            if empty_result:
                print("  ⚠ [Earnings Analysis / Gemini Pro] returned empty stub despite valid input, falling back to Claude Sonnet 4.6...")
                return _call_claude_earnings_analysis(earnings_raw_text, market_context)
        return result

    with ThreadPoolExecutor(max_workers=3) as executor:
        analysis_future = executor.submit(_call_analysis_with_fallback)
        gemini_future = executor.submit(_call_news_with_fallback)
        earnings_future = executor.submit(_call_earnings_with_fallback)

        try:
            analysis_data = analysis_future.result()
            print(f"  ✓ Analysis sections received")
        except Exception as e:
            print(f"  ✗ Analysis failed (Claude Code & Gemini Pro & Claude API): {e}")

        try:
            gemini_data = gemini_future.result()
            print(f"  ✓ News sections received")
        except Exception as e:
            print(f"  ✗ News failed (Claude Code & Gemini Flash): {e}")

        try:
            earnings_analysis_data = earnings_future.result()
            print(f"  ✓ [Earnings Analysis] received")
        except Exception as e:
            print(f"  ✗ [Earnings Analysis] failed: {e}")

    # ── 合併：分析區塊 + Gemini 新聞 ──
    data = {}

    # 分析區塊（Claude Code / Gemini Pro / Claude API 三者之一）
    for key in ["daily_summary", "alert", "regime", "market_pulse", "index_factor_reading",
                "sentiment_analysis", "daily_deep_dive", "tech_trends",
                "system_status", "smart_money"]:
        if key in analysis_data:
            data[key] = analysis_data[key]

    # 分析模型的 market_data 只有 move_index
    analysis_move = analysis_data.get("market_data", {}).get("move_index", {})

    # Gemini 新聞區塊
    for key in ["top_stories", "industry_developments", "watchlist_news", "weekend_reads", "macro", "ai_industry", "regional_tech",
                "fintech_crypto", "geopolitical", "world_news", "startup_news", "frontier_tech",
                "us_market_recap", "earnings_preview", "today_events", "fun_fact"]:
        if key in gemini_data:
            data[key] = gemini_data[key]

    # 深度財報分析
    if earnings_analysis_data:
        data["earnings_deep_analysis"] = earnings_analysis_data

    # 注入真實市場數據
    if market_data:
        data["market_data"] = market_data
        data["market_data"]["move_index"] = analysis_move
    data["_market_context_text"] = market_context  # 供 main.py 存 regime 快照（不渲染）

    # 後處理：過期／行情句／簡繁錯字 → 再跨區塊去重（code-based）
    sanitize_stats = _sanitize_news(data, _news_date_window()[1])
    dedup_stats = _dedup_news(data)
    if isinstance(deep_dive_news, dict):
        deep_search_items = [
            item
            for key in ("fixed", "dynamic")
            for item in deep_dive_news.get(key, [])
        ]
    else:
        deep_search_items = deep_dive_news or []
    data["_news_quality"] = {
        **(news_quality or {}),
        "sanitize": sanitize_stats,
        "events": dedup_stats,
        "planned_search_calls": {
            "base_news": len(raw_news),
            "deep_dive": len(deep_search_items),
            "move_index": 1,
        },
        "successful_search_calls": {
            "base_news": sum(bool(item.get("answer")) for item in raw_news),
            "deep_dive": sum(
                bool(item.get("answer") or item.get("result"))
                for item in deep_search_items
            ),
        },
        "output_counts": {
            "top_stories": len(data.get("top_stories", [])),
            "industry_developments": len(data.get("industry_developments", [])),
            "macro": len(data.get("macro", [])),
            "ai_industry": len(data.get("ai_industry", [])),
            "tech_trends": len(data.get("tech_trends", [])),
            "startup_news": len(data.get("startup_news", [])),
            "frontier_tech": len(data.get("frontier_tech", [])),
        },
        "fact_category_counts": {
            category: sum(
                item.get("category") == category
                for item in data.get("industry_developments", [])
                if isinstance(item, dict)
            )
            for category in _FACT_CATEGORY_ALIASES.values()
        },
    }

    _validate(data)

    print(f"  → stories={len(data.get('top_stories',[]))}, "
          f"industry={len(data.get('industry_developments',[]))}, "
          f"macro={len(data.get('macro',[]))}, "
          f"ai={len(data.get('ai_industry',[]))}, "
          f"tech={len(data.get('tech_trends',[]))}, "
          f"startup={len(data.get('startup_news',[]))}, "
          f"frontier={len(data.get('frontier_tech',[]))}")

    return data


def _validate(data: dict) -> None:
    data.setdefault("daily_summary", "")
    data.setdefault("alert", "")
    data.setdefault("market_data", {})
    data.setdefault("top_stories", [])
    data.setdefault("industry_developments", [])
    data.setdefault("macro", [])
    data.setdefault("ai_industry", [])
    data.setdefault("regional_tech", {"taiwan": [], "japan": [], "us": [], "korea": [], "china": [], "europe": [], "asean": []})
    data.setdefault("fintech_crypto", [])
    data.setdefault("geopolitical", [])
    data.setdefault("world_news", [])
    data["world_news"] = data["world_news"][:3]
    data.setdefault("tech_trends", [])
    data.setdefault("startup_news", [])
    data["startup_news"] = data["startup_news"][:8]
    data.setdefault("frontier_tech", [])
    data["frontier_tech"] = data["frontier_tech"][:5]
    data.setdefault("earnings_preview", [])
    data["implied_trends"] = []  # 已停用，強制清空
    data.setdefault("us_market_recap", {"has_events": False, "earnings": [], "other_events": [], "summary": ""})
    data.setdefault("smart_money", {"has_signals": False, "signals": [], "summary": ""})
    data.setdefault("regime", {
        "call": "", "axes": {}, "contradicts": [], "falsifiers": [],
        "for_w52_engine": "", "confidence": "", "confidence_reason": "",
    })
    if isinstance(data.get("regime"), dict):
        data["regime"].setdefault("review", {"yesterday_call": "", "verdict": "no prior day", "falsifier_check": [], "note": ""})
    data.setdefault("watchlist_news", [])
    data.setdefault("weekend_reads", [])
    data.setdefault("market_pulse", {"hidden_risk": "", "hidden_opportunity": "", "key_level_to_watch": ""})
    data.setdefault("daily_deep_dive", [])
    data.setdefault("index_factor_reading", {"market_structure": ""})
    data.setdefault("sentiment_analysis", {"stage": "No clear signal", "credit_status": ""})
    data.setdefault("fun_fact", {})
    data.setdefault("today_events", [])
    data.setdefault("earnings_deep_analysis", {
        "has_content": False,
        "window": "",
        "overview": "",
        "companies": [],
        "industry_trends": [],
        "winners": [],
        "losers": [],
        "contradictions": [],
        "conclusion": "",
    })

    ss = data.setdefault("system_status", {})
    ss.setdefault("fixed", [])
    ss.setdefault("dynamic", [])
    ss["fixed"]   = ss["fixed"][:3]
    ss["dynamic"] = ss["dynamic"][:3]

    # implied_trends 已停用，不再處理

    for trend in data.get("tech_trends", []):
        trend.setdefault("sub_items", [])
        trend.setdefault("chips", [])
        trend.setdefault("label_type", "other")
        trend["sub_items"] = trend["sub_items"][:3]

    md = data.get("market_data", {})
    md.setdefault("indices", [])
    md.setdefault("factors", [])
    md.setdefault("sentiment", [])
    md.setdefault("move_index", {"val": "—", "interpretation": ""})
    md.setdefault("commodities", [])
    md.setdefault("bonds", [])
    md.setdefault("fx", [])
    md.setdefault("credit", [])
    md.setdefault("liquidity", [])
    md.setdefault("liquidity_assessment", {"label": "—", "color": "neu", "score": 0, "signals": []})

    rt = data.get("regional_tech", {})
    for region in ["taiwan", "japan", "us", "korea", "china", "europe", "asean"]:
        rt.setdefault(region, [])
