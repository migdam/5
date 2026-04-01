import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.evaluator import evaluate_training, get_eligible_pms


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
        },
    }


def make_training_df(records):
    return pd.DataFrame(records)


def test_all_complete():
    """PM with both trainings completed."""
    training = make_training_df([
        {"content_title": "Managing Projects for Business Success - Fundamentals - Certification Test",
         "course_status": "completed", "completion_date": "2026-01-15"},
        {"content_title": "Certification Test for Managing Projects for Business Success (Advanced)",
         "course_status": "completed", "completion_date": "2026-02-01"},
    ])
    matched = [{
        "full_name": "Maya Collins", "email": "maya@corp.example",
        "normalized_name": "maya collins", "normalized_email": "maya@corp.example",
        "match_method": "email", "training_indices": [0, 1],
    }]
    result = evaluate_training(matched, training, make_config())
    assert len(result) == 1
    assert result[0]["all_complete"] is True
    assert result[0]["missing_trainings"] == []


def test_fundamentals_missing():
    """PM with only advanced completed."""
    training = make_training_df([
        {"content_title": "Certification Test for Managing Projects for Business Success (Advanced)",
         "course_status": "completed", "completion_date": "2026-02-01"},
    ])
    matched = [{
        "full_name": "Daniel Carter", "email": "daniel@corp.example",
        "normalized_name": "daniel carter", "normalized_email": "daniel@corp.example",
        "match_method": "email", "training_indices": [0],
    }]
    result = evaluate_training(matched, training, make_config())
    assert result[0]["all_complete"] is False
    assert "Fundamentals" in result[0]["missing_trainings"]


def test_both_missing():
    """PM with no relevant training records."""
    training = make_training_df([
        {"content_title": "Some Other Course", "course_status": "completed",
         "completion_date": "2026-01-01"},
    ])
    matched = [{
        "full_name": "Liam Parker", "email": "liam@corp.example",
        "normalized_name": "liam parker", "normalized_email": "liam@corp.example",
        "match_method": "email", "training_indices": [0],
    }]
    result = evaluate_training(matched, training, make_config())
    assert result[0]["all_complete"] is False
    assert len(result[0]["missing_trainings"]) == 2


def test_incomplete_not_counted():
    """PM with fundamentals incomplete should still show as missing."""
    training = make_training_df([
        {"content_title": "Managing Projects for Business Success - Fundamentals - Certification Test",
         "course_status": "incomplete", "completion_date": None},
    ])
    matched = [{
        "full_name": "Test PM", "email": "test@corp.example",
        "normalized_name": "test pm", "normalized_email": "test@corp.example",
        "match_method": "email", "training_indices": [0],
    }]
    result = evaluate_training(matched, training, make_config())
    assert result[0]["fundamentals_completed"] is False
    assert "Fundamentals" in result[0]["missing_trainings"]


def test_get_eligible_filters_inactive():
    """PMs on completed projects should be filtered out."""
    config = make_config()
    evaluated = [
        {"full_name": "Active PM", "email": "active@corp.example",
         "normalized_name": "active pm", "normalized_email": "active@corp.example",
         "all_complete": False, "missing_trainings": ["Fundamentals"]},
        {"full_name": "Inactive PM", "email": "inactive@corp.example",
         "normalized_name": "inactive pm", "normalized_email": "inactive@corp.example",
         "all_complete": False, "missing_trainings": ["Advanced"]},
    ]
    all_pms = pd.DataFrame([
        {"email": "active@corp.example", "normalized_name": "active pm",
         "project_status": "Not Completed"},
        {"email": "inactive@corp.example", "normalized_name": "inactive pm",
         "project_status": "Completed"},
    ])
    eligible, skipped_complete, skipped_inactive = get_eligible_pms(evaluated, all_pms, config)
    assert len(eligible) == 1
    assert eligible[0]["full_name"] == "Active PM"
    assert skipped_inactive == 1
