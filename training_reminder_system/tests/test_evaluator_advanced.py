"""Advanced evaluator tests — compliance extraction, ghost filtering, nice-to-have."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.evaluator import (
    extract_pm_compliance_issues,
    filter_ghost_projects,
    evaluate_training,
    get_eligible_pms,
)


def make_config():
    return {
        "required_training": {
            "fundamentals": {
                "content_title": "Managing Projects for Business Success - Fundamentals - Certification Test",
                "label": "Fundamentals",
            },
            "advanced": {
                "content_title": "Certification Test for Managing Projects for Business Success (Advanced)",
                "label": "Advanced",
            },
        },
        "status_mapping": {
            "training_completed_values": ["completed"],
            "project_active_statuses": ["Not Completed"],
            "project_excluded_statuses": ["Completed", "Cancelled"],
            "project_completed_stages": ["Completed"],
        },
    }


# --- Compliance Extraction Tests ---

def test_extract_compliance_issues_finds_non_compliant():
    eppm_df = pd.DataFrame([{
        "project_name": "Project Alpha", "project_number": "PRJ001",
        "g0_compliance": "N/A", "g0_action": "N/A",
        "g3_compliance": "Partially compliant", "g3_action": "Stakeholder Agreement needed",
        "g5_compliance": "N/A", "g5_action": "N/A",
        "g6_compliance": "N/A", "g6_action": "N/A",
        "project_compliance": "Partially compliant",
        "it_project_manager_email": "maya@corp.example",
        "project_manager_email": "daniel@corp.example",
    }])
    issues = extract_pm_compliance_issues(eppm_df)
    assert "maya@corp.example" in issues
    assert len(issues["maya@corp.example"]) == 1
    assert issues["maya@corp.example"][0]["gate"] == "G3"
    assert issues["maya@corp.example"][0]["action_needed"] == "Stakeholder Agreement needed"


def test_extract_compliance_issues_skips_full_compliance():
    eppm_df = pd.DataFrame([{
        "project_name": "Good Project", "project_number": "PRJ002",
        "g0_compliance": "Full compliance", "g0_action": "No action required",
        "g3_compliance": "N/A", "g3_action": "N/A",
        "g5_compliance": "N/A", "g5_action": "N/A",
        "g6_compliance": "N/A", "g6_action": "N/A",
        "project_compliance": "Full compliance",
        "it_project_manager_email": "maya@corp.example",
        "project_manager_email": "daniel@corp.example",
    }])
    issues = extract_pm_compliance_issues(eppm_df)
    assert "maya@corp.example" not in issues


def test_extract_compliance_issues_skips_na():
    eppm_df = pd.DataFrame([{
        "project_name": "NA Project", "project_number": "PRJ003",
        "g0_compliance": "N/A", "g0_action": "N/A",
        "g3_compliance": "N/A", "g3_action": "N/A",
        "g5_compliance": "N/A", "g5_action": "N/A",
        "g6_compliance": "N/A", "g6_action": "N/A",
        "project_compliance": "N/A",
        "it_project_manager_email": "maya@corp.example",
        "project_manager_email": "daniel@corp.example",
    }])
    issues = extract_pm_compliance_issues(eppm_df)
    assert len(issues) == 0


def test_extract_compliance_multiple_gates():
    eppm_df = pd.DataFrame([{
        "project_name": "Big Issues", "project_number": "PRJ004",
        "g0_compliance": "Non-compliant", "g0_action": "Create entry in LeanIX",
        "g3_compliance": "Partially compliant", "g3_action": "Stakeholder Agreement needed",
        "g5_compliance": "N/A", "g5_action": "N/A",
        "g6_compliance": "N/A", "g6_action": "N/A",
        "project_compliance": "Non-compliant",
        "it_project_manager_email": "itpm@corp.example",
        "project_manager_email": "pm@corp.example",
    }])
    issues = extract_pm_compliance_issues(eppm_df)
    # Both IT PM and PM get the same issues (2 gates each)
    assert len(issues["itpm@corp.example"]) == 2
    assert len(issues["pm@corp.example"]) == 2
    gates = {i["gate"] for i in issues["itpm@corp.example"]}
    assert "G0" in gates
    assert "G3" in gates


# --- Ghost Project Filter Tests ---

def test_filter_ghost_by_status():
    config = make_config()
    eppm_df = pd.DataFrame([
        {"project_number": "PRJ001", "project_status": "Not Completed", "active_stage": "G3"},
        {"project_number": "PRJ002", "project_status": "Completed", "active_stage": "Completed"},
        {"project_number": "PRJ003", "project_status": "Cancelled", "active_stage": "G1"},
    ])
    filtered, count, details = filter_ghost_projects(eppm_df, None, config)
    assert len(filtered) == 1
    assert filtered.iloc[0]["project_number"] == "PRJ001"
    assert count == 2
    assert details["excluded_status"] == 2


def test_filter_ghost_by_stage():
    config = make_config()
    eppm_df = pd.DataFrame([
        {"project_number": "PRJ001", "project_status": "Not Completed", "active_stage": "G5"},
        {"project_number": "PRJ002", "project_status": "Not Completed", "active_stage": "Completed"},
    ])
    filtered, count, details = filter_ghost_projects(eppm_df, None, config)
    assert len(filtered) == 1
    assert details["completed_stage"] == 1


def test_filter_ghost_by_manual_list():
    config = make_config()
    eppm_df = pd.DataFrame([
        {"project_number": "PRJ001", "project_status": "Not Completed", "active_stage": "G3"},
        {"project_number": "PRJ002", "project_status": "Not Completed", "active_stage": "G5"},
    ])
    excluded = pd.DataFrame([{"project_id": "PRJ002", "reason": "Cancelled"}])
    filtered, count, details = filter_ghost_projects(eppm_df, excluded, config)
    assert len(filtered) == 1
    assert details["manual_exclusion"] == 1


def test_filter_ghost_no_exclusions():
    config = make_config()
    eppm_df = pd.DataFrame([
        {"project_number": "PRJ001", "project_status": "Not Completed", "active_stage": "G3"},
    ])
    filtered, count, details = filter_ghost_projects(eppm_df, None, config)
    assert len(filtered) == 1
    assert count == 0


# --- Nice-to-Have Tests ---

def test_advanced_done_makes_fundamentals_nice_to_have():
    config = make_config()
    training = pd.DataFrame([
        {"content_title": "Certification Test for Managing Projects for Business Success (Advanced)",
         "course_status": "completed", "completion_date": "2026-02-01"},
    ])
    matched = [{
        "full_name": "Test PM", "email": "test@corp.example",
        "normalized_name": "test pm", "normalized_email": "test@corp.example",
        "match_method": "email", "training_indices": [0],
    }]
    result = evaluate_training(matched, training, config)
    assert result[0]["all_complete"] is True
    assert result[0]["missing_trainings"] == []
    assert "Fundamentals" in result[0]["nice_to_have_trainings"]


def test_nice_to_have_pm_tracked_in_eligibility():
    config = make_config()
    evaluated = [
        {"full_name": "NTH PM", "email": "nth@corp.example",
         "normalized_name": "nth pm", "normalized_email": "nth@corp.example",
         "all_complete": True, "missing_trainings": [],
         "nice_to_have_trainings": ["Fundamentals"]},
    ]
    all_pms = pd.DataFrame([
        {"email": "nth@corp.example", "normalized_name": "nth pm",
         "project_status": "Not Completed"},
    ])
    eligible, complete, inactive, nice_to_have = get_eligible_pms(evaluated, all_pms, config)
    assert len(eligible) == 0
    assert len(nice_to_have) == 1
    assert nice_to_have[0]["full_name"] == "NTH PM"


def test_both_complete_no_nice_to_have():
    config = make_config()
    training = pd.DataFrame([
        {"content_title": "Managing Projects for Business Success - Fundamentals - Certification Test",
         "course_status": "completed", "completion_date": "2026-01-15"},
        {"content_title": "Certification Test for Managing Projects for Business Success (Advanced)",
         "course_status": "completed", "completion_date": "2026-02-01"},
    ])
    matched = [{
        "full_name": "Both Done", "email": "both@corp.example",
        "normalized_name": "both done", "normalized_email": "both@corp.example",
        "match_method": "email", "training_indices": [0, 1],
    }]
    result = evaluate_training(matched, training, config)
    assert result[0]["all_complete"] is True
    assert result[0]["nice_to_have_trainings"] == []
