# TaskTrail

Task planner, to-do list and status tracker for Windows (also runs on macOS/Linux) — dashboard with a *Needs attention* panel, drag-and-drop task board with custom columns and labels, a list view of the same tasks, recurring tasks, calendar with drag-to-reschedule, Ctrl+K search across every month, automatic monthly rollover, Backup & Restore, Excel export and a system-tray mode. Python app built on PySide6 (`tasktrail.py` + the `glass.py` design layer).

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

## Performance report (Word, list view, AI-assisted)  — sidebar → *Performance Report* or Ctrl K → "performance report"
Follows the structure of a hand-written monthly report: a **cover page** (title, month, then *Prepared By · Employee Code · Appraiser · Program · Joining Date*), a **"Performance Report"** page heading, **"Internal"** (configurable) bottom-left and page numbers bottom-right starting after the cover.
- **Category headings = your task labels** (e.g. *Admission Data:*), each followed by a bullet list of past-tense action statements ("Prepared and shared PPF performance analysis data…") with key phrases in bold.
- **Sub-tasks are nested bullets** (• → o → ▪, real Word list levels) under the task they belong to.
- **Work in Progress and Carried Forward** lists unfinished tasks with **Completed:** (already-finished sub-tasks) and **Pending:** items — rolled-over tasks are found automatically.
- Overview, Challenges and Plan for Next Month sections (from the month's numbers).

Flow: pick month → fill cover details (remembered) → *Generate preview* → **edit any line** (overview, challenges, plan, and one statement per task) → *Export to Word…*.

**AI:** every number is computed locally; Claude (Anthropic API) only phrases the statements — verb-first, no "I" — using nothing but the supplied facts. Add a short note in a task's description (purpose/outcome) and the AI uses it. Enter an API key in the dialog or set `ANTHROPIC_API_KEY`. Only that month's task titles, notes, sub-tasks, dates and counts are sent; cover details stay on your PC. No key / offline → an offline template writes the text (titles that already start with a verb, like "Prepared…", are kept as written). Key is stored in `settings.json` in plain text.

## Working with lots of tasks
- Board columns render a page at a time (*Show 30 more*, Done shows 10) — 2,000 tasks open in well under a second instead of ~13 s.
- **Quick filters** (Overdue · Due ≤ 7 days · High priority), **Sort** (manual · due date · priority · newest) and a **Compact** card density; header counts show *matching/total*.
- The Task List pages each group (25 rows, *Show more*).

## Auto-priority by due date
Overdue, due today or tomorrow → **High**; due within 7 days → at least **Medium**. It only ever *raises* priority, runs on start-up, after every change and at midnight, and logs each change in the task's activity. Setting a priority yourself locks that task (right-click → Priority → *Auto* unlocks). Switch off in *Appearance → Tasks*.

## Calendar
Driven by **due date across all months** (a task filed in another month still shows on its day and can be dragged), **Month / Week** views, *+N more* overflow with a day panel, red ● for high priority, *Hide completed*, an **Overdue before this view** backlog you can drag onto a day, weekends dimmed.

## Glass UI (v2.3)
- **Window:** Windows 11 Mica / Acrylic / Mica Alt (Windows 10 1803+: Acrylic) behind a translucent tint; macOS/Linux get a simulated glass backdrop. *Appearance → Window effect* switches material, tint, or turns it off; env `TASKTRAIL_GLASS=off` disables native blur entirely.
- **Depth:** frosted cards/panels with layered soft shadows, lit accent edges, hover lift + glow. 10px controls, 12px panels, 8px menus.
- **Sidebar:** collapsible (Ctrl B, auto-folds below 1100px), spring animation, painted line icons.
- **Overlays:** Ctrl K palette and Quick add blur the app beneath; right-click a task for a glass menu (Open, Edit, Complete, Move to, Priority, Delete).
- **Theme:** System / Light / Dark. *System* follows the OS live (cross-fades). Secondary text colours are auto-adjusted to stay ≥ 4.5:1 on the card surface, for every preset.
- **Async:** Excel export and backup run on worker threads with a neon progress toast and a thin activity line.

## Files
- `report.py` — monthly report engine (facts, AI/template writer, Word list-view builder)
- `cover_art.py` — embedded cover-page artwork
- `glass.py` — design tokens, backdrops, glass widgets, blur overlays, async jobs
- `tasktrail.py` — the app
- `test_tasktrail.py` — quick-add parser + recurrence checks
- `test_report.py` — report, AI client (mock server), auto-priority, calendar and scale checks
- `test_glass.py` — headless UI/contrast/async checks (`QT_QPA_PLATFORM=offscreen python test_glass.py`)
- `requirements.txt` — PySide6, openpyxl, python-docx
- `build_win.bat`, `installer.nsi`, `icon.ico`, `icon.png` — Windows packaging

See `UPGRADE_NOTES.md` for what changed in each release.
