#!/usr/bin/env python3
"""Run a multi-cycle simulation to demonstrate the Training Reminder System.

This script:
1. Resets the database for a fresh start
2. Discovers all available cycles in data/simulation/
3. For each cycle:
   - Copies simulation files to data/input/
   - Runs main.py pipeline
   - Prints summary
4. Runs until all PMs are certified (0 reminders generated)
5. Prints cross-cycle comparison showing reminder progression
"""
import os
import sys
import shutil
import sqlite3

# Ensure project root is on path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from src.config_loader import load_config
from main import run_cycle


def reset_database(config):
    """Remove existing database for a fresh simulation."""
    db_path = config["paths"]["database"]
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"  Removed existing database: {db_path}")


def clear_input_folder(config):
    """Remove files from input folder."""
    input_dir = config["paths"]["input_folder"]
    if os.path.exists(input_dir):
        for f in os.listdir(input_dir):
            fpath = os.path.join(input_dir, f)
            if os.path.isfile(fpath):
                os.remove(fpath)


def copy_cycle_files(cycle_num, config):
    """Copy simulation files for a given cycle to the input folder."""
    sim_dir = os.path.join("data", "simulation", f"cycle_{cycle_num}")
    input_dir = config["paths"]["input_folder"]
    os.makedirs(input_dir, exist_ok=True)

    for f in os.listdir(sim_dir):
        if f.endswith(".xlsx"):
            src = os.path.join(sim_dir, f)
            dst = os.path.join(input_dir, f)
            shutil.copy2(src, dst)

    print(f"  Copied cycle {cycle_num} files to {input_dir}")


def print_cross_cycle_summary(config):
    """Print a cross-cycle summary from the database."""
    db_path = config["paths"]["database"]
    if not os.path.exists(db_path):
        print("No database found for summary.")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    print("\n" + "=" * 70)
    print("CROSS-CYCLE SUMMARY")
    print("=" * 70)

    # Cycle overview
    cycles = conn.execute("SELECT * FROM cycles ORDER BY id").fetchall()
    print(f"\nTotal cycles: {len(cycles)}")
    for c in cycles:
        print(f"  Cycle {c['id']}: {c['run_status']} - {c['notes']}")

    # Communication history progression
    print("\n--- Reminder Progression ---")
    comms = conn.execute("""
        SELECT ch.cycle_id, ch.reminder_stage, pm.full_name, pm.email,
               ch.communication_status
        FROM communication_history ch
        JOIN project_managers pm ON ch.project_manager_id = pm.id
        ORDER BY pm.full_name, ch.cycle_id
    """).fetchall()

    if comms:
        # Group by person
        person_history = {}
        for c in comms:
            key = c["full_name"]
            if key not in person_history:
                person_history[key] = []
            person_history[key].append({
                "cycle": c["cycle_id"],
                "stage": c["reminder_stage"],
                "email": c["email"],
            })

        # Show people with multiple reminders (stage progression)
        print(f"\nPeople with reminders across cycles:")
        print(f"{'Name':<30} {'Email':<35} {'Cycle Stages'}")
        print("-" * 90)

        for name in sorted(person_history.keys()):
            history = person_history[name]
            email = history[0]["email"] or "N/A"
            stages_str = " -> ".join(
                f"C{h['cycle']}:S{h['stage']}" for h in history
            )
            print(f"{name:<30} {email:<35} {stages_str}")

        # Stage distribution per cycle
        print("\n--- Stage Distribution Per Cycle ---")
        for cycle in cycles:
            cid = cycle["id"]
            stage_counts = conn.execute("""
                SELECT reminder_stage, COUNT(*) as cnt
                FROM communication_history
                WHERE cycle_id = ?
                GROUP BY reminder_stage
                ORDER BY reminder_stage
            """, (cid,)).fetchall()
            if stage_counts:
                stages_str = ", ".join(f"Stage {s['reminder_stage']}: {s['cnt']}" for s in stage_counts)
                total = sum(s["cnt"] for s in stage_counts)
                print(f"  Cycle {cid}: {total} reminders ({stages_str})")
            else:
                print(f"  Cycle {cid}: 0 reminders")

    # People who completed training and stopped getting reminders
    print("\n--- People Who Completed Training (no longer reminded) ---")
    # Find people who got reminders in earlier cycles but not in later ones
    all_pm_ids = conn.execute("""
        SELECT DISTINCT project_manager_id FROM communication_history
    """).fetchall()

    max_cycle = max(c["id"] for c in cycles)
    stopped = []
    for pm_row in all_pm_ids:
        pm_id = pm_row["project_manager_id"]
        last_cycle = conn.execute("""
            SELECT MAX(cycle_id) as last_cycle FROM communication_history
            WHERE project_manager_id = ?
        """, (pm_id,)).fetchone()
        if last_cycle and last_cycle["last_cycle"] < max_cycle:
            pm = conn.execute(
                "SELECT full_name, email FROM project_managers WHERE id = ?",
                (pm_id,)
            ).fetchone()
            if pm:
                stopped.append((pm["full_name"], pm["email"], last_cycle["last_cycle"]))

    if stopped:
        for name, email, last_c in sorted(stopped):
            print(f"  {name} ({email}) - last reminded in cycle {last_c}")
    else:
        print("  (None detected - all reminded PMs received reminders in every cycle)")

    # Data quality issues
    dq_count = conn.execute("SELECT COUNT(*) as cnt FROM data_quality_issues").fetchone()
    print(f"\nTotal data quality issues logged: {dq_count['cnt']}")

    conn.close()


