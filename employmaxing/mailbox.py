#!/usr/bin/env python3
"""
mailbox.py - Unified Single-Provider Mailbox Engine (Inbox Reply Scanner + Plain-Text Sender).
Supports EXACTLY ONE active provider at a time:
  - google      -> Sign in with Google OAuth2 (PKCE) + native Gmail REST API (2FA-native!)
  - microsoft   -> Sign in with Microsoft OAuth2 (PKCE) + native Microsoft Graph API (2FA-native!)
  - yahoo       -> Yahoo OAuth2 (XOAUTH2) OR Yahoo 2FA App Password (IMAP/SMTP)
  - proton      -> Proton Mail Bridge local loopback TLS (127.0.0.1:1143 / 1025)
  - custom_api  -> Custom Mail Provider REST API (Resend, Postmark, Mailgun, or Custom HTTP API)

Licensed under GNU GPL v3.0.
"""

import argparse
import base64
import email
import imaplib
import json
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

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
SHARED_SCRIPTS = BASE_DIR / "shared" / "scripts"
for p in (str(BASE_DIR), str(SHARED_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from employmaxing.mail_oauth import (
    ensure_valid_access_token,
    load_active_mail_config,
    save_single_provider_config,
)
from employmaxing.store import EmploymaxingStore
from employmaxing.thunderbird import (
    discover_thunderbird,
    is_bridge_online,
    open_thunderbird_compose,
    read_recent_mbox_messages,
)
from optimizer import audit_mail, check_mx_records


def load_mail_config(store: EmploymaxingStore) -> dict:
    return load_active_mail_config(store)


def save_mail_config(store: EmploymaxingStore, cfg: dict) -> dict:
    return save_single_provider_config(store, cfg.get("provider", "google"), cfg)


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


def _ingest_classified_message(
    store: EmploymaxingStore,
    my_email: str,
    from_raw: str,
    subj: str,
    body: str,
    msg_id: str,
    in_reply_to: str,
    sent_domains: set[str],
    sent_msg_ids: set[str],
    company_tokens: dict[str, dict],
) -> dict | None:
    from_name, from_addr = parseaddr(from_raw)
    from_addr = from_addr.lower()
    if not from_addr or (my_email and from_addr == my_email.lower()):
        return None

    sender_domain = from_addr.split("@")[-1] if "@" in from_addr else ""
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
        return None

    classification, new_stage = classify_inbound_email(subj, body, from_addr)
    rec_id = store.record_email({
        "direction": "inbound_reply",
        "job_id": matched_job["id"] if matched_job else "",
        "recipient_name": my_email,
        "recipient_email": my_email,
        "sender_email": f"{from_name} <{from_addr}>" if from_name else from_addr,
        "subject": subj,
        "body": body[:4000],
        "message_id": msg_id,
        "in_reply_to": in_reply_to,
        "classification": classification,
        "status": "received",
    })
    if matched_job and new_stage:
        store.upsert_job({"id": matched_job["id"], "stage": new_stage, "notes": f"Auto-updated from inbox reply ({classification}): {subj}"})

    return {
        "id": rec_id,
        "from": from_addr,
        "subject": subj,
        "classification": classification,
        "matched_job_id": matched_job["id"] if matched_job else "",
        "stage_updated_to": new_stage,
    }


def _scan_gmail_api(store: EmploymaxingStore, days: int, limit: int, ctx_sets: tuple) -> list[dict]:
    token, cfg = ensure_valid_access_token(store)
    hdrs = {"Authorization": f"Bearer {token}"}
    q = f"in:inbox newer_than:{days}d"
    r = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=hdrs,
        params={"q": q, "maxResults": limit},
        timeout=15,
    )
    r.raise_for_status()
    msgs = r.json().get("messages", [])
    sent_domains, sent_msg_ids, company_tokens = ctx_sets
    found = []
    for item in msgs:
        mr = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
            headers=hdrs,
            params={"format": "full"},
            timeout=10,
        )
        if mr.status_code != 200:
            continue
        m = mr.json()
        headers_map = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        subj = headers_map.get("subject", "")
        sender = headers_map.get("from", "")
        msg_id = headers_map.get("message-id", item["id"])
        in_reply_to = headers_map.get("in-reply-to", "")
        body = m.get("snippet", "")
        # Try decoding plain text body part if present
        parts = m.get("payload", {}).get("parts") or [m.get("payload", {})]
        for pt in parts:
            if pt.get("mimeType") == "text/plain" and pt.get("body", {}).get("data"):
                raw_b64 = pt["body"]["data"]
                pad = "=" * ((4 - len(raw_b64) % 4) % 4)
                body = base64.urlsafe_b64decode(raw_b64 + pad).decode("utf-8", errors="replace")
                break
        rec = _ingest_classified_message(store, cfg.get("email", ""), sender, subj, body, msg_id, in_reply_to, sent_domains, sent_msg_ids, company_tokens)
        if rec:
            found.append(rec)
    return found


