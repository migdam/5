"""Tests for streamlit_app.py helper functions and page logic.

These tests exercise the non-Streamlit logic (DB queries, data transforms,
file operations) used by the Streamlit UI pages, without needing a running
Streamlit server.
"""

import io
import json
import os
import sqlite3
import tempfile
import zipfile

import pandas as pd
import pytest
import yaml

# Add project root to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.repository import Database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database with realistic test data."""
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)

    # Cycle 1
    cycle_1 = db.start_cycle()
    pm1_id = db.upsert_project_manager("Alice Smith", "alice@example.com", "alice smith")
    pm2_id = db.upsert_project_manager("Bob Jones", "bob@example.com", "bob jones")
    pm3_id = db.upsert_project_manager("Carol White", "carol@example.com", "carol white")

    db.insert_assignment_snapshot(cycle_1, pm1_id, "Project Alpha", "P001", "Not Completed", "eppm.xlsx")
    db.insert_assignment_snapshot(cycle_1, pm2_id, "Project Beta", "P002", "Not Completed", "eppm.xlsx")
    db.insert_assignment_snapshot(cycle_1, pm3_id, "Project Gamma", "P003", "Not Completed", "eppm.xlsx")

    db.insert_training_snapshot(cycle_1, pm1_id, "incomplete", "incomplete", None, None, "incomplete", "fuse.xlsx",
                                match_method="email", missing_trainings=["Fundamentals", "Advanced"],
                                eligibility_status="eligible")
    db.insert_training_snapshot(cycle_1, pm2_id, "completed", "incomplete", "2026-01-01", None, "incomplete", "fuse.xlsx",
                                match_method="email", missing_trainings=["Advanced"],
                                eligibility_status="eligible")
    db.insert_training_snapshot(cycle_1, pm3_id, "completed", "completed", "2026-01-01", "2026-02-01", "complete", "fuse.xlsx",
                                match_method="name", eligibility_status="skipped_complete")

    db.insert_communication(cycle_1, pm1_id, 1, "Training Reminder", "Dear Alice...", "prepared")
    db.insert_communication(cycle_1, pm2_id, 1, "Training Reminder", "Dear Bob...", "prepared")

    db.insert_data_quality_issue(cycle_1, "unmatched_pm", "Dave Unknown", "dave@example.com", "Could not match")
    db.insert_data_quality_issue(cycle_1, "unmatched_pm", "Eve Missing", None, "No email provided")

    compliance_issues = [{"project_id": "P001", "project_name": "Project Alpha", "gate": "G3", "compliance_status": "Non-Compliant"}]
    db.insert_training_snapshot(cycle_1, pm1_id, "incomplete", "incomplete", None, None, "incomplete", "fuse.xlsx",
                                compliance_issues_json=compliance_issues)

    db.complete_cycle(cycle_1, "completed", "Test cycle 1")

    # Cycle 2
    cycle_2 = db.start_cycle()
    db.insert_assignment_snapshot(cycle_2, pm1_id, "Project Alpha", "P001", "Not Completed", "eppm2.xlsx")
    db.insert_assignment_snapshot(cycle_2, pm2_id, "Project Beta", "P002", "Not Completed", "eppm2.xlsx")
    db.insert_assignment_snapshot(cycle_2, pm2_id, "Project Delta", "P004", "Not Completed", "eppm2.xlsx")

    db.insert_training_snapshot(cycle_2, pm1_id, "completed", "completed", "2026-03-01", "2026-03-15", "complete", "fuse2.xlsx",
                                match_method="email", eligibility_status="skipped_complete")
    db.insert_training_snapshot(cycle_2, pm2_id, "completed", "incomplete", "2026-01-01", None, "incomplete", "fuse2.xlsx",
                                match_method="email", missing_trainings=["Advanced"],
                                eligibility_status="eligible")

    db.insert_communication(cycle_2, pm1_id, 99, "Congratulations!", "Dear Alice, congrats!", "prepared")
    db.insert_communication(cycle_2, pm2_id, 2, "Training Reminder Stage 2", "Dear Bob...", "prepared")

    db.complete_cycle(cycle_2, "completed", "Test cycle 2")

    db.close()
    return db_path


