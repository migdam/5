import csv
import os
import logging
from src.utils import get_timestamp

logger = logging.getLogger(__name__)


def generate_outputs(reminders, summary_data, config, cycle_id):
    """Generate all output files for a processing cycle.

    Args:
        reminders: List of reminder dicts.
        summary_data: Dict with summary counts.
        config: Application configuration.
        cycle_id: Current cycle ID.

    Returns:
        Path to the output folder created.
    """
    output_base = config["paths"]["output_folder"]
    timestamp = get_timestamp()
    output_dir = os.path.join(output_base, f"{timestamp}_cycle{cycle_id}")
    os.makedirs(output_dir, exist_ok=True)

    output_opts = config.get("output", {})

    # 1. Summary report
    if output_opts.get("generate_summary", True):
        _write_summary(output_dir, summary_data, cycle_id)

    # 2. CSV export
    if output_opts.get("generate_csv", True) and reminders:
        _write_csv(output_dir, reminders)

    # 3. Per-stage folders with individual files
    if output_opts.get("generate_per_stage_folders", True) and reminders:
        _write_per_stage(output_dir, reminders)

    # 4. Per-recipient files
    if output_opts.get("generate_per_recipient_files", True) and reminders:
        _write_per_recipient(output_dir, reminders)

    logger.info("Output files generated in %s", output_dir)
    return output_dir


def _write_summary(output_dir, data, cycle_id):
    """Write a summary report in Markdown format."""
    path = os.path.join(output_dir, "summary_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Training Reminder Summary - Cycle {cycle_id}\n\n")
        f.write(f"| Metric | Count |\n")
        f.write(f"|--------|-------|\n")
        for key, value in data.items():
            label = key.replace("_", " ").title()
            f.write(f"| {label} | {value} |\n")
        f.write("\n")
    logger.info("Summary report written: %s", path)


def _write_csv(output_dir, reminders):
    """Write all reminders to a single CSV file."""
    path = os.path.join(output_dir, "reminders.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "recipient_email", "name", "stage", "subject",
            "missing_trainings", "body"
        ])
        writer.writeheader()
        for r in reminders:
            writer.writerow({
                "recipient_email": r["recipient_email"],
                "name": r["name"],
                "stage": r["stage"],
                "subject": r["subject"],
                "missing_trainings": ", ".join(r["missing_trainings"]),
                "body": r["body"],
            })
    logger.info("CSV export written: %s (%d reminders)", path, len(reminders))


def _write_per_stage(output_dir, reminders):
    """Write reminders grouped by stage into separate folders."""
    stages = sorted(set(r["stage"] for r in reminders))
    for stage in stages:
        stage_dir = os.path.join(output_dir, f"stage_{stage}")
        os.makedirs(stage_dir, exist_ok=True)

        stage_reminders = [r for r in reminders if r["stage"] == stage]
        for r in stage_reminders:
            safe_name = _safe_filename(r["name"])
            filename = f"{safe_name}.txt"
            filepath = os.path.join(stage_dir, filename)
            _write_reminder_file(filepath, r)

        logger.info("Stage %d folder: %d reminder files", stage, len(stage_reminders))


def _write_per_recipient(output_dir, reminders):
    """Write one file per recipient in a recipients/ folder."""
    recipients_dir = os.path.join(output_dir, "per_recipient")
    os.makedirs(recipients_dir, exist_ok=True)

    for r in reminders:
        safe_name = _safe_filename(r["name"])
        filename = f"{safe_name}_stage{r['stage']}.txt"
        filepath = os.path.join(recipients_dir, filename)
        _write_reminder_file(filepath, r)

    logger.info("Per-recipient folder: %d files", len(reminders))


def _write_reminder_file(filepath, reminder):
    """Write a single reminder to a text file, formatted for easy copy-paste."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("TRAINING REMINDER - READY TO SEND\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"To:      {reminder['recipient_email']}\n")
        f.write(f"Subject: {reminder['subject']}\n")
        f.write(f"Stage:   {reminder['stage']}\n")
        f.write(f"Gap:     {', '.join(reminder['missing_trainings'])}\n")
        f.write("\n" + "-" * 60 + "\n")
        f.write("EMAIL BODY (copy below this line):\n")
        f.write("-" * 60 + "\n\n")
        f.write(reminder["body"])
        f.write("\n")


def _safe_filename(name):
    """Convert a name to a safe filename."""
    safe = name.lower().replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c == "_")
    return safe
