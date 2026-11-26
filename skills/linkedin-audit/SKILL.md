---
name: linkedin-audit
description: Audit a LinkedIn profile against your resume to catch date/title discrepancies, recruiter turn-offs, and LinkedIn Recruiter SEO gaps, and serve ready-to-paste fixes
argument-hint: "LinkedIn URL, path to LinkedIn 'Save to PDF' / Data Export ZIP, or 'live' for active browser tab"
---

# LinkedIn Discrepancy & Recruiter Turn-Off Auditor

> **Empirical basis**: See `shared/references/conversion-science.md`. Recruiters cross-check LinkedIn on ~85% of shortlisted candidates; a single date drift, inflated title, overlapping "Present" role, or desperation banner silently kills interview conversion.

Scan the user's LinkedIn profile, compare it line-by-line against their Resume and Work History Profile, flag every discrepancy and recruiter turn-off, and output **copy-pasteable turnkey fixes**.

## Quick Start

- `/proficiently:linkedin-audit` - Audit LinkedIn profile (via URL, saved PDF, CSV export, or pasted profile)
- `/proficiently:linkedin-audit /path/to/Profile.pdf` - Audit LinkedIn's "Save to PDF" export against your resume
- `/proficiently:linkedin-audit https://linkedin.com/in/yourname` - Inspect open browser tab / URL and run full discrepancy audit

## File Structure

```
shared/scripts/
  linkedin_audit.py       # Deterministic 12-point discrepancy, turn-off & Boolean SEO engine
```

---

## Workflow

### Step 1: Ingest LinkedIn Profile & Candidate Baseline

Resolve `DATA_DIR` (`~/.proficiently/`). Load `DATA_DIR/resume/*`, `DATA_DIR/profile.md`, and `DATA_DIR/preferences.md`.

Collect the user's LinkedIn profile via whichever source is fastest:
1. **File path provided** (`Profile.pdf` from LinkedIn's *More → Save to PDF*, or LinkedIn Data Export `.zip` / folder): pass directly to `linkedin_audit.py`.
2. **LinkedIn URL or active Chrome tab**: extract visible profile sections (`Name`, `Headline`, `Connection count`, `About`, `Experience` with exact months/years, `Education`, `Skills`, `Recent Activity/Comments`, and whether public `#OpenToWork` frame is active) and save to `DATA_DIR/linkedin-profile-snapshot.md`.
3. **No file or browser open**: ask the user to either run LinkedIn → *More → Save to PDF* and drop the path, or paste their profile text.

### Step 2: Run the Deterministic 12-Point Audit Engine

Execute:
```bash
python3 shared/scripts/linkedin_audit.py \
  --linkedin <linkedin_source> \
  --resume DATA_DIR/resume/resume.md \
  --profile DATA_DIR/profile.md \
  --prefs DATA_DIR/preferences.md \
  --output DATA_DIR/linkedin-fixes.md
```

### Step 3: Deep Qualitative Review (Layering Human Recruiter Eyes Over Script Output)

In addition to the deterministic checks in `DATA_DIR/linkedin-fixes.md`, inspect and report on:
1. **Timeline & Title Integrity**:
   - Any >1-month start/end drift, missing stints, or `"Present"` vs ended conflicts.
   - Any internal/quirky titles (`Ninja`, `MTS`, `Associate III`) that suppress LinkedIn Recruiter Boolean discovery — prescribe safe parenthetical pairing: `Official HR Title (Searchable Market Title)`.
2. **Overemployment (OE) & Short-Stint Risk**:
   - Multiple concurrent `"Present"` roles that trigger split-focus suspicion — label advisory/part-time roles explicitly.
   - Multiple `<12 month` stints or `>3 month` gaps — draft 1-line neutral context anchors (*acquisition, fixed-term turnaround contract, org-wide restructuring*).
3. **Signal Psychology & Visual Hygiene**:
   - Public green `#OpenToWork` banner vs **Recruiters-Only** setting (strongly recommend **Recruiters Only** for mid/senior/lead roles to avoid negative-selection bias while preserving 100% recruiter filter visibility).
   - Headline desperation markers (`Seeking`, `Looking for`, `Ex-Company`, `Unemployed`, buzzword soup).
   - Profile photo & banner guidance (high-contrast head-and-shoulders photo, non-default banner, clean `/in/firstname-lastname` URL slug, `500+` connections target).
4. **The "Multi-Role Tailoring Trap" Solution**:
   - Ensure the user's public LinkedIn Experience bullets act as a **Canonical Umbrella** — rich in core XYZ metrics and truthful across *every* tailored resume variant they send, never contradicting role-specific resumes.

### Step 4: Serve Copy-Pasteable Fixes

Present the prioritized audit scorecard and exact copy-pasteable replacements from `DATA_DIR/linkedin-fixes.md`:
1. **Critical Discrepancies to Fix Today** (Dates, Titles, Missing/Overlapping Roles)
2. **Recruiter Turn-Offs Found & Neutralized**
3. **3 Copy-Pasteable 220-Character Headlines**
4. **Complete Rewritten `About` Section** (optimized for the 2-line mobile fold + XYZ proof + Boolean skill block)
5. **Synchronized Experience Timeline & Umbrella XYZ Bullets**
6. **Top-20 Skills Pin Order + 5-Minute Settings Checklist**
