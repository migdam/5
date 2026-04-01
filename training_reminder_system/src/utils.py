import hashlib
import logging
import os
from datetime import datetime


def get_timestamp():
    """Return a formatted timestamp for folder names: YYYY-MM-DD_HHMM."""
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def get_full_timestamp():
    """Return a full timestamp: YYYY-MM-DD_HHMMSS."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def get_date_stamp():
    """Return date only: YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def compute_checksum(filepath):
    """Compute MD5 checksum for a file."""
    md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def setup_logging(log_dir="logs", log_level=logging.INFO):
    """Configure application logging to file and console."""
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_file = os.path.join(log_dir, f"run_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_fmt)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    logging.info("Logging initialized. Log file: %s", log_file)
    return log_file
