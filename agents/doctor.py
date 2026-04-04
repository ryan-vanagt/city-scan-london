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
