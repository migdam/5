##############################################################################
# utils.py — Shared Utility Functions
#
# Small helper functions used across multiple modules. These provide
# consistent timestamp formatting, file checksums, and logging setup.
##############################################################################

import hashlib
import logging
import os
from datetime import datetime


def get_timestamp():
    """Return a formatted timestamp for folder names: YYYY-MM-DD_HHMM.

    Used for output folder names (e.g., "2026-04-01_1530_cycle5/").
    Minute-level precision is enough — we don't run multiple cycles
    within the same minute.
    """
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def get_full_timestamp():
    """Return a full timestamp with seconds: YYYY-MM-DD_HHMMSS.

    Used for archive filenames where second-level precision is needed
    to avoid collisions (e.g., "2026-04-01_153042_ePPM_export.xlsx").
    """
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def get_date_stamp():
    """Return date only: YYYY-MM-DD.

    Used for archive folder names (one folder per day).
    """
    return datetime.now().strftime("%Y-%m-%d")


def compute_checksum(filepath):
    """Compute MD5 checksum for a file.

    Used when archiving processed files. The checksum is stored in the
    database so we can later verify that an archived file matches the
    original (integrity check). Reads the file in 8KB chunks to handle
    large files without loading them entirely into memory.
    """
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def setup_logging(log_dir="logs", log_level=logging.INFO):
    """Configure application logging to both file and console.

    Creates a timestamped log file (e.g., "logs/run_2026-04-01_153042.log")
    that captures everything at INFO level and above. The console also
    shows log messages for real-time monitoring.

    WHY BOTH FILE AND CONSOLE:
      - File logging: provides a permanent audit trail of what happened
        during each cycle. Essential for troubleshooting and compliance.
      - Console logging: gives immediate feedback to the operator running
        the system so they can see progress and errors in real time.

    Returns:
        str: Path to the log file that was created.
    """
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers to prevent duplicate log entries
    # (important when run_simulation.py calls run_cycle multiple times).
    root_logger.handlers.clear()

    # File handler — detailed format with timestamp and module name.
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    # Console handler — shorter format (no timestamp, module shows in message).
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    logging.info("Logging initialized. Log file: %s", log_file)
    return log_file
