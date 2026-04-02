##############################################################################
# file_loader.py — Load and Validate Excel Input Files
#
# This module is responsible for reading Excel files from the input folder,
# mapping their column headers to standardized internal names, and validating
# that the files contain the data the rest of the system needs.
#
# There are two REQUIRED input files:
#   1. ePPM file — the master list of projects and their assigned Project
#      Managers. This is the "source of truth" for who should have training.
#   2. Fuse file — the training platform export showing who has completed
#      (or not completed) required training courses.
#
# There are three OPTIONAL input files:
#   3. Role Changes — people who changed roles and are no longer IT PMs.
#   4. Excluded Projects — "ghost" projects to ignore during analysis.
#   5. Identity Aliases — manual overrides for name/email mismatches
#      across systems (e.g., maiden names, domain changes).
#
# If a required file fails validation, an InputValidationError is raised.
# The calling code in main.py catches this and reverts to the previous
# processing cycle, because proceeding with corrupt or incomplete data
# would produce unreliable reminder emails.
##############################################################################

import glob
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def find_file(input_folder, pattern):
    """Find a single file matching a glob pattern in the input folder.

    This function searches the input folder for files that match a naming
    pattern (e.g., "*ePPM*.*xlsx"). It is designed to locate a specific
    file even if the exact filename changes between cycles (timestamps,
    version numbers, etc.).

    Why multiple matches trigger a warning:
        Each pattern should correspond to exactly ONE file. If multiple
        files match (e.g., someone left last month's file in the folder),
        we log a warning so the operator knows, but we proceed with the
        first match rather than failing outright. This keeps the process
        running while flagging the issue for cleanup.
    """
    search_path = os.path.join(input_folder, pattern)
    matches = glob.glob(search_path)
    if not matches:
        raise FileNotFoundError(f"No file found matching pattern '{pattern}' in {input_folder}")
    if len(matches) > 1:
        logger.warning("Multiple files match '%s': %s. Using first match.", pattern, matches)
    filepath = matches[0]
    logger.info("Found file: %s", filepath)
    return filepath


def load_excel(filepath, column_mapping):
    """Load an Excel file and rename columns using the provided mapping.

    Column Mapping Mechanism — Why This Exists:
        The rest of the codebase uses consistent internal names like
        "project_manager" and "project_number". But the actual Excel
        files from ePPM and Fuse have their own header names that can
        differ (e.g., "PM Full Name", "Project #", "Learner Email").

        The column_mapping (defined in config.yaml) acts as a translation
        layer:
            logical_name  ->  actual_column_header
            "project_manager" -> "PM Full Name"
            "email"           -> "Learner Email"

        This means if a source system changes its column headers, we only
        need to update the config file — no code changes required.

    Args:
        filepath: Path to the Excel file.
        column_mapping: Dict of {logical_name: actual_column_header}.

    Returns:
        DataFrame with columns renamed to logical names.
    """
    logger.info("Loading Excel file: %s", filepath)
    df = pd.read_excel(filepath, engine="openpyxl")
    logger.info("Loaded %d rows, %d columns", len(df), len(df.columns))

    # Build reverse mapping: actual_header -> logical_name
    # We need the reverse direction because pandas rename() expects
    # {old_name: new_name}, and our config stores {logical: actual}.
    reverse_map = {v: k for k, v in column_mapping.items()}

    # Check which expected columns exist in the actual file.
    # Missing columns are logged as warnings — they may be optional
    # (e.g., "it_project_manager" is not present in every ePPM export).
    available = set(df.columns)
    mapped_cols = {}
    missing_cols = []
    for actual_header, logical_name in reverse_map.items():
        if actual_header in available:
            mapped_cols[actual_header] = logical_name
        else:
            missing_cols.append(actual_header)

    if missing_cols:
        logger.warning("Missing columns in %s: %s", filepath, missing_cols)

    # Rename the columns from actual Excel headers to our internal names.
    df = df.rename(columns=mapped_cols)

    # Strip whitespace from all string columns to prevent invisible
    # mismatches (e.g., "John Smith " != "John Smith"). Also convert
    # pandas NaN placeholders back to None for consistency downstream.
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace("nan", None)

    return df


