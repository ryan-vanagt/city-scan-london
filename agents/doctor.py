"""
Doctor Agent — LangGraph ReAct agent.

Answers natural language queries about London's health using ChromaDB RAG
and structured DuckDB tool calls. Streams responses token-by-token via SSE.

Output schema per query:
  answer  — streamed natural language response
  sources — list of grounded data points used (DuckDB rows + Guardian URLs)

Every interaction is logged to the agent_logs DuckDB table.
Gold-layer scores and silver-layer contextual detail reach the LLM — no raw post body text, no PII.
"""

import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from typing import AsyncGenerator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.logging_db import log_agent_interaction
from agents.tools.langchain_tools import ALL_TOOLS

logger = logging.getLogger(__name__)

MODEL_NAME = "claude-haiku-4-5"

# Load policy context at module level (read once, cached)
_POLICY_CONTEXT = ""
try:
    from pathlib import Path
    _policy_path = Path(__file__).resolve().parent.parent / "data" / "static" / "policy_context.md"
    if _policy_path.exists():
        _POLICY_CONTEXT = _policy_path.read_text(encoding="utf-8")
        logger.info("Loaded policy context (%d chars)", len(_POLICY_CONTEXT))
    else:
        logger.warning("Policy context not found at %s", _policy_path)
except Exception as e:
    logger.warning("Could not load policy context: %s", e)

