"""Tests for file loader validation logic."""
import sys
import os
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import openpyxl
from src.file_loader import validate_eppm, validate_training, InputValidationError


def make_config():
    return {
        "column_mapping": {
            "eppm": {
                "project_number": "Project number",
                "project_manager": "Project Manager",
                "project_manager_email": "Project Manager Email",
                "project_status": "Project Status",
            },
            "fuse": {
                "full_name": "Full Name",
                "email": "Email",
                "content_title": "Content Title",
                "course_status": "Course Status",
            },
        },
    }


def _write_excel(rows, path):
    wb = openpyxl.Workbook()
    ws = wb.active
    if rows:
        ws.append(list(rows[0].keys()))
        for row in rows:
            ws.append(list(row.values()))
    wb.save(path)


# --- ePPM Validation Tests ---

def test_eppm_valid():
    df = pd.DataFrame([{
        "project_number": "PRJ001", "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example", "project_status": "Not Completed",
    }])
    validate_eppm(df, "test.xlsx", make_config())  # Should not raise


def test_eppm_missing_critical_column():
    df = pd.DataFrame([{"project_number": "PRJ001", "project_status": "Not Completed"}])
    with pytest.raises(InputValidationError, match="project_manager"):
        validate_eppm(df, "test.xlsx", make_config())


def test_eppm_empty():
    df = pd.DataFrame(columns=["project_number", "project_manager", "project_manager_email", "project_status"])
    with pytest.raises(InputValidationError, match="empty"):
        validate_eppm(df, "test.xlsx", make_config())


def test_eppm_no_pm_values():
    df = pd.DataFrame([{
        "project_number": "PRJ001", "project_manager": "",
        "project_manager_email": "", "project_status": "Not Completed",
    }])
    with pytest.raises(InputValidationError, match="no Project Manager values"):
        validate_eppm(df, "test.xlsx", make_config())


# --- Training Validation Tests ---

def test_training_valid():
    df = pd.DataFrame([{
        "full_name": "Maya Collins", "email": "maya@corp.example",
        "content_title": "Test Course", "course_status": "completed",
    }])
    validate_training(df, "test.xlsx", make_config())  # Should not raise


def test_training_missing_critical_column():
    df = pd.DataFrame([{"full_name": "Maya Collins"}])
    with pytest.raises(InputValidationError, match="course_status"):
        validate_training(df, "test.xlsx", make_config())


def test_training_empty():
    df = pd.DataFrame(columns=["full_name", "email", "content_title", "course_status"])
    with pytest.raises(InputValidationError, match="empty"):
        validate_training(df, "test.xlsx", make_config())


def test_training_bad_status_values():
    df = pd.DataFrame([{
        "full_name": "Maya Collins", "email": "maya@corp.example",
        "content_title": "Test", "course_status": "passed",  # Not recognized
    }])
    with pytest.raises(InputValidationError, match="no recognized course_status"):
        validate_training(df, "test.xlsx", make_config())


def test_training_accepts_mixed_case_status():
    df = pd.DataFrame([{
        "full_name": "Maya Collins", "email": "maya@corp.example",
        "content_title": "Test", "course_status": "Completed",  # Capital C
    }])
    validate_training(df, "test.xlsx", make_config())  # Should not raise
