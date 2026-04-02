#!/usr/bin/env python3
##############################################################################
# generate_test_data.py — Synthetic Data Generator for Simulation
#
# Creates realistic test data to validate the training reminder system
# across multiple weekly cycles. Generates:
#   - ePPM Excel files (project assignments with gate compliance data)
#   - Fuse Excel files (training records with completion statuses)
#   - role_changes.xlsx (people who changed roles, appears gradually)
#   - excluded_projects.xlsx (ghost/cancelled projects, grows over time)
#   - identity_aliases.xlsx (maiden names, email domain mismatches)
#
# DATA GENERATION STRATEGY:
#   1. Build a shared "people master" (~350 synthetic people) with names,
#      emails, employment types, regions, etc.
#   2. Generate ePPM data from this master — projects with assigned PMs,
#      compliance fields, gate stages. ~35% of ePPM people also appear
#      in Fuse (the overlap that enables matching).
#   3. Generate Fuse data — training records per person. Training
#      completion rates increase each cycle (simulating people completing
#      courses over time).
#   4. Run cycles until all matchable PMs are certified.
#
# TIMING MODEL:
#   - Each cycle = 1 week (matching real operational cadence)
#   - Gate advancement: ~7.7% chance per project per week (avg 3 months/gate)
#   - Gate sequence: G0 → G1 → G2 → G3 → G4 → G5 → G6 → Completed
#   - Training completion: gradual over weeks, reaching 100% by week ~17
#   - New projects/PMs arrive every 3-4 weeks
#   - ~1-2% of projects get cancelled each cycle (ghost projects)
#
# EDGE CASES SIMULATED:
#   - Maiden names (women's last names differ between ePPM and Fuse)
#   - Email domain aliases (corp.example vs brand.example)
#   - Same person in PM + IT PM roles on the same project
#   - Small shared IT Portfolio Manager pool reused across projects
#   - People completing Advanced without Fundamentals (~8%)
#   - Contractors with external email domains
##############################################################################
"""Generate synthetic test data for the Training Reminder System."""
import argparse
import os
import random
import shutil
from datetime import datetime, timedelta

import openpyxl

# ============================================================
# Constants
# ============================================================

SEED = 42

DOMAINS = {
    "primary": "corp.example",
    "brand": "brand.example",
    "contractor": "contractor.example",
    "vendor": "vendor.example",
}

REGIONS = {
    "Europe": ["Poland", "Germany", "United Kingdom", "France", "Switzerland", "Sweden", "Portugal", "Netherlands"],
    "Americas": ["United States", "Canada", "Mexico", "Brazil", "Argentina"],
    "Asia Pacific": ["Japan", "China", "India", "Australia", "South Korea"],
    "Middle East & Africa": ["South Africa", "United Arab Emirates", "Turkey"],
}

FUNCTIONS = [
    "Information Technology", "Operations", "Finance", "Marketing",
    "Supply Chain", "Human Resources", "Legal", "Quality",
    "Research & Development", "Commercial",
]

POSITIONS = [
    "IT Project Manager", "Project Manager", "Senior Project Manager",
    "Program Manager", "Portfolio Manager", "IT Manager",
    "Digital Project Lead", "Transformation Manager",
]

# Non-PM roles for the role_changes.xlsx (people who left IT PM positions)
CHANGED_ROLE_NAMES = [
    "Business Analyst", "Solution Architect", "Data Engineer",
    "Product Owner", "Scrum Master", "DevOps Engineer",
    "Quality Assurance Lead", "Technical Consultant",
]

LEADING_FUNCTIONS = [
    "Operations", "Finance", "IT", "Marketing", "Supply Chain",
    "R&D", "Quality", "Commercial", "HR", "Legal",
]

PROJECT_ARCHETYPES = [
    "Simpler projects", "Complex projects", "Innovation projects",
    "Regulatory projects", "Infrastructure projects",
]

# Real gate distribution from ePPM data (G0→G1→G2→G3→G4→G5→G6→Completed)
STAGE_WEIGHTS = {
    "G0": 0.254, "G1": 0.066, "G2": 0.011, "G3": 0.225,
    "G4": 0.155, "G5": 0.244, "G6": 0.031, "Completed": 0.015,
}
# Ordered gate sequence for project progression
GATE_SEQUENCE = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "Completed"]
ARCHETYPE_WEIGHTS = [0.30, 0.35, 0.10, 0.15, 0.10]

COMPLIANCE_VALUES = ["Full compliance", "Partially compliant", "Non-compliant"]
# Realistic gate-specific action values from real ePPM data
G0_ACTIONS = {
    "Full compliance": "No action required",
    "Partially compliant": "No action required",
    "Non-compliant": "Create entry in LeanIX and assign Domain Architect",
}
G3_ACTIONS = {
    "Full compliance": "No action required",
    "Partially compliant": [
        "Stakeholder Agreement needed",
        "Stakeholder Agreement and G3 architecture review needed",
        "Stakeholder Agreement and G3 security review needed",
    ],
    "Non-compliant": "Stakeholder Agreement, G3 architecture and security review needed",
}
G5_ACTIONS = {
    "Full compliance": "No action required",
    "Partially compliant": "Transition Plan needed",
    "Non-compliant": "Transition Plan and G5 security review needed",
}
G6_ACTIONS = {
    "Full compliance": "No action required",
    "Partially compliant": "Closing Report needed",
    "Non-compliant": "Closing Report needed",
}
COMPLIANCE_ACTIONS = {
    "Full compliance": "No action required",
    "Partially compliant": "Action plan in progress",
    "Non-compliant": "Immediate action required",
}

COURSE_CATALOG = {
    "1920177": "Certification Test for Managing Projects for Business Success (Advanced)",
    "1920150": "Managing Projects for Business Success - Fundamentals - Certification Test",
    "1920200": "Introduction to Project Governance",
    "1920210": "Agile Methods for Enterprise Teams",
    "1920220": "Data Privacy Essentials",
}

FUNDAMENTALS_ID = "1920150"
ADVANCED_ID = "1920177"

# Curated name lists for reproducibility
# Includes Unicode/accented names to test cross-system normalization
FIRST_NAMES = [
    "Maya", "Daniel", "Olivia", "Sofia", "Emma", "Nathan", "Laura", "Kevin",
    "Noah", "Ava", "Liam", "Jenny", "Alex", "Lena", "James", "Sarah",
    "Michael", "Emily", "Robert", "Lisa", "Thomas", "Anna", "David", "Maria",
    "Chris", "Julia", "Peter", "Nina", "Mark", "Helen", "Paul", "Diana",
    "Andrew", "Rachel", "Steven", "Karen", "Brian", "Monica", "Jason", "Sandra",
    "Patrick", "Catherine", "George", "Stephanie", "Edward", "Victoria",
    "Frank", "Angela", "Richard", "Barbara", "Henry", "Claire", "Oscar",
    "Irene", "Martin", "Natalie", "Simon", "Vera", "Lucas", "Ingrid",
    "Felix", "Bianca", "Adrian", "Camille", "Hugo", "Daria", "Ivan",
    "Elena", "Tobias", "Fiona", "Lars", "Greta", "Erik", "Hannah",
    "Nils", "Johanna", "Sven", "Kristina", "Carlos", "Lucia", "Marco",
    "Petra", "Anton", "Sabine", "Jan", "Ursula", "Leo", "Theresa",
    "Max", "Rosa", "Robin", "Astrid", "Elias", "Marta", "Filip",
    "Dorota", "Pawel", "Agnieszka", "Tomas", "Katarina", "Andrei", "Simona",
    # Unicode/accented names — may get ASCII-ified in some systems
    "José", "François", "Łukasz", "Björn", "Søren", "René", "Müller-Hans",
    "Zoë", "Clémentine", "Héléne", "Jiří", "Małgorzata", "Péter", "Ádám",
]

# ASCII equivalents for Unicode names (simulates Fuse stripping accents)
UNICODE_TO_ASCII = {
    "José": "Jose", "François": "Francois", "Łukasz": "Lukasz",
    "Björn": "Bjorn", "Søren": "Soren", "René": "Rene",
    "Müller-Hans": "Muller-Hans", "Zoë": "Zoe", "Clémentine": "Clementine",
    "Héléne": "Helene", "Jiří": "Jiri", "Małgorzata": "Malgorzata",
    "Péter": "Peter", "Ádám": "Adam",
}

# Shared/generic email addresses used for team accounts
SHARED_EMAILS = [
    "pmo-team@corp.example",
    "it-projects@corp.example",
    "delivery-office@corp.example",
]