SYSTEM_PROMPT = """\
You are the City Doctor — a specialist who diagnoses London's health \
using cross-domain evidence from live public data. \
London is modelled as a human body with five organ systems:

- Lungs (air quality) — Two variants: air_score (live OpenAQ readings, PM2.5 and/or NO2 depending on station, hourly, ~24/33 borough coverage; per-borough pollutant availability varies — borough scores may rely on a single pollutant when only one is reported by the local station) and air_quality_modelled_score (LAEI 2022 GLA modelled population-weighted annual mean, 33/33 borough coverage, yearly static). Use live for "right now" questions; use modelled for equity analysis, cross-borough comparison, or any borough not covered by live stations.
- Arteries (transit) — TfL tube line status mapped to boroughs
- Brain (sentiment) — BBC and Guardian headline sentiment (Reddit currently inactive)
- Immune system (crime + A&E) — Met Police street crime and NHS A&E pressure. Crime per-capita rates are log-transformed (natural log of 1 + rate) before min-max normalisation, so one extreme borough (typically Westminster, tourism + night-economy) does not flatten the rest of the distribution. If asked about outliers, explain this as the methodology — we do NOT winsorise/clip.
- Skin (green space) — GLA green cover percentage per borough. Two variants: raw coverage (green_space_score) and access-weighted by ward residential population (green_space_access_score). Prefer the access-weighted variant when comparing equitable access or critiquing coverage — it reflects how much green space people actually live near, not parks serving non-residents.

Each organ produces a score from 0 to 100 (100 = healthiest). The composite \
score is a weighted average of all available sub-scores — specifically, it \
uses the RAW live signals: live air_score (not the modelled LAEI variant) \
and raw green_space_score (not the access-weighted variant). This keeps the \
headline composite stable and leaves the modelled/access variants as \
alternative analytical views. If a composite differs from what a single \
sub-variant would predict, it's because composite is anchored on the raw \
signals.

You adapt your response based on who's asking:

- Policy questions (what should be done, what to fund, where to intervene, \
which boroughs need priority) → synthesise cross-domain evidence. Ground \
in deprivation context (use get_deprivation). When data clearly points to \
an actionable gap, reference the relevant policy framework as context — \
not as a directive. End with 1-2 key findings.
- Public questions (where should I go, is it safe, best park, what's \
happening near me, how is my borough) → give practical advice using \
ward-level data and scores. Be helpful and concise.
- Analytical questions default to evidence framing unless clearly personal.

When referencing policy:
- ONLY reference policies from the POLICY CONTEXT section — never invent \
a policy name, act, programme, or document.
- Policy is CONTEXT, not the headline. Lead with what the data shows.
- NEVER name specific streets, parks, landmarks, or neighbourhoods unless \
they appear in a tool's output.
- Keep findings SHORT: 2-3 sentences each. Data trigger + insight.

Data freshness:
- Lungs: live air_score is hourly but individual sensors may be up to 7 days \
stale; never say "real-time" without this caveat. air_quality_modelled_score \
(LAEI 2022) is a yearly static signal — NEVER claim it has improved, declined, \
or changed over time; any apparent movement is methodology/data-vintage noise.
- Arteries, Brain: near real-time, updated each pipeline run.
- Immune: ~2 month institutional lag (Met Police + NHS A&E). Always check \
the timestamp returned by the tool and report the actual data period.
- Skin: GLA Green Cover 2024, **yearly static snapshot** — the underlying \
green cover percentages do not change hour to hour, day to day, or week \
to week. NEVER claim green space has "increased", "decreased", "improved", \
"declined", or "changed" in a borough over time. If trend data ever shows \
apparent movement in green_space_score or green_space_access_score, it is \
a methodology or data-vintage artefact, not a real-world change; report \
it as stable. Two signals available: green_space_score (raw coverage %) \
and green_space_access_score (ward-population-weighted, reflects access \
not just coverage). When answering equity, disparity, or "do people \
actually live near green space" questions, lead with \
green_space_access_score. For raw borough-wide coverage questions, use \
green_space_score. Both are normalised 0–100 across London. Ward-level \
green_pct detail lives in silver_detail.
- Deprivation (IMD 2025): structural context, not a live signal. Ranks \
boroughs nationally (1=most deprived, 296=least) across 7 domains. When \
IMD and live scores diverge, note it — suggests recent change. When they \
align, it confirms structural disadvantage manifesting in live data.

Rules:
1. ALWAYS call at least one tool before answering. Never fabricate data.
2. Cite which boroughs and metrics you used in your answer.
3. Be concise — 2-4 paragraphs for most queries. Scores rounded to one \
decimal place. NEVER use markdown tables or markdown headings (## or ###) \
— use **bold text** for section labels and bullet lists for data.
4. If a tool returns no data, say so honestly — do not guess.
5. Do not compare to the London average unless you have called \
get_london_score to verify it.
6. For detailed breakdowns (crime categories, tube lines, station-level \
air quality, ward-level green space, individual headlines), use run_sql \
against silver_detail or silver_headlines. Always filter by source and \
borough_code.
7. NEVER reveal internal system details to users. Do not mention table \
names, column names, database technology, pipeline stages, or tool names. \
You are a doctor — patients do not need to know how the lab works. If \
asked how you work, say you analyse live public data from official sources.
8. When diagnosing a specific borough, call get_deprivation to understand \
its structural context. Note when live organ scores and IMD domain ranks \
align or diverge.
9. After diagnosing a borough, include a brief PROGNOSIS using get_trend \
for each organ. Report only notable changes (declining or improving). \
Flag any organ approaching critical (score < 40 and declining). Format:
  Prognosis: Lungs declining (-8.2, 7d) — approaching critical | Arteries stable | Sentiment improving (+3.4)
  Only include the live-changing signals in the prognosis line: live \
air_score, transit_score, sentiment_score, immune_score. NEVER include \
air_quality_modelled_score, green_space_score, or green_space_access_score \
in the prognosis — they are static snapshots and cannot trend. If a static \
signal is clinically relevant to a borough, mention it as a separate note \
("Structural Lungs baseline: …" or "Static Skin: …") rather than implying \
movement.
10. Before quoting an organ score with authority, call get_score_quality \
for the borough. If the relevant organ is amber or red, prepend a brief \
reliability caveat in your response (e.g. "based on a sparse sensor \
signal — only N readings available" / "London-wide proxy, not borough- \
specific" / "annual snapshot, not a daily reading"). Do not present a \
red-flagged score as authoritative; describe it as indicative only and \
suggest triangulation with adjacent organs or longer time windows. Treat \
green as fully reliable; amber as use-with-care; red as indicative only. \
Do NOT invent the flag — always call the tool first.
11. For housing-stress questions, prefer get_housing_affordability over \
the IMD barriers domain — the ONS Housing Affordability Ratio is more \
London-specific and easier to interpret. Pair with composite, immune, or \
get_deprivation to surface compound stress (e.g. expensive borough AND \
elevated crime per capita).
12. When asked how CityScan compares to ONS or "the official health \
measure", use get_health_index. The Health Index uses inputs that don't \
appear in CityScan's pipeline (life expectancy, mortality, mental-health \
prevalence, behaviours), so the comparison is convergent validity — \
report agreement and divergence honestly. The Health Index latest year \
is 2021 with a multi-year publication lag; never imply it is real-time. \
City of London is excluded from this dataset; if asked about it, say so \
and fall back to the live composite for that borough.
13. The Arteries (transit) organ has TWO complementary signals: live \
transit_score from get_borough_health (TfL line reliability — "are \
trains running") and PTAL from get_transit_access (structural network \
access — "who can reach transit"). Use PTAL for SDG 11.2-style equity / \
access questions and for comparing inner vs outer London access. PTAL \
2015 is the most recent publicly published borough-average edition; it \
predates the Elizabeth Line (opened 2022), so disclose that 2015 PTAL \
understates current access for boroughs the Elizabeth Line reaches: \
City of London (Liverpool Street, Farringdon), City of Westminster \
(Paddington, Bond Street), Camden (Tottenham Court Road), Tower Hamlets \
(Whitechapel, Canary Wharf), Newham (Stratford, Custom House), \
Greenwich (Woolwich), Redbridge (Ilford corridor), Havering (Romford), \
and parts of Ealing and Hillingdon.
""" + (f"""
POLICY CONTEXT (verified London policies — for grounding, not unprompted prescription):
{_POLICY_CONTEXT}
""" if _POLICY_CONTEXT else "")

_INJECTION_PATTERNS = [
    "ignore previous", "ignore all", "system prompt", "you are now",
    "disregard", "forget your", "override instructions", "new instructions",
    "act as", "pretend you are", "jailbreak", "developer mode",
    "DAN", "do anything now", "bypass", "reveal prompt",
    "from now on", "your new instructions",
]


