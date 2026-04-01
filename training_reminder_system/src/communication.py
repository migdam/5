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


def render_reminder(name, email, missing_trainings, stage, config, nice_to_have_trainings=None):
    """Render a reminder email using the appropriate stage template.

    Passes structured training gap info to templates so they can
    differentiate messaging based on what's missing:
    - missing_fundamentals: bool
    - missing_advanced: bool
    - missing_both: bool (both missing)
    - completed_fundamentals: bool (fundamentals done, only advanced left)
    - nice_to_have_trainings: list of trainings that are optional (e.g. Fundamentals when Advanced is done)
    - has_nice_to_have: bool

    Returns:
        dict with recipient_email, subject, body, stage.
    """
    template_path = get_template_for_stage(stage, config)
    if nice_to_have_trainings is None:
        nice_to_have_trainings = []

    template_content = load_template(template_path)

    # Split template into subject and body (first line is subject)
    lines = template_content.strip().split("\n", 1)
    subject_template = lines[0].replace("Subject: ", "").strip()
    body_template = lines[1].strip() if len(lines) > 1 else ""

    missing_str = ", ".join(missing_trainings)

    # Build structured gap info for template branching
    missing_lower = [m.lower() for m in missing_trainings]
    missing_fundamentals = "fundamentals" in missing_lower
    missing_advanced = "advanced" in missing_lower
    missing_both = missing_fundamentals and missing_advanced
    completed_fundamentals = missing_advanced and not missing_fundamentals

    template_vars = {
        "name": name,
        "missing_trainings": missing_str,
        "stage": stage,
        "missing_fundamentals": missing_fundamentals,
        "missing_advanced": missing_advanced,
        "missing_both": missing_both,
        "completed_fundamentals": completed_fundamentals,
        "nice_to_have_trainings": nice_to_have_trainings,
        "has_nice_to_have": len(nice_to_have_trainings) > 0,
    }

    # Render with Jinja2
    subject = Template(subject_template).render(**template_vars)
    body = Template(body_template).render(**template_vars)

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
        nice_to_have = pm.get("nice_to_have_trainings", [])

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
        reminder = render_reminder(name, email, missing, stage, config, nice_to_have)

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


def _was_pm_previously_reminded_itpm(pm_email, db):
    """Check if a PM was already sent a missing IT PM reminder in a previous cycle."""
    from src.normalizer import normalize_email
    norm_email = normalize_email(pm_email)
    pm_id = db.get_project_manager_id(email=norm_email)
    if not pm_id:
        return False
    # Stage 0 = missing IT PM reminder
    row = db.conn.execute(
        "SELECT COUNT(*) as cnt FROM communication_history WHERE project_manager_id = ? AND reminder_stage = 0",
        (pm_id,),
    ).fetchone()
    return row["cnt"] > 0


