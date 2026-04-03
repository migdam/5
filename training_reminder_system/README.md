# Training Reminder System

A local Python application that automates **training reminder preparation** for IT Project Managers assigned to projects. It does **not** send emails automatically. Instead, it generates email-ready outputs — including color-coded Excel files with exact email addresses, subjects, and bodies — that can be manually sent or shared with someone else to send.

## Purpose

The system:
1. Reads two Excel files: **ePPM** (project assignments) and **Fuse** (training status)
2. Matches people across both files using a 4-pass engine (aliases → email → exact name → normalized name)
3. Identifies Project Managers who are assigned to active projects but haven't completed required training
4. Generates progressive reminder messages (friendly → encouraging → persuasive → rotating follow-ups)
5. Tracks all communication history in SQLite across cycles
6. Stops generating reminders once training is completed and sends congratulations
7. Detects missing IT PM assignments and escalates to Project Owners
8. Archives processed files and generates color-coded Excel reports

## Quick Start

```bash
# Option A: Use the run script (recommended — handles venv automatically)
./run.sh setup        # Create venv and install dependencies
./run.sh simulate     # Generate test data and run full simulation
./run.sh ui           # Launch the Streamlit web UI
./run.sh cli          # Run a single processing cycle
./run.sh test         # Run the test suite (139 tests)

# Option B: Manual setup
pip install -r requirements.txt
python generate_test_data.py    # Generate synthetic test data
python run_simulation.py        # Run multi-cycle simulation
python main.py                  # Run a single cycle
streamlit run streamlit_app.py  # Launch the web UI
```

## Input Files

Place two Excel files in `data/input/`:

### ePPM Export (project assignments)
Expected columns (configurable in `config.yaml`):
- Project number, Project Name, Active Stage, Project Status
- Project Owner, Project Owner Email
- Project Manager, Project Manager Email
- IT Project Manager, IT Project Manager Email
- IT Portfolio Manager, IT Portfolio Manager Email
- G0/G3/G5/G6 Compliance and Action columns

### Fuse Export (training status)
Expected columns (configurable in `config.yaml`):
- Full Name, Email
- Content Title, Course Status, Completion Date, Score

### Optional Files
- **excluded_projects.xlsx** — Ghost/cancelled projects to exclude
- **identity_aliases.xlsx** — Manual name/email overrides (maiden names, domain changes)
- **role_changes.xlsx** — IT PMs who changed roles

## How Matching Works

People are matched across the two files in four passes:

1. **Alias resolution** — Identity aliases (maiden names, email domain changes) are resolved first
2. **Email match** — Normalized email comparison (highest reliability)
3. **Exact name match** — Full name string comparison
4. **Normalized name match** — Lowercase, stripped, whitespace-collapsed comparison

Each pass only attempts to match records that weren't matched in previous passes.

## How Reminder Stages Work

The system tracks which stage of reminder has been sent to each person:

| Stage | Tone | Template |
|-------|------|----------|
| 1 | Friendly awareness | `templates/reminder_stage_1.txt` |
| 2 | Benefits-oriented encouragement | `templates/reminder_stage_2.txt` |
| 3 | Persuasive, action-oriented | `templates/reminder_stage_3.txt` |
| 4+ | Bi-weekly follow-ups with rotating angles | `templates/followup_*.txt` |
| 99 | Congratulations (newly certified) | `templates/congratulations.txt` |

Special communication types:
- **Stage 0**: Missing IT PM reminder to the Project Manager
- **Stage -1**: Escalation to the Project Owner
- **Stage -2**: Role-changed IT PM alert

Reminders include personalized compliance context showing the PM exactly why training matters for their specific projects (G0/G3/G5/G6 gate issues).

## Output Structure

Each run creates a timestamped folder in `data/output/`:

```
data/output/2026-04-01_1530_cycle5/
├── summary_report.md                              # Metrics
├── reminders.csv                                  # All reminders (for mail merge)
├── cycle_dashboard_2026-04-01_1530_cycle5.xlsx    # Color-coded cycle overview
├── tracker_2026-04-01_1530_cycle5.xlsx            # Cross-cycle PM progression
├── send_schedule_2026-04-01_1530_cycle5.xlsx      # Handoff-ready email list
├── comms_plan.md                                  # Weekly send schedule
├── per_recipient/                                 # One .txt file per PM
├── stage_1/ stage_2/ stage_3/                     # Grouped by stage
├── missing_itpm/                                  # IT PM reminders + CSV
├── escalations_to_owner/                          # Owner escalations + CSV
├── role_changed_itpm/                             # Role change alerts + CSV
├── nice_to_have/                                  # Optional Fundamentals suggestions
├── congratulations/                               # Certification congratulations
├── group_emails/                                  # Consolidated group sends
├── send_tuesday/                                  # Day-specific folders
├── send_wednesday/
├── send_thursday/
└── send_friday/
```

