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

        # Get Project Owner for possible escalation
        owner_name = row.get("project_owner")
        owner_email = row.get("project_owner_email")
        has_owner = (
            owner_name and str(owner_name) not in ("", "None", "nan")
            and owner_email and str(owner_email) not in ("", "None", "nan")
        )

        missing_itpm_projects.append({
            "project_name": str(project_name) if project_name else "",
            "project_id": str(project_id) if project_id else "",
            "pm_name": str(pm_name),
            "pm_email": str(pm_email),
            "owner_name": str(owner_name) if has_owner else None,
            "owner_email": str(owner_email) if has_owner else None,
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
            "owner_name": item["owner_name"],
            "owner_email": item["owner_email"],
        })

    result = list(pm_projects.values())
    total_projects = sum(len(p["projects"]) for p in result)
    logger.info(
        "Missing IT PM: %d active projects without IT PM, affecting %d PMs",
        total_projects,
        len(result),
    )

    return result


def find_role_changed_it_pms(eppm_df, role_changes_df, config):
    """Find IT PMs in ePPM who have changed roles according to a manually maintained list.

    The role_changes_df comes from a CSV file that is updated by users based on
    feedback from people. When an IT PM changes roles, their details are added
    to this file. The system then flags active projects where that person is
    still assigned as IT PM.

    Args:
        eppm_df: ePPM DataFrame with mapped column names.
        role_changes_df: DataFrame from role_changes.xlsx, or None if not provided.
        config: Application configuration.

    Returns:
        List of dicts grouped by PM responsible, with affected projects and
        the IT PM who changed roles.
    """
    if role_changes_df is None or role_changes_df.empty:
        logger.info("No role changes data provided — skipping role-change detection")
        return []

    from src.normalizer import normalize_email

    active_statuses = [s.lower() for s in config["status_mapping"]["project_active_statuses"]]

    # Build lookup from role_changes CSV: normalized_email -> {name, new_role}
    role_changed_lookup = {}
    for _, row in role_changes_df.iterrows():
        email = row.get("it_pm_email")
        if not email or str(email) in ("", "None", "nan"):
            continue
        norm_email = normalize_email(str(email))
        role_changed_lookup[norm_email] = {
            "name": str(row.get("it_pm_name", "")) if row.get("it_pm_name") else "",
            "new_role": str(row.get("new_role", "")) if row.get("new_role") else "Unknown",
        }

    if not role_changed_lookup:
        logger.info("Role changes CSV is empty — no role changes to process")
        return []

    logger.info("Loaded %d role-changed IT PMs from CSV", len(role_changed_lookup))

    # Scan ePPM for active projects with IT PMs in the role-changed list
    role_changed = []

    for _, row in eppm_df.iterrows():
        project_status = str(row.get("project_status", "")).lower().strip()
        if project_status not in active_statuses:
            continue

        it_pm_name = row.get("it_project_manager")
        it_pm_email = row.get("it_project_manager_email")
        if not it_pm_name or str(it_pm_name) in ("", "None", "nan"):
            continue
        if not it_pm_email or str(it_pm_email) in ("", "None", "nan"):
            continue

        norm_itpm_email = normalize_email(str(it_pm_email))
        change_info = role_changed_lookup.get(norm_itpm_email)

        if not change_info:
            continue  # This IT PM is not in the role-changed list

        pm_name = row.get("project_manager")
        pm_email = row.get("project_manager_email")
        owner_name = row.get("project_owner")
        owner_email = row.get("project_owner_email")

        role_changed.append({
            "project_name": str(row.get("project_name", "")),
            "project_id": str(row.get("project_number", "")),
            "it_pm_name": str(it_pm_name),
            "it_pm_email": str(it_pm_email),
            "current_position": change_info["new_role"],
            "pm_name": str(pm_name) if pm_name and str(pm_name) not in ("", "None", "nan") else None,
            "pm_email": str(pm_email) if pm_email and str(pm_email) not in ("", "None", "nan") else None,
            "owner_name": str(owner_name) if owner_name and str(owner_name) not in ("", "None", "nan") else None,
            "owner_email": str(owner_email) if owner_email and str(owner_email) not in ("", "None", "nan") else None,
        })

    # Group by PM email (the PM is who should update ePPM)
    pm_groups = {}
    for item in role_changed:
        pm_email = item["pm_email"]
        if not pm_email:
            continue
        key = pm_email.lower().strip()
        if key not in pm_groups:
            pm_groups[key] = {
                "pm_name": item["pm_name"],
                "pm_email": item["pm_email"],
                "projects": [],
            }
        pm_groups[key]["projects"].append({
            "project_name": item["project_name"],
            "project_id": item["project_id"],
            "it_pm_name": item["it_pm_name"],
            "it_pm_email": item["it_pm_email"],
            "current_position": item["current_position"],
            "owner_name": item["owner_name"],
            "owner_email": item["owner_email"],
        })

    result = list(pm_groups.values())
    total = sum(len(g["projects"]) for g in result)
    logger.info(
        "Role-changed IT PMs: %d projects with IT PM who changed role, affecting %d PMs",
        total, len(result),
    )
    return result
