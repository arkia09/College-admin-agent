"""
study_plan.py
Pure scheduling logic: turns a list of pending tasks into a day-wise study
plan. No MCP, no LLM -- plain data in, plain data out, so it can be tested alone.

Algorithm:
1. Take pending tasks due on or before the plan's end_date.
2. Give each task an hour budget by priority (high=4h, medium=2.5h, low=1.5h).
3. For each day, rank the tasks still needing work: soonest deadline first,
   and for equal deadlines higher priority first. Overdue tasks (due before
   the plan starts) are treated as due on day one, so they are scheduled
   first instead of silently dropped.
4. Hand out that day's hours in chunks capped at MAX_CHUNK_HOURS per task, so
   one big task can't swallow the whole day.
"""

from datetime import date, timedelta

MAX_CHUNK_HOURS = 2.0
HOUR_BUDGET = {"high": 4.0, "medium": 2.5, "low": 1.5}
PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
EPS = 1e-9  # guards against float drift (e.g. 0.1 + 0.2) leaving phantom blocks


def generate_study_plan(
    tasks: list[dict],
    start_date: str,
    end_date: str,
    hours_per_day: float,
) -> dict:
    """
    Returns:
    {
        "start_date", "end_date", "hours_per_day",
        "days": [{"date": ..., "blocks": [{"task_id","title","subject","hours"}]}],
        "overdue": [task_id, ...],       # due before start_date (still scheduled)
        "unscheduled": [{"task_id","title","hours_missing"}]  # didn't fit
    }
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    if hours_per_day <= 0:
        raise ValueError("hours_per_day must be positive")

    relevant = [t for t in tasks if date.fromisoformat(t["due_date"]) <= end]
    by_id = {t["id"]: t for t in relevant}

    # Effective deadline: overdue work is treated as due on day one.
    deadline = {t["id"]: max(date.fromisoformat(t["due_date"]), start) for t in relevant}
    overdue = [t["id"] for t in relevant if date.fromisoformat(t["due_date"]) < start]
    remaining = {t["id"]: HOUR_BUDGET.get(t["priority"], 2.0) for t in relevant}

    days_out = []
    day = start
    while day <= end:
        capacity = hours_per_day
        blocks = []

        candidates = [
            t for t in relevant
            if remaining[t["id"]] > EPS and deadline[t["id"]] >= day
        ]
        candidates.sort(key=lambda t: (
            deadline[t["id"]],
            PRIORITY_RANK.get(t["priority"], 1),
        ))

        for t in candidates:
            if capacity <= EPS:
                break
            chunk = min(MAX_CHUNK_HOURS, remaining[t["id"]], capacity)
            blocks.append({
                "task_id": t["id"],
                "title": t["title"],
                "subject": t["subject"],
                "hours": round(chunk, 2),
            })
            remaining[t["id"]] -= chunk
            capacity -= chunk

        days_out.append({"date": day.isoformat(), "blocks": blocks})
        day += timedelta(days=1)

    unscheduled = [
        {"task_id": tid, "title": by_id[tid]["title"], "hours_missing": round(hrs, 2)}
        for tid, hrs in remaining.items() if hrs > EPS
    ]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "hours_per_day": hours_per_day,
        "days": days_out,
        "overdue": overdue,
        "unscheduled": unscheduled,
    }
