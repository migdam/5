import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.communication import render_reminder, determine_reminder_stage, get_template_for_stage
from src.repository import Database


def make_config():
    base = os.path.join(os.path.dirname(__file__), "..")
    return {
        "templates": {
            "stage_1": os.path.join(base, "templates", "reminder_stage_1.txt"),
            "stage_2": os.path.join(base, "templates", "reminder_stage_2.txt"),
            "stage_3": os.path.join(base, "templates", "reminder_stage_3.txt"),
            "default": os.path.join(base, "templates", "reminder_stage_default.txt"),
        },
        "communication": {"max_reminder_stage": 0},
    }


def test_render_stage_1():
    """Test that stage 1 template renders correctly with placeholders."""
    config = make_config()
    result = render_reminder(
        name="Maya Collins",
        email="maya.collins@corp.example",
        missing_trainings=["Fundamentals", "Advanced"],
        stage=1,
        config=config,
    )
    assert result["recipient_email"] == "maya.collins@corp.example"
    assert result["stage"] == 1
    assert "Maya Collins" in result["body"]
    assert "Fundamentals, Advanced" in result["body"]
    assert result["subject"]  # subject is not empty


def test_render_stage_2():
    config = make_config()
    result = render_reminder("Daniel Carter", "daniel@corp.example", ["Advanced"], 2, config)
    assert result["stage"] == 2
    assert "Daniel Carter" in result["body"]
    assert "Advanced" in result["body"]


def test_render_default_stage():
    """Stage 4+ should use the default template."""
    config = make_config()
    result = render_reminder("Test PM", "test@corp.example", ["Fundamentals"], 5, config)
    assert result["stage"] == 5
    assert "Stage 5" in result["subject"] or "5" in result["subject"]


def test_determine_stage_first_time():
    """First reminder should be stage 1."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")
        stage = determine_reminder_stage(pm_id, db)
        assert stage == 1
        db.close()
    finally:
        os.unlink(db_path)


def test_determine_stage_progression():
    """After stage 1 reminder, next should be stage 2."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        db = Database(db_path)
        cycle_id = db.start_cycle()
        pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")
        db.insert_communication(cycle_id, pm_id, 1, "Subject", "Body")

        stage = determine_reminder_stage(pm_id, db)
        assert stage == 2
        db.close()
    finally:
        os.unlink(db_path)


def test_get_template_for_stage():
    config = make_config()
    assert get_template_for_stage(1, config) == config["templates"]["stage_1"]
    assert get_template_for_stage(2, config) == config["templates"]["stage_2"]
    assert get_template_for_stage(3, config) == config["templates"]["stage_3"]
    assert get_template_for_stage(4, config) == config["templates"]["default"]
    assert get_template_for_stage(10, config) == config["templates"]["default"]