def generate_missing_itpm_reminders(missing_itpm_list, db, cycle_id, config):
    """Generate reminders for missing IT PM assignments with escalation.

    Logic:
    - If PM was NOT previously reminded about missing IT PM → send reminder to PM
    - If PM WAS already reminded in a previous cycle and IT PM is still empty →
      escalate to Project Owner asking them to coordinate IT PM assignment

    Args:
        missing_itpm_list: List of dicts from find_projects_missing_it_pm().
        db: Database instance.
        cycle_id: Current cycle ID.
        config: Application configuration.

    Returns:
        (pm_reminders, escalation_reminders) tuple of reminder lists.
    """
    from src.normalizer import normalize_name

    pm_template_path = config["templates"].get("missing_itpm")
    escalation_template_path = config["templates"].get("missing_itpm_escalation")

    pm_reminders = []
    escalation_reminders = []

    for item in missing_itpm_list:
        pm_name = item["pm_name"]
        pm_email = item["pm_email"]
        projects = item["projects"]

        project_list_str = ", ".join(
            f"{p['project_name']} ({p['project_id']})" for p in projects
        )

        previously_reminded = _was_pm_previously_reminded_itpm(pm_email, db)

        if not previously_reminded:
            # First time: send reminder to PM
            if pm_template_path:
                template_content = load_template(pm_template_path)
                lines = template_content.strip().split("\n", 1)
                subject_tpl = lines[0].replace("Subject: ", "").strip()
                body_tpl = lines[1].strip() if len(lines) > 1 else ""
                subject = Template(subject_tpl).render(pm_name=pm_name, projects=projects)
                body = Template(body_tpl).render(pm_name=pm_name, projects=projects)
            else:
                subject = "Action Requested: Please Assign an IT Project Manager"
                body = f"Dear {pm_name},\n\nPlease assign an IT PM for your projects.\n"

            reminder = {
                "recipient_email": pm_email,
                "subject": subject,
                "body": body,
                "stage": 0,
                "name": pm_name,
                "missing_trainings": [],
                "reminder_type": "missing_itpm",
                "projects": projects,
                "project_list": project_list_str,
            }

            norm_name = normalize_name(pm_name)
            pm_id = db.upsert_project_manager(pm_name, pm_email, norm_name)
            db.insert_communication(cycle_id, pm_id, 0, subject, body, status="prepared")

            pm_reminders.append(reminder)
            logger.debug("Missing IT PM reminder (first) for %s <%s>", pm_name, pm_email)

        else:
            # Escalation: PM was already reminded, escalate to Project Owner
            # Group projects by owner for this PM
            owner_projects = {}
            no_owner_projects = []

            for proj in projects:
                owner_name = proj.get("owner_name")
                owner_email = proj.get("owner_email")

                if owner_name and owner_email:
                    key = owner_email.lower().strip()
                    if key not in owner_projects:
                        owner_projects[key] = {
                            "owner_name": owner_name,
                            "owner_email": owner_email,
                            "projects": [],
                            "pm_name": pm_name,
                            "pm_email": pm_email,
                        }
                    owner_projects[key]["projects"].append(proj)
                else:
                    no_owner_projects.append(proj)

            # Generate escalation for each owner
            for owner_data in owner_projects.values():
                owner_name = owner_data["owner_name"]
                owner_email = owner_data["owner_email"]
                owner_projs = owner_data["projects"]

                owner_project_list_str = ", ".join(
                    f"{p['project_name']} ({p['project_id']})" for p in owner_projs
                )

                if escalation_template_path:
                    template_content = load_template(escalation_template_path)
                    lines = template_content.strip().split("\n", 1)
                    subject_tpl = lines[0].replace("Subject: ", "").strip()
                    body_tpl = lines[1].strip() if len(lines) > 1 else ""
                    subject = Template(subject_tpl).render(
                        owner_name=owner_name, pm_name=pm_name,
                        pm_email=pm_email, projects=owner_projs,
                    )
                    body = Template(body_tpl).render(
                        owner_name=owner_name, pm_name=pm_name,
                        pm_email=pm_email, projects=owner_projs,
                    )
                else:
                    subject = f"Escalation: IT Project Manager Still Missing for Your Project(s)"
                    body = (
                        f"Dear {owner_name},\n\n"
                        f"The Project Manager ({pm_name}) was previously asked to assign "
                        f"an IT PM but has not yet done so.\n"
                        f"Please coordinate with them.\n"
                    )

                escalation = {
                    "recipient_email": owner_email,
                    "subject": subject,
                    "body": body,
                    "stage": -1,  # Stage -1 = escalation to owner
                    "name": owner_name,
                    "missing_trainings": [],
                    "reminder_type": "missing_itpm_escalation",
                    "projects": owner_projs,
                    "project_list": owner_project_list_str,
                    "pm_name": pm_name,
                    "pm_email": pm_email,
                }

                norm_name = normalize_name(owner_name)
                owner_id = db.upsert_project_manager(owner_name, owner_email, norm_name)
                db.insert_communication(
                    cycle_id, owner_id, -1, subject, body, status="prepared"
                )

                escalation_reminders.append(escalation)
                logger.debug(
                    "Escalation to owner %s <%s> for PM %s (%d projects)",
                    owner_name, owner_email, pm_name, len(owner_projs),
                )

            # Log data quality issue for projects with no owner
            if no_owner_projects:
                for proj in no_owner_projects:
                    db.insert_data_quality_issue(
                        cycle_id, "missing_owner_for_escalation",
                        pm_name, pm_email,
                        f"Project '{proj['project_name']}' ({proj['project_id']}) has no "
                        f"Project Owner for IT PM escalation. PM was already reminded.",
                    )

            # Also re-remind the PM (they still need to act)
            if pm_template_path:
                template_content = load_template(pm_template_path)
                lines = template_content.strip().split("\n", 1)
                subject_tpl = lines[0].replace("Subject: ", "").strip()
                body_tpl = lines[1].strip() if len(lines) > 1 else ""
                subject = Template(subject_tpl).render(pm_name=pm_name, projects=projects)
                body = Template(body_tpl).render(pm_name=pm_name, projects=projects)
            else:
                subject = "Action Requested: Please Assign an IT Project Manager"
                body = f"Dear {pm_name},\n\nPlease assign an IT PM for your projects.\n"

            reminder = {
                "recipient_email": pm_email,
                "subject": subject,
                "body": body,
                "stage": 0,
                "name": pm_name,
                "missing_trainings": [],
                "reminder_type": "missing_itpm",
                "projects": projects,
                "project_list": project_list_str,
            }

            norm_name = normalize_name(pm_name)
            pm_id = db.upsert_project_manager(pm_name, pm_email, norm_name)
            db.insert_communication(cycle_id, pm_id, 0, subject, body, status="prepared")

            pm_reminders.append(reminder)
            logger.debug("Missing IT PM reminder (repeat + escalated) for %s <%s>", pm_name, pm_email)

    logger.info(
        "Missing IT PM: %d PM reminders, %d escalations to Project Owners",
        len(pm_reminders),
        len(escalation_reminders),
    )

    return pm_reminders, escalation_reminders


