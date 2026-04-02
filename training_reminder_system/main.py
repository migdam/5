#!/usr/bin/env python3
##############################################################################
# main.py — Training Reminder System: Main Orchestration Pipeline
#
# This is the entry point for the entire system. Running "python main.py"
# executes one complete processing cycle:
#
#   1. Load input files (ePPM projects + Fuse training records)
#   2. Filter out ghost/cancelled projects
#   3. Extract compliance issues from projects (used as motivators in emails)
#   4. Extract unique Project Managers from ePPM
#   5. Match PMs against Fuse training records (4-pass matching)
#   6. Evaluate training completion for each matched PM
#   7. Determine which PMs are eligible for reminders
#   8. Generate training reminders (progressive stages, bi-weekly after S3)
#   9. Generate congratulations for newly certified PMs
#  10. Generate missing IT PM reminders + escalations to Project Owners
#  11. Generate role-change alerts
#  12. Write all output files (per-recipient, per-stage, group, comms plan)
#  13. Archive processed input files
#
# ERROR HANDLING STRATEGY:
#   - InputValidationError (bad input file): REVERT the cycle entirely.
#     No data is saved, no reminders generated. The user fixes the file
#     and re-runs. This prevents sending incorrect reminders.
#   - Any other error: Mark the cycle as "failed" in the database but
#     keep whatever data was stored (for debugging). Re-raise the error.
#
# AUDIT TRAIL:
#   Every decision is recorded in the SQLite database:
#   - assignment_snapshots: which projects each PM is on
#   - training_snapshots: training status + match method + eligibility + compliance
#   - communication_history: every reminder prepared (with full email content)
#   - data_quality_issues: unmatched PMs, missing emails, etc.
##############################################################################

import sys
import os
import logging
from datetime import datetime

# Ensure project root is on the path so "from src.xxx import yyy" works
# regardless of where the script is called from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.config_loader import load_config
from src.utils import setup_logging
from src.repository import Database
from src.file_loader import load_eppm, load_training, load_role_changes, load_excluded_projects, load_identity_aliases, InputValidationError
from src.normalizer import extract_unique_pms, normalize_name, normalize_email
from src.matcher import match_people
from src.evaluator import evaluate_training, get_eligible_pms, find_projects_missing_it_pm, find_role_changed_it_pms, filter_ghost_projects, extract_pm_compliance_issues
from src.communication import generate_reminders, generate_missing_itpm_reminders, generate_role_changed_reminders, generate_congratulations
from src.reporting import generate_outputs
from src.archiver import archive_files

logger = logging.getLogger(__name__)