@pytest.fixture
def db_conn(tmp_db):
    """Return a connection to the test database."""
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Test: zip_directory helper
# ---------------------------------------------------------------------------

def test_zip_directory(tmp_path):
    """Test that zip_directory creates a valid zip."""
    # Import the function
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

    # Create test directory with files
    test_dir = tmp_path / "output"
    test_dir.mkdir()
    (test_dir / "summary.md").write_text("# Summary\n")
    sub = test_dir / "stage_1"
    sub.mkdir()
    (sub / "alice.txt").write_text("Dear Alice...\n")

    # Use the zip_directory function
    from streamlit_app import zip_directory
    buf = zip_directory(str(test_dir))

    # Verify zip contents
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()
        assert "summary.md" in names
        assert os.path.join("stage_1", "alice.txt") in names


# ---------------------------------------------------------------------------
# Test: Dashboard queries
# ---------------------------------------------------------------------------

class TestDashboardQueries:
    def test_certification_rate(self, db_conn):
        """Test % certified query returns correct counts."""
        row = db_conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN overall_training_status = 'complete' THEN 1 ELSE 0 END) as certified
               FROM training_snapshots WHERE cycle_id = 1"""
        ).fetchone()
        # Cycle 1: pm1 incomplete, pm2 incomplete, pm3 complete, pm1 again (from compliance insert) = 4 total, 1 complete
        assert row["total"] >= 3
        assert row["certified"] >= 1

    def test_certification_rate_cycle2(self, db_conn):
        """Cycle 2 should show pm1 newly certified."""
        row = db_conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN overall_training_status = 'complete' THEN 1 ELSE 0 END) as certified
               FROM training_snapshots WHERE cycle_id = 2"""
        ).fetchone()
        assert row["certified"] >= 1  # pm1 is now complete

    def test_reminders_to_certification(self, db_conn):
        """PM who got congrats (stage 99) should have reminder count."""
        certified_pms = db_conn.execute(
            "SELECT DISTINCT project_manager_id FROM communication_history WHERE reminder_stage = 99"
        ).fetchall()
        assert len(certified_pms) >= 1  # Alice got congrats in cycle 2

        pm_id = certified_pms[0]["project_manager_id"]
        congrats_cycle = db_conn.execute(
            "SELECT MIN(cycle_id) as fc FROM communication_history WHERE project_manager_id = ? AND reminder_stage = 99",
            (pm_id,)
        ).fetchone()

        reminder_count = db_conn.execute(
            "SELECT COUNT(*) as cnt FROM communication_history WHERE project_manager_id = ? AND reminder_stage > 0 AND reminder_stage < 99 AND cycle_id < ?",
            (pm_id, congrats_cycle["fc"])
        ).fetchone()["cnt"]
        assert reminder_count == 1  # Alice got 1 reminder in cycle 1

    def test_time_to_certification(self, db_conn):
        """Time to cert should be calculable for certified PMs."""
        pm_id = db_conn.execute(
            "SELECT DISTINCT project_manager_id FROM communication_history WHERE reminder_stage = 99"
        ).fetchone()["project_manager_id"]

        first = db_conn.execute(
            "SELECT MIN(created_at) as d FROM communication_history WHERE project_manager_id = ? AND reminder_stage > 0 AND reminder_stage < 99",
            (pm_id,)
        ).fetchone()
        congrats = db_conn.execute(
            "SELECT MIN(created_at) as d FROM communication_history WHERE project_manager_id = ? AND reminder_stage = 99",
            (pm_id,)
        ).fetchone()

        assert first["d"] is not None
        assert congrats["d"] is not None
        first_dt = pd.to_datetime(first["d"])
        congrats_dt = pd.to_datetime(congrats["d"])
        days = (congrats_dt - first_dt).days
        assert days >= 0


# ---------------------------------------------------------------------------
# Test: Compliance parsing
# ---------------------------------------------------------------------------

