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

MODEL_NAME = "claude-sonnet-4-5-20241022"

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
10. Before Prescriptions, include a brief "Prognosis" section for the 3 worst-scoring \
boroughs: which organs are improving, stable, or declining. One line per borough.
11. End the bulletin with a "Prescriptions" section: 2-3 targeted recommendations \
for the worst-scoring boroughs. Frame as neutral clinical recommendations — \
"the data indicates..." not "the council should..." — since this bulletin is \
read by all audiences (policymakers and the public). Each \
prescription must cite the specific data point that triggered it AND reference \
a real policy from the policy context provided. Format: "For [Borough]'s \
[Organ]: [recommendation] ([policy reference])." Never invent a policy name.\
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


def _build_data_prompt(
    london_score: dict,
    best: list[dict],
    worst: list[dict],
    trends: list[dict],
    headlines: list[dict],
    date_str: str,
    immune_period: str | None = None,
    deprivation: dict[str, dict] | None = None,
) -> str:
    """Format all collected data into the LLM prompt."""
    sections = [f"Date: {date_str}\n"]

    # Overall scores
    sections.append("## London Overall Scores")
    sections.append(f"- Composite: {london_score.get('composite_score')}")
    sections.append(f"- Air Quality (Lungs): {london_score.get('air_score')}")
    sections.append(f"- Transit (Arteries): {london_score.get('transit_score')}")
    sections.append(f"- Sentiment (Brain): {london_score.get('sentiment_score')}")
    sections.append(f"- Crime+A&E (Immune): {london_score.get('immune_score')}")
    sections.append(f"- Green Space (Skin): {london_score.get('green_space_score')}")
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

    # Append policy context summary for prescriptions
    sections.append("## Policy Context (for Prescriptions section)")
    sections.append(
        "Reference these verified London policies when writing prescriptions: "
        "London Plan G4/G5 (green space/urban greening), Borough Air Quality Action Plans, "
        "Mayor's Police and Crime Plan 2025-2029, Violence Reduction Unit, "
        "NHS Long Term Plan (Urgent Treatment Centres), London Health Inequalities Strategy, "
        "Marmot Review (proportionate universalism), Healthy Streets Approach, "
        "Mayor's Transport Strategy (80% sustainable trips by 2041)."
    )
    sections.append("")

    sections.append(
        "Write a markdown bulletin with these sections: "
        "Overall Score, Organ Systems (table), Notable Boroughs, "
        "In the News, Diagnosis, Prescriptions. "
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

    # 5. Build prompt and call LLM
    data_prompt = _build_data_prompt(
        london_score, best, worst, trends, headlines, date_str,
        immune_period=immune_period,
        deprivation=deprivation,
    )

    llm = ChatAnthropic(model=MODEL_NAME)
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
