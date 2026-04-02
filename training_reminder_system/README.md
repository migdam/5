# Training Reminder System

A local Python application that automates **training reminder preparation** for IT Project Managers assigned to projects. It does **not** send emails automatically. Instead, it generates email-ready outputs that can be manually copied and pasted into Outlook or any email client.

## Purpose

The system:
1. Reads two Excel files: **ePPM** (project assignments) and **Fuse** (training status)
2. Matches people across both files using email, name, or normalized name
3. Identifies Project Managers who are assigned to active projects but haven't completed required training
4. Generates progressive reminder messages (friendly -> encouraging -> persuasive)
5. Tracks all communication history in SQLite
6. Stops generating reminders once training is completed
7. Archives processed files to prevent reprocessing

## Quick Start

```bash
# Option A: Use the run script (recommended — handles venv automatically)
./run.sh setup        # Create venv and install dependencies
./run.sh ui           # Launch the Streamlit web UI
./run.sh cli          # Run a single processing cycle
./run.sh simulate     # Generate test data and run simulation
./run.sh test         # Run the test suite

# Option B: Manual setup
pip install -r requirements.txt

# Generate synthetic test data (3 cycles)
python generate_test_data.py

# Run the full 3-cycle simulation
python run_simulation.py

# Or run a single cycle manually
python main.py

# Or launch the Streamlit web UI
streamlit run streamlit_app.py
```

## Input Files

Place two Excel files in `data/input/`:

### ePPM Export (project assignments)
Expected columns (configurable in `config.yaml`):
- Project number, Project Name
- Active Stage, Project Status
- Project Manager, Project Manager Email
- IT Project Manager, IT Project Manager Email
- IT Portfolio Manager, IT Portfolio Manager Email

### Fuse Export (training status)
Expected columns (configurable in `config.yaml`):
- Full Name, Email
- Content Title, Course Status
- Completion Date, Score

The required training courses (configurable) are:
- `Managing Projects for Business Success - Fundamentals - Certification Test`
- `Certification Test for Managing Projects for Business Success (Advanced)`

## How Matching Works

People are matched across the two files in three passes:

1. **Email match** (highest priority): normalized email comparison
2. **Exact name match**: full name string comparison
3. **Normalized name match**: lowercase, stripped, whitespace-collapsed comparison

Each pass only attempts to match records that weren't matched in previous passes.

## How Reminder Stages Work

The system tracks which stage of reminder has been sent to each person:

| Stage | Tone | Template |
|-------|------|----------|
| 1 | Friendly awareness | `templates/reminder_stage_1.txt` |
| 2 | Benefits-oriented encouragement | `templates/reminder_stage_2.txt` |
| 3 | Persuasive, action-oriented | `templates/reminder_stage_3.txt` |
| 4+ | Reusable default | `templates/reminder_stage_default.txt` |

Each time you run the system, it checks the PM's communication history:
- No previous reminder -> Stage 1
- Previous Stage 1 and still non-compliant -> Stage 2
- And so on...

If training is completed, **no reminder is generated**.

## Configuration

All settings are in `config.yaml`:

- **paths**: input, output, archive, database, logs directories
- **column_mapping**: maps logical field names to actual Excel column headers
- **status_mapping**: defines what values mean "completed" or "active"
- **required_training**: which courses PMs must complete
- **templates**: file paths for each reminder stage
- **file_patterns**: glob patterns to find input Excel files

## Output Structure

Each run creates a timestamped folder in `data/output/`:

```
data/output/2026-04-01_1530_cycle1/
├── summary_report.md          # Counts and metrics
├── reminders.csv              # All reminders in CSV (for mail merge)
├── stage_1/                   # Grouped by stage
│   ├── maya_collins.txt
│   └── daniel_carter.txt
├── stage_2/
│   └── ...
└── per_recipient/             # One file per person
    ├── maya_collins_stage1.txt
    └── ...
```

Each reminder file contains:
- Recipient email (To:)
- Subject line
- Stage number
- Training gap
- Full email body ready to copy-paste

## Database Schema

SQLite database (`data/training_reminders.db`) with these tables:

| Table | Purpose |
|-------|---------|
| `cycles` | Tracks each run (timestamp, status, notes) |
| `project_managers` | Unique PM identities |
| `assignment_snapshots` | PM-to-project assignments per cycle |
| `training_snapshots` | Training status per PM per cycle |
| `communication_history` | All generated reminders with stage tracking |
| `processed_files` | Archived file records with checksums |
| `data_quality_issues` | Logged problems (missing email, unmatched records) |

## Archiving

After each successful run, input files are moved to:
```
data/archive/YYYY-MM-DD/YYYY-MM-DD_HHMMSS_original_filename.xlsx
```

This prevents accidental reprocessing and maintains full traceability.

## Adjusting Templates

Templates are plain text files with Jinja2 placeholders:
- `{{name}}` - PM's full name
- `{{missing_trainings}}` - comma-separated list of missing courses
- `{{stage}}` - reminder stage number

The first line of each template is the email subject (prefixed with `Subject: `).

Edit the files in `templates/` to customize the message tone and content.

## Multi-Cycle Simulation

The `run_simulation.py` script demonstrates the system across 3 cycles with evolving data:

