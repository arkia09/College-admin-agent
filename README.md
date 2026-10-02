# College-admin-agent

# College Admin Agent

An MCP (Model Context Protocol) server that manages a student's assignments and
generates day-wise study plans, plus a Gemini-powered CLI agent that uses it.
Built for the Amazon Developer Hackathon (Alexa+ track).

- MCP server: official `mcp` Python SDK (v2), **Streamable HTTP** transport
- Tools: `add_task`, `list_tasks`, `mark_done`, `generate_study_plan`
- State persists across sessions in `data/tasks.json`

```
You (CLI) -> agent.py (Gemini + MCP client) -> server.py (MCP server, HTTP) -> storage.py / study_plan.py -> data/tasks.json
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run

1. Start the server (terminal 1). It serves **`http://127.0.0.1:8000/mcp`** --
   there is no web page at `/`, so a browser/`GET /` returning 404 is normal.
   ```bash
   python server/server.py
   ```
2. Verify it works (terminal 2, no API key needed):
   ```bash
   python server/test_client.py
   ```
3. Talk to it with the Gemini agent (terminal 2):
   ```bash
   export GEMINI_API_KEY="..."        # https://aistudio.google.com/apikey
   export GEMINI_MODEL="gemini-2.5-flash"   # optional; change if retired
   python server/agent.py
   ```
   Try: *"I have an OS assignment due next Friday and a DBMS quiz in 3 days.
   Plan my next week at 3 hours a day."*

## Inspect the server interactively

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP   URL: http://127.0.0.1:8000/mcp
```

## Tests
- `python server/test_storage.py` -- storage layer (if present)
- `python server/test_client.py` -- full MCP round trip over HTTP

## License
MIT -- see `LICENSE`.