def generate_role_changed_reminders(role_changed_list, db, cycle_id, config):
    """Generate reminders for PMs whose projects have an IT PM who changed roles.

    Args:
        role_changed_list: List from find_role_changed_it_pms().
        db: Database instance.
        cycle_id: Current cycle ID.
        config: Application configuration.

    Returns:
        List of reminder dicts.
    """
    from src.normalizer import normalize_name

    template_path = config["templates"].get("role_changed_itpm")
    reminders = []

    for item in role_changed_list:
        pm_name = item["pm_name"]
        pm_email = item["pm_email"]
        projects = item["projects"]

        if template_path:
            template_content = load_template(template_path)
            lines = template_content.strip().split("\n", 1)
            subject_tpl = lines[0].replace("Subject: ", "").strip()
            body_tpl = lines[1].strip() if len(lines) > 1 else ""
            subject = Template(subject_tpl).render(pm_name=pm_name, projects=projects)
            body = Template(body_tpl).render(pm_name=pm_name, projects=projects)
        else:
            subject = "Action Needed: IT PM Allocation Update Required in ePPM"
            body = f"Dear {pm_name},\n\nSome IT PMs on your projects have changed roles.\n"

        project_list_str = ", ".join(
            f"{p['project_name']} ({p['project_id']}) - {p['it_pm_name']} now {p['current_position']}"
            for p in projects
        )

        reminder = {
            "recipient_email": pm_email,
            "subject": subject,
            "body": body,
            "stage": 0,
            "name": pm_name,
            "missing_trainings": [],
            "reminder_type": "role_changed_itpm",
            "projects": projects,
            "project_list": project_list_str,
        }

        norm_name = normalize_name(pm_name)
        pm_id = db.upsert_project_manager(pm_name, pm_email, norm_name)
        db.insert_communication(cycle_id, pm_id, -2, subject, body, status="prepared")

        reminders.append(reminder)
        logger.debug(
            "Role-changed IT PM reminder for %s <%s> (%d projects)",
            pm_name, pm_email, len(projects),
        )

    logger.info("Generated %d role-changed IT PM reminders", len(reminders))
    return reminders
