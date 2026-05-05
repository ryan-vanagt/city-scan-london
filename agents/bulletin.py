"""
Bulletin Agent — LangChain prompt chain.

Generates a structured daily city health digest. Triggered by APScheduler
(daily) and on-demand via POST /bulletin/generate.

Chain:
  1. Fetch current Gold scores for all boroughs (direct DuckDB query)
  2. Query DuckDB for top 3 notable trends this week
  3. Fetch latest Guardian headlines (headline + URL only)
  4. Synthesise into markdown bulletin with cited sources

Output saved to /data/bulletins/YYYY-MM-DD.md.
Every run logged to the bulletin_logs table in agent_logs.duckdb.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agents.logging_db import log_bulletin
from agents.tools.borough_query import compare_boroughs
from agents.tools.health_score import get_london_score
from agents.tools.trend_analysis import get_trend

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BULLETINS_DIR = PROJECT_ROOT / "data" / "bulletins"

MODEL_NAME = "claude-haiku-4-5"

SYSTEM_PROMPT = """\
You are the City Doctor writing a daily health bulletin for London. You will \
receive structured data about London's health scores and recent news headlines. \
Synthesise this into a clear, well-structured markdown bulletin.

London is modelled as a human body with five organ systems: Lungs (air quality), \
Arteries (transit), Brain (sentiment), Immune (crime + A&E), and Skin (green space). \
Include all five systems in the Organ Systems table.

