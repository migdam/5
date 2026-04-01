import os
import shutil
import logging
from src.utils import get_date_stamp, get_full_timestamp, compute_checksum

logger = logging.getLogger(__name__)


def archive_files(input_files, config, cycle_id, db):
    """Archive processed input files to prevent reprocessing.

    Args:
        input_files: List of (file_type, filepath) tuples.
        config: Application configuration.
        cycle_id: Current cycle ID.
        db: Database instance.
    """
    archive_base = config["paths"]["archive_folder"]
    date_folder = os.path.join(archive_base, get_date_stamp())
    os.makedirs(date_folder, exist_ok=True)

    for file_type, filepath in input_files:
        if not os.path.exists(filepath):
            logger.warning("File not found for archiving: %s", filepath)
            continue

        original_name = os.path.basename(filepath)
        timestamp = get_full_timestamp()
        archived_name = f"{timestamp}_{original_name}"
        archived_path = os.path.join(date_folder, archived_name)

        # Compute checksum before moving
        checksum = compute_checksum(filepath)

        # Move file
        shutil.move(filepath, archived_path)
        logger.info("Archived %s -> %s", filepath, archived_path)

        # Record in database
        db.record_processed_file(
            cycle_id=cycle_id,
            file_type=file_type,
            original=original_name,
            archived=archived_name,
            archive_path=archived_path,
            checksum=checksum,
        )

    logger.info("Archiving complete. %d files archived to %s", len(input_files), date_folder)
