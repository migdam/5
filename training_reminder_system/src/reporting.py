import csv
import os
import logging
from jinja2 import Template
from src.utils import get_timestamp

logger = logging.getLogger(__name__)


def generate_outputs(reminders, summary_data, config, cycle_id,
                     missing_itpm_reminders=None, escalation_reminders=None,
                     role_changed_reminders=None, nice_to_have_pms=None):
    """Generate all output files for a processing cycle.

    Args:
        reminders: List of training reminder dicts.
        summary_data: Dict with summary counts.
        config: Application configuration.
        cycle_id: Current cycle ID.
        missing_itpm_reminders: List of missing IT PM reminder dicts (optional).
        escalation_reminders: List of escalation-to-owner reminder dicts (optional).
        role_changed_reminders: List of role-changed IT PM reminders (optional).

    Returns:
        Path to the output folder created.
    """
    if missing_itpm_reminders is None:
        missing_itpm_reminders = []
    if escalation_reminders is None:
        escalation_reminders = []
    if role_changed_reminders is None:
        role_changed_reminders = []
    if nice_to_have_pms is None:
        nice_to_have_pms = []

    output_base = config["paths"]["output_folder"]
    timestamp = get_timestamp()
    output_dir = os.path.join(output_base, f"{timestamp}_cycle{cycle_id}")
    os.makedirs(output_dir, exist_ok=True)

    output_opts = config.get("output", {})

    # 1. Summary report
    if output_opts.get("generate_summary", True):
        _write_summary(output_dir, summary_data, cycle_id)

    # 2. CSV export (training reminders)
    if output_opts.get("generate_csv", True) and reminders:
        _write_csv(output_dir, reminders)

    # 3. Per-stage folders with individual files
    if output_opts.get("generate_per_stage_folders", True) and reminders:
        _write_per_stage(output_dir, reminders)

    # 4. Per-recipient files
    if output_opts.get("generate_per_recipient_files", True) and reminders:
        _write_per_recipient(output_dir, reminders)

    # 5. Missing IT PM reminders
    if missing_itpm_reminders:
        _write_missing_itpm(output_dir, missing_itpm_reminders)

    # 5b. Escalation reminders to Project Owners
    if escalation_reminders:
        _write_escalations(output_dir, escalation_reminders)

    # 5c. Role-changed IT PM reminders
    if role_changed_reminders:
        _write_role_changed(output_dir, role_changed_reminders)

    # 5d. Nice-to-have training suggestions (Advanced done, Fundamentals optional)
    if nice_to_have_pms:
        _write_nice_to_have(output_dir, nice_to_have_pms)

    # 6. Group emails (single email with all recipients in To: field)
    if output_opts.get("generate_group_emails", False):
        _write_group_emails(output_dir, reminders, missing_itpm_reminders, config)

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


