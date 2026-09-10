"""Smallest check that fails if the quick-add parser breaks:  python test_tasktrail.py"""
import datetime as dt, types
import tasktrail as T

s = types.SimpleNamespace(year=2026, month=8, labels=[])          # September 2026
today = dt.date.today()
p = T.parse_quick(s, "Renew SSL !high #ops @fri")
assert p["title"] == "Renew SSL" and p["priority"] == "high" and s.labels[0]["name"] == "ops" and p["labels"] == [s.labels[0]["id"]]
assert dt.date.fromisoformat(p["dueDate"]).weekday() == 4 and 0 <= (dt.date.fromisoformat(p["dueDate"]) - today).days < 7
assert T.parse_quick(s, "x @tomorrow")["dueDate"] == (today + dt.timedelta(1)).isoformat()
assert T.parse_quick(s, "x @+3")["dueDate"] == (today + dt.timedelta(3)).isoformat()
assert T.parse_quick(s, "x @15")["dueDate"] == "2026-09-15"
assert T.parse_quick(s, "x @2026-10-01")["dueDate"] == "2026-10-01"
assert T.parse_quick(s, "x @31 @2026-02-30 !soon #ops")["title"] == "x @31 @2026-02-30 !soon" and len(s.labels) == 1   # invalid tokens kept, label reused
assert T.parse_quick(s, "  !low  ")["title"] == ""
print("parse_quick OK")

# recurrence rules
D = dt.date
assert T.repeat_step(D(2026, 9, 11), "weekdays") == D(2026, 9, 14)          # Fri → Mon
assert T.repeat_step(D(2026, 1, 31), "monthly") == D(2026, 2, 28)           # clamps to month end
assert T.repeat_step(D(2024, 2, 29), "yearly") == D(2025, 2, 28)
assert T.next_due("2026-09-01", "daily", after=D(2026, 9, 10)) == D(2026, 9, 11)
assert T.occurrences({"repeat": "weekly", "dueDate": "2026-09-10", "repeatUntil": "2026-09-30"}, D(2026, 8, 31), D(2026, 10, 4)) == [D(2026, 9, 17), D(2026, 9, 24)]
assert T.parse_quick(s, "Standup *weekdays")["repeat"] == "weekdays"
print("recurrence OK")