LAST_NAMES = [
    "Collins", "Carter", "Reed", "Bennett", "Foster", "Hayes", "Bishop",
    "Brooks", "Parker", "Turner", "Morgan", "Strid", "Rusu", "Chen",
    "Kim", "Singh", "Mueller", "Schmidt", "Johansson", "Andersson",
    "Nielsen", "Larsen", "Berg", "Kowalski", "Novak", "Horvat",
    "Popov", "Costa", "Santos", "Fernandez", "Garcia", "Lopez",
    "Martinez", "Rodriguez", "Wilson", "Thompson", "Anderson", "Taylor",
    "Brown", "Davis", "Miller", "Jackson", "White", "Harris",
    "Clark", "Lewis", "Robinson", "Walker", "Young", "Hall",
    "Allen", "King", "Wright", "Hill", "Scott", "Green",
    "Adams", "Baker", "Nelson", "Mitchell", "Roberts", "Campbell",
    "Petrov", "Koval", "Mazur", "Nowak", "Zielinski", "Szymanski",
    "Wojcik", "Wozniak", "Dabrowski", "Lewandowski", "Kaminski", "Piotrowski",
    "Eriksson", "Lindberg", "Svensson", "Holmberg", "Nilsson", "Gustafsson",
    "Richter", "Weber", "Fischer", "Becker", "Hoffmann", "Wagner",
    "Schneider", "Bauer", "Koch", "Braun", "Schwarz", "Krause",
    "Rossi", "Bianchi", "Moretti", "Colombo", "Ricci", "Esposito",
    "Dubois", "Moreau", "Laurent", "Bernard", "Leroy", "Roux",
]


# ============================================================
# People Master Builder
# ============================================================

def build_people_master(rng, num_people=200, name_collision_count=3):
    """Build a master list of synthetic people.

    Args:
        rng: Random number generator.
        num_people: Total people to generate.
        name_collision_count: Number of duplicate-name pairs to create
            (different people with the same full name but different emails).
    """
    used_emails = set()
    people = []

    # Shuffle name combos — wraps around if num_people exceeds combinations
    name_combos = []
    for fn in FIRST_NAMES:
        for ln in LAST_NAMES:
            name_combos.append((fn, ln))
    rng.shuffle(name_combos)

    # If we need more people than unique combos, allow reuse with numeric suffix
    if num_people > len(name_combos):
        extra_needed = num_people - len(name_combos)
        extra_combos = [name_combos[i % len(name_combos)] for i in range(extra_needed)]
        name_combos = name_combos + extra_combos

    for i in range(num_people):
        fn, ln = name_combos[i]
        full_name = f"{fn} {ln}"

        # Track if this is a Unicode name (for ASCII-ification in Fuse)
        has_unicode = fn in UNICODE_TO_ASCII

        # Employment type
        emp_roll = rng.random()
        if emp_roll < 0.82:
            emp_type = "Standard"
        elif emp_roll < 0.90:
            emp_type = "Foreign Assignee"
        else:
            emp_type = "Contractor"

        # Email domain
        if emp_type == "Contractor":
            domain = DOMAINS["contractor"]
        else:
            domain = DOMAINS["primary"]

        # For email, always use ASCII-safe version of name
        fn_email = UNICODE_TO_ASCII.get(fn, fn).lower().replace("-", "")
        ln_email = ln.lower().replace("-", "")
        local_part = f"{fn_email}.{ln_email}"
        email = f"{local_part}@{domain}"
        if email in used_emails:
            email = f"{local_part}{i}@{domain}"
        used_emails.add(email)

        region = rng.choice(list(REGIONS.keys()))
        country = rng.choice(REGIONS[region])
        function = rng.choice(FUNCTIONS)
        position = rng.choice(POSITIONS)
        gender = rng.choice(["Male", "Female"])

        # Hire date
        start = datetime(2010, 1, 1)
        days_range = (datetime(2024, 12, 31) - start).days
        hire_date = start + timedelta(days=rng.randint(0, days_range))

        people.append({
            "person_id": f"P{i+1:05d}",
            "full_name": full_name,
            "full_name_ascii": f"{UNICODE_TO_ASCII.get(fn, fn)} {ln}" if has_unicode else None,
            "first_name": fn,
            "last_name": ln,
            "email_primary": email,
            "email_aliases": [],
            "employment_type": emp_type,
            "region": region,
            "country": country,
            "function": function,
            "position": position,
            "gender": gender,
            "hire_date": hire_date,
            "pernr": 10000001 + i,
            "has_unicode_name": has_unicode,
            "is_shared_email": False,
        })

    # --- Name collisions: create pairs of different people with the same name ---
    # Pick existing people and create new people with the same name but different email
    non_unicode = [p for p in people if not p["has_unicode_name"]]
    collision_sources = rng.sample(non_unicode, min(name_collision_count, len(non_unicode)))
    for src in collision_sources:
        # Find the person and mark it
        new_id = f"P{len(people)+1:05d}"
        new_email = f"{src['first_name'].lower()}.{src['last_name'].lower()}.dup@{DOMAINS['primary']}"
        if new_email in used_emails:
            new_email = f"{src['first_name'].lower()}.{src['last_name'].lower()}.dup{len(people)}@{DOMAINS['primary']}"
        used_emails.add(new_email)
        people.append({
            "person_id": new_id,
            "full_name": src["full_name"],  # Same name!
            "full_name_ascii": None,
            "first_name": src["first_name"],
            "last_name": src["last_name"],
            "email_primary": new_email,
            "email_aliases": [],
            "employment_type": "Standard",
            "region": rng.choice(list(REGIONS.keys())),
            "country": rng.choice(sum(REGIONS.values(), [])),
            "function": rng.choice(FUNCTIONS),
            "position": rng.choice(POSITIONS),
            "gender": src["gender"],
            "hire_date": src["hire_date"] + timedelta(days=rng.randint(30, 365)),
            "pernr": 10000001 + len(people),
            "has_unicode_name": False,
            "is_shared_email": False,
            "name_collision_with": src["person_id"],
        })

    return people


def assign_aliases(people, rng, rate=0.065):
    """Assign email aliases to a subset of people."""
    count = int(len(people) * rate)
    candidates = [p for p in people if p["employment_type"] != "Contractor"]
    alias_people = rng.sample(candidates, min(count, len(candidates)))

    for p in alias_people:
        local = p["email_primary"].split("@")[0]
        alias_domain = DOMAINS["brand"]
        p["email_aliases"].append(f"{local}@{alias_domain}")

    return [p["person_id"] for p in alias_people]


def build_portfolio_pool(people, rng, pool_size=25):
    """Select a small pool of IT Portfolio Managers for reuse across ePPM."""
    candidates = [p for p in people if p["employment_type"] != "Contractor"]
    pool = rng.sample(candidates, min(pool_size, len(candidates)))
    return pool


# ============================================================
# ePPM Generator
# ============================================================

