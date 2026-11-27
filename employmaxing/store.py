#!/usr/bin/env python3
"""
store.py - Unified SQLite + Markdown state store for Employmaxing.
Maintains the Transparent Information & Consent Ledger, Jobs/Applications,
Mailbox (Inbox Replies + Outbox Queue + Sent Log), Form Fill Plans, and Audit Events.
Licensed under GNU GPL v3.0.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DEFAULT_DATA_DIR = Path.home() / ".employmaxing"
LEGACY_DATA_DIR = Path.home() / ".proficiently"


def resolve_data_dir(custom_dir: str | Path | None = None) -> Path:
    if custom_dir:
        d = Path(custom_dir).expanduser().resolve()
    elif os.environ.get("EMPLOYMAXING_DATA_DIR"):
        d = Path(os.environ["EMPLOYMAXING_DATA_DIR"]).expanduser().resolve()
    elif (Path.cwd() / ".employmaxing").exists():
        d = (Path.cwd() / ".employmaxing").resolve()
    else:
        d = DEFAULT_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    for sub in ("resume", "jobs", "screenshots", "exports"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


class EmploymaxingStore:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = resolve_data_dir(data_dir)
        self.db_path = self.data_dir / "employmaxing.db"
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_url TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    consent_status TEXT NOT NULL DEFAULT 'pending_review',
                    planned_usage TEXT NOT NULL DEFAULT 'resume,outreach_mail,form_fill',
                    user_note TEXT DEFAULT '',
                    discovered_at TEXT NOT NULL,
                    reviewed_at TEXT DEFAULT ''
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique
                    ON profile_facts(category, fact_key, source);

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    company TEXT NOT NULL,
                    role TEXT NOT NULL,
                    url TEXT DEFAULT '',
                    ats_type TEXT DEFAULT 'unknown',
                    location TEXT DEFAULT '',
                    salary_band TEXT DEFAULT '',
                    days_old INTEGER,
                    fit_rating TEXT DEFAULT 'Unscored',
                    ghost_risk TEXT DEFAULT 'UNKNOWN',
                    ghost_score INTEGER DEFAULT 0,
                    priority_tier TEXT DEFAULT 'P2',
                    stage TEXT NOT NULL DEFAULT 'Discovered',
                    resume_score INTEGER,
                    has_referral INTEGER DEFAULT 0,
                    network_contacts TEXT DEFAULT '[]',
                    folder_path TEXT DEFAULT '',
                    next_followup TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL,
                    job_id TEXT DEFAULT '',
                    recipient_name TEXT DEFAULT '',
                    recipient_email TEXT DEFAULT '',
                    sender_email TEXT DEFAULT '',
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    thread_id TEXT DEFAULT '',
                    message_id TEXT DEFAULT '',
                    in_reply_to TEXT DEFAULT '',
                    classification TEXT DEFAULT 'general',
                    mail_score INTEGER,
                    mx_gateway TEXT DEFAULT '',
                    facts_used TEXT DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending_approval',
                    scheduled_at TEXT DEFAULT '',
                    sent_or_received_at TEXT NOT NULL,
                    error_msg TEXT DEFAULT ''
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_emails_msgid
                    ON emails(message_id) WHERE message_id != '';

                CREATE TABLE IF NOT EXISTS form_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    ats_type TEXT NOT NULL,
                    form_url TEXT NOT NULL,
                    field_plan TEXT NOT NULL DEFAULT '[]',
                    files_attached TEXT NOT NULL DEFAULT '[]',
                    knockout_warnings TEXT NOT NULL DEFAULT '[]',
                    facts_used TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'awaiting_approval',
                    screenshot_path TEXT DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    details TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log_event(self, event_type: str, summary: str, details: dict | None = None):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO audit_events (event_type, summary, details, created_at) VALUES (?, ?, ?, ?)",
                (event_type, summary, json.dumps(details or {}), self._now()),
            )

    # ---------- Profile Facts & Transparent Consent Ledger ----------
    def upsert_fact(
        self,
        category: str,
        fact_key: str,
        fact_value: str,
        source: str,
        source_url: str = "",
        confidence: float = 1.0,
        consent_status: str = "pending_review",
        planned_usage: str = "resume,outreach_mail,form_fill",
    ) -> int:
        now = self._now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO profile_facts
                    (category, fact_key, fact_value, source, source_url, confidence, consent_status, planned_usage, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category, fact_key, source) DO UPDATE SET
                    fact_value = excluded.fact_value,
                    source_url = excluded.source_url,
                    confidence = excluded.confidence,
                    planned_usage = excluded.planned_usage
                """,
                (category, fact_key, fact_value, source, source_url, confidence, consent_status, planned_usage, now),
            )
            row = conn.execute(
                "SELECT id FROM profile_facts WHERE category=? AND fact_key=? AND source=?",
                (category, fact_key, source),
            ).fetchone()
            return int(row["id"])

    def list_facts(self, consent_status: str | None = None, category: str | None = None) -> list[dict]:
        q = "SELECT * FROM profile_facts WHERE 1=1"
        params: list = []
        if consent_status:
            q += " AND consent_status = ?"
            params.append(consent_status)
        if category:
            q += " AND category = ?"
            params.append(category)
        q += " ORDER BY CASE consent_status WHEN 'pending_review' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, category, id"
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def set_fact_consent(self, fact_id: int, status: str, edited_value: str | None = None, user_note: str | None = None) -> bool:
        if status not in {"pending_review", "approved", "rejected", "redacted"}:
            raise ValueError(f"Invalid consent_status: {status}")
        now = self._now()
        with self._conn() as conn:
            if edited_value is not None:
                cur = conn.execute(
                    "UPDATE profile_facts SET consent_status=?, fact_value=?, user_note=COALESCE(?, user_note), reviewed_at=? WHERE id=?",
                    (status, edited_value, user_note, now, fact_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE profile_facts SET consent_status=?, user_note=COALESCE(?, user_note), reviewed_at=? WHERE id=?",
                    (status, user_note, now, fact_id),
                )
            ok = cur.rowcount > 0
        if ok:
            self.log_event("fact_consent_updated", f"Fact #{fact_id} marked '{status}'", {"fact_id": fact_id, "status": status})
        return ok

    def approve_all_pending_facts(self, source_filter: str | None = None) -> int:
        now = self._now()
        with self._conn() as conn:
            if source_filter:
                cur = conn.execute(
                    "UPDATE profile_facts SET consent_status='approved', reviewed_at=? WHERE consent_status='pending_review' AND source=?",
                    (now, source_filter),
                )
            else:
                cur = conn.execute(
                    "UPDATE profile_facts SET consent_status='approved', reviewed_at=? WHERE consent_status='pending_review'",
                    (now,),
                )
            count = cur.rowcount
        if count:
            self.log_event("facts_bulk_approved", f"Approved {count} pending facts", {"source_filter": source_filter})
        return count

    # ---------- Jobs & Custom Applications ----------
    def upsert_job(self, job: dict) -> str:
        now = self._now()
        job_id = job["id"]
        with self._conn() as conn:
            existing = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE jobs SET
                        company=COALESCE(?, company),
                        role=COALESCE(?, role),
                        url=COALESCE(?, url),
                        ats_type=COALESCE(?, ats_type),
                        location=COALESCE(?, location),
                        salary_band=COALESCE(?, salary_band),
                        days_old=COALESCE(?, days_old),
                        fit_rating=COALESCE(?, fit_rating),
                        ghost_risk=COALESCE(?, ghost_risk),
                        ghost_score=COALESCE(?, ghost_score),
                        priority_tier=COALESCE(?, priority_tier),
                        stage=COALESCE(?, stage),
                        resume_score=COALESCE(?, resume_score),
                        has_referral=COALESCE(?, has_referral),
                        network_contacts=COALESCE(?, network_contacts),
                        folder_path=COALESCE(?, folder_path),
                        next_followup=COALESCE(?, next_followup),
                        notes=COALESCE(?, notes),
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        job.get("company"), job.get("role"), job.get("url"), job.get("ats_type"),
                        job.get("location"), job.get("salary_band"), job.get("days_old"),
                        job.get("fit_rating"), job.get("ghost_risk"), job.get("ghost_score"),
                        job.get("priority_tier"), job.get("stage"), job.get("resume_score"),
                        job.get("has_referral"),
                        json.dumps(job["network_contacts"]) if isinstance(job.get("network_contacts"), list) else job.get("network_contacts"),
                        job.get("folder_path"), job.get("next_followup"), job.get("notes"), now, job_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, company, role, url, ats_type, location, salary_band, days_old,
                        fit_rating, ghost_risk, ghost_score, priority_tier, stage, resume_score,
                        has_referral, network_contacts, folder_path, next_followup, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id, job.get("company", "Unknown"), job.get("role", "Unknown"),
                        job.get("url", ""), job.get("ats_type", "unknown"), job.get("location", ""),
                        job.get("salary_band", ""), job.get("days_old"), job.get("fit_rating", "Unscored"),
                        job.get("ghost_risk", "UNKNOWN"), job.get("ghost_score", 0),
                        job.get("priority_tier", "P2"), job.get("stage", "Discovered"),
                        job.get("resume_score"), int(bool(job.get("has_referral", False))),
                        json.dumps(job.get("network_contacts", [])),
                        job.get("folder_path", str(self.data_dir / "jobs" / job_id)),
                        job.get("next_followup", ""), job.get("notes", ""), now, now,
                    ),
                )
        return job_id

    def list_jobs(self, stage: str | None = None) -> list[dict]:
        q = "SELECT * FROM jobs"
        params: list = []
        if stage:
            q += " WHERE stage = ?"
            params.append(stage)
        q += " ORDER BY updated_at DESC"
        with self._conn() as conn:
            rows = []
            for r in conn.execute(q, params).fetchall():
                d = dict(r)
                try:
                    d["network_contacts"] = json.loads(d["network_contacts"] or "[]")
                except Exception:
                    d["network_contacts"] = []
                rows.append(d)
            return rows

    def get_job(self, job_id: str) -> dict | None:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not r:
                return None
            d = dict(r)
            try:
                d["network_contacts"] = json.loads(d["network_contacts"] or "[]")
            except Exception:
                d["network_contacts"] = []
            return d

    # ---------- Mailbox (Inbox Replies, Outbox Queue, Sent Log) ----------
    def record_email(self, email_data: dict) -> int:
        now = self._now()
        with self._conn() as conn:
            msg_id = email_data.get("message_id", "")
            if msg_id:
                existing = conn.execute("SELECT id FROM emails WHERE message_id=?", (msg_id,)).fetchone()
                if existing:
                    return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO emails (
                    direction, job_id, recipient_name, recipient_email, sender_email,
                    subject, body, thread_id, message_id, in_reply_to, classification,
                    mail_score, mx_gateway, facts_used, status, scheduled_at, sent_or_received_at, error_msg
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_data.get("direction", "outbound_draft"),
                    email_data.get("job_id", ""),
                    email_data.get("recipient_name", ""),
                    email_data.get("recipient_email", ""),
                    email_data.get("sender_email", ""),
                    email_data.get("subject", "(No Subject)"),
                    email_data.get("body", ""),
                    email_data.get("thread_id", ""),
                    msg_id,
                    email_data.get("in_reply_to", ""),
                    email_data.get("classification", "general"),
                    email_data.get("mail_score"),
                    email_data.get("mx_gateway", ""),
                    json.dumps(email_data.get("facts_used", [])),
                    email_data.get("status", "pending_approval"),
                    email_data.get("scheduled_at", ""),
                    email_data.get("sent_or_received_at", now),
                    email_data.get("error_msg", ""),
                ),
            )
            return int(cur.lastrowid)

    def list_emails(self, direction: str | None = None, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM emails WHERE 1=1"
        params: list = []
        if direction:
            q += " AND direction = ?"
            params.append(direction)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY id DESC"
        with self._conn() as conn:
            rows = []
            for r in conn.execute(q, params).fetchall():
                d = dict(r)
                try:
                    d["facts_used"] = json.loads(d["facts_used"] or "[]")
                except Exception:
                    d["facts_used"] = []
                rows.append(d)
            return rows

    def update_email(self, email_id: int, **fields) -> bool:
        if not fields:
            return False
        cols = []
        vals = []
        for k, v in fields.items():
            if k in {"status", "direction", "subject", "body", "message_id", "error_msg", "classification", "sent_or_received_at", "mail_score"}:
                cols.append(f"{k}=?")
                vals.append(v)
        if not cols:
            return False
        vals.append(email_id)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE emails SET {', '.join(cols)} WHERE id=?", vals)
            return cur.rowcount > 0

    # ---------- Form Submissions ----------
    def save_form_submission(self, plan: dict) -> int:
        now = self._now()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO form_submissions
                    (job_id, ats_type, form_url, field_plan, files_attached, knockout_warnings, facts_used, status, screenshot_path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan["job_id"],
                    plan.get("ats_type", "unknown"),
                    plan.get("form_url", ""),
                    json.dumps(plan.get("field_plan", [])),
                    json.dumps(plan.get("files_attached", [])),
                    json.dumps(plan.get("knockout_warnings", [])),
                    json.dumps(plan.get("facts_used", [])),
                    plan.get("status", "awaiting_approval"),
                    plan.get("screenshot_path", ""),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def list_form_submissions(self, job_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM form_submissions"
        params: list = []
        if job_id:
            q += " WHERE job_id = ?"
            params.append(job_id)
        q += " ORDER BY id DESC"
        with self._conn() as conn:
            rows = []
            for r in conn.execute(q, params).fetchall():
                d = dict(r)
                for col in ("field_plan", "files_attached", "knockout_warnings", "facts_used"):
                    try:
                        d[col] = json.loads(d[col] or "[]")
                    except Exception:
                        d[col] = []
                rows.append(d)
            return rows

    def update_form_status(self, sub_id: int, status: str, field_plan: list | None = None, screenshot_path: str | None = None) -> bool:
        now = self._now()
        with self._conn() as conn:
            if field_plan is not None:
                cur = conn.execute(
                    "UPDATE form_submissions SET status=?, field_plan=?, screenshot_path=COALESCE(?, screenshot_path), updated_at=? WHERE id=?",
                    (status, json.dumps(field_plan), screenshot_path, now, sub_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE form_submissions SET status=?, screenshot_path=COALESCE(?, screenshot_path), updated_at=? WHERE id=?",
                    (status, screenshot_path, now, sub_id),
                )
            return cur.rowcount > 0

    # ---------- Dashboard Summary ----------
    def get_dashboard_summary(self) -> dict:
        facts = self.list_facts()
        jobs = self.list_jobs()
        emails = self.list_emails()
        forms = self.list_form_submissions()
        with self._conn() as conn:
            events = [dict(r) for r in conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 30").fetchall()]
        return {
            "data_dir": str(self.data_dir),
            "counts": {
                "facts_total": len(facts),
                "facts_pending_consent": sum(1 for f in facts if f["consent_status"] == "pending_review"),
                "facts_approved": sum(1 for f in facts if f["consent_status"] == "approved"),
                "jobs_total": len(jobs),
                "jobs_applied": sum(1 for j in jobs if j["stage"] not in {"Discovered", "Saved", "Tailored"}),
                "jobs_interviews": sum(1 for j in jobs if j["stage"] in {"Phone Screen", "Technical", "Onsite / Final"}),
                "jobs_offers": sum(1 for j in jobs if j["stage"] in {"Offer", "Accepted"}),
                "emails_sent": sum(1 for e in emails if e["direction"] == "outbound_sent" and e["status"] == "sent"),
                "emails_pending_approval": sum(1 for e in emails if e["status"] == "pending_approval"),
                "inbox_replies": sum(1 for e in emails if e["direction"] == "inbound_reply"),
                "interview_invites": sum(1 for e in emails if e["direction"] == "inbound_reply" and e["classification"] in {"interview_invite", "recruiter_screen", "assessment", "offer"}),
                "forms_pending": sum(1 for fm in forms if fm["status"] in {"awaiting_approval", "filled_pending_submit"}),
            },
            "recent_events": events,
        }
