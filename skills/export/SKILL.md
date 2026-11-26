---
name: export
description: Export tailored resumes and cover letters from Markdown to ATS-optimized PDF and DOCX
argument-hint: "'last' to export most recent job materials, a job folder name, or specific file path"
---

# Export Skill

> **Priority hierarchy**: See `shared/references/priority-hierarchy.md` for conflict resolution.

Export tailored resumes and cover letters into recruiter-grade, ATS-optimized PDF and DOCX files.

## Quick Start

- `/proficiently:export` - Export resume and cover letter for the most recent job
- `/proficiently:export last` - Export most recent job materials to both PDF and DOCX
- `/proficiently:export https://...` - Export materials for a specific saved job
- `/proficiently:export /path/to/resume.md` - Export any specific markdown file

## File Structure

```
shared/scripts/
  export_document.py    # Python rendering engine (HTML+Chrome Headless PDF & python-docx)
```

## Data Directory

Resolve the data directory using `shared/references/data-directory.md`.

---

## Workflow

### Step 0: Check Prerequisites

Resolve `DATA_DIR`. Verify `DATA_DIR/jobs/` has at least one saved job folder, or that an explicit file path was provided.

### Step 1: Resolve Target Files

Parse `$ARGUMENTS`:

1. **If "last" or empty**:
   - Locate the most recently modified job folder in `DATA_DIR/jobs/`
   - Look for `resume.md` and `cover-letter.md` inside that folder
2. **If a URL or folder slug**:
   - Match the corresponding folder in `DATA_DIR/jobs/`
3. **If a direct file path**:
   - Use the file directly and infer whether it's a resume or cover letter from its name or content

Confirm target files with the user:
```
Exporting materials for [Role] at [Company]:
- Resume: DATA_DIR/jobs/[folder]/resume.md
- Cover letter: DATA_DIR/jobs/[folder]/cover-letter.md
```

### Step 2: Run Exporter

Execute `shared/scripts/export_document.py` for each file:

```bash
# Export resume to PDF and DOCX
python3 shared/scripts/export_document.py DATA_DIR/jobs/[folder]/resume.md --type resume --format all

# Export cover letter if present
python3 shared/scripts/export_document.py DATA_DIR/jobs/[folder]/cover-letter.md --type cover-letter --format all
```

The script produces:
- `resume.pdf` (Single/two-page ATS-compliant format with selectable text and standard 0.55" margins)
- `resume.docx` (Standard Word document with native headings and bullet lists)
- `cover-letter.pdf` (Standard professional letter layout)
- `cover-letter.docx` (Standard Word letter)

### Step 3: Present Deliverables

Report the generated files with clickable file paths:

```markdown
### Export Complete

Your application materials are compiled and ATS-ready:

- **Resume PDF**: `[path-to-resume.pdf]` (Ready for Greenhouse, Lever, Ashby, Workday)
- **Resume DOCX**: `[path-to-resume.docx]` (For systems requiring Word format)
- **Cover Letter PDF**: `[path-to-cover-letter.pdf]`
- **Cover Letter DOCX**: `[path-to-cover-letter.docx]`

All files are formatted with ATS-safe fonts, standard margins, and zero-loss semantic text layers.
```

---

## Response Format

Structure user-facing output with:
1. **Generated Files** — list of exported PDF and DOCX files with paths
2. **Next Steps** — ready to submit via `/proficiently:apply` or upload directly