def _scan_microsoft_graph(store: EmploymaxingStore, days: int, limit: int, ctx_sets: tuple) -> list[dict]:
    token, cfg = ensure_valid_access_token(store)
    hdrs = {"Authorization": f"Bearer {token}"}
    since_iso = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
        headers=hdrs,
        params={
            "$top": limit,
            "$filter": f"receivedDateTime ge {since_iso}",
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,bodyPreview,internetMessageId,conversationId",
        },
        timeout=15,
    )
    r.raise_for_status()
    sent_domains, sent_msg_ids, company_tokens = ctx_sets
    found = []
    for m in r.json().get("value", []):
        ea = (m.get("from") or {}).get("emailAddress") or {}
        sender = f"{ea.get('name', '')} <{ea.get('address', '')}>".strip()
        subj = m.get("subject") or ""
        body = m.get("bodyPreview") or ""
        msg_id = m.get("internetMessageId") or m.get("id", "")
        rec = _ingest_classified_message(store, cfg.get("email", ""), sender, subj, body, msg_id, "", sent_domains, sent_msg_ids, company_tokens)
        if rec:
            found.append(rec)
    return found


def _scan_custom_api_inbox(store: EmploymaxingStore, cfg: dict, days: int, limit: int, ctx_sets: tuple) -> list[dict]:
    inbox_url = (cfg.get("inbox_url") or "").strip()
    if not inbox_url:
        return []
    auth_hdr = cfg.get("auth_header") or "Authorization"
    prefix = cfg.get("auth_prefix", "Bearer ")
    hdrs = {auth_hdr: f"{prefix}{cfg.get('api_key', '')}".strip(), "Accept": "application/json"}
    r = requests.get(inbox_url, headers=hdrs, params={"days": days, "limit": limit}, timeout=15)
    r.raise_for_status()
    data = r.json()
    items = data if isinstance(data, list) else (data.get("messages") or data.get("data") or [])
    sent_domains, sent_msg_ids, company_tokens = ctx_sets
    found = []
    for m in items[:limit]:
        sender = m.get("from") or m.get("sender") or ""
        subj = m.get("subject") or ""
        body = m.get("text") or m.get("body") or m.get("snippet") or ""
        msg_id = str(m.get("message_id") or m.get("id") or "")
        in_reply_to = str(m.get("in_reply_to") or "")
        rec = _ingest_classified_message(store, cfg.get("from_email") or cfg.get("email", ""), sender, subj, body, msg_id, in_reply_to, sent_domains, sent_msg_ids, company_tokens)
        if rec:
            found.append(rec)
    return found


