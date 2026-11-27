#!/usr/bin/env python3
"""
scheduler.py - Background Inbox Auto-Poller & Day 3 / Day 7 Threaded Follow-Up Queue Generator.
- Silently checks the active mail provider on a configurable interval (default 15 min) for new
  interview replies & Thunderbird Sent confirmations.
- Automatically queues polite, 2-sentence same-thread follow-ups (In-Reply-To) into Outbox Pending
  for unanswered cold outreach after Day 3 and Day 7 so zero warm leads go cold.
Licensed under GNU GPL v3.0.
"""

import json
import threading
import time
from datetime import datetime, timedelta

from employmaxing.mail_oauth import load_active_mail_config
from employmaxing.mailbox import queue_outbound_email, scan_inbox
from employmaxing.store import EmploymaxingStore


def _parse_ts(ts_str: str) -> datetime | None:
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts_str[:19], fmt)
        except Exception:
            continue
    return None


def generate_due_followups(store: EmploymaxingStore, day_touch_2: int = 3, day_touch_3: int = 7) -> dict:
    """
    Scan sent outreach threads and auto-queue crisp, 2-sentence same-thread follow-ups
    into `pending_approval` when no reply has arrived after Day 3 or Day 7.
    """
    all_emails = store.list_emails()
    inbound = [e for e in all_emails if e["direction"] == "inbound_reply"]
    sent_primary = [
        e for e in all_emails
        if e["direction"] == "outbound_sent"
        and e["status"] == "sent"
        and e.get("classification", "") in {"outreach_touch_1", "general", "referral"}
    ]

    replied_senders = {
        (e.get("sender_email") or "").lower()
        for e in inbound
    }
    replied_in_reply = {e.get("in_reply_to") for e in inbound if e.get("in_reply_to")}

    # Track existing follow-ups by (recipient_email, classification) so we never double-queue
    existing_followups = {
        ((e.get("recipient_email") or "").lower(), e.get("classification", ""))
        for e in all_emails
        if "followup" in (e.get("classification") or "")
    }

    now = datetime.now()
    queued = []

    for orig in sent_primary:
        rcpt = (orig.get("recipient_email") or "").strip().lower()
        if not rcpt:
            continue
        # Skip if recipient already replied
        if any(rcpt in s for s in replied_senders) or (orig.get("message_id") and orig["message_id"] in replied_in_reply):
            continue

        sent_dt = _parse_ts(orig.get("sent_or_received_at", ""))
        if not sent_dt:
            continue
        age_days = (now - sent_dt).total_seconds() / 86400.0
        first_name = (orig.get("recipient_name") or "").split()[0] or "there"
        subj = orig.get("subject", "")
        re_subj = subj if subj.lower().startswith("re:") else f"Re: {subj}"

        if age_days >= day_touch_3 and (rcpt, "outreach_followup_day7") not in existing_followups:
            body = (
                f"Hi {first_name},\n\n"
                f"Closing the loop on my note below — totally understand if your team's priorities shifted this sprint.\n\n"
                f"Happy to reconnect anytime if scaling reliability or delivery speed pops back up on your roadmap?"
            )
            res = queue_outbound_email(
                store,
                recipient_email=rcpt,
                recipient_name=orig.get("recipient_name", ""),
                subject=re_subj,
                body=body,
                job_id=orig.get("job_id", ""),
                classification="outreach_followup_day7",
                facts_used=orig.get("facts_used", []),
                in_reply_to=orig.get("message_id", ""),
                auto_approve=False,
            )
            queued.append({"email_id": res["email_id"], "to": rcpt, "touch": "day7", "score": res["mail_score"]})
            existing_followups.add((rcpt, "outreach_followup_day7"))

        elif age_days >= day_touch_2 and (rcpt, "outreach_followup_day3") not in existing_followups:
            body = (
                f"Hi {first_name},\n\n"
                f"Quick bump in case my note below got buried in inbox traffic.\n\n"
                f"Still happy to share that brief 3-bullet breakdown if it's helpful for your team this quarter?"
            )
            res = queue_outbound_email(
                store,
                recipient_email=rcpt,
                recipient_name=orig.get("recipient_name", ""),
                subject=re_subj,
                body=body,
                job_id=orig.get("job_id", ""),
                classification="outreach_followup_day3",
                facts_used=orig.get("facts_used", []),
                in_reply_to=orig.get("message_id", ""),
                auto_approve=False,
            )
            queued.append({"email_id": res["email_id"], "to": rcpt, "touch": "day3", "score": res["mail_score"]})
            existing_followups.add((rcpt, "outreach_followup_day3"))

    if queued:
        store.log_event("followups_queued", f"Auto-drafted {len(queued)} Day 3/Day 7 threaded follow-up(s) into Outbox Pending")
    return {"checked": len(sent_primary), "queued_followups": queued}


class BackgroundAutomation:
    """Lightweight daemon thread inside server.py for periodic inbox polling & follow-up drafting."""

    def __init__(self, store: EmploymaxingStore):
        self.store = store
        self.cfg_path = store.data_dir / "automation-config.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run_at = ""
        self.last_result: dict = {}

    def get_config(self) -> dict:
        cfg = {"enabled": True, "interval_minutes": 15, "auto_followup_drafts": True}
        if self.cfg_path.exists():
            try:
                cfg.update(json.loads(self.cfg_path.read_text(encoding="utf-8")))
            except Exception:
                pass
        cfg["last_run_at"] = self.last_run_at
        cfg["last_result"] = self.last_result
        return cfg

    def save_config(self, updates: dict) -> dict:
        cfg = self.get_config()
        for k in ("enabled", "interval_minutes", "auto_followup_drafts"):
            if k in updates:
                cfg[k] = updates[k]
        clean = {
            "enabled": bool(cfg["enabled"]),
            "interval_minutes": max(2, int(cfg["interval_minutes"])),
            "auto_followup_drafts": bool(cfg["auto_followup_drafts"]),
        }
        self.cfg_path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
        return self.get_config()

    def run_once(self) -> dict:
        res = {"inbox": None, "followups": None}
        cfg = self.get_config()
        try:
            if load_active_mail_config(self.store).get("provider"):
                res["inbox"] = scan_inbox(self.store, days=7, limit=30)
        except Exception as ex:
            res["inbox"] = {"error": str(ex)}
        if cfg.get("auto_followup_drafts", True):
            try:
                res["followups"] = generate_due_followups(self.store)
            except Exception as ex:
                res["followups"] = {"error": str(ex)}
        self.last_run_at = self.store._now()
        self.last_result = res
        return res

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        # Small initial delay so server boots instantaneously
        self._stop.wait(10.0)
        while not self._stop.is_set():
            cfg = self.get_config()
            if cfg.get("enabled"):
                self.run_once()
            self._stop.wait(max(120.0, float(cfg.get("interval_minutes", 15)) * 60.0))

    def stop(self):
        self._stop.set()