class TestComplianceParsing:
    def test_parse_compliance_json(self, db_conn):
        """Compliance JSON should be parseable."""
        rows = db_conn.execute(
            """SELECT compliance_issues_json FROM training_snapshots
               WHERE compliance_issues_json IS NOT NULL AND compliance_issues_json != 'null'"""
        ).fetchall()
        assert len(rows) >= 1

        for r in rows:
            issues = json.loads(r["compliance_issues_json"])
            assert isinstance(issues, list)
            for issue in issues:
                assert "project_id" in issue
                assert "gate" in issue

    def test_compliance_projects_extraction(self, db_conn):
        """Should extract unique project IDs from compliance data."""
        rows = db_conn.execute(
            """SELECT compliance_issues_json FROM training_snapshots
               WHERE cycle_id = 1 AND compliance_issues_json IS NOT NULL AND compliance_issues_json != 'null'"""
        ).fetchall()
        projects = set()
        for r in rows:
            issues = json.loads(r["compliance_issues_json"])
            if isinstance(issues, list):
                for issue in issues:
                    if issue.get("project_id"):
                        projects.add(issue["project_id"])
        assert "P001" in projects


# ---------------------------------------------------------------------------
# Test: Cycle Comparison logic
# ---------------------------------------------------------------------------

class TestCycleComparison:
    def test_merge_training_snapshots(self, db_conn):
        """Merging two cycles should produce correct suffixed columns."""
        train_a = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t
               JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 1""", db_conn)
        train_b = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t
               JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 2""", db_conn)

        merged = train_a.merge(train_b, on=["pm_id", "full_name", "email"],
                               suffixes=("_c1", "_c2"), how="outer", indicator=True)

        assert "overall_training_status_c1" in merged.columns
        assert "overall_training_status_c2" in merged.columns

    def test_newly_certified_detection(self, db_conn):
        """Should detect PMs who went from incomplete to complete."""
        train_a = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t
               JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 1""", db_conn)
        train_b = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t
               JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 2""", db_conn)

        merged = train_a.merge(train_b, on=["pm_id", "full_name", "email"],
                               suffixes=("_c1", "_c2"), how="outer", indicator=True)

        col_a = "overall_training_status_c1"
        col_b = "overall_training_status_c2"
        newly_certified = merged[
            (merged[col_a] != "complete") & (merged[col_b] == "complete")
        ]
        # Alice went from incomplete to complete
        assert len(newly_certified) >= 1
        assert "Alice Smith" in newly_certified["full_name"].values

    def test_project_assignment_changes(self, db_conn):
        """Should detect new and removed projects between cycles."""
        assign_a = set(pd.read_sql_query(
            "SELECT DISTINCT project_id FROM assignment_snapshots WHERE cycle_id = 1",
            db_conn)["project_id"].tolist())
        assign_b = set(pd.read_sql_query(
            "SELECT DISTINCT project_id FROM assignment_snapshots WHERE cycle_id = 2",
            db_conn)["project_id"].tolist())

        new_projects = assign_b - assign_a
        removed_projects = assign_a - assign_b

        assert "P004" in new_projects  # Delta is new in cycle 2
        assert "P003" in removed_projects  # Gamma is gone in cycle 2


# ---------------------------------------------------------------------------
# Test: Data Quality
# ---------------------------------------------------------------------------

class TestDataQuality:
    def test_unmatched_pm_query(self, db_conn):
        """Should find unmatched PMs."""
        dq_df = pd.read_sql_query(
            "SELECT * FROM data_quality_issues WHERE issue_type = 'unmatched_pm'",
            db_conn)
        assert len(dq_df) == 2
        names = dq_df["person_name"].tolist()
        assert "Dave Unknown" in names
        assert "Eve Missing" in names

    def test_value_counts_rename(self, db_conn):
        """Test the fixed value_counts rename pattern."""
        dq_df = pd.read_sql_query("SELECT issue_type FROM data_quality_issues", db_conn)
        type_counts = dq_df["issue_type"].value_counts()
        result = type_counts.reset_index().set_axis(["Issue Type", "Count"], axis=1)
        assert list(result.columns) == ["Issue Type", "Count"]
        assert result["Count"].sum() == 2


# ---------------------------------------------------------------------------
# Test: IT PM Track Record queries
# ---------------------------------------------------------------------------

