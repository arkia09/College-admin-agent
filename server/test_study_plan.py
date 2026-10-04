"""
test_study_plan.py
Tests for the scheduling logic in study_plan.py. No server needed.

    python server/test_study_plan.py
"""

import sys

from study_plan import generate_study_plan

failures = 0


def check(label, cond):
    global failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures += 1


def task(tid, due, priority="medium"):
    return {"id": tid, "title": f"task {tid}", "subject": "S", "due_date": due,
            "priority": priority, "status": "pending"}


def total(plan, tid=None):
    return sum(b["hours"] for d in plan["days"] for b in d["blocks"] if tid in (None, b["task_id"]))


# one medium task = 2.5h budget, plenty of time -> fully scheduled
p = generate_study_plan([task("a", "2026-10-10")], "2026-10-05", "2026-10-10", 3)
check("task gets its full hour budget", abs(total(p, "a") - 2.5) < 1e-6)
check("nothing left unscheduled", p["unscheduled"] == [])
check("one day per date in the range", len(p["days"]) == 6)

# earlier deadline should be worked on first
p = generate_study_plan([task("late", "2026-10-09"), task("soon", "2026-10-06")], "2026-10-05", "2026-10-09", 2)
first_block = p["days"][0]["blocks"][0]
check("nearest deadline is scheduled first", first_block["task_id"] == "soon")

# nothing is scheduled after its own due date
p = generate_study_plan([task("a", "2026-10-06", "high")], "2026-10-05", "2026-10-09", 1)
check("no work after the due date", all(not d["blocks"] for d in p["days"] if d["date"] > "2026-10-06"))
check("too little time shows up as unscheduled", len(p["unscheduled"]) == 1)

# overdue
p = generate_study_plan([task("old", "2026-10-01")], "2026-10-05", "2026-10-07", 3)
check("overdue task is flagged", p["overdue"] == ["old"])
check("overdue task still gets scheduled on day one", p["days"][0]["blocks"][0]["task_id"] == "old")

# a day never goes over hours_per_day
p = generate_study_plan([task(str(i), "2026-10-07", "high") for i in range(4)], "2026-10-05", "2026-10-07", 2.5)
check("daily hours never exceeded", all(sum(b["hours"] for b in d["blocks"]) <= 2.5 + 1e-6 for d in p["days"]))

# bad input
for label, args in [("end before start", ("2026-10-09", "2026-10-05", 2)), ("zero hours", ("2026-10-05", "2026-10-06", 0))]:
    try:
        generate_study_plan([], *args)
        check(f"{label} raises ValueError", False)
    except ValueError:
        check(f"{label} raises ValueError", True)

print("\nALL PASSED" if not failures else f"\n{failures} CHECK(S) FAILED")
sys.exit(1 if failures else 0)
