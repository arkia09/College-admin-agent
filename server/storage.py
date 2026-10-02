"""
storage.py
Plain CRUD layer over data/tasks.json. No MCP, no LLM — just functions
you can call directly and unit-test before wiring anything else up.

Task shape:
{
    "id": "a1b2c3d4",
    "title": "OS Assignment 2",
    "subject": "Operating Systems",
    "due_date": "2026-10-02",   # ISO format YYYY-MM-DD
    "priority": "high",         # low | medium | high
    "status": "pending"         # pending | done
}
"""

import json
import os
import tempfile
import threading
import uuid
from datetime import date, datetime
from typing import Optional

# data/tasks.json, relative to this file's location (server/ -> ../data)
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(_THIS_DIR, "..", "data", "tasks.json")

_LOCK = threading.RLock()  # server may handle concurrent requests

VALID_PRIORITIES = {"low", "medium", "high"}
VALID_STATUSES = {"pending", "done"}


class TaskNotFoundError(Exception):
    pass


class InvalidTaskDataError(Exception):
    pass


# ---------- low-level load/save ----------

def _load() -> list[dict]:
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return []
        return json.loads(content)


def _save(tasks: list[dict]) -> None:
    # Atomic write: write to a temp file, then replace. A crash mid-write can
    # no longer leave tasks.json truncated/corrupt.
    directory = os.path.dirname(DATA_PATH)
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2)
        os.replace(tmp_path, DATA_PATH)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _validate_due_date(due_date: str) -> str:
    """Validate and return the canonical YYYY-MM-DD form.
    (Python 3.11+ fromisoformat also accepts '20261011' / '2026-W41-1';
    storing those raw would break string sorting, so we normalise.)"""
    try:
        return date.fromisoformat(due_date.strip()).isoformat()
    except (ValueError, AttributeError):
        raise InvalidTaskDataError(
            f"due_date {due_date!r} is not a valid ISO date (expected YYYY-MM-DD)"
        )


# ---------- public CRUD functions ----------

def add_task(title: str, subject: str, due_date: str, priority: str = "medium") -> dict:
    """Create a new task and persist it. Returns the created task record."""
    if not title or not title.strip():
        raise InvalidTaskDataError("title must not be empty")
    if not subject or not subject.strip():
        raise InvalidTaskDataError("subject must not be empty")

    priority = priority.lower().strip()
    if priority not in VALID_PRIORITIES:
        raise InvalidTaskDataError(
            f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}"
        )

    due_date = _validate_due_date(due_date)

    task = {
        "id": uuid.uuid4().hex[:8],
        "title": title.strip(),
        "subject": subject.strip(),
        "due_date": due_date,
        "priority": priority,
        "status": "pending",
    }

    with _LOCK:
        tasks = _load()
        tasks.append(task)
        _save(tasks)
    return task


def list_tasks(
    subject: Optional[str] = None,
    status: Optional[str] = None,
    due_before: Optional[str] = None,
) -> list[dict]:
    """
    Return tasks, optionally filtered.
    - subject: case-insensitive partial match
    - status: 'pending' or 'done'
    - due_before: ISO date string; only tasks due on or before this date
    Results are sorted by due_date ascending.
    """
    tasks = _load()

    if subject:
        subject_lower = subject.lower()
        tasks = [t for t in tasks if subject_lower in t["subject"].lower()]

    if status:
        if status not in VALID_STATUSES:
            raise InvalidTaskDataError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
            )
        tasks = [t for t in tasks if t["status"] == status]

    if due_before:
        cutoff = date.fromisoformat(_validate_due_date(due_before))
        tasks = [t for t in tasks if date.fromisoformat(t["due_date"]) <= cutoff]

    tasks.sort(key=lambda t: t["due_date"])
    return tasks


def get_task(task_id: str) -> dict:
    """Fetch a single task by id. Raises TaskNotFoundError if missing."""
    tasks = _load()
    for t in tasks:
        if t["id"] == task_id:
            return t
    raise TaskNotFoundError(f"No task with id {task_id!r}")


def mark_done(task_id: str) -> dict:
    """Mark a task as done. Returns the updated task record."""
    with _LOCK:
        tasks = _load()
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = "done"
                _save(tasks)
                return t
    raise TaskNotFoundError(f"No task with id {task_id!r}")


def delete_task(task_id: str) -> None:
    """Remove a task entirely. Raises TaskNotFoundError if missing."""
    with _LOCK:
        tasks = _load()
        remaining = [t for t in tasks if t["id"] != task_id]
        if len(remaining) == len(tasks):
            raise TaskNotFoundError(f"No task with id {task_id!r}")
        _save(remaining)


def days_until_due(task: dict, reference: Optional[date] = None) -> int:
    """Helper the study-plan generator will use later: days between today and due_date."""
    reference = reference or datetime.now().date()
    due = date.fromisoformat(task["due_date"])
    return (due - reference).days