def run_cycle(config_path="config.yaml"):
    """Execute a single processing cycle.

    This is the main function that orchestrates the entire pipeline.
    It can be called directly (python main.py) or programmatically
    from run_simulation.py for multi-cycle testing.

    Args:
        config_path: Path to config.yaml (default: "config.yaml").

    Returns:
        dict: Summary data with counts (reminders generated, PMs matched, etc.)
        None: If the cycle was reverted due to invalid input.
    """
    # ===================================================================
    # INITIALIZATION
    # ===================================================================
    config = load_config(config_path)
    log_file = setup_logging(config["paths"]["log_folder"])

    logger.info("=" * 60)
    logger.info("TRAINING REMINDER SYSTEM - Starting new cycle")
    logger.info("=" * 60)

    # Start a new cycle in the database. This records the timestamp and
    # gives us a cycle_id that links all data from this run together.
    db = Database(config["paths"]["database"])
    cycle_id = db.start_cycle()
    cycle_start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info("Cycle %d started at %s", cycle_id, cycle_start)

    try:
        # ===============================================================
        # STEP 1: Load all input files
        # ===============================================================
        # Two files are REQUIRED (ePPM + Fuse). Three are OPTIONAL
        # (excluded_projects, identity_aliases, role_changes).
        # If a required file fails validation, InputValidationError is
        # raised and the cycle is reverted (see except block below).
        logger.info("Step 1: Loading input files")
        eppm_df, eppm_path = load_eppm(config)
        training_df, training_path = load_training(config)
        input_files = [("eppm", eppm_path), ("fuse", training_path)]

        # Optional: manually maintained list of ghost/cancelled projects
        excluded_projects_df, excluded_projects_path = load_excluded_projects(config)
        if excluded_projects_path:
            input_files.append(("excluded_projects", excluded_projects_path))

        # Optional: identity aliases for maiden names, email domain changes
        aliases_df, aliases_path = load_identity_aliases(config)
        if aliases_path:
            input_files.append(("identity_aliases", aliases_path))

        # ===============================================================
        # STEP 1c: Filter out ghost projects
        # ===============================================================
        # Ghost projects are completed, cancelled, or on-hold projects
        # that still appear in the ePPM extract. They should not trigger
        # training reminders. Three filtering mechanisms:
        #   1. Status-based: "Completed", "Cancelled", "On Hold"
        #   2. Stage-based: Active Stage = "Completed"
        #   3. Manual exclusion: listed in excluded_projects.xlsx
        logger.info("Step 1c: Filtering ghost projects (completed, cancelled, excluded)")
        eppm_df, ghost_count, ghost_details = filter_ghost_projects(
            eppm_df, excluded_projects_df, config
        )

        # ===============================================================
        # STEP 1d: Extract compliance issues per PM
        # ===============================================================
        # Scan each project's G0/G3/G5/G6 compliance columns to find
        # non-compliant or partially compliant gates. These are used later
        # as personalized motivators in training reminders — showing PMs
        # exactly why the training matters for THEIR specific projects.
        logger.info("Step 1d: Extracting compliance issues per PM")
        pm_compliance_issues = extract_pm_compliance_issues(eppm_df)

        # ===============================================================
        # STEP 2: Extract unique PMs from ePPM
        # ===============================================================
        # A PM may appear on many projects and in multiple roles (PM + IT PM).
        # We deduplicate to get one entry per unique person (for matching),
        # while preserving all project assignments (for reminder content).
        logger.info("Step 2: Extracting unique PMs from ePPM")
        unique_pms, all_pms_df = extract_unique_pms(eppm_df)

        if unique_pms.empty:
            logger.warning("No PMs found in ePPM data. Ending cycle.")
            db.complete_cycle(cycle_id, "completed", "No PMs found")
            db.close()
            return

        # Store all PM identities and their project assignments in the DB.
        # This creates the audit trail of who was assigned to what.
        logger.info("Storing %d PMs and %d assignment records in database", len(unique_pms), len(all_pms_df))
        eppm_filename = os.path.basename(eppm_path)
        for _, pm_row in unique_pms.iterrows():
            pm_id = db.upsert_project_manager(
                pm_row["full_name"],
                pm_row["email"],
                pm_row["normalized_name"],
            )

        # Store one assignment snapshot per PM-project combination.
        # This records which projects each PM was assigned to in THIS cycle.
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

        # ===============================================================
        # STEP 3: Match PMs against training records
        # ===============================================================
        # The 4-pass matching engine links ePPM PMs to their Fuse training
        # records using: aliases → email → exact name → normalized name.
        # Unmatched PMs are logged as data quality issues.
        logger.info("Step 3: Matching PMs against training records")
        matched_pms, unmatched_pms, unmatched_training = match_people(
            unique_pms, training_df, config, aliases_df=aliases_df
        )

        # Log each unmatched PM as a data quality issue so the admin
        # can investigate (typo? missing Fuse record? alias needed?)
        for pm in unmatched_pms:
            db.insert_data_quality_issue(
                cycle_id, "unmatched_pm", pm["full_name"], pm.get("email"),
                f"PM '{pm['full_name']}' could not be matched to any training record."
            )

        # ===============================================================
        # STEP 4: Evaluate training completion
        # ===============================================================
        # For each matched PM, check which required courses they have
        # completed (Fundamentals, Advanced). If Advanced is done,
        # Fundamentals becomes "nice to have" (not required).
        logger.info("Step 4: Evaluating training completion")
        evaluated_pms = evaluate_training(matched_pms, training_df, config)

        # ===============================================================
        # STEP 5: Determine eligible PMs
        # ===============================================================
        # Filter to PMs who are:
        #   - assigned to at least one ACTIVE project, AND
        #   - have NOT completed all required training
        # Each PM is annotated with eligibility_status for the audit trail.
        logger.info("Step 5: Determining eligible PMs for reminders")
        eligible_pms, skipped_complete, skipped_inactive, nice_to_have_pms = get_eligible_pms(
            evaluated_pms, all_pms_df, config
        )

        # Store training snapshots with full audit trail.
        # NOTE: This is done AFTER get_eligible_pms because we need the
        # eligibility_status that was set on each PM during that step.
        # The audit columns (match_method, missing_trainings, compliance,
        # eligibility_status) allow auditors to query WHY each decision
        # was made for any PM in any cycle.
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

        # ===============================================================
        # STEP 6: Generate all communications
        # ===============================================================

        # 6: Training reminders — progressive stages (S1 friendly → S3 action-needed)
        # with bi-weekly cadence after S3 and rotating motivational angles.
        logger.info("Step 6: Generating training reminders")
        reminders, skipped_no_email = generate_reminders(
            eligible_pms, db, cycle_id, config, pm_compliance_issues
        )

        # 6a: Congratulations for PMs who just became fully certified.
        # Only sent to PMs who previously received training reminders
        # (stage 99 in DB). This closes the loop with positive reinforcement.
        newly_certified = [pm for pm in evaluated_pms
                           if pm.get("eligibility_status") in ("skipped_complete", "skipped_complete_nice_to_have")]
        congratulations = generate_congratulations(newly_certified, db, cycle_id, config)

        # 6b: Missing IT PM reminders — for active projects with no IT PM.
        # First time: notify the PM. Repeat: escalate to Project Owner.
        logger.info("Step 6b: Checking for active projects without IT PM")
        missing_itpm_list = find_projects_missing_it_pm(eppm_df, config)
        missing_itpm_reminders, escalation_reminders = generate_missing_itpm_reminders(
            missing_itpm_list, db, cycle_id, config
        )

        # 6c: Role-changed IT PM alerts — from the manually maintained
        # role_changes.xlsx. Notifies the PM to update ePPM.
        logger.info("Step 6c: Checking for IT PMs who changed roles")
        role_changes_df, role_changes_path = load_role_changes(config)
        if role_changes_path:
            input_files.append(("role_changes", role_changes_path))
        role_changed_list = find_role_changed_it_pms(eppm_df, role_changes_df, config)
        role_changed_reminders = generate_role_changed_reminders(
            role_changed_list, db, cycle_id, config
        )

        # ===============================================================
        # STEP 7: Generate output files
        # ===============================================================
        # Creates a timestamped output folder with:
        #   - summary_report.md
        #   - reminders.csv
        #   - per_recipient/ and stage_N/ folders
        #   - missing_itpm/, escalations_to_owner/, role_changed_itpm/
        #   - nice_to_have/, congratulations/
        #   - group_emails/ (consolidated group sends)
        #   - comms_plan.md (weekly send schedule)
        #   - send_tuesday/, send_wednesday/, etc. (day-specific folders)
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
            "congratulations_sent": len(congratulations),
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
            congratulations=congratulations,
        )

        # ===============================================================
        # STEP 8: Archive input files
        # ===============================================================
        # Move processed Excel files to archive/ with timestamp prefix.
        # This prevents accidental reprocessing and maintains traceability.
        logger.info("Step 8: Archiving processed files")
        archive_files(input_files, config, cycle_id, db)

        # ===============================================================
        # COMPLETE THE CYCLE
        # ===============================================================
        notes = (
            f"Generated {len(reminders)} training reminders, "
            f"{len(missing_itpm_reminders)} IT PM reminders to PMs, "
            f"{len(escalation_reminders)} escalations to owners, "
            f"{len(role_changed_reminders)} role-change alerts. Output: {output_dir}"
        )
        db.complete_cycle(cycle_id, "completed", notes)

        # Print a human-readable summary to the console.
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
        # ===============================================================
        # INVALID INPUT FILE → REVERT THE ENTIRE CYCLE
        # ===============================================================
        # If the input file is structurally wrong (missing columns, empty,
        # unrecognized values), we do NOT want to leave partial data in the
        # database. We fully revert: delete all records for this cycle_id
        # from every table, as if the cycle never happened.
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
        # ===============================================================
        # OTHER ERRORS → MARK AS FAILED (keep data for debugging)
        # ===============================================================
        logger.error("Cycle %d failed: %s", cycle_id, str(e), exc_info=True)
        db.complete_cycle(cycle_id, "failed", str(e))
        raise
    finally:
        db.close()

    return summary_data


# ===================================================================
# COMMAND-LINE ENTRY POINT
# ===================================================================
if __name__ == "__main__":
    # Change to the script's directory so relative paths in config work.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_cycle(config_path)
