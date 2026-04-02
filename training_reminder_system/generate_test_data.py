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

def build_people_master(rng, num_people=200):
    """Build a master list of synthetic people."""
    used_emails = set()
    people = []

    # Shuffle name combos
    name_combos = []
    for fn in FIRST_NAMES:
        for ln in LAST_NAMES:
            name_combos.append((fn, ln))
    rng.shuffle(name_combos)

    for i in range(num_people):
        fn, ln = name_combos[i]
        full_name = f"{fn} {ln}"

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

        local_part = f"{fn.lower()}.{ln.lower()}"
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
                       stage_overrides=None, cancelled_project_ids=None):
    """Generate ePPM project assignment data.

    Args:
        people: People master list.
        portfolio_pool: IT Portfolio Manager pool.
        rng: Random number generator.
        num_projects: Number of projects to generate.
        completed_project_ids: Set of project IDs that should be marked Completed.
        new_project_start: Index offset for new projects (to generate unique IDs).
        stage_overrides: Dict of project_id -> new_stage for evolution.
    """
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
        g0_comp, g0_act = (None, None)
        g3_comp, g3_act = (None, None)
        g5_comp, g5_act = (None, None)
        g6_comp, g6_act = (None, None)

        stage_idx = GATE_SEQUENCE.index(stage) if stage in GATE_SEQUENCE else 0
        # G0 compliance if past G0
        if stage_idx >= 1 and rng.random() > 0.57:
            g0_comp = rng.choice(COMPLIANCE_VALUES)
            g0_act = G0_ACTIONS[g0_comp]
        # G3 compliance if past G3
        if stage_idx >= 4 and rng.random() > 0.73:
            g3_comp = rng.choice(COMPLIANCE_VALUES)
            act = G3_ACTIONS[g3_comp]
            g3_act = rng.choice(act) if isinstance(act, list) else act
        # G5 compliance if past G5
        if stage_idx >= 6 and rng.random() > 0.96:
            g5_comp = rng.choice(COMPLIANCE_VALUES)
            g5_act = G5_ACTIONS[g5_comp]
        # G6 compliance if past G6
        if stage_idx >= 7 and rng.random() > 0.98:
            g6_comp = rng.choice(COMPLIANCE_VALUES)
            g6_act = G6_ACTIONS[g6_comp]

        proj_compliance = None
        if rng.random() > 0.476:
            proj_compliance = rng.choices(
                COMPLIANCE_VALUES, weights=[0.5, 0.35, 0.15]
            )[0]

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