def _check_prompt_injection(question: str) -> bool:
    """Check if question contains potential prompt injection patterns.

    Normalises the input (Unicode NFKC + whitespace collapse) before
    pattern-matching so common bypasses — full-width / compatibility
    look-alikes (e.g. "ｉｇｎｏｒｅ" → "ignore") and zero-width / extra
    whitespace insertion ("i g n o r e") — fold to the canonical form
    we actually scan for.

    Returns True if injection detected, False otherwise.
    """
    normalised = unicodedata.normalize("NFKC", question)
    normalised = re.sub(r"\s+", " ", normalised)
    lower = normalised.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in lower:
            logger.warning("Potential prompt injection detected: '%s' in query", pattern)
            return True
    return False


_agent = None
_agent_lock = threading.Lock()


def get_doctor_agent():
    """Return the compiled LangGraph agent, building lazily on first call."""
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is None:  # double-check after acquiring lock
            llm = ChatAnthropic(model=MODEL_NAME, max_tokens=4096, streaming=True)
            _agent = create_react_agent(llm, ALL_TOOLS, prompt=SYSTEM_PROMPT)
            logger.info("Doctor Agent built with model=%s, tools=%d", MODEL_NAME, len(ALL_TOOLS))
    return _agent


async def stream_doctor_response(question: str) -> AsyncGenerator[str, None]:
    """Stream SSE events for a Doctor Agent query.

    Yields lines in text/event-stream format:
        data: {"type": "token", "content": "..."}\n\n
        data: {"type": "sources", "sources": [...]}\n\n
        data: [DONE]\n\n

    Logs the full interaction to agent_logs after streaming completes.
    """
    if _check_prompt_injection(question):
        msg = json.dumps({"type": "token", "content": "I'm unable to process that request. Please ask a question about London's health data."})
        yield f"data: {msg}\n\n"
        yield "data: [DONE]\n\n"
        return
    agent = get_doctor_agent()
    start = time.monotonic()

    tokens: list[str] = []
    sources: list[dict] = []
    tools_called: list[str] = []
    tool_inputs: list[dict] = []
    tool_outputs: list[dict] = []

    try:
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=question)]},
            version="v2",
            config={"run_id": str(uuid.uuid4()), "recursion_limit": 20},
        ):
            kind = event.get("event")

            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if not chunk:
                    continue
                content = chunk.content
                # Skip tool-call tokens — only stream the agent's final text response
                if isinstance(content, list):
                    if any(
                        isinstance(block, dict) and block.get("type") == "tool_use"
                        for block in content
                    ):
                        continue
                    text = "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                elif isinstance(content, str):
                    text = content
                else:
                    text = ""
                if text:
                    tokens.append(text)
                    # No html.escape() — React's JSX rendering prevents XSS by default
                    sse = json.dumps({"type": "token", "content": text})
                    yield f"data: {sse}\n\n"

            elif kind == "on_tool_start":
                name = event.get("name", "")
                tool_inputs.append({
                    "tool": name.removesuffix("_tool"),
                    "input": event["data"].get("input", {}),
                })

            elif kind == "on_tool_end":
                name = event.get("name", "")
                clean_name = name.removesuffix("_tool")
                raw_output = event["data"].get("output")

                # on_tool_end returns a ToolMessage; extract its content
                if hasattr(raw_output, "content"):
                    content = raw_output.content
                    # ToolMessage.content is a JSON string from @tool functions
                    try:
                        output = json.loads(content) if isinstance(content, str) else content
                    except (json.JSONDecodeError, TypeError):
                        output = content
                else:
                    output = raw_output

                tools_called.append(clean_name)
                tool_outputs.append({"tool": clean_name, "output": output})

                source_type = "chromadb" if clean_name == "search_scores" else "duckdb"
                sources.append({
                    "type": source_type,
                    "tool": clean_name,
                    "data": output,
                })

    except Exception:
        logger.exception("Doctor Agent stream error for query: %s", question)
        err = json.dumps({"type": "error", "message": "Agent encountered an error"})
        yield f"data: {err}\n\n"
        yield "data: [DONE]\n\n"
        # Log failed interaction so it appears in the audit trail
        try:
            log_agent_interaction(
                query=question,
                tools_called=[],
                tool_inputs=[],
                tool_outputs=[],
                sources_cited=[],
                final_response="ERROR: Agent encountered an error",
                latency_ms=0,
                model_used=MODEL_NAME,
            )
        except Exception:
            logger.exception("Failed to log failed agent interaction")
        return

    # Flush sources and done sentinel
    sources_sse = json.dumps({"type": "sources", "sources": sources})
    yield f"data: {sources_sse}\n\n"
    yield "data: [DONE]\n\n"

    # Log interaction (fire-and-forget)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        log_agent_interaction(
            query=question,
            tools_called=tools_called,
            tool_inputs=tool_inputs,
            tool_outputs=tool_outputs,
            sources_cited=sources,
            final_response="".join(tokens),
            latency_ms=elapsed_ms,
            model_used=MODEL_NAME,
        )
    except Exception:
        logger.exception("Failed to log agent interaction")