Rules:
1. Use ONLY the data provided — do not fabricate scores or statistics.
2. Present scores rounded to one decimal place.
3. Frame the bulletin in medical metaphors when natural, but prioritise clarity.
4. The immune system data (crime + A&E) has a reporting lag. The actual \
data period is provided in the data below — quote it exactly when reporting \
immune scores. Do NOT guess or calculate the period yourself.
5. If Guardian headlines are provided, they are already formatted as markdown \
links — preserve them exactly as provided. Do NOT rewrite the URLs. List them \
as context but do NOT draw causal connections between headlines and scores. \
If NO headlines section is provided, do NOT invent or fabricate any news \
headlines — simply omit the "In the News" section entirely.
6. Do not speculate on causes — only report what the data shows.
7. Keep the bulletin concise — aim for ~500 words.
8. Do NOT include a "next bulletin" date — the schedule is not fixed.
9. When deprivation context (IMD 2025) is provided for worst-scoring boroughs, \
note the structural disadvantage in your Diagnosis section. Highlight where \
deprivation aligns with poor health scores — this is the key insight.
10. Before the Signal of the Day, include a brief "Prognosis" section for the \
3 worst-scoring boroughs: which organs are improving, stable, or declining. \
One line per borough. NEVER report the Skin (green space) organ OR the \
modelled Lungs score (`air_quality_modelled_score`, LAEI 2022) as \
improving, declining, or changed — both are yearly static snapshots. \
Report them as stable if mentioned at all. The live `air_score` (OpenAQ) \
is the only Lungs signal that can move hour to hour.
11. End the bulletin with a "Signal of the Day": the single most notable \
cross-domain pattern in today's data. What changed, what's surprising, what \
diverges from the structural deprivation baseline. One paragraph, max 4 \
sentences. Cite specific numbers. Do NOT speculate on causation — surface \
the pattern. Look for what CHANGED today, not what's always been worst.
12. If a "Reliability Watch" line is provided in the data, render it as a \
short note immediately after the Organ Systems table — boroughs whose \
underlying signals are sparse today (e.g. zero live air sensors) should be \
flagged so the reader knows to triangulate any borough-level claim about \
them.
13. If an "External Agreement" line is provided (CityScan vs ONS Health \
Index 2021), render it as a one-sentence note at the end of the Diagnosis \
section. Frame divergence as informative ("CityScan and ONS diverge most \
at borough X — different lenses, different priorities"), not as error in \
either tool.\
"""


def _get_immune_data_period() -> str | None:
    """Read the actual data period from bronze immune source files.

    Checks Met Police (has 'date' field like '2026-02') and NHS A&E
    (has 'period' field like 'MSitAE-FEBRUARY-2026'). Returns a
    human-readable string like 'February 2026' or None if unavailable.
    """
    bronze_root = PROJECT_ROOT / "data" / "bronze"
    period = None

    # Try Met Police first — has clean YYYY-MM date
    met_dir = bronze_root / "met_police"
    if met_dir.exists():
        try:
            files = sorted(met_dir.iterdir())
            if files:
                import json as _json
                data = _json.loads(files[-1].read_text(encoding="utf-8"))
                raw_date = data.get("date", "")  # e.g. "2026-02"
                if raw_date:
                    dt = datetime.strptime(raw_date, "%Y-%m")
                    period = dt.strftime("%B %Y")  # e.g. "February 2026"
        except Exception:
            logger.debug("Could not read Met Police data period from bronze")

    # Fallback: try NHS A&E
    if not period:
        nhs_dir = bronze_root / "nhs_ae"
        if nhs_dir.exists():
            try:
                files = sorted(nhs_dir.iterdir())
                if files:
                    import json as _json
                    data = _json.loads(files[-1].read_text(encoding="utf-8"))
                    raw_period = data.get("period", "")  # e.g. "MSitAE-FEBRUARY-2026"
                    if raw_period:
                        parts = raw_period.split("-")
                        # Extract month name and year
                        month = parts[1].capitalize() if len(parts) >= 3 else ""
                        year = parts[2] if len(parts) >= 3 else ""
                        if month and year:
                            period = f"{month} {year}"
            except Exception:
                logger.debug("Could not read NHS A&E data period from bronze")

    return period


def _fetch_headlines() -> list[dict]:
    """Fetch Guardian headlines for the bulletin. Returns [] on failure.

    Uses a direct requests.get call instead of importing from the ingestion
    package, because the API container does not include ingestion sources.
    """
    import requests

    api_key = os.environ.get("GUARDIAN_API_KEY", "")
    params = {
        "q": "london",
        "tag": "uk/london",
        "show-fields": "headline",
        "page-size": 5,
        "order-by": "newest",
        "api-key": api_key or "test",
    }

    try:
        resp = requests.get(
            "https://content.guardianapis.com/search",
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("response", {}).get("results", [])
        return [
            {
                "headline": a.get("fields", {}).get("headline", a.get("webTitle", "")),
                "url": a.get("webUrl", ""),
            }
            for a in articles
            if a.get("webUrl")
        ]
    except Exception:
        logger.warning("Bulletin: Guardian fetch failed — proceeding without headlines")
        return []


def _build_reliability_watch(score_quality: dict | None, worst: list[dict]) -> str | None:
    """Compose a "Reliability Watch" sentence flagging boroughs whose
    bootstrappable organs (air, transit, immune) are red-flagged today.

    Restricts the watch list to the worst-scoring boroughs to avoid burying
    the bulletin in metadata. Returns None when nothing is worth flagging.
    """
    if not score_quality or not worst:
        return None
    red_watch: list[tuple[str, list[str]]] = []
    amber_concentration: list[str] = []
    worst_codes = [b.get("borough_code") for b in worst if b.get("borough_code")]
    for code in worst_codes:
        b = score_quality.get(code)
        if not b:
            continue
        organs = b.get("organs", {})
        red_organs: list[str] = []
        amber_count = 0
        for organ_key in ("air_score", "transit_score", "immune_score"):
            flag = organs.get(organ_key, {}).get("flag")
            if flag == "red":
                red_organs.append(organ_key.removesuffix("_score").replace("_", " "))
            elif flag == "amber":
                amber_count += 1
        name = b.get("borough_name", code)
        if red_organs:
            red_watch.append((name, red_organs))
        elif amber_count >= 2:
            # No red, but ≥2 of 3 bootstrappable inputs are amber → wide CIs
            # collectively, even if no single signal is sparse.
            amber_concentration.append(name)
    if not red_watch and not amber_concentration:
        return None
    parts: list[str] = []
    if red_watch:
        red_text = "; ".join(f"{n} ({', '.join(o)})" for n, o in red_watch)
        parts.append(
            "Sparse underlying data today in: " + red_text
            + ". Borough-level claims about these signals should be treated as indicative only."
        )
    if amber_concentration:
        parts.append(
            "Wide CIs across multiple organs in: "
            + ", ".join(amber_concentration)
            + ". Composite changes here may reflect input noise more than signal."
        )
    return " ".join(parts)


_EXTERNAL_VALIDITY_MIN_PAIRS = 20


def _build_external_validity(
    health_index: dict | None,
    london_score: dict,
    worst: list[dict],
    best: list[dict],
) -> str | None:
    """Compose a one-sentence comparison between CityScan and the ONS Health
    Index across all paired boroughs (typically 32 of 33; City of London is
    excluded from the ONS dataset by convention). Surfaces the single
    largest divergence in centred residual space. Returns None when fewer
    than _EXTERNAL_VALIDITY_MIN_PAIRS pairs are available.
    """
    if not health_index:
        return None
    # Pull a full ranking so the sample is the whole borough set, not just
    # the top/bottom-5. The notable lists are biased to extremes; computing
    # within-set means on 6 boroughs gives a degenerate residual baseline.
    all_ranked = compare_boroughs("composite_score", top_n=33, ascending=False).get("boroughs", [])
    pairs: list[tuple[str, float, float]] = []
    for b in all_ranked:
        code = b.get("borough_code")
        cs_score = b.get("score")
        if not code or cs_score is None:
            continue
        hi_entry = health_index.get(code)
        if not hi_entry or hi_entry.get("not_in_dataset"):
            continue
        hi_score = hi_entry.get("score")
        if hi_score is None:
            for key, value in hi_entry.items():
                if isinstance(key, str) and key.startswith("score_") and key not in (
                    "score_2020",
                    "score_2015",
                ):
                    hi_score = value
                    break
        if hi_score is None:
            continue
        name = hi_entry.get("name") or hi_entry.get("borough_name") or b.get("borough_name") or code
        pairs.append((name, cs_score, hi_score))
    if len(pairs) < _EXTERNAL_VALIDITY_MIN_PAIRS:
        return None
    cs_mean = sum(p[1] for p in pairs) / len(pairs)
    hi_mean = sum(p[2] for p in pairs) / len(pairs)
    divergences = [(p[0], (p[1] - cs_mean) - (p[2] - hi_mean)) for p in pairs]
    divergences.sort(key=lambda x: -abs(x[1]))
    top_div = divergences[0]
    direction = "CityScan reads relatively healthier" if top_div[1] > 0 else "CityScan reads relatively worse"
    return (
        f"External agreement (vs ONS Health Index 2021): across {len(pairs)} "
        f"paired boroughs, {top_div[0]} shows the largest divergence — "
        f"{direction} than the official health measure suggests. Different "
        "lenses; the gap is itself a finding."
    )


def _load_score_quality_static() -> dict | None:
    """Lazy-load the per-organ score-quality JSON if present."""
    path = PROJECT_ROOT / "data" / "static" / "score_quality.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("boroughs")
    except Exception:
        logger.warning("Bulletin: failed to load score_quality.json")
        return None


def _load_health_index_static() -> dict | None:
    """Lazy-load the ONS Health Index JSON if present."""
    path = PROJECT_ROOT / "data" / "static" / "ons_health_index.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("boroughs")
    except Exception:
        logger.warning("Bulletin: failed to load ons_health_index.json")
        return None


def _build_data_prompt(
    london_score: dict,
    best: list[dict],
    worst: list[dict],
    trends: list[dict],
    headlines: list[dict],
    date_str: str,
    immune_period: str | None = None,
    deprivation: dict[str, dict] | None = None,
    reliability_watch: str | None = None,
    external_validity: str | None = None,
) -> str:
    """Format all collected data into the LLM prompt."""
    sections = [f"Date: {date_str}\n"]

    # Overall scores
    sections.append("## London Overall Scores")
    sections.append(f"- Composite: {london_score.get('composite_score')}")
    sections.append(f"- Air Quality live (Lungs, OpenAQ): {london_score.get('air_score')}")
    sections.append(f"- Air Quality modelled (Lungs, LAEI 2022 static): {london_score.get('air_quality_modelled_score')}")
    sections.append(f"- Transit (Arteries): {london_score.get('transit_score')}")
    sections.append(f"- Sentiment (Brain): {london_score.get('sentiment_score')}")
    sections.append(f"- Crime+A&E (Immune): {london_score.get('immune_score')}")
    sections.append(f"- Green Space coverage (Skin, static): {london_score.get('green_space_score')}")
    sections.append(f"- Green Space access-weighted (Skin, static): {london_score.get('green_space_access_score')}")
    if immune_period:
        sections.append(f"- Immune data period: {immune_period}")
    sections.append(f"- Borough count: {london_score.get('borough_count')}")
    sections.append(f"- Data timestamp: {london_score.get('timestamp')}\n")

    # Best boroughs
    sections.append("## Healthiest Boroughs")
    for b in best:
        sections.append(f"- #{b['rank']} {b['borough_name']}: {b['score']}")
    sections.append("")

    # Worst boroughs
    sections.append("## Boroughs Needing Attention")
    for b in worst:
        sections.append(f"- #{b['rank']} {b['borough_name']}: {b['score']}")
    sections.append("")

    # Deprivation context for worst boroughs
    if deprivation:
        sections.append("## Deprivation Context (IMD 2025)")
        for code, dep in deprivation.items():
            # Find top 3 worst domains for this borough
            domains = dep.get("domains", {})
            worst_domains = sorted(domains.items(), key=lambda x: x[1]["rank"])[:3]
            domain_str = ", ".join(
                f"{name} (rank {vals['rank']}/296)" for name, vals in worst_domains
            )
            sections.append(
                f"- {dep['borough_name']}: IMD rank {dep['imd_rank']}/296 nationally "
                f"({dep['pct_most_deprived_10']}% of areas in most deprived 10%). "
                f"Worst domains: {domain_str}"
            )
        sections.append("")

    # Trends
    if trends:
        sections.append("## Notable Trends (7-day)")
        for t in trends:
            arrow = {"improving": "↑", "declining": "↓", "stable": "→"}.get(
                t.get("direction", ""), "?"
            )
            sections.append(
                f"- {t['borough_name']}: {arrow} {t.get('direction', 'unknown')} "
                f"(delta: {t.get('delta')})"
            )
        sections.append("")

    # Headlines
    if headlines:
        sections.append("## Recent London Headlines (Guardian)")
        for h in headlines:
            sections.append(f"- [{h['headline']}]({h['url']})")
        sections.append("")

    # Reliability watch — boroughs whose bootstrappable organs are red-flagged today
    if reliability_watch:
        sections.append("## Reliability Watch")
        sections.append(reliability_watch)
        sections.append("")

    # External validity — CityScan vs ONS Health Index agreement / divergence
    if external_validity:
        sections.append("## External Agreement")
        sections.append(external_validity)
        sections.append("")

    # No policy context needed — Signal of the Day is purely data-driven

    sections.append(
        "Write a markdown bulletin with these sections: "
        "Overall Score, Organ Systems (table), Notable Boroughs, "
        "In the News, Diagnosis, Signal of the Day. "
        "Start with: # London Health Bulletin — " + date_str
    )

    return "\n".join(sections)


def generate_bulletin(trigger: str = "manual") -> dict:
    """Generate a daily London health bulletin.

    Intentionally synchronous — FastAPI runs sync endpoint handlers in its
    default thread pool (anyio), so this does not block the event loop.

    Fetches data via direct DuckDB queries and Guardian API, synthesises
    a markdown bulletin via LLM, saves to disk, and logs the run.

    Args:
        trigger: 'manual' or 'scheduled' — recorded in bulletin_logs.

    Returns:
        Dict with 'date', 'content' (markdown string), and 'output_path'.
        On failure, returns dict with 'error' key.
    """
    start = time.monotonic()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Fetch London-wide scores
    london_score = get_london_score()
    if london_score.get("borough_count", 0) == 0:
        return {"error": "No gold_scores data available — run the pipeline first"}

    # 2. Fetch best and worst boroughs
    best_result = compare_boroughs("composite_score", top_n=5, ascending=False)
    worst_result = compare_boroughs("composite_score", top_n=5, ascending=True)
    best = best_result.get("boroughs", [])
    worst = worst_result.get("boroughs", [])

    # 2b. Fetch deprivation context for worst boroughs
    from agents.tools.deprivation import get_deprivation
    deprivation: dict[str, dict] = {}
    for b in worst:
        dep = get_deprivation(b.get("borough_code", ""))
        if "error" not in dep:
            deprivation[b["borough_code"]] = dep

    # 3. Fetch trends for top 3 best and worst
    trend_boroughs = [b["borough_code"] for b in best[:3]] + [
        b["borough_code"] for b in worst[:3]
    ]
    trends = []
    for code in trend_boroughs:
        t = get_trend(code, "composite_score", 7)
        if t.get("found"):
            trends.append(t)

    # 4. Fetch Guardian headlines (fault-tolerant)
    headlines = _fetch_headlines()

    # 4b. Fetch actual immune data period from bronze files
    immune_period = _get_immune_data_period()

    # 4c. Load static reliability + external-validity context (best-effort)
    score_quality = _load_score_quality_static()
    health_index = _load_health_index_static()
    reliability_watch = _build_reliability_watch(score_quality, worst)
    external_validity = _build_external_validity(health_index, london_score, worst, best)

    # 5. Build prompt and call LLM
    data_prompt = _build_data_prompt(
        london_score, best, worst, trends, headlines, date_str,
        immune_period=immune_period,
        deprivation=deprivation,
        reliability_watch=reliability_watch,
        external_validity=external_validity,
    )

    llm = ChatAnthropic(model=MODEL_NAME, max_tokens=4096)
    response = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=data_prompt),
    ])

    content = response.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )

    # 6. Save to disk (atomic write via temp file + rename)
    BULLETINS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = str(BULLETINS_DIR / f"{date_str}.md")
    temp_path = str(Path(output_path).with_suffix(".tmp"))
    Path(temp_path).write_text(content, encoding="utf-8")
    os.replace(temp_path, output_path)
    logger.info("Bulletin saved to %s", output_path)

    # 6b. Save scores JSON sidecar so the frontend can show the bulletin's
    # own scores instead of mixing in live data that drifts throughout the day.
    sources_data = {
        "london_score": london_score,
        "best_boroughs": best,
        "worst_boroughs": worst,
        "trends": [
            {
                "borough_name": t["borough_name"],
                "direction": t.get("direction"),
                "delta": t.get("delta"),
            }
            for t in trends
        ],
        "headlines": headlines,
    }
    json_path = str(BULLETINS_DIR / f"{date_str}.json")
    json_tmp = str(Path(json_path).with_suffix(".jtmp"))
    Path(json_tmp).write_text(json.dumps(sources_data, default=str), encoding="utf-8")
    os.replace(json_tmp, json_path)
    logger.info("Bulletin scores saved to %s", json_path)

    # 7. Log the run
    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        log_bulletin(
            trigger=trigger,
            scores_used=london_score,
            headlines_used=headlines,
            output_path=output_path,
            latency_ms=elapsed_ms,
        )
    except Exception:
        logger.exception("Failed to log bulletin generation")

    return {
        "date": date_str,
        "content": content,
        "output_path": output_path,
        "sources": sources_data,
    }
