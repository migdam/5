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


def load_eppm(config):
    """Load the ePPM assignment file."""
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("eppm", "*ePPM*.*xlsx")
    filepath = find_file(input_folder, pattern)
    mapping = config["column_mapping"]["eppm"]
    df = load_excel(filepath, mapping)
    logger.info("ePPM data: %d rows loaded", len(df))
    return df, filepath


def load_training(config):
    """Load the Fuse training status file."""
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("fuse", "*Fuse*.*xlsx")
    filepath = find_file(input_folder, pattern)
    mapping = config["column_mapping"]["fuse"]
    df = load_excel(filepath, mapping)
    logger.info("Training data: %d rows loaded", len(df))
    return df, filepath


def load_role_changes(config):
    """Load the manually maintained role changes CSV file.

    This file lists IT PMs who have changed roles and should no longer
    be assigned as IT PM on projects. It is optional — if not found,
    role-change detection is skipped.

    Returns:
        (DataFrame, filepath) if file found, or (None, None) if not found.
    """
    input_folder = config["paths"]["input_folder"]
    pattern = config.get("file_patterns", {}).get("role_changes", "*role_changes*.*csv")
    try:
        filepath = find_file(input_folder, pattern)
    except FileNotFoundError:
        logger.info("No role_changes CSV found in %s — skipping role-change detection", input_folder)
        return None, None

    mapping = config.get("column_mapping", {}).get("role_changes", {})

    logger.info("Loading role changes CSV: %s", filepath)
    df = pd.read_csv(filepath)
    logger.info("Loaded %d role change entries", len(df))

    # Rename columns using mapping
    reverse_map = {v: k for k, v in mapping.items()}
    available = set(df.columns)
    mapped_cols = {}
    for actual_header, logical_name in reverse_map.items():
        if actual_header in available:
            mapped_cols[actual_header] = logical_name

    df = df.rename(columns=mapped_cols)

    # Strip whitespace from string columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace("nan", None)

    return df, filepath