def _scan_imap_provider(store: EmploymaxingStore, cfg: dict, days: int, limit: int, ctx_sets: tuple) -> list[dict]:
    provider = cfg.get("provider", "")
    host = cfg.get("imap_host") or ("127.0.0.1" if provider == "proton" else "imap.mail.yahoo.com")
    port = int(cfg.get("imap_port") or (1143 if provider == "proton" else 993))
    since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    sent_domains, sent_msg_ids, company_tokens = ctx_sets
    found = []

    if provider == "proton" and host in ("127.0.0.1", "localhost"):
        # Proton Bridge uses STARTTLS on loopback 127.0.0.1:1143 with local self-signed cert
        imap = imaplib.IMAP4(host, port)
        local_ctx = ssl.create_default_context()
        local_ctx.check_hostname = False
        local_ctx.verify_mode = ssl.CERT_NONE
        imap.starttls(ssl_context=local_ctx)
    else:
        imap = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())

    try:
        if provider == "yahoo" and cfg.get("auth_mode") == "oauth2":
            token, _ = ensure_valid_access_token(store)
            auth_str = f"user={cfg['email']}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
            imap.authenticate("XOAUTH2", lambda _: auth_str)
        else:
            imap.login(cfg["email"], cfg["password"])

        imap.select("INBOX", readonly=True)
        typ, data = imap.search(None, f'(SINCE "{since_date}")')
        if typ != "OK":
            return []
        for num in reversed(data[0].split()[-limit:]):
            t2, msg_data = imap.fetch(num, "(RFC822)")
            if t2 != "OK" or not msg_data or not msg_data[0] or not isinstance(msg_data[0][1], (bytes, bytearray)):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            rec = _ingest_classified_message(
                store,
                cfg.get("email", ""),
                _decode_hdr(msg.get("From")),
                _decode_hdr(msg.get("Subject")),
                _extract_body(msg),
                (msg.get("Message-ID") or "").strip(),
                (msg.get("In-Reply-To") or "").strip(),
                sent_domains,
                sent_msg_ids,
                company_tokens,
            )
            if rec:
                found.append(rec)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return found


def _scan_thunderbird_mbox(store: EmploymaxingStore, cfg: dict, days: int, limit: int, ctx_sets: tuple) -> tuple[list[dict], int]:
    """
    Read Thunderbird's local INBOX mbox files for replies AND check Sent mbox files to
    auto-confirm emails that the user clicked Send on in Thunderbird!
    """
    disc = discover_thunderbird(cfg.get("profile_dir") or None)
    inbox_paths = [Path(p) for p in (cfg.get("inbox_files") or disc.get("inbox_files") or [])]
    sent_paths = [Path(p) for p in (cfg.get("sent_files") or disc.get("sent_files") or [])]

    # Restrict to the chosen account's mail_dir when available
    mail_dir = (cfg.get("mail_dir") or "").strip()
    if mail_dir:
        filtered_in = [p for p in inbox_paths if str(p).startswith(mail_dir)]
        filtered_sent = [p for p in sent_paths if str(p).startswith(mail_dir)]
        if filtered_in:
            inbox_paths = filtered_in
        if filtered_sent:
            sent_paths = filtered_sent

    sent_domains, sent_msg_ids, company_tokens = ctx_sets
    my_email = cfg.get("email", "")
    found = []

    for mbox_p in inbox_paths:
        for m in read_recent_mbox_messages(mbox_p, days=days, limit=limit):
            rec = _ingest_classified_message(
                store, my_email, m["from"], m["subject"], m["body"], m["message_id"], m["in_reply_to"],
                sent_domains, sent_msg_ids, company_tokens,
            )
            if rec:
                found.append(rec)

    # Auto-confirm any emails previously handed to Thunderbird compose that now appear in Sent mbox!
    confirmed_sent = 0
    pending_tb = store.list_emails(status="opened_in_thunderbird")
    if pending_tb and sent_paths:
        sent_recent = []
        for sp in sent_paths:
            sent_recent.extend(read_recent_mbox_messages(sp, days=max(days, 7), limit=100))
        for pe in pending_tb:
            pe_to = (pe.get("recipient_email") or "").lower()
            pe_subj = (pe.get("subject") or "").strip().lower()
            for sm in sent_recent:
                if pe_to and pe_to in (sm.get("to") or "").lower() and pe_subj == (sm.get("subject") or "").strip().lower():
                    store.update_email(
                        pe["id"],
                        direction="outbound_sent",
                        status="sent",
                        message_id=sm.get("message_id") or pe.get("message_id", ""),
                        sent_or_received_at=store._now(),
                    )
                    store.log_event("email_sent_confirmed", f"Auto-confirmed Thunderbird sent email #{pe['id']} to {pe['recipient_email']}")
                    confirmed_sent += 1
                    break
    return found, confirmed_sent