def generate_eppm_data(people, portfolio_pool, rng, num_projects=250,
                       completed_project_ids=None, new_project_start=0,
                       stage_overrides=None, cancelled_project_ids=None,
                       compliance_state=None, compliance_noise=None):
    """Generate ePPM project assignment data.

    Args:
        people: People master list.
        portfolio_pool: IT Portfolio Manager pool.
        rng: Random number generator.
        num_projects: Number of projects to generate.
        completed_project_ids: Set of project IDs that should be marked Completed.
        new_project_start: Index offset for new projects (to generate unique IDs).
        stage_overrides: Dict of project_id -> new_stage for evolution.
        compliance_state: Dict of project_id -> {gate: status} tracking compliance
            evolution across cycles. Mutated in place.
        compliance_noise: Dict with noise rates: late_discovery, data_correction,
            stale_rollup. Defaults to 0.03, 0.04, 0.05.
    """
    if compliance_noise is None:
        compliance_noise = {}
    noise_late_discovery = compliance_noise.get("late_discovery", 0.03)
    noise_data_correction = compliance_noise.get("data_correction", 0.04)
    noise_stale_rollup = compliance_noise.get("stale_rollup", 0.05)
    if completed_project_ids is None:
        completed_project_ids = set()
    if stage_overrides is None:
        stage_overrides = {}
    if cancelled_project_ids is None:
        cancelled_project_ids = set()

    non_contractor_people = [p for p in people if p["employment_type"] != "Contractor"]
    rows = []
    project_names_used = set()

    project_name_templates = [
        "Global {} Enablement", "{} Data Hub", "{} Transformation Program",
        "{} Platform Migration", "Digital {} Initiative", "{} Process Optimization",
        "{} System Upgrade", "Enterprise {} Integration", "{} Analytics Platform",
        "{} Compliance Framework", "Next-Gen {} Solution", "{} Workflow Automation",
        "{} Security Enhancement", "{} Cloud Migration", "{} Customer Experience",
        "Regional {} Rollout", "{} Supply Chain Digitization", "{} ERP Enhancement",
        "{} Quality Management", "{} Innovation Lab",
    ]
    name_nouns = [
        "Payments", "Retail", "Manufacturing", "Finance", "HR", "Logistics",
        "Marketing", "Sales", "Procurement", "Quality", "Regulatory",
        "Operations", "IT", "Data", "CRM", "ERP", "SAP", "Cloud",
        "Mobile", "Web", "AI", "IoT", "Blockchain", "RPA", "DevOps",
    ]

    for i in range(num_projects):
        proj_id = f"PRJ{1000000 + new_project_start + i}"

        # Generate unique project name
        attempts = 0
        while True:
            template = rng.choice(project_name_templates)
            noun = rng.choice(name_nouns)
            country = rng.choice(sum(REGIONS.values(), []))
            pname = template.format(noun)
            if rng.random() < 0.3:
                pname += f" {country}"
            if pname not in project_names_used or attempts > 10:
                project_names_used.add(pname)
                break
            attempts += 1

        # Stage
        if proj_id in completed_project_ids:
            stage = "Completed"
            status = "Completed"
        elif proj_id in cancelled_project_ids:
            # Ghost projects: cancelled but status not updated in ePPM
            # They still show "Not Completed" with their last known stage
            stage = stage_overrides.get(proj_id, rng.choice(["G0", "G1", "G2", "G3"]))
            status = "Not Completed"  # Stale — not updated
        elif proj_id in stage_overrides:
            stage = stage_overrides[proj_id]
            status = "Completed" if stage == "Completed" else "Not Completed"
        else:
            stage = rng.choices(
                list(STAGE_WEIGHTS.keys()),
                weights=list(STAGE_WEIGHTS.values())
            )[0]
            status = "Completed" if stage == "Completed" else "Not Completed"

        leading_function = rng.choice(LEADING_FUNCTIONS)
        sub_function = None if rng.random() < 0.666 else rng.choice(LEADING_FUNCTIONS)
        archetype = rng.choices(PROJECT_ARCHETYPES, weights=ARCHETYPE_WEIGHTS)[0]

        # Assign roles
        # Project Owner (23.6% null)
        if rng.random() < 0.236:
            owner, owner_email = None, None
        else:
            p = rng.choice(non_contractor_people)
            owner, owner_email = p["full_name"], p["email_primary"]

        # Project Manager (0.3% null)
        if rng.random() < 0.003:
            pm, pm_email = None, None
        else:
            p = rng.choice(non_contractor_people)
            pm, pm_email = p["full_name"], p["email_primary"]

        # IT Project Manager (7.6% null)
        if rng.random() < 0.076:
            it_pm, it_pm_email = None, None
        else:
            # 12% chance: same as PM
            if pm and rng.random() < 0.12:
                it_pm, it_pm_email = pm, pm_email
            else:
                p = rng.choice(non_contractor_people)
                it_pm, it_pm_email = p["full_name"], p["email_primary"]

        # Owner == PM (5% of rows where both exist)
        if owner and pm and rng.random() < 0.05:
            owner, owner_email = pm, pm_email

        # IT Portfolio Manager from pool (7.9% null)
        if rng.random() < 0.079:
            it_port, it_port_email = None, None
        else:
            p = rng.choice(portfolio_pool)
            it_port, it_port_email = p["full_name"], p["email_primary"]
            # 3% chance: IT PM == IT Portfolio Manager
            if it_pm and rng.random() < 0.03:
                it_port, it_port_email = it_pm, it_pm_email

        # Compliance fields (sparse — populated for gates the project has passed)
        # Compliance evolves across cycles: Non-compliant -> Partially -> Full
        # Once a gate reaches Full compliance, it stays there.
        g0_comp, g0_act = (None, None)
        g3_comp, g3_act = (None, None)
        g5_comp, g5_act = (None, None)
        g6_comp, g6_act = (None, None)

        stage_idx = GATE_SEQUENCE.index(stage) if stage in GATE_SEQUENCE else 0

        if compliance_state is not None:
            proj_comp = compliance_state.setdefault(proj_id, {})
        else:
            proj_comp = {}

        def _evolve_gate(gate, min_stage_idx, appear_prob, action_map):
            """Get compliance for a gate, evolving from prior state.

            Noise scenarios (matching real ePPM data quality issues):
            - 3% chance: late discovery — audit reveals non-compliance at an
              earlier gate that was previously reported as fully compliant
            - 4% chance of temporary regression — a review downgrades
              Partially compliant back to Non-compliant (data correction)
            - Compliance data may disappear for a cycle (appear_prob) and
              come back — simulating inconsistent reporting
            """
            if stage_idx < min_stage_idx:
                return None, None
            if rng.random() < appear_prob:
                return None, None  # Not reported this cycle

            prev = proj_comp.get(gate)
            if prev is None:
                # First time: assign initial compliance (weighted toward non-compliant)
                val = rng.choices(COMPLIANCE_VALUES, weights=[0.25, 0.40, 0.35])[0]
            elif prev == "Full compliance":
                # Late-discovery: audit finds issues at a gate that was
                # previously marked fully compliant
                if rng.random() < noise_late_discovery:
                    val = rng.choice(["Partially compliant", "Non-compliant"])
                else:
                    val = "Full compliance"
            elif prev == "Partially compliant":
                roll = rng.random()
                if roll < 0.30:
                    val = "Full compliance"
                elif roll < 0.30 + noise_data_correction:
                    # Data correction — downgraded after closer review
                    val = "Non-compliant"
                else:
                    val = "Partially compliant"
            else:  # Non-compliant
                # 20% chance to improve to Partially, 5% chance to jump to Full
                roll = rng.random()
                if roll < 0.05:
                    val = "Full compliance"
                elif roll < 0.25:
                    val = "Partially compliant"
                else:
                    val = "Non-compliant"

            proj_comp[gate] = val
            act = action_map[val]
            act = rng.choice(act) if isinstance(act, list) else act
            return val, act

        # G0 compliance if past G0 (43% chance of being reported)
        g0_comp, g0_act = _evolve_gate("G0", 1, 0.57, G0_ACTIONS)
        # G3 compliance if past G3 (27% chance of being reported)
        g3_comp, g3_act = _evolve_gate("G3", 4, 0.73, G3_ACTIONS)
        # G5 compliance if past G5 (4% chance of being reported)
        g5_comp, g5_act = _evolve_gate("G5", 6, 0.96, G5_ACTIONS)
        # G6 compliance if past G6 (2% chance of being reported)
        g6_comp, g6_act = _evolve_gate("G6", 7, 0.98, G6_ACTIONS)

        # Overall project compliance also evolves (with noise)
        # Noise: 5% chance overall compliance contradicts individual gates
        # (e.g., all gates Full but overall shows Partially — stale rollup)
        prev_proj = proj_comp.get("project")
        if rng.random() > 0.476:
            if prev_proj is None:
                proj_compliance = rng.choices(
                    COMPLIANCE_VALUES, weights=[0.5, 0.35, 0.15]
                )[0]
            elif prev_proj == "Full compliance":
                # 5% stale rollup: overall hasn't been refreshed after a
                # gate-level regression, so it still says Full even though
                # a gate was downgraded, or vice versa
                proj_compliance = "Partially compliant" if rng.random() < noise_stale_rollup else "Full compliance"
            elif prev_proj == "Partially compliant":
                roll = rng.random()
                if roll < 0.25:
                    proj_compliance = "Full compliance"
                elif roll < 0.25 + noise_data_correction:
                    proj_compliance = "Non-compliant"
                else:
                    proj_compliance = "Partially compliant"
            else:
                    proj_compliance = "Non-compliant"
            proj_comp["project"] = proj_compliance
        else:
            proj_compliance = None

        rows.append({
            "Project number": proj_id,
            "Project Name": pname,
            "Leading Function": leading_function,
            "Sub Function": sub_function,
            "Active Stage": stage,
            "Project Status": status,
            "Project Archetype": archetype,
            "Project Owner": owner,
            "Project Owner Email": owner_email,
            "Project Manager": pm,
            "Project Manager Email": pm_email,
            "IT Project Manager": it_pm,
            "IT Project Manager Email": it_pm_email,
            "IT Portfolio Manager": it_port,
            "IT Portfolio Manager Email": it_port_email,
            "G0 Compliance": g0_comp,
            "G0 Action": g0_act,
            "G3 Compliance": g3_comp,
            "G3 Action": g3_act,
            "G5 Compliance": g5_comp,
            "G5 Action": g5_act,
            "G6 Compliance": g6_comp,
            "G6 Action": g6_act,
            "Project Compliance": proj_compliance,
        })

    return rows