### Color-Coded Excel Reports

Three Excel workbooks are generated per cycle, with timestamped filenames and archived to `data/archive/reports/`:

**cycle_dashboard.xlsx** — Per-cycle snapshot:
- Summary sheet with all metrics
- Training Reminders: green=Stage 1, yellow=Stage 2, orange=Stage 3, red=Stage 4+
- IT PM Issues: orange for reminders, red for escalations
- Congratulations: blue
- Role Changes: gray

**tracker.xlsx** — Cross-cycle PM progression:
- One row per PM, two columns per cycle (Status + Stage)
- Training status: green=complete, red=incomplete
- Stage colors: green→yellow→orange→red→blue(congrats)
- Frozen panes, Legend sheet

**send_schedule.xlsx** — Handoff-ready email list:
- Instructions sheet with step-by-step guide
- All Emails sheet with: #, Send Date, Type, To, Name, Subject, full Email Body, Sent? column
- Per-day sheets (Tuesday, Wednesday, Thursday) with that day's emails
- Color-coded by type, auto-filter enabled
- Designed to be shared with someone who sends the emails

## Configuration

All settings are in `config.yaml`:

- **paths**: input, output, archive, database, logs directories
- **column_mapping**: maps logical field names to actual Excel column headers
- **status_mapping**: defines what values mean "completed" or "active"
- **required_training**: which courses PMs must complete
- **templates**: file paths for each reminder stage and email type
- **action_links**: URLs included in reminders (learning platform, ePPM, Viva Engage)
- **comms_schedule**: weekly send schedule (Monday→Friday)
- **file_patterns**: glob patterns to find input Excel files

## Database Schema

SQLite database (`data/training_reminders.db`) with these tables:

| Table | Purpose |
|-------|---------|
| `cycles` | Tracks each run (timestamp, status, notes) |
| `project_managers` | Unique PM identities |
| `assignment_snapshots` | PM-to-project assignments per cycle |
| `training_snapshots` | Training status per PM per cycle (with audit trail) |
| `communication_history` | All generated reminders with stage tracking |
| `processed_files` | Archived file records with checksums |
| `data_quality_issues` | Logged problems (missing email, unmatched records) |

## Streamlit Web UI

Launch with `./run.sh ui` or `streamlit run streamlit_app.py`.

**Weekly Operations:**
- **Dashboard** — Certification rate over time, compliance rate, reminders-to-certification metrics, time-to-certification charts. Smart landing: shows onboarding for new users, metrics for returning users.
- **Run Cycle** — Upload files with step indicators, preview data, run a cycle, view results with next-step guidance.
- **Reminders** — Browse generated emails by send day or category. Preview with parsed To/Subject/Body fields.
- **Calendar** — Color-coded weekly schedule, communication volume charts, cycle timeline, next-week projection.

**Analysis:**
- **IT PM Track Record** — Per-PM deep-dive: training progress, project assignments, communication timeline, compliance issues, full activity timeline.
- **Cycle Comparison** — Side-by-side diff: newly certified, new/left PMs, stage progression, project changes.
- **Cycle History** — Browse past cycles with tabs for assignments, training, communications, data quality.
- **Communications** — Filter/search all communications. Per-PM timeline showing reminder progression.
- **Data Quality** — Issue browser with unmatched PM resolution (name matching suggestions, alias creation guidance).

**Configuration:**
- **Templates** — View/edit Jinja2 email templates with variable reference guide.
- **Settings** — Visual and raw YAML editor for config.yaml with validation.

**Admin:**
- **Simulation** — Generate test data, run simulations, browse simulation data.
- **Log Viewer** — Browse logs with level filtering and search.
- **Archive Browser** — Browse archived files by cycle with checksums.
- **Database Explorer** — Browse tables with pagination, run custom SQL queries.

## Data Generator

The `generate_test_data.py` script creates realistic synthetic data with a **stable project registry** — projects keep the same PM, IT PM, Owner, and name across cycles. Changes happen via explicit mutations, not random reassignment.

### Scenarios Simulated

