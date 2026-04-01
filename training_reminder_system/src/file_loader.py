import glob
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def find_file(input_folder, pattern):
    """Find a single file matching a glob pattern in the input folder."""
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
    reverse_map = {v: k for k, v in column_mapping.items()}

    # Check which expected columns exist
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

    df = df.rename(columns=mapped_cols)

    # Strip whitespace from string columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace("nan", None)

    return df


class InputValidationError(Exception):
    """Raised when an input file fails validation checks."""
    pass


def validate_eppm(df, filepath, config):
    """Validate that the ePPM file has the expected structure and content."""
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

    # Check at least some PMs have values
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
    """Validate that the Fuse training file has the expected structure and content."""
    errors = []
    mapping = config["column_mapping"]["fuse"]

    critical_cols = ["full_name", "email", "content_title", "course_status"]
    for logical_name in critical_cols:
        if logical_name not in df.columns:
            actual_header = mapping.get(logical_name, logical_name)
            errors.append(f"Missing critical column '{actual_header}' (mapped as '{logical_name}')")

    if len(df) == 0:
        errors.append("Training file is empty (0 rows)")

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
    """Load the ePPM assignment file."""
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("eppm", "*ePPM*.*xlsx")
    filepath = find_file(input_folder, pattern)
    mapping = config["column_mapping"]["eppm"]
    df = load_excel(filepath, mapping)
    validate_eppm(df, filepath, config)
    logger.info("ePPM data: %d rows loaded", len(df))
    return df, filepath


def load_training(config):
    """Load the Fuse training status file."""
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
