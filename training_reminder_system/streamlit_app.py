#!/usr/bin/env python3
##############################################################################
# streamlit_app.py — Streamlit Web UI for the Training Reminder System
#
# Provides a browser-based interface for:
#   - Uploading input Excel files (ePPM, Fuse, optional files)
#   - Running a processing cycle
#   - Viewing results (summary, reminders, matching stats)
#   - Browsing the database (cycle history, communications, data quality)
#   - Previewing generated emails
#   - Downloading output files
#
# Run with:  streamlit run streamlit_app.py
##############################################################################

import sys
import os
import io
import shutil
import sqlite3
import logging
import tempfile
import zipfile
from datetime import datetime

import streamlit as st
import pandas as pd

# Ensure project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from src.config_loader import load_config
from src.repository import Database
from src.file_loader import InputValidationError

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Training Reminder System",
    page_icon=":mortar_board:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_config():
    """Load config, changing to project root so relative paths work."""
    original_dir = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        config = load_config("config.yaml")
    finally:
        os.chdir(original_dir)
    return config


def get_db_connection(config):
    """Return a read-only sqlite3 connection for querying."""
    db_path = os.path.join(PROJECT_ROOT, config["paths"]["database"])
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def save_uploaded_file(uploaded_file, dest_folder):
    """Save an uploaded file to the input folder."""
    os.makedirs(dest_folder, exist_ok=True)
    dest_path = os.path.join(dest_folder, uploaded_file.name)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest_path