class InputValidationError(Exception):
    """Raised when an input file fails validation checks.

    Why this causes a cycle revert in main.py:
        The training reminder system runs on a recurring schedule. If the
        input files for the current cycle are corrupt, incomplete, or
        structurally wrong (e.g., missing the Project Manager column),
        then the entire analysis would be invalid — we might send reminders
        to the wrong people or miss people entirely.

        Rather than producing bad output, main.py catches this error and
        reverts to the previous cycle's results. This ensures that even if
        someone uploads a broken file, the system does not send incorrect
        reminders. The error is logged so operators can fix the file and
        re-run.
    """
    pass


def validate_eppm(df, filepath, config):
    """Validate that the ePPM file has the expected structure and content.

    The ePPM file is the project assignment master list. For the system to
    work, it MUST contain:
      - project_number: unique identifier for each project
      - project_manager: the person assigned as PM (who needs training)
      - project_manager_email: used for matching against Fuse records
      - project_status: used to filter out closed/cancelled projects

    These columns are "critical" because without them we cannot determine
    WHO needs training reminders or WHICH projects are active. If any are
    missing, we raise InputValidationError rather than producing partial
    results.

    We also check that the file is not empty and that at least some rows
    have PM values — an ePPM export with all-blank PM fields is likely a
    data extraction error.
    """
    errors = []
    mapping = config["column_mapping"]["eppm"]

    # Check critical columns exist
    critical_cols = ["project_number", "project_manager", "project_manager_email", "project_status"]
    for logical_name in critical_cols:
        if logical_name not in df.columns:
            actual_header = mapping.get(logical_name, logical_name)
            errors.append(f"Missing critical column '{actual_header}' (mapped as '{logical_name}')")

    # Check not empty
    if len(df) == 0:
        errors.append("ePPM file is empty (0 rows)")

    # Check at least some PMs have values — if every row has a blank PM,
    # the file was likely exported incorrectly or with wrong filters.
    if "project_manager" in df.columns:
        non_null = df["project_manager"].dropna()
        non_null = non_null[non_null.astype(str).str.strip() != ""]
        if len(non_null) == 0:
            errors.append("ePPM file has no Project Manager values")

    if errors:
        raise InputValidationError(
            f"ePPM file validation failed ({filepath}):\n  " + "\n  ".join(errors)
        )

    logger.info("ePPM file validated: %d rows, critical columns present", len(df))


def validate_training(df, filepath, config):
    """Validate that the Fuse training file has the expected structure and content.

    The Fuse file is the training platform export. For the system to work,
    it MUST contain:
      - full_name: the learner's name (used for matching against ePPM PMs)
      - email: the learner's email (primary matching key)
      - content_title: which training course the record pertains to
      - course_status: whether the course is "completed" or "incomplete"

    We also verify that course_status contains recognizable values. If the
    file has status values we do not recognize (e.g., "done" instead of
    "completed"), it likely means the Fuse export format changed and the
    config needs updating.
    """
    errors = []
    mapping = config["column_mapping"]["fuse"]

    critical_cols = ["full_name", "email", "content_title", "course_status"]
    for logical_name in critical_cols:
        if logical_name not in df.columns:
            actual_header = mapping.get(logical_name, logical_name)
            errors.append(f"Missing critical column '{actual_header}' (mapped as '{logical_name}')")

    if len(df) == 0:
        errors.append("Training file is empty (0 rows)")

    # Verify that the course_status column contains values we understand.
    # We expect "completed" or "incomplete". If neither appears, the file
    # format may have changed (e.g., a new LMS version using different terms).
    if "course_status" in df.columns:
        valid_statuses = {"completed", "incomplete"}
        actual = set(df["course_status"].dropna().astype(str).str.lower().str.strip().unique())
        if actual and not actual.intersection(valid_statuses):
            errors.append(
                f"Training file has no recognized course_status values. "
                f"Found: {actual}. Expected: {valid_statuses}"
            )

    if errors:
        raise InputValidationError(
            f"Training file validation failed ({filepath}):\n  " + "\n  ".join(errors)
        )

    logger.info("Training file validated: %d rows, critical columns present", len(df))


