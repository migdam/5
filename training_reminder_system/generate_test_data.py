#!/usr/bin/env python3
"""Generate synthetic test data for the Training Reminder System.

Creates 3 cycles of ePPM and Fuse Excel files with controlled evolution:
- Cycle 1: Baseline (~250 projects, ~40% fundamentals completion)
- Cycle 2: Growth (~280 projects, ~55% fundamentals completion, some projects completed)
- Cycle 3: Maturity (~300 projects, ~70% fundamentals completion, more completions)

Data is output to data/simulation/cycle_1/, cycle_2/, cycle_3/
and cycle_1 is also copied to data/input/ for easy first run.
"""
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

LEADING_FUNCTIONS = [
    "Operations", "Finance", "IT", "Marketing", "Supply Chain",
    "R&D", "Quality", "Commercial", "HR", "Legal",
]

PROJECT_ARCHETYPES = [
    "Simpler projects", "Complex projects", "Innovation projects",
    "Regulatory projects", "Infrastructure projects",
]

STAGE_WEIGHTS = {"G0": 0.10, "G3": 0.35, "G5": 0.35, "Completed": 0.20}
ARCHETYPE_WEIGHTS = [0.30, 0.35, 0.10, 0.15, 0.10]

COMPLIANCE_VALUES = ["Full compliance", "Partially compliant", "Non-compliant"]
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
                       stage_overrides=None):
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

        # Compliance fields (sparse)
        g0_comp, g0_act = (None, None)
        g3_comp, g3_act = (None, None)
        g5_comp, g5_act = (None, None)
        g6_comp, g6_act = (None, None)

        if stage in ("G0", "G3", "G5", "Completed"):
            if rng.random() > 0.57:
                g0_comp = rng.choice(COMPLIANCE_VALUES)
                g0_act = COMPLIANCE_ACTIONS[g0_comp]
        if stage in ("G3", "G5", "Completed"):
            if rng.random() > 0.73:
                g3_comp = rng.choice(COMPLIANCE_VALUES)
                g3_act = COMPLIANCE_ACTIONS[g3_comp]
        if stage in ("G5", "Completed"):
            if rng.random() > 0.96:
                g5_comp = rng.choice(COMPLIANCE_VALUES)
                g5_act = COMPLIANCE_ACTIONS[g5_comp]
        if stage == "Completed":
            if rng.random() > 0.98:
                g6_comp = rng.choice(COMPLIANCE_VALUES)
                g6_act = COMPLIANCE_ACTIONS[g6_comp]

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

def generate_fuse_data(people, overlap_ids, rng, cycle_num=1,
                       fundamentals_rate=0.40, advanced_rate=0.20,
                       extra_fuse_people=None):
    """Generate Fuse training data.

    Args:
        people: People master list.
        overlap_ids: Set of person_ids that must appear in Fuse.
        rng: Random number generator.
        cycle_num: Cycle number (affects dates).
        fundamentals_rate: Rate of fundamentals completion.
        advanced_rate: Rate of advanced completion.
        extra_fuse_people: Additional people (non-overlap) to include.
    """
    # Build fuse person pool
    overlap_people = [p for p in people if p["person_id"] in overlap_ids]
    if extra_fuse_people is None:
        non_overlap = [p for p in people if p["person_id"] not in overlap_ids]
        extra_fuse_people = rng.sample(non_overlap, min(90, len(non_overlap)))

    fuse_people = overlap_people + extra_fuse_people

    rows = []
    imdl_counter = 100001 + (cycle_num - 1) * 10000

    base_date = datetime(2025, 10, 1)
    cycle_offset = timedelta(days=(cycle_num - 1) * 14)

    for person in fuse_people:
        # Determine which courses this person has records for
        courses = []

        # Fundamentals
        fund_completed = rng.random() < fundamentals_rate
        courses.append((FUNDAMENTALS_ID, fund_completed))

        # Advanced (higher chance if fundamentals completed)
        if fund_completed:
            adv_completed = rng.random() < (advanced_rate * 1.5)
        else:
            adv_completed = rng.random() < (advanced_rate * 0.3)
        courses.append((ADVANCED_ID, adv_completed))

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