def zip_directory(dir_path):
    """Create an in-memory zip of a directory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, dir_path)
                zf.write(file_path, arcname)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("Training Reminder System")

page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Run Cycle", "Reminders", "Templates", "Calendar", "IT PM Track Record",
     "Cycle Comparison", "Cycle History", "Communications", "Data Quality",
     "Settings", "Simulation", "Log Viewer", "Archive Browser", "Database Explorer"],
    index=0,
)


# ===========================================================================
# PAGE: Dashboard
# ===========================================================================
if page == "Dashboard":
    st.title("Dashboard")
    st.markdown("Key metrics tracking IT PM certification progress, compliance, and reminder effectiveness.")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            cycles_df = pd.read_sql_query(
                "SELECT id, cycle_timestamp FROM cycles WHERE run_status = 'completed' ORDER BY id",
                conn,
            )
            if cycles_df.empty:
                st.info("No completed cycles yet. Run a processing cycle to see metrics.")
            else:
                cycles_df["date"] = pd.to_datetime(cycles_df["cycle_timestamp"]).dt.strftime("%Y-%m-%d")

                # ==============================================================
                # METRIC 1: % IT PMs Certified Over Time
                # ==============================================================
                st.header("IT PM Certification Rate Over Time")

                cert_data = []
                for _, cycle in cycles_df.iterrows():
                    cid = int(cycle["id"])
                    row = conn.execute(
                        """SELECT
                               COUNT(*) as total,
                               SUM(CASE WHEN overall_training_status = 'complete' THEN 1 ELSE 0 END) as certified
                           FROM training_snapshots
                           WHERE cycle_id = ?""",
                        (cid,),
                    ).fetchone()
                    total = row["total"] if row["total"] else 0
                    certified = row["certified"] if row["certified"] else 0
                    pct = round(certified / total * 100, 1) if total > 0 else 0.0
                    cert_data.append({
                        "Cycle": f"Cycle {cid}",
                        "Date": cycle["date"],
                        "Certified": certified,
                        "Not Certified": total - certified,
                        "Total PMs": total,
                        "% Certified": pct,
                    })

                cert_df = pd.DataFrame(cert_data)

                if not cert_df.empty:
                    # KPI cards
                    latest = cert_df.iloc[-1]
                    first = cert_df.iloc[0]
                    delta_pct = latest["% Certified"] - first["% Certified"]

                    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                    kpi1.metric("Current Certification Rate", f"{latest['% Certified']}%",
                                delta=f"{delta_pct:+.1f}pp" if len(cert_df) > 1 else None)
                    kpi2.metric("Certified PMs", int(latest["Certified"]))
                    kpi3.metric("Not Certified", int(latest["Not Certified"]))
                    kpi4.metric("Total PMs Tracked", int(latest["Total PMs"]))

                    # Line chart — % certified over time
                    chart_df = cert_df.set_index("Cycle")[["% Certified"]]
                    st.line_chart(chart_df, height=300)

                    # Stacked view
                    with st.expander("Detailed Breakdown per Cycle"):
                        st.dataframe(cert_df, use_container_width=True, hide_index=True)

                # ==============================================================
                # METRIC 2: % Projects Not Compliant Over Time
                # ==============================================================
                st.header("Project Compliance Rate Over Time")

                compliance_data = []
                for _, cycle in cycles_df.iterrows():
                    cid = int(cycle["id"])
                    # Get all PMs with compliance data for this cycle
                    rows = conn.execute(
                        """SELECT compliance_issues_json
                           FROM training_snapshots
                           WHERE cycle_id = ? AND compliance_issues_json IS NOT NULL
                             AND compliance_issues_json != 'null'""",
                        (cid,),
                    ).fetchall()

                    # Collect unique projects with issues
                    import json as json_mod
                    projects_with_issues = set()
                    for r in rows:
                        try:
                            issues = json_mod.loads(r["compliance_issues_json"])
                            if isinstance(issues, list):
                                for issue in issues:
                                    pid = issue.get("project_id")
                                    if pid:
                                        projects_with_issues.add(pid)
                        except (json_mod.JSONDecodeError, TypeError):
                            pass

                    # Total unique projects in this cycle
                    total_projects_row = conn.execute(
                        "SELECT COUNT(DISTINCT project_id) as cnt FROM assignment_snapshots WHERE cycle_id = ?",
                        (cid,),
                    ).fetchone()
                    total_projects = total_projects_row["cnt"] if total_projects_row else 0
                    non_compliant = len(projects_with_issues)
                    compliant = total_projects - non_compliant if total_projects > non_compliant else 0
                    pct_non_compliant = round(non_compliant / total_projects * 100, 1) if total_projects > 0 else 0.0

                    compliance_data.append({
                        "Cycle": f"Cycle {cid}",
                        "Date": cycle["date"],
                        "Total Projects": total_projects,
                        "Non-Compliant": non_compliant,
                        "Compliant": compliant,
                        "% Non-Compliant": pct_non_compliant,
                        "% Compliant": round(100 - pct_non_compliant, 1),
                    })

                comp_df = pd.DataFrame(compliance_data)

                if not comp_df.empty and comp_df["Total Projects"].sum() > 0:
                    latest_c = comp_df.iloc[-1]
                    first_c = comp_df.iloc[0]
                    delta_nc = latest_c["% Non-Compliant"] - first_c["% Non-Compliant"]

                    kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)
                    kpi_c1.metric("Non-Compliant Rate", f"{latest_c['% Non-Compliant']}%",
                                  delta=f"{delta_nc:+.1f}pp" if len(comp_df) > 1 else None,
                                  delta_color="inverse")
                    kpi_c2.metric("Non-Compliant Projects", int(latest_c["Non-Compliant"]))
                    kpi_c3.metric("Compliant Projects", int(latest_c["Compliant"]))
                    kpi_c4.metric("Total Projects", int(latest_c["Total Projects"]))

                    chart_comp = comp_df.set_index("Cycle")[["% Non-Compliant", "% Compliant"]]
                    st.line_chart(chart_comp, height=300)

                    with st.expander("Detailed Breakdown per Cycle"):
                        st.dataframe(comp_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No compliance data available yet.")

                # ==============================================================
                # METRIC 3: Avg Number of Reminders to Certification
                # ==============================================================
                st.header("Reminders to Certification")
                st.markdown("How many training reminders does it take before a PM completes certification?")

                # Find PMs who received congratulations (stage 99) — they completed training
                certified_pms = conn.execute(
                    """SELECT DISTINCT project_manager_id
                       FROM communication_history
                       WHERE reminder_stage = 99"""
                ).fetchall()

                reminders_to_cert = []
                for pm_row_cert in certified_pms:
                    pm_id = pm_row_cert["project_manager_id"]
                    # Count training reminders (stage 1-98) sent before the congratulations
                    congrats_cycle = conn.execute(
                        """SELECT MIN(cycle_id) as first_congrats_cycle
                           FROM communication_history
                           WHERE project_manager_id = ? AND reminder_stage = 99""",
                        (pm_id,),
                    ).fetchone()
                    if congrats_cycle and congrats_cycle["first_congrats_cycle"]:
                        reminder_count = conn.execute(
                            """SELECT COUNT(*) as cnt
                               FROM communication_history
                               WHERE project_manager_id = ?
                                 AND reminder_stage > 0 AND reminder_stage < 99
                                 AND cycle_id < ?""",
                            (pm_id, congrats_cycle["first_congrats_cycle"]),
                        ).fetchone()["cnt"]
                        pm_name = conn.execute(
                            "SELECT full_name FROM project_managers WHERE id = ?", (pm_id,)
                        ).fetchone()
                        reminders_to_cert.append({
                            "PM": pm_name["full_name"] if pm_name else f"PM #{pm_id}",
                            "Reminders Before Certification": reminder_count,
                        })

                if reminders_to_cert:
                    rtc_df = pd.DataFrame(reminders_to_cert)
                    avg_reminders = rtc_df["Reminders Before Certification"].mean()
                    median_reminders = rtc_df["Reminders Before Certification"].median()
                    max_reminders = rtc_df["Reminders Before Certification"].max()
                    min_reminders = rtc_df["Reminders Before Certification"].min()

                    kpi_r1, kpi_r2, kpi_r3, kpi_r4 = st.columns(4)
                    kpi_r1.metric("Average Reminders", f"{avg_reminders:.1f}")
                    kpi_r2.metric("Median Reminders", f"{median_reminders:.0f}")
                    kpi_r3.metric("Min", int(min_reminders))
                    kpi_r4.metric("Max", int(max_reminders))

                    # Distribution histogram
                    st.subheader("Distribution")
                    dist = rtc_df["Reminders Before Certification"].value_counts().sort_index()
                    dist.index = [f"{int(x)} reminders" for x in dist.index]
                    st.bar_chart(dist)

                    with st.expander(f"Per-PM Detail ({len(rtc_df)} certified PMs)"):
                        st.dataframe(
                            rtc_df.sort_values("Reminders Before Certification"),
                            use_container_width=True, hide_index=True,
                        )
                else:
                    st.info("No PMs have been certified yet (no congratulations sent). Metrics will appear after PMs complete training.")

                # ==============================================================
                # METRIC 4: Time to Certification from First Reminder
                # ==============================================================
                st.header("Time to Certification")
                st.markdown("Elapsed time between the first training reminder and certification completion.")

                time_to_cert = []
                for pm_row_cert in certified_pms:
                    pm_id = pm_row_cert["project_manager_id"]

                    # First training reminder date
                    first_reminder = conn.execute(
                        """SELECT MIN(ch.created_at) as first_date
                           FROM communication_history ch
                           WHERE ch.project_manager_id = ?
                             AND ch.reminder_stage > 0 AND ch.reminder_stage < 99""",
                        (pm_id,),
                    ).fetchone()

                    # Congratulations date
                    congrats = conn.execute(
                        """SELECT MIN(ch.created_at) as congrats_date
                           FROM communication_history ch
                           WHERE ch.project_manager_id = ?
                             AND ch.reminder_stage = 99""",
                        (pm_id,),
                    ).fetchone()

                    if first_reminder and congrats and first_reminder["first_date"] and congrats["congrats_date"]:
                        try:
                            # Handle both ISO and standard datetime formats
                            first_dt = pd.to_datetime(first_reminder["first_date"])
                            congrats_dt = pd.to_datetime(congrats["congrats_date"])
                            days_elapsed = (congrats_dt - first_dt).days
                            if days_elapsed >= 0:
                                pm_name = conn.execute(
                                    "SELECT full_name FROM project_managers WHERE id = ?", (pm_id,)
                                ).fetchone()
                                time_to_cert.append({
                                    "PM": pm_name["full_name"] if pm_name else f"PM #{pm_id}",
                                    "First Reminder": first_dt.strftime("%Y-%m-%d"),
                                    "Certified": congrats_dt.strftime("%Y-%m-%d"),
                                    "Days to Certification": days_elapsed,
                                    "Weeks": round(days_elapsed / 7, 1),
                                })
                        except (ValueError, TypeError):
                            pass

                if time_to_cert:
                    ttc_df = pd.DataFrame(time_to_cert)
                    avg_days = ttc_df["Days to Certification"].mean()
                    median_days = ttc_df["Days to Certification"].median()
                    max_days = ttc_df["Days to Certification"].max()
                    min_days = ttc_df["Days to Certification"].min()

                    kpi_t1, kpi_t2, kpi_t3, kpi_t4 = st.columns(4)
                    kpi_t1.metric("Average", f"{avg_days:.0f} days")
                    kpi_t2.metric("Median", f"{median_days:.0f} days")
                    kpi_t3.metric("Fastest", f"{min_days} days")
                    kpi_t4.metric("Slowest", f"{max_days} days")

                    # Distribution
                    st.subheader("Distribution")
                    # Bucket into week ranges
                    ttc_df["Week Bucket"] = ttc_df["Days to Certification"].apply(
                        lambda d: f"{(d // 7) * 7}-{(d // 7) * 7 + 6} days"
                        if d >= 7 else "0-6 days"
                    )
                    week_dist = ttc_df["Days to Certification"].value_counts().sort_index()
                    week_dist.index = [f"{int(x)} days" for x in week_dist.index]
                    st.bar_chart(week_dist)

                    with st.expander(f"Per-PM Detail ({len(ttc_df)} certified PMs)"):
                        st.dataframe(
                            ttc_df.sort_values("Days to Certification"),
                            use_container_width=True, hide_index=True,
                        )
                else:
                    st.info("No time-to-certification data available yet. Metrics will appear after PMs complete training following reminders.")

        finally:
            conn.close()


# ===========================================================================
# PAGE: Run Cycle
# ===========================================================================
elif page == "Run Cycle":
    st.title("Run Processing Cycle")
    st.markdown(
        "Upload input Excel files and run a processing cycle to generate training reminders."
    )

    config = get_config()
    input_folder = os.path.join(PROJECT_ROOT, config["paths"]["input_folder"])

    # --- File uploads ---
    st.header("1. Upload Input Files")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Required Files")
        eppm_file = st.file_uploader(
            "ePPM Export (.xlsx)", type=["xlsx"], key="eppm",
            help="Project assignments master list from ePPM."
        )
        fuse_file = st.file_uploader(
            "Fuse Training Export (.xlsx)", type=["xlsx"], key="fuse",
            help="Training completion records from Fuse learning platform."
        )

    with col2:
        st.subheader("Optional Files")
        excluded_file = st.file_uploader(
            "Excluded Projects (.xlsx)", type=["xlsx"], key="excluded",
            help="Ghost/cancelled projects to exclude."
        )
        aliases_file = st.file_uploader(
            "Identity Aliases (.xlsx)", type=["xlsx"], key="aliases",
            help="Manual name/email overrides for cross-system mismatches."
        )
        role_changes_file = st.file_uploader(
            "Role Changes (.xlsx)", type=["xlsx"], key="role_changes",
            help="IT PMs who have changed roles."
        )

    # --- Preview uploaded files ---
    if eppm_file or fuse_file:
        st.header("2. Preview Uploaded Data")
        if eppm_file:
            with st.expander("ePPM Data Preview", expanded=False):
                try:
                    df = pd.read_excel(io.BytesIO(eppm_file.getvalue()), engine="openpyxl")
                    st.write(f"**{len(df)} rows, {len(df.columns)} columns**")
                    st.dataframe(df.head(20), use_container_width=True)
                except Exception as e:
                    st.error(f"Could not read ePPM file: {e}")

        if fuse_file:
            with st.expander("Fuse Training Data Preview", expanded=False):
                try:
                    df = pd.read_excel(io.BytesIO(fuse_file.getvalue()), engine="openpyxl")
                    st.write(f"**{len(df)} rows, {len(df.columns)} columns**")
                    st.dataframe(df.head(20), use_container_width=True)
                except Exception as e:
                    st.error(f"Could not read Fuse file: {e}")

    # --- Run cycle ---
    st.header("3. Run Cycle")

    can_run = eppm_file is not None and fuse_file is not None
    if not can_run:
        st.info("Upload both required files (ePPM and Fuse) to enable the Run button.")

    if st.button("Run Processing Cycle", disabled=not can_run, type="primary"):
        # Clear input folder and save uploaded files
        if os.path.exists(input_folder):
            for f in os.listdir(input_folder):
                fp = os.path.join(input_folder, f)
                if os.path.isfile(fp):
                    os.remove(fp)
        os.makedirs(input_folder, exist_ok=True)

        save_uploaded_file(eppm_file, input_folder)
        save_uploaded_file(fuse_file, input_folder)
        if excluded_file:
            save_uploaded_file(excluded_file, input_folder)
        if aliases_file:
            save_uploaded_file(aliases_file, input_folder)
        if role_changes_file:
            save_uploaded_file(role_changes_file, input_folder)

        # Run the cycle
        with st.spinner("Running processing cycle..."):
            original_dir = os.getcwd()
            os.chdir(PROJECT_ROOT)
            try:
                from main import run_cycle
                summary = run_cycle("config.yaml")
            except InputValidationError as e:
                st.error(f"**Input Validation Error** - Cycle reverted.\n\n{e}")
                summary = None
            except Exception as e:
                st.error(f"**Cycle failed:** {e}")
                summary = None
            finally:
                os.chdir(original_dir)

        if summary:
            st.success("Cycle completed successfully!")

            # Display summary
            st.header("Cycle Results")
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("PMs in ePPM", summary.get("total_pms_in_eppm", 0))
            col2.metric("Matched PMs", summary.get("matched_pms", 0))
            col3.metric("Eligible for Reminder", summary.get("pms_eligible_for_reminder", 0))
            col4.metric("Reminders Generated", summary.get("training_reminders_generated", 0))

            col5, col6, col7, col8 = st.columns(4)
            col5.metric("Unmatched PMs", summary.get("unmatched_pms", 0))
            col6.metric("Training Complete", summary.get("pms_training_complete", 0))
            col7.metric("Congratulations", summary.get("congratulations_sent", 0))
            col8.metric("Ghost Projects Filtered", summary.get("ghost_projects_filtered", 0))

            col9, col10, col11, col12 = st.columns(4)
            col9.metric("Missing IT PM Reminders", summary.get("missing_itpm_reminders_to_pm", 0))
            col10.metric("Escalations to Owner", summary.get("missing_itpm_escalations_to_owner", 0))
            col11.metric("Role Change Alerts", summary.get("role_changed_itpm_reminders", 0))
            col12.metric("Skipped (No Email)", summary.get("skipped_no_email", 0))

            # Full summary table
            with st.expander("Full Summary Details"):
                summary_df = pd.DataFrame(
                    [{"Metric": k.replace("_", " ").title(), "Value": v} for k, v in summary.items()]
                )
                st.dataframe(summary_df, use_container_width=True, hide_index=True)

            # Find latest output folder and offer download
            output_base = os.path.join(PROJECT_ROOT, config["paths"]["output_folder"])
            if os.path.exists(output_base):
                output_dirs = sorted(
                    [d for d in os.listdir(output_base) if os.path.isdir(os.path.join(output_base, d))],
                    reverse=True,
                )
                if output_dirs:
                    latest_output = os.path.join(output_base, output_dirs[0])
                    st.header("Download Output")
                    zip_buf = zip_directory(latest_output)
                    st.download_button(
                        label=f"Download Output ({output_dirs[0]}.zip)",
                        data=zip_buf,
                        file_name=f"{output_dirs[0]}.zip",
                        mime="application/zip",
                    )

                    # Browse output files
                    with st.expander("Browse Output Files"):
                        for root, _dirs, files in os.walk(latest_output):
                            rel_root = os.path.relpath(root, latest_output)
                            if rel_root == ".":
                                rel_root = ""
                            for file in sorted(files):
                                rel_path = os.path.join(rel_root, file) if rel_root else file
                                file_path = os.path.join(root, file)
                                if st.button(f"View: {rel_path}", key=f"view_{rel_path}"):
                                    try:
                                        with open(file_path, "r", encoding="utf-8") as fh:
                                            content = fh.read()
                                        if file.endswith(".md"):
                                            st.markdown(content)
                                        elif file.endswith(".csv"):
                                            csv_df = pd.read_csv(file_path)
                                            st.dataframe(csv_df, use_container_width=True)
                                        else:
                                            st.code(content, language=None)
                                    except Exception as e:
                                        st.error(f"Could not read file: {e}")


# ===========================================================================
# PAGE: Reminders
# ===========================================================================
elif page == "Reminders":
    st.title("Generated Reminders")
    st.markdown("Browse and preview generated email reminders organized by send day.")

    config = get_config()
    output_base = os.path.join(PROJECT_ROOT, config["paths"]["output_folder"])

    if not os.path.exists(output_base):
        st.info("No output folder found. Run a processing cycle first.")
    else:
        output_dirs = sorted(
            [d for d in os.listdir(output_base) if os.path.isdir(os.path.join(output_base, d))],
            reverse=True,
        )
        if not output_dirs:
            st.info("No cycle outputs found. Run a processing cycle first.")
        else:
            selected_output = st.selectbox("Select Output Cycle", output_dirs)
            output_dir = os.path.join(output_base, selected_output)

            # Download button
            zip_buf = zip_directory(output_dir)
            st.download_button(
                label=f"Download All ({selected_output}.zip)",
                data=zip_buf,
                file_name=f"{selected_output}.zip",
                mime="application/zip",
            )

            # Show comms plan if it exists
            comms_plan_path = os.path.join(output_dir, "comms_plan.md")
            if os.path.exists(comms_plan_path):
                with st.expander("Weekly Communication Plan", expanded=False):
                    with open(comms_plan_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())

            # Show summary report if it exists
            summary_path = os.path.join(output_dir, "summary_report.md")
            if os.path.exists(summary_path):
                with st.expander("Cycle Summary Report", expanded=False):
                    with open(summary_path, "r", encoding="utf-8") as f:
                        st.markdown(f.read())

            # Organize by send day
            st.header("Browse by Send Day")
            send_days = sorted(
                [d for d in os.listdir(output_dir)
                 if d.startswith("send_") and os.path.isdir(os.path.join(output_dir, d))]
            )

            # Also collect category folders
            category_folders = []
            for d in sorted(os.listdir(output_dir)):
                full = os.path.join(output_dir, d)
                if os.path.isdir(full) and not d.startswith("send_"):
                    category_folders.append(d)

            if send_days:
                day_tabs = st.tabs([d.replace("send_", "").capitalize() for d in send_days])
                for tab, send_day in zip(day_tabs, send_days):
                    with tab:
                        day_path = os.path.join(output_dir, send_day)
                        # List subfolders and files
                        for item in sorted(os.listdir(day_path)):
                            item_path = os.path.join(day_path, item)
                            if os.path.isdir(item_path):
                                st.subheader(item.replace("_", " ").title())
                                files = sorted(os.listdir(item_path))
                                txt_files = [f for f in files if f.endswith(".txt")]
                                csv_files = [f for f in files if f.endswith(".csv")]

                                if csv_files:
                                    for csv_file in csv_files:
                                        csv_path = os.path.join(item_path, csv_file)
                                        with st.expander(f"CSV: {csv_file}"):
                                            try:
                                                csv_df = pd.read_csv(csv_path)
                                                st.dataframe(csv_df, use_container_width=True, hide_index=True)
                                            except Exception as e:
                                                st.error(f"Could not read CSV: {e}")

                                if txt_files:
                                    selected_file = st.selectbox(
                                        "Select email to preview",
                                        txt_files,
                                        key=f"sel_{send_day}_{item}",
                                    )
                                    if selected_file:
                                        file_path = os.path.join(item_path, selected_file)
                                        with open(file_path, "r", encoding="utf-8") as fh:
                                            content = fh.read()

                                        # Parse email parts for structured display
                                        lines = content.split("\n")
                                        to_line = ""
                                        subject_line = ""
                                        body_start = 0
                                        for i, line in enumerate(lines):
                                            if line.startswith("To:"):
                                                to_line = line[3:].strip()
                                            elif line.startswith("Subject:"):
                                                subject_line = line[8:].strip()
                                            elif "copy below this line" in line.lower():
                                                body_start = i + 2
                                                break

                                        if to_line:
                                            st.text_input("To", to_line, key=f"to_{send_day}_{item}_{selected_file}", disabled=True)
                                        if subject_line:
                                            st.text_input("Subject", subject_line, key=f"subj_{send_day}_{item}_{selected_file}", disabled=True)
                                        if body_start > 0 and body_start < len(lines):
                                            email_body = "\n".join(lines[body_start:])
                                            st.text_area("Email Body", email_body, height=300, key=f"body_{send_day}_{item}_{selected_file}")
                                        else:
                                            st.text_area("Full Content", content, height=300, key=f"full_{send_day}_{item}_{selected_file}")

                            elif os.path.isfile(item_path) and item.endswith(".txt"):
                                with st.expander(item):
                                    with open(item_path, "r", encoding="utf-8") as fh:
                                        st.code(fh.read(), language=None)
                            elif os.path.isfile(item_path) and item.endswith(".csv"):
                                with st.expander(item):
                                    try:
                                        csv_df = pd.read_csv(item_path)
                                        st.dataframe(csv_df, use_container_width=True, hide_index=True)
                                    except Exception as e:
                                        st.error(f"Could not read CSV: {e}")

            # Browse by category
            if category_folders:
                st.header("Browse by Category")
                selected_category = st.selectbox("Category", category_folders)
                if selected_category:
                    cat_path = os.path.join(output_dir, selected_category)
                    files = sorted(os.listdir(cat_path))
                    txt_files = [f for f in files if f.endswith(".txt")]
                    csv_files = [f for f in files if f.endswith(".csv")]

                    if csv_files:
                        for csv_file in csv_files:
                            csv_path = os.path.join(cat_path, csv_file)
                            with st.expander(f"CSV: {csv_file}", expanded=len(csv_files) == 1):
                                try:
                                    csv_df = pd.read_csv(csv_path)
                                    st.write(f"**{len(csv_df)} rows**")
                                    st.dataframe(csv_df, use_container_width=True, hide_index=True)
                                except Exception as e:
                                    st.error(f"Could not read CSV: {e}")

                    if txt_files:
                        st.write(f"**{len(txt_files)} email files**")
                        selected_file = st.selectbox(
                            "Select email to preview",
                            txt_files,
                            key=f"cat_{selected_category}",
                        )
                        if selected_file:
                            file_path = os.path.join(cat_path, selected_file)
                            with open(file_path, "r", encoding="utf-8") as fh:
                                content = fh.read()

                            lines = content.split("\n")
                            to_line = ""
                            subject_line = ""
                            body_start = 0
                            for i, line in enumerate(lines):
                                if line.startswith("To:"):
                                    to_line = line[3:].strip()
                                elif line.startswith("Subject:"):
                                    subject_line = line[8:].strip()
                                elif "copy below this line" in line.lower():
                                    body_start = i + 2
                                    break

                            if to_line:
                                st.text_input("To", to_line, key=f"cat_to_{selected_category}_{selected_file}", disabled=True)
                            if subject_line:
                                st.text_input("Subject", subject_line, key=f"cat_subj_{selected_category}_{selected_file}", disabled=True)
                            if body_start > 0 and body_start < len(lines):
                                email_body = "\n".join(lines[body_start:])
                                st.text_area("Email Body (select and copy)", email_body, height=300, key=f"cat_body_{selected_category}_{selected_file}")
                            else:
                                st.text_area("Full Content", content, height=300, key=f"cat_full_{selected_category}_{selected_file}")


# ===========================================================================
# PAGE: Templates
# ===========================================================================
elif page == "Templates":
    st.title("Email Templates")
    st.markdown(
        "View and edit the Jinja2 email templates used for generating reminders. "
        "Changes are saved directly to disk and take effect on the next cycle run."
    )

    config = get_config()
    templates_dir = os.path.join(PROJECT_ROOT, "templates")
    templates_config = config.get("templates", {})

    # Build a mapping: display name -> (config key, file path)
    TEMPLATE_CATEGORIES = {
        "Training Reminders": [
            ("stage_1", "Stage 1 — Friendly Awareness"),
            ("stage_2", "Stage 2 — Benefits-Oriented Encouragement"),
            ("stage_3", "Stage 3 — Persuasive, Action-Oriented"),
            ("default", "Stage 4+ — Default / Reusable"),
        ],
        "Follow-up Rotations (Stage 4+)": [
            ("followup_0", "Follow-up Angle: Compliance / Project-Focused"),
            ("followup_1", "Follow-up Angle: Peer / Social Proof"),
            ("followup_2", "Follow-up Angle: Support / Help Offer"),
        ],
        "IT PM Reminders": [
            ("missing_itpm", "Missing IT PM — Reminder to PM"),
            ("missing_itpm_escalation", "Missing IT PM — Escalation to Owner"),
            ("role_changed_itpm", "Role-Changed IT PM Alert"),
        ],
        "Other": [
            ("congratulations", "Congratulations — Newly Certified"),
            ("group_training", "Group Training Reminder"),
            ("group_missing_itpm", "Group Missing IT PM Reminder"),
        ],
    }

    # Sidebar-style category selection
    category = st.selectbox("Category", list(TEMPLATE_CATEGORIES.keys()))
    templates_in_category = TEMPLATE_CATEGORIES[category]

    template_key, template_label = st.selectbox(
        "Template",
        templates_in_category,
        format_func=lambda x: x[1],
    )

    # Resolve file path from config
    template_rel_path = templates_config.get(template_key, "")
    template_path = os.path.join(PROJECT_ROOT, template_rel_path) if template_rel_path else ""

    if not template_path or not os.path.exists(template_path):
        st.warning(f"Template file not found: `{template_rel_path}`")
    else:
        st.caption(f"File: `{template_rel_path}`")

        with open(template_path, "r", encoding="utf-8") as f:
            original_content = f.read()

        # Parse subject line (first line starting with "Subject:")
        lines = original_content.split("\n")
        subject_line = ""
        body_lines = lines
        if lines and lines[0].startswith("Subject:"):
            subject_line = lines[0][len("Subject:"):].strip()
            body_lines = lines[1:]

        if subject_line:
            st.text_input("Subject Line", subject_line, disabled=True, key=f"tpl_subj_{template_key}")

        # Show available variables
        import re
        variables = sorted(set(re.findall(r"\{\{(\s*[\w.]+\s*)\}\}", original_content)))
        variables = [v.strip() for v in variables]
        conditionals = sorted(set(re.findall(r"\{%\s*if\s+([\w.]+)\s*%\}", original_content)))

        col1, col2 = st.columns(2)
        with col1:
            if variables:
                st.markdown("**Template Variables:** " + ", ".join(f"`{{{{{v}}}}}`" for v in variables))
        with col2:
            if conditionals:
                st.markdown("**Conditionals:** " + ", ".join(f"`{c}`" for c in conditionals))

        # Editable text area
        edited_content = st.text_area(
            "Template Content",
            original_content,
            height=400,
            key=f"tpl_edit_{template_key}",
        )

        # Save button
        col_save, col_revert = st.columns([1, 4])
        with col_save:
            if st.button("Save Changes", type="primary", key=f"tpl_save_{template_key}"):
                if edited_content != original_content:
                    with open(template_path, "w", encoding="utf-8") as f:
                        f.write(edited_content)
                    st.success(f"Template saved: `{template_rel_path}`")
                    st.rerun()
                else:
                    st.info("No changes to save.")
        with col_revert:
            if edited_content != original_content:
                st.warning("You have unsaved changes.")

    # Reference: all template variables
    with st.expander("Template Variable Reference"):
        st.markdown("""
