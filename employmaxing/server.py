#!/usr/bin/env python3
"""
server.py - Local-only (127.0.0.1) REST API & Web Dashboard Server for Employmaxing.
Provides a complete non-CLI interface over:
  - Transparent Information & Consent Ledger (/api/facts)
  - Personal Profile Enricher (/api/enrich)
  - LinkedIn Discrepancy & Turn-Off Auditor (/api/linkedin-audit)
  - Potential Jobs & Custom Applications (/api/jobs, /api/jobs/<id>/artifacts)
  - Mailbox Reply Scanner, Outbox Approval Queue & Sent Mail Log (/api/emails/*)
  - Complex ATS Form-Fill Plans & CDP Execution (/api/forms/*)
Frontend UI files are decoupled inside `web/` (built once user selects preferred visual style).
Licensed under GNU GPL v3.0.
"""

import argparse
import json
import mimetypes
import re
import sys
import urllib.parse
from http import HTTPStatus
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
from employmaxing.mailbox import (
    load_mail_config,
    queue_outbound_email,
    save_mail_config,
    scan_inbox,
    send_approved_emails,
)
from employmaxing.store import EmploymaxingStore
from linkedin_audit import audit_linkedin_vs_resume, load_linkedin_data, render_markdown_report
from optimizer import audit_job_posting, audit_resume, find_emails, generate_ats_dorks


def make_handler(store: EmploymaxingStore):
    class EmploymaxingHandler(BaseHTTPRequestHandler):
        server_version = "EmploymaxingLocal/1.0"

        def _send_json(self, payload: dict | list, status: int = 200):
            raw = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
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
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            return json.loads(body) if body.strip() else {}

        def log_message(self, format, *args):
            # Clean concise server logs
            sys.stderr.write(f"[employmaxing-web] {self.address_string()} - {format % args}\n")

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            # ---- API Routes ----
            if path == "/api/health":
                return self._send_json({"status": "ok", "ui_installed": (WEB_DIR / "index.html").exists(), "data_dir": str(store.data_dir)})

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

            if path == "/api/mail-config":
                cfg = load_mail_config(store)
                safe_cfg = {k: v for k, v in cfg.items() if k != "password"}
                safe_cfg["configured"] = bool(cfg.get("email") and cfg.get("password"))
                return self._send_json(safe_cfg)

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

            # ---- Static Frontend (web/) ----
            if path == "/" or path == "/index.html":
                idx = WEB_DIR / "index.html"
                if idx.exists():
                    return self._send_file(idx)
                return self._send_json({
                    "app": "Employmaxing Local Server",
                    "ui_status": "Awaiting UI visual style selection before rendering web/index.html",
                    "api_endpoints": [
                        "/api/dashboard", "/api/facts", "/api/profile", "/api/jobs",
                        "/api/emails", "/api/forms", "/api/dorks", "/api/mail-config",
                    ],
                })
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
                    if data.get("resume_path"):
                        res["resume"] = ingest_resume(store, Path(data["resume_path"]).expanduser().resolve(), auto_approve_direct=bool(data.get("auto_approve_resume", False)))
                    if data.get("resume_text"):
                        p = store.data_dir / "resume" / "uploaded_resume.md"
                        p.write_text(data["resume_text"], encoding="utf-8")
                        res["resume"] = ingest_resume(store, p, auto_approve_direct=bool(data.get("auto_approve_resume", False)))
                    if data.get("linkedin_path"):
                        res["linkedin"] = ingest_linkedin(store, Path(data["linkedin_path"]).expanduser().resolve())
                    if data.get("linkedin_text"):
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
                    li_path = Path(data["linkedin_path"]).expanduser().resolve() if data.get("linkedin_path") else (store.data_dir / "linkedin-profile-snapshot.md")
                    if data.get("linkedin_text"):
                        li_path.write_text(data["linkedin_text"], encoding="utf-8")
                    res_path = Path(data["resume_path"]).expanduser().resolve() if data.get("resume_path") else (store.data_dir / "resume" / "resume.md")
                    if not li_path.exists() or not res_path.exists():
                        return self._send_json({"error": "Both LinkedIn profile and Resume are required for discrepancy audit."}, 400)
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

                if path == "/api/mail-config":
                    save_mail_config(store, data)
                    return self._send_json({"status": "saved"})

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


def run_server(host: str = "127.0.0.1", port: int = 8787, data_dir: str | None = None):
    store = EmploymaxingStore(data_dir)
    srv = ThreadingHTTPServer((host, port), make_handler(store))
    print(f"Employmaxing Local Server running at http://{host}:{port} (data: {store.data_dir})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Employmaxing server.")
        srv.server_close()


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Local Webserver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()
    run_server(args.host, args.port, args.data_dir)


if __name__ == "__main__":
    main()
