"""Tests for evaluator — missing IT PM and role-changed IT PM detection."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.evaluator import find_projects_missing_it_pm, find_role_changed_it_pms


def make_config():
    return {
        "status_mapping": {
            "project_active_statuses": ["Not Completed"],
        },
        "valid_itpm_positions": [
            "IT Project Manager", "Project Manager", "Senior Project Manager",
        ],
    }


# --- Missing IT PM Tests ---

def test_find_missing_itpm_detects_blank():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test Project",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": None,
        "it_project_manager_email": None,
        "project_owner": "Owner Name",
        "project_owner_email": "owner@corp.example",
    }])
    result = find_projects_missing_it_pm(eppm_df, config)
    assert len(result) == 1
    assert result[0]["pm_name"] == "Maya Collins"
    assert len(result[0]["projects"]) == 1


def test_find_missing_itpm_skips_completed():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Done Project",
        "project_status": "Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": None,
        "it_project_manager_email": None,
        "project_owner": None, "project_owner_email": None,
    }])
    result = find_projects_missing_it_pm(eppm_df, config)
    assert len(result) == 0


def test_find_missing_itpm_skips_assigned():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel Carter",
        "it_project_manager_email": "daniel@corp.example",
        "project_owner": None, "project_owner_email": None,
    }])
    result = find_projects_missing_it_pm(eppm_df, config)
    assert len(result) == 0


def test_find_missing_itpm_groups_by_pm():
    """Multiple projects for same PM should be grouped."""
    config = make_config()
    eppm_df = pd.DataFrame([
        {"project_number": "PRJ001", "project_name": "Project A",
         "project_status": "Not Completed",
         "project_manager": "Maya Collins", "project_manager_email": "maya@corp.example",
         "it_project_manager": None, "it_project_manager_email": None,
         "project_owner": None, "project_owner_email": None},
        {"project_number": "PRJ002", "project_name": "Project B",
         "project_status": "Not Completed",
         "project_manager": "Maya Collins", "project_manager_email": "maya@corp.example",
         "it_project_manager": None, "it_project_manager_email": None,
         "project_owner": None, "project_owner_email": None},
    ])
    result = find_projects_missing_it_pm(eppm_df, config)
    assert len(result) == 1  # Grouped into one entry for Maya
    assert len(result[0]["projects"]) == 2


def test_find_missing_itpm_includes_owner_info():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": None, "it_project_manager_email": None,
        "project_owner": "Big Boss", "project_owner_email": "boss@corp.example",
    }])
    result = find_projects_missing_it_pm(eppm_df, config)
    assert result[0]["projects"][0]["owner_name"] == "Big Boss"
    assert result[0]["projects"][0]["owner_email"] == "boss@corp.example"


# --- Role-Changed IT PM Tests ---

def test_find_role_changed_detects_mismatch():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya Collins",
        "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel Carter",
        "it_project_manager_email": "daniel@corp.example",
    }])
    role_changes_df = pd.DataFrame([{
        "it_pm_email": "daniel@corp.example",
        "it_pm_name": "Daniel Carter",
        "new_role": "Data Engineer",
    }])
    result = find_role_changed_it_pms(eppm_df, role_changes_df, config)
    assert len(result) == 1
    assert result[0]["projects"][0]["it_pm_name"] == "Daniel Carter"
    assert result[0]["projects"][0]["current_position"] == "Data Engineer"


def test_find_role_changed_none_when_no_file():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya", "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel", "it_project_manager_email": "daniel@corp.example",
    }])
    result = find_role_changed_it_pms(eppm_df, None, config)
    assert len(result) == 0


def test_find_role_changed_skips_completed_projects():
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Done Project",
        "project_status": "Completed",
        "project_manager": "Maya", "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel", "it_project_manager_email": "daniel@corp.example",
    }])
    role_changes_df = pd.DataFrame([{
        "it_pm_email": "daniel@corp.example",
        "it_pm_name": "Daniel", "new_role": "Analyst",
    }])
    result = find_role_changed_it_pms(eppm_df, role_changes_df, config)
    assert len(result) == 0


def test_find_role_changed_skips_unlisted_itpm():
    """IT PM not in role_changes list should not be flagged."""
    config = make_config()
    eppm_df = pd.DataFrame([{
        "project_number": "PRJ001", "project_name": "Test",
        "project_status": "Not Completed",
        "project_manager": "Maya", "project_manager_email": "maya@corp.example",
        "it_project_manager": "Daniel", "it_project_manager_email": "daniel@corp.example",
    }])
    role_changes_df = pd.DataFrame([{
        "it_pm_email": "someone.else@corp.example",
        "it_pm_name": "Someone Else", "new_role": "Analyst",
    }])
    result = find_role_changed_it_pms(eppm_df, role_changes_df, config)
    assert len(result) == 0
