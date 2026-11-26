---
name: tracker
description: Track application status, interview pipeline stages, follow-up reminders, and search analytics
argument-hint: "'view' to show dashboard, 'update <company> <stage>', or 'stats'"
---

# Application Tracker Skill

> **Priority hierarchy**: See `shared/references/priority-hierarchy.md` for conflict resolution.

Unified dashboard and pipeline manager that tracks every application from saved posting to interview loops, offers, and follow-ups.

## Quick Start

- `/proficiently:tracker` - View current application pipeline and upcoming action items
- `/proficiently:tracker update Stripe screen` - Advance Stripe to Phone Screen stage
- `/proficiently:tracker update Google onsite "Invited for 4-panel onsite March 15"` - Advance with custom notes

## Pipeline Stages

Applications progress through standardized stages:
1. `Saved` (Job identified and materials drafted)
2. `Applied` (Application submitted on portal)
3. `Phone Screen` (Recruiter / Hiring Manager initial call)
4. `Technical Assessment` (Take-home, coding challenge, system design)
5. `Onsite / Final` (Multi-round panel / executive interviews)
6. `Offer` (Offer extended)
7. `Accepted` / `Rejected` / `Withdrawn`

## File Structure

```
shared/scripts/
  tracker.py              # CLI engine that syncs jobs/ and generates pipeline.md
```

## Data Directory

Resolve the data directory using `shared/references/data-directory.md`.
Stores state in `DATA_DIR/tracker.json` and renders `DATA_DIR/pipeline.md`.

---

## Workflow

### Step 0: Check Prerequisites

Resolve `DATA_DIR`.

### Step 1: Parse Arguments & Execute Action

Parse `$ARGUMENTS`:

1. **If empty, "view", or "stats"**:
   Run `python3 shared/scripts/tracker.py DATA_DIR view`
   - Automatically scans `DATA_DIR/jobs/` for any newly created job folders or submitted `applied.md` files
   - Calculates funnel metrics: Total applications, Active interview loops, Offers
   - Flags follow-ups due (e.g. applications > 7 days old with no response)

2. **If "update [company] [stage] [notes...]"**:
   Run `python3 shared/scripts/tracker.py DATA_DIR update [company] [stage] [optional notes]`
   - Matches the company name
   - Updates the stage and timestamp
   - Appends notes to the application record

### Step 2: Present Dashboard

Render the updated `DATA_DIR/pipeline.md` markdown dashboard to the user.

Highlight:
- Active interview rounds scheduled
- Applications needing a follow-up email or LinkedIn ping (suggest running `/proficiently:outreach`)
- Current conversion rate (Applications → Screens → Offers)

---

## Response Format

Structure user-facing output with:
1. **Pipeline Summary Table** (Funnel numbers & active candidates)
2. **Action Items Due** (Follow-ups, scheduled interviews)
3. **Suggested Next Commands** (e.g., `/proficiently:interview-prep`, `/proficiently:outreach`, `/proficiently:negotiate`)
