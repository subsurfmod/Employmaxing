#!/usr/bin/env python3
"""
Automated zero-network unit & integration test suite for Employmaxing v1.4 (GPL-3.0).
Run via: python3 -m unittest discover -s tests -v
"""

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "shared" / "scripts"))

from employmaxing.build_xpi import build_xpi
from employmaxing.enricher import compile_master_profile, ingest_resume
from employmaxing.form_filler import build_transparent_form_plan, detect_ats
from employmaxing.mailbox import queue_outbound_email, scan_inbox, send_approved_emails
from employmaxing.scheduler import generate_due_followups
from employmaxing.server import make_handler
from employmaxing.store import EmploymaxingStore
from employmaxing.thunderbird import discover_thunderbird, read_recent_mbox_messages
from linkedin_audit import audit_linkedin_vs_resume, load_linkedin_data
from optimizer import audit_mail, audit_resume, build_form_plan

SAMPLE_RESUME = """# Alex Mercer
alex.mercer@example.dev | (415) 555-0192 | linkedin.com/in/alex-mercer | github.com/alexmercer-dev

## Summary
Staff Infrastructure Engineer with 9 years scaling distributed systems, Kubernetes (K8s), Go, and AWS cloud platforms. Reduced annual cloud compute costs by $1.2M while maintaining 99.99% SLA across 180k RPS payment workloads.

## Experience
### Staff Infrastructure Engineer | Orbital Cloud (Jan 2022 — Present)
- Architected multi-region Kubernetes (K8s) and Go microservices handling 180k RPS, cutting p99 latency by 41% across 4 AWS regions.
- Automated Terraform and Continuous Integration (CI/CD) deployment pipelines across 28 services, saving $420k annually in cloud spend.
- Engineered zero-downtime database failover across PostgreSQL (Postgres) shards supporting 12M daily active transactions with 99.99% uptime.
- Scaled Kafka event ingestion pipelines processing 18TB daily across 450 enterprise accounts while cutting broker cost by 34%.
- Redesigned OpenTelemetry tracing and Prometheus alerting for 6 engineering squads, decreasing incident MTTR by 58%.
- Spearheaded service-mesh security hardening across 90 production containers, passing SOC2 Type II audit with zero findings.

### Senior Platform Engineer | Nimbus Systems (Mar 2019 - Dec 2021)
- Built Go and Python deployment automation reducing release lead time by 64% across 14 backend teams.
- Migrated 22 legacy monolith modules onto AWS EKS clusters, trimming infrastructure overhead by $310k annually.
- Optimized PostgreSQL indexing and query caching to reduce peak checkout latency from 480ms to 115ms across 3 global regions.
- Mentored 7 backend engineers on distributed systems reliability, lifting quarterly on-call SLA compliance from 98.4% to 99.95%.

## Skills
Go (Golang), Python, Kubernetes (K8s), AWS, Terraform, Kafka, PostgreSQL (Postgres), Continuous Integration (CI/CD), Distributed Systems, OpenTelemetry

## Education
B.S. Computer Science - UC Berkeley (2017)
"""

SAMPLE_JD = """# Staff Infrastructure Engineer - Stripe
Location: Remote, US (2 days per week in-office SF optional)
Compensation: $200,000 - $240,000 base + equity

We need a Staff Infrastructure Engineer experienced in Go, Python, Kubernetes, AWS, Terraform, Kafka, PostgreSQL, CI/CD, and Distributed Systems.
"""


