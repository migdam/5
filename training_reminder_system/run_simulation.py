#!/usr/bin/env python3
##############################################################################
# run_simulation.py — Multi-Cycle Simulation Runner
#
# This script runs the training reminder system across multiple weekly
# cycles using pre-generated synthetic data from generate_test_data.py.
# It demonstrates the full lifecycle:
#   - Training reminders progressing from Stage 1 → 2 → 3 → follow-ups
#   - New PMs joining and starting at Stage 1
#   - PMs completing training and receiving congratulations
#   - Missing IT PM reminders escalating to Project Owners
#   - Compliance improvements generating thank-you notes
#   - Ghost projects being filtered out
#
# HOW IT WORKS:
#   1. Resets the database (fresh start for each simulation)
#   2. Discovers all available cycles in data/simulation/
#   3. For each cycle:
#      - Copies that cycle's files (ePPM, Fuse, role_changes, etc.)
#        from data/simulation/cycle_N/ to data/input/
#      - Runs the main.py pipeline via run_cycle()
#      - Prints summary counts
#   4. Stops when 0 training reminders are generated (all certified)
#   5. Prints a cross-cycle progression table and analysis
#
# PROGRESSION TABLE COLUMNS:
#   Cycle — cycle number (= week number)
#   Ghost — projects filtered out (completed/cancelled/excluded)
#   PMs — unique PMs found in ePPM
#   Match — PMs matched to Fuse training records
#   Done — PMs with all training complete
#   Elig — PMs eligible for training reminders
#   TrRem — training reminders generated
#   S1/S2/S3+ — reminder stage breakdown
#   ITPM — missing IT PM reminders to PMs
#   Escal — escalations to Project Owners
#   RChg — role-changed IT PM alerts
##############################################################################
"""Run a multi-cycle simulation to demonstrate the Training Reminder System."""
import argparse
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


def run_simulation(start_cycle=None, end_cycle=None, cycles=None,
                   keep_db=False, keep_output=False, stop_on_zero=True,
                   config_path="config.yaml", generate_first=False,
                   generator_args=None):
    """Run a multi-cycle simulation.

    Args:
        start_cycle: First cycle number to run (default: first available).
        end_cycle: Last cycle number to run (default: last available).
        cycles: Explicit list of cycle numbers to run (overrides start/end).
        keep_db: If True, keep the existing database (resume mode).
        keep_output: If True, keep existing output/archive folders.
        stop_on_zero: If True, stop when 0 training reminders generated.
        config_path: Path to config.yaml.
        generate_first: If True, run generate_test_data.py before simulating.
        generator_args: List of extra CLI args for generate_test_data.py
            (e.g., ["--num-people", "100", "--training-speed", "2.0"]).

    Returns:
        List of summary dicts, one per cycle.
    """
    print("=" * 70)
    print("TRAINING REMINDER SYSTEM - Multi-Cycle Simulation")
    print("=" * 70)

    # Optionally generate test data first
    if generate_first:
        import subprocess
        cmd = [sys.executable, "generate_test_data.py"]
        if generator_args:
            cmd.extend(generator_args)
        print(f"\nGenerating test data: {' '.join(cmd)}")
        result = subprocess.run(cmd, timeout=300)
        if result.returncode != 0:
            print("ERROR: Test data generation failed.")
            sys.exit(1)

    # Discover available cycles
    available_cycles = discover_cycles()
    if not available_cycles:
        print("\nNo simulation data found in data/simulation/")
        print("Run 'python generate_test_data.py' first to create test data.")
        sys.exit(1)

    # Determine which cycles to run
    if cycles:
        run_cycles = [c for c in cycles if c in available_cycles]
    else:
        lo = start_cycle or available_cycles[0]
        hi = end_cycle or available_cycles[-1]
        run_cycles = [c for c in available_cycles if lo <= c <= hi]

    if not run_cycles:
        print(f"\nNo matching cycles found. Available: {available_cycles}")
        sys.exit(1)

    print(f"\nWill run cycles: {run_cycles} (of {len(available_cycles)} available)")

    config = load_config(config_path)

    # Reset or keep database
    if not keep_db:
        print("\nPreparing fresh simulation...")
        reset_database(config)
    else:
        print("\nResuming with existing database (--keep-db)...")

    # Clear or keep output/archive folders
    if not keep_output:
        for folder in ["archive_folder", "output_folder"]:
            path = config["paths"][folder]
            if os.path.exists(path):
                shutil.rmtree(path)
            os.makedirs(path, exist_ok=True)

    # Run each cycle
    all_summaries = []
    for cycle_num in run_cycles:
        print(f"\n{'='*70}")
        print(f"RUNNING CYCLE {cycle_num} of {run_cycles[-1]}")
        print(f"{'='*70}")

        clear_input_folder(config)
        copy_cycle_files(cycle_num, config)

        try:
            summary = run_cycle(config_path)
            all_summaries.append(summary)

            reminders = summary.get("training_reminders_generated", summary.get("reminders_generated", 0)) if summary else 0
            if stop_on_zero and reminders == 0 and cycle_num > run_cycles[0]:
                print(f"\n  *** ZERO reminders generated! All PMs are certified. ***")
                print(f"  Simulation reached full certification at cycle {cycle_num}.")
                break

        except Exception as e:
            print(f"\n  ERROR in cycle {cycle_num}: {e}")
            import traceback
            traceback.print_exc()
            continue

    return all_summaries, config


