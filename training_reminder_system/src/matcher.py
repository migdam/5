##############################################################################
# matcher.py — Match PMs from ePPM Against Training Records in Fuse
#
# OVERVIEW:
#   This is the core matching engine of the training reminder system.
#   It takes two lists of people:
#     1. PMs from ePPM (who SHOULD have training)
#     2. Learners from Fuse (who HAVE training records)
#   ...and figures out which PM corresponds to which training record(s).
#
#   This is harder than it sounds because the two systems are independent.
#   A PM named "John Smith" with email "j.smith@corp.com" in ePPM might
#   appear as "John A. Smith" with email "john.smith@corp.com" in Fuse.
#   The matcher uses multiple strategies (passes) to handle these
#   discrepancies.
#
# THE 4-PASS MATCHING STRATEGY:
#   The matcher runs four passes in priority order. Each successive pass
#   uses a less strict (more fuzzy) matching criterion. Once a PM is
#   matched in an earlier pass, they are removed from later passes to
#   avoid double-matching.
#
#   Pass 0 — Alias Resolution (pre-processing):
#       Before any matching begins, we apply identity aliases. These are
#       manually maintained mappings for known mismatches (e.g., maiden
#       names, corporate email domain changes). This pass does not match
#       directly — it rewrites training records so they CAN match in the
#       subsequent passes.
#
#   Pass 1 — Email Match (highest confidence):
#       Match PMs to training records by normalized email address. Email
#       is the most reliable identifier because it is (in theory) globally
#       unique to a person. If two records share the same email, they are
#       almost certainly the same person.
#
#   Pass 2 — Exact Full Name Match:
#       For PMs not matched by email, try matching on exact full name
#       (as stored in the file, after whitespace trimming). This catches
#       cases where emails differ but names are identical.
#
#   Pass 3 — Normalized Name Match (most lenient):
#       For PMs still unmatched, try matching on normalized names (lowercased,
#       punctuation stripped, whitespace collapsed). This catches cases like
#       "O'Brien" vs "OBrien" or "Smith-Jones" vs "Smith Jones".
#
# WHY EACH PASS REMOVES MATCHED RECORDS FROM THE POOL:
#   Once a PM is matched in a given pass, both the PM and the corresponding
#   training records are marked as "used". This prevents the same PM from
#   being matched again in a later pass (which would create duplicates),
#   and prevents training records from being claimed by a less-confident
#   match when they were already correctly matched by a more-confident one.
#   For example, if "john@corp.com" matched in Pass 1 (email), we do not
#   want Pass 3 (normalized name) to also claim that same training record
#   for a different PM who happens to share the same normalized name.
#
# OUTPUT:
#   - matched_pms: PMs successfully linked to their Fuse training records.
#     Each entry includes the match method so we can audit HOW confidence.
#   - unmatched_pms: PMs from ePPM who have NO corresponding Fuse records.
#     These people may need to be enrolled in training, or there may be a
#     data issue (typo, missing record) that needs manual investigation.
#   - unmatched_training: People in Fuse who are NOT assigned as PMs in
#     ePPM. These are training records for people outside our target
#     audience (they completed training but are not current PMs).
##############################################################################

import logging
import pandas as pd
from src.normalizer import normalize_name, normalize_email

logger = logging.getLogger(__name__)