def load_eppm(config):
    """Load the ePPM assignment file.

    This is a REQUIRED file. The ePPM export contains the master list of
    all projects and their assigned Project Managers. Without it, we have
    no way of knowing who should receive training reminders.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("eppm", "*ePPM*.*xlsx")
    filepath = find_file(input_folder, pattern)
    mapping = config["column_mapping"]["eppm"]
    df = load_excel(filepath, mapping)
    validate_eppm(df, filepath, config)
    logger.info("ePPM data: %d rows loaded", len(df))
    return df, filepath


def load_training(config):
    """Load the Fuse training status file.

    This is a REQUIRED file. The Fuse export contains training completion
    records — who has completed which courses, and who has not. Without it,
    we cannot determine who still needs to complete their training.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("fuse", "*Fuse*.*xlsx")
    filepath = find_file(input_folder, pattern)
    mapping = config["column_mapping"]["fuse"]
    df = load_excel(filepath, mapping)
    validate_training(df, filepath, config)
    logger.info("Training data: %d rows loaded", len(df))
    return df, filepath


def load_role_changes(config):
    """Load the manually maintained role changes Excel file.

    This file lists IT PMs who have changed roles and should no longer
    be assigned as IT PM on projects. It is optional — if not found,
    role-change detection is skipped.

    Why this file is OPTIONAL:
        Role changes are a supplementary data source maintained by hand.
        Many processing cycles may not have any role changes to report.
        If the file is absent, the system simply skips role-change
        detection and continues normally. This avoids forcing operators
        to create an empty file every cycle.

    Returns:
        (DataFrame, filepath) if file found, or (None, None) if not found.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("role_changes", "*role_changes*.*xlsx")
    try:
        filepath = find_file(input_folder, pattern)
    except FileNotFoundError:
        logger.info("No role_changes file found in %s — skipping role-change detection", input_folder)
        return None, None

    mapping = config.get("column_mapping", {}).get("role_changes", {})
    df = load_excel(filepath, mapping)
    logger.info("Role changes data: %d entries loaded", len(df))
    return df, filepath


def load_excluded_projects(config):
    """Load the manually maintained excluded projects Excel file.

    This file lists project IDs for ghost projects (completed, cancelled,
    or otherwise no longer active) that should be excluded from analysis
    even if they still appear in ePPM. It is optional.

    Why this file is OPTIONAL:
        Ghost projects are an edge case — projects that are effectively
        dead but linger in ePPM due to administrative delays. Most cycles
        may have none. If the file is absent, no projects are excluded
        and all ePPM records are processed normally.

    Returns:
        (DataFrame, filepath) if file found, or (None, None) if not found.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("excluded_projects", "*excluded_projects*.*xlsx")
    try:
        filepath = find_file(input_folder, pattern)
    except FileNotFoundError:
        logger.info("No excluded_projects file found in %s", input_folder)
        return None, None

    mapping = config.get("column_mapping", {}).get("excluded_projects", {})
    df = load_excel(filepath, mapping)
    logger.info("Excluded projects data: %d entries loaded", len(df))
    return df, filepath


def load_identity_aliases(config):
    """Load the manually maintained identity aliases Excel file.

    This file maps alternate identities (maiden names, old emails, cross-system
    email differences) to the canonical identity. Used to resolve matches that
    automated matching cannot handle.

    Why this file is OPTIONAL:
        Identity aliases are a manual correction mechanism. They handle
        rare edge cases where a person's name or email differs between
        ePPM and Fuse (e.g., maiden name vs. married name, different email
        domains across corporate systems). Most cycles may not need any
        aliases. If the file is absent, the matcher simply relies on its
        standard email and name matching passes.

    Format:
        canonical_email | canonical_name | alias_email | alias_name | reason
        anna.nowak@...  | Anna Nowak     | anna.kowalska@... | Anna Kowalska | Maiden name
        john@corp.ex    | John Smith     | john@brand.ex     |               | Domain change

    Returns:
        (DataFrame, filepath) if file found, or (None, None) if not found.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("identity_aliases", "*identity_aliases*.*xlsx")
    try:
        filepath = find_file(input_folder, pattern)
    except FileNotFoundError:
        logger.info("No identity_aliases file found in %s", input_folder)
        return None, None

    mapping = config.get("column_mapping", {}).get("identity_aliases", {})
    df = load_excel(filepath, mapping)
    logger.info("Identity aliases data: %d entries loaded", len(df))
    return df, filepath
