"""Tests for normalizer — name/email normalization and PM extraction."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.normalizer import normalize_name, normalize_email, normalize_dataframe, extract_unique_pms


def test_normalize_name_basic():
    assert normalize_name("  Maya  Collins ") == "maya collins"


def test_normalize_name_extra_spaces():
    assert normalize_name("Daniel    Carter") == "daniel carter"


def test_normalize_name_none():
    assert normalize_name(None) == ""


def test_normalize_name_empty():
    assert normalize_name("") == ""


def test_normalize_email_basic():
    assert normalize_email("Maya.Collins@Corp.Example") == "maya.collins@corp.example"


def test_normalize_email_whitespace():
    assert normalize_email("  test@example.com  ") == "test@example.com"


def test_normalize_email_none():
    assert normalize_email(None) == ""


def test_normalize_dataframe():
    df = pd.DataFrame([
        {"name": "Maya Collins", "email": "Maya@Corp.Example"},
        {"name": " Daniel  Carter ", "email": "DANIEL@corp.example"},
    ])
    result = normalize_dataframe(df, "name", "email")
    assert "normalized_name" in result.columns
    assert "normalized_email" in result.columns
    assert result.iloc[0]["normalized_name"] == "maya collins"
    assert result.iloc[1]["normalized_email"] == "daniel@corp.example"


def test_extract_unique_pms_deduplicates():
    """Same person as PM and IT PM should appear once."""
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test Project",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": "Maya Collins",
        "it_project_manager_email": "maya@corp.example",
    }])
    unique_pms, all_pms_df = extract_unique_pms(eppm_df)
    assert len(unique_pms) == 1  # Deduplicated
    assert len(all_pms_df) == 2  # Both role records kept


def test_extract_unique_pms_multiple_people():
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel Carter",
        "it_project_manager_email": "daniel@corp.example",
    }])
    unique_pms, all_pms_df = extract_unique_pms(eppm_df)
    assert len(unique_pms) == 2
    names = set(unique_pms["full_name"])
    assert "Maya Collins" in names
    assert "Daniel Carter" in names


def test_extract_unique_pms_skips_empty():
    """Rows with no PM should be handled gracefully."""
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": None,
        "project_manager_email": None,
        "it_project_manager": "Daniel Carter",
        "it_project_manager_email": "daniel@corp.example",
    }])
    unique_pms, all_pms_df = extract_unique_pms(eppm_df)
    assert len(unique_pms) == 1
    assert unique_pms.iloc[0]["full_name"] == "Daniel Carter"


def test_extract_unique_pms_preserves_project_info():
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Alpha Project",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": None,
        "it_project_manager_email": None,
    }])
    unique_pms, all_pms_df = extract_unique_pms(eppm_df)
    assert all_pms_df.iloc[0]["project_name"] == "Alpha Project"
    assert all_pms_df.iloc[0]["project_id"] == "PRJ001"