# ============================================================
# Fuse Generator
# ============================================================

def generate_fuse_data(fuse_people, person_training_state, rng, cycle_num=1,
                       params=None):
    """Generate Fuse training data using tracked per-person training state.

    Args:
        fuse_people: List of person dicts to include in Fuse.
        person_training_state: Dict of person_id -> {fund_completed, adv_completed}.
        rng: Random number generator.
        cycle_num: Cycle number (affects dates).
        params: Generation parameters dict.
    """
    if params is None:
        params = {}
    training_fail_rate = params.get("training_fail_rate", 0.05)
    passing_score = params.get("training_passing_score", 70.0)
    in_progress_rate = params.get("training_in_progress_rate", 0.08)
    stale_fuse_rate = params.get("stale_fuse_rate", 0.03)
    export_offset_days = params.get("export_date_offset_days", 2)
    unicode_ascii_rate = params.get("unicode_name_ascii_rate", 0.5)

    rows = []
    imdl_counter = 100001 + (cycle_num - 1) * 10000

    base_date = datetime(2025, 10, 1)
    cycle_offset = timedelta(days=(cycle_num - 1) * 14)
    # Export date mismatch: Fuse export may be offset by 0-N days from ePPM
    fuse_date_offset = timedelta(days=rng.randint(0, export_offset_days))

    for person in fuse_people:
        pid = person["person_id"]
        state = person_training_state.get(pid, {})

        # Stale Fuse data: some people's data is 1 cycle behind
        if rng.random() < stale_fuse_rate and cycle_num > 1:
            prev_state = state.get("_prev", {})
            fund_completed = prev_state.get("fund_completed", False)
            adv_completed = prev_state.get("adv_completed", False)
        else:
            fund_completed = state.get("fund_completed", False)
            adv_completed = state.get("adv_completed", False)

        courses = [
            (FUNDAMENTALS_ID, fund_completed),
            (ADVANCED_ID, adv_completed),
        ]

        # Noise courses (0-2 extra)
        noise_count = rng.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        noise_ids = rng.sample(["1920200", "1920210", "1920220"], min(noise_count, 3))
        for nid in noise_ids:
            courses.append((nid, rng.random() < 0.80))

        # Use alias email for alias cases (50% chance)
        email = person["email_primary"]
        if person["email_aliases"] and rng.random() < 0.5:
            email = person["email_aliases"][0]

        # Unicode name ASCII-ification: some systems strip accents
        display_name = person["full_name"]
        if person.get("has_unicode_name") and person.get("full_name_ascii"):
            if rng.random() < unicode_ascii_rate:
                display_name = person["full_name_ascii"]

        # Generate hire date text
        hire_date = person["hire_date"]
        hire_text = hire_date.strftime("%A, %B ") + str(hire_date.day) + hire_date.strftime(", %Y")

        user_id = person["email_primary"].split("@")[0].replace(".", "")

        for course_id, is_completed in courses:
            start_date = base_date + cycle_offset + fuse_date_offset + timedelta(days=rng.randint(0, 60))
            completion_date = None
            score = None

            if is_completed:
                completion_date = start_date + timedelta(days=rng.randint(0, 14))
                score = round(rng.gauss(85, 8), 1)
                score = max(60.0, min(100.0, score))

                # Training score below passing: completed but failed
                if rng.random() < training_fail_rate:
                    score = round(rng.uniform(30.0, passing_score - 0.1), 1)
                    # Status still shows "completed" but score is failing
                    # (real Fuse data quirk: completion doesn't guarantee passing)

                status = "completed"
            else:
                # Partial progress: some courses show "in_progress"
                if rng.random() < in_progress_rate:
                    status = "in_progress"
                    start_date = base_date + cycle_offset + timedelta(days=rng.randint(0, 30))
                else:
                    status = "incomplete"

            content_group = None
            if rng.random() < 0.10:
                content_group = "Project Management"

            rows.append({
                "IMDL ID": imdl_counter,
                "PerNR": person["pernr"],
                "User ID": user_id,
                "Full Name": display_name,
                "Gender": person["gender"],
                "Email": email,
                "Employee Group": person["employment_type"],
                "Geographical Region": person["region"],
                "Country": person["country"],
                "Function": person["function"],
                "Position": person["position"],
                "Hire Date": hire_text,
                "Content ID": course_id,
                "Content Title": COURSE_CATALOG[course_id],
                "Course Status": status,
                "Start Date": start_date.strftime("%Y-%m-%d"),
                "Completion Date": completion_date.strftime("%Y-%m-%d") if completion_date else None,
                "Score": score,
                "Content Group": content_group,
            })
            imdl_counter += 1

    return rows


# ============================================================
# Excel Writer
# ============================================================

def write_excel(rows, filepath, sheet_name="Sheet1"):
    """Write a list of dicts to an Excel file."""
    if not rows:
        return

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    headers = list(rows[0].keys())
    ws.append(headers)

    for row in rows:
        ws.append([row.get(h) for h in headers])

    # Auto-size columns
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            if cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = min(max_len + 2, 50)

    wb.save(filepath)


# ============================================================
# Multi-Cycle Generation
# ============================================================

# Default generation parameters — override via CLI or by passing a dict
DEFAULT_PARAMS = {
    # Population sizes
    "num_people": 350,              # Total synthetic people in master list
    "num_projects": 250,            # Initial number of projects
    "portfolio_pool_size": 25,      # IT Portfolio Managers reused across projects
    "initial_eppm_pool": 160,       # People in initial ePPM pool (non-contractors)
    "extra_fuse_people": 60,        # Fuse-only background learners

    # Overlap and matching
    "overlap_rate": 0.35,           # % of ePPM people also in Fuse (matchable)
    "alias_rate": 0.065,            # % of people with email domain aliases
    "role_change_rate": 0.10,       # % of overlap people who change roles
    "maiden_name_count": 4,         # Number of maiden name alias cases
    "email_alias_count": 5,         # Number of email domain alias cases

    # Project evolution
    "gate_advance_prob": 1.0 / 13,  # Per-project per-week gate advancement (~7.7%)
    "cancel_rate_min": 0.005,       # Min % of active projects cancelled per cycle
    "cancel_rate_max": 0.015,       # Max % of active projects cancelled per cycle

    # Training completion speed (multiplier; 1.0 = default pace)
    "training_speed": 1.0,          # >1 = faster certification, <1 = slower

    # Compliance noise rates
    "compliance_late_discovery_rate": 0.03,   # Audit finds issues at previously Full gate
    "compliance_data_correction_rate": 0.04,  # Partially downgraded to Non-compliant
    "compliance_stale_rollup_rate": 0.05,     # Overall contradicts gate-level status

    # Skip path: complete Advanced without Fundamentals
    "skip_fundamentals_rate": 0.08,  # % of people who skip Fundamentals

    # New PM waves: list of (week, new_projects, new_pms)
    # Set to [] to disable new PM arrivals
    "new_pm_waves": [
        (3, 8, 4), (4, 8, 4),
        (7, 6, 3), (8, 6, 3),
        (11, 5, 3), (12, 5, 3),
        (15, 4, 2), (16, 4, 2),
        (19, 3, 2),
    ],

    # --- New edge case scenarios ---

    # People lifecycle
    "pm_leave_rate": 0.02,           # % of PMs who leave org per cycle
    "pm_leave_start_cycle": 4,       # First cycle PMs can leave
    "pm_readd_rate": 0.3,            # % of removed PMs who get re-added later
    "pm_transfer_rate": 0.05,        # % of PMs who change project assignments per cycle

    # Data quality noise
    "name_collision_count": 3,       # Number of duplicate-name pairs (different people, same name)
    "unicode_name_ascii_rate": 0.5,  # % of Unicode-named people who appear ASCII-ified in Fuse
    "shared_email_rate": 0.02,       # % of projects using shared/generic PM email
    "project_rename_rate": 0.03,     # % of projects that change name between cycles

    # Training edge cases
    "training_fail_rate": 0.05,      # % of "completed" courses with score below passing
    "training_passing_score": 70.0,  # Minimum passing score
    "training_revoke_rate": 0.02,    # % of completed trainings that get revoked per cycle
    "training_in_progress_rate": 0.08,  # % of courses shown as "in_progress" instead of incomplete

    # Timing
    "stale_fuse_rate": 0.03,         # % of people whose Fuse data is 1 cycle behind
    "export_date_offset_days": 2,    # Max days between ePPM and Fuse exports

    # Scale
    "heavy_pm_count": 2,             # Number of PMs assigned to 20+ projects
    "heavy_pm_project_count": 25,    # How many projects per heavy PM
}


