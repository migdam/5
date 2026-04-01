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
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate synthetic test data (3 cycles)
python generate_test_data.py

# 3. Run the full 3-cycle simulation
python run_simulation.py

# Or run a single cycle manually
python main.py
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

## Project Structure

```
training_reminder_system/
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
