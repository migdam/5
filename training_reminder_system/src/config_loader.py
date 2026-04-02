##############################################################################
# config_loader.py — Load and Validate the YAML Configuration
#
# The entire training reminder system is driven by a single config file
# (config.yaml by default). This module reads that file, validates that
# all required sections are present, and creates any directories that
# don't exist yet (input, output, archive, logs, database folder).
#
# WHY VALIDATION HAPPENS EARLY:
#   If the config file is missing a critical section (e.g., column_mapping),
#   the system would crash later with a confusing KeyError deep inside the
#   pipeline. By validating upfront, we fail fast with a clear message:
#   "Missing required configuration section: 'column_mapping'".
#
# REQUIRED CONFIG SECTIONS:
#   - paths: where to find input files, where to write output, archive, logs, DB
#   - column_mapping: maps internal field names to actual Excel column headers
#     (must include sub-sections for 'eppm' and 'fuse')
#   - status_mapping: defines what values mean "completed", "active", etc.
#   - required_training: which courses PMs must complete (Fundamentals, Advanced)
#   - templates: file paths for all email templates
#
# OPTIONAL CONFIG SECTIONS (used if present, ignored if not):
#   - action_links: URLs for learning platform, ePPM, Viva Engage
#   - comms_schedule: weekly communication calendar
#   - valid_itpm_positions: valid PM role titles for role-change detection
#   - communication: settings like max_reminder_stage
#   - file_patterns: glob patterns for finding input files
##############################################################################

import os
import yaml
import logging

logger = logging.getLogger(__name__)

# These sections MUST exist in the config file. Without any one of them,
# the system cannot function correctly and will refuse to start.
REQUIRED_SECTIONS = ["paths", "column_mapping", "status_mapping", "required_training", "templates"]


def load_config(config_path="config.yaml"):
    """Load and validate the YAML configuration file.

    This is typically the first thing called when the system starts.
    It reads config.yaml, checks that all required sections are present,
    creates any missing directories, and returns the config dictionary
    that every other module uses.

    Args:
        config_path: Path to the YAML config file (default: "config.yaml").

    Returns:
        dict: The full configuration dictionary.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        ValueError: If a required section is missing.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Validate that all required sections exist in the config.
    # This catches typos (e.g., "colum_mapping" instead of "column_mapping")
    # and missing sections before the system tries to use them.
    for section in REQUIRED_SECTIONS:
        if section not in config:
            raise ValueError(f"Missing required configuration section: '{section}'")

    # column_mapping must have sub-sections for both input file types.
    # Without these, we cannot translate Excel headers to internal names.
    if "eppm" not in config["column_mapping"]:
        raise ValueError("Missing 'eppm' in column_mapping configuration")
    if "fuse" not in config["column_mapping"]:
        raise ValueError("Missing 'fuse' in column_mapping configuration")

    # Create all required directories if they don't already exist.
    # This means the user doesn't need to manually create data/input/,
    # data/output/, etc. — the system sets itself up on first run.
    for key in ["input_folder", "output_folder", "archive_folder", "log_folder"]:
        path = config["paths"].get(key, "")
        if path:
            os.makedirs(path, exist_ok=True)

    # The database file needs its parent directory to exist.
    # For example, if database = "data/training_reminders.db",
    # we need to ensure "data/" exists.
    db_path = config["paths"].get("database", "")
    if db_path:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    # Log a summary of what was loaded — useful for debugging and audit.
    logger.info("Configuration loaded from %s", config_path)
    logger.info("  Input: %s, Output: %s, Archive: %s",
                config["paths"].get("input_folder"), config["paths"].get("output_folder"),
                config["paths"].get("archive_folder"))
    logger.info("  Database: %s", config["paths"].get("database"))
    logger.info("  ePPM columns mapped: %d, Fuse columns mapped: %d",
                len(config["column_mapping"].get("eppm", {})),
                len(config["column_mapping"].get("fuse", {})))
    logger.info("  Required training: %s",
                ", ".join(config.get("required_training", {}).keys()))
    return config