**Common variables available in all templates:**

| Variable | Description |
|----------|-------------|
| `{{name}}` | PM's full name |
| `{{links.learning_platform}}` | URL to the learning platform |
| `{{links.learning_platform_name}}` | Name of the learning platform |
| `{{links.eppm_tool}}` | URL to ePPM |
| `{{links.eppm_tool_name}}` | Name of ePPM tool |
| `{{links.pm_standard_page}}` | URL to PM Standard page |
| `{{links.pm_standard_name}}` | Name of PM Standard |
| `{{links.viva_engage_standard}}` | URL to Viva Engage community |
| `{{links.viva_engage_name}}` | Name of Viva Engage community |

**Training reminder variables:**

| Variable | Description |
|----------|-------------|
| `{{missing_both}}` | True if both Fundamentals and Advanced are missing |
| `{{completed_fundamentals}}` | True if Fundamentals is done but Advanced is not |
| `{{missing_fundamentals}}` | True if only Fundamentals is missing |
| `{{has_compliance_issues}}` | True if PM has projects with compliance issues |
| `{{compliance_issues}}` | List of compliance issue dicts (project_name, project_id, gate, etc.) |
| `{{has_compliance_improvements}}` | True if compliance improved since last cycle |
| `{{compliance_improvements}}` | List of improvement dicts |

**Missing IT PM variables:**

| Variable | Description |
|----------|-------------|
| `{{projects}}` | List of projects missing IT PM (project_name, project_id) |
| `{{project_count}}` | Number of affected projects |

**Group email variables:**