def generate_all_cycles(rng, max_cycles=30, params=None):
    """Generate cycles until ALL PMs are fully certified.

    Args:
        rng: Random number generator.
        max_cycles: Maximum number of weekly cycles to generate.
        params: Dict of generation parameters (see DEFAULT_PARAMS).
            Any key not provided falls back to the default value.
    """
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)

    people = build_people_master(rng, num_people=p["num_people"],
                                name_collision_count=p.get("name_collision_count", 3))
    alias_ids = assign_aliases(people, rng, rate=p["alias_rate"])
    portfolio_pool = build_portfolio_pool(people, rng, pool_size=p["portfolio_pool_size"])

    non_contractor = [p_person for p_person in people if p_person["employment_type"] != "Contractor"]
    people_by_id = {p_person["person_id"]: p_person for p_person in people}

    # Ensure name-collision people are in the initial pool (not just the reserve)
    collision_people = [p_person for p_person in people if p_person.get("name_collision_with")]
    regular_non_contractor = [p_person for p_person in non_contractor if not p_person.get("name_collision_with")]

    initial_pool_size = min(p["initial_eppm_pool"], len(regular_non_contractor))
    initial_eppm_pool = regular_non_contractor[:initial_pool_size] + collision_people
    new_pm_reserve = regular_non_contractor[initial_pool_size:]
    rng.shuffle(new_pm_reserve)

    overlap_count = int(len(initial_eppm_pool) * p["overlap_rate"])
    overlap_people = rng.sample(initial_eppm_pool, overlap_count)
    overlap_ids = {op["person_id"] for op in overlap_people}

    role_change_pool_count = max(4, int(len(overlap_people) * p["role_change_rate"]))
    role_change_pool = rng.sample(overlap_people, role_change_pool_count)
    role_change_pool_ids = {rc["person_id"] for rc in role_change_pool}

    fuse_only_candidates = [fp for fp in people if fp["person_id"] not in overlap_ids
                            and fp not in initial_eppm_pool]
    extra_fuse_count = min(p["extra_fuse_people"], len(fuse_only_candidates))
    extra_fuse = rng.sample(fuse_only_candidates, extra_fuse_count)
    extra_fuse_ids = {ef["person_id"] for ef in extra_fuse}

    # Track per-person training state: person_id -> {fund_completed, adv_completed}
    person_training_state = {}

    # Track all project IDs and their completion state
    all_project_ids = []
    completed_project_ids = set()
    cancelled_project_ids = set()  # Ghost projects — cancelled but not updated in ePPM
    stage_overrides = {}
    compliance_state = {}  # project_id -> {gate: status} — tracks compliance evolution
    removed_pms = []       # (cycle_num, person) — PMs who left, may be re-added

    # Track which people are currently in the ePPM people pool (for assigning to projects)
    active_eppm_people = list(initial_eppm_pool)
    # Track all people who have ever been in ePPM (need to appear in Fuse)
    all_eppm_person_ids = {p["person_id"] for p in initial_eppm_pool}

    # New PMs added per cycle (for reporting)
    new_pms_per_cycle = {}

    cycles_data = {}

    # --- Weekly cycle timing ---
    # Each cycle = 1 week
    # Gate advancement: avg 3 months per gate = ~13 weeks
    #   -> probability of advancing per project per week ≈ 1/13 ≈ 0.077
    # Training completion: people typically complete within 2-6 weeks after reminder
    #   -> per-week completion probability starts low and increases over time
    # New projects/PMs arrive periodically (every few weeks)
    GATE_ADVANCE_PROB = p["gate_advance_prob"]
    training_speed = p["training_speed"]
    skip_fund_rate = p["skip_fundamentals_rate"]

    # Build lookup for new PM waves: week -> (n_projects, n_pms)
    wave_lookup = {}
    for wave_week, wave_proj, wave_pms in p["new_pm_waves"]:
        wave_lookup[wave_week] = (wave_proj, wave_pms)

    compliance_noise = {
        "late_discovery": p["compliance_late_discovery_rate"],
        "data_correction": p["compliance_data_correction_rate"],
        "stale_rollup": p["compliance_stale_rollup_rate"],
    }

    new_project_offset = 0

    for cycle_num in range(1, max_cycles + 1):
        week = cycle_num

        # Training completion probability increases over weeks.
        # training_speed multiplier scales the curve: >1 = faster, <1 = slower.
        if week <= 4:
            fund_chance = (0.05 + week * 0.02) * training_speed
            adv_chance = (0.02 + week * 0.01) * training_speed
        elif week <= 8:
            fund_chance = (0.12 + (week - 4) * 0.03) * training_speed
            adv_chance = (0.08 + (week - 4) * 0.03) * training_speed
        elif week <= 12:
            fund_chance = (0.25 + (week - 8) * 0.05) * training_speed
            adv_chance = (0.20 + (week - 8) * 0.05) * training_speed
        elif week <= 16:
            fund_chance = (0.50 + (week - 12) * 0.10) * training_speed
            adv_chance = (0.45 + (week - 12) * 0.10) * training_speed
        elif week <= 20:
            fund_chance = (0.90 + (week - 16) * 0.025) * training_speed
            adv_chance = (0.85 + (week - 16) * 0.03) * training_speed
        else:
            fund_chance = 1.0
            adv_chance = 1.0

        fund_chance = min(fund_chance, 1.0)
        adv_chance = min(adv_chance, 1.0)

        # New projects/PMs arrive based on configured waves
        n_new_projects, n_new_pms = wave_lookup.get(week, (0, 0))

        label = f"week {week}"
        print(f"Generating Cycle {cycle_num} ({label})...")

        # --- Add new PMs from reserve ---
        new_pms_this_cycle = []
        if n_new_pms > 0 and new_pm_reserve:
            actual_new = min(n_new_pms, len(new_pm_reserve))
            new_pms_this_cycle = new_pm_reserve[:actual_new]
            new_pm_reserve = new_pm_reserve[actual_new:]
            active_eppm_people.extend(new_pms_this_cycle)
            # New PMs also need to appear in Fuse as overlap
            for new_pm in new_pms_this_cycle:
                overlap_ids.add(new_pm["person_id"])
                all_eppm_person_ids.add(new_pm["person_id"])
        new_pms_per_cycle[cycle_num] = len(new_pms_this_cycle)

        # --- PM leaves organization ---
        # After cycle N, some PMs disappear from the ePPM pool entirely
        if cycle_num >= p["pm_leave_start_cycle"] and p["pm_leave_rate"] > 0:
            n_leave = max(0, int(len(active_eppm_people) * p["pm_leave_rate"]))
            if n_leave > 0:
                leavers = rng.sample(active_eppm_people, min(n_leave, len(active_eppm_people)))
                for leaver in leavers:
                    active_eppm_people.remove(leaver)
                    # Track for possible re-add later
                    removed_pms.append((cycle_num, leaver))

        # --- PM temporarily removed then re-added ---
        if removed_pms and p["pm_readd_rate"] > 0:
            still_removed = [(c, pm) for c, pm in removed_pms
                             if pm not in active_eppm_people and cycle_num - c >= 2]
            for rem_cycle, pm in still_removed:
                if rng.random() < p["pm_readd_rate"]:
                    active_eppm_people.append(pm)
                    removed_pms.remove((rem_cycle, pm))

        # shared_email_projects: applied post-generation on eppm_rows
        shared_email_count = max(0, int(p["num_projects"] * p["shared_email_rate"]))

        # --- Heavy PMs: assign some people to many projects ---
        # (tracked separately, injected into ePPM rows after generation)
        heavy_pms = []
        if cycle_num == 1 and p["heavy_pm_count"] > 0:
            heavy_candidates = [hp for hp in active_eppm_people if hp["employment_type"] != "Contractor"]
            heavy_pms = rng.sample(heavy_candidates, min(p["heavy_pm_count"], len(heavy_candidates)))

        # --- PM transfers: shuffle project assignments for some PMs ---
        # (happens naturally since generate_eppm_data randomly assigns PMs each cycle)
        # We force it by removing/re-adding some PMs to change their position in the pool
        if cycle_num > 1 and p["pm_transfer_rate"] > 0:
            n_transfer = max(0, int(len(active_eppm_people) * p["pm_transfer_rate"]))
            if n_transfer > 0:
                transfer_pms = rng.sample(active_eppm_people, min(n_transfer, len(active_eppm_people)))
                for tpm in transfer_pms:
                    active_eppm_people.remove(tpm)
                    # Re-insert at random position (changes which projects they get assigned to)
                    active_eppm_people.insert(rng.randint(0, len(active_eppm_people)), tpm)

        # --- Update training state ---
        # All people in overlap_ids + extra_fuse need training state
        all_fuse_person_ids = overlap_ids | extra_fuse_ids

        for pid in all_fuse_person_ids:
            if pid not in person_training_state:
                person_training_state[pid] = {"fund_completed": False, "adv_completed": False}

            state = person_training_state[pid]

            # Save previous state for stale Fuse data simulation
            state["_prev"] = {"fund_completed": state["fund_completed"], "adv_completed": state["adv_completed"]}

            # Training revoked/expired: previously completed training gets removed
            if p["training_revoke_rate"] > 0:
                if state["fund_completed"] and rng.random() < p["training_revoke_rate"]:
                    state["fund_completed"] = False
                if state["adv_completed"] and rng.random() < p["training_revoke_rate"]:
                    state["adv_completed"] = False

            # Progress training: usually fundamentals first, then advanced
            if not state["fund_completed"]:
                if rng.random() < fund_chance:
                    state["fund_completed"] = True
            if not state["adv_completed"]:
                if state["fund_completed"]:
                    # Normal path: fundamentals done, now try advanced
                    if rng.random() < adv_chance:
                        state["adv_completed"] = True
                elif rng.random() < adv_chance * skip_fund_rate:
                    # Skip path: complete advanced without fundamentals
                    state["adv_completed"] = True

        # --- Evolve ePPM project state ---
        if cycle_num == 1:
            # Generate base projects
            eppm_rows = generate_eppm_data(
                active_eppm_people, portfolio_pool, rng,
                num_projects=p["num_projects"],
                compliance_state=compliance_state,
                compliance_noise=compliance_noise,
            )
            all_project_ids = [r["Project number"] for r in eppm_rows]
            # Record initial stages for each project
            for row in eppm_rows:
                pid = row["Project number"]
                if pid not in stage_overrides:
                    stage_overrides[pid] = row["Active Stage"]
        else:
            # Cancel ~1-2% of active projects per cycle (ghost projects)
            still_active = [pid for pid in all_project_ids
                            if pid not in completed_project_ids and pid not in cancelled_project_ids]
            n_cancel = max(0, int(len(still_active) * rng.uniform(p["cancel_rate_min"], p["cancel_rate_max"])))
            if n_cancel > 0:
                newly_cancelled = rng.sample(still_active, n_cancel)
                cancelled_project_ids.update(newly_cancelled)
                still_active = [pid for pid in still_active if pid not in cancelled_project_ids]

            # Advance projects through gate sequence (G0→G1→...→G6→Completed)
            # Each project has ~7.7% chance of advancing 1 gate per week (avg 3 months/gate)
            for pid in still_active:
                if rng.random() < GATE_ADVANCE_PROB:
                    current = stage_overrides.get(pid, "G0")
                    if current in GATE_SEQUENCE:
                        idx = GATE_SEQUENCE.index(current)
                        # Advance 1 gate (occasionally 2 for faster projects)
                        advance = 1 if rng.random() < 0.85 else 2
                        new_idx = min(idx + advance, len(GATE_SEQUENCE) - 1)
                        new_stage = GATE_SEQUENCE[new_idx]
                        stage_overrides[pid] = new_stage
                        if new_stage == "Completed":
                            completed_project_ids.add(pid)

            # Generate existing projects (with updated stages)
            eppm_rows = generate_eppm_data(
                active_eppm_people, portfolio_pool, rng,
                num_projects=len(all_project_ids),
                completed_project_ids=completed_project_ids,
                stage_overrides=stage_overrides,
                cancelled_project_ids=cancelled_project_ids,
                compliance_state=compliance_state,
                compliance_noise=compliance_noise,
            )

            # Add new projects (start mostly at G0/G1)
            if n_new_projects > 0:
                new_project_offset += 500
                new_rows = generate_eppm_data(
                    active_eppm_people, portfolio_pool, rng,
                    num_projects=n_new_projects,
                    new_project_start=new_project_offset,
                    compliance_state=compliance_state,
                    compliance_noise=compliance_noise,
                )
                eppm_rows.extend(new_rows)
                for row in new_rows:
                    npid = row["Project number"]
                    all_project_ids.append(npid)
                    stage_overrides[npid] = row["Active Stage"]

        # --- Post-process ePPM rows: shared emails, heavy PMs, project renames ---

        # Shared/generic emails: replace PM email on some projects
        if shared_email_count > 0 and eppm_rows:
            shared_targets = rng.sample(eppm_rows, min(shared_email_count, len(eppm_rows)))
            for row in shared_targets:
                row["Project Manager Email"] = rng.choice(SHARED_EMAILS)

        # Heavy PMs: force specific people onto many projects
        if heavy_pms:
            for hpm in heavy_pms:
                target_count = p["heavy_pm_project_count"]
                assigned = 0
                for row in eppm_rows:
                    if assigned >= target_count:
                        break
                    if row.get("Project Status") != "Completed" and assigned < target_count:
                        # Assign as IT PM (more realistic — one person managing many)
                        row["IT Project Manager"] = hpm["full_name"]
                        row["IT Project Manager Email"] = hpm["email_primary"]
                        assigned += 1

        # Project name changes: some projects get renamed between cycles
        if cycle_num > 1 and p["project_rename_rate"] > 0:
            n_rename = max(0, int(len(eppm_rows) * p["project_rename_rate"]))
            if n_rename > 0:
                rename_rows = rng.sample(eppm_rows, min(n_rename, len(eppm_rows)))
                suffixes = [" (Rebranded)", " v2", " - Phase 2", " (Updated)", " - New Scope"]
                for row in rename_rows:
                    old_name = row["Project Name"]
                    row["Project Name"] = old_name + rng.choice(suffixes)

        # --- Generate Fuse data using tracked state ---
        fuse_people_list = []
        seen_ids = set()
        for pid in overlap_ids:
            if pid in people_by_id and pid not in seen_ids:
                fuse_people_list.append(people_by_id[pid])
                seen_ids.add(pid)
        for pid in extra_fuse_ids:
            if pid in people_by_id and pid not in seen_ids:
                fuse_people_list.append(people_by_id[pid])
                seen_ids.add(pid)

        fuse_rows = generate_fuse_data(fuse_people_list, person_training_state, rng, cycle_num, params=p)

        cycles_data[cycle_num] = (eppm_rows, fuse_rows)

        # --- Check if all matchable PMs are fully certified ---
        # Build email->person_id lookup for active_eppm_people
        email_to_pid = {p["email_primary"]: p["person_id"] for p in active_eppm_people}

        # Find PMs on active projects who are also in the Fuse overlap (matchable)
        active_matchable_pm_ids = set()
        for row in eppm_rows:
            if row.get("Project Status") != "Completed":
                for role_field in ["Project Manager Email", "IT Project Manager Email"]:
                    email = row.get(role_field)
                    if email and email in email_to_pid:
                        pid = email_to_pid[email]
                        if pid in overlap_ids:  # Only count PMs who appear in Fuse
                            active_matchable_pm_ids.add(pid)

        uncertified = 0
        for pid in active_matchable_pm_ids:
            state = person_training_state.get(pid, {})
            if not (state.get("fund_completed") and state.get("adv_completed")):
                uncertified += 1

        fund_done = sum(1 for pid in all_fuse_person_ids
                       if person_training_state.get(pid, {}).get("fund_completed"))
        adv_done = sum(1 for pid in all_fuse_person_ids
                      if person_training_state.get(pid, {}).get("adv_completed"))
        total_fuse = len(all_fuse_person_ids)

        print(f"  Projects: {len(eppm_rows)} (ghost/cancelled: {len(cancelled_project_ids)}), Fuse records: {len(fuse_rows)}")
        print(f"  New PMs this cycle: {len(new_pms_this_cycle)}")
        print(f"  Training: Fund {fund_done}/{total_fuse} ({100*fund_done/total_fuse:.0f}%), "
              f"Adv {adv_done}/{total_fuse} ({100*adv_done/total_fuse:.0f}%)")
        print(f"  Matchable active PMs uncertified: {uncertified} (of {len(active_matchable_pm_ids)} matchable)")

        if uncertified == 0 and cycle_num >= 3:
            print(f"\n  All matchable active PMs are fully certified! Stopping at cycle {cycle_num}.")
            break

    return cycles_data, people, overlap_ids, alias_ids, new_pms_per_cycle, role_change_pool, cancelled_project_ids


