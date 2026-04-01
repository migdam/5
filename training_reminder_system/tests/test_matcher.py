import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from src.matcher import match_people
from src.normalizer import normalize_name, normalize_email


def make_config():
    return {
        "matching": {
            "match_by_email": True,
            "match_by_exact_name": True,
            "match_by_normalized_name": True,
        }
    }


def test_email_match():
    """Test Pass 1: exact email match."""
    pms = pd.DataFrame([
        {"full_name": "Maya Collins", "email": "maya.collins@corp.example",
         "normalized_name": "maya collins", "normalized_email": "maya.collins@corp.example"},
    ])
    training = pd.DataFrame([
        {"full_name": "Maya Collins", "email": "maya.collins@corp.example",
         "content_title": "Fundamentals", "course_status": "completed"},
    ])
    matched, unmatched_pm, unmatched_tr = match_people(pms, training, make_config())
    assert len(matched) == 1
    assert matched[0]["match_method"] == "email"
    assert len(unmatched_pm) == 0


def test_exact_name_match():
    """Test Pass 2: exact name match when email differs."""
    pms = pd.DataFrame([
        {"full_name": "Daniel Carter", "email": "daniel@corp.example",
         "normalized_name": "daniel carter", "normalized_email": "daniel@corp.example"},
    ])
    training = pd.DataFrame([
        {"full_name": "Daniel Carter", "email": "daniel.carter@other.example",
         "content_title": "Fundamentals", "course_status": "completed"},
    ])
    matched, unmatched_pm, unmatched_tr = match_people(pms, training, make_config())
    assert len(matched) == 1
    assert matched[0]["match_method"] == "exact_name"


def test_normalized_name_match():
    """Test Pass 3: normalized name match with extra whitespace."""
    pms = pd.DataFrame([
        {"full_name": "Olivia  Reed", "email": "olivia@corp.example",
         "normalized_name": "olivia reed", "normalized_email": "olivia@corp.example"},
    ])
    training = pd.DataFrame([
        {"full_name": "olivia reed", "email": "olivia.reed@brand.example",
         "content_title": "Fundamentals", "course_status": "completed"},
    ])
    matched, _, _ = match_people(pms, training, make_config())
    assert len(matched) == 1
    assert matched[0]["match_method"] == "normalized_name"


def test_no_match():
    """Test that truly unmatched PMs are reported."""
    pms = pd.DataFrame([
        {"full_name": "Unknown Person", "email": "unknown@corp.example",
         "normalized_name": "unknown person", "normalized_email": "unknown@corp.example"},
    ])
    training = pd.DataFrame([
        {"full_name": "Someone Else", "email": "someone@corp.example",
         "content_title": "Fundamentals", "course_status": "completed"},
    ])
    matched, unmatched_pm, _ = match_people(pms, training, make_config())
    assert len(matched) == 0
    assert len(unmatched_pm) == 1


def test_multiple_training_records():
    """Test that a PM gets all their training records matched."""
    pms = pd.DataFrame([
        {"full_name": "Maya Collins", "email": "maya@corp.example",
         "normalized_name": "maya collins", "normalized_email": "maya@corp.example"},
    ])
    training = pd.DataFrame([
        {"full_name": "Maya Collins", "email": "maya@corp.example",
         "content_title": "Fundamentals", "course_status": "completed"},
        {"full_name": "Maya Collins", "email": "maya@corp.example",
         "content_title": "Advanced", "course_status": "incomplete"},
    ])
    matched, _, _ = match_people(pms, training, make_config())
    assert len(matched) == 1
    assert len(matched[0]["training_indices"]) == 2


def test_normalize_name():
    assert normalize_name("  Maya   Collins  ") == "maya collins"
    assert normalize_name("DANIEL CARTER") == "daniel carter"
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


def test_normalize_email():
    assert normalize_email("  Maya.Collins@CORP.example  ") == "maya.collins@corp.example"
    assert normalize_email(None) == ""