| Variable | Description |
|----------|-------------|
| `{{stage}}` | Reminder stage number |
| `{{recipients}}` | List of recipient dicts (name, email, missing_trainings) |
""")


# ===========================================================================
# PAGE: Calendar
# ===========================================================================
elif page == "Calendar":
    st.title("Communication Calendar")
    st.markdown(
        "View the weekly send schedule and a history of communications over time."
    )

    config = get_config()
    comms_schedule = config.get("comms_schedule", {})

    # ------------------------------------------------------------------
    # Section 1: Weekly Send Schedule (from config)
    # ------------------------------------------------------------------
    st.header("Weekly Send Schedule")
    st.markdown("Configured in `config.yaml` — defines which communications go out on which day after a Monday cycle run.")

    DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday"]
    ACTION_LABELS = {
        "run_cycle": "Run Cycle (data processing)",
        "training_reminders": "Training Reminders (individual, all stages)",
        "congratulations": "Congratulations (newly certified PMs)",
        "missing_itpm": "Missing IT PM Reminders (to PMs)",
        "role_changed_itpm": "Role-Changed IT PM Alerts",
        "escalations": "Escalations to Project Owners",
        "group_emails": "Group Emails (consolidated)",
        "nice_to_have": "Nice-to-Have Suggestions (optional)",
    }
    ACTION_COLORS = {
        "run_cycle": "#4A90D9",
        "training_reminders": "#E8913A",
        "congratulations": "#50C878",
        "missing_itpm": "#D94A6B",
        "role_changed_itpm": "#9B59B6",
        "escalations": "#E74C3C",
        "group_emails": "#3498DB",
        "nice_to_have": "#95A5A6",
    }

    # Visual weekly grid
    day_cols = st.columns(5)
    for col, day in zip(day_cols, DAY_ORDER):
        actions = comms_schedule.get(day, [])
        with col:
            st.markdown(f"#### {day.capitalize()}")
            if not actions:
                st.caption("No actions")
            else:
                for action in actions:
                    label = ACTION_LABELS.get(action, action)
                    color = ACTION_COLORS.get(action, "#888888")
                    st.markdown(
                        f'<div style="background-color:{color};color:white;padding:6px 10px;'
                        f'border-radius:6px;margin-bottom:6px;font-size:0.85em;">'
                        f'{label}</div>',
                        unsafe_allow_html=True,
                    )

    # Schedule table
    with st.expander("Schedule Table"):
        schedule_rows = []
        for day in DAY_ORDER:
            actions = comms_schedule.get(day, [])
            if actions:
                for action in actions:
                    schedule_rows.append({
                        "Day": day.capitalize(),
                        "Action": ACTION_LABELS.get(action, action),
                        "Config Key": action,
                    })
            else:
                schedule_rows.append({
                    "Day": day.capitalize(),
                    "Action": "—",
                    "Config Key": "—",
                })
        st.dataframe(pd.DataFrame(schedule_rows), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Section 2: Communication History Timeline
    # ------------------------------------------------------------------
    st.header("Communication History")

    conn = get_db_connection(config)
    if conn is None:
        st.info("No database found. Run a processing cycle to see history.")
    else:
        try:
            # Get cycle data
            cycles_df = pd.read_sql_query(
                "SELECT id, cycle_timestamp, run_status, notes FROM cycles ORDER BY id",
                conn,
            )

            if cycles_df.empty:
                st.info("No cycles recorded yet.")
            else:
                # Communication counts by cycle and stage
                comms_df = pd.read_sql_query(
                    """SELECT c.cycle_id,
                              cy.cycle_timestamp,
                              c.reminder_stage,
                              COUNT(*) as count
                       FROM communication_history c
                       JOIN cycles cy ON c.cycle_id = cy.id
                       GROUP BY c.cycle_id, c.reminder_stage
                       ORDER BY c.cycle_id""",
                    conn,
                )

                STAGE_LABELS = {
                    0: "Missing IT PM",
                    -1: "Escalation",
                    -2: "Role Change",
                    99: "Congratulations",
                }

                if comms_df.empty:
                    st.info("No communications recorded yet.")
                else:
                    # Pivot for per-cycle breakdown
                    comms_df["stage_label"] = comms_df["reminder_stage"].apply(
                        lambda s: STAGE_LABELS.get(s, f"Stage {s}")
                    )
                    pivot_df = comms_df.pivot_table(
                        index=["cycle_id", "cycle_timestamp"],
                        columns="stage_label",
                        values="count",
                        fill_value=0,
                        aggfunc="sum",
                    ).reset_index()
                    pivot_df.columns.name = None
                    pivot_df = pivot_df.rename(columns={"cycle_id": "Cycle", "cycle_timestamp": "Date"})

                    st.subheader("Communications per Cycle")
                    st.dataframe(pivot_df, use_container_width=True, hide_index=True)

                    # Bar chart
                    st.subheader("Communication Volume Over Time")
                    cycle_totals = comms_df.groupby(["cycle_id", "cycle_timestamp"])["count"].sum().reset_index()
                    cycle_totals.columns = ["Cycle", "Date", "Total Communications"]
                    cycle_totals["Cycle Label"] = cycle_totals.apply(
                        lambda r: f"Cycle {r['Cycle']}\n{r['Date'][:10]}", axis=1
                    )
                    st.bar_chart(
                        cycle_totals.set_index("Cycle Label")["Total Communications"],
                    )

                    # Stage distribution chart
                    st.subheader("Communication Types Across All Cycles")
                    stage_totals = comms_df.groupby("stage_label")["count"].sum().sort_values(ascending=False)
                    st.bar_chart(stage_totals)

                # ----------------------------------------------------------
                # Section 3: Cycle Timeline
                # ----------------------------------------------------------
                st.subheader("Cycle Run Timeline")
                cycles_df["cycle_date"] = pd.to_datetime(cycles_df["cycle_timestamp"]).dt.strftime("%Y-%m-%d %H:%M")

                for _, cycle in cycles_df.iterrows():
                    status_icon = {"completed": "OK", "failed": "FAIL", "running": "..."}.get(
                        cycle["run_status"], "?"
                    )
                    status_color = {"completed": "green", "failed": "red", "running": "orange"}.get(
                        cycle["run_status"], "gray"
                    )

                    # Get communication count for this cycle
                    comm_count_row = conn.execute(
                        "SELECT COUNT(*) as cnt FROM communication_history WHERE cycle_id = ?",
                        (cycle["id"],),
                    ).fetchone()
                    comm_count = comm_count_row["cnt"] if comm_count_row else 0

                    st.markdown(
                        f'<div style="display:flex;align-items:center;gap:12px;padding:8px 0;'
                        f'border-bottom:1px solid #eee;">'
                        f'<span style="background-color:{status_color};color:white;padding:2px 8px;'
                        f'border-radius:4px;font-size:0.8em;font-weight:bold;">{status_icon}</span>'
                        f'<strong>Cycle {cycle["id"]}</strong>'
                        f'<span style="color:#666;">{cycle["cycle_date"]}</span>'
                        f'<span style="color:#888;">{comm_count} communications</span>'
                        f'<span style="color:#aaa;font-size:0.85em;">{cycle["notes"] or ""}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                # ----------------------------------------------------------
                # Section 4: Upcoming Week Projection
                # ----------------------------------------------------------
                st.header("Next Week Projection")
                st.markdown(
                    "Based on the latest cycle results, here's what the next send week would look like."
                )

                # Get latest completed cycle's comms breakdown
                latest_cycle = cycles_df[cycles_df["run_status"] == "completed"]
                if latest_cycle.empty:
                    st.info("No completed cycles to project from.")
                else:
                    latest_id = latest_cycle.iloc[-1]["id"]
                    latest_comms = pd.read_sql_query(
                        """SELECT reminder_stage, COUNT(*) as count
                           FROM communication_history
                           WHERE cycle_id = ?
                           GROUP BY reminder_stage""",
                        conn,
                        params=(int(latest_id),),
                    )

                    # Map stages to schedule actions
                    stage_to_action = {
                        # Positive stages are training reminders
                        0: "missing_itpm",
                        -1: "escalations",
                        -2: "role_changed_itpm",
                        99: "congratulations",
                    }
                    action_counts = {}
                    for _, row in latest_comms.iterrows():
                        stage = row["reminder_stage"]
                        if stage > 0:
                            action = "training_reminders"
                        else:
                            action = stage_to_action.get(stage, "training_reminders")
                        action_counts[action] = action_counts.get(action, 0) + row["count"]

                    from datetime import timedelta
                    today = datetime.now()
                    # Find next Monday
                    days_to_monday = (7 - today.weekday()) % 7
                    if days_to_monday == 0:
                        next_monday = today
                    else:
                        next_monday = today + timedelta(days=days_to_monday)

                    projection_cols = st.columns(5)
                    for col, day_idx, day in zip(projection_cols, range(5), DAY_ORDER):
                        day_date = next_monday + timedelta(days=day_idx)
                        actions = comms_schedule.get(day, [])
                        with col:
                            st.markdown(f"**{day.capitalize()}**")
                            st.caption(day_date.strftime("%b %d"))
                            if not actions:
                                st.write("—")
                            else:
                                for action in actions:
                                    count = action_counts.get(action, 0)
                                    label = ACTION_LABELS.get(action, action).split("(")[0].strip()
                                    if action == "run_cycle":
                                        st.markdown(f"*{label}*")
                                    elif count > 0:
                                        st.markdown(f"**{count}** {label}")
                                    else:
                                        st.caption(f"0 {label}")

                    st.caption(
                        f"Based on Cycle {latest_id} "
                        f"({latest_cycle.iloc[-1]['cycle_timestamp'][:10]}). "
                        f"Actual counts depend on the next cycle run."
                    )
        finally:
            conn.close()


# ===========================================================================
# PAGE: IT PM Track Record
# ===========================================================================
elif page == "IT PM Track Record":
    st.title("IT PM Track Record")
    st.markdown(
        "Comprehensive per-PM view showing training progression, project assignments, "
        "communication history, and compliance issues across all cycles."
    )

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            # Load all PMs
            pms_df = pd.read_sql_query(
                "SELECT id, full_name, email, normalized_name, created_at FROM project_managers ORDER BY full_name",
                conn,
            )
            if pms_df.empty:
                st.info("No project managers recorded yet.")
            else:
                # PM selector with search
                col_search, col_select = st.columns([1, 2])
                with col_search:
                    pm_search = st.text_input("Search PM", "", placeholder="Type a name or email...")
                with col_select:
                    filtered_pms = pms_df
                    if pm_search:
                        mask = (
                            pms_df["full_name"].str.contains(pm_search, case=False, na=False)
                            | pms_df["email"].fillna("").str.contains(pm_search, case=False, na=False)
                        )
                        filtered_pms = pms_df[mask]

                    if filtered_pms.empty:
                        st.warning("No PMs match your search.")
                        st.stop()

                    selected_pm_id = st.selectbox(
                        "Select PM",
                        filtered_pms["id"].tolist(),
                        format_func=lambda x: f"{pms_df[pms_df['id']==x]['full_name'].values[0]} ({pms_df[pms_df['id']==x]['email'].values[0] or 'no email'})",
                    )

                pm_row = pms_df[pms_df["id"] == selected_pm_id].iloc[0]

                # ----------------------------------------------------------
                # PM Identity Card
                # ----------------------------------------------------------
                st.markdown("---")
                id_col1, id_col2, id_col3 = st.columns(3)
                id_col1.markdown(f"### {pm_row['full_name']}")
                id_col2.markdown(f"**Email:** {pm_row['email'] or 'N/A'}")
                id_col3.markdown(f"**First seen:** {pm_row['created_at'][:10]}")

                # Quick stats
                total_comms = conn.execute(
                    "SELECT COUNT(*) as cnt FROM communication_history WHERE project_manager_id = ?",
                    (int(selected_pm_id),),
                ).fetchone()["cnt"]
                max_stage_row = conn.execute(
                    "SELECT MAX(reminder_stage) as ms FROM communication_history WHERE project_manager_id = ? AND reminder_stage > 0 AND reminder_stage < 99",
                    (int(selected_pm_id),),
                ).fetchone()
                max_stage = max_stage_row["ms"] if max_stage_row and max_stage_row["ms"] is not None else 0
                got_congrats = conn.execute(
                    "SELECT COUNT(*) as cnt FROM communication_history WHERE project_manager_id = ? AND reminder_stage = 99",
                    (int(selected_pm_id),),
                ).fetchone()["cnt"] > 0
                latest_training = conn.execute(
                    """SELECT overall_training_status, eligibility_status, fundamentals_status, advanced_status
                       FROM training_snapshots WHERE project_manager_id = ?
                       ORDER BY cycle_id DESC LIMIT 1""",
                    (int(selected_pm_id),),
                ).fetchone()
                total_projects = conn.execute(
                    "SELECT COUNT(DISTINCT project_id) as cnt FROM assignment_snapshots WHERE project_manager_id = ?",
                    (int(selected_pm_id),),
                ).fetchone()["cnt"]
                cycles_appeared = conn.execute(
                    "SELECT COUNT(DISTINCT cycle_id) as cnt FROM training_snapshots WHERE project_manager_id = ?",
                    (int(selected_pm_id),),
                ).fetchone()["cnt"]

                stat_cols = st.columns(6)
                if latest_training:
                    current_status = latest_training["overall_training_status"]
                    stat_cols[0].metric("Training Status", current_status.capitalize() if current_status else "Unknown")
                else:
                    stat_cols[0].metric("Training Status", "Unknown")
                stat_cols[1].metric("Current Stage", max_stage if max_stage > 0 else "N/A")
                stat_cols[2].metric("Total Reminders", total_comms)
                stat_cols[3].metric("Projects (All Time)", total_projects)
                stat_cols[4].metric("Cycles Tracked", cycles_appeared)
                stat_cols[5].metric("Certified", "Yes" if got_congrats or (latest_training and latest_training["overall_training_status"] == "complete") else "No")

                # ----------------------------------------------------------
                # Tabs
                # ----------------------------------------------------------
                tab_train, tab_assign, tab_comms, tab_compliance, tab_timeline = st.tabs(
                    ["Training Progress", "Project Assignments", "Communications", "Compliance", "Full Timeline"]
                )

                # --- Training Progress ---
                with tab_train:
                    training_hist = pd.read_sql_query(
                        """SELECT ts.cycle_id, c.cycle_timestamp,
                                  ts.fundamentals_status, ts.advanced_status,
                                  ts.fundamentals_date, ts.advanced_date,
                                  ts.overall_training_status, ts.match_method,
                                  ts.missing_trainings, ts.nice_to_have_trainings,
                                  ts.eligibility_status
                           FROM training_snapshots ts
                           JOIN cycles c ON ts.cycle_id = c.id
                           WHERE ts.project_manager_id = ?
                           ORDER BY ts.cycle_id""",
                        conn,
                        params=(int(selected_pm_id),),
                    )
                    if training_hist.empty:
                        st.info("No training records for this PM.")
                    else:
                        st.subheader("Training Status Over Time")

                        # Visual progress indicators
                        for _, row in training_hist.iterrows():
                            fund = row["fundamentals_status"]
                            adv = row["advanced_status"]
                            fund_icon = "OK" if fund == "completed" else "---"
                            adv_icon = "OK" if adv == "completed" else "---"
                            fund_color = "green" if fund == "completed" else "#cc4444"
                            adv_color = "green" if adv == "completed" else "#cc4444"
                            eligibility = row["eligibility_status"] or ""

                            st.markdown(
                                f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #eee;">'
                                f'<strong style="min-width:70px;">Cycle {row["cycle_id"]}</strong>'
                                f'<span style="color:#888;min-width:90px;">{row["cycle_timestamp"][:10]}</span>'
                                f'<span style="background:{fund_color};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;">Fund: {fund_icon}</span>'
                                f'<span style="background:{adv_color};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;">Adv: {adv_icon}</span>'
                                f'<span style="color:#888;font-size:0.85em;">Match: {row["match_method"] or "?"}</span>'
                                f'<span style="color:#666;font-size:0.85em;">{eligibility}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                        st.markdown("")  # spacer

                        with st.expander("Full Training Data Table"):
                            st.dataframe(training_hist, use_container_width=True, hide_index=True)

                # --- Project Assignments ---
                with tab_assign:
                    assignments = pd.read_sql_query(
                        """SELECT a.cycle_id, c.cycle_timestamp,
                                  a.project_name, a.project_id,
                                  a.assignment_status AS role
                           FROM assignment_snapshots a
                           JOIN cycles c ON a.cycle_id = c.id
                           WHERE a.project_manager_id = ?
                           ORDER BY a.cycle_id DESC, a.project_name""",
                        conn,
                        params=(int(selected_pm_id),),
                    )
                    if assignments.empty:
                        st.info("No assignment records for this PM.")
                    else:
                        # Unique projects across all cycles
                        unique_projects = assignments[["project_id", "project_name"]].drop_duplicates()
                        st.write(f"**{len(unique_projects)} unique projects** across {assignments['cycle_id'].nunique()} cycles")

                        st.subheader("All Projects (All Time)")
                        st.dataframe(unique_projects.sort_values("project_name"), use_container_width=True, hide_index=True)

                        # Project assignment timeline — which projects in which cycles
                        st.subheader("Assignment Timeline")
                        pivot = assignments.pivot_table(
                            index=["project_id", "project_name"],
                            columns="cycle_id",
                            values="role",
                            aggfunc="first",
                            fill_value="",
                        ).reset_index()
                        pivot.columns.name = None
                        # Rename cycle columns
                        pivot.columns = [
                            f"Cycle {c}" if isinstance(c, (int, float)) and str(c).replace('.', '').isdigit() else c
                            for c in pivot.columns
                        ]
                        st.dataframe(pivot, use_container_width=True, hide_index=True)

                # --- Communications ---
                with tab_comms:
                    STAGE_LABELS = {
                        0: "Missing IT PM",
                        -1: "Escalation",
                        -2: "Role Change",
                        99: "Congratulations",
                    }

                    pm_comms = pd.read_sql_query(
                        """SELECT ch.cycle_id, c.cycle_timestamp,
                                  ch.reminder_stage, ch.email_subject,
                                  ch.email_body, ch.communication_status,
                                  ch.created_at
                           FROM communication_history ch
                           JOIN cycles c ON ch.cycle_id = c.id
                           WHERE ch.project_manager_id = ?
                           ORDER BY ch.cycle_id, ch.created_at""",
                        conn,
                        params=(int(selected_pm_id),),
                    )
                    if pm_comms.empty:
                        st.info("No communications sent to this PM.")
                    else:
                        st.write(f"**{len(pm_comms)} communications** across {pm_comms['cycle_id'].nunique()} cycles")

                        # Stage progression visualization
                        st.subheader("Reminder Progression")
                        for _, row in pm_comms.iterrows():
                            stage = row["reminder_stage"]
                            label = STAGE_LABELS.get(stage, f"Stage {stage}")
                            if stage == 99:
                                color = "#50C878"
                            elif stage < 0:
                                color = "#9B59B6"
                            elif stage == 0:
                                color = "#D94A6B"
                            elif stage <= 2:
                                color = "#E8913A"
                            else:
                                color = "#E74C3C"

                            st.markdown(
                                f'<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #eee;">'
                                f'<span style="background:{color};color:white;padding:2px 10px;border-radius:4px;'
                                f'font-size:0.8em;font-weight:bold;min-width:100px;text-align:center;">{label}</span>'
                                f'<strong>Cycle {row["cycle_id"]}</strong>'
                                f'<span style="color:#888;">{row["cycle_timestamp"][:10]}</span>'
                                f'<span style="color:#555;">{row["email_subject"]}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

                        # Email preview
                        st.subheader("Email Preview")
                        email_options = []
                        for _, row in pm_comms.iterrows():
                            stage = row["reminder_stage"]
                            stage_lbl = STAGE_LABELS.get(stage, f"Stage {stage}")
                            email_options.append(f"Cycle {row['cycle_id']} | {stage_lbl} | {row['email_subject']}")
                        selected_idx = st.selectbox(
                            "Select email", range(len(email_options)),
                            format_func=lambda x: email_options[x],
                            key="pm_track_email_sel",
                        )
                        sel_row = pm_comms.iloc[selected_idx]
                        st.text_input("To", pm_row["email"] or "N/A", disabled=True, key="pm_track_to")
                        st.text_input("Subject", sel_row["email_subject"], disabled=True, key="pm_track_subj")
                        st.text_area("Email Body", sel_row["email_body"], height=300, key="pm_track_body")

                # --- Compliance ---
                with tab_compliance:
                    compliance_rows = pd.read_sql_query(
                        """SELECT ts.cycle_id, c.cycle_timestamp,
                                  ts.compliance_issues_json
                           FROM training_snapshots ts
                           JOIN cycles c ON ts.cycle_id = c.id
                           WHERE ts.project_manager_id = ?
                             AND ts.compliance_issues_json IS NOT NULL
                             AND ts.compliance_issues_json != 'null'
                           ORDER BY ts.cycle_id""",
                        conn,
                        params=(int(selected_pm_id),),
                    )
                    if compliance_rows.empty:
                        st.info("No compliance issues recorded for this PM.")
                    else:
                        import json as json_mod

                        all_issues = []
                        for _, row in compliance_rows.iterrows():
                            try:
                                issues = json_mod.loads(row["compliance_issues_json"])
                                if isinstance(issues, list):
                                    for issue in issues:
                                        issue["cycle_id"] = row["cycle_id"]
                                        issue["cycle_date"] = row["cycle_timestamp"][:10]
                                        all_issues.append(issue)
                            except (json_mod.JSONDecodeError, TypeError):
                                pass

                        if not all_issues:
                            st.info("No parseable compliance issues found.")
                        else:
                            issues_df = pd.DataFrame(all_issues)
                            st.write(f"**{len(issues_df)} compliance issues** across {compliance_rows['cycle_id'].nunique()} cycles")

                            # Summary by project
                            if "project_id" in issues_df.columns:
                                st.subheader("Issues by Project")
                                project_issues = issues_df.groupby(
                                    ["project_id", "project_name"] if "project_name" in issues_df.columns else ["project_id"]
                                ).size().reset_index(name="Issue Count").sort_values("Issue Count", ascending=False)
                                st.dataframe(project_issues, use_container_width=True, hide_index=True)

                            # Summary by gate
                            if "gate" in issues_df.columns:
                                st.subheader("Issues by Gate")
                                gate_counts = issues_df["gate"].value_counts()
                                st.bar_chart(gate_counts)

                            # Trend over cycles
                            st.subheader("Compliance Issues Over Time")
                            cycle_issue_counts = issues_df.groupby(["cycle_id", "cycle_date"]).size().reset_index(name="Issues")
                            cycle_issue_counts["Label"] = cycle_issue_counts.apply(
                                lambda r: f"Cycle {r['cycle_id']}\n{r['cycle_date']}", axis=1
                            )
                            st.bar_chart(cycle_issue_counts.set_index("Label")["Issues"])

                            with st.expander("All Compliance Issues"):
                                st.dataframe(issues_df, use_container_width=True, hide_index=True)

                # --- Full Timeline ---
                with tab_timeline:
                    st.subheader("Complete Activity Timeline")
                    st.markdown("All events for this PM in chronological order.")

                    # Gather all events
                    events = []

                    # Training snapshots
                    for _, row in training_hist.iterrows() if not training_hist.empty else []:
                        events.append({
                            "cycle_id": row["cycle_id"],
                            "date": row["cycle_timestamp"][:10],
                            "type": "Training",
                            "detail": f"Fund: {row['fundamentals_status']}, Adv: {row['advanced_status']} | {row['eligibility_status'] or ''}",
                        })

                    # Assignments (summarized per cycle)
                    if not assignments.empty:
                        for cycle_id, group in assignments.groupby("cycle_id"):
                            cycle_date = group["cycle_timestamp"].iloc[0][:10]
                            project_list = ", ".join(group["project_name"].tolist()[:5])
                            extra = f" +{len(group)-5} more" if len(group) > 5 else ""
                            events.append({
                                "cycle_id": cycle_id,
                                "date": cycle_date,
                                "type": "Assignment",
                                "detail": f"{len(group)} projects: {project_list}{extra}",
                            })

                    # Communications
                    if not pm_comms.empty:
                        for _, row in pm_comms.iterrows():
                            stage = row["reminder_stage"]
                            label = STAGE_LABELS.get(stage, f"Stage {stage}")
                            events.append({
                                "cycle_id": row["cycle_id"],
                                "date": row["cycle_timestamp"][:10],
                                "type": f"Communication ({label})",
                                "detail": row["email_subject"],
                            })

                    if not events:
                        st.info("No activity recorded.")
                    else:
                        events_df = pd.DataFrame(events).sort_values(["cycle_id", "type"])

                        TYPE_COLORS = {
                            "Training": "#4A90D9",
                            "Assignment": "#50C878",
                        }

                        for _, ev in events_df.iterrows():
                            ev_type = ev["type"]
                            if "Communication" in ev_type:
                                color = "#E8913A"
                            else:
                                color = TYPE_COLORS.get(ev_type, "#888")

                            st.markdown(
                                f'<div style="display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-bottom:1px solid #eee;">'
                                f'<span style="min-width:60px;font-weight:bold;">Cycle {ev["cycle_id"]}</span>'
                                f'<span style="color:#888;min-width:85px;">{ev["date"]}</span>'
                                f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;'
                                f'font-size:0.8em;min-width:120px;text-align:center;">{ev_type}</span>'
                                f'<span style="color:#444;">{ev["detail"]}</span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )

        finally:
            conn.close()


# ===========================================================================
# PAGE: Cycle Comparison
# ===========================================================================
elif page == "Cycle Comparison":
    st.title("Cycle Comparison")
    st.markdown("Compare two cycles side-by-side to see what changed between them.")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            cycles_df = pd.read_sql_query(
                "SELECT id, cycle_timestamp, run_status FROM cycles WHERE run_status = 'completed' ORDER BY id",
                conn,
            )
            if len(cycles_df) < 2:
                st.info("Need at least 2 completed cycles to compare. Run more cycles first.")
            else:
                cycle_ids = cycles_df["id"].tolist()
                col_a, col_b = st.columns(2)
                with col_a:
                    cycle_a = st.selectbox(
                        "Cycle A (earlier)",
                        cycle_ids[:-1],
                        index=max(0, len(cycle_ids) - 2),
                        format_func=lambda x: f"Cycle {x} — {cycles_df[cycles_df['id']==x]['cycle_timestamp'].values[0][:10]}",
                    )
                with col_b:
                    cycle_b = st.selectbox(
                        "Cycle B (later)",
                        [c for c in cycle_ids if c > cycle_a] if cycle_a else cycle_ids[1:],
                        format_func=lambda x: f"Cycle {x} — {cycles_df[cycles_df['id']==x]['cycle_timestamp'].values[0][:10]}",
                    )

                if cycle_a and cycle_b:
                    # --- Training status comparison ---
                    st.header("Training Status Changes")

                    train_a = pd.read_sql_query(
                        """SELECT pm.id as pm_id, pm.full_name, pm.email,
                                  t.overall_training_status, t.eligibility_status,
                                  t.fundamentals_status, t.advanced_status
                           FROM training_snapshots t
                           JOIN project_managers pm ON t.project_manager_id = pm.id
                           WHERE t.cycle_id = ?""",
                        conn, params=(int(cycle_a),),
                    )
                    train_b = pd.read_sql_query(
                        """SELECT pm.id as pm_id, pm.full_name, pm.email,
                                  t.overall_training_status, t.eligibility_status,
                                  t.fundamentals_status, t.advanced_status
                           FROM training_snapshots t
                           JOIN project_managers pm ON t.project_manager_id = pm.id
                           WHERE t.cycle_id = ?""",
                        conn, params=(int(cycle_b),),
                    )

                    # Merge on pm_id
                    if not train_a.empty and not train_b.empty:
                        merged = train_a.merge(
                            train_b, on=["pm_id", "full_name", "email"],
                            suffixes=(f"_c{cycle_a}", f"_c{cycle_b}"),
                            how="outer", indicator=True,
                        )

                        # Newly certified
                        newly_certified = merged[
                            (merged.get(f"overall_training_status_c{cycle_a}") != "complete")
                            & (merged.get(f"overall_training_status_c{cycle_b}") == "complete")
                        ]
                        # New PMs (only in cycle B)
                        new_pms = merged[merged["_merge"] == "right_only"]
                        # Left PMs (only in cycle A)
                        left_pms = merged[merged["_merge"] == "left_only"]
                        # Status changed
                        both = merged[merged["_merge"] == "both"]
                        status_changed = both[
                            both[f"overall_training_status_c{cycle_a}"] != both[f"overall_training_status_c{cycle_b}"]
                        ]

                        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
                        kpi1.metric("Newly Certified", len(newly_certified))
                        kpi2.metric("New PMs", len(new_pms))
                        kpi3.metric("PMs No Longer Tracked", len(left_pms))
                        kpi4.metric("Status Changed", len(status_changed))

                        if not newly_certified.empty:
                            with st.expander(f"Newly Certified ({len(newly_certified)})"):
                                st.dataframe(
                                    newly_certified[["full_name", "email"]],
                                    use_container_width=True, hide_index=True,
                                )

                        if not new_pms.empty:
                            with st.expander(f"New PMs in Cycle {cycle_b} ({len(new_pms)})"):
                                display_cols = ["full_name", "email"]
                                avail = [c for c in display_cols if c in new_pms.columns]
                                st.dataframe(new_pms[avail], use_container_width=True, hide_index=True)

                        if not status_changed.empty:
                            with st.expander(f"Training Status Changed ({len(status_changed)})"):
                                show_cols = ["full_name", "email",
                                             f"overall_training_status_c{cycle_a}",
                                             f"overall_training_status_c{cycle_b}"]
                                avail = [c for c in show_cols if c in status_changed.columns]
                                st.dataframe(status_changed[avail], use_container_width=True, hide_index=True)

                    # --- Communication comparison ---
                    st.header("Communication Changes")

                    comms_a = pd.read_sql_query(
                        """SELECT pm.full_name, pm.email, ch.reminder_stage
                           FROM communication_history ch
                           JOIN project_managers pm ON ch.project_manager_id = pm.id
                           WHERE ch.cycle_id = ?""",
                        conn, params=(int(cycle_a),),
                    )
                    comms_b = pd.read_sql_query(
                        """SELECT pm.full_name, pm.email, ch.reminder_stage
                           FROM communication_history ch
                           JOIN project_managers pm ON ch.project_manager_id = pm.id
                           WHERE ch.cycle_id = ?""",
                        conn, params=(int(cycle_b),),
                    )

                    STAGE_LABELS = {0: "Missing IT PM", -1: "Escalation", -2: "Role Change", 99: "Congratulations"}

                    col_ca, col_cb = st.columns(2)
                    with col_ca:
                        st.subheader(f"Cycle {cycle_a}")
                        if comms_a.empty:
                            st.write("No communications")
                        else:
                            stage_counts_a = comms_a["reminder_stage"].value_counts().sort_index()
                            for s, c in stage_counts_a.items():
                                st.write(f"- {STAGE_LABELS.get(s, f'Stage {s}')}: **{c}**")
                    with col_cb:
                        st.subheader(f"Cycle {cycle_b}")
                        if comms_b.empty:
                            st.write("No communications")
                        else:
                            stage_counts_b = comms_b["reminder_stage"].value_counts().sort_index()
                            for s, c in stage_counts_b.items():
                                st.write(f"- {STAGE_LABELS.get(s, f'Stage {s}')}: **{c}**")

                    # --- Stage progression between cycles ---
                    if not comms_a.empty and not comms_b.empty:
                        st.header("Stage Progression")
                        st.markdown("PMs whose reminder stage changed between cycles.")
                        stages_a = comms_a.groupby("email")["reminder_stage"].max().reset_index()
                        stages_a.columns = ["email", f"stage_c{cycle_a}"]
                        stages_b = comms_b.groupby("email")["reminder_stage"].max().reset_index()
                        stages_b.columns = ["email", f"stage_c{cycle_b}"]
                        stage_merged = stages_a.merge(stages_b, on="email", how="inner")
                        progressed = stage_merged[
                            stage_merged[f"stage_c{cycle_a}"] != stage_merged[f"stage_c{cycle_b}"]
                        ]
                        if progressed.empty:
                            st.info("No stage changes between these cycles.")
                        else:
                            # Add names
                            name_map = pd.concat([comms_a, comms_b])[["full_name", "email"]].drop_duplicates(subset=["email"])
                            progressed = progressed.merge(name_map, on="email", how="left")
                            progressed[f"stage_c{cycle_a}"] = progressed[f"stage_c{cycle_a}"].apply(
                                lambda s: STAGE_LABELS.get(s, f"Stage {s}")
                            )
                            progressed[f"stage_c{cycle_b}"] = progressed[f"stage_c{cycle_b}"].apply(
                                lambda s: STAGE_LABELS.get(s, f"Stage {s}")
                            )
                            st.dataframe(
                                progressed[["full_name", "email", f"stage_c{cycle_a}", f"stage_c{cycle_b}"]],
                                use_container_width=True, hide_index=True,
                            )

                    # --- Assignment comparison ---
                    st.header("Project Assignment Changes")
                    assign_a = set(pd.read_sql_query(
                        "SELECT DISTINCT project_id FROM assignment_snapshots WHERE cycle_id = ?",
                        conn, params=(int(cycle_a),),
                    )["project_id"].tolist())
                    assign_b = set(pd.read_sql_query(
                        "SELECT DISTINCT project_id FROM assignment_snapshots WHERE cycle_id = ?",
                        conn, params=(int(cycle_b),),
                    )["project_id"].tolist())

                    new_projects = assign_b - assign_a
                    removed_projects = assign_a - assign_b
                    common_projects = assign_a & assign_b

                    kp1, kp2, kp3 = st.columns(3)
                    kp1.metric("New Projects", len(new_projects))
                    kp2.metric("Removed Projects", len(removed_projects))
                    kp3.metric("Continuing Projects", len(common_projects))

                    if new_projects:
                        with st.expander(f"New Projects in Cycle {cycle_b} ({len(new_projects)})"):
                            new_p_df = pd.read_sql_query(
                                f"SELECT DISTINCT project_id, project_name FROM assignment_snapshots WHERE cycle_id = ? AND project_id IN ({','.join('?' * len(new_projects))})",
                                conn, params=[int(cycle_b)] + list(new_projects),
                            )
                            st.dataframe(new_p_df, use_container_width=True, hide_index=True)

                    if removed_projects:
                        with st.expander(f"Removed Projects from Cycle {cycle_a} ({len(removed_projects)})"):
                            rem_p_df = pd.read_sql_query(
                                f"SELECT DISTINCT project_id, project_name FROM assignment_snapshots WHERE cycle_id = ? AND project_id IN ({','.join('?' * len(removed_projects))})",
                                conn, params=[int(cycle_a)] + list(removed_projects),
                            )
                            st.dataframe(rem_p_df, use_container_width=True, hide_index=True)

        finally:
            conn.close()


# ===========================================================================
# PAGE: Cycle History
# ===========================================================================
elif page == "Cycle History":
    st.title("Cycle History")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            cycles_df = pd.read_sql_query(
                "SELECT id, cycle_timestamp, run_status, notes FROM cycles ORDER BY id DESC",
                conn,
            )
            if cycles_df.empty:
                st.info("No cycles recorded yet.")
            else:
                st.dataframe(cycles_df, use_container_width=True, hide_index=True)

                # Cycle detail
                selected_cycle = st.selectbox(
                    "Select a cycle for details",
                    cycles_df["id"].tolist(),
                    format_func=lambda x: f"Cycle {x} - {cycles_df[cycles_df['id']==x]['cycle_timestamp'].values[0]} ({cycles_df[cycles_df['id']==x]['run_status'].values[0]})",
                )

                if selected_cycle:
                    st.subheader(f"Cycle {selected_cycle} Details")

                    tab1, tab2, tab3, tab4 = st.tabs(
                        ["Assignments", "Training Status", "Communications", "Data Quality"]
                    )

                    with tab1:
                        assignments_df = pd.read_sql_query(
                            """SELECT pm.full_name, pm.email, a.project_name, a.project_id,
                                      a.assignment_status, a.source_file
                               FROM assignment_snapshots a
                               JOIN project_managers pm ON a.project_manager_id = pm.id
                               WHERE a.cycle_id = ?
                               ORDER BY pm.full_name""",
                            conn,
                            params=(selected_cycle,),
                        )
                        if assignments_df.empty:
                            st.info("No assignment data for this cycle.")
                        else:
                            st.write(f"**{len(assignments_df)} assignments**")
                            st.dataframe(assignments_df, use_container_width=True, hide_index=True)

                    with tab2:
                        training_df = pd.read_sql_query(
                            """SELECT pm.full_name, pm.email,
                                      t.fundamentals_status, t.advanced_status,
                                      t.overall_training_status, t.match_method,
                                      t.missing_trainings, t.eligibility_status
                               FROM training_snapshots t
                               JOIN project_managers pm ON t.project_manager_id = pm.id
                               WHERE t.cycle_id = ?
                               ORDER BY pm.full_name""",
                            conn,
                            params=(selected_cycle,),
                        )
                        if training_df.empty:
                            st.info("No training data for this cycle.")
                        else:
                            st.write(f"**{len(training_df)} training records**")

                            # Status breakdown
                            col1, col2, col3 = st.columns(3)
                            complete = len(training_df[training_df["overall_training_status"] == "complete"])
                            incomplete = len(training_df[training_df["overall_training_status"] == "incomplete"])
                            col1.metric("Complete", complete)
                            col2.metric("Incomplete", incomplete)
                            col3.metric("Total", len(training_df))

                            st.dataframe(training_df, use_container_width=True, hide_index=True)

                    with tab3:
                        comms_df = pd.read_sql_query(
                            """SELECT pm.full_name, pm.email, c.reminder_stage,
                                      c.email_subject, c.communication_status, c.created_at
                               FROM communication_history c
                               JOIN project_managers pm ON c.project_manager_id = pm.id
                               WHERE c.cycle_id = ?
                               ORDER BY c.reminder_stage, pm.full_name""",
                            conn,
                            params=(selected_cycle,),
                        )
                        if comms_df.empty:
                            st.info("No communications for this cycle.")
                        else:
                            st.write(f"**{len(comms_df)} communications**")

                            # Stage breakdown
                            stage_counts = comms_df["reminder_stage"].value_counts().sort_index()
                            stage_labels = {
                                0: "Missing IT PM",
                                -1: "Escalation",
                                -2: "Role Change",
                                99: "Congratulations",
                            }
                            stage_display = pd.DataFrame({
                                "Stage": [stage_labels.get(s, f"Stage {s}") for s in stage_counts.index],
                                "Count": stage_counts.values,
                            })
                            st.dataframe(stage_display, use_container_width=True, hide_index=True)

                            st.dataframe(comms_df, use_container_width=True, hide_index=True)

                            # Email preview
                            st.subheader("Email Preview")
                            email_options = [
                                f"{row['full_name']} - {row['email_subject']}"
                                for _, row in comms_df.iterrows()
                            ]
                            if email_options:
                                selected_email_idx = st.selectbox(
                                    "Select an email to preview",
                                    range(len(email_options)),
                                    format_func=lambda x: email_options[x],
                                )
                                # Fetch full email body
                                email_row = conn.execute(
                                    """SELECT c.email_subject, c.email_body, pm.full_name, pm.email
                                       FROM communication_history c
                                       JOIN project_managers pm ON c.project_manager_id = pm.id
                                       WHERE c.cycle_id = ?
                                       ORDER BY c.reminder_stage, pm.full_name
                                       LIMIT 1 OFFSET ?""",
                                    (selected_cycle, selected_email_idx),
                                ).fetchone()
                                if email_row:
                                    st.text(f"To: {email_row['email']}")
                                    st.text(f"Subject: {email_row['email_subject']}")
                                    st.markdown("---")
                                    st.text(email_row["email_body"])

                    with tab4:
                        dq_df = pd.read_sql_query(
                            """SELECT issue_type, person_name, email, details, created_at
                               FROM data_quality_issues
                               WHERE cycle_id = ?
                               ORDER BY issue_type, person_name""",
                            conn,
                            params=(selected_cycle,),
                        )
                        if dq_df.empty:
                            st.info("No data quality issues for this cycle.")
                        else:
                            st.write(f"**{len(dq_df)} issues**")
                            st.dataframe(dq_df, use_container_width=True, hide_index=True)
        finally:
            conn.close()


# ===========================================================================
# PAGE: Communications
# ===========================================================================
elif page == "Communications":
    st.title("Communication History")
    st.markdown("View all communications across all cycles.")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            comms_df = pd.read_sql_query(
                """SELECT c.cycle_id, pm.full_name, pm.email, c.reminder_stage,
                          c.email_subject, c.communication_status, c.created_at
                   FROM communication_history c
                   JOIN project_managers pm ON c.project_manager_id = pm.id
                   ORDER BY c.created_at DESC""",
                conn,
            )
            if comms_df.empty:
                st.info("No communications recorded yet.")
            else:
                # Filters
                col1, col2, col3 = st.columns(3)
                with col1:
                    cycles = sorted(comms_df["cycle_id"].unique(), reverse=True)
                    selected_cycles = st.multiselect("Filter by Cycle", cycles, default=[])
                with col2:
                    stages = sorted(comms_df["reminder_stage"].unique())
                    stage_labels = {0: "Missing IT PM", -1: "Escalation", -2: "Role Change", 99: "Congratulations"}
                    stage_options = {s: stage_labels.get(s, f"Stage {s}") for s in stages}
                    selected_stages = st.multiselect(
                        "Filter by Stage",
                        stages,
                        format_func=lambda x: stage_options[x],
                        default=[],
                    )
                with col3:
                    search_name = st.text_input("Search by PM Name", "")

                filtered = comms_df.copy()
                if selected_cycles:
                    filtered = filtered[filtered["cycle_id"].isin(selected_cycles)]
                if selected_stages:
                    filtered = filtered[filtered["reminder_stage"].isin(selected_stages)]
                if search_name:
                    filtered = filtered[
                        filtered["full_name"].str.contains(search_name, case=False, na=False)
                    ]

                st.write(f"**{len(filtered)} communications** (of {len(comms_df)} total)")
                st.dataframe(filtered, use_container_width=True, hide_index=True)

                # Per-PM communication timeline
                st.subheader("PM Communication Timeline")
                pm_list = sorted(comms_df["full_name"].unique())
                selected_pm = st.selectbox("Select a PM", pm_list)
                if selected_pm:
                    pm_comms = comms_df[comms_df["full_name"] == selected_pm].sort_values("created_at")
                    for _, row in pm_comms.iterrows():
                        stage = row["reminder_stage"]
                        label = stage_labels.get(stage, f"Stage {stage}")
                        st.markdown(
                            f"**Cycle {row['cycle_id']}** | {label} | "
                            f"{row['email_subject']} | {row['created_at']}"
                        )
        finally:
            conn.close()


# ===========================================================================
# PAGE: Data Quality
# ===========================================================================
elif page == "Data Quality":
    st.title("Data Quality Issues")
    st.markdown("View data quality issues and resolve unmatched PMs by creating identity aliases.")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            dq_df = pd.read_sql_query(
                """SELECT d.cycle_id, d.issue_type, d.person_name, d.email,
                          d.details, d.created_at
                   FROM data_quality_issues d
                   ORDER BY d.created_at DESC""",
                conn,
            )
            if dq_df.empty:
                st.info("No data quality issues recorded.")
            else:
                # Summary by type
                st.subheader("Issues by Type")
                type_counts = dq_df["issue_type"].value_counts()
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.dataframe(
                        type_counts.reset_index().rename(columns={"index": "Issue Type", "issue_type": "Issue Type", "count": "Count"}),
                        use_container_width=True,
                        hide_index=True,
                    )

                # Filter
                issue_types = dq_df["issue_type"].unique().tolist()
                selected_type = st.selectbox("Filter by Issue Type", ["All"] + issue_types)

                filtered = dq_df if selected_type == "All" else dq_df[dq_df["issue_type"] == selected_type]
                st.write(f"**{len(filtered)} issues**")
                st.dataframe(filtered, use_container_width=True, hide_index=True)

                # -------------------------------------------------------
                # Unmatched PM Resolution
                # -------------------------------------------------------
                unmatched = dq_df[dq_df["issue_type"] == "unmatched_pm"]
                if not unmatched.empty:
                    st.header("Resolve Unmatched PMs")
                    st.markdown(
                        "Unmatched PMs could not be found in Fuse training records. "
                        "You can create an identity alias to link them, or check for "
                        "possible matches below."
                    )

                    # Get latest cycle's unmatched PMs (deduplicated)
                    latest_cycle = unmatched["cycle_id"].max()
                    latest_unmatched = unmatched[unmatched["cycle_id"] == latest_cycle].drop_duplicates(subset=["person_name"])
                    st.write(f"**{len(latest_unmatched)} unmatched PMs** in latest cycle (Cycle {latest_cycle})")

                    # Load Fuse names from DB for fuzzy matching suggestions
                    all_pms = pd.read_sql_query(
                        "SELECT DISTINCT full_name, email FROM project_managers ORDER BY full_name",
                        conn,
                    )

                    for idx, um_row in latest_unmatched.iterrows():
                        pm_name = um_row["person_name"] or "Unknown"
                        pm_email = um_row["email"] or ""

                        with st.expander(f"{pm_name} ({pm_email or 'no email'})"):
                            st.markdown(f"**Details:** {um_row['details']}")

                            # Suggest possible matches by partial name
                            if pm_name and pm_name != "Unknown":
                                name_parts = pm_name.lower().split()
                                suggestions = []
                                for _, pm in all_pms.iterrows():
                                    existing_name = (pm["full_name"] or "").lower()
                                    existing_email = (pm["email"] or "").lower()
                                    # Check if any name part appears in existing PM
                                    score = sum(1 for part in name_parts if part in existing_name or part in existing_email)
                                    if score > 0 and existing_name != pm_name.lower():
                                        suggestions.append((score, pm["full_name"], pm["email"]))

                                suggestions.sort(key=lambda x: -x[0])
                                top_suggestions = suggestions[:5]

                                if top_suggestions:
                                    st.markdown("**Possible matches in database:**")
                                    for score, sname, semail in top_suggestions:
                                        st.markdown(f"- {sname} ({semail or 'no email'}) — {score} name part(s) match")

                            # Alias creation form
                            st.markdown("**Create Identity Alias:**")
                            st.markdown(
                                "To resolve this, add a row to `identity_aliases.xlsx` with:\n"
                                f"- **alias_name:** `{pm_name}`\n"
                                f"- **alias_email:** `{pm_email}`\n"
                                "- **canonical_name:** *(the correct name in Fuse)*\n"
                                "- **canonical_email:** *(the correct email in Fuse)*\n"
                                "- **reason:** *(e.g., maiden name, domain change)*"
                            )

        finally:
            conn.close()


# ===========================================================================
# PAGE: Database Explorer
# ===========================================================================
elif page == "Database Explorer":
    st.title("Database Explorer")
    st.markdown("Browse all tables in the SQLite database.")

    config = get_config()
    conn = get_db_connection(config)

    if conn is None:
        st.info("No database found. Run a processing cycle first.")
    else:
        try:
            # List tables
            tables = pd.read_sql_query(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name", conn
            )["name"].tolist()

            selected_table = st.selectbox("Select Table", tables)

            if selected_table:
                # Row count
                count = pd.read_sql_query(f"SELECT COUNT(*) as cnt FROM [{selected_table}]", conn)["cnt"][0]
                st.write(f"**{count} rows** in `{selected_table}`")

                # Pagination
                page_size = st.selectbox("Rows per page", [25, 50, 100, 250], index=0)
                total_pages = max(1, (count + page_size - 1) // page_size)
                page_num = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
                offset = (page_num - 1) * page_size

                df = pd.read_sql_query(
                    f"SELECT * FROM [{selected_table}] LIMIT ? OFFSET ?",
                    conn,
                    params=(page_size, offset),
                )
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Custom query
                st.subheader("Custom SQL Query")
                query = st.text_area(
                    "Enter SQL query",
                    value=f"SELECT * FROM {selected_table} LIMIT 10",
                    height=100,
                )
                if st.button("Execute Query"):
                    try:
                        result_df = pd.read_sql_query(query, conn)
                        st.write(f"**{len(result_df)} rows returned**")
                        st.dataframe(result_df, use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.error(f"Query error: {e}")
        finally:
            conn.close()


# ===========================================================================
# PAGE: Settings
# ===========================================================================
elif page == "Settings":
    st.title("Settings")
    st.markdown("View and edit the system configuration (`config.yaml`).")

    config = get_config()
    config_path = os.path.join(PROJECT_ROOT, "config.yaml")

    import yaml

    with open(config_path, "r", encoding="utf-8") as f:
        raw_yaml = f.read()

    tab_visual, tab_raw = st.tabs(["Visual Editor", "Raw YAML"])

    with tab_visual:
        # --- Paths ---
        st.header("Paths")
        paths = config.get("paths", {})
        for key, val in paths.items():
            st.text_input(key, val, disabled=True, key=f"path_{key}")

        # --- Required Training ---
        st.header("Required Training Courses")
        req_training = config.get("required_training", {})
        for course_key, course_info in req_training.items():
            st.markdown(f"**{course_info.get('label', course_key)}**")
            st.text_input("Content Title", course_info.get("content_title", ""), disabled=True, key=f"rt_{course_key}")

        # --- Status Mapping ---
        st.header("Status Mappings")
        status_mapping = config.get("status_mapping", {})
        for key, values in status_mapping.items():
            label = key.replace("_", " ").title()
            st.markdown(f"**{label}:** {', '.join(str(v) for v in values)}")

        # --- Action Links ---
        st.header("Action Links")
        action_links = config.get("action_links", {})
        edited_links = {}
        changed = False
        for key, val in action_links.items():
            label = key.replace("_", " ").title()
            new_val = st.text_input(label, val, key=f"al_{key}")
            edited_links[key] = new_val
            if new_val != val:
                changed = True

        # --- Communication Settings ---
        st.header("Communication Settings")
        comm = config.get("communication", {})
        max_stage = st.number_input(
            "Max Reminder Stage (0 = unlimited)",
            min_value=0, value=comm.get("max_reminder_stage", 0),
            key="comm_max_stage",
        )
        if max_stage != comm.get("max_reminder_stage", 0):
            changed = True

        # --- File Patterns ---
        st.header("File Patterns")
        file_patterns = config.get("file_patterns", {})
        edited_patterns = {}
        for key, val in file_patterns.items():
            new_val = st.text_input(f"{key} pattern", val, key=f"fp_{key}")
            edited_patterns[key] = new_val
            if new_val != val:
                changed = True

        # --- Comms Schedule ---
        st.header("Weekly Communication Schedule")
        comms_schedule = config.get("comms_schedule", {})
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
            actions = comms_schedule.get(day, [])
            st.markdown(f"**{day.capitalize()}:** {', '.join(actions) if actions else '—'}")

        # Save
        if changed:
            st.warning("You have unsaved changes.")
            if st.button("Save Configuration", type="primary"):
                # Update config dict
                for key, val in edited_links.items():
                    config["action_links"][key] = val
                config.setdefault("communication", {})["max_reminder_stage"] = max_stage
                for key, val in edited_patterns.items():
                    config.setdefault("file_patterns", {})[key] = val

                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
                st.success("Configuration saved!")
                st.rerun()

    with tab_raw:
        st.markdown("Edit the raw YAML directly. Be careful with indentation.")
        edited_yaml = st.text_area("config.yaml", raw_yaml, height=600, key="raw_yaml_editor")

        col_save, col_validate = st.columns([1, 4])
        with col_save:
            if st.button("Save Raw YAML", type="primary"):
                try:
                    yaml.safe_load(edited_yaml)  # Validate
                    with open(config_path, "w", encoding="utf-8") as f:
                        f.write(edited_yaml)
                    st.success("Configuration saved!")
                    st.rerun()
                except yaml.YAMLError as e:
                    st.error(f"Invalid YAML: {e}")
        with col_validate:
            if st.button("Validate Only"):
                try:
                    yaml.safe_load(edited_yaml)
                    st.success("YAML is valid.")
                except yaml.YAMLError as e:
                    st.error(f"Invalid YAML: {e}")


# ===========================================================================
# PAGE: Simulation
# ===========================================================================
elif page == "Simulation":
    st.title("Simulation Runner")
    st.markdown(
        "Generate synthetic test data and run multi-cycle simulations to test "
        "the system or demo its capabilities."
    )

    config = get_config()
    sim_dir = os.path.join(PROJECT_ROOT, "data", "simulation")

    # Check existing simulation data
    existing_cycles = []
    if os.path.exists(sim_dir):
        existing_cycles = sorted(
            [d for d in os.listdir(sim_dir) if d.startswith("cycle_") and os.path.isdir(os.path.join(sim_dir, d))]
        )

    st.header("1. Generate Test Data")
    if existing_cycles:
        st.success(f"Simulation data exists: **{len(existing_cycles)} cycles** in `data/simulation/`")
        for cycle_dir in existing_cycles:
            cycle_path = os.path.join(sim_dir, cycle_dir)
            files = [f for f in os.listdir(cycle_path) if f.endswith(".xlsx")]
            st.caption(f"  {cycle_dir}: {len(files)} files — {', '.join(files[:3])}{'...' if len(files) > 3 else ''}")
    else:
        st.info("No simulation data found.")

    col_gen, col_clear = st.columns([1, 1])
    with col_gen:
        if st.button("Generate Test Data", type="primary"):
            with st.spinner("Generating synthetic test data..."):
                original_dir = os.getcwd()
                os.chdir(PROJECT_ROOT)
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, "generate_test_data.py"],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0:
                        st.success("Test data generated successfully!")
                        st.code(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
                    else:
                        st.error(f"Generation failed:\n{result.stderr}")
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.chdir(original_dir)
            st.rerun()

    with col_clear:
        if existing_cycles and st.button("Clear Simulation Data"):
            import shutil as shutil_mod
            shutil_mod.rmtree(sim_dir, ignore_errors=True)
            st.success("Simulation data cleared.")
            st.rerun()

    # --- Run Simulation ---
    st.header("2. Run Simulation")
    if not existing_cycles:
        st.info("Generate test data first before running simulation.")
    else:
        st.markdown(
            f"Run the full multi-cycle simulation ({len(existing_cycles)} cycles). "
            "This resets the database and processes each cycle sequentially."
        )
        st.warning("This will **reset the database** and all existing cycle data.")

        if st.button("Run Full Simulation", type="primary"):
            with st.spinner("Running simulation..."):
                original_dir = os.getcwd()
                os.chdir(PROJECT_ROOT)
                try:
                    import subprocess
                    result = subprocess.run(
                        [sys.executable, "run_simulation.py"],
                        capture_output=True, text=True, timeout=600,
                    )
                    if result.returncode == 0:
                        st.success("Simulation completed!")
                        st.code(result.stdout[-3000:] if len(result.stdout) > 3000 else result.stdout)
                    else:
                        st.error(f"Simulation failed:\n{result.stderr[-2000:]}")
                        if result.stdout:
                            st.code(result.stdout[-2000:])
                except subprocess.TimeoutExpired:
                    st.error("Simulation timed out (10 minute limit).")
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.chdir(original_dir)

        # Run individual cycle
        st.subheader("Or Run a Single Simulation Cycle")
        cycle_nums = [int(d.replace("cycle_", "")) for d in existing_cycles]
        selected_cycle_num = st.selectbox("Select Cycle", cycle_nums, format_func=lambda x: f"Cycle {x}")
        if st.button(f"Run Cycle {selected_cycle_num} Only"):
            with st.spinner(f"Running cycle {selected_cycle_num}..."):
                original_dir = os.getcwd()
                os.chdir(PROJECT_ROOT)
                try:
                    from run_simulation import clear_input_folder, copy_cycle_files
                    from main import run_cycle

                    clear_input_folder(config)
                    copy_cycle_files(selected_cycle_num, config)
                    summary = run_cycle("config.yaml")

                    if summary:
                        st.success(f"Cycle {selected_cycle_num} completed!")
                        summary_df = pd.DataFrame(
                            [{"Metric": k.replace("_", " ").title(), "Value": v} for k, v in summary.items()]
                        )
                        st.dataframe(summary_df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("Cycle was reverted due to input validation error.")
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.chdir(original_dir)


# ===========================================================================
# PAGE: Log Viewer
# ===========================================================================
elif page == "Log Viewer":
    st.title("Log Viewer")
    st.markdown("Browse application logs from processing cycles.")

    config = get_config()
    log_dir = os.path.join(PROJECT_ROOT, config["paths"].get("log_folder", "logs"))

    if not os.path.exists(log_dir):
        st.info("No log directory found.")
    else:
        log_files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(".log")],
            reverse=True,
        )
        if not log_files:
            st.info("No log files found.")
        else:
            st.write(f"**{len(log_files)} log files** in `{config['paths'].get('log_folder', 'logs')}/`")

            selected_log = st.selectbox("Select Log File", log_files)
            log_path = os.path.join(log_dir, selected_log)

            # File size
            file_size = os.path.getsize(log_path)
            st.caption(f"Size: {file_size:,} bytes")

            # Read log content
            with open(log_path, "r", encoding="utf-8") as f:
                log_content = f.read()

            log_lines = log_content.split("\n")

            # Filters
            col_level, col_search = st.columns(2)
            with col_level:
                level_filter = st.multiselect(
                    "Filter by Level",
                    ["INFO", "WARNING", "ERROR", "DEBUG"],
                    default=[],
                )
            with col_search:
                search_text = st.text_input("Search in logs", "")

            if level_filter or search_text:
                filtered_lines = []
                for line in log_lines:
                    if level_filter:
                        if not any(f"[{level}]" in line for level in level_filter):
                            continue
                    if search_text:
                        if search_text.lower() not in line.lower():
                            continue
                    filtered_lines.append(line)
                display_lines = filtered_lines
                st.write(f"**{len(display_lines)}** matching lines (of {len(log_lines)} total)")
            else:
                display_lines = log_lines

            # Show last N lines option
            max_lines = st.selectbox("Show lines", [50, 100, 250, 500, 1000], index=1)
            if len(display_lines) > max_lines:
                st.caption(f"Showing last {max_lines} of {len(display_lines)} lines")
                display_lines = display_lines[-max_lines:]

            # Color-code by level
            log_text = "\n".join(display_lines)
            st.code(log_text, language="log")

            # Error summary
            errors = [l for l in log_lines if "[ERROR]" in l]
            warnings = [l for l in log_lines if "[WARNING]" in l]
            if errors or warnings:
                st.subheader("Issues Summary")
                if errors:
                    with st.expander(f"Errors ({len(errors)})", expanded=True):
                        for e in errors:
                            st.markdown(f"``{e.strip()}``")
                if warnings:
                    with st.expander(f"Warnings ({len(warnings)})"):
                        for w in warnings[:50]:
                            st.markdown(f"``{w.strip()}``")
                        if len(warnings) > 50:
                            st.caption(f"... and {len(warnings) - 50} more warnings")

            # Download
            st.download_button(
                "Download Log File",
                log_content,
                file_name=selected_log,
                mime="text/plain",
            )


# ===========================================================================
# PAGE: Archive Browser
# ===========================================================================
elif page == "Archive Browser":
    st.title("Archive Browser")
    st.markdown("Browse archived input files from past processing cycles.")

    config = get_config()
    archive_dir = os.path.join(PROJECT_ROOT, config["paths"].get("archive_folder", "data/archive"))
    conn = get_db_connection(config)

    if not os.path.exists(archive_dir):
        st.info("No archive directory found.")
    else:
        # List archive folders/files
        archive_items = sorted(os.listdir(archive_dir), reverse=True)
        if not archive_items:
            st.info("Archive is empty. Files are archived after each cycle run.")
        else:
            # Show database records if available
            if conn:
                try:
                    processed_df = pd.read_sql_query(
                        """SELECT pf.cycle_id, c.cycle_timestamp, pf.file_type,
                                  pf.original_filename, pf.archived_filename,
                                  pf.archive_path, pf.checksum, pf.processed_at
                           FROM processed_files pf
                           JOIN cycles c ON pf.cycle_id = c.id
                           ORDER BY pf.cycle_id DESC, pf.file_type""",
                        conn,
                    )
                    if not processed_df.empty:
                        st.header("Processed Files Registry")
                        st.write(f"**{len(processed_df)} archived files** across {processed_df['cycle_id'].nunique()} cycles")

                        # Group by cycle
                        for cycle_id in sorted(processed_df["cycle_id"].unique(), reverse=True):
                            cycle_files = processed_df[processed_df["cycle_id"] == cycle_id]
                            cycle_ts = cycle_files.iloc[0]["cycle_timestamp"][:10]
                            with st.expander(f"Cycle {cycle_id} — {cycle_ts} ({len(cycle_files)} files)"):
                                st.dataframe(
                                    cycle_files[["file_type", "original_filename", "archived_filename", "checksum", "processed_at"]],
                                    use_container_width=True, hide_index=True,
                                )
                finally:
                    conn.close()

            # Browse actual files on disk
            st.header("Archive Files on Disk")

            # Detect structure: could be flat files or date-based subfolders
            folders = [d for d in archive_items if os.path.isdir(os.path.join(archive_dir, d))]
            files = [f for f in archive_items if os.path.isfile(os.path.join(archive_dir, f))]

            if folders:
                selected_folder = st.selectbox("Select Archive Folder", folders)
                folder_path = os.path.join(archive_dir, selected_folder)
                folder_files = sorted(os.listdir(folder_path))
                st.write(f"**{len(folder_files)} files** in `{selected_folder}/`")
                for f in folder_files:
                    fpath = os.path.join(folder_path, f)
                    fsize = os.path.getsize(fpath)
                    st.markdown(f"- `{f}` ({fsize:,} bytes)")

            if files:
                st.subheader("Archived Files")
                for f in files:
                    fpath = os.path.join(archive_dir, f)
                    fsize = os.path.getsize(fpath)
                    st.markdown(f"- `{f}` ({fsize:,} bytes)")

            # Total archive size
            total_size = 0
            for root, _dirs, flist in os.walk(archive_dir):
                for f in flist:
                    total_size += os.path.getsize(os.path.join(root, f))
            st.caption(f"Total archive size: {total_size / 1024:.1f} KB")
