import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_timestamp TEXT NOT NULL,
    run_status TEXT DEFAULT 'running',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS project_managers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT,
    normalized_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    project_manager_id INTEGER NOT NULL,
    project_name TEXT,
    project_id TEXT,
    assignment_status TEXT,
    source_file TEXT,
    snapshot_timestamp TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id),
    FOREIGN KEY (project_manager_id) REFERENCES project_managers(id)
);

CREATE TABLE IF NOT EXISTS training_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    project_manager_id INTEGER NOT NULL,
    fundamentals_status TEXT,
    advanced_status TEXT,
    fundamentals_date TEXT,
    advanced_date TEXT,
    overall_training_status TEXT,
    source_file TEXT,
    snapshot_timestamp TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id),
    FOREIGN KEY (project_manager_id) REFERENCES project_managers(id)
);

CREATE TABLE IF NOT EXISTS communication_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    project_manager_id INTEGER NOT NULL,
    reminder_stage INTEGER NOT NULL,
    email_subject TEXT,
    email_body TEXT,
    communication_status TEXT DEFAULT 'prepared',
    created_at TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id),
    FOREIGN KEY (project_manager_id) REFERENCES project_managers(id)
);

CREATE TABLE IF NOT EXISTS processed_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    file_type TEXT,
    original_filename TEXT,
    archived_filename TEXT,
    archive_path TEXT,
    processed_at TEXT NOT NULL,
    checksum TEXT,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id)
);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id INTEGER NOT NULL,
    issue_type TEXT NOT NULL,
    person_name TEXT,
    email TEXT,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES cycles(id)
);
"""


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
        logger.info("Database initialized at %s", db_path)

    def _create_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Cycle management ---

    def start_cycle(self, notes=None):
        now = datetime.now().isoformat()
        cursor = self.conn.execute(
            "INSERT INTO cycles (cycle_timestamp, run_status, notes) VALUES (?, 'running', ?)",
            (now, notes),
        )
        self.conn.commit()
        cycle_id = cursor.lastrowid
        logger.info("Started cycle %d", cycle_id)
        return cycle_id

    def complete_cycle(self, cycle_id, status="completed", notes=None):
        self.conn.execute(
            "UPDATE cycles SET run_status = ?, notes = ? WHERE id = ?",
            (status, notes, cycle_id),
        )
        self.conn.commit()
        logger.info("Cycle %d marked as %s", cycle_id, status)

    # --- Project managers ---

    def upsert_project_manager(self, full_name, email, normalized_name):
        now = datetime.now().isoformat()
        # Try to find existing by email first, then by normalized name
        row = None
        if email:
            row = self.conn.execute(
                "SELECT id FROM project_managers WHERE email = ?",
                (email.lower().strip(),),
            ).fetchone()
        if not row and normalized_name:
            row = self.conn.execute(
                "SELECT id FROM project_managers WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()

        if row:
            pm_id = row["id"]
            self.conn.execute(
                "UPDATE project_managers SET full_name = ?, email = ?, normalized_name = ?, updated_at = ? WHERE id = ?",
                (full_name, email.lower().strip() if email else None, normalized_name, now, pm_id),
            )
        else:
            cursor = self.conn.execute(
                "INSERT INTO project_managers (full_name, email, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (full_name, email.lower().strip() if email else None, normalized_name, now, now),
            )
            pm_id = cursor.lastrowid

        self.conn.commit()
        return pm_id

    def get_project_manager_id(self, email=None, normalized_name=None):
        if email:
            row = self.conn.execute(
                "SELECT id FROM project_managers WHERE email = ?",
                (email.lower().strip(),),
            ).fetchone()
            if row:
                return row["id"]
        if normalized_name:
            row = self.conn.execute(
                "SELECT id FROM project_managers WHERE normalized_name = ?",
                (normalized_name,),
            ).fetchone()
            if row:
                return row["id"]
        return None

    # --- Snapshots ---

    def insert_assignment_snapshot(self, cycle_id, pm_id, project_name, project_id, status, source_file):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO assignment_snapshots
               (cycle_id, project_manager_id, project_name, project_id, assignment_status, source_file, snapshot_timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cycle_id, pm_id, project_name, project_id, status, source_file, now),
        )
        self.conn.commit()

    def insert_training_snapshot(self, cycle_id, pm_id, fund_status, adv_status, fund_date, adv_date, overall, source_file):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO training_snapshots
               (cycle_id, project_manager_id, fundamentals_status, advanced_status,
                fundamentals_date, advanced_date, overall_training_status, source_file, snapshot_timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (cycle_id, pm_id, fund_status, adv_status, fund_date, adv_date, overall, source_file, now),
        )
        self.conn.commit()

    # --- Communication history ---

    def get_last_reminder_stage(self, pm_id):
        row = self.conn.execute(
            "SELECT MAX(reminder_stage) as max_stage FROM communication_history WHERE project_manager_id = ?",
            (pm_id,),
        ).fetchone()
        if row and row["max_stage"] is not None:
            return row["max_stage"]
        return 0

    def insert_communication(self, cycle_id, pm_id, stage, subject, body, status="prepared"):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO communication_history
               (cycle_id, project_manager_id, reminder_stage, email_subject, email_body, communication_status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cycle_id, pm_id, stage, subject, body, status, now),
        )
        self.conn.commit()

    # --- Data quality ---

    def insert_data_quality_issue(self, cycle_id, issue_type, person_name, email, details):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO data_quality_issues
               (cycle_id, issue_type, person_name, email, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cycle_id, issue_type, person_name, email, details, now),
        )
        self.conn.commit()

    # --- Processed files ---

    def record_processed_file(self, cycle_id, file_type, original, archived, archive_path, checksum=None):
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO processed_files
               (cycle_id, file_type, original_filename, archived_filename, archive_path, processed_at, checksum)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cycle_id, file_type, original, archived, archive_path, now, checksum),
        )
        self.conn.commit()

    # --- Query helpers ---

    def get_communication_summary(self, cycle_id=None):
        if cycle_id:
            return self.conn.execute(
                """SELECT pm.full_name, pm.email, ch.reminder_stage, ch.communication_status
                   FROM communication_history ch
                   JOIN project_managers pm ON ch.project_manager_id = pm.id
                   WHERE ch.cycle_id = ?
                   ORDER BY ch.reminder_stage, pm.full_name""",
                (cycle_id,),
            ).fetchall()
        return self.conn.execute(
            """SELECT pm.full_name, pm.email, ch.reminder_stage, ch.communication_status, ch.cycle_id
               FROM communication_history ch
               JOIN project_managers pm ON ch.project_manager_id = pm.id
               ORDER BY ch.cycle_id, ch.reminder_stage, pm.full_name"""
        ).fetchall()

    def get_cycle_count(self):
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM cycles").fetchone()
        return row["cnt"]
