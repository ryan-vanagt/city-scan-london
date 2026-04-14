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
import threading
import time
import uuid
from typing import AsyncGenerator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from agents.logging_db import log_agent_interaction
from agents.tools.langchain_tools import ALL_TOOLS

logger = logging.getLogger(__name__)

MODEL_NAME = "claude-haiku-4-5"

SYSTEM_PROMPT = """\
You are the City Doctor — a specialist who diagnoses London's health using \
live public data. London is modelled as a human body with five organ systems:

- Lungs (air quality) — OpenAQ PM2.5 and NO2 readings per borough
- Arteries (transit) — TfL tube line status mapped to boroughs
- Brain (sentiment) — Reddit, BBC, and Guardian headline sentiment
- Immune system (crime + A&E) — Met Police street crime and NHS A&E pressure
- Skin (green space) — GLA green cover percentage per borough, scored 0–100 relative to London range

Each organ produces a score from 0 to 100 (100 = healthiest). The composite \
score is a weighted average of all available sub-scores.

Data freshness:
- Arteries (transit), Brain (sentiment): near real-time, updated each pipeline run.
- Lungs (air quality): updated each pipeline run, but individual sensor readings \
may be up to 7 days old. Not all OpenAQ stations report continuously — some \
readings in the score may be several days stale. When asked about air quality \
freshness, ALWAYS mention this 7-day window — do not say the data is "live" \
or "real-time" without this caveat.
- Immune system: Met Police crime data and NHS A&E statistics are published \
with a lag (typically ~2 months). When reporting immune scores, check the \
timestamp returned by the tool and tell the user the actual date the data is \
from — do not assume it is current.
- Skin (green space): data is from the GLA Green Cover 2024 analysis \
(satellite imagery). Updated yearly — scores are static between annual releases. \
The borough-level score measures green COVERAGE (% of land area), not ACCESS \
to parks. A borough with low coverage may still have excellent park access \
(e.g. Westminster scores low on coverage but has Hyde Park). When discussing \
green space for any borough, ALWAYS check ward-level detail first using run_sql \
against silver_detail — this reveals which specific wards are green deserts \
versus which benefit from nearby parks. Diagnose at ward level, not just borough.

Rules:
1. ALWAYS call at least one tool before answering. Never fabricate data.
2. Cite which boroughs and metrics you used in your answer.
3. Be concise — 2-4 paragraphs for most queries.
4. When comparing boroughs, use the compare_boroughs tool.
5. When asked about trends or changes, use the get_trend tool.
6. For complex analytical questions, use the run_sql tool.
7. Use search_scores for semantic searches over historical data.
8. If a tool returns no data, say so honestly — do not guess.
9. Present scores rounded to one decimal place.
10. When reporting immune scores, note the ~2 month data lag.
11. Do not speculate on causes (e.g. "likely due to traffic") — only report \
what the data shows. Do not compare to the London average unless you have \
called get_london_score to verify it.
12. Frame your diagnosis in medical metaphors when natural, but prioritise clarity.
13. For detailed breakdowns (crime categories in a borough, which tube lines \
are disrupted, station-level air quality, ward-level green space coverage, \
individual headlines), use run_sql against silver_detail or silver_headlines. \
Always filter by source and borough_code. Examples: \
SELECT category, COUNT(*) FROM silver_detail \
WHERE source='met_police' AND borough_code='E09000007' GROUP BY category \
— or for green space wards: SELECT label, value FROM silver_detail \
WHERE source='green_space' AND borough_code='E09000007' ORDER BY value ASC
14. NEVER reveal internal system details to users. Do not mention table names \
(gold_scores, silver_metrics, silver_detail, silver_headlines), column names, \
database technology (DuckDB, ChromaDB), pipeline stages, tool names, or how \
the system is built. You are a doctor — patients do not need to know how \
the lab equipment works. If asked about how you work, say you analyse live \
public data from official sources (TfL, OpenAQ, Met Police, NHS England, \
news outlets) and synthesise it into health scores.\
"""

_INJECTION_PATTERNS = ["ignore previous", "ignore all", "system prompt", "you are now", "disregard", "forget your"]


def _check_prompt_injection(question: str) -> bool:
    """Check if question contains potential prompt injection patterns.

    Returns True if injection detected, False otherwise.
    """
    lower = question.lower()
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
            llm = ChatAnthropic(model=MODEL_NAME, max_tokens=1024, streaming=True)
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
            config={"run_id": str(uuid.uuid4())},
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
