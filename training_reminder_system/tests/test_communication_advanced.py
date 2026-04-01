"""Tests for communication — escalation, missing ITPM, role-change, compliance in templates."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.communication import (
    render_reminder,
    generate_reminders,
    _was_pm_previously_reminded_itpm,
    generate_missing_itpm_reminders,
    generate_role_changed_reminders,
)
from src.repository import Database


def make_config():
    base = os.path.join(os.path.dirname(__file__), "..")
    return {
        "templates": {
            "stage_1": os.path.join(base, "templates", "reminder_stage_1.txt"),
            "stage_2": os.path.join(base, "templates", "reminder_stage_2.txt"),
            "stage_3": os.path.join(base, "templates", "reminder_stage_3.txt"),
            "default": os.path.join(base, "templates", "reminder_stage_default.txt"),
            "missing_itpm": os.path.join(base, "templates", "missing_itpm_reminder.txt"),
            "missing_itpm_escalation": os.path.join(base, "templates", "missing_itpm_escalation.txt"),
            "role_changed_itpm": os.path.join(base, "templates", "role_changed_itpm_reminder.txt"),
        },
        "communication": {"max_reminder_stage": 0},
    }


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


# --- Compliance in Templates ---

def test_render_with_compliance_issues():
    config = make_config()
    issues = [
        {"project_name": "Alpha", "project_id": "PRJ001",
         "gate": "G3", "compliance_status": "Partially compliant",
         "action_needed": "Stakeholder Agreement needed"},
    ]
    result = render_reminder(
        "Maya Collins", "maya@corp.example", ["Advanced"], 1, config,
        compliance_issues=issues,
    )
    assert "Stakeholder Agreement needed" in result["body"]
    assert "Alpha" in result["body"]
    assert "G3" in result["body"]


def test_render_without_compliance_issues():
    config = make_config()
    result = render_reminder(
        "Maya Collins", "maya@corp.example", ["Advanced"], 1, config,
        compliance_issues=[],
    )
    assert "compliance items" not in result["body"]


def test_render_stage3_compliance_covers_specifics():
    config = make_config()
    issues = [
        {"project_name": "Beta", "project_id": "PRJ002",
         "gate": "G5", "compliance_status": "Non-compliant",
         "action_needed": "Transition Plan and G5 security review needed"},
    ]
    result = render_reminder(
        "Test PM", "test@corp.example", ["Fundamentals", "Advanced"], 3, config,
        compliance_issues=issues,
    )
    assert "Transition Plan" in result["body"]
    assert "Stakeholder Agreements" in result["body"]  # Stage 3 template mentions these


# --- Nice-to-Have in Templates ---

def test_render_passes_nice_to_have():
    config = make_config()
    result = render_reminder(
        "Test PM", "test@corp.example", ["Advanced"], 1, config,
        nice_to_have_trainings=["Fundamentals"],
    )
    assert result["body"]  # Should render without error


# --- Escalation Logic ---

def test_was_pm_previously_reminded_first_time():
    db, path = make_db()
    db.start_cycle()
    assert _was_pm_previously_reminded_itpm("new@corp.example", db) is False
    db.close()
    os.unlink(path)


def test_was_pm_previously_reminded_after_reminder():
    db, path = make_db()
    cycle_id = db.start_cycle()
    pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")
    db.insert_communication(cycle_id, pm_id, 0, "Subject", "Body")  # Stage 0 = ITPM reminder

    assert _was_pm_previously_reminded_itpm("test@corp.example", db) is True
    db.close()
    os.unlink(path)


def test_missing_itpm_first_time_sends_to_pm():
    db, path = make_db()
    config = make_config()
    cycle_id = db.start_cycle()

    missing_list = [{
        "pm_name": "Maya Collins",
        "pm_email": "maya@corp.example",
        "projects": [
            {"project_name": "Project A", "project_id": "PRJ001",
             "owner_name": "Boss", "owner_email": "boss@corp.example"},
        ],
    }]

    pm_rem, esc_rem = generate_missing_itpm_reminders(missing_list, db, cycle_id, config)
    assert len(pm_rem) == 1
    assert len(esc_rem) == 0  # First time — no escalation
    assert pm_rem[0]["recipient_email"] == "maya@corp.example"

    db.close()
    os.unlink(path)


def test_missing_itpm_escalates_on_repeat():
    db, path = make_db()
    config = make_config()

    # Cycle 1: First reminder
    c1 = db.start_cycle()
    missing_list = [{
        "pm_name": "Maya Collins",
        "pm_email": "maya@corp.example",
        "projects": [
            {"project_name": "Project A", "project_id": "PRJ001",
             "owner_name": "Boss", "owner_email": "boss@corp.example"},
        ],
    }]
    generate_missing_itpm_reminders(missing_list, db, c1, config)

    # Cycle 2: Same issue — should escalate to owner
    c2 = db.start_cycle()
    pm_rem, esc_rem = generate_missing_itpm_reminders(missing_list, db, c2, config)
    assert len(pm_rem) == 1  # PM still gets reminded
    assert len(esc_rem) == 1  # Owner gets escalation
    assert esc_rem[0]["recipient_email"] == "boss@corp.example"

    db.close()
    os.unlink(path)


# --- Role Change Reminders ---

def test_role_changed_generates_reminder():
    db, path = make_db()
    config = make_config()
    cycle_id = db.start_cycle()

    role_changed_list = [{
        "pm_name": "Maya Collins",
        "pm_email": "maya@corp.example",
        "projects": [
            {"project_name": "Project A", "project_id": "PRJ001",
             "it_pm_name": "Daniel Carter", "it_pm_email": "daniel@corp.example",
             "current_position": "Data Engineer"},
        ],
    }]

    result = generate_role_changed_reminders(role_changed_list, db, cycle_id, config)
    assert len(result) == 1
    assert result[0]["recipient_email"] == "maya@corp.example"
    assert "Daniel Carter" in result[0]["body"]
    assert "Data Engineer" in result[0]["body"]

    db.close()
    os.unlink(path)


# --- Generate Reminders with Compliance ---

def test_generate_reminders_passes_compliance():
    db, path = make_db()
    config = make_config()
    cycle_id = db.start_cycle()

    eligible_pms = [{
        "full_name": "Maya Collins",
        "email": "maya@corp.example",
        "normalized_name": "maya collins",
        "normalized_email": "maya@corp.example",
        "missing_trainings": ["Advanced"],
        "nice_to_have_trainings": [],
    }]
    compliance = {
        "maya@corp.example": [
            {"project_name": "Test", "project_id": "PRJ001",
             "gate": "G3", "compliance_status": "Partially compliant",
             "action_needed": "Stakeholder Agreement needed"},
        ],
    }

    reminders, skipped = generate_reminders(eligible_pms, db, cycle_id, config, compliance)
    assert len(reminders) == 1
    assert "Stakeholder Agreement" in reminders[0]["body"]

    db.close()
    os.unlink(path)
