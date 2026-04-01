"""Tests for file archiver."""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import openpyxl
from src.archiver import archive_files
from src.repository import Database


def _create_test_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["test", "data"])
    wb.save(path)


def test_archive_moves_files():
    tmpdir = tempfile.mkdtemp()
    archive_dir = os.path.join(tmpdir, "archive")
    os.makedirs(archive_dir)

    # Create test input file
    input_file = os.path.join(tmpdir, "test_input.xlsx")
    _create_test_xlsx(input_file)

    config = {"paths": {"archive_folder": archive_dir}}
    db = Database(os.path.join(tmpdir, "test.db"))
    cycle_id = db.start_cycle()

    input_files = [("eppm", input_file)]
    archive_files(input_files, config, cycle_id, db)

    # Original file should be gone
    assert not os.path.exists(input_file)

    # Archive should have the file
    archive_subdirs = os.listdir(archive_dir)
    assert len(archive_subdirs) == 1
    archived = os.listdir(os.path.join(archive_dir, archive_subdirs[0]))
    assert len(archived) == 1
    assert "test_input" in archived[0]

    # DB should have a record
    row = db.conn.execute("SELECT * FROM processed_files WHERE cycle_id = ?", (cycle_id,)).fetchone()
    assert row is not None
    assert row["file_type"] == "eppm"

    db.close()
    shutil.rmtree(tmpdir)


def test_archive_multiple_files():
    tmpdir = tempfile.mkdtemp()
    archive_dir = os.path.join(tmpdir, "archive")
    os.makedirs(archive_dir)

    file1 = os.path.join(tmpdir, "eppm.xlsx")
    file2 = os.path.join(tmpdir, "fuse.xlsx")
    _create_test_xlsx(file1)
    _create_test_xlsx(file2)

    config = {"paths": {"archive_folder": archive_dir}}
    db = Database(os.path.join(tmpdir, "test.db"))
    cycle_id = db.start_cycle()

    archive_files([("eppm", file1), ("fuse", file2)], config, cycle_id, db)

    assert not os.path.exists(file1)
    assert not os.path.exists(file2)

    count = db.conn.execute("SELECT COUNT(*) FROM processed_files WHERE cycle_id = ?", (cycle_id,)).fetchone()[0]
    assert count == 2

    db.close()
    shutil.rmtree(tmpdir)


def test_archive_preserves_filename():
    tmpdir = tempfile.mkdtemp()
    archive_dir = os.path.join(tmpdir, "archive")
    os.makedirs(archive_dir)

    input_file = os.path.join(tmpdir, "ePPM_export.xlsx")
    _create_test_xlsx(input_file)

    config = {"paths": {"archive_folder": archive_dir}}
    db = Database(os.path.join(tmpdir, "test.db"))
    cycle_id = db.start_cycle()

    archive_files([("eppm", input_file)], config, cycle_id, db)

    # Archived filename should contain original name
    archive_subdir = os.listdir(archive_dir)[0]
    archived_name = os.listdir(os.path.join(archive_dir, archive_subdir))[0]
    assert "ePPM_export" in archived_name
    assert archived_name.endswith(".xlsx")

    db.close()
    shutil.rmtree(tmpdir)