def generate_fuse_data(fuse_people, person_training_state, rng, cycle_num=1):
    """Generate Fuse training data using tracked per-person training state.

    Args:
        fuse_people: List of person dicts to include in Fuse.
        person_training_state: Dict of person_id -> {fund_completed, adv_completed}.
        rng: Random number generator.
        cycle_num: Cycle number (affects dates).
    """
    rows = []
    imdl_counter = 100001 + (cycle_num - 1) * 10000

    base_date = datetime(2025, 10, 1)
    cycle_offset = timedelta(days=(cycle_num - 1) * 14)

    for person in fuse_people:
        pid = person["person_id"]
        state = person_training_state.get(pid, {})
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

        # Generate hire date text
        hire_date = person["hire_date"]
        hire_text = hire_date.strftime("%A, %B ") + str(hire_date.day) + hire_date.strftime(", %Y")

        user_id = person["email_primary"].split("@")[0].replace(".", "")

        for course_id, is_completed in courses:
            start_date = base_date + cycle_offset + timedelta(days=rng.randint(0, 60))
            completion_date = None
            score = None
            status = "completed" if is_completed else "incomplete"

            if is_completed:
                completion_date = start_date + timedelta(days=rng.randint(0, 14))
                score = round(rng.gauss(85, 8), 1)
                score = max(60.0, min(100.0, score))

            content_group = None
            if rng.random() < 0.10:
                content_group = "Project Management"

            rows.append({
                "IMDL ID": imdl_counter,
                "PerNR": person["pernr"],
                "User ID": user_id,
                "Full Name": person["full_name"],
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

def generate_all_cycles(rng, max_cycles=30):
    """Generate cycles until ALL PMs are fully certified.

    Each cycle:
    - Existing PMs gradually complete training (fundamentals first, then advanced)
    - New projects appear with new PMs who also need certification
    - Some existing projects complete
    - Training completion rates increase until 100%

    New PM waves:
    - Cycles 2-4: 8-15 new PMs per cycle (from fresh people pool)
    - Cycles 5-7: 5-8 new PMs per cycle
    - Cycles 8+: 2-4 new PMs per cycle (tapering off)
    - All new PMs must also get certified before simulation ends
    """
    # Build large people master (enough for initial + new PMs across cycles)
    people = build_people_master(rng, num_people=350)
    alias_ids = assign_aliases(people, rng)
    portfolio_pool = build_portfolio_pool(people, rng, pool_size=25)

    non_contractor = [p for p in people if p["employment_type"] != "Contractor"]
    people_by_id = {p["person_id"]: p for p in people}

    # Initial ePPM people pool (first 160 non-contractors)
    initial_eppm_pool = non_contractor[:160]
    # Reserve remaining for new PMs in later cycles
    new_pm_reserve = non_contractor[160:]
    rng.shuffle(new_pm_reserve)

    # Select overlap people (35% of initial pool will also be in Fuse)
    overlap_count = int(len(initial_eppm_pool) * 0.35)
    overlap_people = rng.sample(initial_eppm_pool, overlap_count)
    overlap_ids = {p["person_id"] for p in overlap_people}

    # Select people who will be reported as having changed roles via CSV
    # These people stay in the people master with PM positions (Fuse won't detect them)
    # but they appear in the manually maintained role_changes.xlsx
    role_change_pool_count = max(4, int(len(overlap_people) * 0.10))
    role_change_pool = rng.sample(overlap_people, role_change_pool_count)
    role_change_pool_ids = {p["person_id"] for p in role_change_pool}

    # Extra Fuse-only people (stable background learners)
    fuse_only_candidates = [p for p in people if p["person_id"] not in overlap_ids
                            and p not in initial_eppm_pool]
    extra_fuse = rng.sample(fuse_only_candidates, min(60, len(fuse_only_candidates)))
    extra_fuse_ids = {p["person_id"] for p in extra_fuse}

    # Track per-person training state: person_id -> {fund_completed, adv_completed}
    person_training_state = {}

    # Track all project IDs and their completion state
    all_project_ids = []
    completed_project_ids = set()
    cancelled_project_ids = set()  # Ghost projects — cancelled but not updated in ePPM
    stage_overrides = {}

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
    GATE_ADVANCE_PROB = 1.0 / 13.0  # ~7.7% chance per project per week

    new_project_offset = 0

    for cycle_num in range(1, max_cycles + 1):
        week = cycle_num

        # Training completion probability increases over weeks
        # Weeks 1-4: people are just getting started, low completion
        # Weeks 5-8: moderate uptake
        # Weeks 9-12: strong uptake
        # Weeks 13-16: most people done
        # Weeks 17+: stragglers complete, force to 100%
        if week <= 4:
            fund_chance = 0.05 + week * 0.02     # 7-13%
            adv_chance = 0.02 + week * 0.01      # 3-6%
        elif week <= 8:
            fund_chance = 0.12 + (week - 4) * 0.03  # 15-24%
            adv_chance = 0.08 + (week - 4) * 0.03   # 11-20%
        elif week <= 12:
            fund_chance = 0.25 + (week - 8) * 0.05  # 30-45%
            adv_chance = 0.20 + (week - 8) * 0.05   # 25-40%
        elif week <= 16:
            fund_chance = 0.50 + (week - 12) * 0.10  # 60-90%
            adv_chance = 0.45 + (week - 12) * 0.10   # 55-85%
        elif week <= 20:
            fund_chance = 0.90 + (week - 16) * 0.025
            adv_chance = 0.85 + (week - 16) * 0.03
        else:
            fund_chance = 1.0
            adv_chance = 1.0

        fund_chance = min(fund_chance, 1.0)
        adv_chance = min(adv_chance, 1.0)

        # New projects arrive every ~3-4 weeks, new PMs with them
        n_new_projects = 0
        n_new_pms = 0
        if week in (3, 4):
            n_new_projects, n_new_pms = 8, 4
        elif week in (7, 8):
            n_new_projects, n_new_pms = 6, 3
        elif week in (11, 12):
            n_new_projects, n_new_pms = 5, 3
        elif week in (15, 16):
            n_new_projects, n_new_pms = 4, 2
        elif week == 19:
            n_new_projects, n_new_pms = 3, 2

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
            for p in new_pms_this_cycle:
                overlap_ids.add(p["person_id"])
                all_eppm_person_ids.add(p["person_id"])
        new_pms_per_cycle[cycle_num] = len(new_pms_this_cycle)

        # --- Update training state ---
        # All people in overlap_ids + extra_fuse need training state
        all_fuse_person_ids = overlap_ids | extra_fuse_ids

        for pid in all_fuse_person_ids:
            if pid not in person_training_state:
                person_training_state[pid] = {"fund_completed": False, "adv_completed": False}

            state = person_training_state[pid]
            # Progress training: usually fundamentals first, then advanced
            # But ~8% of people complete Advanced directly (skipping Fundamentals)
            if not state["fund_completed"]:
                if rng.random() < fund_chance:
                    state["fund_completed"] = True
            if not state["adv_completed"]:
                if state["fund_completed"]:
                    # Normal path: fundamentals done, now try advanced
                    if rng.random() < adv_chance:
                        state["adv_completed"] = True
                elif rng.random() < adv_chance * 0.08:
                    # Skip path: complete advanced without fundamentals (~8% of cases)
                    state["adv_completed"] = True

        # --- Evolve ePPM project state ---
        if cycle_num == 1:
            # Generate base projects
            eppm_rows = generate_eppm_data(
                active_eppm_people, portfolio_pool, rng,
                num_projects=250,
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
            n_cancel = max(0, int(len(still_active) * rng.uniform(0.005, 0.015)))
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
            )

            # Add new projects (start mostly at G0/G1)
            if n_new_projects > 0:
                new_project_offset += 500
                new_rows = generate_eppm_data(
                    active_eppm_people, portfolio_pool, rng,
                    num_projects=n_new_projects,
                    new_project_start=new_project_offset,
                )
                eppm_rows.extend(new_rows)
                for row in new_rows:
                    npid = row["Project number"]
                    all_project_ids.append(npid)
                    stage_overrides[npid] = row["Active Stage"]

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

        fuse_rows = generate_fuse_data(fuse_people_list, person_training_state, rng, cycle_num)

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
    parser = argparse.ArgumentParser(description="Generate synthetic test data")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    parser.add_argument("--max-cycles", type=int, default=30, help="Max weekly cycles to generate")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    cycles_data, people, overlap_ids, alias_ids, new_pms_per_cycle, role_change_pool, cancelled_project_ids = generate_all_cycles(
        rng, max_cycles=args.max_cycles
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
    for p in alias_people_in_overlap[:5]:
        identity_alias_rows.append({
            "canonical_email": p["email_primary"],
            "canonical_name": p["full_name"],
            "alias_email": p["email_aliases"][0],
            "alias_name": "",
            "reason": "Domain change / cross-system email",
        })

    # 2. Maiden name cases — pick some women from overlap, give them a different last name in Fuse
    women_in_overlap = [p for p in people if p["person_id"] in overlap_ids and p["gender"] == "Female"]
    maiden_candidates = rng.sample(women_in_overlap, min(4, len(women_in_overlap)))
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
    print(f"Identity aliases: {len(identity_alias_rows)} ({len(maiden_candidates)} maiden names, {len(alias_people_in_overlap[:5])} email aliases)")
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
