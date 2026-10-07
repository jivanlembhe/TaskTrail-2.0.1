# TaskTrail (formerly FlowBoard Pro) — upgrade notes

## v2.4.1 — Report in list view (matches the user's own August report)
Replaced the table layout with a list-view report: cover page with employee details, label-based category headings, bullet lists, nested sub-task bullets, Completed/Pending under unfinished tasks, header/footer like the original. Statements are action-style (no "I"); every statement is editable before export. Fixed: review step was not shown after generation (caught in testing).

## v2.4 — Reports, scale, auto-priority, calendar
Data format unchanged (new optional card field `prioLock`). New module `report.py`; new dependency `python-docx`.
- **Monthly performance report → Word**, AI-written sentences with offline fallback and a review step (see README).
- **Scale:** per-column paging, quick filters, sorting, compact density; list paging. 2,000-task board 13.3 s → 0.7 s.
- **Auto-priority** by due date (escalate-only, manual override locks).
- **Calendar rebuilt:** due-date driven across months, Month/Week, overflow day panel, overdue backlog, fixed cross-month drag/open (previously a task filed under another month could not be seen or dragged).
- Known limit: the AI path is verified against a mock server, not the live API.

## v2.3 — Glass UI
Data file, format and backups are unchanged. New `glass.py` module (PyInstaller picks it up automatically).
- Mica/Acrylic window backdrop on Windows, simulated glass elsewhere; frosted layered-shadow cards; collapsible sidebar; blurred Ctrl K / Quick add; glass right-click menus; System/Light/Dark with live OS following; glow progress with async export + backup; new *Next 7 days* dashboard chart; vector line icons; accessible checkboxes (tick mark, not colour only).
- New default theme mode is **System** for fresh installs; an explicitly saved Dark/Light choice is kept.
- Fixed: `os.getlogin()` crash at import when there is no controlling terminal; re-render no longer flashes stale widgets for a frame; toast timer no longer hides a newer toast early.
- Shortcuts added: `Ctrl B` toggle sidebar.
- **Not verified on real Windows hardware** (developed headless): DWM Mica/Acrylic calls. If the window looks wrong, set *Appearance → Material → Off*.

## Python-only repository
The Electron/HTML edition has been removed; the PySide6 app that used to live in `python/` is now the repository root.
The data file, its format and the backup layout are unchanged, so existing installs keep all their data.
Installer registry keys are unchanged too, so `TaskTrail-Setup-*.exe` upgrades an existing install in place.

## v2.2
### Checklist merged into the board
There is now one set of tasks. On first launch every Checklist group becomes a **label** and every checklist task becomes a board card carrying that label (To Do, or Done if it was ticked). A backup of the previous data file is written first (Backup & Restore → list). The **Task List** page (Alt 3) replaces Task Checklist: the same cards as the board, one line each, grouped by column, due date, label or priority. Ticking a row completes the card exactly like the board checkbox. Restoring an older backup re-runs the merge automatically. Excel export no longer has Checklist sheets.

### Recurring tasks
`repeat` (daily · weekdays · weekly · monthly · yearly) and optional `repeatUntil` on a card. Completing a recurring card — checkbox, Mark complete, dragging it to Done or ticking it in the list — advances its due date to the next occurrence after today and keeps it in its column, logged as "Completed ↻ next due …" with a completion history. When the end date is reached it completes normally. "Skip once" in the detail panel moves it on without a completion. The calendar draws upcoming occurrences as dashed ghost chips (not draggable). Quick-add: `*daily` etc.

### Layout
Board columns stretch to fill the window (176–380 px) and shrink so all columns stay visible when the task pane slides open; the pane animates in and out. Due-date fields are wide enough for the full date.

## v2.1
Data file format is unchanged. Everything below is additive.
- **Quick-add in every column** — `Renew SSL !high #ops @fri`. Enter saves; Shift+Enter opens the full form with the parsed values.
- **Calendar page (Alt+4)** — tasks by due date, drag to reschedule, *Unscheduled* tray, double-click a day to add. Checklist tasks with due dates appear too. Card activity gets "Rescheduled to …" / "Due date removed".
- **Search & commands (Ctrl+K)** — tasks from every month and year, plus commands; no match → Enter creates the task.
- **Needs attention** panel on the dashboard — overdue and due-within-7-days items from the board and the checklist, sorted by urgency, click to open.
- **Keyboard** — `[` `]` change month, `Alt 1–4` pages, `?` shortcut sheet.
- **Quick add** (Ctrl K → "Quick add") — a floating window with a live preview of the parsed priority, labels and due date; Enter saves, Shift+Enter → full form.
- **Detail panel** — checklist items wrap and can be edited (✎ / double-click); labels wrap into rows; due date on its own row; no more horizontal scrolling.
- **Dashboard** — KPI count-up, completion ring, open-tasks-by-priority bar, tasks-per-month bars highlight the shown month and are clickable.
- **Motion** — page cross-fade, toast slide-in, ring/chart sweeps. Switch off under Appearance → "Animations & transitions".
- 11 more colour presets (Ocean, Rose, Sunset, Graphite, Violet, Lavender, Mint, Sky, Slate, Peach).

## v2.0
### Renamed
- App is now **TaskTrail** (Plan · Do · Track). The "Kanban Board" page is now **Task Board**.
- On first launch, the old `%APPDATA%\FlowBoard Pro` data is picked up automatically if the new folder is empty — nothing is lost.

### Data model
- Storage is per **year**: `db.years[2026|2027|…].kanban / .checklist`. Existing data is upgraded automatically on load (it becomes year 2026). Old backups still restore.
- December → January rolls incomplete tasks into the next year. Switch years with ◀ ▶ in the sidebar.

### Task Board
- Drag to **reorder within a column** as well as between columns.
- **Custom columns**: ⋯ on any column header to rename / recolour / move; "+ Column" to add. Built-in columns can't be deleted (the dashboard and rollover depend on them).
- **Labels**: manage via "🏷 Labels"; assign in the task form or the detail panel; filter bar with search, priority and label chips.
- **Card detail panel**: click a card → title, column, priority, due date, labels, description, checklist, comments, and an automatic activity log.

### Appearance (sidebar → Tools)
- Body / heading font, text size, text colour, accent, background, card colour, six presets.

### Backup & Restore (sidebar → Tools)
- Choose any backup folder (e.g. OneDrive — detected automatically with a one-click button), reset to default.
- Backup now, list, restore from the folder, or **Restore from file…**.
- Automatic backups every 30 minutes and on quit, 30 kept.
