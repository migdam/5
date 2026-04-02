##############################################################################
# excel_reports.py — Color-Coded Excel Output Files
#
# Generates visually rich Excel workbooks that make it easy to see what
# happened in each cycle at a glance:
#
# 1. cycle_dashboard.xlsx — Per-cycle snapshot with color-coded sheets:
#    - Training Reminders: green=Stage 1, yellow=Stage 2, red=Stage 3+
#    - Missing IT PM: orange for reminders, red for escalations
#    - Congratulations: blue
#    - Data Quality: gray
#
# 2. tracker.xlsx — Cross-cycle PM tracker (generated from DB):
#    - One row per PM, one column group per cycle
#    - Training status: green=complete, red=incomplete
#    - Reminder stage: color gradient 1(green)->2(yellow)->3+(red)->99(blue)
#    - Shows progression at a glance across all cycles
#
# Color Legend:
#    Green   = complete / certified / Stage 1 (friendly)
#    Yellow  = in progress / Stage 2 (encouraging)
#    Orange  = warning / missing IT PM
#    Red     = incomplete / Stage 3+ (urgent) / escalation
#    Blue    = congratulations / nice-to-have
#    Gray    = skipped / not applicable
##############################################################################

import os
import logging

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color definitions
# ---------------------------------------------------------------------------
FILL_GREEN = PatternFill(start_color="D5F5E3", end_color="D5F5E3", fill_type="solid")
FILL_YELLOW = PatternFill(start_color="FEF9E7", end_color="FEF9E7", fill_type="solid")
FILL_ORANGE = PatternFill(start_color="FDEBD0", end_color="FDEBD0", fill_type="solid")
FILL_RED = PatternFill(start_color="FADBD8", end_color="FADBD8", fill_type="solid")
FILL_BLUE = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
FILL_GRAY = PatternFill(start_color="EAECEE", end_color="EAECEE", fill_type="solid")
FILL_DARK_GREEN = PatternFill(start_color="82E0AA", end_color="82E0AA", fill_type="solid")
FILL_DARK_RED = PatternFill(start_color="F1948A", end_color="F1948A", fill_type="solid")

FILL_HEADER = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
FONT_HEADER = Font(bold=True, color="FFFFFF", size=10)
FONT_BOLD = Font(bold=True, size=10)
FONT_NORMAL = Font(size=10)

ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")

THIN_BORDER = Border(
    left=Side(style="thin", color="D5D8DC"),
    right=Side(style="thin", color="D5D8DC"),
    top=Side(style="thin", color="D5D8DC"),
    bottom=Side(style="thin", color="D5D8DC"),
)

STAGE_FILLS = {
    1: FILL_GREEN,
    2: FILL_YELLOW,
    3: FILL_ORANGE,
    99: FILL_BLUE,    # Congratulations
    0: FILL_ORANGE,   # Missing IT PM
    -1: FILL_RED,     # Escalation
    -2: FILL_GRAY,    # Role change
}

STAGE_LABELS = {
    0: "Missing IT PM",
    -1: "Escalation",
    -2: "Role Change",
    99: "Congratulations",
}