def generate_all_cycles(rng):
    """Generate 3 cycles of test data with controlled evolution."""
    people = build_people_master(rng, num_people=200)
    alias_ids = assign_aliases(people, rng)
    portfolio_pool = build_portfolio_pool(people, rng, pool_size=25)

    # Select overlap people (35% of ePPM people will also be in Fuse)
    non_contractor = [p for p in people if p["employment_type"] != "Contractor"]
    overlap_count = int(len(non_contractor) * 0.35)
    overlap_people = rng.sample(non_contractor, overlap_count)
    overlap_ids = {p["person_id"] for p in overlap_people}

    # Extra Fuse-only people (stable across cycles)
    fuse_only = [p for p in people if p["person_id"] not in overlap_ids]
    extra_fuse = rng.sample(fuse_only, min(90, len(fuse_only)))

    # --- Cycle 1: Baseline ---
    print("Generating Cycle 1 (baseline)...")
    eppm1 = generate_eppm_data(people, portfolio_pool, rng, num_projects=250)
    fuse1 = generate_fuse_data(
        people, overlap_ids, rng, cycle_num=1,
        fundamentals_rate=0.40, advanced_rate=0.20,
        extra_fuse_people=extra_fuse,
    )

    # --- Cycle 2: Growth ---
    print("Generating Cycle 2 (growth)...")
    # Some projects complete, some change stage
    cycle1_ids = [r["Project number"] for r in eppm1]
    completed_ids_2 = set(rng.sample(cycle1_ids, 15))
    stage_changes_2 = {}
    remaining = [pid for pid in cycle1_ids if pid not in completed_ids_2]
    for pid in rng.sample(remaining, min(20, len(remaining))):
        stage_changes_2[pid] = rng.choice(["G3", "G5"])

    # Keep existing projects + add new ones
    eppm2_existing = generate_eppm_data(
        people, portfolio_pool, rng, num_projects=250,
        completed_project_ids=completed_ids_2,
        stage_overrides=stage_changes_2,
    )
    eppm2_new = generate_eppm_data(
        people, portfolio_pool, rng, num_projects=30,
        new_project_start=500,
    )
    eppm2 = eppm2_existing + eppm2_new

    fuse2 = generate_fuse_data(
        people, overlap_ids, rng, cycle_num=2,
        fundamentals_rate=0.55, advanced_rate=0.30,
        extra_fuse_people=extra_fuse,
    )

    # --- Cycle 3: Maturity ---
    print("Generating Cycle 3 (maturity)...")
    completed_ids_3 = completed_ids_2.copy()
    new_completions = rng.sample(
        [pid for pid in cycle1_ids if pid not in completed_ids_3],
        10
    )
    completed_ids_3.update(new_completions)

    stage_changes_3 = dict(stage_changes_2)
    remaining3 = [pid for pid in cycle1_ids if pid not in completed_ids_3]
    for pid in rng.sample(remaining3, min(15, len(remaining3))):
        stage_changes_3[pid] = rng.choice(["G5", "Completed"])

    eppm3_existing = generate_eppm_data(
        people, portfolio_pool, rng, num_projects=250,
        completed_project_ids=completed_ids_3,
        stage_overrides=stage_changes_3,
    )
    eppm3_new = generate_eppm_data(
        people, portfolio_pool, rng, num_projects=50,
        new_project_start=700,
    )
    eppm3 = eppm3_existing + eppm3_new

    fuse3 = generate_fuse_data(
        people, overlap_ids, rng, cycle_num=3,
        fundamentals_rate=0.70, advanced_rate=0.45,
        extra_fuse_people=extra_fuse,
    )

    return {
        1: (eppm1, fuse1),
        2: (eppm2, fuse2),
        3: (eppm3, fuse3),
    }, people, overlap_ids, alias_ids


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic test data")
    parser.add_argument("--seed", type=int, default=SEED, help="Random seed")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    cycles_data, people, overlap_ids, alias_ids = generate_all_cycles(rng)

    base_dir = os.path.dirname(os.path.abspath(__file__))

    for cycle_num, (eppm_rows, fuse_rows) in cycles_data.items():
        cycle_dir = os.path.join(base_dir, "data", "simulation", f"cycle_{cycle_num}")
        os.makedirs(cycle_dir, exist_ok=True)

        eppm_path = os.path.join(cycle_dir, "ePPM_export.xlsx")
        fuse_path = os.path.join(cycle_dir, "Fuse_export.xlsx")

        write_excel(eppm_rows, eppm_path, sheet_name="ePPM")
        write_excel(fuse_rows, fuse_path, sheet_name="Fuse")

        print(f"  Cycle {cycle_num}: {len(eppm_rows)} ePPM rows, {len(fuse_rows)} Fuse rows")
        print(f"    -> {eppm_path}")
        print(f"    -> {fuse_path}")

    # Copy cycle 1 to data/input for easy first run
    input_dir = os.path.join(base_dir, "data", "input")
    os.makedirs(input_dir, exist_ok=True)
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
    print("\n--- Diagnostics ---")
    print(f"People master: {len(people)}")
    print(f"Overlap people (in both ePPM and Fuse): {len(overlap_ids)}")
    print(f"Alias cases: {len(alias_ids)}")
    contractors = sum(1 for p in people if p["employment_type"] == "Contractor")
    print(f"Contractors: {contractors}")
    print(f"Standard: {sum(1 for p in people if p['employment_type'] == 'Standard')}")
    print(f"Foreign Assignees: {sum(1 for p in people if p['employment_type'] == 'Foreign Assignee')}")


if __name__ == "__main__":
    main()
