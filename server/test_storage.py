"""
test_storage.py
Quick tests for storage.py.
    python server/test_storage.py
"""

import os
import sys
import tempfile

# TASKS_FILE has to be set BEFORE importing storage, because it reads it at import time
_tmp = tempfile.mkdtemp()
os.environ["TASKS_FILE"] = os.path.join(_tmp, "tasks.json")

import storage  # noqa: E402

failures = 0


def check(label, cond):
    global failures
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        failures += 1


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception:
        return False
    return False


check("empty store lists nothing", storage.list_tasks() == [])

t1 = storage.add_task("  OS lab  ", "Operating Systems", "2026-10-10", "HIGH")
check("add_task trims title and lowercases priority", t1["title"] == "OS lab" and t1["priority"] == "high")
t2 = storage.add_task("DBMS quiz", "DBMS", "20261005")
check("compact date is normalised", t2["due_date"] == "2026-10-05")
check("list is sorted by due date", [t["id"] for t in storage.list_tasks()] == [t2["id"], t1["id"]])

check("empty title rejected", raises(storage.InvalidTaskDataError, storage.add_task, " ", "X", "2026-10-10"))
check("bad date rejected", raises(storage.InvalidTaskDataError, storage.add_task, "a", "X", "tomorrow"))
check("bad priority rejected", raises(storage.InvalidTaskDataError, storage.add_task, "a", "X", "2026-10-10", "urgent"))

check("subject filter is case-insensitive", len(storage.list_tasks(subject="operating")) == 1)
check("due_before filter", [t["id"] for t in storage.list_tasks(due_before="2026-10-07")] == [t2["id"]])

storage.mark_done(t2["id"])
check("mark_done changes status", storage.get_task(t2["id"])["status"] == "done")
check("status filter", len(storage.list_tasks(status="pending")) == 1)
check("mark_done unknown id raises", raises(storage.TaskNotFoundError, storage.mark_done, "nope"))

storage.delete_task(t1["id"])
check("delete_task removes it", len(storage.list_tasks()) == 1)
check("delete_task unknown id raises", raises(storage.TaskNotFoundError, storage.delete_task, "nope"))

print("\nALL PASSED" if not failures else f"\n{failures} CHECK(S) FAILED")
sys.exit(1 if failures else 0)
