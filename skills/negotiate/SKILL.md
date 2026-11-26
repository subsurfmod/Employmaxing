---
name: negotiate
description: Evaluate job offers, benchmark total compensation (base, bonus, equity), and generate negotiation scripts
argument-hint: "offer details, or 'compare' to benchmark against other offers"
---

# Salary Negotiation Skill

> **Priority hierarchy**: See `shared/references/priority-hierarchy.md` for conflict resolution.

Evaluate total compensation packages, calculate true annual value, and craft high-leverage negotiation scripts.

## Quick Start

- `/proficiently:negotiate` - Walk through offer details to evaluate and build a negotiation plan
- `/proficiently:negotiate "$185k base, 20k bonus, 100k equity over 4 yrs at Datadog"` - Analyze a specific package
- `/proficiently:negotiate compare` - Benchmark multiple competing offers side-by-side

## File Structure

```
scripts/
  evaluate-offer.md       # Compensation analysis framework & negotiation scripts
```

## Data Directory

Resolve the data directory using `shared/references/data-directory.md`.

---

## Workflow

### Step 0: Check Prerequisites

Resolve `DATA_DIR`. Read `DATA_DIR/preferences.md` to benchmark against the candidate's initial compensation expectations.

### Step 1: Intake Offer Details

Prompt for or parse the offer package elements:
1. **Company & Role Title**
2. **Base Salary** (annual)
3. **Bonus Target** (% or fixed dollar amount)
4. **Equity Grant** (RSUs or Options, vesting schedule, estimated annual value)
5. **Signing Bonus** (amount & clawback conditions)
6. **Location / Remote status** & benefits notes
7. **Competing Offers or Current Baseline** (if applicable)

### Step 2: Compute Total Compensation (TC) Analysis

Calculate:
- Year 1 Total Realized Cash (Base + Bonus + Signing Bonus)
- 4-Year Annualized Total Compensation (Base + Bonus + Annual Equity)
- Risk Profile: Guaranteed Cash vs. Illiquid Paper Equity
- Comparison against target compensation in `preferences.md`

### Step 3: Formulate Negotiation Strategy

Identify candidate leverage points:
- Market percentile benchmarking for the title and metro area
- Specific high-impact skills mentioned in the job posting
- Competing timelines or offers
- Best levers to pull (Signing bonus vs. Equity vs. Base salary vs. Remote flexibility)

### Step 4: Generate Verifiable Scripts

Produce tailored scripts:
1. **Phone Call Script with Recruiter**: Clear verbal talking points to use during the initial offer debrief.
2. **Formal Counter-Offer Email**: Professional written response with clear justification and specific targets.
3. **Exploding Offer Pushback**: Safe language to buy additional time (3-7 days) without burning goodwill.

Save the evaluation and scripts to `DATA_DIR/jobs/[folder]/negotiation.md` or `DATA_DIR/negotiations-[date].md`.

---

## Response Format

Structure user-facing output with:
1. **Total Compensation Breakdown Table** (Year 1 vs. Annualized 4-Year)
2. **Strengths & Gaps Analysis**
3. **Negotiation Levers & Target Counter-Numbers**
4. **Verbal Call Script & Written Counter-Offer Email**
