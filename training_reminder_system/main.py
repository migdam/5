#!/usr/bin/env python3
"""Training Reminder System - Main Entry Point.

Processes ePPM assignment and Fuse training Excel files to identify
IT Project Managers who need training reminders. Generates email-ready
output files for manual sending.
"""
import sys
import os
import logging
from datetime import datetime

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config_loader import load_config
from src.utils import setup_logging
from src.repository import Database
from src.file_loader import load_eppm, load_training, load_role_changes, load_excluded_projects, InputValidationError
from src.normalizer import extract_unique_pms, normalize_name, normalize_email
from src.matcher import match_people
from src.evaluator import evaluate_training, get_eligible_pms, find_projects_missing_it_pm, find_role_changed_it_pms, filter_ghost_projects, extract_pm_compliance_issues
from src.communication import generate_reminders, generate_missing_itpm_reminders, generate_role_changed_reminders
from src.reporting import generate_outputs
from src.archiver import archive_files

logger = logging.getLogger(__name__)


def run_cycle(config_path="config.yaml"):
    """Execute a single processing cycle."""
    # Load configuration
    config = load_config(config_path)

    # Setup logging
    log_file = setup_logging(config["paths"]["log_folder"])

    logger.info("=" * 60)
    logger.info("TRAINING REMINDER SYSTEM - Starting new cycle")
    logger.info("=" * 60)

    # Initialize database
    db = Database(config["paths"]["database"])
    cycle_id = db.start_cycle()
    cycle_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Cycle %d started at %s", cycle_id, cycle_start)

    try:
        # --- Step 1: Load Excel files ---
        logger.info("Step 1: Loading input files")
        eppm_df, eppm_path = load_eppm(config)
        training_df, training_path = load_training(config)
        input_files = [("eppm", eppm_path), ("fuse", training_path)]

        # --- Step 1b: Load optional excluded projects list ---
        excluded_projects_df, excluded_projects_path = load_excluded_projects(config)
        if excluded_projects_path:
            input_files.append(("excluded_projects", excluded_projects_path))

        # --- Step 1c: Filter out ghost projects ---
        logger.info("Step 1c: Filtering ghost projects (completed, cancelled, excluded)")
        eppm_df, ghost_count, ghost_details = filter_ghost_projects(
            eppm_df, excluded_projects_df, config
        )

        # --- Step 1d: Extract per-PM compliance issues ---
        logger.info("Step 1d: Extracting compliance issues per PM")
        pm_compliance_issues = extract_pm_compliance_issues(eppm_df)

        # --- Step 2: Extract unique PMs from ePPM ---
        logger.info("Step 2: Extracting unique PMs from ePPM")
        unique_pms, all_pms_df = extract_unique_pms(eppm_df)

        if unique_pms.empty:
            logger.warning("No PMs found in ePPM data. Ending cycle.")
            db.complete_cycle(cycle_id, "completed", "No PMs found")
            db.close()
            return

        # Store PMs and assignment snapshots in database
        logger.info("Storing %d PMs and %d assignment records in database", len(unique_pms), len(all_pms_df))
        eppm_filename = os.path.basename(eppm_path)
        for _, pm_row in unique_pms.iterrows():
            pm_id = db.upsert_project_manager(
                pm_row["full_name"],
                pm_row["email"],
                pm_row["normalized_name"],
            )

        # Store assignment snapshots
        snapshot_count = 0
        for _, row in all_pms_df.iterrows():
            pm_id = db.get_project_manager_id(
                email=normalize_email(row["email"]) if row.get("email") else None,
                normalized_name=row.get("normalized_name", ""),
            )
            if pm_id:
                db.insert_assignment_snapshot(
                    cycle_id, pm_id,
                    row.get("project_name", ""),
                    row.get("project_id", ""),
                    row.get("project_status", ""),
                    eppm_filename,
                )
                snapshot_count += 1
        logger.info("Stored %d assignment snapshots", snapshot_count)

        # --- Step 3: Match PMs against training records ---
        logger.info("Step 3: Matching PMs against training records")
        matched_pms, unmatched_pms, unmatched_training = match_people(
            unique_pms, training_df, config
        )

        # Log unmatched records as data quality issues
        for pm in unmatched_pms:
            db.insert_data_quality_issue(
                cycle_id, "unmatched_pm", pm["full_name"], pm.get("email"),
                f"PM '{pm['full_name']}' could not be matched to any training record."
            )

        # --- Step 4: Evaluate training ---
        logger.info("Step 4: Evaluating training completion")
        evaluated_pms = evaluate_training(matched_pms, training_df, config)

        # --- Step 5: Determine eligible PMs ---
        logger.info("Step 5: Determining eligible PMs for reminders")
        eligible_pms, skipped_complete, skipped_inactive, nice_to_have_pms = get_eligible_pms(
            evaluated_pms, all_pms_df, config
        )

        # Store training snapshots with full audit trail
        # (after eligibility so eligibility_status is set on each PM)
        logger.info("Storing %d training snapshots with audit fields in database", len(evaluated_pms))
        training_filename = os.path.basename(training_path)
        for pm in evaluated_pms:
            pm_id = db.get_project_manager_id(
                email=normalize_email(pm["email"]) if pm.get("email") else None,
                normalized_name=pm.get("normalized_name", ""),
            )
            if pm_id:
                overall = "complete" if pm["all_complete"] else "incomplete"
                pm_email_key = pm["email"].lower().strip() if pm.get("email") else ""
                compliance = pm_compliance_issues.get(pm_email_key, [])
                db.insert_training_snapshot(
                    cycle_id, pm_id,
                    "completed" if pm.get("fundamentals_completed") else "incomplete",
                    "completed" if pm.get("advanced_completed") else "incomplete",
                    str(pm.get("fundamentals_date", "")) if pm.get("fundamentals_date") else None,
                    str(pm.get("advanced_date", "")) if pm.get("advanced_date") else None,
                    overall,
                    training_filename,
                    match_method=pm.get("match_method"),
                    missing_trainings=pm.get("missing_trainings", []),
                    nice_to_have_trainings=pm.get("nice_to_have_trainings", []),
                    compliance_issues_json=compliance if compliance else None,
                    eligibility_status=pm.get("eligibility_status", "unknown"),
                )

        # --- Step 6: Generate training reminders ---
        logger.info("Step 6: Generating training reminders")
        reminders, skipped_no_email = generate_reminders(
            eligible_pms, db, cycle_id, config, pm_compliance_issues
        )

        # --- Step 6b: Find projects missing IT PM and generate reminders ---
        logger.info("Step 6b: Checking for active projects without IT PM")
        missing_itpm_list = find_projects_missing_it_pm(eppm_df, config)
        missing_itpm_reminders, escalation_reminders = generate_missing_itpm_reminders(
            missing_itpm_list, db, cycle_id, config
        )

        # --- Step 6c: Find IT PMs who changed roles (from manual CSV) ---
        logger.info("Step 6c: Checking for IT PMs who changed roles")
        role_changes_df, role_changes_path = load_role_changes(config)
        if role_changes_path:
            input_files.append(("role_changes", role_changes_path))
        role_changed_list = find_role_changed_it_pms(eppm_df, role_changes_df, config)
        role_changed_reminders = generate_role_changed_reminders(
            role_changed_list, db, cycle_id, config
        )

        # --- Step 7: Generate output files ---
        logger.info("Step 7: Generating output files")
        missing_itpm_project_count = sum(len(m["projects"]) for m in missing_itpm_list)
        role_changed_project_count = sum(len(g["projects"]) for g in role_changed_list)
        summary_data = {
            "cycle_id": cycle_id,
            "cycle_started_at": cycle_start,
            "ghost_projects_filtered": ghost_count,
            "ghost_by_status": ghost_details.get("excluded_status", 0),
            "ghost_by_stage": ghost_details.get("completed_stage", 0),
            "ghost_by_manual_list": ghost_details.get("manual_exclusion", 0),
            "total_pms_in_eppm": len(unique_pms),
            "total_pm_assignments": len(all_pms_df),
            "matched_pms": len(matched_pms),
            "unmatched_pms": len(unmatched_pms),
            "pms_training_complete": skipped_complete,
            "pms_nice_to_have_only": len(nice_to_have_pms),
            "pms_inactive_projects": skipped_inactive,
            "pms_eligible_for_reminder": len(eligible_pms),
            "training_reminders_generated": len(reminders),
            "skipped_no_email": skipped_no_email,
            "unmatched_training_people": len(unmatched_training),
            "projects_missing_it_pm": missing_itpm_project_count,
            "missing_itpm_reminders_to_pm": len(missing_itpm_reminders),
            "missing_itpm_escalations_to_owner": len(escalation_reminders),
            "role_changed_itpm_projects": role_changed_project_count,
            "role_changed_itpm_reminders": len(role_changed_reminders),
        }

        output_dir = generate_outputs(
            reminders, summary_data, config, cycle_id,
            missing_itpm_reminders=missing_itpm_reminders,
            escalation_reminders=escalation_reminders,
            role_changed_reminders=role_changed_reminders,
            nice_to_have_pms=nice_to_have_pms,
        )

        # --- Step 8: Archive input files ---
        logger.info("Step 8: Archiving processed files")
        archive_files(input_files, config, cycle_id, db)

        # --- Complete cycle ---
        notes = (
            f"Generated {len(reminders)} training reminders, "
            f"{len(missing_itpm_reminders)} IT PM reminders to PMs, "
            f"{len(escalation_reminders)} escalations to owners, "
            f"{len(role_changed_reminders)} role-change alerts. Output: {output_dir}"
        )
        db.complete_cycle(cycle_id, "completed", notes)

        # Print summary
        print("\n" + "=" * 60)
        print("TRAINING REMINDER SYSTEM - Cycle Complete")
        print("=" * 60)
        for key, value in summary_data.items():
            label = key.replace("_", " ").title()
            print(f"  {label}: {value}")
        print(f"\n  Output folder: {output_dir}")
        print("=" * 60 + "\n")

        logger.info("Cycle %d completed successfully", cycle_id)

    except InputValidationError as e:
        logger.error("Cycle %d REVERTED — invalid input file: %s", cycle_id, str(e))
        print(f"\n{'!'*60}")
        print(f"CYCLE REVERTED — Invalid input file detected")
        print(f"{'!'*60}")
        print(f"\n{str(e)}")
        print(f"\nCycle {cycle_id} has been fully reverted. No data was saved.")
        print(f"Please fix the input file and re-run.\n")
        db.revert_cycle(cycle_id)
        return None

    except Exception as e:
        logger.error("Cycle %d failed: %s", cycle_id, str(e), exc_info=True)
        db.complete_cycle(cycle_id, "failed", str(e))
        raise
    finally:
        db.close()

    return summary_data


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_cycle(config_path)