def _build_alias_lookups(aliases_df):
    """Build lookup dictionaries from the identity aliases DataFrame.

    WHAT THIS FUNCTION DOES:
        It reads the manually maintained alias file and creates two fast
        lookup dictionaries:
          1. email_to_canonical: maps an alias email to its canonical
             (correct/current) email. For example:
               "anna.kowalska@corp.com" -> "anna.nowak@corp.com"
             This handles cases like email changes after marriage.
          2. name_to_canonical: maps an alias name to its canonical name.
             For example:
               "anna kowalska" -> "anna nowak"

    WHY ALIAS RESOLUTION HAPPENS BEFORE STANDARD MATCHING:
        Some mismatches can NEVER be resolved by normalization alone.
        If someone changed their last name (marriage, legal change) or
        if two corporate systems use different email domains for the same
        person, no amount of lowercasing or punctuation removal will help.
        Aliases are the manual override that catches these known cases
        BEFORE the automated passes run, so those passes see corrected
        data and can match normally.

    Returns:
        (email_to_canonical, name_to_canonical) — two dicts for lookups.
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

        # Map alias email to canonical email (both normalized to lowercase).
        if alias_email and str(alias_email) not in ("", "None", "nan"):
            norm_alias = normalize_email(str(alias_email))
            if canon_email and str(canon_email) not in ("", "None", "nan"):
                email_map[norm_alias] = normalize_email(str(canon_email))

        # Map alias name to canonical name (both fully normalized).
        if alias_name and str(alias_name) not in ("", "None", "nan"):
            norm_alias = normalize_name(str(alias_name))
            if canon_name and str(canon_name) not in ("", "None", "nan"):
                name_map[norm_alias] = normalize_name(str(canon_name))

    logger.info("Alias lookups built: %d email aliases, %d name aliases", len(email_map), len(name_map))
    return email_map, name_map


def match_people(unique_pms, training_df, config, aliases_df=None):
    """Match PMs from ePPM against training records from Fuse.

    This is the main matching function. It runs the 4-pass strategy
    described in the module docstring above.

    Args:
        unique_pms: DataFrame of unique PM identities (from normalizer).
            Must have columns: full_name, email, normalized_name, normalized_email.
        training_df: DataFrame of Fuse training data.
            Must have columns: full_name, email (plus any course data columns).
        config: Application configuration (currently unused but reserved for
            future matching thresholds or options).
        aliases_df: Optional DataFrame of identity aliases. If provided,
            alias resolution (Pass 0) is performed before matching.

    Returns:
        (matched_pms, unmatched_pms, unmatched_training)
        - matched_pms: list of dicts, each containing PM info, the match
          method used, and indices into training_df for their records.
        - unmatched_pms: list of dicts for PMs with no Fuse match found.
        - unmatched_training: list of dicts for Fuse people not in ePPM.
    """

    # ===================================================================
    # PASS 0: Alias Resolution (pre-processing step)
    # Build lookup tables from the alias file, then apply them to the
    # training data. This "rewrites" alias emails/names to their canonical
    # forms so that Passes 1-3 can find them using normal matching.
    # ===================================================================
    email_aliases, name_aliases = _build_alias_lookups(aliases_df)

    # Prepare training data with normalized fields for matching.
    training = training_df.copy()
    training["normalized_email"] = training["email"].apply(
        lambda x: normalize_email(x) if x and str(x) not in ("", "None", "nan") else ""
    )
    training["normalized_name"] = training["full_name"].apply(
        lambda x: normalize_name(x) if x and str(x) not in ("", "None", "nan") else ""
    )

    # Apply alias resolution to training data: if a training record's email
    # or name is a known alias, replace it with the canonical version.
    # This way, when Pass 1 looks up a PM's email, it will find the training
    # record even if Fuse stored the old/alternate email.
    alias_resolved = 0
    if email_aliases or name_aliases:
        training["resolved_email"] = training["normalized_email"].apply(
            lambda e: email_aliases.get(e, e)
        )
        training["resolved_name"] = training["normalized_name"].apply(
            lambda n: name_aliases.get(n, n)
        )
        # Count how many records were actually changed by alias resolution.
        alias_resolved = int((training["resolved_email"] != training["normalized_email"]).sum() +
                             (training["resolved_name"] != training["normalized_name"]).sum())
        if alias_resolved > 0:
            logger.info("Pass 0 (aliases): %d training records resolved via aliases", alias_resolved)
    else:
        # No aliases provided — resolved fields are just copies of the originals.
        training["resolved_email"] = training["normalized_email"]
        training["resolved_name"] = training["normalized_name"]

    # ===================================================================
    # Build index structures for fast lookups during matching.
    # Instead of scanning the entire training DataFrame for each PM,
    # we pre-index training records by email, exact name, and normalized
    # name. Each index maps a key to a list of DataFrame row indices.
    # We index by BOTH original and resolved (alias-corrected) values
    # so that either version can produce a match.
    # ===================================================================
    training_by_email = {}      # normalized email -> list of row indices
    training_by_name = {}       # exact full name (trimmed) -> list of row indices
    training_by_norm_name = {}  # normalized name -> list of row indices

    for idx, row in training.iterrows():
        # Index by both original and resolved email (if alias changed it).
        for email in set(filter(None, [row["normalized_email"], row["resolved_email"]])):
            training_by_email.setdefault(email, []).append(idx)

        name = row.get("full_name", "")
        if name:
            training_by_name.setdefault(str(name).strip(), []).append(idx)

        # Index by both original and resolved normalized name.
        for norm_name in set(filter(None, [row["normalized_name"], row["resolved_name"]])):
            training_by_norm_name.setdefault(norm_name, []).append(idx)

    # These sets track which PMs and training records have been matched.
    # They grow as each pass claims matches, ensuring later passes only
    # consider the remaining unmatched records.
    matched_pms = []
    unmatched_pms = []
    matched_pm_indices = set()      # PM DataFrame indices that have been matched
    used_training_indices = set()   # Training DataFrame indices that have been claimed

    # ===================================================================
    # PASS 1: Email Match (highest priority, most reliable)
    #
    # WHY EMAIL HAS HIGHEST PRIORITY:
    #   Email addresses are designed to be unique identifiers. Unlike names
    #   (which can be shared by different people — "John Smith"), an email
    #   belongs to exactly one person. When emails match, we have very high
    #   confidence this is the same individual. That is why email matching
    #   runs first and its results take precedence over name-based passes.
    # ===================================================================
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

    # ===================================================================
    # PASS 2: Exact Full Name Match
    #
    # For PMs that could not be matched by email (maybe the email differs
    # between systems, or was missing in one of them), we fall back to
    # matching on exact full name. "Exact" means the name string must be
    # identical after whitespace trimming (but before normalization).
    #
    # We skip PMs already matched in Pass 1, and we only use training
    # records not already claimed in Pass 1.
    # ===================================================================
    pass2_count = 0
    for pm_idx, pm_row in unique_pms.iterrows():
        # Skip PMs already matched by email in Pass 1.
        if pm_idx in matched_pm_indices:
            continue

        pm_name = str(pm_row["full_name"]).strip()
        if not pm_name:
            continue

        if pm_name in training_by_name:
            # Only consider training records not already used by a prior pass.
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

    # ===================================================================
    # PASS 3: Normalized Name Match (most lenient)
    #
    # For PMs still unmatched after email and exact name, we try matching
    # on fully normalized names (lowercased, punctuation removed, whitespace
    # collapsed). This catches formatting differences like:
    #   "O'Brien, Mary-Jane" vs "obrien maryjane"
    #
    # This is the most lenient pass and has the lowest confidence. It runs
    # last so that higher-confidence matches always take precedence.
    # ===================================================================
    pass3_count = 0
    for pm_idx, pm_row in unique_pms.iterrows():
        # Skip PMs already matched in Pass 1 or Pass 2.
        if pm_idx in matched_pm_indices:
            continue

        norm_name = pm_row["normalized_name"]
        if not norm_name:
            continue

        if norm_name in training_by_norm_name:
            # Only consider training records not already used by prior passes.
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

    # ===================================================================
    # Collect unmatched PMs.
    #
    # WHAT unmatched_pms REPRESENTS:
    #   These are Project Managers listed in ePPM who could NOT be found
    #   in the Fuse training system by any matching method. Possible causes:
    #     - The PM has never been enrolled in the Fuse training platform.
    #     - The PM's name/email in ePPM is so different from Fuse that
    #       even normalized matching cannot reconcile them.
    #     - Data entry error in either system.
    #   These need manual review and possibly a new identity alias entry.
    # ===================================================================
    for pm_idx, pm_row in unique_pms.iterrows():
        if pm_idx not in matched_pm_indices:
            unmatched_pms.append({
                "full_name": pm_row["full_name"],
                "email": pm_row["email"],
                "normalized_name": pm_row["normalized_name"],
            })

    # ===================================================================
    # Collect unmatched training records (unique people only).
    #
    # WHAT unmatched_training REPRESENTS:
    #   These are people in the Fuse training system whose records were
    #   not claimed by any PM from ePPM. They are typically:
    #     - People who completed PM training but are not currently assigned
    #       as PMs on any active project.
    #     - Former PMs who moved to other roles.
    #     - People in other departments who took the same training course.
    #   We deduplicate by (name, email) to report unique people, not
    #   individual course records.
    # ===================================================================
    unmatched_training_people = set()
    unmatched_training = []
    for idx, row in training.iterrows():
        if idx not in used_training_indices:
            # Deduplicate by person identity so we do not list the same
            # person multiple times (they may have multiple course records).
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
