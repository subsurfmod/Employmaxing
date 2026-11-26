#!/usr/bin/env python3
"""
mailbox.py - Transparent IMAP Reply Monitor & Automated Plain-Text SMTP Sender.
- Scans user's inbox via IMAP4_SSL for recruiter/hiring-manager replies, classifies them
  (interview_invite, recruiter_screen, assessment, offer, rejection, follow_up_needed),
  and automatically updates the Jobs pipeline in EmploymaxingStore.
- Queues & sends approved outbound emails via SMTP_SSL / STARTTLS with rate limiting,
  plain-text deliverability, In-Reply-To threading, and full Facts-Used transparency.
Licensed under GNU GPL v3.0.
"""

import argparse
import email
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SHARED_SCRIPTS = BASE_DIR / "shared" / "scripts"
for p in (str(BASE_DIR), str(SHARED_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from employmaxing.store import EmploymaxingStore
from optimizer import audit_mail, check_mx_records

PROVIDER_PRESETS = {
    "gmail": {"imap_host": "imap.gmail.com", "imap_port": 993, "smtp_host": "smtp.gmail.com", "smtp_port": 465, "smtp_ssl": True},
    "outlook": {"imap_host": "outlook.office365.com", "imap_port": 993, "smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_ssl": False},
    "fastmail": {"imap_host": "imap.fastmail.com", "imap_port": 993, "smtp_host": "smtp.fastmail.com", "smtp_port": 465, "smtp_ssl": True},
    "icloud": {"imap_host": "imap.mail.me.com", "imap_port": 993, "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_ssl": False},
}


def load_mail_config(store: EmploymaxingStore) -> dict:
    cfg_path = store.data_dir / "mail-config.json"
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # Allow secure environment variable overrides
    if os.environ.get("EMPLOYMAXING_MAIL_USER"):
        cfg["email"] = os.environ["EMPLOYMAXING_MAIL_USER"]
    if os.environ.get("EMPLOYMAXING_MAIL_PASS"):
        cfg["password"] = os.environ["EMPLOYMAXING_MAIL_PASS"]
    if os.environ.get("EMPLOYMAXING_MAIL_PROVIDER"):
        cfg["provider"] = os.environ["EMPLOYMAXING_MAIL_PROVIDER"]
    provider = cfg.get("provider", "gmail").lower()
    preset = PROVIDER_PRESETS.get(provider, {})
    for k, v in preset.items():
        cfg.setdefault(k, v)
    cfg.setdefault("daily_send_limit", 20)
    cfg.setdefault("send_delay_seconds", 4)
    return cfg


def save_mail_config(store: EmploymaxingStore, cfg: dict) -> Path:
    cfg_path = store.data_dir / "mail-config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.chmod(cfg_path, 0o600)
    return cfg_path


def _decode_hdr(raw: str | None) -> str:
    if not raw:
        return ""
    parts = []
    for chunk, enc in decode_header(raw):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts).strip()


def _extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in disp.lower():
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()
    payload = msg.get_payload(decode=True)
    if payload:
        return payload.decode(msg.get_content_charset() or "utf-8", errors="replace").strip()
    return ""


def classify_inbound_email(subject: str, body: str, sender: str) -> tuple[str, str | None]:
    """
    Classify an incoming recruiting email and optionally return the new Jobs pipeline stage.
    Returns (classification, new_job_stage_or_None).
    """
    blob = f"{subject}\n{body[:2500]}".lower()
    if any(k in blob for k in ("offer letter", "pleased to offer", "formal offer", "extend an offer", "compensation package")):
        return "offer", "Offer"
    if any(k in blob for k in ("unfortunately", "not moving forward", "decided not to move forward", "other candidates", "position has been filled", "regret to inform")):
        return "rejection", "Rejected"
    if any(k in blob for k in ("calendly.com", "goodtime.io", "ashbyhq.com/scheduling", "interview invitation", "schedule an interview", "technical interview", "onsite interview", "panel interview")):
        return "interview_invite", "Onsite / Final" if "onsite" in blob or "panel" in blob else "Phone Screen"
    if any(k in blob for k in ("hackerrank", "codesignal", "codility", "take-home", "coding assessment", "technical assessment", "case study assignment")):
        return "assessment", "Technical"
    if any(k in blob for k in ("phone screen", "intro call", "recruiter call", "quick chat about your background", "15-minute call", "availability to chat", "interview with")):
        return "recruiter_screen", "Phone Screen"
    if any(k in blob for k in ("thank you for applying", "received your application", "application confirmation", "out of office", "automatic reply", "auto-reply")):
        return "auto_reply", None
    return "follow_up_needed", None


def scan_inbox(store: EmploymaxingStore, days: int = 14, limit: int = 50) -> dict:
    """Connect via IMAP4_SSL, scan recent messages for job replies, classify, and update Jobs pipeline."""
    cfg = load_mail_config(store)
    if not cfg.get("email") or not cfg.get("password") or not cfg.get("imap_host"):
        return {
            "status": "not_configured",
            "message": "Mailbox credentials not configured. Run `employmaxing mail-setup` or configure in the Web UI Settings.",
            "new_replies": [],
        }

    known_jobs = store.list_jobs()
    sent_emails = store.list_emails(direction="outbound_sent")
    sent_domains = {e["recipient_email"].split("@")[-1].lower() for e in sent_emails if "@" in e.get("recipient_email", "")}
    sent_msg_ids = {e["message_id"] for e in sent_emails if e.get("message_id")}
    company_tokens = {re.sub(r'[^a-z0-9]', '', j["company"].lower()): j for j in known_jobs if j.get("company")}

    since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    new_replies = []

    ctx = ssl.create_default_context()
    with imaplib.IMAP4_SSL(cfg["imap_host"], int(cfg.get("imap_port", 993)), ssl_context=ctx) as imap:
        imap.login(cfg["email"], cfg["password"])
        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, f'(SINCE "{since_date}")')
        if typ != "OK":
            return {"status": "error", "message": "IMAP search failed", "new_replies": []}

        uid_list = data[0].split()[-limit:]
        for num in reversed(uid_list):
            t2, msg_data = imap.fetch(num, "(RFC822)")
            if t2 != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            if not isinstance(raw_bytes, (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(raw_bytes)
            subj = _decode_hdr(msg.get("Subject"))
            from_name, from_addr = parseaddr(_decode_hdr(msg.get("From")))
            from_addr = from_addr.lower()
            if from_addr == cfg["email"].lower():
                continue

            msg_id = (msg.get("Message-ID") or "").strip()
            in_reply_to = (msg.get("In-Reply-To") or "").strip()
            sender_domain = from_addr.split("@")[-1] if "@" in from_addr else ""
            body = _extract_body(msg)[:4000]

            # Relevance filter: matches an outbound thread, tracked company, or recruiting domain/keywords
            matched_job = None
            is_thread_reply = bool(in_reply_to and in_reply_to in sent_msg_ids)
            is_known_domain = sender_domain in sent_domains
            for tok, job_obj in company_tokens.items():
                if len(tok) >= 3 and (tok in sender_domain or tok in subj.lower()):
                    matched_job = job_obj
                    break

            recruiting_signal = any(
                k in f"{from_addr} {subj}".lower()
                for k in ("greenhouse", "lever.co", "ashbyhq", "myworkday", "recruiting", "talent", "careers", "interview", "application", "hiring")
            )
            if not (is_thread_reply or is_known_domain or matched_job or recruiting_signal):
                continue

            classification, new_stage = classify_inbound_email(subj, body, from_addr)
            rec_id = store.record_email({
                "direction": "inbound_reply",
                "job_id": matched_job["id"] if matched_job else "",
                "recipient_name": cfg["email"],
                "recipient_email": cfg["email"],
                "sender_email": f"{from_name} <{from_addr}>" if from_name else from_addr,
                "subject": subj,
                "body": body,
                "message_id": msg_id,
                "in_reply_to": in_reply_to,
                "classification": classification,
                "status": "received",
            })

            if matched_job and new_stage:
                store.upsert_job({"id": matched_job["id"], "stage": new_stage, "notes": f"Auto-updated from inbox reply ({classification}): {subj}"})

            new_replies.append({
                "id": rec_id,
                "from": from_addr,
                "subject": subj,
                "classification": classification,
                "matched_job_id": matched_job["id"] if matched_job else "",
                "stage_updated_to": new_stage,
            })

    store.log_event("inbox_scanned", f"Scanned inbox ({days}d): found {len(new_replies)} job-related message(s)", {"count": len(new_replies)})
    return {"status": "ok", "scanned_days": days, "new_replies": new_replies}


def queue_outbound_email(
    store: EmploymaxingStore,
    recipient_email: str,
    subject: str,
    body: str,
    recipient_name: str = "",
    job_id: str = "",
    classification: str = "outreach_touch_1",
    facts_used: list[int] | None = None,
    in_reply_to: str = "",
    auto_approve: bool = False,
) -> dict:
    """
    Score an outbound email via Lavender/Gong empirical rules, run live DNS MX check,
    record exact facts_used for user transparency, and queue it in Outbox.
    """
    # Run empirical mail scorer via temp buffer
    tmp_file = store.data_dir / ".tmp_mail_check.md"
    tmp_file.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
    try:
        mode = "referral" if "referral" in classification else "cold-email"
        audit = audit_mail(tmp_file, mode=mode)
    finally:
        if tmp_file.exists():
            tmp_file.unlink()

    domain = recipient_email.split("@")[-1] if "@" in recipient_email else ""
    mx = check_mx_records(domain) if domain else {"valid_mx": False, "gateway": "Invalid Email"}

    eid = store.record_email({
        "direction": "outbound_approved" if auto_approve else "outbound_draft",
        "job_id": job_id,
        "recipient_name": recipient_name,
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "in_reply_to": in_reply_to,
        "classification": classification,
        "mail_score": audit["score"],
        "mx_gateway": mx["gateway"],
        "facts_used": facts_used or [],
        "status": "approved" if auto_approve else "pending_approval",
    })
    store.log_event(
        "email_queued",
        f"Queued email #{eid} to {recipient_email} (Score: {audit['score']}/100, MX: {mx['gateway']})",
        {"email_id": eid, "facts_used": facts_used or []},
    )
    return {"email_id": eid, "mail_score": audit["score"], "issues": audit["issues"], "mx": mx, "status": "approved" if auto_approve else "pending_approval"}


def send_approved_emails(store: EmploymaxingStore, email_id: int | None = None, dry_run: bool = False) -> dict:
    """Send approved outbound plain-text emails via SMTP with daily rate limiting & threading."""
    cfg = load_mail_config(store)
    approved = store.list_emails(status="approved")
    if email_id is not None:
        approved = [e for e in approved if e["id"] == email_id]

    if not approved:
        return {"status": "ok", "sent": [], "message": "No approved emails waiting in Outbox."}

    # Daily cap check
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    sent_today = sum(
        1 for e in store.list_emails(direction="outbound_sent", status="sent")
        if (e.get("sent_or_received_at") or "").startswith(today_prefix)
    )
    remaining = max(0, int(cfg.get("daily_send_limit", 20)) - sent_today)
    if remaining <= 0 and not dry_run:
        return {"status": "rate_limited", "sent": [], "message": f"Daily safe send limit ({cfg['daily_send_limit']}) reached."}

    if not dry_run and (not cfg.get("email") or not cfg.get("password") or not cfg.get("smtp_host")):
        return {"status": "not_configured", "sent": [], "message": "SMTP credentials not configured in mail-config.json."}

    results = []
    batch = approved[:remaining] if not dry_run else approved

    if dry_run:
        for e in batch:
            results.append({"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "dry_run": True})
        return {"status": "dry_run", "sent": results}

    ctx = ssl.create_default_context()
    port = int(cfg.get("smtp_port", 465))
    use_ssl = bool(cfg.get("smtp_ssl", port == 465))
    sender_domain = cfg["email"].split("@")[-1]

    conn = smtplib.SMTP_SSL(cfg["smtp_host"], port, context=ctx) if use_ssl else smtplib.SMTP(cfg["smtp_host"], port)
    try:
        if not use_ssl:
            conn.starttls(context=ctx)
        conn.login(cfg["email"], cfg["password"])

        for idx, e in enumerate(batch):
            msg = EmailMessage()
            msg["From"] = f"{cfg.get('display_name', '')} <{cfg['email']}>".strip() if cfg.get("display_name") else cfg["email"]
            msg["To"] = e["recipient_email"]
            msg["Subject"] = e["subject"]
            msg_id = make_msgid(domain=sender_domain)
            msg["Message-ID"] = msg_id
            if e.get("in_reply_to"):
                msg["In-Reply-To"] = e["in_reply_to"]
                msg["References"] = e["in_reply_to"]
            # Pure plain text (0 HTML bloat, 0 cold attachments) for peak deliverability
            msg.set_content(e["body"])

            try:
                conn.send_message(msg)
                now = store._now()
                store.update_email(
                    e["id"],
                    direction="outbound_sent",
                    status="sent",
                    message_id=msg_id,
                    sent_or_received_at=now,
                    error_msg="",
                )
                store.log_event("email_sent", f"Sent email #{e['id']} to {e['recipient_email']} ('{e['subject']}')", {"email_id": e["id"]})
                results.append({"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "message_id": msg_id, "sent": True})
                if idx + 1 < len(batch):
                    time.sleep(float(cfg.get("send_delay_seconds", 4)))
            except Exception as ex:
                store.update_email(e["id"], status="failed", error_msg=str(ex))
                results.append({"id": e["id"], "to": e["recipient_email"], "sent": False, "error": str(ex)})
    finally:
        try:
            conn.quit()
        except Exception:
            pass

    return {"status": "ok", "sent": results}


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Mailbox Engine (IMAP Scanner + SMTP Sender)")
    parser.add_argument("--data-dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_cfg = sub.add_parser("configure", help="Save IMAP/SMTP credentials locally (chmod 600)")
    p_cfg.add_argument("--provider", choices=["gmail", "outlook", "fastmail", "icloud", "custom"], default="gmail")
    p_cfg.add_argument("--email", required=True)
    p_cfg.add_argument("--password", required=True, help="App Password (recommended over account password)")
    p_cfg.add_argument("--display-name", default="")
    p_cfg.add_argument("--imap-host", default="")
    p_cfg.add_argument("--smtp-host", default="")

    p_scan = sub.add_parser("scan-inbox", help="Check mailbox for recruiter/HM replies & update job stages")
    p_scan.add_argument("--days", type=int, default=14)
    p_scan.add_argument("--limit", type=int, default=50)

    p_q = sub.add_parser("queue", help="Score & queue an outbound email for review/approval")
    p_q.add_argument("--to", required=True)
    p_q.add_argument("--name", default="")
    p_q.add_argument("--subject", required=True)
    p_q.add_argument("--body-file", required=True)
    p_q.add_argument("--job-id", default="")
    p_q.add_argument("--approve", action="store_true")

    p_send = sub.add_parser("send", help="Send approved outbound emails via SMTP")
    p_send.add_argument("--id", type=int, default=None)
    p_send.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    store = EmploymaxingStore(args.data_dir)

    if args.cmd == "configure":
        cfg = {"provider": args.provider, "email": args.email, "password": args.password, "display_name": args.display_name}
        if args.imap_host:
            cfg["imap_host"] = args.imap_host
        if args.smtp_host:
            cfg["smtp_host"] = args.smtp_host
        path = save_mail_config(store, cfg)
        print(json.dumps({"saved": str(path), "provider": args.provider, "email": args.email}, indent=2))
    elif args.cmd == "scan-inbox":
        print(json.dumps(scan_inbox(store, days=args.days, limit=args.limit), indent=2))
    elif args.cmd == "queue":
        body = Path(args.body_file).read_text(encoding="utf-8")
        print(json.dumps(queue_outbound_email(store, args.to, args.subject, body, args.name, args.job_id, auto_approve=args.approve), indent=2))
    elif args.cmd == "send":
        print(json.dumps(send_approved_emails(store, email_id=args.id, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