def _style_header(ws, num_cols):
    """Apply header styling to the first row."""
    for col in range(1, num_cols + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = FILL_HEADER
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER
        cell.border = THIN_BORDER


def _auto_width(ws, min_width=10, max_width=40):
    """Auto-size columns based on content."""
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(min_width, min(max_len + 2, max_width))


# ---------------------------------------------------------------------------
# 1. Per-Cycle Dashboard Excel
# ---------------------------------------------------------------------------

def write_cycle_dashboard(output_dir, reminders, missing_itpm_reminders=None,
                          escalation_reminders=None, role_changed_reminders=None,
                          nice_to_have_pms=None, congratulations=None,
                          summary_data=None, cycle_id=None):
    """Write a color-coded Excel dashboard for a single cycle.

    Produces: cycle_dashboard.xlsx with multiple sheets.
    """
    if missing_itpm_reminders is None:
        missing_itpm_reminders = []
    if escalation_reminders is None:
        escalation_reminders = []
    if role_changed_reminders is None:
        role_changed_reminders = []
    if nice_to_have_pms is None:
        nice_to_have_pms = []
    if congratulations is None:
        congratulations = []

    filepath = os.path.join(output_dir, "cycle_dashboard.xlsx")
    wb = openpyxl.Workbook()

    # --- Sheet 1: Summary ---
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum.append(["Metric", "Value"])
    _style_header(ws_sum, 2)
    if summary_data:
        for key, value in summary_data.items():
            label = key.replace("_", " ").title()
            row_num = ws_sum.max_row + 1
            ws_sum.append([label, value])
            ws_sum.cell(row=row_num, column=1).font = FONT_BOLD
            ws_sum.cell(row=row_num, column=2).alignment = ALIGN_CENTER
            ws_sum.cell(row=row_num, column=1).border = THIN_BORDER
            ws_sum.cell(row=row_num, column=2).border = THIN_BORDER
    _auto_width(ws_sum)

    # --- Sheet 2: Training Reminders (color-coded by stage) ---
    if reminders:
        ws_rem = wb.create_sheet("Training Reminders")
        headers = ["Name", "Email", "Stage", "Missing Training", "Subject"]
        ws_rem.append(headers)
        _style_header(ws_rem, len(headers))

        for r in sorted(reminders, key=lambda x: (x["stage"], x["name"])):
            row_num = ws_rem.max_row + 1
            ws_rem.append([
                r["name"],
                r["recipient_email"],
                r["stage"],
                ", ".join(r.get("missing_trainings", [])),
                r["subject"],
            ])
            # Color the entire row by stage
            fill = STAGE_FILLS.get(r["stage"], FILL_RED if r["stage"] >= 3 else FILL_GRAY)
            for col in range(1, len(headers) + 1):
                cell = ws_rem.cell(row=row_num, column=col)
                cell.fill = fill
                cell.border = THIN_BORDER
                cell.font = FONT_NORMAL
        _auto_width(ws_rem)

    # --- Sheet 3: Missing IT PM ---
    if missing_itpm_reminders or escalation_reminders:
        ws_itpm = wb.create_sheet("IT PM Issues")
        headers = ["Type", "Name", "Email", "Projects", "Subject"]
        ws_itpm.append(headers)
        _style_header(ws_itpm, len(headers))

        for r in missing_itpm_reminders:
            row_num = ws_itpm.max_row + 1
            projects = ", ".join(f"{p['project_name']}" for p in r.get("projects", []))
            ws_itpm.append(["Reminder to PM", r["name"], r["recipient_email"], projects, r["subject"]])
            for col in range(1, len(headers) + 1):
                cell = ws_itpm.cell(row=row_num, column=col)
                cell.fill = FILL_ORANGE
                cell.border = THIN_BORDER

        for r in escalation_reminders:
            row_num = ws_itpm.max_row + 1
            projects = ", ".join(f"{p['project_name']}" for p in r.get("projects", []))
            ws_itpm.append(["Escalation to Owner", r["name"], r["recipient_email"], projects, r["subject"]])
            for col in range(1, len(headers) + 1):
                cell = ws_itpm.cell(row=row_num, column=col)
                cell.fill = FILL_RED
                cell.border = THIN_BORDER

        _auto_width(ws_itpm)

    # --- Sheet 4: Congratulations ---
    if congratulations:
        ws_congrats = wb.create_sheet("Congratulations")
        headers = ["Name", "Email", "Subject"]
        ws_congrats.append(headers)
        _style_header(ws_congrats, len(headers))

        for r in congratulations:
            row_num = ws_congrats.max_row + 1
            ws_congrats.append([r["name"], r["recipient_email"], r["subject"]])
            for col in range(1, len(headers) + 1):
                cell = ws_congrats.cell(row=row_num, column=col)
                cell.fill = FILL_BLUE
                cell.border = THIN_BORDER
        _auto_width(ws_congrats)

    # --- Sheet 5: Role Changes ---
    if role_changed_reminders:
        ws_rc = wb.create_sheet("Role Changes")
        headers = ["Name", "Email", "Projects", "Subject"]
        ws_rc.append(headers)
        _style_header(ws_rc, len(headers))

        for r in role_changed_reminders:
            row_num = ws_rc.max_row + 1
            projects = ", ".join(f"{p['project_name']}" for p in r.get("projects", []))
            ws_rc.append([r["name"], r["recipient_email"], projects, r["subject"]])
            for col in range(1, len(headers) + 1):
                cell = ws_rc.cell(row=row_num, column=col)
                cell.fill = FILL_GRAY
                cell.border = THIN_BORDER
        _auto_width(ws_rc)

    # --- Sheet 6: Nice to Have ---
    if nice_to_have_pms:
        ws_nth = wb.create_sheet("Nice to Have")
        headers = ["Name", "Email", "Completed", "Suggested"]
        ws_nth.append(headers)
        _style_header(ws_nth, len(headers))

        for pm in nice_to_have_pms:
            row_num = ws_nth.max_row + 1
            ws_nth.append([
                pm.get("full_name", ""),
                pm.get("email", ""),
                "Advanced",
                ", ".join(pm.get("nice_to_have_trainings", [])),
            ])
            for col in range(1, len(headers) + 1):
                cell = ws_nth.cell(row=row_num, column=col)
                cell.fill = FILL_BLUE
                cell.border = THIN_BORDER
        _auto_width(ws_nth)

    wb.save(filepath)
    logger.info("Cycle dashboard Excel written: %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# 2. Cross-Cycle Tracker Excel (from database)
# ---------------------------------------------------------------------------

def write_cross_cycle_tracker(output_dir, db_path):
    """Write a cross-cycle tracker Excel showing PM progression over time.

    Produces: tracker.xlsx with:
    - One row per PM
    - Per-cycle columns: Training Status, Reminder Stage
    - Color-coded cells showing progression
    """
    import sqlite3

    if not os.path.exists(db_path):
        logger.warning("No database at %s — skipping tracker", db_path)
        return None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cycles = conn.execute(
        "SELECT id, cycle_timestamp FROM cycles WHERE run_status = 'completed' ORDER BY id"
    ).fetchall()

    if not cycles:
        conn.close()
        return None

    cycle_ids = [c["id"] for c in cycles]

    # Get all PMs
    pms = conn.execute(
        "SELECT id, full_name, email FROM project_managers ORDER BY full_name"
    ).fetchall()

    if not pms:
        conn.close()
        return None

    # Build data: pm_id -> {cycle_id -> {status, stage}}
    pm_data = {}
    for pm in pms:
        pm_id = pm["id"]
        pm_data[pm_id] = {"name": pm["full_name"], "email": pm["email"], "cycles": {}}

        # Training status per cycle
        training = conn.execute(
            """SELECT cycle_id, overall_training_status, eligibility_status
               FROM training_snapshots WHERE project_manager_id = ?""",
            (pm_id,),
        ).fetchall()
        for t in training:
            pm_data[pm_id]["cycles"].setdefault(t["cycle_id"], {})["status"] = t["overall_training_status"]
            pm_data[pm_id]["cycles"].setdefault(t["cycle_id"], {})["eligibility"] = t["eligibility_status"]

        # Reminder stage per cycle
        comms = conn.execute(
            """SELECT cycle_id, reminder_stage
               FROM communication_history WHERE project_manager_id = ?""",
            (pm_id,),
        ).fetchall()
        for c in comms:
            pm_data[pm_id]["cycles"].setdefault(c["cycle_id"], {})["stage"] = c["reminder_stage"]

    conn.close()

    # --- Write Excel ---
    filepath = os.path.join(output_dir, "tracker.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PM Tracker"

    # Headers
    headers = ["Name", "Email"]
    for cid in cycle_ids:
        headers.append(f"C{cid} Status")
        headers.append(f"C{cid} Stage")
    ws.append(headers)
    _style_header(ws, len(headers))

    # Freeze panes: freeze name+email columns and header row
    ws.freeze_panes = "C2"

    # Data rows
    for pm_id, data in pm_data.items():
        if not data["cycles"]:
            continue  # Skip PMs with no cycle data

        row = [data["name"], data["email"]]
        for cid in cycle_ids:
            cycle_data = data["cycles"].get(cid, {})
            status = cycle_data.get("status", "")
            stage = cycle_data.get("stage", "")
            row.append(status or "")
            row.append(STAGE_LABELS.get(stage, f"S{stage}") if stage != "" else "")

        row_num = ws.max_row + 1
        ws.append(row)

        # Color-code cells
        for i, cid in enumerate(cycle_ids):
            status_col = 3 + i * 2
            stage_col = 4 + i * 2
            cycle_data = data["cycles"].get(cid, {})

            # Status cell
            status_cell = ws.cell(row=row_num, column=status_col)
            status_cell.border = THIN_BORDER
            status_cell.alignment = ALIGN_CENTER
            status = cycle_data.get("status", "")
            if status == "complete":
                status_cell.fill = FILL_DARK_GREEN
            elif status == "incomplete":
                status_cell.fill = FILL_DARK_RED
            else:
                status_cell.fill = FILL_GRAY

            # Stage cell
            stage_cell = ws.cell(row=row_num, column=stage_col)
            stage_cell.border = THIN_BORDER
            stage_cell.alignment = ALIGN_CENTER
            stage = cycle_data.get("stage", "")
            if stage != "":
                fill = STAGE_FILLS.get(stage, FILL_RED if isinstance(stage, int) and stage >= 3 else FILL_GRAY)
                stage_cell.fill = fill

        # Name and email cells
        ws.cell(row=row_num, column=1).border = THIN_BORDER
        ws.cell(row=row_num, column=1).font = FONT_BOLD
        ws.cell(row=row_num, column=2).border = THIN_BORDER

    _auto_width(ws, min_width=8, max_width=20)

    # --- Legend sheet ---
    ws_legend = wb.create_sheet("Legend")
    ws_legend.append(["Color", "Meaning"])
    _style_header(ws_legend, 2)
    legend_items = [
        (FILL_DARK_GREEN, "Training Complete"),
        (FILL_DARK_RED, "Training Incomplete"),
        (FILL_GREEN, "Stage 1 — Friendly Awareness"),
        (FILL_YELLOW, "Stage 2 — Encouraging"),
        (FILL_ORANGE, "Stage 3 — Persuasive / Missing IT PM"),
        (FILL_RED, "Stage 4+ — Urgent / Escalation"),
        (FILL_BLUE, "Congratulations / Nice-to-Have"),
        (FILL_GRAY, "Not Applicable / Role Change"),
    ]
    for fill, meaning in legend_items:
        row_num = ws_legend.max_row + 1
        ws_legend.append(["", meaning])
        ws_legend.cell(row=row_num, column=1).fill = fill
        ws_legend.cell(row=row_num, column=1).border = THIN_BORDER
        ws_legend.cell(row=row_num, column=2).border = THIN_BORDER
    _auto_width(ws_legend)

    wb.save(filepath)
    logger.info("Cross-cycle tracker Excel written: %s", filepath)
    return filepath