class TestEmploymaxingSuite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = EmploymaxingStore(self.root / "data")

    def tearDown(self):
        self.tmp.cleanup()

    def test_consent_gate_and_profile_compilation(self):
        rf = self.root / "resume.md"
        rf.write_text(SAMPLE_RESUME, encoding="utf-8")
        ingest_resume(self.store, rf, auto_approve_direct=False)
        m0 = compile_master_profile(self.store)
        self.assertGreaterEqual(m0["pending_review_count"], 5)
        self.assertEqual(m0["approved_count"], 0)
        n = self.store.approve_all_pending_facts()
        m1 = compile_master_profile(self.store)
        self.assertEqual(m1["approved_count"], n)
        self.assertEqual(m1["pending_review_count"], 0)

    def test_empirical_resume_and_mail_gates(self):
        rf = self.root / "resume.md"
        jf = self.root / "posting.md"
        rf.write_text(SAMPLE_RESUME, encoding="utf-8")
        jf.write_text(SAMPLE_JD, encoding="utf-8")
        res = audit_resume(rf, jf, autofix=True)
        self.assertGreaterEqual(res["total_score"], 85)
        self.assertTrue(res["ready_to_ship"])
        self.assertEqual(len(res["autofixes_applied"]), 1)

        mf = self.root / "cold.md"
        mf.write_text(
            "Subject: scaling k8s pipelines at stripe\n\n"
            "Hi Priya,\n\nSaw Stripe is expanding multi-region Kubernetes throughput.\n\n"
            "At Orbital Cloud our team cut p99 latency by 41% across 180k RPS Go services while saving $420k/yr.\n\n"
            "Worth a quick look at a 3-bullet breakdown?\n",
            encoding="utf-8",
        )
        mres = audit_mail(mf, mode="cold-email")
        self.assertGreaterEqual(mres["score"], 85)

        li_note = self.root / "note.md"
        li_note.write_text("x" * 310, encoding="utf-8")
        nres = audit_mail(li_note, mode="linkedin-note")
        self.assertFalse(nres["ready_to_send"])

    def test_linkedin_discrepancy_and_turnoff_auditor(self):
        rf = self.root / "resume.md"
        lf = self.root / "linkedin.md"
        rf.write_text(SAMPLE_RESUME, encoding="utf-8")
        lf.write_text(
            "# Alex Mercer\n"
            "Headline: Passionate Ex-Nimbus Ninja | Actively Seeking Opportunities! #OpenToWork\n"
            "https://linkedin.com/in/alex-mercer-99ab12ef\n"
            "310 connections\n\n"
            "## Experience\n"
            "### Senior Infrastructure Engineer | Orbital Cloud (Jun 2022 - Present)\n"
            "### Co-Founder | Stealth AI (Jan 2024 - Present)\n"
            "### Platform Engineer | Nimbus Systems (Mar 2019 - Nov 2020)\n",
            encoding="utf-8",
        )
        audit = audit_linkedin_vs_resume(load_linkedin_data(lf), rf)
        self.assertGreaterEqual(audit["discrepancy_count"], 3)
        self.assertGreaterEqual(audit["turn_off_count"], 4)
        self.assertEqual(len(audit["turnkey_fixes"]["headlines_220_char"]), 3)

    def test_form_plan_salary_75th_percentile_and_ats_detection(self):
        self.assertEqual(detect_ats("https://jobs.ashbyhq.com/stripe/123"), "ashby")
        self.assertEqual(detect_ats("https://boards.greenhouse.io/anthropic/jobs/9"), "greenhouse")
        self.assertEqual(detect_ats("https://jobs.lever.co/datadog/abc"), "lever")
        self.assertEqual(detect_ats("https://acme.wd5.myworkdayjobs.com/ext"), "workday")
        jf = self.root / "posting.md"
        jf.write_text(SAMPLE_JD, encoding="utf-8")
        fp = build_form_plan(jf)
        self.assertEqual(fp["salary_strategy"]["strict_numeric_input"], 230000)
        self.assertTrue(any("HYBRID" in w for w in fp["knockout_warnings"]))

    def test_thunderbird_mbox_and_maildir_readers(self):
        now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        # Maildir test
        mdir = self.root / "INBOX"
        (mdir / "cur").mkdir(parents=True)
        (mdir / "cur" / "msg1.eml").write_text(
            f"From: recruiter@stripe.com\nTo: alex@gmail.com\nSubject: Panel Interview\nDate: {now_rfc}\nMessage-ID: <md1@stripe.com>\n\nPick a Calendly slot!\n",
            encoding="utf-8",
        )
        msgs = read_recent_mbox_messages(mdir, days=7)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["subject"], "Panel Interview")

        # XPI archive build test
        xpi = build_xpi()
        with zipfile.ZipFile(xpi, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode())
            self.assertIn("compose.send", manifest["permissions"])
            self.assertIn("messagesRead", manifest["permissions"])

    def test_followup_scheduler_day3_and_day7(self):
        old_ts = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d %H:%M:%S")
        self.store.record_email({
            "direction": "outbound_sent",
            "status": "sent",
            "recipient_name": "Priya Nair",
            "recipient_email": "priya@stripe.com",
            "subject": "scaling k8s at stripe",
            "body": "Short note.",
            "message_id": "<orig1@example.dev>",
            "classification": "outreach_touch_1",
            "sent_or_received_at": old_ts,
        })
        res = generate_due_followups(self.store)
        self.assertEqual(len(res["queued_followups"]), 1)
        self.assertEqual(res["queued_followups"][0]["touch"], "day3")
        # Second run should be idempotent (no duplicates!)
        res2 = generate_due_followups(self.store)
        self.assertEqual(len(res2["queued_followups"]), 0)

    def test_live_server_onboarding_bridge_and_resume_editor(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.store))
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()

        def post(path, payload, hdrs=None):
            h = {"Content-Type": "application/json", **(hdrs or {})}
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(payload).encode(), headers=h, method="POST")
            return json.loads(urllib.request.urlopen(req).read().decode())

        try:
            # 1. Onboarding upload & complete
            ext = post("/api/onboarding/upload-and-extract", {
                "resume_filename": "resume.md",
                "resume_b64": base64.b64encode(SAMPLE_RESUME.encode()).decode(),
            })
            self.assertEqual(ext["onboarding"]["defaults"]["full_name"], "Alex Mercer")
            post("/api/onboarding/complete", {**ext["onboarding"]["defaults"], "approve_all_extracted": True})

            # 2. Job creation + Live Resume Editor/Scorer + Universal Autofill Bookmarklet + URL normalization
            job = post("/api/jobs", {"company": "Stripe", "role": "Staff Infrastructure Engineer", "url": "jobs.ashbyhq.com/stripe/1", "posting_text": SAMPLE_JD})
            self.assertEqual(job["job"]["url"], "https://jobs.ashbyhq.com/stripe/1")
            r_scored = post(f"/api/jobs/{job['id']}/resume", {"content": SAMPLE_RESUME, "autofix": True})
            self.assertGreaterEqual(r_scored["audit"]["total_score"], 85)

            plan = post("/api/forms/plan", {"job_id": job["id"]})
            self.assertTrue(plan["autofill_bookmarklet"].startswith("javascript:(function(P){"))
            self.assertEqual(plan["form_url"], "https://jobs.ashbyhq.com/stripe/1")
            forms_resp = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/forms").read().decode())
            self.assertIn("browser_cdp_available", forms_resp)
            self.assertEqual(len(forms_resp["forms"]), 1)
            self.assertTrue(forms_resp["forms"][0]["autofill_script"].startswith("(function(P){"))

            # 3. Thunderbird Bridge CORS Preflight (OPTIONS) + Security Guard + Poll
            opt_req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/thunderbird/bridge/poll",
                headers={"Origin": "moz-extension://test-addon-uuid", "Access-Control-Request-Headers": "Content-Type, X-Employmaxing-Bridge"},
                method="OPTIONS",
            )
            with urllib.request.urlopen(opt_req) as opt_resp:
                self.assertEqual(opt_resp.status, 204)
                self.assertEqual(opt_resp.headers.get("Access-Control-Allow-Origin"), "moz-extension://test-addon-uuid")
                self.assertIn("X-Employmaxing-Bridge", opt_resp.headers.get("Access-Control-Allow-Headers", ""))

            evil_opt = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/thunderbird/bridge/poll",
                headers={"Origin": "https://evil.example"},
                method="OPTIONS",
            )
            with urllib.request.urlopen(evil_opt) as evil_resp:
                self.assertIsNone(evil_resp.headers.get("Access-Control-Allow-Origin"))

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                post("/api/thunderbird/bridge/poll", {})
            self.assertEqual(ctx.exception.code, 403)

            post("/api/thunderbird/connect", {"email": "alex@gmail.com"})
            hdr = {"X-Employmaxing-Bridge": "employmaxing-tb-v1", "Origin": "moz-extension://test-addon-uuid"}
            poll_res = post("/api/thunderbird/bridge/poll", {
                "version": "1.5.0",
                "accounts": [{"email": "alex@gmail.com"}],
                "recent_inbox": [{
                    "from": "Priya <priya@stripe.com>",
                    "subject": "Interview Invitation - Stripe",
                    "body": "Please book your panel interview on Calendly!",
                    "message_id": "<live-msg-1@stripe.com>",
                }],
            }, hdr)
            self.assertEqual(poll_res["ingested_replies"], 1)
            self.assertEqual(self.store.get_job(job["id"])["stage"], "Onsite / Final")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
