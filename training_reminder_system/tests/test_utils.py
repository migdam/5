"""Tests for utility functions."""
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.utils import get_timestamp, get_full_timestamp, compute_checksum, setup_logging


def test_get_timestamp_format():
    ts = get_timestamp()
    # Should be YYYY-MM-DD_HHMM
    assert len(ts) == 15
    assert ts[4] == "-"
    assert ts[7] == "-"
    assert ts[10] == "_"


def test_get_full_timestamp_format():
    ts = get_full_timestamp()
    # Should be YYYY-MM-DD_HHMMSS
    assert len(ts) == 17
    assert ts[4] == "-"


def test_compute_checksum():
    fd, path = tempfile.mkstemp()
    os.write(fd, b"test content for checksum")
    os.close(fd)
    checksum = compute_checksum(path)
    assert len(checksum) == 32  # MD5 hex length
    # Same file should give same checksum
    assert compute_checksum(path) == checksum
    os.unlink(path)


def test_compute_checksum_different_content():
    fd1, path1 = tempfile.mkstemp()
    os.write(fd1, b"content A")
    os.close(fd1)
    fd2, path2 = tempfile.mkstemp()
    os.write(fd2, b"content B")
    os.close(fd2)
    assert compute_checksum(path1) != compute_checksum(path2)
    os.unlink(path1)
    os.unlink(path2)


def test_setup_logging():
    tmpdir = tempfile.mkdtemp()
    log_file = setup_logging(tmpdir)
    assert os.path.exists(log_file)
    assert log_file.startswith(tmpdir)
    # Cleanup
    import shutil
    shutil.rmtree(tmpdir)
