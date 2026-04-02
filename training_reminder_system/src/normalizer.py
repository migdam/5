##############################################################################
# normalizer.py — Normalize Names and Emails, Extract Unique PMs
#
# WHY NORMALIZATION MATTERS:
#   The two main data sources — ePPM (project assignments) and Fuse
#   (training records) — are completely separate systems. They often
#   store the same person's name and email in slightly different ways:
#
#     ePPM might have:   "John  Smith", "JOHN.SMITH@company.com"
#     Fuse might have:   "John Smith", "john.smith@Company.Com"
#
#   Without normalization, these would look like different people and
#   the system would fail to match their training records. This module
#   provides consistent normalization so that minor formatting differences
#   do not prevent correct matching.
#
# This module also extracts the unique list of Project Managers from the
# ePPM data. A single person may appear on many projects and in multiple
# roles (PM and IT PM), but they should receive only ONE training reminder.
##############################################################################

import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def normalize_name(name):
    """Normalize a person's name for comparison purposes.

    What this does, step by step:
      1. Converts to lowercase — so "John SMITH" and "john smith" match.
      2. Strips leading/trailing whitespace — removes accidental spaces.
      3. Collapses multiple spaces into one — "John  Smith" becomes "John Smith".
      4. Removes all punctuation — strips periods, hyphens, apostrophes, etc.
         This handles differences like "O'Brien" vs "OBrien" or "Smith-Jones"
         vs "Smith Jones".
      5. Final strip — catches any trailing space left after punctuation removal.

    The result is a clean, uniform string that can be compared across systems
    without worrying about formatting inconsistencies.
    """
    if not name or pd.isna(name):
        return ""
    name = str(name).lower().strip()
    name = re.sub(r"\s+", " ", name)
    # Remove common suffixes/prefixes that cause mismatches
    # This regex removes ALL non-word, non-space characters (punctuation).
    # For example: periods, hyphens, apostrophes, commas.
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def normalize_email(email):
    """Normalize email: lowercase, strip.

    Email addresses are case-insensitive by RFC standard, but systems
    often store them with inconsistent casing (e.g., "John@Company.COM"
    vs "john@company.com"). Lowercasing and stripping whitespace ensures
    that the same email always produces the same normalized form.
    """
    if not email or pd.isna(email):
        return ""
    return str(email).lower().strip()


def normalize_dataframe(df, name_col, email_col):
    """Add normalized_name and normalized_email columns to a DataFrame.

    This is a convenience function that applies normalize_name and
    normalize_email to the specified columns of a DataFrame, creating
    new columns that downstream code (especially the matcher) can use
    for comparison without modifying the original data.
    """
    df = df.copy()
    df["normalized_name"] = df[name_col].apply(normalize_name)
    df["normalized_email"] = df[email_col].apply(normalize_email)
    logger.debug("Normalized %d records (name_col=%s, email_col=%s)", len(df), name_col, email_col)
    return df


def extract_unique_pms(eppm_df):
    """Extract unique Project Managers from ePPM data.

    WHY WE PROCESS BOTH PM AND IT PM COLUMNS:
        In the ePPM system, a project can have two PM-related roles:
          - "Project Manager" (PM) — the overall project lead
          - "IT Project Manager" (IT PM) — the technical/IT lead
        Both roles require training. A person might be the PM on one
        project and the IT PM on another — or even hold both roles on
        the same project. We collect people from BOTH columns to ensure
        nobody is missed.

    WHY PROJECT INFO IS PRESERVED IN all_pms_df:
        The returned all_pms_df keeps project details (name, ID, status, role)
        attached to each PM record. This is needed downstream so the system
        can tell a PM exactly WHICH projects they are assigned to when
        sending a reminder. Without this, we would know WHO needs training
        but not be able to tell them WHY (i.e., which project assignments
        triggered the reminder).

    HOW DEDUPLICATION WORKS:
        After collecting all PM records, we deduplicate to find unique
        people. The same person may appear many times — once per project,
        and possibly in both the PM and IT PM columns.

        Deduplication uses a two-tier approach:
          1. First by email (most reliable) — if we have already seen
             this email address, this is the same person.
          2. Then by normalized name (fallback) — if email is missing,
             we use the normalized name to detect duplicates. This is
             less reliable but catches cases where email was not provided.

        The result is one entry per unique human being, regardless of how
        many projects or roles they have.

    Returns:
        (unique_df, all_pms_df)
        - unique_df: One row per unique person (for matching against Fuse).
        - all_pms_df: All PM-project records with project details preserved
          (for building reminder content that lists specific projects).
    """
    pm_records = []

    for _, row in eppm_df.iterrows():
        # Capture the project details — these travel with each PM record
        # so we can later tell each PM which projects triggered their reminder.
        project_name = row.get("project_name", "")
        project_id = row.get("project_number", "")
        project_status = row.get("project_status", "")

        # Collect IT Project Manager (if present on this project row)
        it_pm_name = row.get("it_project_manager")
        it_pm_email = row.get("it_project_manager_email")
        if it_pm_name and str(it_pm_name) not in ("", "None", "nan"):
            pm_records.append({
                "full_name": str(it_pm_name),
                "email": str(it_pm_email) if it_pm_email and str(it_pm_email) not in ("", "None", "nan") else None,
                "project_name": str(project_name) if project_name else "",
                "project_id": str(project_id) if project_id else "",
                "project_status": str(project_status) if project_status else "",
                "role": "IT Project Manager",
            })

        # Also collect Project Manager (if present on this project row)
        pm_name = row.get("project_manager")
        pm_email = row.get("project_manager_email")
        if pm_name and str(pm_name) not in ("", "None", "nan"):
            pm_records.append({
                "full_name": str(pm_name),
                "email": str(pm_email) if pm_email and str(pm_email) not in ("", "None", "nan") else None,
                "project_name": str(project_name) if project_name else "",
                "project_id": str(project_id) if project_id else "",
                "project_status": str(project_status) if project_status else "",
                "role": "Project Manager",
            })

    if not pm_records:
        logger.warning("No PM records extracted from ePPM data")
        return pd.DataFrame(), pd.DataFrame()

    # all_pms_df contains every PM-project combination (with duplicates).
    # This is the "expanded" view used later to list projects per person.
    all_pms_df = pd.DataFrame(pm_records)

    # Normalize names and emails for matching purposes.
    all_pms_df["normalized_name"] = all_pms_df["full_name"].apply(normalize_name)
    all_pms_df["normalized_email"] = all_pms_df["email"].apply(
        lambda x: normalize_email(x) if x else ""
    )

    # --- Deduplication: collapse to one entry per unique person ---
    # We track "seen" emails and names separately. Email is checked first
    # because it is the most reliable identifier (globally unique).
    # Name is the fallback for records that lack an email address.
    unique_pms = []
    seen_emails = set()
    seen_names = set()

    for _, row in all_pms_df.iterrows():
        email = row["normalized_email"]
        name = row["normalized_name"]

        # If this email was already seen, skip — same person.
        if email and email in seen_emails:
            continue
        # If no email but this name was already seen, skip — likely same person.
        if not email and name in seen_names:
            continue

        # New unique person — add to the list.
        unique_pms.append({
            "full_name": row["full_name"],
            "email": row["email"],
            "normalized_name": name,
            "normalized_email": email,
        })
        if email:
            seen_emails.add(email)
        if name:
            seen_names.add(name)

    unique_df = pd.DataFrame(unique_pms)
    logger.info(
        "Extracted %d total PM records, %d unique persons",
        len(all_pms_df),
        len(unique_df),
    )
    return unique_df, all_pms_df
