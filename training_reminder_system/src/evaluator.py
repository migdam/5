import logging
import pandas as pd

logger = logging.getLogger(__name__)


def evaluate_training(matched_pms, training_df, config):
    """Evaluate training completion for each matched PM.

    For each PM, checks their training records to determine which required
    courses are completed and which are still missing.

    Args:
        matched_pms: List of matched PM dicts from matcher (with training_indices).
        training_df: Full Fuse training DataFrame.
        config: Application configuration.

    Returns:
        List of dicts with PM info + training evaluation results.
    """
    required = config["required_training"]
    completed_values = [v.lower() for v in config["status_mapping"]["training_completed_values"]]

    evaluated = []

    for pm in matched_pms:
        t_indices = pm["training_indices"]
        pm_training = training_df.iloc[t_indices]

        result = {
            "full_name": pm["full_name"],
            "email": pm["email"],
            "normalized_name": pm["normalized_name"],
            "normalized_email": pm["normalized_email"],
            "match_method": pm["match_method"],
        }

        missing = []
        for key, req in required.items():
            content_title = req["content_title"]
            label = req["label"]

            # Find records for this course
            course_records = pm_training[
                pm_training["content_title"].astype(str).str.strip() == content_title
            ]

            # Check if any record shows completed
            is_completed = False
            completion_date = None
            if not course_records.empty:
                for _, rec in course_records.iterrows():
                    status = str(rec.get("course_status", "")).lower().strip()
                    if status in completed_values:
                        is_completed = True
                        completion_date = rec.get("completion_date")
                        break

            result[f"{key}_completed"] = is_completed
            result[f"{key}_date"] = completion_date
            if not is_completed:
                missing.append(label)

        result["missing_trainings"] = missing
        result["all_complete"] = len(missing) == 0

        evaluated.append(result)

    completed_count = sum(1 for e in evaluated if e["all_complete"])
    incomplete_count = len(evaluated) - completed_count
    logger.info(
        "Training evaluation: %d PMs evaluated, %d fully complete, %d with gaps",
        len(evaluated),
        completed_count,
        incomplete_count,
    )

    return evaluated


def get_eligible_pms(evaluated_pms, all_pms_df, config):
    """Filter to PMs who are assigned to active projects and have incomplete training.

    Args:
        evaluated_pms: List of evaluated PM dicts.
        all_pms_df: Full PM assignment records (with project_status).
        config: Application configuration.

    Returns:
        List of eligible PM dicts (those needing reminders).
    """
    active_statuses = [s.lower() for s in config["status_mapping"]["project_active_statuses"]]

    # Build set of PMs who have at least one active project
    active_pm_emails = set()
    active_pm_names = set()

    for _, row in all_pms_df.iterrows():
        status = str(row.get("project_status", "")).lower().strip()
        if status in active_statuses:
            email = row.get("email")
            if email and str(email) not in ("", "None", "nan"):
                active_pm_emails.add(str(email).lower().strip())
            name = row.get("normalized_name", "")
            if name:
                active_pm_names.add(name)

    eligible = []
    skipped_complete = 0
    skipped_inactive = 0

    for pm in evaluated_pms:
        # Check if PM is on an active project
        email = pm.get("normalized_email", "")
        name = pm.get("normalized_name", "")
        is_active = email in active_pm_emails or name in active_pm_names

        if not is_active:
            skipped_inactive += 1
            continue

        if pm["all_complete"]:
            skipped_complete += 1
            continue

        eligible.append(pm)

    logger.info(
        "Eligibility: %d eligible for reminders, %d completed (skipped), %d inactive (skipped)",
        len(eligible),
        skipped_complete,
        skipped_inactive,
    )

    return eligible, skipped_complete, skipped_inactive


def find_projects_missing_it_pm(eppm_df, config):
    """Find active projects that have no IT Project Manager assigned.

    For each such project, the Project Manager should be reminded to
    update the IT PM field in ePPM.

    Args:
        eppm_df: ePPM DataFrame with mapped column names.
        config: Application configuration.

    Returns:
        List of dicts with project info and PM contact details.
    """
    active_statuses = [s.lower() for s in config["status_mapping"]["project_active_statuses"]]
    missing_itpm_projects = []

    for _, row in eppm_df.iterrows():
        project_status = str(row.get("project_status", "")).lower().strip()
        if project_status not in active_statuses:
            continue

        # Check if IT Project Manager is missing
        it_pm = row.get("it_project_manager")
        it_pm_email = row.get("it_project_manager_email")
        has_it_pm = (
            it_pm and str(it_pm) not in ("", "None", "nan")
            and it_pm_email and str(it_pm_email) not in ("", "None", "nan")
        )

        if has_it_pm:
            continue

        # Get the Project Manager who should be notified
        pm_name = row.get("project_manager")
        pm_email = row.get("project_manager_email")

        if not pm_name or str(pm_name) in ("", "None", "nan"):
            continue
        if not pm_email or str(pm_email) in ("", "None", "nan"):
            continue

        project_name = row.get("project_name", "")
        project_id = row.get("project_number", "")

        missing_itpm_projects.append({
            "project_name": str(project_name) if project_name else "",
            "project_id": str(project_id) if project_id else "",
            "pm_name": str(pm_name),
            "pm_email": str(pm_email),
        })

    # Deduplicate: group projects by PM email
    pm_projects = {}
    for item in missing_itpm_projects:
        email = item["pm_email"].lower().strip()
        if email not in pm_projects:
            pm_projects[email] = {
                "pm_name": item["pm_name"],
                "pm_email": item["pm_email"],
                "projects": [],
            }
        pm_projects[email]["projects"].append({
            "project_name": item["project_name"],
            "project_id": item["project_id"],
        })

    result = list(pm_projects.values())
    total_projects = sum(len(p["projects"]) for p in result)
    logger.info(
        "Missing IT PM: %d active projects without IT PM, affecting %d PMs",
        total_projects,
        len(result),
    )

    return result