def ingest_bridge_inbox_messages(store: EmploymaxingStore, messages: list[dict]) -> list[dict]:
    """Process recent inbox messages pushed live by Thunderbird's messagesRead MailExtension API."""
    if not messages:
        return []
    cfg = load_active_mail_config(store)
    known_jobs = store.list_jobs()
    sent_emails = store.list_emails(direction="outbound_sent")
    sent_domains = {e["recipient_email"].split("@")[-1].lower() for e in sent_emails if "@" in e.get("recipient_email", "")}
    sent_msg_ids = {e["message_id"] for e in sent_emails if e.get("message_id")}
    company_tokens = {re.sub(r'[^a-z0-9]', '', j["company"].lower()): j for j in known_jobs if j.get("company")}
    my_email = cfg.get("email", "")
    ingested = []
    for m in messages:
        rec = _ingest_classified_message(
            store,
            my_email,
            m.get("from", ""),
            m.get("subject", ""),
            m.get("body", ""),
            m.get("message_id", ""),
            m.get("in_reply_to", ""),
            sent_domains,
            sent_msg_ids,
            company_tokens,
        )
        if rec:
            ingested.append(rec)
    return ingested


def scan_inbox(store: EmploymaxingStore, days: int = 14, limit: int = 50) -> dict:
    """Scan the single active mail provider for recruiter/HM replies and update Jobs pipeline."""
    cfg = load_active_mail_config(store)
    provider = cfg.get("provider", "")
    if not provider:
        return {
            "status": "not_configured",
            "message": "No mail provider connected yet. Connect Thunderbird (easiest!) or Google/Microsoft/Yahoo/Proton/Custom API in 00 // Get Started.",
            "new_replies": [],
        }

    known_jobs = store.list_jobs()
    sent_emails = store.list_emails(direction="outbound_sent")
    sent_domains = {e["recipient_email"].split("@")[-1].lower() for e in sent_emails if "@" in e.get("recipient_email", "")}
    sent_msg_ids = {e["message_id"] for e in sent_emails if e.get("message_id")}
    company_tokens = {re.sub(r'[^a-z0-9]', '', j["company"].lower()): j for j in known_jobs if j.get("company")}
    ctx_sets = (sent_domains, sent_msg_ids, company_tokens)

    confirmed_sent = 0
    if provider == "thunderbird":
        new_replies, confirmed_sent = _scan_thunderbird_mbox(store, cfg, days, limit, ctx_sets)
    elif provider == "google":
        new_replies = _scan_gmail_api(store, days, limit, ctx_sets)
    elif provider == "microsoft":
        new_replies = _scan_microsoft_graph(store, days, limit, ctx_sets)
    elif provider == "custom_api":
        new_replies = _scan_custom_api_inbox(store, cfg, days, limit, ctx_sets)
    else:
        new_replies = _scan_imap_provider(store, cfg, days, limit, ctx_sets)

    store.log_event("inbox_scanned", f"Scanned {provider.upper()} inbox ({days}d): {len(new_replies)} reply(s), {confirmed_sent} sent confirmed", {"provider": provider, "count": len(new_replies), "confirmed_sent": confirmed_sent})
    return {"status": "ok", "provider": provider, "scanned_days": days, "new_replies": new_replies, "confirmed_sent": confirmed_sent}


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


def _build_mime(cfg: dict, e: dict) -> tuple[EmailMessage, str]:
    sender = cfg.get("from_email") or cfg.get("email", "")
    sender_domain = sender.split("@")[-1] if "@" in sender else "localhost"
    msg = EmailMessage()
    msg["From"] = f"{cfg.get('display_name', '')} <{sender}>".strip() if cfg.get("display_name") else sender
    msg["To"] = e["recipient_email"]
    msg["Subject"] = e["subject"]
    msg_id = make_msgid(domain=sender_domain)
    msg["Message-ID"] = msg_id
    if e.get("in_reply_to"):
        msg["In-Reply-To"] = e["in_reply_to"]
        msg["References"] = e["in_reply_to"]
    msg.set_content(e["body"])
    return msg, msg_id


