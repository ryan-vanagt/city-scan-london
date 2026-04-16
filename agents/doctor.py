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

- Lungs (air quality) — OpenAQ PM2.5 and NO2 readings per borough
- Arteries (transit) — TfL tube line status mapped to boroughs
- Brain (sentiment) — BBC and Guardian headline sentiment (Reddit currently inactive)
- Immune system (crime + A&E) — Met Police street crime and NHS A&E pressure
- Skin (green space) — GLA green cover percentage per borough, scored 0–100 relative to London range

Each organ produces a score from 0 to 100 (100 = healthiest). The composite \
score is a weighted average of all available sub-scores.

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
- Lungs: hourly pipeline, but individual sensors may be up to 7 days stale. \
Never say "real-time" without this caveat.
- Arteries, Brain: near real-time, updated each pipeline run.
- Immune: ~2 month institutional lag (Met Police + NHS A&E). Always check \
the timestamp returned by the tool and report the actual data period.
- Skin: GLA Green Cover 2024, yearly static. Measures COVERAGE not ACCESS. \
A borough with low coverage may still have good park access (e.g. Westminster \
has Hyde Park). Always check ward-level detail via run_sql against \
silver_detail before diagnosing green space.
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
""" + (f"""
POLICY CONTEXT (verified London policies — for grounding, not unprompted prescription):
{_POLICY_CONTEXT}
""" if _POLICY_CONTEXT else "")

_INJECTION_PATTERNS = [
    "ignore previous", "ignore all", "system prompt", "you are now",
    "disregard", "forget your", "override instructions", "new instructions",
    "act as", "pretend you are", "jailbreak", "developer mode",
    "DAN", "do anything now", "bypass", "reveal prompt",
]


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
            config={"run_id": str(uuid.uuid4()), "recursion_limit": 50},
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
