# TaskTrail

Task planner, to-do list and status tracker for Windows (also runs on macOS/Linux) — dashboard with a *Needs attention* panel, drag-and-drop task board with custom columns and labels, a list view of the same tasks, recurring tasks, calendar with drag-to-reschedule, Ctrl+K search across every month, automatic monthly rollover, Backup & Restore, Excel export and a system-tray mode. Single-file Python app built on PySide6.

Data lives in `%APPDATA%\TaskTrail\flowboard_data.json` (backups in `%APPDATA%\TaskTrail\backups`, or any folder you choose, e.g. OneDrive). Old FlowBoard / TaskTrail v1 files are upgraded automatically on first load. Files from v2.1 and earlier have their Checklist groups merged into the board on first launch (each group becomes a label; a backup of the old file is written first).

## Run from source
```
pip install -r requirements.txt
python tasktrail.py
```
Python 3.9+. Tested with PySide6 6.11.

## Build a Windows .exe
Run `build_win.bat` → `dist\TaskTrail.exe` (single file, no console window, unsigned — SmartScreen shows the "unknown publisher" prompt once; choose *More info → Run anyway*).

Optional installer (per-user, no admin rights): install [NSIS](https://nsis.sourceforge.io/) and run `makensis installer.nsi` → `TaskTrail-Setup-<version>.exe`.

## GitHub Actions
`.github/workflows/build.yml` builds the portable exe and the installer on every push to `main` and on manual dispatch (download from the **Actions** tab → artifacts). Pushing a tag `v*` also attaches both files to a GitHub Release.

## Features
- Dashboard: KPIs that count up, completion ring, **Needs attention** (overdue + due within 7 days, board and checklist, click to open), open-tasks-by-priority bar, recent activity, tasks-per-month chart (click a bar to open that month)
- Task Board: columns stretch to the window and shrink to fit when the task pane opens; drag to reorder within a column or move between columns; custom columns (⋯ to rename/recolour/move, "+ Column" to add); labels with a filter bar (search, priority, labels)
- "+ Add Task", Ctrl N and the button under each column open the full task form. **Quick add** (Ctrl K → "Quick add") shows the parsed priority / labels / due date live as you type; Enter saves into the chosen column, Shift+Enter opens the full form pre-filled. The title understands `!high` / `!low`, `#label` (created if it doesn't exist) , `@today`, `@tomorrow`, `@fri`, `@15` (day of the shown month), `@+3`, `@2026-10-01`, and `*daily` / `*weekdays` / `*weekly` / `*monthly` / `*yearly`
- **Calendar** page: month grid of this month's tasks by due date, plus ghost chips for upcoming repeats. Drag a task to another day to reschedule (logged in its activity); an *Unscheduled* tray lists open tasks with no date — drag them onto a day, or drop a dated task back into the tray to clear its date. Double-click a day (or its `+`) to add a task due that day. Overdue count shows on the Calendar nav item
- **Search & commands (Ctrl+K)**: finds tasks in every month and year (title, description, sub-tasks), shows where they live and opens them; also runs commands (new task, go to page, jump to today, switch month, theme, export, rollover, labels, backup…). If nothing matches, Enter creates a task with that title (quick-add syntax works there too)
- Card detail panel: column, priority, due date, labels, description, checklist (✎ or double-click an item to edit it), comments, activity log
- **Task List** page: the same tasks as the board, one line each, grouped by column / due date (Overdue · Today · Tomorrow · This week · …) / label / priority; tick to complete, click to open, search, hide completed
- **Recurring tasks**: repeat every day / weekday / week / month / year, optional end date (form, detail panel, or `*daily` in quick-add). Completing a recurring task advances its due date and keeps it in its column (logged as "Completed ↻ next due …"); "Skip once" moves it on without completing. The calendar shows future occurrences as ghost chips
- Month grid + year switcher (◀ ▶); auto-rollover of unfinished tasks at month end, December → January of the next year; manual rollover panel with history
- Backup & Restore: choose any folder (one-click OneDrive), backup now, restore from list or from any file; automatic backup every 30 min and on quit; 30 kept
- Excel export (openpyxl): board sheets, checklist sheets, month-wise summary
- Appearance: font family & size, text/accent/background/card colours, dark/light, 17 presets, animations on/off
- System tray: closing the window quits TaskTrail. To keep it running in the background instead, right-click the tray icon and tick *Keep running in tray when window is closed* (then closing twice within 3 s still quits). *Minimize to tray* is always available from the tray menu. Launching TaskTrail while it is already running just brings the existing window to the front

## Keyboard
`Ctrl K` search & commands · `Ctrl N` new task · `[` `]` previous / next month · `Alt 1–4` Dashboard · Board · List · Calendar · `?` all shortcuts · `Ctrl Shift B` backup now

## Files
- `tasktrail.py` — the whole app
- `test_tasktrail.py` — quick-add parser check (`python test_tasktrail.py`)
- `requirements.txt` — PySide6, openpyxl
- `build_win.bat`, `installer.nsi`, `icon.ico`, `icon.png` — Windows packaging

See `UPGRADE_NOTES.md` for what changed in each release.