| Category | Scenario | Parameter |
|----------|----------|-----------|
| **People** | PM leaves organization | `--pm-leave-rate` |
| | PM temporarily removed then re-added | `--pm-readd-rate` |
| | PM transfers between projects | `--pm-transfer-rate` |
| **Identity** | Maiden names (different last name in ePPM vs Fuse) | `--maiden-name-count` |
| | Email domain aliases (corp.example vs brand.example) | `--alias-rate` |
| | Name collisions (two people, same name, different email) | `--name-collision-count` |
| | Unicode/accented names (Łukasz, Björn, José) ASCII-ified in Fuse | `--unicode-name-ascii-rate` (built-in) |
| | Shared/generic emails (pmo-team@, it-projects@) | `--shared-email-rate` |
| **Projects** | Gate progression (G0→G1→...→G6→Completed) | `--gate-advance-prob` |
| | Ghost/cancelled projects | `--cancel-rate-min/max` |
| | Project name changes between cycles | `--project-rename-rate` |
| | Heavy PM (one person on 20+ projects) | `--heavy-pm-count` |
| **Training** | Gradual certification over weeks | `--training-speed` |
| | Skip Fundamentals (Advanced without Fundamentals) | `--skip-fundamentals-rate` |
| | Score below passing threshold | `--training-fail-rate` |
| | Training revoked/expired | `--training-revoke-rate` |
| | Partial progress (in_progress status) | `--training-in-progress-rate` |
| **Compliance** | Gate-aware compliance (only for passed gates) | Built-in |
| | Late discovery (audit finds issues at Full gate) | `--compliance-late-discovery` |
| | Data correction (Partial downgraded to Non-compliant) | `--compliance-data-correction` |
| | Stale rollup (overall contradicts gates) | `--compliance-stale-rollup` |
| **Timing** | Stale Fuse data (1 cycle behind) | `--stale-fuse-rate` |
| | ePPM/Fuse export date mismatch | `--export-date-offset` |

Simulation files are prefixed with `SIM_` and include a timestamp and optional label:
```
ePPM_export_SIM_2026-04-03_0519_baseline_cycle1.xlsx
```

### Generator Examples

```bash
# Default (350 people, 250 projects, ~17 cycles to full certification)
python generate_test_data.py

# Quick demo with label
python generate_test_data.py --label quick-demo --num-people 100 --training-speed 2.0

# Stress test with high churn
python generate_test_data.py --label high-churn --pm-leave-rate 0.05 --cancel-rate-max 0.03

# Compare scenarios
python generate_test_data.py --label slow --training-speed 0.5
python generate_test_data.py --label fast --training-speed 2.0
```

## Simulation Runner

```bash
# Run all cycles
python run_simulation.py

# Generate + run in one command
python run_simulation.py --generate --generator-args --num-people 100 --training-speed 2.0

# Run specific cycles
python run_simulation.py --cycles 1 2 3

# Resume from existing database
python run_simulation.py --keep-db --start-cycle 4

# Run all cycles even after everyone is certified
python run_simulation.py --no-stop
```

## Project Structure

```
training_reminder_system/
├── run.sh                   # Setup and run script (venv, cli, ui, simulate, test)
├── streamlit_app.py         # Streamlit web UI (15 pages)
├── main.py                  # Entry point for single cycle
├── config.yaml              # All configuration
├── requirements.txt         # Python dependencies
├── generate_test_data.py    # Configurable synthetic data generator
├── run_simulation.py        # Multi-cycle simulation runner
├── data/
│   ├── input/               # Place Excel files here
│   ├── archive/             # Processed files + archived reports
│   ├── output/              # Generated outputs per cycle
│   └── simulation/          # Synthetic test data per cycle
├── logs/                    # Application logs
├── templates/               # 13 Jinja2 email templates
├── src/
│   ├── config_loader.py     # Configuration management
│   ├── file_loader.py       # Excel file reading and validation
│   ├── normalizer.py        # Name/email normalization
│   ├── matcher.py           # 4-pass cross-file identity matching
│   ├── evaluator.py         # Training evaluation + compliance extraction
│   ├── communication.py     # Reminder generation with stage progression
│   ├── repository.py        # SQLite database layer
│   ├── archiver.py          # File archiving with checksums
│   ├── reporting.py         # Output file generation
│   ├── excel_reports.py     # Color-coded Excel reports
│   └── utils.py             # Shared helpers
└── tests/                   # 139 unit tests
    ├── test_integration.py
    ├── test_streamlit_helpers.py
    └── ...
```

## Running Tests

```bash
./run.sh test           # Via run script
python -m pytest tests/ -v  # Direct
```

139 tests covering: matching, evaluation, communication, reporting, repository, file loading, configuration, archiving, Streamlit page logic, edge cases (empty DB, single cycle), templates, and data quality resolution.

## Limitations / Assumptions

- Column names must match the mappings in `config.yaml` (adjust as needed)
- The system assumes one ePPM and one Fuse file per run
- Email matching is case-insensitive
- The system does not send emails — all output is file-based
- SQLite is single-user; concurrent runs on the same database are not supported