class TestITPMTrackRecord:
    def test_pm_communication_timeline(self, db_conn):
        """Should return full communication history for a PM."""
        pm_id = db_conn.execute(
            "SELECT id FROM project_managers WHERE email = 'alice@example.com'"
        ).fetchone()["id"]

        comms = pd.read_sql_query(
            """SELECT ch.cycle_id, ch.reminder_stage, ch.email_subject
               FROM communication_history ch
               WHERE ch.project_manager_id = ?
               ORDER BY ch.cycle_id""",
            db_conn, params=(pm_id,))

        assert len(comms) == 2
        assert comms.iloc[0]["reminder_stage"] == 1  # Stage 1 in cycle 1
        assert comms.iloc[1]["reminder_stage"] == 99  # Congrats in cycle 2

    def test_pm_training_progression(self, db_conn):
        """Should show training status changing over cycles."""
        pm_id = db_conn.execute(
            "SELECT id FROM project_managers WHERE email = 'bob@example.com'"
        ).fetchone()["id"]

        training = pd.read_sql_query(
            """SELECT ts.cycle_id, ts.fundamentals_status, ts.advanced_status,
                      ts.overall_training_status
               FROM training_snapshots ts
               WHERE ts.project_manager_id = ?
               ORDER BY ts.cycle_id""",
            db_conn, params=(pm_id,))

        assert len(training) >= 2
        # Bob has fundamentals done but not advanced in both cycles
        assert all(training["fundamentals_status"] == "completed")
        assert all(training["advanced_status"] == "incomplete")

    def test_pm_assignment_count(self, db_conn):
        """Should count unique projects across all cycles."""
        pm_id = db_conn.execute(
            "SELECT id FROM project_managers WHERE email = 'bob@example.com'"
        ).fetchone()["id"]

        projects = db_conn.execute(
            "SELECT COUNT(DISTINCT project_id) as cnt FROM assignment_snapshots WHERE project_manager_id = ?",
            (pm_id,)
        ).fetchone()["cnt"]
        assert projects == 2  # Beta + Delta


# ---------------------------------------------------------------------------
# Test: Settings / Config
# ---------------------------------------------------------------------------

class TestSettings:
    def test_config_yaml_is_valid(self):
        """config.yaml should be valid YAML."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        assert "paths" in config
        assert "column_mapping" in config
        assert "required_training" in config

    def test_config_roundtrip(self, tmp_path):
        """Saving and reloading config should preserve structure."""
        config = {
            "paths": {"input_folder": "data/input"},
            "action_links": {"learning_platform": "https://example.com"},
        }
        config_path = tmp_path / "test_config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        with open(config_path, "r") as f:
            reloaded = yaml.safe_load(f)

        assert reloaded["action_links"]["learning_platform"] == "https://example.com"


# ---------------------------------------------------------------------------
# Test: Log Viewer helpers
# ---------------------------------------------------------------------------

class TestLogViewer:
    def test_log_level_filtering(self, tmp_path):
        """Log lines should be filterable by level."""
        log_content = """2026-04-01 10:00:00 [INFO] main: Starting cycle
