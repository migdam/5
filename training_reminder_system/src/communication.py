import os
import logging
from jinja2 import Template

logger = logging.getLogger(__name__)


def load_template(template_path):
    """Load a Jinja2 template from a file."""
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"Template not found: {template_path}")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    return content


def get_template_for_stage(stage, config):
    """Get the appropriate template file path for a reminder stage."""
    templates = config["templates"]
    if stage == 1 and "stage_1" in templates:
        return templates["stage_1"]
    elif stage == 2 and "stage_2" in templates:
        return templates["stage_2"]
    elif stage == 3 and "stage_3" in templates:
        return templates["stage_3"]
    else:
        return templates.get("default", templates.get("stage_3"))


def determine_reminder_stage(pm_id, db):
    """Determine the next reminder stage for a PM based on communication history."""
    last_stage = db.get_last_reminder_stage(pm_id)
    next_stage = last_stage + 1

    max_stage = db.conn.execute("SELECT 1").fetchone()  # just a check
    return next_stage


def render_reminder(name, email, missing_trainings, stage, config):
    """Render a reminder email using the appropriate stage template.

    Returns:
        dict with recipient_email, subject, body, stage.
    """
    template_path = get_template_for_stage(stage, config)
    template_content = load_template(template_path)

    # Split template into subject and body (first line is subject)
    lines = template_content.strip().split("\n", 1)
    subject_template = lines[0].replace("Subject: ", "").strip()
    body_template = lines[1].strip() if len(lines) > 1 else ""

    missing_str = ", ".join(missing_trainings)

    # Render with Jinja2
    subject = Template(subject_template).render(
        name=name, missing_trainings=missing_str, stage=stage
    )
    body = Template(body_template).render(
        name=name, missing_trainings=missing_str, stage=stage
    )

    return {
        "recipient_email": email,
        "subject": subject,
        "body": body,
        "stage": stage,
        "name": name,
        "missing_trainings": missing_trainings,
    }


def generate_reminders(eligible_pms, db, cycle_id, config):
    """Generate reminder communications for all eligible PMs.

    Args:
        eligible_pms: List of PM dicts with missing_trainings.
        db: Database instance.
        cycle_id: Current cycle ID.
        config: Application configuration.

    Returns:
        List of reminder dicts ready for output.
    """
    reminders = []
    skipped_no_email = 0

    for pm in eligible_pms:
        name = pm["full_name"]
        email = pm.get("email")
        missing = pm["missing_trainings"]

        # Skip if no email
        if not email or str(email) in ("", "None", "nan"):
            db.insert_data_quality_issue(
                cycle_id, "missing_email", name, None,
                f"PM '{name}' has no email address; cannot generate reminder."
            )
            skipped_no_email += 1
            logger.warning("Skipping PM '%s' - no email address", name)
            continue

        # Get PM ID from database
        from src.normalizer import normalize_name, normalize_email
        norm_name = normalize_name(name)
        norm_email = normalize_email(email)
        pm_id = db.upsert_project_manager(name, email, norm_name)

        # Determine stage
        stage = determine_reminder_stage(pm_id, db)

        # Check max stage config
        max_stage = config.get("communication", {}).get("max_reminder_stage", 0)
        if max_stage > 0 and stage > max_stage:
            logger.info("PM '%s' has reached max reminder stage %d, capping", name, max_stage)
            stage = max_stage

        # Render reminder
        reminder = render_reminder(name, email, missing, stage, config)

        # Store in database
        db.insert_communication(cycle_id, pm_id, stage, reminder["subject"], reminder["body"])

        reminders.append(reminder)
        logger.debug("Generated stage %d reminder for %s <%s>", stage, name, email)

    logger.info(
        "Generated %d reminders, skipped %d (no email)",
        len(reminders),
        skipped_no_email,
    )

    return reminders, skipped_no_email