- **Cycle 1**: Baseline with ~250 projects, ~40% fundamentals completion
- **Cycle 2**: 30 new projects, 15 completed, more people trained (+15% fundamentals)
- **Cycle 3**: 20 more new projects, training rates increase further

This shows:
- Stage 1 reminders in cycle 1
- Stage 2 for persistent non-compliant in cycle 2, Stage 1 for new PMs
- Stage 3 for those still non-compliant in cycle 3
- No reminders for PMs who completed training between cycles

## Streamlit Web UI

The system includes an optional browser-based interface built with Streamlit. Launch it with:

```bash
streamlit run streamlit_app.py
```

The UI provides fifteen pages:

- **Dashboard**: Key metrics with KPI cards and charts — IT PM certification rate over time (line chart), project compliance rate over time (line chart with inverse delta coloring), average/median/min/max reminders to certification (distribution histogram), and time to certification from first reminder (days distribution chart). Each metric includes per-PM detail tables.
- **Run Cycle**: Upload ePPM and Fuse Excel files (plus optional files), preview data, run a processing cycle, view summary metrics, browse output files, and download results as a zip.
- **Reminders**: Browse generated email reminders organized by send day (Tuesday through Friday) matching the weekly comms schedule. Preview individual emails with parsed To/Subject/Body fields ready to copy into Outlook. Also browse by category (per-recipient, per-stage, missing IT PM, escalations, etc.). Includes the communication plan and summary report. Download output as a zip.
- **Templates**: View and edit all Jinja2 email templates organized by category (training reminders, follow-up rotations, IT PM reminders, congratulations, group emails). Shows available template variables and conditionals. Includes a variable reference guide. Changes save directly to disk.
- **Calendar**: Visual weekly send schedule showing which communication types go out on which day (color-coded cards). Communication history charts showing volume and type breakdown across cycles. Cycle run timeline with status indicators. Next-week projection based on the latest cycle results.
- **IT PM Track Record**: Comprehensive per-PM view with search. Shows identity card with quick stats (training status, current stage, total reminders, projects, cycles tracked, certification). Five detail tabs: Training Progress (status over time with visual indicators), Project Assignments (unique projects and assignment timeline matrix), Communications (stage progression visualization with full email preview), Compliance (issues by project, gate distribution chart, trend over time), and Full Timeline (all events chronologically).
- **Cycle Comparison**: Side-by-side comparison of two cycles showing newly certified PMs, new/removed PMs, training status changes, communication stage progression, and project assignment changes (new/removed/continuing projects).
- **Cycle History**: Browse all past cycles with detailed tabs for assignments, training status, communications, and data quality issues per cycle. Includes email preview.
- **Communications**: Filter and search all communications across cycles. View per-PM communication timelines to see reminder progression.
- **Data Quality**: Review data quality issues with filtering by type. Includes unmatched PM resolution — shows possible name matches from the database and provides guidance for creating identity aliases.
- **Settings**: Visual editor and raw YAML editor for `config.yaml`. Edit action links, communication settings, file patterns. Validates YAML before saving.
- **Simulation**: Generate synthetic test data and run multi-cycle simulations. Run full simulations or individual cycles. Browse existing simulation data.
- **Log Viewer**: Browse application logs with level filtering (INFO/WARNING/ERROR/DEBUG) and text search. Error/warning summary. Download log files.
- **Archive Browser**: Browse archived input files by cycle, view the processed files registry with checksums, inspect archive folder contents and total size.
- **Database Explorer**: Browse any table in the SQLite database with pagination, or run custom SQL queries.

## Project Structure

```
training_reminder_system/
├── run.sh                   # Setup and run script (venv, cli, ui, simulate, test)
├── streamlit_app.py         # Streamlit web UI
├── main.py                  # Entry point for single cycle
├── config.yaml              # All configuration
├── requirements.txt         # Python dependencies
├── generate_test_data.py    # Synthetic data generator
├── run_simulation.py        # Multi-cycle simulation runner
├── data/
│   ├── input/               # Place Excel files here
│   ├── archive/             # Processed files moved here
│   ├── output/              # Generated outputs per run
│   └── simulation/          # Test data for 3 cycles
├── logs/                    # Application logs
├── templates/               # Email templates (editable)
├── src/                     # Source modules
│   ├── config_loader.py     # Configuration management
│   ├── file_loader.py       # Excel file reading
│   ├── normalizer.py        # Name/email normalization
│   ├── matcher.py           # Cross-file identity matching
│   ├── evaluator.py         # Training completion evaluation
│   ├── communication.py     # Reminder generation
│   ├── repository.py        # SQLite database layer
│   ├── archiver.py          # File archiving
│   ├── reporting.py         # Output file generation
│   └── utils.py             # Shared helpers
└── tests/                   # Unit tests
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Limitations / Assumptions

- Column names must match the mappings in `config.yaml` (adjust as needed)
- The system assumes one ePPM and one Fuse file per run
- Email matching is case-insensitive but exact on the local part
- Name matching handles whitespace but not transliteration (e.g., umlauts)
- The system does not send emails - all output is file-based
- SQLite is single-user; concurrent runs on the same database are not supported
