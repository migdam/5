"""Tests for config loader."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from src.config_loader import load_config


def test_load_config_from_project():
    """Load the actual config.yaml from the project."""
    original = os.getcwd()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        config = load_config()
        assert "paths" in config
        assert "column_mapping" in config
        assert "status_mapping" in config
        assert "required_training" in config
        assert "templates" in config
        assert config["paths"]["input_folder"] == "data/input"
    finally:
        os.chdir(original)


def test_load_config_has_eppm_mappings():
    original = os.getcwd()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        config = load_config()
        eppm = config["column_mapping"]["eppm"]
        assert "project_number" in eppm
        assert "project_manager" in eppm
        assert "project_manager_email" in eppm
        assert "it_project_manager" in eppm
        assert "g3_compliance" in eppm
        assert "g3_action" in eppm
    finally:
        os.chdir(original)


def test_load_config_has_fuse_mappings():
    original = os.getcwd()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        config = load_config()
        fuse = config["column_mapping"]["fuse"]
        assert "full_name" in fuse
        assert "email" in fuse
        assert "content_title" in fuse
        assert "course_status" in fuse
    finally:
        os.chdir(original)


def test_load_config_has_required_training():
    original = os.getcwd()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))
    try:
        config = load_config()
        rt = config["required_training"]
        assert "fundamentals" in rt
        assert "advanced" in rt
        assert "content_title" in rt["fundamentals"]
        assert "label" in rt["fundamentals"]
    finally:
        os.chdir(original)


def test_load_config_missing_file():
    with pytest.raises(Exception):
        load_config("/nonexistent/path/config.yaml")
