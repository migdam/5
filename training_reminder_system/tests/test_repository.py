"""Tests for SQLite repository — cycle management and revert."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.repository import Database


def make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return Database(path), path


def test_start_and_complete_cycle():
    db, path = make_db()
    cycle_id = db.start_cycle()
    assert cycle_id >= 1
    row = db.conn.execute("SELECT run_status FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    assert row["run_status"] == "running"

    db.complete_cycle(cycle_id, "completed", "test notes")
    row = db.conn.execute("SELECT run_status, notes FROM cycles WHERE id = ?", (cycle_id,)).fetchone()
    assert row["run_status"] == "completed"
    assert row["notes"] == "test notes"
    db.close()
    os.unlink(path)


def test_revert_cycle_removes_all_data():
    db, path = make_db()
    cycle_id = db.start_cycle()

    # Insert data into multiple tables
    pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")
    db.insert_assignment_snapshot(cycle_id, pm_id, "Project A", "PRJ001", "Not Completed", "test.xlsx")
    db.insert_training_snapshot(cycle_id, pm_id, "completed", "incomplete", None, None, "incomplete", "fuse.xlsx")
    db.insert_communication(cycle_id, pm_id, 1, "Subject", "Body")
    db.insert_data_quality_issue(cycle_id, "test_issue", "Test PM", "test@corp.example", "details")
    db.record_processed_file(cycle_id, "eppm", "test.xlsx", "archived.xlsx", "/archive", None)

    # Verify data exists
    assert db.conn.execute("SELECT COUNT(*) FROM assignment_snapshots WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM communication_history WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 1

    # Revert
    db.revert_cycle(cycle_id)

    # Verify all cycle data gone
    assert db.conn.execute("SELECT COUNT(*) FROM cycles WHERE id = ?", (cycle_id,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM assignment_snapshots WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM training_snapshots WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM communication_history WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM data_quality_issues WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM processed_files WHERE cycle_id = ?", (cycle_id,)).fetchone()[0] == 0

    # PM record should still exist (not cycle-specific)
    assert db.conn.execute("SELECT COUNT(*) FROM project_managers").fetchone()[0] == 1

    db.close()
    os.unlink(path)


def test_revert_doesnt_affect_other_cycles():
    db, path = make_db()

    # Create two cycles
    c1 = db.start_cycle()
    pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")
    db.insert_communication(c1, pm_id, 1, "Cycle 1 Subject", "Cycle 1 Body")
    db.complete_cycle(c1, "completed")

    c2 = db.start_cycle()
    db.insert_communication(c2, pm_id, 2, "Cycle 2 Subject", "Cycle 2 Body")

    # Revert cycle 2
    db.revert_cycle(c2)

    # Cycle 1 data should be intact
    assert db.conn.execute("SELECT COUNT(*) FROM cycles WHERE id = ?", (c1,)).fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM communication_history WHERE cycle_id = ?", (c1,)).fetchone()[0] == 1

    # Cycle 2 gone
    assert db.conn.execute("SELECT COUNT(*) FROM cycles WHERE id = ?", (c2,)).fetchone()[0] == 0

    db.close()
    os.unlink(path)


def test_upsert_project_manager():
    db, path = make_db()

    # First insert
    pm_id1 = db.upsert_project_manager("Maya Collins", "maya@corp.example", "maya collins")
    assert pm_id1 >= 1

    # Same email — should return same ID
    pm_id2 = db.upsert_project_manager("Maya Collins", "maya@corp.example", "maya collins")
    assert pm_id1 == pm_id2

    db.close()
    os.unlink(path)


def test_training_snapshot_with_audit_fields():
    """Verify new audit columns are stored and retrievable."""
    db, path = make_db()
    cycle_id = db.start_cycle()
    pm_id = db.upsert_project_manager("Test PM", "test@corp.example", "test pm")

    db.insert_training_snapshot(
        cycle_id, pm_id, "completed", "incomplete", "2026-01-15", None, "incomplete", "fuse.xlsx",
        match_method="email",
        missing_trainings=["Advanced"],
        nice_to_have_trainings=[],
        compliance_issues_json=[
            {"project_name": "Proj A", "project_id": "PRJ001",
             "gate": "G3", "compliance_status": "Non-compliant",
             "action_needed": "Stakeholder Agreement needed"},
        ],
        eligibility_status="eligible",
    )

    row = db.conn.execute(
        "SELECT match_method, missing_trainings, nice_to_have_trainings, "
        "compliance_issues_json, eligibility_status "
        "FROM training_snapshots WHERE cycle_id = ? AND project_manager_id = ?",
        (cycle_id, pm_id),
    ).fetchone()

    assert row["match_method"] == "email"
    assert '"Advanced"' in row["missing_trainings"]
    assert row["eligibility_status"] == "eligible"
    assert "Non-compliant" in row["compliance_issues_json"]
    assert "Stakeholder Agreement" in row["compliance_issues_json"]

    db.close()
    os.unlink(path)


def test_training_snapshot_audit_fields_optional():
    """Audit fields should be optional (backward compat with old callers)."""
    db, path = make_db()
    cycle_id = db.start_cycle()
    pm_id = db.upsert_project_manager("Test", "test@corp.example", "test")

    # Old-style call without audit fields — should work
    db.insert_training_snapshot(
        cycle_id, pm_id, "completed", "completed", None, None, "complete", "fuse.xlsx"
    )

    row = db.conn.execute(
        "SELECT match_method, eligibility_status FROM training_snapshots WHERE cycle_id = ?",
        (cycle_id,),
    ).fetchone()
    assert row["match_method"] is None
    assert row["eligibility_status"] is None

    db.close()
    os.unlink(path)


def test_reminder_stage_progression():
    db, path = make_db()
    c1 = db.start_cycle()
    pm_id = db.upsert_project_manager("Test", "test@corp.example", "test")

    # No history — stage should be 0
    assert db.get_last_reminder_stage(pm_id) == 0

    # Insert stage 1
    db.insert_communication(c1, pm_id, 1, "Sub", "Body")
    assert db.get_last_reminder_stage(pm_id) == 1

    # Insert stage 2
    c2 = db.start_cycle()
    db.insert_communication(c2, pm_id, 2, "Sub2", "Body2")
    assert db.get_last_reminder_stage(pm_id) == 2

    db.close()
    os.unlink(path)
