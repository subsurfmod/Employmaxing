---
name: autopilot
description: End-to-end "Triple-Tap" interview maximizer — audits ghost-job risk, tailors >=85-score XYZ resume + PDF/DOCX, verifies LinkedIn consistency, drafts MX-checked plain-text hiring manager mail + <295c LinkedIn note + referral blurb, and pre-computes knockout-safe ATS form fills in one run
argument-hint: "job URL or path to posting"
---

# Autopilot ("Triple-Tap" Interview Maximizer)

> **Empirical basis**: Cold portal applications convert at ~1–2%. Executing the **Triple-Tap Protocol** within 48 hours of posting — (1) >=85-score XYZ ATS Resume + Knockout-Safe Form Fill, (2) Warm Internal Referral OR Plain-Text <95w Hiring Manager Value Mail, and (3) Synchronized LinkedIn Profile + <295-char Peer/Recruiter Note — lifts interview conversion to **15–28%+**.

Run the entire high-efficiency application machine for a target job in a single coordinated workflow.

## Quick Start

- `/proficiently:autopilot https://jobs.ashbyhq.com/...` - Run full Triple-Tap package on a job URL
- `/proficiently:autopilot last` - Upgrade and score all materials for the most recent saved job

---

## Workflow

### Step 1: Intake & Ghost-Job / ROI Gate (Save Time First)

1. Fetch or load `DATA_DIR/jobs/[company-slug]-[date]/posting.md`.
2. Run the Ghost-Job & Priority Triage gate:
   ```bash
   python3 shared/scripts/optimizer.py job-audit DATA_DIR/jobs/[folder]/posting.md
   ```
3. If **Ghost Risk is HIGH (`P3 SKIP`)** and the user has **no network connection** at the company, warn the user immediately before wasting effort, and ask if they still want to proceed.

### Step 2: LinkedIn Consistency Lock

If `DATA_DIR/linkedin-profile-snapshot.md` or a LinkedIn export exists, verify zero title/date drift against `DATA_DIR/resume/` via `linkedin_audit.py`. Lock exact company names, job titles, and start/end months so the tailored resume and public LinkedIn match 100%.

### Step 3: Auto-Optimized XYZ Resume (>= 85/100 Gate) + PDF/DOCX Export

1. Generate `DATA_DIR/jobs/[folder]/resume.md` applying all rules in `shared/references/conversion-science.md`:
   - **475–650 words** (or **525–780w** for Staff/Principal/Director/VP)
   - **F-Pattern Top Third**: Exact target role framing + 2-sentence Summary + strongest 2 XYZ bullets at top of 2 most recent roles
   - **>=70% Quantified Bullets** (min 6 concrete numbers, 14–26 words/bullet, zero repeated lead verbs per role, zero pronouns/em-dashes/AI fluff)
   - **>=80% Truthful JD Hard-Skill Parity** with acronym pairing (`Kubernetes (K8s)`)
2. Run the deterministic quality gate with auto-fix:
   ```bash
   python3 shared/scripts/optimizer.py resume DATA_DIR/jobs/[folder]/resume.md --jd DATA_DIR/jobs/[folder]/posting.md --autofix
   ```
   **Mandatory Loop**: If score `< 85`, fix every reported item in `priority_fixes` and re-run until `>= 85`!
3. Export ATS-safe single-column PDF & DOCX:
   ```bash
   python3 shared/scripts/export_document.py DATA_DIR/jobs/[folder]/resume.md --type resume --format all
   ```

### Step 4: Pain-Hook Cover Letter + Plain-Text Value Mail + Referral Kit (>= 85/100 Gate)

1. Generate `cover-letter.md` (200–280w Pain-Hook pitch, zero *"I am writing to apply"*, 2–3 XYZ wins), audit with `optimizer.py mail ... --mode cover-letter --autofix`, and export PDF/DOCX.
2. Check `linkedin-contacts.csv` for company insiders; identify likely Hiring Manager / Recruiter domain and run live MX & email permutation check:
   ```bash
   python3 shared/scripts/optimizer.py email-find --first <First> --last <Last> --domain <company.com>
   ```
3. Save `outreach.md` containing:
   - **Plain-Text Hiring Manager Value Email** (3–6 word lowercase subject, **45–95 words**, Grade <=6.5, **0 attachments**, <=1 link, interest-question CTA) — audited via `optimizer.py mail --mode cold-email`
   - **LinkedIn Connection Note** (**<= 295 chars** hard gate) — audited via `optimizer.py mail --mode linkedin-note`
   - **De-Risked Warm Referral Ask + 3-Bullet Forwardable Blurb**
   - **Day 3 / Day 7 / Day 14 Follow-up Schedule**

### Step 5: Knockout-Safe Form-Fill Plan & Pipeline Tracking

1. Pre-compute exact salary anchors (75th percentile of posted band), defensible years of experience, knockout warnings, and 65–105w `"Why [Company]?"` supplemental answers:
   ```bash
   python3 shared/scripts/optimizer.py form-plan DATA_DIR/jobs/[folder]/posting.md \
     --app-data DATA_DIR/application-data.md \
     --profile DATA_DIR/profile.md \
     --prefs DATA_DIR/preferences.md
   ```
2. Save the form plan to `DATA_DIR/jobs/[folder]/form-plan.md`, sync `tracker.py`, and offer immediate 1-approval browser form filling via `/proficiently:apply last`!
