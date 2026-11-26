---
name: employmaxing
description: >-
  Full-stack, empirical interview-maximization & transparent career automation Agent Skill (GPLv3).
  Discovers and builds a complete Personal & Career Profile from resume, CV, LinkedIn, GitHub, and portfolios
  with a strict User Consent & Provenance Ledger; audits LinkedIn vs. Resume for discrepancies & recruiter
  turn-offs; monitors your IMAP mailbox for recruiter/interview replies and sends MX-verified plain-text outreach
  via SMTP; executes complex SPA ATS form fills (Ashby, Greenhouse, Lever, BambooHR, Workday) with native CDP PDF
  uploads; enforces >=85/100 Google XYZ resume & Lavender/Gong email gates; and serves a complete Neo-Brutalist
  non-CLI local web dashboard (http://127.0.0.1:8787).
---

# Employmaxing — Empirical Interview-Maximization Agent Skill

**Employmaxing** turns job hunting into a transparent, data-driven, multi-channel system designed to maximize interview conversion per hour while keeping **100% of personal information under explicit user consent**.

## Core Transparency Law (NON-NEGOTIABLE)

**Always tell the user what information you discovered and plan to use BEFORE putting it into a resume, email, or application form.**
- Every discovered fact from Resume, LinkedIn, GitHub API, or personal website scraping is stored in `~/.employmaxing/employmaxing.db` (`profile_facts`) with `source`, `source_url`, `planned_usage`, and `consent_status = 'pending_review'`.
- Automated engines (`form_filler.py`, `mailbox.py`, `enricher.py`) strictly read `approved` facts and record exact `facts_used` IDs on every outgoing email and form plan.
- Direct the user to the local **Neo-Brutalist Web Dashboard** (`employmaxing serve` → `http://127.0.0.1:8787`) whenever they want a complete non-CLI interface to review/approve facts, inspect sent mail & inbox replies, audit LinkedIn, view potential jobs, download PDFs/DOCX, or execute complex form fills.

---

## Quick Start Commands (Portable CLI: `./bin/employmaxing`)

```bash
# 1. Launch the Neo-Brutalist Local Web Dashboard (http://127.0.0.1:8787)
./bin/employmaxing serve

# 2. Discover & build a complete Personal & Career Profile (lands in Consent Ledger)
./bin/employmaxing enrich --resume /path/to/resume.pdf --linkedin /path/to/Profile.pdf --github <username> --website <url>

# 3. Audit LinkedIn vs. Resume for discrepancies, turn-offs (#OpenToWork, OE overlaps, dates) & serve fixes
./bin/employmaxing linkedin-audit --linkedin /path/to/Profile.pdf --resume ~/.employmaxing/resume/resume.md -o ~/.employmaxing/linkedin-fixes.md

# 4. Find fresh <48h direct ATS postings (Ashby, Greenhouse, Lever, Workday, Rippling, YC) & filter ghost jobs
./bin/employmaxing dorks --roles "Staff Engineer,Platform Engineer" --location "Remote" --hours 48
./bin/employmaxing job-audit posting.md --days-old 1

# 5. Enforce >=85/100 Empirical Resume & Cold Mail Quality Gates + Export ATS PDF/DOCX
./bin/employmaxing audit-resume resume.md --jd posting.md --autofix
./bin/employmaxing export resume.md --type resume --format all
./bin/employmaxing audit-mail hm_email.md --mode cold-email --autofix
./bin/employmaxing email-find --first Alex --last Rivera --domain stripe.com

# 6. Mailbox Automation: Scan IMAP Replies & Send Approved Plain-Text Outreach
./bin/employmaxing mail configure --provider gmail --email you@gmail.com --password "app-password"
./bin/employmaxing mail scan-inbox --days 14
./bin/employmaxing mail send --dry-run

# 7. Complex ATS Form Filling (75th-Pct Salary Anchor, Knockout Safeguards, CDP Native PDF Upload)
./bin/employmaxing form plan --job-id stripe-staff-engineer --url https://jobs.ashbyhq.com/stripe/123
./bin/employmaxing form execute --id 1 --cdp-port 9222
```

---

## Sub-Skills Included

| Sub-Skill | Path | Purpose |
| :--- | :--- | :--- |
| **Web Dashboard** | `skills/web-dashboard/SKILL.md` | Local Neo-Brutalist UI (`127.0.0.1:8787`) for non-CLI control |
| **Enrich Profile** | `skills/enrich-profile/SKILL.md` | Multi-source profile builder with transparent Consent Ledger |
| **LinkedIn Audit** | `skills/linkedin-audit/SKILL.md` | 12-point discrepancy, turn-off & LinkedIn Recruiter SEO fixer |
| **Mailbox** | `skills/mailbox/SKILL.md` | IMAP reply scanner + interview classifier + plain-text SMTP sender |
| **Autopilot** | `skills/autopilot/SKILL.md` | 1-command **Triple-Tap** (Ghost Check + >=85 Resume + Mail + Form Plan) |
| **Job Search** | `skills/job-search/SKILL.md` | `<48h` direct ATS radar + ghost-job triage |
| **Tailor Resume** | `skills/tailor-resume/SKILL.md` | Google X-Y-Z + 475–650w optimal length + >=80% keyword parity |
| **Cover Letter** | `skills/cover-letter/SKILL.md` | 200–290w Pain-Hook value pitch cover letters |
| **Export** | `skills/export/SKILL.md` | Headless Chrome single-column PDF + `python-docx` export |
| **Outreach** | `skills/outreach/SKILL.md` | MX-verified `<95w` HM emails (0 cold attachments) & `<=295c` LinkedIn notes |
| **Network Scan** | `skills/network-scan/SKILL.md` | Scan LinkedIn connections' companies for open roles |
| **Apply** | `skills/apply/SKILL.md` | Complex ATS form fills (Ashby, Greenhouse, Lever, BambooHR, Workday) |
| **Interview Prep** | `skills/interview-prep/SKILL.md` | STAR behavioral blueprints, company dossiers & live mock drills |
| **Tracker** | `skills/tracker/SKILL.md` | Application pipeline funnel & follow-up alerts |
| **Negotiate** | `skills/negotiate/SKILL.md` | Total comp breakdown (base/bonus/equity) & counter-offer scripts |

See `shared/references/conversion-science.md` for all underlying empirical conversion laws.
