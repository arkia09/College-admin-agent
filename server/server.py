"""
server.py
The MCP server. It takes storage.py + study_plan.py and exposes them as MCP
tools over Streamable HTTP.

Run:   python server/server.py
MCP endpoint (this is NOT a website, so browser will show 404/400 here, that is normal):
       http://127.0.0.1:8000/mcp
Test:  python server/test_client.py     (no API key needed)
"""

import os
from typing import Annotated, Literal, Optional

from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from pydantic import Field

import storage
from study_plan import generate_study_plan as _generate_study_plan

# --- MCP Apps: interactive study-plan view -------------------------------
# generate_study_plan is linked to a ui:// resource. Hosts which support MCP Apps
# will show ui/plan_view.html inside a sandboxed iframe. Other clients (like our
# CLI agent) just ignore the UI and get the normal JSON text, so nothing breaks.
apps = Apps()
PLAN_UI_URI = "ui://college-admin/study-plan.html"
_UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "plan_view.html")

# Where the web chat (web_app.py) is running. The "Ask agent to build your study
# plan" button in the view opens this. Change it with AGENT_URL if you use another port.
AGENT_URL = os.environ.get("AGENT_URL", "http://127.0.0.1:8081").rstrip("/")

with open(_UI_PATH, "r", encoding="utf-8") as _f:
    # the html is a static file, so we just replace one placeholder with the real url
    PLAN_UI_HTML = _f.read().replace("__AGENT_URL__", AGENT_URL)


IsoDate = Annotated[str, Field(description="ISO date, YYYY-MM-DD, e.g. 2026-10-02")]


@apps.tool(
    resource_uri=PLAN_UI_URI,
    description=(
        "Generate a day-wise study plan for pending tasks over a date range. "
        "Only pending tasks due on or before end_date are included. "
        "In MCP Apps hosts this renders an interactive plan the student can adjust."
    )
)
def generate_study_plan(
    start_date: IsoDate,
    end_date: IsoDate,
    hours_per_day: Annotated[
        float, Field(gt=0, le=24, description="Hours the student can study per day")
    ],
) -> dict:
    try:
        pending = storage.list_tasks(status="pending")
        plan = _generate_study_plan(pending, start_date, end_date, hours_per_day)
        return {"ok": True, "plan": plan}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


apps.add_html_resource(
    PLAN_UI_URI,
    PLAN_UI_HTML,
    name="study_plan_view",
    title="Study Plan",
    description="Interactive day-by-day study plan",
)

mcp = MCPServer(
    name="CollegeAdminAgent",
    title="College Admin Agent",
    instructions=(
        "Tools for managing a student's assignments/tasks and generating "
        "day-wise study plans. Dates are always ISO format YYYY-MM-DD. "
        "Priority is one of low/medium/high."
    ),
    extensions=[apps],
)


@mcp.tool(description="Add a new assignment/task to track.")
def add_task(
    title: Annotated[str, Field(description="Short name of the assignment")],
    subject: Annotated[str, Field(description="Course/subject it belongs to")],
    due_date: IsoDate,
    priority: Annotated[
        Literal["low", "medium", "high"], Field(description="Task priority")
    ] = "medium",
) -> dict:
    try:
        return {"ok": True, "task": storage.add_task(title, subject, due_date, priority)}
    except storage.InvalidTaskDataError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="List tasks (sorted by due date), optionally filtered.")
def list_tasks(
    subject: Annotated[
        Optional[str], Field(description="Case-insensitive partial match on subject")
    ] = None,
    status: Annotated[
        Optional[Literal["pending", "done"]], Field(description="Filter by status")
    ] = None,
    due_before: Annotated[
        Optional[str],
        Field(description="ISO date YYYY-MM-DD; only tasks due on or before it"),
    ] = None,
) -> dict:
    try:
        tasks = storage.list_tasks(subject=subject, status=status, due_before=due_before)
        return {"ok": True, "count": len(tasks), "tasks": tasks}
    except storage.InvalidTaskDataError as e:
        return {"ok": False, "error": str(e)}


@mcp.tool(description="Mark a task as done by its id.")
def mark_done(
    task_id: Annotated[str, Field(description="Id returned by add_task or list_tasks")],
) -> dict:
    try:
        return {"ok": True, "task": storage.mark_done(task_id)}
    except storage.TaskNotFoundError as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
