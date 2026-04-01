import os
import yaml
import logging

logger = logging.getLogger(__name__)

REQUIRED_SECTIONS = ["paths", "column_mapping", "status_mapping", "required_training", "templates"]


def load_config(config_path="config.yaml"):
    """Load and validate the YAML configuration file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    for section in REQUIRED_SECTIONS:
        if section not in config:
            raise ValueError(f"Missing required configuration section: '{section}'")

    if "eppm" not in config["column_mapping"]:
        raise ValueError("Missing 'eppm' in column_mapping configuration")
    if "fuse" not in config["column_mapping"]:
        raise ValueError("Missing 'fuse' in column_mapping configuration")

    # Ensure directories exist
    for key in ["input_folder", "output_folder", "archive_folder", "log_folder"]:
        path = config["paths"].get(key, "")
        if path:
            os.makedirs(path, exist_ok=True)

    # Ensure database directory exists
    db_path = config["paths"].get("database", "")
    if db_path:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

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
