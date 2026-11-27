#!/usr/bin/env python3
"""
server.py - Local-only (127.0.0.1) REST API & Neo-Brutalist Web Dashboard Server for Employmaxing.
Features:
  - Zero-CLI First-Time Setup & Direct Browser Resume/LinkedIn File Upload (/api/onboarding/*)
  - Single-Provider OAuth 2.0 (PKCE) Sign-In for Google & Microsoft (+ Yahoo, Proton Bridge, Custom Mail API)
  - Transparent Information & Consent Ledger (/api/facts)
  - LinkedIn Discrepancy & Turn-Off Auditor (/api/linkedin-audit)
  - Potential Jobs, Applied Jobs & Custom Job Applications (/api/jobs/*)
  - Mailbox Reply Monitor, Outbox Approval Queue & Sent Mail Ledger (/api/emails/*)
  - Complex ATS Form-Fill Plans & Chrome CDP Execution (/api/forms/*)
Licensed under GNU GPL v3.0.
"""

import argparse
import base64
import json
import mimetypes
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
SHARED_SCRIPTS = BASE_DIR / "shared" / "scripts"
for p in (str(BASE_DIR), str(SHARED_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from employmaxing.enricher import (
    compile_master_profile,
    enrich_from_github,
    enrich_from_website,
    ingest_linkedin,
    ingest_resume,
)
from employmaxing.form_filler import build_transparent_form_plan, execute_cdp_fill
from employmaxing.mail_oauth import (
    complete_oauth_callback,
    disconnect_mail_provider,
    get_public_mail_status,
    save_single_provider_config,
    start_oauth_flow,
)
from employmaxing.build_xpi import OUT_XPI, build_xpi
from employmaxing.mailbox import queue_outbound_email, scan_inbox, send_approved_emails
from employmaxing.store import EmploymaxingStore
from employmaxing.thunderbird import (
    discover_thunderbird,
    get_bridge_status,
    install_addon_into_profile,
    record_bridge_heartbeat,
)
from linkedin_audit import audit_linkedin_vs_resume, load_linkedin_data, render_markdown_report
from optimizer import audit_job_posting, audit_resume, find_emails, generate_ats_dorks


def _safe_filename(name: str, default: str) -> str:
    base = Path(name or default).name
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', base).strip("._")
    return cleaned or default


def _build_onboarding_status(store: EmploymaxingStore) -> dict:
    state_file = store.data_dir / "onboarding-state.json"
    saved = {}
    if state_file.exists():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            saved = {}

    facts = store.list_facts()
    approved = [f for f in facts if f["consent_status"] == "approved"]
    fact_map = {f["fact_key"].lower(): f["fact_value"] for f in facts}
    mail_status = get_public_mail_status(store)

    defaults = {
        "full_name": saved.get("full_name") or fact_map.get("name", ""),
        "email": saved.get("email") or fact_map.get("email", ""),
        "phone": saved.get("phone") or fact_map.get("phone", ""),
        "city": saved.get("city") or fact_map.get("city") or fact_map.get("github_location", ""),
        "country": saved.get("country") or "United States",
        "linkedin": saved.get("linkedin") or fact_map.get("linkedin") or fact_map.get("linkedin_url", ""),
        "github": saved.get("github") or fact_map.get("github", ""),
        "website": saved.get("website") or fact_map.get("github_website") or next((v for k, v in fact_map.items() if k.startswith("website:")), ""),
        "target_roles": saved.get("target_roles", ""),
        "location_pref": saved.get("location_pref", "Remote"),
        "min_salary": saved.get("min_salary", ""),
        "dealbreakers": saved.get("dealbreakers", ""),
        "work_auth": saved.get("work_auth", "Yes"),
        "sponsorship": saved.get("sponsorship", "No"),
        "notice_period": saved.get("notice_period", "2 weeks from offer acceptance"),
        "eeo_default": saved.get("eeo_default", "Decline to self-identify"),
    }

    has_resume = (store.data_dir / "resume" / "resume.md").exists()
    completed = bool(saved.get("completed")) or (len(approved) >= 3 and (store.data_dir / "preferences.md").exists())
    return {
        "completed": completed,
        "has_resume": has_resume,
        "facts_total": len(facts),
        "facts_approved": len(approved),
        "mail_connected": mail_status["configured"],
        "mail_provider": mail_status.get("provider", ""),
        "defaults": defaults,
    }


def make_handler(store: EmploymaxingStore):
    class EmploymaxingHandler(BaseHTTPRequestHandler):
        server_version = "EmploymaxingLocal/1.1"

        def _base_url(self) -> str:
            host_hdr = self.headers.get("Host")
            if host_hdr:
                return f"http://{host_hdr}"
            host, port = self.server.server_address[:2]
            return f"http://{host}:{port}"

        def _send_json(self, payload: dict | list, status: int = 200):
            raw = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, html: str, status: int = 200):
            raw = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _send_file(self, path: Path):
            if not path.exists() or not path.is_file():
                self._send_json({"error": "File not found"}, 404)
                return
            mime, _ = mimetypes.guess_type(str(path))
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            if length > 25 * 1024 * 1024:
                raise ValueError("Payload exceeds 25 MB upload limit.")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            return json.loads(body) if body.strip() else {}

        def log_message(self, format, *args):
            sys.stderr.write(f"[employmaxing-web] {self.address_string()} - {format % args}\n")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            # ---- OAuth2 Callback Route (Google / Microsoft / Yahoo) ----
            m_cb = re.match(r'^/api/oauth/(google|microsoft|yahoo)/callback$', path)
            if m_cb:
                provider = m_cb.group(1)
                err = qs.get("error", [""])[0]
                if err:
                    desc = qs.get("error_description", [err])[0]
                    return self._send_html(
                        f"<!doctype html><html><body style='font-family:monospace;background:#F4EFE6;padding:40px;'>"
                        f"<div style='border:4px solid #111;background:#FF4D4D;color:#fff;padding:24px;box-shadow:6px 6px 0 #111;'>"
                        f"<h1>OAUTH SIGN-IN FAILED ({provider.upper()})</h1><p>{desc}</p>"
                        f"<a href='/' style='display:inline-block;margin-top:16px;padding:10px 16px;background:#111;color:#C8FF2E;text-decoration:none;font-weight:900;'>RETURN TO EMPLOYMAXING</a>"
                        f"</div></body></html>",
                        status=400,
                    )
                code = qs.get("code", [""])[0]
                state = qs.get("state", [""])[0]
                try:
                    res = complete_oauth_callback(store, provider, code, state)
                    return self._send_html(
                        f"<!doctype html><html><body style='font-family:monospace;background:#F4EFE6;padding:40px;'>"
                        f"<div style='border:4px solid #111;background:#C8FF2E;color:#111;padding:24px;box-shadow:6px 6px 0 #111;'>"
                        f"<h1>CONNECTED: {provider.upper()} ({res['email']})</h1>"
                        f"<p>2FA-safe OAuth2 tokens stored locally in ~/.employmaxing/mail-config.json (chmod 600).</p>"
                        f"<script>if(window.opener){{window.opener.postMessage({{type:'employmaxing_oauth_ok',provider:'{provider}',email:'{res['email']}'}},'*');setTimeout(()=>window.close(),900);}}else{{setTimeout(()=>location.href='/?oauth=ok&provider={provider}',1100);}}</script>"
                        f"<a href='/?oauth=ok&provider={provider}' style='display:inline-block;margin-top:12px;padding:10px 16px;background:#111;color:#C8FF2E;text-decoration:none;font-weight:900;'>BACK TO DASHBOARD</a>"
                        f"</div></body></html>"
                    )
                except Exception as ex:
                    return self._send_html(
                        f"<!doctype html><html><body style='font-family:monospace;background:#F4EFE6;padding:40px;'>"
                        f"<div style='border:4px solid #111;background:#FF4D4D;color:#fff;padding:24px;box-shadow:6px 6px 0 #111;'>"
                        f"<h1>TOKEN EXCHANGE ERROR</h1><p>{ex}</p>"
                        f"<a href='/' style='display:inline-block;margin-top:16px;padding:10px 16px;background:#111;color:#C8FF2E;text-decoration:none;font-weight:900;'>RETURN TO DASHBOARD</a>"
                        f"</div></body></html>",
                        status=500,
                    )

            # ---- API Routes ----
            if path == "/api/health":
                return self._send_json({"status": "ok", "ui_installed": (WEB_DIR / "index.html").exists(), "data_dir": str(store.data_dir)})

            if path == "/api/onboarding/status":
                return self._send_json(_build_onboarding_status(store))

            if path == "/api/dashboard":
                return self._send_json(store.get_dashboard_summary())

            if path == "/api/facts":
                status = qs.get("status", [None])[0]
                cat = qs.get("category", [None])[0]
                return self._send_json({"facts": store.list_facts(consent_status=status, category=cat)})

            if path == "/api/profile":
                mp = store.data_dir / "master-profile.json"
                if not mp.exists():
                    compile_master_profile(store)
                master = json.loads(mp.read_text(encoding="utf-8"))
                li_fix = store.data_dir / "linkedin-fixes.md"
                master["linkedin_audit_md"] = li_fix.read_text(encoding="utf-8") if li_fix.exists() else ""
                return self._send_json(master)

            if path == "/api/jobs":
                stage = qs.get("stage", [None])[0]
                return self._send_json({"jobs": store.list_jobs(stage=stage)})

            m_art = re.match(r'^/api/jobs/([^/]+)/artifacts$', path)
            if m_art:
                job_id = urllib.parse.unquote(m_art.group(1))
                job = store.get_job(job_id)
                if not job:
                    return self._send_json({"error": "Job not found"}, 404)
                jdir = Path(job.get("folder_path") or (store.data_dir / "jobs" / job_id))
                artifacts = {}
                for fn in ("posting.md", "resume.md", "cover-letter.md", "outreach.md", "interview-prep.md", "form-plan.md", "applied.md", "negotiation.md"):
                    fp = jdir / fn
                    if fp.exists():
                        artifacts[fn] = fp.read_text(encoding="utf-8", errors="replace")
                downloads = []
                for fn in ("resume.pdf", "resume.docx", "cover-letter.pdf", "cover-letter.docx"):
                    fp = jdir / fn
                    if fp.exists():
                        downloads.append({"name": fn, "url": f"/api/files/jobs/{job_id}/{fn}"})
                res_audit = None
                if (jdir / "resume.md").exists():
                    res_audit = audit_resume(jdir / "resume.md", (jdir / "posting.md") if (jdir / "posting.md").exists() else None)
                return self._send_json({"job": job, "artifacts": artifacts, "downloads": downloads, "resume_audit": res_audit})

            if path == "/api/emails":
                direction = qs.get("direction", [None])[0]
                status = qs.get("status", [None])[0]
                return self._send_json({"emails": store.list_emails(direction=direction, status=status)})

            if path == "/api/thunderbird/discover":
                custom_p = qs.get("profile_dir", [None])[0]
                return self._send_json(discover_thunderbird(custom_p))

            if path == "/api/thunderbird/addon.xpi":
                if not OUT_XPI.exists():
                    build_xpi()
                raw = OUT_XPI.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-xpinstall")
                self.send_header("Content-Disposition", 'attachment; filename="employmaxing-bridge.xpi"')
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if path == "/api/mail-config":
                info = get_public_mail_status(store)
                info["thunderbird"] = discover_thunderbird(info.get("profile_dir") or None)
                info["redirect_uris"] = {
                    "google": f"{self._base_url()}/api/oauth/google/callback",
                    "microsoft": f"{self._base_url()}/api/oauth/microsoft/callback",
                    "yahoo": f"{self._base_url()}/api/oauth/yahoo/callback",
                }
                return self._send_json(info)

            if path == "/api/forms":
                job_id = qs.get("job_id", [None])[0]
                return self._send_json({"forms": store.list_form_submissions(job_id=job_id)})

            if path == "/api/dorks":
                roles = qs.get("roles", ["Software Engineer"])[0]
                loc = qs.get("location", ["Remote"])[0]
                hours = int(qs.get("hours", ["48"])[0])
                return self._send_json(generate_ats_dorks(roles, loc, hours))

            if path.startswith("/api/files/"):
                rel = urllib.parse.unquote(path[len("/api/files/"):])
                target = (store.data_dir / rel).resolve()
                if not str(target).startswith(str(store.data_dir.resolve())):
                    return self._send_json({"error": "Forbidden path"}, 403)
                return self._send_file(target)

            if path == "/" or path == "/index.html":
                return self._send_file(WEB_DIR / "index.html")
            asset = (WEB_DIR / path.lstrip("/")).resolve()
            if str(asset).startswith(str(WEB_DIR.resolve())) and asset.exists() and asset.is_file():
                return self._send_file(asset)
            return self._send_json({"error": "Not found"}, 404)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            try:
                data = self._read_json()
            except Exception as ex:
                return self._send_json({"error": f"Invalid JSON: {ex}"}, 400)

            try:
                # ---- Zero-CLI Onboarding Upload & Auto-Extract ----
                if path == "/api/onboarding/upload-and-extract":
                    summary = {}
                    if data.get("resume_b64"):
                        fname = _safe_filename(data.get("resume_filename", "resume.pdf"), "resume.pdf")
                        dest = store.data_dir / "resume" / fname
                        dest.write_bytes(base64.b64decode(data["resume_b64"]))
                        summary["resume"] = ingest_resume(store, dest, auto_approve_direct=False)
                    elif data.get("resume_path"):
                        summary["resume"] = ingest_resume(store, Path(data["resume_path"]).expanduser().resolve(), auto_approve_direct=False)
                    elif data.get("resume_text"):
                        dest = store.data_dir / "resume" / "pasted_resume.md"
                        dest.write_text(data["resume_text"], encoding="utf-8")
                        summary["resume"] = ingest_resume(store, dest, auto_approve_direct=False)

                    if data.get("linkedin_b64"):
                        lname = _safe_filename(data.get("linkedin_filename", "Profile.pdf"), "Profile.pdf")
                        ldest = store.data_dir / lname
                        ldest.write_bytes(base64.b64decode(data["linkedin_b64"]))
                        summary["linkedin"] = ingest_linkedin(store, ldest)
                    elif data.get("linkedin_path"):
                        summary["linkedin"] = ingest_linkedin(store, Path(data["linkedin_path"]).expanduser().resolve())
                    elif data.get("linkedin_text"):
                        ldest = store.data_dir / "linkedin-profile-snapshot.md"
                        ldest.write_text(data["linkedin_text"], encoding="utf-8")
                        summary["linkedin"] = ingest_linkedin(store, ldest)

                    if data.get("linkedin_url"):
                        store.upsert_fact("social_link", "linkedin", data["linkedin_url"].strip(), source="onboarding_form", source_url=data["linkedin_url"].strip(), confidence=1.0, consent_status="pending_review", planned_usage="resume,form_fill")

                    # Auto-detect GitHub handle from resume if user didn't explicitly type it
                    gh_target = (data.get("github") or "").strip()
                    if not gh_target and summary.get("resume", {}).get("metadata", {}).get("github"):
                        gh_target = summary["resume"]["metadata"]["github"]
                    if gh_target:
                        try:
                            summary["github"] = enrich_from_github(store, gh_target)
                        except Exception as ex:
                            summary["github"] = {"warning": str(ex)}

                    web_target = (data.get("website") or "").strip()
                    if web_target:
                        try:
                            summary["website"] = enrich_from_website(store, web_target)
                        except Exception as ex:
                            summary["website"] = {"warning": str(ex)}

                    compile_master_profile(store)
                    status = _build_onboarding_status(store)
                    return self._send_json({"extracted": summary, "onboarding": status, "facts": store.list_facts()})

                if path == "/api/onboarding/complete":
                    # Save verified personal/form requirements as approved facts + preferences.md + application-data.md
                    field_map = [
                        ("identity", "name", data.get("full_name", ""), "resume,outreach_mail,form_fill"),
                        ("contact", "email", data.get("email", ""), "resume,outreach_mail,form_fill"),
                        ("contact", "phone", data.get("phone", ""), "resume,form_fill"),
                        ("contact", "city", data.get("city", ""), "resume,form_fill"),
                        ("contact", "country", data.get("country", "United States"), "form_fill"),
                        ("social_link", "linkedin", data.get("linkedin", ""), "resume,form_fill"),
                        ("social_link", "github", data.get("github", ""), "resume,form_fill"),
                        ("social_link", "portfolio", data.get("website", ""), "resume,form_fill"),
                        ("preference", "target_roles", data.get("target_roles", ""), "job_search,linkedin_fix"),
                        ("preference", "location_pref", data.get("location_pref", "Remote"), "job_search,form_fill"),
                        ("preference", "min_salary", data.get("min_salary", ""), "job_search,form_fill"),
                        ("preference", "dealbreakers", data.get("dealbreakers", ""), "job_search"),
                        ("form_default", "work_authorization", data.get("work_auth", "Yes"), "form_fill"),
                        ("form_default", "requires_sponsorship", data.get("sponsorship", "No"), "form_fill"),
                        ("form_default", "notice_period", data.get("notice_period", "2 weeks from offer acceptance"), "form_fill"),
                        ("form_default", "eeo_default", data.get("eeo_default", "Decline to self-identify"), "form_fill"),
                    ]
                    for cat, key, val, usage in field_map:
                        if str(val).strip():
                            store.upsert_fact(cat, key, str(val).strip(), source="onboarding_verified", confidence=1.0, consent_status="approved", planned_usage=usage)

                    if data.get("approve_all_extracted"):
                        store.approve_all_pending_facts()

                    # Write clean preferences.md & application-data.md so all skills read them seamlessly
                    roles_lines = "\n".join(f"- {r.strip()}" for r in str(data.get("target_roles", "")).split(",") if r.strip()) or "- Software Engineer"
                    deals_lines = "\n".join(f"- {d.strip()}" for d in str(data.get("dealbreakers", "")).split(",") if d.strip()) or "- None specified"
                    (store.data_dir / "preferences.md").write_text(
                        f"# Job Preferences\n\n## Target Roles\n{roles_lines}\n\n"
                        f"## Location\n{data.get('location_pref', 'Remote')}\n\n"
                        f"## Compensation\nMinimum target: {data.get('min_salary') or 'Market rate'}\n\n"
                        f"## Dealbreakers\n{deals_lines}\n",
                        encoding="utf-8",
                    )

                    full_n = str(data.get("full_name", "")).strip()
                    fn = full_n.split()[0] if full_n.split() else ""
                    ln = " ".join(full_n.split()[1:]) if len(full_n.split()) > 1 else ""
                    (store.data_dir / "application-data.md").write_text(
                        f"# Application Data\n\n## Personal Information\n"
                        f"- First Name: {fn}\n- Last Name: {ln}\n- Email: {data.get('email', '')}\n"
                        f"- Phone: {data.get('phone', '')}\n- City: {data.get('city', '')}\n- Country: {data.get('country', 'United States')}\n\n"
                        f"## Online Profiles\n- LinkedIn: {data.get('linkedin', '')}\n- GitHub: {data.get('github', '')}\n- Portfolio: {data.get('website', '')}\n\n"
                        f"## Standard Answers\n- How did you hear about us: Company Website / Careers Page\n"
                        f"- Previously worked at this company: No\n- Authorized to work in the US: {data.get('work_auth', 'Yes')}\n"
                        f"- Requires visa sponsorship: {data.get('sponsorship', 'No')}\n- Earliest start date: {data.get('notice_period', '2 weeks from offer acceptance')}\n\n"
                        f"## EEO / Voluntary Disclosures\n- Gender: {data.get('eeo_default', 'Decline to self-identify')}\n"
                        f"- Race/Ethnicity: {data.get('eeo_default', 'Decline to self-identify')}\n"
                        f"- Veteran status: I don't wish to answer\n- Disability: I don't wish to answer\n",
                        encoding="utf-8",
                    )

                    saved_state = {**data, "completed": True, "completed_at": store._now()}
                    (store.data_dir / "onboarding-state.json").write_text(json.dumps(saved_state, indent=2), encoding="utf-8")
                    compile_master_profile(store)
                    store.log_event("onboarding_completed", f"Completed First-Time Setup for {full_n or 'candidate'} (profile, preferences & form defaults saved)")
                    return self._send_json({"status": "completed", "onboarding": _build_onboarding_status(store)})

                # ---- OAuth2 Start (Google / Microsoft / Yahoo) ----
                m_o_start = re.match(r'^/api/oauth/(google|microsoft|yahoo)/start$', path)
                if m_o_start:
                    provider = m_o_start.group(1)
                    redirect_uri = f"{self._base_url()}/api/oauth/{provider}/callback"
                    res = start_oauth_flow(
                        store,
                        provider=provider,
                        redirect_uri=redirect_uri,
                        client_id=data.get("client_id", ""),
                        client_secret=data.get("client_secret", ""),
                        display_name=data.get("display_name", ""),
                    )
                    return self._send_json(res)

                if path == "/api/thunderbird/install-addon":
                    return self._send_json(install_addon_into_profile((data.get("profile_dir") or "").strip() or None))

                if path == "/api/thunderbird/bridge/poll":
                    if self.headers.get("X-Employmaxing-Bridge") != "employmaxing-tb-v1":
                        return self._send_json({"error": "Missing Employmaxing Bridge header"}, 403)
                    record_bridge_heartbeat(version=data.get("version", ""), accounts=data.get("accounts"))
                    cfg = get_public_mail_status(store)
                    from_email = cfg.get("email", "")
                    queued = store.list_emails(status="queued_for_bridge")
                    out_jobs = []
                    for e in queued[:5]:
                        # Mark in-flight so it is never sent twice
                        store.update_email(e["id"], status="sending_via_bridge")
                        out_jobs.append({
                            "id": e["id"],
                            "from_email": from_email,
                            "recipient_email": e["recipient_email"],
                            "subject": e["subject"],
                            "body": e["body"],
                        })
                    return self._send_json({"ok": True, "queue": out_jobs})

                if path == "/api/thunderbird/bridge/ack":
                    if self.headers.get("X-Employmaxing-Bridge") != "employmaxing-tb-v1":
                        return self._send_json({"error": "Missing Employmaxing Bridge header"}, 403)
                    eid = int(data["id"])
                    if data.get("sent"):
                        store.update_email(
                            eid,
                            direction="outbound_sent",
                            status="sent",
                            message_id=data.get("message_id", ""),
                            sent_or_received_at=store._now(),
                            error_msg="",
                        )
                        store.log_event("email_sent_thunderbird_auto", f"Thunderbird Auto-Send Bridge sent email #{eid} automatically (from {data.get('from_email', '')})")
                    else:
                        store.update_email(eid, status="failed", error_msg=str(data.get("error", "Unknown Thunderbird send error")))
                        store.log_event("email_failed_thunderbird", f"Thunderbird Bridge failed sending email #{eid}: {data.get('error', '')}")
                    return self._send_json({"ok": True, "id": eid})

                if path == "/api/thunderbird/connect":
                    custom_p = (data.get("profile_dir") or "").strip() or None
                    disc = discover_thunderbird(custom_p)
                    selected_email = (data.get("email") or "").strip()
                    chosen_acc = next((a for a in disc["accounts"] if a["email"].lower() == selected_email.lower()), None) if selected_email else (disc["accounts"][0] if disc["accounts"] else None)
                    email_addr = selected_email or (chosen_acc["email"] if chosen_acc else "")
                    saved = save_single_provider_config(
                        store,
                        "thunderbird",
                        {
                            "auth_mode": "thunderbird_local",
                            "email": email_addr,
                            "display_name": (chosen_acc["display_name"] if chosen_acc else data.get("display_name", "")),
                            "profile_dir": (chosen_acc["profile_dir"] if chosen_acc else (disc["profiles"][0] if disc["profiles"] else (custom_p or ""))),
                            "mail_dir": chosen_acc["mail_dir"] if chosen_acc else "",
                            "inbox_files": disc["inbox_files"],
                            "sent_files": disc["sent_files"],
                            "command": disc["command"],
                            "connected": True,
                        },
                    )
                    return self._send_json({"status": "connected", "provider": "thunderbird", "email": saved["email"], "thunderbird": disc})

                if path == "/api/mail-config":
                    provider = (data.get("provider") or "").lower().strip()
                    saved = save_single_provider_config(store, provider, {**data, "connected": True})
                    return self._send_json({"status": "saved", "provider": saved["provider"], "mail": get_public_mail_status(store)})

                if path == "/api/mail-config/disconnect":
                    disconnect_mail_provider(store)
                    return self._send_json({"status": "disconnected", "mail": get_public_mail_status(store)})

                # ---- Existing Core Routes ----
                if path == "/api/facts":
                    fid = store.upsert_fact(
                        category=data["category"],
                        fact_key=data["fact_key"],
                        fact_value=data["fact_value"],
                        source=data.get("source", "user_input"),
                        source_url=data.get("source_url", ""),
                        confidence=float(data.get("confidence", 1.0)),
                        consent_status=data.get("consent_status", "approved"),
                        planned_usage=data.get("planned_usage", "resume,outreach_mail,form_fill"),
                    )
                    compile_master_profile(store)
                    return self._send_json({"id": fid, "status": "saved"}, 201)

                if path == "/api/facts/approve-all":
                    n = store.approve_all_pending_facts(source_filter=data.get("source"))
                    compile_master_profile(store)
                    return self._send_json({"approved_count": n})

                if path == "/api/enrich":
                    res = {}
                    if data.get("resume_b64"):
                        fname = _safe_filename(data.get("resume_filename", "resume.pdf"), "resume.pdf")
                        dest = store.data_dir / "resume" / fname
                        dest.write_bytes(base64.b64decode(data["resume_b64"]))
                        res["resume"] = ingest_resume(store, dest, auto_approve_direct=bool(data.get("auto_approve_resume", False)))
                    elif data.get("resume_path"):
                        res["resume"] = ingest_resume(store, Path(data["resume_path"]).expanduser().resolve(), auto_approve_direct=bool(data.get("auto_approve_resume", False)))
                    elif data.get("resume_text"):
                        p = store.data_dir / "resume" / "uploaded_resume.md"
                        p.write_text(data["resume_text"], encoding="utf-8")
                        res["resume"] = ingest_resume(store, p, auto_approve_direct=bool(data.get("auto_approve_resume", False)))

                    if data.get("linkedin_b64"):
                        lname = _safe_filename(data.get("linkedin_filename", "Profile.pdf"), "Profile.pdf")
                        ldest = store.data_dir / lname
                        ldest.write_bytes(base64.b64decode(data["linkedin_b64"]))
                        res["linkedin"] = ingest_linkedin(store, ldest)
                    elif data.get("linkedin_path"):
                        res["linkedin"] = ingest_linkedin(store, Path(data["linkedin_path"]).expanduser().resolve())
                    elif data.get("linkedin_text"):
                        lp = store.data_dir / "linkedin-profile-snapshot.md"
                        lp.write_text(data["linkedin_text"], encoding="utf-8")
                        res["linkedin"] = ingest_linkedin(store, lp)

                    if data.get("github"):
                        res["github"] = enrich_from_github(store, data["github"])
                    if data.get("website"):
                        res["website"] = enrich_from_website(store, data["website"])
                    master = compile_master_profile(store)
                    res["pending_review_count"] = master["pending_review_count"]
                    res["approved_count"] = master["approved_count"]
                    return self._send_json(res)

                if path == "/api/linkedin-audit":
                    li_path = store.data_dir / "linkedin-profile-snapshot.md"
                    if data.get("linkedin_b64"):
                        lname = _safe_filename(data.get("linkedin_filename", "Profile.pdf"), "Profile.pdf")
                        li_path = store.data_dir / lname
                        li_path.write_bytes(base64.b64decode(data["linkedin_b64"]))
                    elif data.get("linkedin_path"):
                        li_path = Path(data["linkedin_path"]).expanduser().resolve()
                    elif data.get("linkedin_text"):
                        li_path.write_text(data["linkedin_text"], encoding="utf-8")
                    res_path = Path(data["resume_path"]).expanduser().resolve() if data.get("resume_path") else (store.data_dir / "resume" / "resume.md")
                    if not li_path.exists() or not res_path.exists():
                        return self._send_json({"error": "Upload your Resume in 00 // Get Started and drop your LinkedIn Profile.pdf or pasted text first."}, 400)
                    audit = audit_linkedin_vs_resume(
                        load_linkedin_data(li_path),
                        res_path,
                        (store.data_dir / "profile.md") if (store.data_dir / "profile.md").exists() else None,
                        (store.data_dir / "preferences.md") if (store.data_dir / "preferences.md").exists() else None,
                    )
                    md = render_markdown_report(audit)
                    (store.data_dir / "linkedin-fixes.md").write_text(md, encoding="utf-8")
                    store.log_event("linkedin_audited", f"LinkedIn Audit: {audit['discrepancy_count']} discrepancies, {audit['turn_off_count']} turn-offs (SEO {audit['credibility_and_seo_score']}/100)")
                    return self._send_json({"audit": audit, "markdown": md})

                if path == "/api/jobs":
                    slug = data.get("id") or re.sub(r'[^a-z0-9]+', '-', f"{data.get('company', 'company')}-{data.get('role', 'role')}".lower()).strip("-")
                    data["id"] = slug
                    jdir = store.data_dir / "jobs" / slug
                    jdir.mkdir(parents=True, exist_ok=True)
                    data["folder_path"] = str(jdir)
                    if data.get("posting_text"):
                        pp = jdir / "posting.md"
                        pp.write_text(data["posting_text"], encoding="utf-8")
                        ja = audit_job_posting(pp, days_old=data.get("days_old"), has_referral=bool(data.get("has_referral")))
                        data.setdefault("ghost_risk", ja["ghost_risk"])
                        data.setdefault("ghost_score", ja["ghost_score_100"])
                        data.setdefault("priority_tier", ja["priority_tier"])
                    jid = store.upsert_job(data)
                    return self._send_json({"id": jid, "job": store.get_job(jid)}, 201)

                if path == "/api/emails/queue":
                    out = queue_outbound_email(
                        store,
                        recipient_email=data["recipient_email"],
                        subject=data["subject"],
                        body=data["body"],
                        recipient_name=data.get("recipient_name", ""),
                        job_id=data.get("job_id", ""),
                        classification=data.get("classification", "outreach_touch_1"),
                        facts_used=data.get("facts_used", []),
                        in_reply_to=data.get("in_reply_to", ""),
                        auto_approve=bool(data.get("auto_approve", False)),
                    )
                    return self._send_json(out, 201)

                m_eapp = re.match(r'^/api/emails/(\d+)/approve$', path)
                if m_eapp:
                    eid = int(m_eapp.group(1))
                    ok = store.update_email(eid, status="approved", direction="outbound_approved")
                    return self._send_json({"updated": ok, "id": eid})

                m_esent = re.match(r'^/api/emails/(\d+)/mark-sent$', path)
                if m_esent:
                    eid = int(m_esent.group(1))
                    ok = store.update_email(eid, status="sent", direction="outbound_sent", sent_or_received_at=store._now())
                    if ok:
                        store.log_event("email_marked_sent", f"User confirmed email #{eid} sent via Thunderbird")
                    return self._send_json({"updated": ok, "id": eid})

                if path == "/api/emails/send":
                    return self._send_json(send_approved_emails(store, email_id=data.get("id"), dry_run=bool(data.get("dry_run", False))))

                if path == "/api/emails/scan-inbox":
                    return self._send_json(scan_inbox(store, days=int(data.get("days", 14)), limit=int(data.get("limit", 50))))

                if path == "/api/email-find":
                    return self._send_json(find_emails(data["first"], data["last"], data["domain"]))

                if path == "/api/forms/plan":
                    plan = build_transparent_form_plan(store, data["job_id"], data.get("form_url", ""))
                    return self._send_json(plan, 201)

                m_fexec = re.match(r'^/api/forms/(\d+)/execute$', path)
                if m_fexec:
                    fid = int(m_fexec.group(1))
                    return self._send_json(execute_cdp_fill(store, fid, cdp_port=int(data.get("cdp_port", 9222))))

                return self._send_json({"error": "Endpoint not found"}, 404)
            except KeyError as ke:
                return self._send_json({"error": f"Missing required field: {ke}"}, 400)
            except ValueError as ve:
                return self._send_json({"error": str(ve)}, 400)
            except Exception as ex:
                return self._send_json({"error": str(ex)}, 500)

        def do_PATCH(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            try:
                data = self._read_json()
            except Exception as ex:
                return self._send_json({"error": f"Invalid JSON: {ex}"}, 400)

            m_fact = re.match(r'^/api/facts/(\d+)$', path)
            if m_fact:
                fid = int(m_fact.group(1))
                ok = store.set_fact_consent(
                    fid,
                    status=data.get("consent_status", "approved"),
                    edited_value=data.get("fact_value"),
                    user_note=data.get("user_note"),
                )
                compile_master_profile(store)
                return self._send_json({"updated": ok, "id": fid})

            m_job = re.match(r'^/api/jobs/([^/]+)$', path)
            if m_job:
                jid = urllib.parse.unquote(m_job.group(1))
                data["id"] = jid
                store.upsert_job(data)
                return self._send_json({"updated": True, "job": store.get_job(jid)})

            m_form = re.match(r'^/api/forms/(\d+)$', path)
            if m_form:
                sub_id = int(m_form.group(1))
                ok = store.update_form_status(sub_id, status=data.get("status", "approved"), field_plan=data.get("field_plan"))
                return self._send_json({"updated": ok, "id": sub_id})

            return self._send_json({"error": "Endpoint not found"}, 404)

    return EmploymaxingHandler


def run_server(host: str = "127.0.0.1", port: int = 8787, data_dir: str | None = None, open_browser: bool = True):
    store = EmploymaxingStore(data_dir)
    srv = ThreadingHTTPServer((host, port), make_handler(store))
    url = f"http://{host}:{port}"
    print(f"Employmaxing Local Web App running at {url} (data: {store.data_dir})", flush=True)
    if open_browser:
        def _open():
            time.sleep(0.5)
            try:
                webbrowser.open(url)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Employmaxing server.")
        srv.server_close()


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Local Web App")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser window")
    args = parser.parse_args()
    run_server(args.host, args.port, args.data_dir, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