def main():
    parser = argparse.ArgumentParser(
        description="Run a multi-cycle simulation of the Training Reminder System",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--start-cycle", type=int, default=None,
                        help="First cycle to run (default: first available)")
    parser.add_argument("--end-cycle", type=int, default=None,
                        help="Last cycle to run (default: last available)")
    parser.add_argument("--cycles", type=int, nargs="+", default=None,
                        help="Explicit list of cycle numbers to run (e.g., --cycles 1 3 5)")
    parser.add_argument("--keep-db", action="store_true",
                        help="Keep existing database instead of resetting (resume mode)")
    parser.add_argument("--keep-output", action="store_true",
                        help="Keep existing output/archive folders")
    parser.add_argument("--no-stop", action="store_true",
                        help="Don't stop when 0 training reminders (run all cycles)")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config.yaml")
    parser.add_argument("--generate", action="store_true",
                        help="Generate test data before running simulation")
    parser.add_argument("--generator-args", nargs=argparse.REMAINDER, default=None,
                        help="Extra args for generate_test_data.py (e.g., --generator-args --num-people 100)")

    args = parser.parse_args()

    all_summaries, config = run_simulation(
        start_cycle=args.start_cycle,
        end_cycle=args.end_cycle,
        cycles=args.cycles,
        keep_db=args.keep_db,
        keep_output=args.keep_output,
        stop_on_zero=not args.no_stop,
        config_path=args.config,
        generate_first=args.generate,
        generator_args=args.generator_args,
    )

    # Print cross-cycle comparison
    print_cross_cycle_summary(config)

    # Print compact progression table
    if all_summaries:
        print("\n--- Cycle Progression Table ---")
        print(f"{'Cycle':<7} {'Ghost':<7} {'PMs':<7} {'Match':<7} {'Done':<7} {'Elig':<7} {'TrRem':<7} {'S1':<5} {'S2':<5} {'S3+':<5} {'ITPM':<6} {'Escal':<6} {'RChg':<6}")
        print("-" * 92)
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
                ghost = s.get('ghost_projects_filtered', '')
                print(f"{cid:<7} {ghost:<7} {s.get('total_pms_in_eppm',''):<7} "
                      f"{s.get('matched_pms',''):<7} {s.get('pms_training_complete',''):<7} "
                      f"{s.get('pms_eligible_for_reminder',''):<7} {train_rem:<7} "
                      f"{s1:<5} {s2:<5} {s3p:<5} {miss_itpm:<6} {escalations:<6} {role_chg:<6}")

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
