---
name: enrich-profile
description: Discover and build a complete Personal & Career Profile from resume, CV, LinkedIn, GitHub, and websites while transparently logging every discovered fact in a Consent Ledger before use
argument-hint: "--resume <path> --linkedin <path> --github <user> --website <url>"
---

# Transparent Profile Enrichment Skill

Build the richest, highest-converting Master Career Profile for the user using their Resume/CV, LinkedIn profile, GitHub repositories, and personal website/portfolio — while **strictly disclosing every single piece of information planned for use**.

## Mandatory Transparency Workflow

1. Run the enricher engine:
   ```bash
   ./bin/employmaxing enrich --resume <resume> --linkedin <linkedin> --github <user> --website <url>
   ```
2. Every discovered item is saved into `~/.employmaxing/employmaxing.db` (`profile_facts`) with `consent_status = 'pending_review'`, exact `source`, `source_url`, and `planned_usage`.
3. Present `~/.employmaxing/DISCLOSURE-REPORT.md` to the user (or direct them to **02 // Info & Consent** at `http://127.0.0.1:8787`) so they can **Approve, Edit, or Exclude** each fact before any resume, email, or form fill uses it.
4. Once approved, `master-profile.json` and `profile.md` automatically compile using **only approved facts**.
