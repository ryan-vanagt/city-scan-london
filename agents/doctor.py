"""
Doctor Agent — LangGraph ReAct agent.

Answers natural language queries about London's health using ChromaDB RAG
and structured DuckDB tool calls. Streams responses token-by-token via SSE.

Output schema per query:
  answer  — streamed natural language response
  sources — list of grounded data points used (DuckDB rows + Guardian URLs)

Every interaction is logged to the agent_logs DuckDB table.
Only Gold-layer aggregated data reaches the LLM — no raw text, no PII.
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
live public data. London is modelled as a human body with four organ systems:

- Lungs (air quality) — OpenAQ PM2.5 and NO2 readings per borough
- Arteries (transit) — TfL tube line status mapped to boroughs
- Brain (sentiment) — Reddit, BBC, and Guardian headline sentiment
- Immune system (crime + A&E) — Met Police street crime and NHS A&E pressure

Each organ produces a score from 0 to 100 (100 = healthiest). The composite \
score is a weighted average of all available sub-scores.

Data freshness:
- Lungs (air quality), Arteries (transit), Brain (sentiment): near real-time, \
updated each pipeline run.
- Immune system: Met Police crime data and NHS A&E statistics are published \
with a lag (typically ~2 months). When reporting immune scores, check the \
timestamp returned by the tool and tell the user the actual date the data is \
from — do not assume it is current.

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
12. Frame your diagnosis in medical metaphors when natural, but prioritise clarity.\
"""

_INJECTION_PATTERNS = ["ignore previous", "ignore all", "system prompt", "you are now", "disregard", "forget your"]


def _check_prompt_injection(question: str) -> None:
    """Log a warning if the question contains potential prompt injection patterns."""
    q_lower = question.lower()
    for pattern in _INJECTION_PATTERNS:
        if pattern in q_lower:
            logger.warning("Potential prompt injection detected: %r", question[:100])
            return


_agent = None
_agent_lock = threading.Lock()


def get_doctor_agent():
    """Return the compiled LangGraph agent, building lazily on first call."""
    global _agent
    if _agent is not None:
        return _agent
    with _agent_lock:
        if _agent is None:  # double-check after acquiring lock
            llm = ChatAnthropic(model=MODEL_NAME, streaming=True)
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
    _check_prompt_injection(question)
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
