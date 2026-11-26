---
name: outreach
description: Generate high-converting networking, referral, and recruiter outreach messages
argument-hint: "job URL, company name, contact name, or 'last'"
---

# Outreach Skill

> **Priority hierarchy**: See `shared/references/priority-hierarchy.md` for conflict resolution.

Turn discovered contacts and open roles into warm referrals and direct recruiter conversations.

## Quick Start

- `/proficiently:outreach` - Generate outreach messages for the most recent job
- `/proficiently:outreach last` - Use the most recently modified job folder
- `/proficiently:outreach https://...` - Generate outreach for a specific job posting
- `/proficiently:outreach "Jane Smith at Stripe"` - Craft targeted outreach to a specific person

## File Structure

```
scripts/
  draft-outreach.md       # High-converting messaging strategy & formulas
```

## Data Directory

Resolve the data directory using `shared/references/data-directory.md`.

---

## Workflow

### Step 0: Check Prerequisites

Resolve `DATA_DIR`. Require `DATA_DIR/resume/*` or `DATA_DIR/profile.md`. If `DATA_DIR/linkedin-contacts.csv` exists, use it to cross-reference potential contacts.

### Step 1: Identify Context & Target Contact

1. **If a job URL or "last"**:
   - Load `posting.md` and `resume.md` from the target job folder in `DATA_DIR/jobs/`
   - Check if `posting.md` has a recorded "Network Contact" (from `network-scan` or `job-search`)
   - Check `linkedin-contacts.csv` for any connections at that company
2. **If a specific contact was specified**:
   - Use their name and company as the target

Report the context to the user:
```
Target: [Role] at [Company]
Contact: [Name] ([Title]) — [1st degree / recruiter / hiring manager]
```

### Step 2: Run Corporate Email + Live DNS MX Discovery

If targeting a Hiring Manager, Team Lead, or Recruiter at `[company.com]`, run the deterministic email permutation & MX spam-gateway checker:
```bash
python3 shared/scripts/optimizer.py email-find --first <First> --last <Last> --domain <company.com>
```
Adapt formatting to the detected gateway (e.g., if Proofpoint or Mimecast is detected, include **zero URLs and zero attachments** on Touch #1).

### Step 3: Draft & Deterministically Score 4 High-Impact Variations

Using the empirical Lavender/Gong rules in `scripts/draft-outreach.md`, generate:

1. **Warm Referral Ask + 3-Bullet Forwardable Blurb** (if connection exists in network):
   - Personal greeting + role link + easy out (*"No pressure at all if your plate is full!"*)
   - Ready-to-copy 3rd-person blurb with 2 quantified XYZ metrics they can paste straight into their internal referral portal

2. **LinkedIn Connection Note (`<= 295 characters` hard cap)**:
   - Audit via `python3 shared/scripts/optimizer.py mail <note_file> --mode linkedin-note`

3. **Hiring Manager Plain-Text Value Email (`45–95 words`, `Subject: 3–6 words`, `0 attachments`)**:
   - Audit via `python3 shared/scripts/optimizer.py mail <email_file> --mode cold-email --autofix` (must score `>= 85/100`)

4. **Recruiter / Talent Partner Post-Apply Ping**:
   - Concise Req ID reference + 3 XYZ bullets proving exact must-have alignment

5. **4-Touch Multi-Channel Follow-Up Sequence**:
   - **Day 0**: Plain-text Value Email
   - **Day 3**: Same-thread 2-sentence bump with 1 micro-insight
   - **Day 7**: Channel switch to LinkedIn connection note
   - **Day 14**: Polite 2-line close-the-loop breakup (highest reply touch)

### Step 4: Save and Present

Save to `DATA_DIR/jobs/[folder]/outreach.md`.

Present the messages clearly with character counts for LinkedIn notes and instructions on when to send each.

---

## Response Format

Structure user-facing output with:
1. **Target Summary** — Company, Role, and Contact Name/Title
2. **LinkedIn Connection Note** — (<300 chars with exact character count)
3. **Warm Referral Message & Forwardable Blurb**
4. **Direct Hiring Manager Email / InMail**
5. **Follow-up Templates** (Day 4 & Day 8)
