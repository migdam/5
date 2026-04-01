import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def normalize_name(name):
    """Normalize a person name for comparison: lowercase, strip, collapse whitespace."""
    if not name or pd.isna(name):
        return ""
    name = str(name).lower().strip()
    name = re.sub(r"\s+", " ", name)
    # Remove common suffixes/prefixes that cause mismatches
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def normalize_email(email):
    """Normalize email: lowercase, strip."""
    if not email or pd.isna(email):
        return ""
    return str(email).lower().strip()


def normalize_dataframe(df, name_col, email_col):
    """Add normalized_name and normalized_email columns to a DataFrame."""
    df = df.copy()
    df["normalized_name"] = df[name_col].apply(normalize_name)
    df["normalized_email"] = df[email_col].apply(normalize_email)
    logger.debug("Normalized %d records (name_col=%s, email_col=%s)", len(df), name_col, email_col)
    return df


def extract_unique_pms(eppm_df):
    """Extract unique IT Project Managers from ePPM data.

    A PM can appear in the 'project_manager' or 'it_project_manager' columns.
    We focus on IT Project Managers as the target audience but also include
    regular Project Managers if they have no separate IT PM.

    Returns DataFrame with columns: full_name, email, normalized_name, normalized_email,
    plus lists of projects they're assigned to.
    """
    pm_records = []

    for _, row in eppm_df.iterrows():
        project_name = row.get("project_name", "")
        project_id = row.get("project_number", "")
        project_status = row.get("project_status", "")

        # Collect IT Project Manager
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

        # Also collect Project Manager
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

    all_pms_df = pd.DataFrame(pm_records)

    # Normalize
    all_pms_df["normalized_name"] = all_pms_df["full_name"].apply(normalize_name)
    all_pms_df["normalized_email"] = all_pms_df["email"].apply(
        lambda x: normalize_email(x) if x else ""
    )

    # Deduplicate to unique persons (by email first, then name)
    unique_pms = []
    seen_emails = set()
    seen_names = set()

    for _, row in all_pms_df.iterrows():
        email = row["normalized_email"]
        name = row["normalized_name"]

        if email and email in seen_emails:
            continue
        if not email and name in seen_names:
            continue

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
