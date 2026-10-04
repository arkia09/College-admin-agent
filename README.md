# College Admin Agent

An MCP (Model Context Protocol) server that keeps track of a student's assignments
and makes a day-wise study plan, plus a Gemini-powered agent which uses it.
Made for the Amazon Developer Hackathon (Alexa+ track).

Alexa+ track: I am going with the **simulated Alexa+ experience** option. The web chat
(`server/web_app.py`) is the simulation, and the MCP server behind it is the real engine.

- MCP server: official `mcp` Python SDK, **Streamable HTTP** transport
- Tools: `add_task`, `list_tasks`, `mark_done`, `generate_study_plan`
- `generate_study_plan` is an **MCP App**, so hosts can show an interactive plan
- Tasks are saved in `data/tasks.json`, so state stays between sessions


## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp data/tasks.sample.json data/tasks.json     # starting tasks, edit as you like
```

## Run

1. Start the server (terminal 1). The MCP endpoint is **`http://127.0.0.1:8000/mcp`**.
   There is no web page at `/`, so a 404 in the browser is normal.
   ```bash
   python server/server.py
   ```
2. Check that it works (terminal 2, no API key needed). Please start the server with a
   separate data file when running this, because the test adds a few tasks:
   ```bash
   TASKS_FILE=/tmp/test_tasks.json python server/server.py     # terminal 1
   python server/test_client.py                                # terminal 2
   ```
3. Talk to it with the Gemini CLI agent (terminal 2):
   ```bash
   export GEMINI_API_KEY="..."        # https://aistudio.google.com/apikey
   export GEMINI_MODEL="..."          # optional, if the default model gives 404
   python server/agent.py
   ```
   Try: *"I have an OS assignment due next Friday and a DBMS quiz in 3 days.
   Plan my next week at 3 hours a day."*

## Web chat (the simulated Alexa+ experience)

`server/web_app.py` is a browser chat for the Gemini agent. It is also an MCP Apps host,
so the interactive study plan shows up inline in the conversation.
```bash
python server/server.py                       # terminal 1
export GEMINI_API_KEY=...                     # terminal 2
python server/web_app.py                      # open http://127.0.0.1:8081
```

## MCP App (interactive study plan)

`generate_study_plan` declares `_meta.ui.resourceUri = ui://college-admin/study-plan.html`.
Hosts that support MCP Apps show `server/ui/plan_view.html` in a sandboxed iframe: a
day-by-day plan with an hours/day slider and "Done" buttons per task, which call the
server tools back through the host. Clients without Apps support (like `agent.py`)
just get the JSON.

To see it without any chat client, use the bundled dev host:
```bash
python server/server.py      # terminal 1
python server/dev_host.py    # terminal 2 -> open http://127.0.0.1:8080
```
Add a couple of tasks and click **Generate plan**.

### The two apps are connected
- In the web chat, **Generate your own study plan** (top right) opens the standalone MCP App.
- In the MCP App, **Ask agent to build your study plan** opens the web chat with a ready
  prompt (dates and hours/day taken from the plan you are looking at). You just press Send.
  The button is hidden inside the web chat itself, since you are already there.

If you run things on different ports, set `AGENT_URL` (for `server.py`) and
`PLAN_APP_URL` (for `web_app.py`).

## Inspect the server interactively

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP   URL: http://127.0.0.1:8000/mcp
```

## Tests
```bash
python server/test_storage.py      # storage layer, uses a temp file
python server/test_study_plan.py   # scheduling logic
python server/test_client.py       # full MCP round trip over HTTP (see step 2 above)
```

## Known limitations (being honest)
- Single user only. All tasks are in one JSON file and the web chat keeps one shared
  conversation in memory.
- Every tool call from the web chat / dev host opens a new MCP session. Works fine for a
  demo, but it is wasteful.
- Study hours per task are a fixed guess by priority (4h / 2.5h / 1.5h), the student
  cannot give own estimates yet.
- The agent loop is written separately in `agent.py` and `web_app.py` (a bit of repeated code).
- No authentication on the MCP endpoint. It is meant to run on localhost.

## License
MIT -- see `LICENSE`.
