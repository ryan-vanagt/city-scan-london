"""
Agent and bulletin endpoints.

POST /agent/query        — Doctor agent query; returns SSE stream (text/event-stream)
                           body: {"question": string}
                           events: token stream → final [SOURCES] JSON event

GET  /bulletin/latest    — latest generated bulletin as markdown
POST /bulletin/generate  — trigger on-demand bulletin generation
"""