def _send_one_gmail(store: EmploymaxingStore, cfg: dict, e: dict) -> str:
    token, cfg = ensure_valid_access_token(store)
    msg, msg_id = _build_mime(cfg, e)
    raw_b64 = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    r = requests.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"raw": raw_b64},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("id") or msg_id


def _send_one_microsoft(store: EmploymaxingStore, cfg: dict, e: dict) -> str:
    token, _ = ensure_valid_access_token(store)
    payload = {
        "message": {
            "subject": e["subject"],
            "body": {"contentType": "Text", "content": e["body"]},
            "toRecipients": [{"emailAddress": {"address": e["recipient_email"]}}],
        },
        "saveToSentItems": True,
    }
    r = requests.post(
        "https://graph.microsoft.com/v1.0/me/sendMail",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return make_msgid(domain="graph.microsoft.com")


def _send_one_custom_api(cfg: dict, e: dict) -> str:
    send_url = (cfg.get("send_url") or "").strip()
    if not send_url:
        raise RuntimeError("Custom Mail API send_url is not configured.")
    auth_hdr = cfg.get("auth_header") or "Authorization"
    prefix = cfg.get("auth_prefix", "Bearer ")
    hdrs = {auth_hdr: f"{prefix}{cfg.get('api_key', '')}".strip(), "Content-Type": "application/json"}
    preset = (cfg.get("api_preset") or "custom").lower()
    from_addr = cfg.get("from_email") or cfg.get("email") or ""

    if preset == "postmark":
        body = {"From": from_addr, "To": e["recipient_email"], "Subject": e["subject"], "TextBody": e["body"]}
    elif preset == "resend":
        body = {"from": from_addr, "to": [e["recipient_email"]], "subject": e["subject"], "text": e["body"]}
    else:
        body = {"from": from_addr, "to": e["recipient_email"], "subject": e["subject"], "text": e["body"]}

    r = requests.post(send_url, headers=hdrs, json=body, timeout=15)
    r.raise_for_status()
    try:
        j = r.json()
        return str(j.get("id") or j.get("MessageID") or make_msgid(domain="custom.api"))
    except Exception:
        return make_msgid(domain="custom.api")


def _send_one_smtp(store: EmploymaxingStore, cfg: dict, e: dict) -> str:
    provider = cfg.get("provider", "")
    host = cfg.get("smtp_host") or ("127.0.0.1" if provider == "proton" else "smtp.mail.yahoo.com")
    port = int(cfg.get("smtp_port") or (1025 if provider == "proton" else 465))
    msg, msg_id = _build_mime(cfg, e)

    if provider == "proton" and host in ("127.0.0.1", "localhost"):
        conn = smtplib.SMTP(host, port, timeout=15)
        local_ctx = ssl.create_default_context()
        local_ctx.check_hostname = False
        local_ctx.verify_mode = ssl.CERT_NONE
        conn.starttls(context=local_ctx)
    elif port == 465:
        conn = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15)
    else:
        conn = smtplib.SMTP(host, port, timeout=15)
        conn.starttls(context=ssl.create_default_context())

    try:
        if provider == "yahoo" and cfg.get("auth_mode") == "oauth2":
            token, _ = ensure_valid_access_token(store)
            auth_b64 = base64.b64encode(f"user={cfg['email']}\x01auth=Bearer {token}\x01\x01".encode("utf-8")).decode("ascii")
            conn.docmd("AUTH", f"XOAUTH2 {auth_b64}")
        else:
            conn.login(cfg["email"], cfg["password"])
        conn.send_message(msg)
    finally:
        try:
            conn.quit()
        except Exception:
            pass
    return msg_id