def _write_missing_itpm(output_dir, reminders):
    """Write missing IT PM assignment reminders to a dedicated folder."""
    itpm_dir = os.path.join(output_dir, "missing_itpm")
    os.makedirs(itpm_dir, exist_ok=True)

    # Write individual files
    for r in reminders:
        safe_name = _safe_filename(r["name"])
        filename = f"{safe_name}_missing_itpm.txt"
        filepath = os.path.join(itpm_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("MISSING IT PM REMINDER - READY TO SEND\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"To:      {r['recipient_email']}\n")
            f.write(f"Subject: {r['subject']}\n")
            f.write(f"Type:    IT PM Assignment Reminder\n")
            f.write(f"Projects without IT PM:\n")
            for p in r.get("projects", []):
                f.write(f"  - {p['project_name']} ({p['project_id']})\n")
            f.write("\n" + "-" * 60 + "\n")
            f.write("EMAIL BODY (copy below this line):\n")
            f.write("-" * 60 + "\n\n")
            f.write(r["body"])
            f.write("\n")

    # Write CSV summary
    csv_path = os.path.join(itpm_dir, "missing_itpm_reminders.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "recipient_email", "pm_name", "num_projects", "projects", "subject"
        ])
        writer.writeheader()
        for r in reminders:
            writer.writerow({
                "recipient_email": r["recipient_email"],
                "pm_name": r["name"],
                "num_projects": len(r.get("projects", [])),
                "projects": r.get("project_list", ""),
                "subject": r["subject"],
            })

    logger.info(
        "Missing IT PM folder: %d reminder files + CSV", len(reminders)
    )


def _write_escalations(output_dir, reminders):
    """Write escalation reminders to Project Owners."""
    esc_dir = os.path.join(output_dir, "escalations_to_owner")
    os.makedirs(esc_dir, exist_ok=True)

    for r in reminders:
        safe_name = _safe_filename(r["name"])
        pm_safe = _safe_filename(r.get("pm_name", "unknown"))
        filename = f"escalation_{safe_name}_re_{pm_safe}.txt"
        filepath = os.path.join(esc_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("ESCALATION TO PROJECT OWNER - READY TO SEND\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"To:      {r['recipient_email']}\n")
            f.write(f"Subject: {r['subject']}\n")
            f.write(f"Type:    Escalation - IT PM Not Assigned\n")
            f.write(f"PM who was reminded: {r.get('pm_name', 'N/A')} ({r.get('pm_email', 'N/A')})\n")
            f.write(f"Projects affected:\n")
            for p in r.get("projects", []):
                f.write(f"  - {p['project_name']} ({p['project_id']})\n")
            f.write("\n" + "-" * 60 + "\n")
            f.write("EMAIL BODY (copy below this line):\n")
            f.write("-" * 60 + "\n\n")
            f.write(r["body"])
            f.write("\n")

    # CSV summary
    csv_path = os.path.join(esc_dir, "escalation_reminders.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "owner_email", "owner_name", "pm_name", "pm_email",
            "num_projects", "projects", "subject",
        ])
        writer.writeheader()
        for r in reminders:
            writer.writerow({
                "owner_email": r["recipient_email"],
                "owner_name": r["name"],
                "pm_name": r.get("pm_name", ""),
                "pm_email": r.get("pm_email", ""),
                "num_projects": len(r.get("projects", [])),
                "projects": r.get("project_list", ""),
                "subject": r["subject"],
            })

    logger.info(
        "Escalation folder: %d escalation files + CSV", len(reminders)
    )


def _write_role_changed(output_dir, reminders):
    """Write role-changed IT PM reminders."""
    rc_dir = os.path.join(output_dir, "role_changed_itpm")
    os.makedirs(rc_dir, exist_ok=True)

    for r in reminders:
        safe_name = _safe_filename(r["name"])
        filename = f"{safe_name}_role_changed_itpm.txt"
        filepath = os.path.join(rc_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("ROLE-CHANGED IT PM ALERT - READY TO SEND\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"To:      {r['recipient_email']}\n")
            f.write(f"Subject: {r['subject']}\n")
            f.write(f"Type:    IT PM Role Change Alert\n")
            f.write(f"Affected projects:\n")
            for p in r.get("projects", []):
                f.write(f"  - {p['project_name']} ({p['project_id']})\n")
                f.write(f"    IT PM: {p['it_pm_name']} -> now: {p['current_position']}\n")
            f.write("\n" + "-" * 60 + "\n")
            f.write("EMAIL BODY (copy below this line):\n")
            f.write("-" * 60 + "\n\n")
            f.write(r["body"])
            f.write("\n")

    # CSV
    csv_path = os.path.join(rc_dir, "role_changed_itpm_reminders.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "recipient_email", "pm_name", "num_projects", "details", "subject",
        ])
        writer.writeheader()
        for r in reminders:
            writer.writerow({
                "recipient_email": r["recipient_email"],
                "pm_name": r["name"],
                "num_projects": len(r.get("projects", [])),
                "details": r.get("project_list", ""),
                "subject": r["subject"],
            })

    logger.info("Role-changed IT PM folder: %d files + CSV", len(reminders))


def _write_nice_to_have(output_dir, nice_to_have_pms):
    """Write optional nice-to-have training suggestions.

    These are PMs who completed Advanced but not Fundamentals.
    Fundamentals is recommended but not required for them.
    """
    nth_dir = os.path.join(output_dir, "nice_to_have")
    os.makedirs(nth_dir, exist_ok=True)

    # Summary file
    summary_path = os.path.join(nth_dir, "nice_to_have_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("NICE-TO-HAVE TRAINING SUGGESTIONS\n")
        f.write("(These PMs completed Advanced but not Fundamentals)\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total: {len(nice_to_have_pms)} PMs\n\n")
        f.write("These PMs are fully certified for project delivery purposes.\n")
        f.write("Completing Fundamentals would round out their knowledge base\n")
        f.write("but is NOT required.\n\n")
        f.write("-" * 60 + "\n\n")
        for pm in sorted(nice_to_have_pms, key=lambda p: p.get("full_name", "")):
            name = pm.get("full_name", "Unknown")
            email = pm.get("email", "")
            nice = ", ".join(pm.get("nice_to_have_trainings", []))
            f.write(f"  {name} ({email})\n")
            f.write(f"    Completed: Advanced\n")
            f.write(f"    Suggested: {nice}\n\n")

    # CSV
    csv_path = os.path.join(nth_dir, "nice_to_have.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "name", "email", "completed", "suggested_training",
        ])
        writer.writeheader()
        for pm in nice_to_have_pms:
            writer.writerow({
                "name": pm.get("full_name", ""),
                "email": pm.get("email", ""),
                "completed": "Advanced",
                "suggested_training": ", ".join(pm.get("nice_to_have_trainings", [])),
            })

    logger.info("Nice-to-have folder: %d PMs with optional training suggestions", len(nice_to_have_pms))


def _write_group_emails(output_dir, training_reminders, itpm_reminders, config):
    """Write group email files: one email per reminder type with all recipients in To:.

    Generates ready-to-paste files where all recipients are listed in the To: field
    and the body is a single group message addressing everyone.
    """
    group_dir = os.path.join(output_dir, "group_emails")
    os.makedirs(group_dir, exist_ok=True)

    templates_config = config.get("templates", {})

    # --- Group training reminders (one per stage) ---
    if training_reminders:
        stages = sorted(set(r["stage"] for r in training_reminders))
        for stage in stages:
            stage_reminders = [r for r in training_reminders if r["stage"] == stage]
            emails = sorted(set(r["recipient_email"] for r in stage_reminders))

            # Build recipient list for template
            recipients_data = []
            for r in sorted(stage_reminders, key=lambda x: x["name"]):
                recipients_data.append({
                    "name": r["name"],
                    "email": r["recipient_email"],
                    "missing_trainings": ", ".join(r["missing_trainings"]),
                })

            # Render group template
            template_path = templates_config.get("group_training")
            if template_path and os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    template_content = f.read()
                lines = template_content.strip().split("\n", 1)
                subject_tpl = lines[0].replace("Subject: ", "").strip()
                body_tpl = lines[1].strip() if len(lines) > 1 else ""
                subject = Template(subject_tpl).render(stage=stage, recipients=recipients_data)
                body = Template(body_tpl).render(stage=stage, recipients=recipients_data)
            else:
                subject = f"Reminder: Project Management Training Completion Required (Stage {stage})"
                body = _build_default_group_training_body(recipients_data)

            filepath = os.path.join(group_dir, f"group_training_stage_{stage}.txt")
            _write_group_file(filepath, emails, subject, body,
                              f"GROUP TRAINING REMINDER - STAGE {stage}",
                              len(stage_reminders))

        # Also write an all-stages combined group email
        all_emails = sorted(set(r["recipient_email"] for r in training_reminders))
        all_recipients = []
        for r in sorted(training_reminders, key=lambda x: x["name"]):
            all_recipients.append({
                "name": r["name"],
                "email": r["recipient_email"],
                "missing_trainings": ", ".join(r["missing_trainings"]),
                "stage": r["stage"],
            })

        template_path = templates_config.get("group_training")
        if template_path and os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()
            lines = template_content.strip().split("\n", 1)
            subject_tpl = lines[0].replace("Subject: ", "").strip()
            body_tpl = lines[1].strip() if len(lines) > 1 else ""
            subject = Template(subject_tpl).render(stage="all", recipients=all_recipients)
            body = Template(body_tpl).render(stage="all", recipients=all_recipients)
        else:
            subject = "Reminder: Project Management Training Completion Required"
            body = _build_default_group_training_body(all_recipients)

        filepath = os.path.join(group_dir, "group_training_all.txt")
        _write_group_file(filepath, all_emails, subject, body,
                          "GROUP TRAINING REMINDER - ALL STAGES",
                          len(training_reminders))

    # --- Group missing IT PM reminders ---
    if itpm_reminders:
        emails = sorted(set(r["recipient_email"] for r in itpm_reminders))
        recipients_data = []
        for r in sorted(itpm_reminders, key=lambda x: x["name"]):
            recipients_data.append({
                "name": r["name"],
                "email": r["recipient_email"],
                "projects": r.get("projects", []),
            })

        template_path = templates_config.get("group_missing_itpm")
        if template_path and os.path.exists(template_path):
            with open(template_path, "r", encoding="utf-8") as f:
                template_content = f.read()
            lines = template_content.strip().split("\n", 1)
            subject_tpl = lines[0].replace("Subject: ", "").strip()
            body_tpl = lines[1].strip() if len(lines) > 1 else ""
            subject = Template(subject_tpl).render(recipients=recipients_data)
            body = Template(body_tpl).render(recipients=recipients_data)
        else:
            subject = "Action Requested: Please Assign IT Project Managers in ePPM"
            body = _build_default_group_itpm_body(recipients_data)

        filepath = os.path.join(group_dir, "group_missing_itpm.txt")
        _write_group_file(filepath, emails, subject, body,
                          "GROUP MISSING IT PM REMINDER",
                          len(itpm_reminders))

    # Write recipient list files (easy to copy into Outlook To: field)
    if training_reminders:
        all_training_emails = sorted(set(r["recipient_email"] for r in training_reminders))
        _write_email_list(os.path.join(group_dir, "training_recipients.txt"), all_training_emails)

    if itpm_reminders:
        all_itpm_emails = sorted(set(r["recipient_email"] for r in itpm_reminders))
        _write_email_list(os.path.join(group_dir, "missing_itpm_recipients.txt"), all_itpm_emails)

    total = (len(training_reminders) > 0) + (len(itpm_reminders) > 0)
    logger.info("Group emails folder: %s", group_dir)


def _write_group_file(filepath, emails, subject, body, title, recipient_count):
    """Write a group email file ready for copy-paste."""
    logger.debug("Writing group file: %s (%d recipients)", filepath, recipient_count)
    email_list = "; ".join(emails)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write(f"{title}\n")
        f.write(f"Recipients: {recipient_count}\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"To:      {email_list}\n\n")
        f.write(f"Subject: {subject}\n")
        f.write("\n" + "-" * 70 + "\n")
        f.write("EMAIL BODY (copy below this line):\n")
        f.write("-" * 70 + "\n\n")
        f.write(body)
        f.write("\n")


def _write_email_list(filepath, emails):
    """Write a plain list of emails, one per line and semicolon-separated."""
    logger.debug("Writing email list: %s (%d emails)", filepath, len(emails))
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Email list - copy the line below into the To: field\n")
        f.write("# Semicolon-separated (Outlook format):\n")
        f.write("; ".join(emails))
        f.write("\n\n")
        f.write("# One per line:\n")
        for email in emails:
            f.write(email + "\n")


def _build_default_group_training_body(recipients):
    """Fallback group training body if no template is configured."""
    lines = ["Dear Colleagues,\n"]
    lines.append("You are receiving this message because you have outstanding "
                 "project management training.\n")
    lines.append("Outstanding training per person:")
    for r in recipients:
        lines.append(f"  - {r['name']}: missing {r['missing_trainings']}")
    lines.append("\nPlease complete your training at your earliest convenience.")
    lines.append("\nBest regards,\nProject Management Office")
    return "\n".join(lines)


def _build_default_group_itpm_body(recipients):
    """Fallback group missing IT PM body if no template is configured."""
    lines = ["Dear Colleagues,\n"]
    lines.append("The following projects need an IT Project Manager assigned in ePPM:\n")
    for r in recipients:
        lines.append(f"{r['name']} ({r['email']}):")
        for p in r.get("projects", []):
            lines.append(f"  - {p['project_name']} ({p['project_id']})")
        lines.append("")
    lines.append("Please update ePPM at your earliest convenience.")
    lines.append("\nBest regards,\nProject Management Office")
    return "\n".join(lines)


def _write_reminder_file(filepath, reminder):
    """Write a single reminder to a text file, formatted for easy copy-paste."""
    logger.debug("Writing reminder file: %s (stage %d)", filepath, reminder.get("stage", 0))
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