def discover_cycles():
    """Find all available cycle directories in data/simulation/."""
    sim_dir = os.path.join("data", "simulation")
    if not os.path.exists(sim_dir):
        return []
    cycles = []
    for name in sorted(os.listdir(sim_dir)):
        if name.startswith("cycle_"):
            try:
                num = int(name.split("_")[1])
                cycle_path = os.path.join(sim_dir, name)
                has_eppm = any(f.endswith(".xlsx") and "ePPM" in f for f in os.listdir(cycle_path))
                has_fuse = any(f.endswith(".xlsx") and "Fuse" in f for f in os.listdir(cycle_path))
                if has_eppm and has_fuse:
                    cycles.append(num)
            except (ValueError, IndexError):
                continue
    return sorted(cycles)


def main():
    print("=" * 70)
    print("TRAINING REMINDER SYSTEM - Multi-Cycle Simulation")
    print("=" * 70)

    # Discover available cycles
    available_cycles = discover_cycles()
    if not available_cycles:
        print("\nNo simulation data found in data/simulation/")
        print("Run 'python generate_test_data.py' first to create test data.")
        sys.exit(1)

    print(f"\nDiscovered {len(available_cycles)} cycles: {available_cycles}")

    config = load_config()

    # Reset for fresh simulation
    print("\nPreparing fresh simulation...")
    reset_database(config)

    # Clear archive and output folders for clean demo
    for folder in ["archive_folder", "output_folder"]:
        path = config["paths"][folder]
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)

    # Run each cycle until all PMs certified or no more cycles
    all_summaries = []
    for cycle_num in available_cycles:
        print(f"\n{'='*70}")
        print(f"RUNNING CYCLE {cycle_num} of {len(available_cycles)}")
        print(f"{'='*70}")

        clear_input_folder(config)
        copy_cycle_files(cycle_num, config)

        try:
            summary = run_cycle()
            all_summaries.append(summary)

            reminders = summary.get("training_reminders_generated", summary.get("reminders_generated", 0)) if summary else 0
            if reminders == 0 and cycle_num > 1:
                print(f"\n  *** ZERO reminders generated! All PMs are certified. ***")
                print(f"  Simulation reached full certification at cycle {cycle_num}.")
                break

        except Exception as e:
            print(f"\n  ERROR in cycle {cycle_num}: {e}")
            import traceback
            traceback.print_exc()
            continue

    # Print cross-cycle comparison
    print_cross_cycle_summary(config)

    # Print compact progression table
    if all_summaries:
        print("\n--- Cycle Progression Table ---")
        print(f"{'Cycle':<7} {'PMs':<7} {'Match':<7} {'Done':<7} {'Elig':<7} {'TrRem':<7} {'S1':<5} {'S2':<5} {'S3+':<5} {'ITPM':<6} {'Escal':<6} {'RoleChg':<8}")
        print("-" * 86)
        for s in all_summaries:
            if s:
                cid = s.get("cycle_id", "?")
                # Get stage breakdown from DB
                db_path = config["paths"]["database"]
                conn = sqlite3.connect(db_path)
                stages = conn.execute("""
                    SELECT reminder_stage, COUNT(*) as cnt
                    FROM communication_history WHERE cycle_id = ?
                    GROUP BY reminder_stage
                """, (cid,)).fetchall()
                conn.close()
                s1 = sum(r[1] for r in stages if r[0] == 1)
                s2 = sum(r[1] for r in stages if r[0] == 2)
                s3p = sum(r[1] for r in stages if r[0] >= 3)
                train_rem = s.get('training_reminders_generated', s.get('reminders_generated', ''))
                miss_itpm = s.get('missing_itpm_reminders_to_pm', s.get('missing_itpm_reminders_generated', ''))
                escalations = s.get('missing_itpm_escalations_to_owner', '')
                role_chg = s.get('role_changed_itpm_reminders', '')
                print(f"{cid:<7} {s.get('total_pms_in_eppm',''):<7} "
                      f"{s.get('matched_pms',''):<7} {s.get('pms_training_complete',''):<7} "
                      f"{s.get('pms_eligible_for_reminder',''):<7} {train_rem:<7} "
                      f"{s1:<5} {s2:<5} {s3p:<5} {miss_itpm:<6} {escalations:<6} {role_chg:<8}")

    print("\n" + "=" * 70)
    print("SIMULATION COMPLETE")
    print("=" * 70)
    print(f"\nTotal cycles run: {len(all_summaries)}")
    if all_summaries and all_summaries[-1]:
        last = all_summaries[-1]
        train_rem = last.get("training_reminders_generated", last.get("reminders_generated", 0))
        itpm_rem = last.get("missing_itpm_reminders_to_pm", last.get("missing_itpm_reminders_generated", 0))
        esc_rem = last.get("missing_itpm_escalations_to_owner", 0)
        if train_rem == 0:
            print("Result: ALL PMs are fully certified!")
        else:
            print(f"Result: {train_rem} training reminders still pending in last cycle")
        if itpm_rem > 0:
            print(f"  Note: {itpm_rem} IT PM assignment reminders sent to PMs")
        if esc_rem > 0:
            print(f"  Note: {esc_rem} escalations sent to Project Owners")
    print(f"\nCheck the following locations:")
    print(f"  Output:   data/output/")
    print(f"  Archive:  data/archive/")
    print(f"  Database: {config['paths']['database']}")
    print(f"  Logs:     logs/")


if __name__ == "__main__":
    main()
