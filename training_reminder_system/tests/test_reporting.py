"""Tests for reporting — output file generation."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.reporting import generate_outputs, _safe_filename


def make_config(tmpdir):
    return {
        "paths": {"output_folder": os.path.join(tmpdir, "output")},
        "output": {
            "generate_per_recipient_files": True,
            "generate_per_stage_folders": True,
            "generate_csv": True,
            "generate_summary": True,
            "generate_group_emails": True,
        },
        "templates": {},
    }


def make_reminder(name, email, stage=1, missing=None):
    if missing is None:
        missing = ["Fundamentals"]
    return {
        "recipient_email": email,
        "subject": f"Training Reminder Stage {stage}",
        "body": f"Dear {name}, please complete training.",
        "stage": stage,
        "name": name,
        "missing_trainings": missing,
    }


def make_itpm_reminder(pm_name, pm_email, projects):
    return {
        "recipient_email": pm_email,
        "subject": "Assign IT PM",
        "body": f"Dear {pm_name}, assign IT PM.",
        "stage": 0,
        "name": pm_name,
        "missing_trainings": [],
        "reminder_type": "missing_itpm",
        "projects": projects,
        "project_list": ", ".join(f"{p['project_name']} ({p['project_id']})" for p in projects),
    }


# --- Output Generation Tests ---

def test_generate_outputs_creates_folder():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    reminders = [make_reminder("Maya Collins", "maya@corp.example")]
    summary = {"cycle_id": 1, "total_pms_in_eppm": 10, "reminders_generated": 1}

    output_dir = generate_outputs(reminders, summary, config, 1)
    assert os.path.exists(output_dir)
    assert os.path.exists(os.path.join(output_dir, "summary_report.md"))
    shutil.rmtree(tmpdir)


def test_generate_outputs_creates_csv():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    reminders = [make_reminder("Maya Collins", "maya@corp.example")]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs(reminders, summary, config, 1)
    csv_path = os.path.join(output_dir, "reminders.csv")
    assert os.path.exists(csv_path)
    with open(csv_path) as f:
        lines = f.readlines()
    assert len(lines) == 2  # Header + 1 reminder
    assert "maya@corp.example" in lines[1]
    shutil.rmtree(tmpdir)


def test_generate_outputs_per_stage_folders():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    reminders = [
        make_reminder("Maya", "maya@example.com", stage=1),
        make_reminder("Daniel", "daniel@example.com", stage=2),
    ]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs(reminders, summary, config, 1)
    assert os.path.exists(os.path.join(output_dir, "stage_1"))
    assert os.path.exists(os.path.join(output_dir, "stage_2"))
    s1_files = os.listdir(os.path.join(output_dir, "stage_1"))
    assert len(s1_files) == 1
    shutil.rmtree(tmpdir)


def test_generate_outputs_per_recipient():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    reminders = [make_reminder("Maya Collins", "maya@example.com")]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs(reminders, summary, config, 1)
    recip_dir = os.path.join(output_dir, "per_recipient")
    assert os.path.exists(recip_dir)
    files = os.listdir(recip_dir)
    assert any("maya" in f for f in files)
    shutil.rmtree(tmpdir)


def test_generate_outputs_missing_itpm():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    itpm_reminders = [make_itpm_reminder("PM1", "pm1@example.com", [
        {"project_name": "Project A", "project_id": "PRJ001"},
    ])]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs([], summary, config, 1, missing_itpm_reminders=itpm_reminders)
    itpm_dir = os.path.join(output_dir, "missing_itpm")
    assert os.path.exists(itpm_dir)
    files = os.listdir(itpm_dir)
    assert any("pm1" in f for f in files)
    assert any("csv" in f for f in files)
    shutil.rmtree(tmpdir)


def test_generate_outputs_escalations():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    escalations = [{
        "recipient_email": "owner@example.com",
        "subject": "Escalation",
        "body": "Dear Owner, please help.",
        "stage": -1,
        "name": "Owner Name",
        "missing_trainings": [],
        "reminder_type": "missing_itpm_escalation",
        "projects": [{"project_name": "Proj", "project_id": "PRJ001"}],
        "project_list": "Proj (PRJ001)",
        "pm_name": "PM Name",
        "pm_email": "pm@example.com",
    }]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs([], summary, config, 1, escalation_reminders=escalations)
    esc_dir = os.path.join(output_dir, "escalations_to_owner")
    assert os.path.exists(esc_dir)
    files = os.listdir(esc_dir)
    assert len(files) >= 2  # At least one .txt + CSV
    shutil.rmtree(tmpdir)


def test_generate_outputs_role_changed():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    role_changed = [{
        "recipient_email": "pm@example.com",
        "subject": "Role Changed",
        "body": "Dear PM, IT PM changed roles.",
        "stage": 0,
        "name": "PM Name",
        "missing_trainings": [],
        "reminder_type": "role_changed_itpm",
        "projects": [{"project_name": "Proj", "project_id": "PRJ001",
                       "it_pm_name": "Old ITPM", "current_position": "Data Engineer"}],
        "project_list": "Proj - Old ITPM now Data Engineer",
    }]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs([], summary, config, 1, role_changed_reminders=role_changed)
    rc_dir = os.path.join(output_dir, "role_changed_itpm")
    assert os.path.exists(rc_dir)
    shutil.rmtree(tmpdir)


def test_generate_outputs_nice_to_have():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    nth_pms = [{
        "full_name": "Lena Collins",
        "email": "lena@corp.example",
        "nice_to_have_trainings": ["Fundamentals"],
    }]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs([], summary, config, 1, nice_to_have_pms=nth_pms)
    nth_dir = os.path.join(output_dir, "nice_to_have")
    assert os.path.exists(nth_dir)
    with open(os.path.join(nth_dir, "nice_to_have_summary.txt")) as f:
        content = f.read()
    assert "Lena Collins" in content
    assert "Fundamentals" in content
    shutil.rmtree(tmpdir)


def test_generate_outputs_group_emails():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    reminders = [
        make_reminder("Maya", "maya@example.com", stage=1),
        make_reminder("Daniel", "daniel@example.com", stage=1),
    ]
    summary = {"cycle_id": 1}

    output_dir = generate_outputs(reminders, summary, config, 1)
    group_dir = os.path.join(output_dir, "group_emails")
    assert os.path.exists(group_dir)
    files = os.listdir(group_dir)
    assert any("group_training" in f for f in files)
    assert any("recipients" in f for f in files)

    # Check recipients file has both emails
    recip_file = [f for f in files if "training_recipients" in f][0]
    with open(os.path.join(group_dir, recip_file)) as f:
        content = f.read()
    assert "maya@example.com" in content
    assert "daniel@example.com" in content
    shutil.rmtree(tmpdir)


def test_generate_outputs_summary_report_content():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    summary = {
        "cycle_id": 5,
        "total_pms_in_eppm": 150,
        "matched_pms": 80,
        "training_reminders_generated": 45,
    }

    output_dir = generate_outputs([], summary, config, 5)
    with open(os.path.join(output_dir, "summary_report.md")) as f:
        content = f.read()
    assert "Cycle 5" in content
    assert "150" in content
    assert "80" in content
    assert "45" in content
    shutil.rmtree(tmpdir)


def test_generate_outputs_empty_reminders():
    tmpdir = tempfile.mkdtemp()
    config = make_config(tmpdir)
    summary = {"cycle_id": 1}

    output_dir = generate_outputs([], summary, config, 1)
    assert os.path.exists(output_dir)
    # Summary should still be created
    assert os.path.exists(os.path.join(output_dir, "summary_report.md"))
    # But no CSV or stage folders
    assert not os.path.exists(os.path.join(output_dir, "reminders.csv"))
    shutil.rmtree(tmpdir)


# --- Helper Tests ---

def test_safe_filename():
    assert _safe_filename("Maya Collins") == "maya_collins"
    assert _safe_filename("Daniel O'Brien") == "daniel_obrien"
    assert _safe_filename("Test-Name 123") == "testname_123"
