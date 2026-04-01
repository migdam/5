"""Integration tests — end-to-end pipeline with test data."""
import sys
import os
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl
from src.config_loader import load_config


def _create_eppm(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ePPM"
    headers = [
        "Project number", "Project Name", "Leading Function", "Sub Function",
        "Active Stage", "Project Status", "Project Archetype",
        "Project Owner", "Project Owner Email",
        "Project Manager", "Project Manager Email",
        "IT Project Manager", "IT Project Manager Email",
        "IT Portfolio Manager", "IT Portfolio Manager Email",
        "G0 Compliance", "G0 Action", "G3 Compliance", "G3 Action",
        "G5 Compliance", "G5 Action", "G6 Compliance", "G6 Action",
        "Project Compliance",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    wb.save(path)


def _create_fuse(path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fuse"
    headers = [
        "Full Name", "Email", "Employee Group", "Geographical Region",
        "Country", "Function", "Position", "Content ID", "Content Title",
        "Course Status", "Start Date", "Completion Date", "Score",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    wb.save(path)


def setup_test_env():
    """Create a temporary project directory with config and test data."""
    tmpdir = tempfile.mkdtemp()
    # Create directory structure
    for d in ["data/input", "data/output", "data/archive", "logs"]:
        os.makedirs(os.path.join(tmpdir, d))

    # Copy templates
    src_templates = os.path.join(os.path.dirname(__file__), "..", "templates")
    dst_templates = os.path.join(tmpdir, "templates")
    shutil.copytree(src_templates, dst_templates)

    # Copy config and adjust paths
    config_src = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    config_dst = os.path.join(tmpdir, "config.yaml")
    shutil.copy2(config_src, config_dst)

    return tmpdir


def test_full_cycle_with_matched_data():
    """Run a complete cycle with test data that has matching PMs."""
    tmpdir = setup_test_env()
    original_dir = os.getcwd()

    try:
        os.chdir(tmpdir)

        # Create ePPM with 2 projects
        _create_eppm(os.path.join(tmpdir, "data/input/ePPM_export.xlsx"), [
            {
                "Project number": "PRJ001", "Project Name": "Test Project",
                "Active Stage": "G3", "Project Status": "Not Completed",
                "Project Manager": "Maya Collins", "Project Manager Email": "maya@corp.example",
                "IT Project Manager": "Maya Collins", "IT Project Manager Email": "maya@corp.example",
                "G3 Compliance": "Partially compliant", "G3 Action": "Stakeholder Agreement needed",
                "Project Compliance": "Partially compliant",
            },
            {
                "Project number": "PRJ002", "Project Name": "Another Project",
                "Active Stage": "G5", "Project Status": "Not Completed",
                "Project Manager": "Daniel Carter", "Project Manager Email": "daniel@corp.example",
                "IT Project Manager": "Daniel Carter", "IT Project Manager Email": "daniel@corp.example",
                "Project Compliance": "Full compliance",
            },
        ])

        # Create Fuse with matching training records
        _create_fuse(os.path.join(tmpdir, "data/input/Fuse_export.xlsx"), [
            {
                "Full Name": "Maya Collins", "Email": "maya@corp.example",
                "Content Title": "Managing Projects for Business Success - Fundamentals - Certification Test",
                "Course Status": "completed", "Completion Date": "2026-01-15",
            },
            {
                "Full Name": "Maya Collins", "Email": "maya@corp.example",
                "Content Title": "Certification Test for Managing Projects for Business Success (Advanced)",
                "Course Status": "incomplete",
            },
            {
                "Full Name": "Daniel Carter", "Email": "daniel@corp.example",
                "Content Title": "Managing Projects for Business Success - Fundamentals - Certification Test",
                "Course Status": "completed", "Completion Date": "2026-01-20",
            },
            {
                "Full Name": "Daniel Carter", "Email": "daniel@corp.example",
                "Content Title": "Certification Test for Managing Projects for Business Success (Advanced)",
                "Course Status": "completed", "Completion Date": "2026-02-01",
            },
        ])

        # Run cycle
        from main import run_cycle
        summary = run_cycle("config.yaml")

        assert summary is not None
        assert summary["matched_pms"] == 2
        # Maya: has Fundamentals, missing Advanced → eligible
        # Daniel: both complete → skipped
        assert summary["training_reminders_generated"] == 1
        assert summary["pms_training_complete"] == 1

        # Check output folder was created
        output_dirs = os.listdir(os.path.join(tmpdir, "data/output"))
        assert len(output_dirs) == 1

        # Check reminder file exists for Maya
        output_dir = os.path.join(tmpdir, "data/output", output_dirs[0])
        recipients_dir = os.path.join(output_dir, "per_recipient")
        assert os.path.exists(recipients_dir)
        files = os.listdir(recipients_dir)
        assert any("maya" in f for f in files)

        # Check compliance appears in Maya's reminder (her project has G3 issues)
        maya_file = [f for f in files if "maya" in f][0]
        with open(os.path.join(recipients_dir, maya_file)) as f:
            content = f.read()
        assert "Stakeholder Agreement needed" in content

        # Check archive
        archive_dirs = os.listdir(os.path.join(tmpdir, "data/archive"))
        assert len(archive_dirs) >= 1

    finally:
        os.chdir(original_dir)
        shutil.rmtree(tmpdir)


def test_cycle_reverts_on_bad_file():
    """Cycle should revert cleanly when given an invalid input file."""
    tmpdir = setup_test_env()
    original_dir = os.getcwd()

    try:
        os.chdir(tmpdir)

        # Create a bad ePPM file
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Wrong", "Columns"])
        ws.append(["a", "b"])
        wb.save(os.path.join(tmpdir, "data/input/ePPM_export.xlsx"))

        # Create valid Fuse
        _create_fuse(os.path.join(tmpdir, "data/input/Fuse_export.xlsx"), [
            {"Full Name": "Test", "Email": "test@example.com",
             "Content Title": "Test", "Course Status": "completed"},
        ])

        from main import run_cycle
        import sqlite3

        result = run_cycle("config.yaml")
        assert result is None  # Reverted

        # Check DB has no cycles
        db_path = os.path.join(tmpdir, "data/training_reminders.db")
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM cycles").fetchone()[0]
        conn.close()
        assert count == 0

    finally:
        os.chdir(original_dir)
        shutil.rmtree(tmpdir)


def test_second_cycle_increments_stage():
    """Running two cycles should produce stage 2 reminders for still-eligible PMs."""
    tmpdir = setup_test_env()
    original_dir = os.getcwd()

    try:
        os.chdir(tmpdir)

        eppm_data = [{
            "Project number": "PRJ001", "Project Name": "Test",
            "Active Stage": "G3", "Project Status": "Not Completed",
            "Project Manager": "Maya Collins", "Project Manager Email": "maya@corp.example",
            "IT Project Manager": "Maya Collins", "IT Project Manager Email": "maya@corp.example",
        }]

        fuse_data = [{
            "Full Name": "Maya Collins", "Email": "maya@corp.example",
            "Content Title": "Managing Projects for Business Success - Fundamentals - Certification Test",
            "Course Status": "incomplete",
        }]

        # Cycle 1
        _create_eppm(os.path.join(tmpdir, "data/input/ePPM_export.xlsx"), eppm_data)
        _create_fuse(os.path.join(tmpdir, "data/input/Fuse_export.xlsx"), fuse_data)

        from main import run_cycle
        s1 = run_cycle("config.yaml")
        assert s1["training_reminders_generated"] == 1

        # Cycle 2 — same data (Maya still hasn't completed)
        _create_eppm(os.path.join(tmpdir, "data/input/ePPM_export.xlsx"), eppm_data)
        _create_fuse(os.path.join(tmpdir, "data/input/Fuse_export.xlsx"), fuse_data)

        s2 = run_cycle("config.yaml")
        assert s2["training_reminders_generated"] == 1

        # Check stage 2 was generated
        import sqlite3
        conn = sqlite3.connect(os.path.join(tmpdir, "data/training_reminders.db"))
        stages = conn.execute(
            "SELECT reminder_stage FROM communication_history ORDER BY id"
        ).fetchall()
        conn.close()
        assert stages[0][0] == 1
        assert stages[1][0] == 2

    finally:
        os.chdir(original_dir)
        shutil.rmtree(tmpdir)
