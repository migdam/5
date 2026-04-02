##############################################################################
# archiver.py — Archive Processed Input Files
#
# After a successful processing cycle, the original input Excel files
# are moved from data/input/ to data/archive/ with a timestamp prefix.
#
# WHY FILES ARE ARCHIVED (not deleted):
#   1. PREVENT REPROCESSING: If the files stay in data/input/, the next
#      cycle run would process them again, creating duplicate reminders.
#      Moving them out ensures each file is processed exactly once.
#   2. MAINTAIN TRACEABILITY: The archived files are preserved so that
#      if questions arise later ("what data was used in cycle 5?"), the
#      exact input files can be found in the archive.
#   3. INTEGRITY VERIFICATION: An MD5 checksum is computed before moving.
#      This is stored in the database so the archived file can be verified
#      against the original if needed.
#
# ARCHIVE NAMING CONVENTION:
#   Files are organized by date, with a timestamp prefix:
#     archive/2026-04-01/2026-04-01_153042_ePPM_export.xlsx
#     archive/2026-04-01/2026-04-01_153042_Fuse_export.xlsx
#   The timestamp ensures uniqueness even if multiple cycles run on
#   the same day.
##############################################################################

import os
import shutil
import logging
from src.utils import get_date_stamp, get_full_timestamp, compute_checksum

logger = logging.getLogger(__name__)


def archive_files(input_files, config, cycle_id, db):
    """Archive processed input files to prevent reprocessing.

    Moves each input file from data/input/ to data/archive/YYYY-MM-DD/
    with a timestamp prefix. Records the archive location and checksum
    in the database for traceability.

    Args:
        input_files: List of (file_type, filepath) tuples.
            file_type is "eppm", "fuse", "role_changes", etc.
        config: Application configuration (provides archive folder path).
        cycle_id: Current cycle ID (links the archive record to this cycle).
        db: Database instance (for recording the processed_files entry).
    """
    archive_base = config["paths"]["archive_folder"]
    # Create a date-based subfolder (one folder per day).
    date_folder = os.path.join(archive_base, get_date_stamp())
    os.makedirs(date_folder, exist_ok=True)

    for file_type, filepath in input_files:
        if not os.path.exists(filepath):
            logger.warning("File not found for archiving: %s", filepath)
            continue

        original_name = os.path.basename(filepath)
        timestamp = get_full_timestamp()
        # Prepend timestamp to ensure uniqueness within the day folder.
        archived_name = f"{timestamp}_{original_name}"
        archived_path = os.path.join(date_folder, archived_name)

        # Compute checksum BEFORE moving (we need the file to still be
        # in its original location to read it).
        checksum = compute_checksum(filepath)

        # Move the file from input/ to archive/.
        # Using shutil.move instead of os.rename to handle cross-device moves.
        shutil.move(filepath, archived_path)
        logger.info("Archived %s -> %s", filepath, archived_path)

        # Record the archive in the database for full traceability.
        # This allows querying: "Which files were used in cycle 5?"
        db.record_processed_file(
            cycle_id=cycle_id,
            file_type=file_type,
            original=original_name,
            archived=archived_name,
            archive_path=archived_path,
            checksum=checksum,
        )

    logger.info("Archiving complete. %d files archived to %s", len(input_files), date_folder)
