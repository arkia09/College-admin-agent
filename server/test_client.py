"""
test_client.py
End-to-end smoke test for the MCP server. NO Gemini key needed.
Start the server in one terminal (python server/server.py), then in another:

    python server/test_client.py

It talks to the server over real Streamable HTTP, exactly like an MCP client
(or Alexa+) would. Uses a temporary task and removes nothing from your data
except the task it creates (it marks it done at the end).
"""

import asyncio
import json
import os
import sys
from datetime import date, timedelta

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
failures = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures += 1


async def call(session, name, args):
    res = await session.call_tool(name, args)
    text = "".join(b.text for b in res.content if hasattr(b, "text"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "error": text}


async def main():
    async with streamable_http_client(URL) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            check("tools/list exposes the 4 tools",
                  tools == {"add_task", "list_tasks", "mark_done", "generate_study_plan"}, str(tools))

            today = date.today()
            due = (today + timedelta(days=3)).isoformat()

            out = await call(s, "add_task", {"title": "SMOKE TEST", "subject": "Testing",
                                             "due_date": due, "priority": "high"})
            check("add_task ok", out.get("ok") is True, str(out))
            tid = out.get("task", {}).get("id")

            out = await call(s, "add_task", {"title": "bad", "subject": "T", "due_date": "not-a-date"})
            check("add_task rejects bad date", out.get("ok") is False)

            out = await call(s, "add_task", {"title": "norm", "subject": "T", "due_date": due.replace("-", "")})
            check("compact date is normalised to YYYY-MM-DD",
                  out.get("task", {}).get("due_date") == due, str(out))
            if out.get("task"):
                await call(s, "mark_done", {"task_id": out["task"]["id"]})

            out = await call(s, "list_tasks", {"subject": "testing", "status": "pending"})
            check("list_tasks finds it", any(t["id"] == tid for t in out.get("tasks", [])), str(out))

            out = await call(s, "generate_study_plan", {
                "start_date": today.isoformat(), "end_date": due, "hours_per_day": 3})
            planned = [b["task_id"] for d in out.get("plan", {}).get("days", []) for b in d["blocks"]]
            check("generate_study_plan schedules it", tid in planned, str(out)[:200])

            out = await call(s, "generate_study_plan", {
                "start_date": due, "end_date": today.isoformat(), "hours_per_day": 3})
            check("plan rejects end < start", out.get("ok") is False)

            out = await call(s, "mark_done", {"task_id": tid})
            check("mark_done ok", out.get("ok") is True, str(out))
            out = await call(s, "mark_done", {"task_id": "nope"})
            check("mark_done unknown id -> error", out.get("ok") is False)

    print("\nALL PASSED" if not failures else f"\n{failures} CHECK(S) FAILED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:  # connection refused etc.
        print(f"Could not reach the MCP server at {URL}: {e!r}\nIs `python server/server.py` running?")
        sys.exit(1)