def send_approved_emails(store: EmploymaxingStore, email_id: int | None = None, dry_run: bool = False) -> dict:
    """Send approved outbound plain-text emails through the single active mail provider."""
    cfg = load_active_mail_config(store)
    approved = store.list_emails(status="approved")
    if email_id is not None:
        approved = [e for e in approved if e["id"] == email_id]

    if not approved:
        return {"status": "ok", "sent": [], "message": "No approved emails waiting in Outbox."}

    today_prefix = datetime.now().strftime("%Y-%m-%d")
    sent_today = sum(
        1 for e in store.list_emails(direction="outbound_sent", status="sent")
        if (e.get("sent_or_received_at") or "").startswith(today_prefix)
    )
    remaining = max(0, int(cfg.get("daily_send_limit", 20)) - sent_today)
    if remaining <= 0 and not dry_run:
        return {"status": "rate_limited", "sent": [], "message": f"Daily safe send limit ({cfg['daily_send_limit']}) reached."}

    provider = cfg.get("provider", "")
    if not dry_run and not provider:
        return {"status": "not_configured", "sent": [], "message": "No mail provider connected. Sign in with Google/Microsoft or configure Yahoo/Proton/Custom API."}

    batch = approved[:remaining] if not dry_run else approved
    if dry_run:
        return {"status": "dry_run", "provider": provider or "unconfigured", "sent": [{"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "dry_run": True} for e in batch]}

    results = []
    for idx, e in enumerate(batch):
        try:
            if provider == "thunderbird":
                if is_bridge_online():
                    # 100% hands-free auto-send via live Thunderbird Companion Add-on!
                    store.update_email(
                        e["id"],
                        direction="outbound_approved",
                        status="queued_for_bridge",
                        sent_or_received_at=store._now(),
                        error_msg="",
                    )
                    store.log_event("email_queued_bridge", f"Dispatched email #{e['id']} to live Thunderbird Auto-Send Bridge for {e['recipient_email']}")
                    results.append({"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "queued_for_bridge": True, "hands_free": True})
                else:
                    # Graceful fallback: open pre-filled plain-text draft in Thunderbird
                    open_thunderbird_compose(e["recipient_email"], e["subject"], e["body"], custom_cmd=cfg.get("command") or None)
                    store.update_email(
                        e["id"],
                        direction="outbound_approved",
                        status="opened_in_thunderbird",
                        sent_or_received_at=store._now(),
                        error_msg="",
                    )
                    store.log_event("email_opened_thunderbird", f"Opened pre-filled plain-text draft #{e['id']} in Thunderbird for {e['recipient_email']} (install the Employmaxing Bridge add-on for 100% hands-free sending)")
                    results.append({"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "opened_in_thunderbird": True, "hands_free": False})
                continue

            if provider == "google":
                msg_id = _send_one_gmail(store, cfg, e)
            elif provider == "microsoft":
                msg_id = _send_one_microsoft(store, cfg, e)
            elif provider == "custom_api":
                msg_id = _send_one_custom_api(cfg, e)
            else:
                msg_id = _send_one_smtp(store, cfg, e)

            store.update_email(
                e["id"],
                direction="outbound_sent",
                status="sent",
                message_id=msg_id,
                sent_or_received_at=store._now(),
                error_msg="",
            )
            store.log_event("email_sent", f"Sent email #{e['id']} via {provider.upper()} to {e['recipient_email']} ('{e['subject']}')", {"email_id": e["id"], "provider": provider})
            results.append({"id": e["id"], "to": e["recipient_email"], "subject": e["subject"], "message_id": msg_id, "sent": True})
            if idx + 1 < len(batch):
                time.sleep(float(cfg.get("send_delay_seconds", 4)))
        except Exception as ex:
            store.update_email(e["id"], status="failed", error_msg=str(ex))
            results.append({"id": e["id"], "to": e["recipient_email"], "sent": False, "error": str(ex)})

    return {"status": "ok", "provider": provider, "sent": results}


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Single-Provider Mailbox Engine")
    parser.add_argument("--data-dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan-inbox", help="Scan active mail provider for recruiter/HM replies")
    p_scan.add_argument("--days", type=int, default=14)
    p_scan.add_argument("--limit", type=int, default=50)

    p_send = sub.add_parser("send", help="Send approved outbound emails via active provider")
    p_send.add_argument("--id", type=int, default=None)
    p_send.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    store = EmploymaxingStore(args.data_dir)
    if args.cmd == "scan-inbox":
        print(json.dumps(scan_inbox(store, days=args.days, limit=args.limit), indent=2))
    elif args.cmd == "send":
        print(json.dumps(send_approved_emails(store, email_id=args.id, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