2026-04-01 10:00:01 [WARNING] file_loader: Missing column
2026-04-01 10:00:02 [ERROR] main: Cycle failed
2026-04-01 10:00:03 [INFO] main: Retrying
2026-04-01 10:00:04 [DEBUG] matcher: Checking email"""

        lines = log_content.split("\n")

        # Filter ERROR only
        errors = [l for l in lines if "[ERROR]" in l]
        assert len(errors) == 1
        assert "Cycle failed" in errors[0]

        # Filter WARNING + ERROR
        issues = [l for l in lines if "[WARNING]" in l or "[ERROR]" in l]
        assert len(issues) == 2

    def test_log_search(self, tmp_path):
        """Log search should be case-insensitive."""
        lines = ["[INFO] Loading ePPM file", "[INFO] Loading Fuse file", "[ERROR] Missing column"]
        search = "eppm"
        filtered = [l for l in lines if search.lower() in l.lower()]
        assert len(filtered) == 1


# ---------------------------------------------------------------------------
# Test: Archive Browser queries
# ---------------------------------------------------------------------------

class TestArchiveBrowser:
    def test_processed_files_query(self, tmp_db):
        """Should query processed files (empty since we didn't archive)."""
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        result = pd.read_sql_query(
            "SELECT * FROM processed_files ORDER BY cycle_id", conn)
        # No files archived in test data
        assert isinstance(result, pd.DataFrame)
        conn.close()


# ---------------------------------------------------------------------------
# Test: Edge cases — empty database
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_db(tmp_path):
    """Create an empty database (schema only, no data)."""
    db_path = str(tmp_path / "empty.db")
    db = Database(db_path)
    db.close()
    return db_path


@pytest.fixture
def empty_conn(empty_db):
    conn = sqlite3.connect(empty_db)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


class TestEmptyDatabase:
    def test_no_cycles(self, empty_conn):
        """All queries should handle empty cycles table."""
        cycles = pd.read_sql_query("SELECT * FROM cycles", empty_conn)
        assert cycles.empty

    def test_no_training_snapshots(self, empty_conn):
        """Dashboard cert rate query on empty DB."""
        row = empty_conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN overall_training_status = 'complete' THEN 1 ELSE 0 END) as certified
               FROM training_snapshots WHERE cycle_id = 1"""
        ).fetchone()
        assert row["total"] == 0
        assert row["certified"] is None or row["certified"] == 0

    def test_no_communications(self, empty_conn):
        """Comms queries should return empty results."""
        comms = pd.read_sql_query(
            "SELECT * FROM communication_history", empty_conn)
        assert comms.empty

    def test_no_data_quality_issues(self, empty_conn):
        """DQ query on empty DB."""
        dq = pd.read_sql_query("SELECT * FROM data_quality_issues", empty_conn)
        assert dq.empty

    def test_empty_pm_list(self, empty_conn):
        """PM list should be empty."""
        pms = pd.read_sql_query("SELECT * FROM project_managers", empty_conn)
        assert pms.empty

    def test_certified_pms_empty(self, empty_conn):
        """Reminders-to-cert query should return nothing."""
        result = empty_conn.execute(
            "SELECT DISTINCT project_manager_id FROM communication_history WHERE reminder_stage = 99"
        ).fetchall()
        assert len(result) == 0

    def test_cycle_comparison_with_no_data(self, empty_conn):
        """Merge of two empty training snapshots should produce empty DataFrame."""
        train_a = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 1""", empty_conn)
        train_b = pd.read_sql_query(
            """SELECT pm.id as pm_id, pm.full_name, pm.email, t.overall_training_status
               FROM training_snapshots t JOIN project_managers pm ON t.project_manager_id = pm.id
               WHERE t.cycle_id = 2""", empty_conn)
        assert train_a.empty
        assert train_b.empty


# ---------------------------------------------------------------------------
# Test: Edge cases — single cycle
# ---------------------------------------------------------------------------

@pytest.fixture
def single_cycle_db(tmp_path):
    """Create a DB with exactly one cycle and one PM."""
    db_path = str(tmp_path / "single.db")
    db = Database(db_path)
    cycle_id = db.start_cycle()
    pm_id = db.upsert_project_manager("Solo PM", "solo@example.com", "solo pm")
    db.insert_assignment_snapshot(cycle_id, pm_id, "Project One", "P001", "Not Completed", "e.xlsx")
    db.insert_training_snapshot(cycle_id, pm_id, "incomplete", "incomplete", None, None, "incomplete", "f.xlsx",
                                match_method="email", missing_trainings=["Fundamentals", "Advanced"],
                                eligibility_status="eligible")
    db.insert_communication(cycle_id, pm_id, 1, "Reminder", "Dear Solo...", "prepared")
    db.complete_cycle(cycle_id, "completed", "Single cycle")
    db.close()
    return db_path


