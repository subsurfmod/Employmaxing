---
name: web-dashboard
description: Launch the Neo-Brutalist High-Contrast local web dashboard (http://127.0.0.1:8787) for complete non-CLI control over personal info consent, profile building, LinkedIn auditing, sent mail & inbox replies, potential jobs, custom applications, and complex ATS form fills
argument-hint: "optional port number (default 8787)"
---

# Local Neo-Brutalist Web Dashboard Skill

Provide the user a complete, zero-CLI local web interface bound strictly to `127.0.0.1` (private to their machine).

## Launch

```bash
./bin/employmaxing serve --port 8787
```

Open `http://127.0.0.1:8787` to access all 6 command views:
1. **01 // Overview**: Live KPI counters, urgent consent/interview banners, and the full Transparency Activity Audit Log.
2. **02 // Info & Consent**: Run Resume/LinkedIn/GitHub/Website discovery and Approve, Edit, or Exclude every personal fact Employmaxing plans to use.
3. **03 // Profile & LinkedIn**: View your compiled User-Approved Master Profile and run the 12-point LinkedIn Discrepancy & Turn-Off Auditor with 1-click copyable Headlines & About fixes.
4. **04 // Jobs & Apps**: Triage potential jobs for Ghost-Job risk, launch `<48h` direct ATS searches, move pipeline stages, inspect tailored resumes (`0–100` score), and download ATS PDF/DOCX deliverables.
5. **05 // Mailbox & Sent**: Scan IMAP inbox replies, configure local credentials, compose MX-checked plain-text outreach, approve outbox drafts, and inspect every email sent + exact personal facts used.
6. **06 // Complex Forms**: Inspect every planned ATS field (75th-pct salary anchor, YOE, knockout warnings, PDF uploads), execute Chrome CDP auto-fill, and review pre-submit screenshots.
