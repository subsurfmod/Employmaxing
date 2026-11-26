---
name: interview-prep
description: Prepare for interviews with role-specific behavioral STAR answers, technical dossiers, and mock simulations
argument-hint: "job URL, 'last' for most recent job, or 'mock' to start interactive practice"
---

# Interview Prep Skill

> **Priority hierarchy**: See `shared/references/priority-hierarchy.md` for conflict resolution.

Comprehensive interview preparation and live mock interview simulation tailored specifically to the target role and company.

## Quick Start

- `/proficiently:interview-prep` - Generate full interview prep dossier for the most recent job
- `/proficiently:interview-prep last` - Same as above
- `/proficiently:interview-prep https://...` - Generate prep for a specific job posting
- `/proficiently:interview-prep mock` - Start an interactive question-by-question mock interview

## File Structure

```
scripts/
  generate-prep.md        # Interview strategy, STAR framework & questions guide
```

## Data Directory

Resolve the data directory using `shared/references/data-directory.md`.

---

## Workflow

### Step 0: Check Prerequisites

Resolve `DATA_DIR`. Require `DATA_DIR/profile.md` or `DATA_DIR/resume/*`. Load the target job folder from `DATA_DIR/jobs/`.

### Step 1: Load Target Role Context

Parse `$ARGUMENTS`:
- If "last" or empty: find the latest job folder in `DATA_DIR/jobs/`
- If a URL or folder slug: find that specific folder
- Load `posting.md`, `resume.md`, and `profile.md`

### Step 2: Determine Mode (Dossier vs. Interactive Mock)

If `$ARGUMENTS` contains "mock", skip to **Interactive Mock Interview Flow** below.
Otherwise, proceed to generate the Comprehensive Prep Dossier.

### Step 3: Generate Comprehensive Prep Dossier

Synthesize the target role requirements, company context, and candidate experience:

1. **Executive Company Dossier**:
   - Company mission, product lines, revenue model, customer base
   - Recent public initiatives, tech stack, and industry headwinds
2. **Behavioral STAR Master Matrix (5 Key Questions)**:
   - Leadership / Ownership
   - Technical / Operational Conflict
   - Handling Failure / Course Correction
   - Navigating Ambiguity / Fast Deadlines
   - Scaling People or Systems
   - *For each*: Provide the exact STAR breakdown (Situation, Task, Action, Result) mapped directly from the candidate's authentic history in `profile.md`.
3. **Deep-Dive Technical / Situational Scenarios (3 Scenarios)**:
   - High-probability technical or case questions directly reflecting the job's daily responsibilities.
   - Core concepts, recommended architecture/frameworks, and pitfall warnings.
4. **Questions to Ask the Interviewer (5 High-Signal Questions)**:
   - Insightful, peer-level questions that demonstrate business acumen and curiosity.

Save the dossier to `DATA_DIR/jobs/[folder]/interview-prep.md`.

### Step 4: Interactive Mock Interview Flow (If "mock" requested)

1. Greet the candidate in character as the hiring manager for [Company].
2. Ask ONE question at a time (starting with "Tell me about yourself and why you're interested in this role at [Company]").
3. Wait for the candidate's response.
4. Provide structured feedback:
   - **Strengths**: What worked well (metrics, conciseness, confidence).
   - **Gaps**: What was missing (e.g., lack of clear action steps, missing numbers).
   - **Refined Sample**: A polished version of their answer.
5. Move to the next question (Behavioral, then Technical/Case).
6. Continue for 3-5 rounds or until the user types "exit".

---

## Response Format

Structure dossier output with:
1. **Company & Role Overview**
2. **Top Behavioral Questions & STAR Blueprints**
3. **Technical / Case Scenario Practice**
4. **Questions to Ask the Team**
5. **Call to Action**: Suggest running `/proficiently:interview-prep mock` to practice live