class TestSingleCycle:
    def test_single_cycle_queries(self, single_cycle_db):
        """All queries should work with just one cycle."""
        conn = sqlite3.connect(single_cycle_db)
        conn.row_factory = sqlite3.Row

        cycles = pd.read_sql_query("SELECT * FROM cycles", conn)
        assert len(cycles) == 1

        pms = pd.read_sql_query("SELECT * FROM project_managers", conn)
        assert len(pms) == 1

        # Dashboard cert rate
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN overall_training_status = 'complete' THEN 1 ELSE 0 END) as certified FROM training_snapshots WHERE cycle_id = 1"
        ).fetchone()
        assert row["total"] == 1
        assert row["certified"] == 0

        # No certified PMs yet
        certified = conn.execute(
            "SELECT DISTINCT project_manager_id FROM communication_history WHERE reminder_stage = 99"
        ).fetchall()
        assert len(certified) == 0

        conn.close()

    def test_compliance_empty_json(self, single_cycle_db):
        """PM without compliance issues should not cause errors."""
        conn = sqlite3.connect(single_cycle_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT compliance_issues_json FROM training_snapshots WHERE compliance_issues_json IS NOT NULL AND compliance_issues_json != 'null'"
        ).fetchall()
        assert len(rows) == 0  # No compliance data
        conn.close()


# ---------------------------------------------------------------------------
# Test: Template file operations
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_all_template_files_exist(self):
        """All templates referenced in config should exist on disk."""
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
        project_root = os.path.dirname(config_path)
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        templates = config.get("templates", {})
        for key, rel_path in templates.items():
            full_path = os.path.join(project_root, rel_path)
            assert os.path.exists(full_path), f"Template '{key}' not found: {rel_path}"

    def test_template_has_subject_line(self):
        """All templates should start with a Subject: line."""
        templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        for fname in os.listdir(templates_dir):
            if not fname.endswith(".txt"):
                continue
            with open(os.path.join(templates_dir, fname), "r") as f:
                first_line = f.readline().strip()
            assert first_line.startswith("Subject:"), \
                f"Template '{fname}' missing Subject: line, got: {first_line[:50]}"

    def test_template_jinja_variables_parseable(self):
        """Template variables should be extractable via regex."""
        import re
        templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
        for fname in os.listdir(templates_dir):
            if not fname.endswith(".txt"):
                continue
            with open(os.path.join(templates_dir, fname), "r") as f:
                content = f.read()
            variables = re.findall(r"\{\{(\s*[\w.]+\s*)\}\}", content)
            # Every template should have at least one variable
            assert len(variables) > 0, f"Template '{fname}' has no Jinja2 variables"

    def test_template_read_write_roundtrip(self, tmp_path):
        """Writing and re-reading a template should preserve content."""
        content = "Subject: Test\nDear {{name}},\n\nHello!\n"
        path = tmp_path / "test_template.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        with open(path, "r", encoding="utf-8") as f:
            reloaded = f.read()
        assert reloaded == content


# ---------------------------------------------------------------------------
# Test: Unmatched PM resolution logic
# ---------------------------------------------------------------------------

class TestUnmatchedPMResolution:
    def test_partial_name_matching(self):
        """Partial name matching should find candidates."""
        pm_name = "Dave Unknown"
        name_parts = pm_name.lower().split()

        existing_pms = [
            {"full_name": "David Unknown-Smith", "email": "david@example.com"},
            {"full_name": "Jane Doe", "email": "jane@example.com"},
            {"full_name": "Dave Other", "email": "dave.other@example.com"},
        ]

        suggestions = []
        for pm in existing_pms:
            existing_name = pm["full_name"].lower()
            existing_email = (pm["email"] or "").lower()
            score = sum(1 for part in name_parts if part in existing_name or part in existing_email)
            if score > 0 and existing_name != pm_name.lower():
                suggestions.append((score, pm["full_name"], pm["email"]))

        suggestions.sort(key=lambda x: -x[0])
        # "David Unknown-Smith" matches "unknown" and "dave" partially
        assert len(suggestions) >= 1
        # "Dave Other" matches "dave"
        assert any("Dave Other" in s[1] for s in suggestions)

    def test_no_self_match(self):
        """PM should not match against itself."""
        pm_name = "Alice Smith"
        name_parts = pm_name.lower().split()

        existing_pms = [
            {"full_name": "Alice Smith", "email": "alice@example.com"},
        ]

        suggestions = []
        for pm in existing_pms:
            existing_name = pm["full_name"].lower()
            score = sum(1 for part in name_parts if part in existing_name)
            if score > 0 and existing_name != pm_name.lower():
                suggestions.append(pm)

        assert len(suggestions) == 0  # Should not suggest self
