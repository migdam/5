import logging
import pandas as pd
from src.normalizer import normalize_name, normalize_email

logger = logging.getLogger(__name__)


def _build_alias_lookups(aliases_df):
    """Build lookup dicts from the identity aliases DataFrame.

    Returns:
        (email_to_canonical, name_to_canonical)
        email_to_canonical: maps alias_email -> canonical_email
        name_to_canonical: maps alias_name -> canonical_name
    """
    email_map = {}  # alias_email -> canonical_email
    name_map = {}   # normalized alias_name -> canonical_name

    if aliases_df is None or aliases_df.empty:
        return email_map, name_map

    for _, row in aliases_df.iterrows():
        canon_email = row.get("canonical_email")
        canon_name = row.get("canonical_name")
        alias_email = row.get("alias_email")
        alias_name = row.get("alias_name")

        if alias_email and str(alias_email) not in ("", "None", "nan"):
            norm_alias = normalize_email(str(alias_email))
            if canon_email and str(canon_email) not in ("", "None", "nan"):
                email_map[norm_alias] = normalize_email(str(canon_email))

        if alias_name and str(alias_name) not in ("", "None", "nan"):
            norm_alias = normalize_name(str(alias_name))
            if canon_name and str(canon_name) not in ("", "None", "nan"):
                name_map[norm_alias] = normalize_name(str(canon_name))

    logger.info("Alias lookups built: %d email aliases, %d name aliases", len(email_map), len(name_map))
    return email_map, name_map


def match_people(unique_pms, training_df, config, aliases_df=None):
    """Match PMs from ePPM against training records from Fuse.

    Pass 0: Resolve identity aliases (maiden names, email changes)
    Pass 1: Exact email match (normalized)
    Pass 2: Exact full name match
    Pass 3: Normalized name match

    Args:
        unique_pms: DataFrame of unique PM identities with normalized_name, normalized_email.
        training_df: DataFrame of Fuse training data with full_name, email columns.
        config: Application configuration.
        aliases_df: Optional DataFrame of identity aliases for resolving mismatches.

    Returns:
        (matched_pms, unmatched_pms, unmatched_training)
        matched_pms: list of dicts with PM info + training records
    """
    # --- Pass 0: Build alias lookups and resolve ---
    email_aliases, name_aliases = _build_alias_lookups(aliases_df)

    # Prepare training data with normalized fields
    training = training_df.copy()
    training["normalized_email"] = training["email"].apply(
        lambda x: normalize_email(x) if x and str(x) not in ("", "None", "nan") else ""
    )
    training["normalized_name"] = training["full_name"].apply(
        lambda x: normalize_name(x) if x and str(x) not in ("", "None", "nan") else ""
    )

    # Apply alias resolution to training data: if a training email/name is an alias,
    # add the canonical version so it can match against ePPM
    alias_resolved = 0
    if email_aliases or name_aliases:
        training["resolved_email"] = training["normalized_email"].apply(
            lambda e: email_aliases.get(e, e)
        )
        training["resolved_name"] = training["normalized_name"].apply(
            lambda n: name_aliases.get(n, n)
        )
        alias_resolved = int((training["resolved_email"] != training["normalized_email"]).sum() +
                             (training["resolved_name"] != training["normalized_name"]).sum())
        if alias_resolved > 0:
            logger.info("Pass 0 (aliases): %d training records resolved via aliases", alias_resolved)
    else:
        training["resolved_email"] = training["normalized_email"]
        training["resolved_name"] = training["normalized_name"]

    # Build lookup structures from training data
    # Use resolved (alias-corrected) email/name for matching
    training_by_email = {}
    training_by_name = {}
    training_by_norm_name = {}

    for idx, row in training.iterrows():
        # Index by both original and resolved email/name
        for email in set(filter(None, [row["normalized_email"], row["resolved_email"]])):
            training_by_email.setdefault(email, []).append(idx)

        name = row.get("full_name", "")
        if name:
            training_by_name.setdefault(str(name).strip(), []).append(idx)

        for norm_name in set(filter(None, [row["normalized_name"], row["resolved_name"]])):
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