def _cycle_label(cycle_num):
    """Return a descriptive label for each weekly cycle."""
    return f"week {cycle_num}"


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic test data for the Training Reminder System",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    d = DEFAULT_PARAMS  # shorthand for defaults

    # Core
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed for reproducibility")
    parser.add_argument("--max-cycles", type=int, default=30, help="Max weekly cycles to generate")

    # Population
    parser.add_argument("--num-people", type=int, default=d["num_people"], help="Total synthetic people")
    parser.add_argument("--num-projects", type=int, default=d["num_projects"], help="Initial number of projects")
    parser.add_argument("--portfolio-pool-size", type=int, default=d["portfolio_pool_size"], help="IT Portfolio Manager pool size")
    parser.add_argument("--initial-eppm-pool", type=int, default=d["initial_eppm_pool"], help="People in initial ePPM pool")
    parser.add_argument("--extra-fuse-people", type=int, default=d["extra_fuse_people"], help="Fuse-only background learners")

    # Matching
    parser.add_argument("--overlap-rate", type=float, default=d["overlap_rate"], help="Fraction of ePPM people also in Fuse")
    parser.add_argument("--alias-rate", type=float, default=d["alias_rate"], help="Fraction of people with email aliases")
    parser.add_argument("--role-change-rate", type=float, default=d["role_change_rate"], help="Fraction of overlap people who change roles")
    parser.add_argument("--maiden-name-count", type=int, default=d["maiden_name_count"], help="Number of maiden name alias cases")
    parser.add_argument("--email-alias-count", type=int, default=d["email_alias_count"], help="Number of email domain alias cases")

    # Evolution
    parser.add_argument("--gate-advance-prob", type=float, default=d["gate_advance_prob"], help="Per-project per-week gate advance probability")
    parser.add_argument("--cancel-rate-min", type=float, default=d["cancel_rate_min"], help="Min project cancellation rate per cycle")
    parser.add_argument("--cancel-rate-max", type=float, default=d["cancel_rate_max"], help="Max project cancellation rate per cycle")
    parser.add_argument("--training-speed", type=float, default=d["training_speed"], help="Training completion speed multiplier (>1 faster, <1 slower)")
    parser.add_argument("--skip-fundamentals-rate", type=float, default=d["skip_fundamentals_rate"], help="Rate of people who complete Advanced without Fundamentals")

    # Compliance noise
    parser.add_argument("--compliance-late-discovery", type=float, default=d["compliance_late_discovery_rate"], help="Rate of late-discovery compliance regressions")
    parser.add_argument("--compliance-data-correction", type=float, default=d["compliance_data_correction_rate"], help="Rate of data-correction downgrades")
    parser.add_argument("--compliance-stale-rollup", type=float, default=d["compliance_stale_rollup_rate"], help="Rate of stale overall compliance rollups")

    # People lifecycle
    parser.add_argument("--pm-leave-rate", type=float, default=d["pm_leave_rate"], help="Rate of PMs leaving per cycle")
    parser.add_argument("--pm-readd-rate", type=float, default=d["pm_readd_rate"], help="Rate of removed PMs being re-added")
    parser.add_argument("--pm-transfer-rate", type=float, default=d["pm_transfer_rate"], help="Rate of PM project transfers per cycle")

    # Data quality
    parser.add_argument("--name-collision-count", type=int, default=d["name_collision_count"], help="Number of duplicate-name pairs")
    parser.add_argument("--shared-email-rate", type=float, default=d["shared_email_rate"], help="Rate of projects using shared PM email")
    parser.add_argument("--project-rename-rate", type=float, default=d["project_rename_rate"], help="Rate of project name changes per cycle")

    # Training edge cases
    parser.add_argument("--training-fail-rate", type=float, default=d["training_fail_rate"], help="Rate of completed courses with failing score")
    parser.add_argument("--training-revoke-rate", type=float, default=d["training_revoke_rate"], help="Rate of training revocations per cycle")
    parser.add_argument("--training-in-progress-rate", type=float, default=d["training_in_progress_rate"], help="Rate of courses shown as in_progress")

    # Timing
    parser.add_argument("--stale-fuse-rate", type=float, default=d["stale_fuse_rate"], help="Rate of stale Fuse data (1 cycle behind)")
    parser.add_argument("--export-date-offset", type=int, default=d["export_date_offset_days"], help="Max days offset between ePPM and Fuse exports")

    # Scale
    parser.add_argument("--heavy-pm-count", type=int, default=d["heavy_pm_count"], help="Number of PMs assigned to many projects")
    parser.add_argument("--heavy-pm-projects", type=int, default=d["heavy_pm_project_count"], help="Projects per heavy PM")

    args = parser.parse_args()

    # Build params dict from CLI args
    params = {
        "num_people": args.num_people,
        "num_projects": args.num_projects,
        "portfolio_pool_size": args.portfolio_pool_size,
        "initial_eppm_pool": args.initial_eppm_pool,
        "extra_fuse_people": args.extra_fuse_people,
        "overlap_rate": args.overlap_rate,
        "alias_rate": args.alias_rate,
        "role_change_rate": args.role_change_rate,
        "maiden_name_count": args.maiden_name_count,
        "email_alias_count": args.email_alias_count,
        "gate_advance_prob": args.gate_advance_prob,
        "cancel_rate_min": args.cancel_rate_min,
        "cancel_rate_max": args.cancel_rate_max,
        "training_speed": args.training_speed,
        "skip_fundamentals_rate": args.skip_fundamentals_rate,
        "compliance_late_discovery_rate": args.compliance_late_discovery,
        "compliance_data_correction_rate": args.compliance_data_correction,
        "compliance_stale_rollup_rate": args.compliance_stale_rollup,
        # People lifecycle
        "pm_leave_rate": args.pm_leave_rate,
        "pm_readd_rate": args.pm_readd_rate,
        "pm_transfer_rate": args.pm_transfer_rate,
        # Data quality
        "name_collision_count": args.name_collision_count,
        "shared_email_rate": args.shared_email_rate,
        "project_rename_rate": args.project_rename_rate,
        # Training edge cases
        "training_fail_rate": args.training_fail_rate,
        "training_revoke_rate": args.training_revoke_rate,
        "training_in_progress_rate": args.training_in_progress_rate,
        # Timing
        "stale_fuse_rate": args.stale_fuse_rate,
        "export_date_offset_days": args.export_date_offset,
        # Scale
        "heavy_pm_count": args.heavy_pm_count,
        "heavy_pm_project_count": args.heavy_pm_projects,
    }

    rng = random.Random(args.seed)

    cycles_data, people, overlap_ids, alias_ids, new_pms_per_cycle, role_change_pool, cancelled_project_ids = generate_all_cycles(
        rng, max_cycles=args.max_cycles, params=params
    )

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Clean old simulation data
    sim_base = os.path.join(base_dir, "data", "simulation")
    if os.path.exists(sim_base):
        shutil.rmtree(sim_base)

    total_cycles = len(cycles_data)

    # Generate role_changes.xlsx per cycle
    # Simulates feedback arriving over time: the list grows as more people report changes
    # Cycle 1: no CSV (nobody reported yet)
    # Cycle 2+: gradually add people from role_change_pool
    role_change_csvs = {}
    accumulated_changes = []
    for cycle_num in sorted(cycles_data.keys()):
        if cycle_num == 1 or not role_change_pool:
            role_change_csvs[cycle_num] = None
            continue

        # Every 2-3 weeks, 1-2 new role changes get reported
        if cycle_num % 2 == 0 and accumulated_changes != role_change_pool:
            remaining = [p for p in role_change_pool if p not in accumulated_changes]
            if remaining:
                new_reports = remaining[:rng.randint(1, min(2, len(remaining)))]
                accumulated_changes.extend(new_reports)

        if accumulated_changes:
            base_date = datetime(2026, 3, 1)
            rows = []
            for p in accumulated_changes:
                rows.append({
                    "it_pm_email": p["email_primary"],
                    "it_pm_name": p["full_name"],
                    "new_role": rng.choice(CHANGED_ROLE_NAMES),
                    "reported_date": (base_date + timedelta(days=rng.randint(0, cycle_num * 7))).strftime("%Y-%m-%d"),
                    "notes": "Confirmed via team feedback",
                })
            role_change_csvs[cycle_num] = rows
        else:
            role_change_csvs[cycle_num] = None

    # Build excluded_projects data per cycle (ghost projects accumulate over time)
    # Simulates: someone discovers a project is dead and adds it to the exclusion list
    excluded_projects_per_cycle = {}
    accumulated_excluded = []
    cancelled_list = sorted(cancelled_project_ids)
    for cycle_num in sorted(cycles_data.keys()):
        if cycle_num <= 2 or not cancelled_list:
            excluded_projects_per_cycle[cycle_num] = None
            continue
        # Every few weeks, 1-3 ghost projects get reported and added to exclusion list
        if cycle_num % 3 == 0:
            remaining = [pid for pid in cancelled_list if pid not in [e["project_id"] for e in accumulated_excluded]]
            if remaining:
                new_excluded = remaining[:rng.randint(1, min(3, len(remaining)))]
                base_date = datetime(2026, 3, 1)
                for pid in new_excluded:
                    accumulated_excluded.append({
                        "project_id": pid,
                        "reason": rng.choice(["Cancelled", "Cancelled - budget cut", "Cancelled - merged with another project", "On Hold indefinitely"]),
                        "reported_date": (base_date + timedelta(days=rng.randint(0, cycle_num * 7))).strftime("%Y-%m-%d"),
                    })
        if accumulated_excluded:
            excluded_projects_per_cycle[cycle_num] = list(accumulated_excluded)
        else:
            excluded_projects_per_cycle[cycle_num] = None

    # Build identity aliases data
    # These resolve matching issues: maiden names, email domain changes
    MAIDEN_NAMES = ["Kowalska", "Nowak", "Wisniewska", "Kaminska", "Lewandowska",
                    "Zielinska", "Szymanska", "Wojcik", "Piotrowska", "Mazur"]
    identity_alias_rows = []

    # 1. Email alias cases (existing alias people — different domain in Fuse vs ePPM)
    alias_people_in_overlap = [p for p in people if p["email_aliases"] and p["person_id"] in overlap_ids]
    email_alias_limit = params.get("email_alias_count", 5)
    for p in alias_people_in_overlap[:email_alias_limit]:
        identity_alias_rows.append({
            "canonical_email": p["email_primary"],
            "canonical_name": p["full_name"],
            "alias_email": p["email_aliases"][0],
            "alias_name": "",
            "reason": "Domain change / cross-system email",
        })

    # 2. Maiden name cases — pick some women from overlap, give them a different last name in Fuse
    women_in_overlap = [p for p in people if p["person_id"] in overlap_ids and p["gender"] == "Female"]
    maiden_count = params.get("maiden_name_count", 4)
    maiden_candidates = rng.sample(women_in_overlap, min(maiden_count, len(women_in_overlap)))
    for i, p in enumerate(maiden_candidates):
        maiden_last = MAIDEN_NAMES[i % len(MAIDEN_NAMES)]
        maiden_full = f"{p['first_name']} {maiden_last}"
        maiden_local = f"{p['first_name'].lower()}.{maiden_last.lower()}"
        maiden_email = f"{maiden_local}@{DOMAINS['primary']}"

        # Change the person's name/email in Fuse data for all cycles
        # (simulate: ePPM has married name, Fuse has maiden name)
        for cycle_num in cycles_data:
            eppm_rows, fuse_rows = cycles_data[cycle_num]
            for row in fuse_rows:
                if row.get("Email") == p["email_primary"] or row.get("Email") in p.get("email_aliases", []):
                    row["Full Name"] = maiden_full
                    row["Email"] = maiden_email

        identity_alias_rows.append({
            "canonical_email": p["email_primary"],
            "canonical_name": p["full_name"],
            "alias_email": maiden_email,
            "alias_name": maiden_full,
            "reason": f"Maiden name (panieńskie) — married name in ePPM",
        })

    # Identity aliases available from cycle 2+ (simulates: admin noticed mismatches and built the list)
    identity_aliases_per_cycle = {}
    for cycle_num in sorted(cycles_data.keys()):
        if cycle_num >= 2:
            identity_aliases_per_cycle[cycle_num] = identity_alias_rows
        else:
            identity_aliases_per_cycle[cycle_num] = None

    for cycle_num, (eppm_rows, fuse_rows) in sorted(cycles_data.items()):
        cycle_dir = os.path.join(base_dir, "data", "simulation", f"cycle_{cycle_num}")
        os.makedirs(cycle_dir, exist_ok=True)

        eppm_path = os.path.join(cycle_dir, "ePPM_export.xlsx")
        fuse_path = os.path.join(cycle_dir, "Fuse_export.xlsx")

        write_excel(eppm_rows, eppm_path, sheet_name="ePPM")
        write_excel(fuse_rows, fuse_path, sheet_name="Fuse")

        # Write role_changes.xlsx if available for this cycle
        csv_data = role_change_csvs.get(cycle_num)
        if csv_data:
            rc_path = os.path.join(cycle_dir, "role_changes.xlsx")
            write_excel(csv_data, rc_path, sheet_name="Role Changes")

        # Write identity_aliases.xlsx if available for this cycle
        alias_data = identity_aliases_per_cycle.get(cycle_num)
        if alias_data:
            alias_path = os.path.join(cycle_dir, "identity_aliases.xlsx")
            write_excel(alias_data, alias_path, sheet_name="Identity Aliases")

        # Write excluded_projects.xlsx if available for this cycle
        excl_data = excluded_projects_per_cycle.get(cycle_num)
        if excl_data:
            excl_path = os.path.join(cycle_dir, "excluded_projects.xlsx")
            write_excel(excl_data, excl_path, sheet_name="Excluded Projects")

    # Copy cycle 1 to data/input for easy first run
    input_dir = os.path.join(base_dir, "data", "input")
    os.makedirs(input_dir, exist_ok=True)
    # Clear existing input files
    for f in os.listdir(input_dir):
        if f.endswith(".xlsx"):
            os.remove(os.path.join(input_dir, f))
    shutil.copy2(
        os.path.join(base_dir, "data", "simulation", "cycle_1", "ePPM_export.xlsx"),
        os.path.join(input_dir, "ePPM_export.xlsx"),
    )
    shutil.copy2(
        os.path.join(base_dir, "data", "simulation", "cycle_1", "Fuse_export.xlsx"),
        os.path.join(input_dir, "Fuse_export.xlsx"),
    )
    print(f"\nCycle 1 files copied to {input_dir}")

    # Print diagnostics
    total_cycles = len(cycles_data)
    print(f"\n{'='*60}")
    print(f"GENERATION COMPLETE: {total_cycles} cycles generated")
    print(f"{'='*60}")
    print(f"People master: {len(people)}")
    print(f"Overlap people (in both ePPM and Fuse): {len(overlap_ids)}")
    print(f"Alias cases: {len(alias_ids)}")
    print(f"Role-change pool: {len(role_change_pool)}")
    print(f"Ghost/cancelled projects: {len(cancelled_project_ids)}")
    csv_cycles = [c for c, d in role_change_csvs.items() if d]
    print(f"Cycles with role_changes.xlsx: {len(csv_cycles)} (cycles {csv_cycles[:5]}{'...' if len(csv_cycles) > 5 else ''})")
    print(f"Identity aliases: {len(identity_alias_rows)} ({len(maiden_candidates)} maiden names, {min(email_alias_limit, len(alias_people_in_overlap))} email aliases)")
    contractors = sum(1 for p in people if p["employment_type"] == "Contractor")
    print(f"Contractors: {contractors}")
    print(f"Standard: {sum(1 for p in people if p['employment_type'] == 'Standard')}")
    print(f"Foreign Assignees: {sum(1 for p in people if p['employment_type'] == 'Foreign Assignee')}")

    print(f"\nNew PMs introduced per cycle:")
    for c in sorted(new_pms_per_cycle.keys()):
        n = new_pms_per_cycle[c]
        if n > 0:
            print(f"  Cycle {c}: +{n} new PMs")


if __name__ == "__main__":
    main()
