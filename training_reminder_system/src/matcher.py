import logging
import pandas as pd
from src.normalizer import normalize_name, normalize_email

logger = logging.getLogger(__name__)


def match_people(unique_pms, training_df, config):
    """Match PMs from ePPM against training records from Fuse using three-pass matching.

    Pass 1: Exact email match (normalized)
    Pass 2: Exact full name match
    Pass 3: Normalized name match

    Args:
        unique_pms: DataFrame of unique PM identities with normalized_name, normalized_email.
        training_df: DataFrame of Fuse training data with full_name, email columns.
        config: Application configuration.

    Returns:
        (matched_pms, unmatched_pms, unmatched_training)
        matched_pms: list of dicts with PM info + training records
    """
    # Prepare training data with normalized fields
    training = training_df.copy()
    training["normalized_email"] = training["email"].apply(
        lambda x: normalize_email(x) if x and str(x) not in ("", "None", "nan") else ""
    )
    training["normalized_name"] = training["full_name"].apply(
        lambda x: normalize_name(x) if x and str(x) not in ("", "None", "nan") else ""
    )

    # Build lookup structures from training data
    # Group training records by person (email or name)
    training_by_email = {}
    training_by_name = {}
    training_by_norm_name = {}

    for idx, row in training.iterrows():
        email = row["normalized_email"]
        name = row.get("full_name", "")
        norm_name = row["normalized_name"]

        if email:
            training_by_email.setdefault(email, []).append(idx)
        if name:
            training_by_name.setdefault(str(name).strip(), []).append(idx)
        if norm_name:
            training_by_norm_name.setdefault(norm_name, []).append(idx)

    matched_pms = []
    unmatched_pms = []
    matched_pm_indices = set()
    used_training_indices = set()

    # --- Pass 1: Email match ---
    pass1_count = 0
    for pm_idx, pm_row in unique_pms.iterrows():
        pm_email = pm_row.get("normalized_email", "")
        if not pm_email:
            continue

        if pm_email in training_by_email:
            t_indices = training_by_email[pm_email]
            matched_pms.append({
                "pm_idx": pm_idx,
                "full_name": pm_row["full_name"],
                "email": pm_row["email"],
                "normalized_name": pm_row["normalized_name"],
                "normalized_email": pm_email,
                "match_method": "email",
                "training_indices": t_indices,
            })
            matched_pm_indices.add(pm_idx)
            used_training_indices.update(t_indices)
            pass1_count += 1

    logger.info("Pass 1 (email): %d matches", pass1_count)

    # --- Pass 2: Exact full name match ---
    pass2_count = 0
    for pm_idx, pm_row in unique_pms.iterrows():
        if pm_idx in matched_pm_indices:
            continue

        pm_name = str(pm_row["full_name"]).strip()
        if not pm_name:
            continue

        if pm_name in training_by_name:
            t_indices = [i for i in training_by_name[pm_name] if i not in used_training_indices]
            if t_indices:
                matched_pms.append({
                    "pm_idx": pm_idx,
                    "full_name": pm_row["full_name"],
                    "email": pm_row["email"],
                    "normalized_name": pm_row["normalized_name"],
                    "normalized_email": pm_row.get("normalized_email", ""),
                    "match_method": "exact_name",
                    "training_indices": t_indices,
                })
                matched_pm_indices.add(pm_idx)
                used_training_indices.update(t_indices)
                pass2_count += 1

    logger.info("Pass 2 (exact name): %d matches", pass2_count)

    # --- Pass 3: Normalized name match ---
    pass3_count = 0
    for pm_idx, pm_row in unique_pms.iterrows():
        if pm_idx in matched_pm_indices:
            continue

        norm_name = pm_row["normalized_name"]
        if not norm_name:
            continue

        if norm_name in training_by_norm_name:
            t_indices = [i for i in training_by_norm_name[norm_name] if i not in used_training_indices]
            if t_indices:
                matched_pms.append({
                    "pm_idx": pm_idx,
                    "full_name": pm_row["full_name"],
                    "email": pm_row["email"],
                    "normalized_name": pm_row["normalized_name"],
                    "normalized_email": pm_row.get("normalized_email", ""),
                    "match_method": "normalized_name",
                    "training_indices": t_indices,
                })
                matched_pm_indices.add(pm_idx)
                used_training_indices.update(t_indices)
                pass3_count += 1

    logger.info("Pass 3 (normalized name): %d matches", pass3_count)

    # Collect unmatched PMs
    for pm_idx, pm_row in unique_pms.iterrows():
        if pm_idx not in matched_pm_indices:
            unmatched_pms.append({
                "full_name": pm_row["full_name"],
                "email": pm_row["email"],
                "normalized_name": pm_row["normalized_name"],
            })

    # Collect unmatched training records (unique people only)
    unmatched_training_people = set()
    unmatched_training = []
    for idx, row in training.iterrows():
        if idx not in used_training_indices:
            person_key = (row["normalized_name"], row["normalized_email"])
            if person_key not in unmatched_training_people:
                unmatched_training_people.add(person_key)
                unmatched_training.append({
                    "full_name": row.get("full_name", ""),
                    "email": row.get("email", ""),
                })

    logger.info(
        "Matching complete: %d matched, %d unmatched PMs, %d unmatched training people",
        len(matched_pms),
        len(unmatched_pms),
        len(unmatched_training),
    )

    return matched_pms, unmatched_pms, unmatched_training
