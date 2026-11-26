#!/usr/bin/env python3
"""
linkedin_audit.py - Deep LinkedIn vs. Resume Discrepancy Detector, Recruiter Turn-Off Scanner,
LinkedIn Recruiter Boolean SEO Scorer, and Copy-Pasteable Fix Generator.
Part of Proficiently v3.0.
"""

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from optimizer import COMMON_TECH_AND_DOMAIN_TERMS, METRIC_REGEX, extract_jd_keywords
from parse_resume import extract_text

MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

DESPERATION_HEADLINE_PATTERNS = [
    r'\bseeking\b', r'\blooking for\b', r'\bunemployed\b', r'\bopen to (?:new )?(?:work|opportunities|roles)\b',
    r'#opentowork', r'\baspiring\b', r'\bactively applying\b', r'\bavailable immediately\b',
    r'\b Laid off\b', r'\bbetween roles\b', r'\bfree agent\b',
]

HEADLINE_FLUFF_PATTERNS = [
    r'\bpassionate\b', r'\bthought leader\b', r'\bninja\b', r'\brockstar\b', r'\bguru\b',
    r'\bvisionary\b', r'\bresults-driven\b', r'\bproblem solver\b', r'\bwearer of many hats\b',
    r'\bex-[a-z0-9]+',  # Flag 'Ex-Company' identity crutch for recruiter critique
]

ACTIVITY_RED_FLAGS = [
    "ghosted by", "recruiters are useless", "broken hiring", "hate my boss", "toxic workplace",
    "ai slop recruiters", "500 rejections", "nobody is hiring",
]

DATE_SPAN_RE = re.compile(
    r'(?P<s_m>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|\d{1,2})?'
    r'[\s/\.,-]*'
    r'(?P<s_y>(?:199\d|20[0-3]\d))'
    r'\s*(?:-|–|—|to)\s*'
    r'(?:(?P<present>Present|Current|Now)|'
    r'(?:(?P<e_m>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|\d{1,2})?[\s/\.,-]*(?P<e_y>(?:199\d|20[0-3]\d))))',
    re.IGNORECASE,
)


def parse_month(m_str: str | None) -> int | None:
    if not m_str:
        return None
    m_clean = m_str.strip().lower().rstrip(".")
    if m_clean.isdigit():
        val = int(m_clean)
        return val if 1 <= val <= 12 else None
    return MONTH_MAP.get(m_clean)


def normalize_company(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r'\b(inc|llc|ltd|corp|corporation|co|technologies|technology|labs|group|holdings|plc)\b\.?', '', n)
    n = re.sub(r'[^a-z0-9]', '', n)
    return n


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r'\([^)]*\)', '', t)
    t = re.sub(r'\bsr\.?\b', 'senior', t)
    t = re.sub(r'\bjr\.?\b', 'junior', t)
    t = re.sub(r'\bswe\b', 'software engineer', t)
    t = re.sub(r'\bpm\b', 'product manager', t)
    t = re.sub(r'\beng\b', 'engineer', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    return " ".join(t.split())


def extract_roles_from_text(text: str) -> list[dict]:
    """Extract structured roles from Markdown resume, LinkedIn Save-to-PDF text, or pasted profile text."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    roles = []
    # Restrict to Experience section when recognizable so Education dates aren't mistaken for jobs
    in_edu = False
    for idx, line in enumerate(lines):
        if re.match(r'^(?:#+\s*)?(?:education|certifications|publications|volunteering)\b', line, re.I):
            in_edu = True
        elif re.match(r'^(?:#+\s*)?(?:experience|work experience|employment|professional experience|skills|projects)\b', line, re.I):
            in_edu = False
        if in_edu:
            continue

        m = DATE_SPAN_RE.search(line)
        if not m:
            continue

        s_y = int(m.group("s_y"))
        s_m = parse_month(m.group("s_m"))
        is_present = bool(m.group("present"))
        e_y = datetime.now().year if is_present else int(m.group("e_y"))
        e_m = datetime.now().month if is_present else parse_month(m.group("e_m"))

        # Strip date span and markdown markers from line to see if Title/Company are on the same line
        rem = (line[:m.start()] + " " + line[m.end():]).strip()
        rem = re.sub(r'^#+\s*', '', rem)
        rem = re.sub(r'^\*\*Dates\*\*\s*:\s*', '', rem, flags=re.I)
        rem = re.sub(r'\(\s*\)', '', rem).strip(" -|–—•*:")

        title, company = "", ""
        if " | " in rem:
            parts = [p.strip(" *") for p in rem.split(" | ") if p.strip(" *")]
            if len(parts) >= 2:
                title, company = parts[0], parts[1]
        elif " at " in rem:
            parts = rem.split(" at ", 1)
            title, company = parts[0].strip(" *"), parts[1].strip(" *")
        elif " - " in rem or " — " in rem or " – " in rem:
            parts = re.split(r'\s+(?:-|—|–)\s+', rem, maxsplit=1)
            if len(parts) == 2:
                title, company = parts[0].strip(" *"), parts[1].strip(" *")
        elif "," in rem and len(rem.split(",")) == 2:
            parts = [p.strip(" *") for p in rem.split(",")]
            title, company = parts[0], parts[1]

        # If date was on its own line (like LinkedIn Save-to-PDF: Company on idx-2, Title on idx-1, Date on idx)
        if not company and idx >= 1:
            prev1 = re.sub(r'^#+\s*', '', lines[idx - 1]).strip(" *")
            if " at " in prev1:
                t_p, c_p = prev1.split(" at ", 1)
                title = re.sub(r'^Role:\s*', '', t_p, flags=re.I).strip()
                company = c_p.strip()
            elif " | " in prev1:
                parts = [p.strip() for p in prev1.split(" | ")]
                title, company = parts[0], parts[1]
            elif idx >= 2:
                prev2 = re.sub(r'^#+\s*', '', lines[idx - 2]).strip(" *")
                # In LinkedIn PDF: Company line -> Title line -> Date line (or Title -> Company -> Date)
                title, company = prev1, prev2

        if title or company:
            roles.append({
                "company": company or "Unknown",
                "company_norm": normalize_company(company or title),
                "title": title or "Unknown",
                "title_norm": normalize_title(title),
                "start_year": s_y,
                "start_month": s_m,
                "end_year": e_y,
                "end_month": e_m,
                "is_present": is_present,
                "raw_context": line,
            })
    return roles


def load_linkedin_data(li_path: Path) -> dict:
    """Load LinkedIn profile from CSV export directory/ZIP, PDF, or MD/TXT."""
    result = {
        "name": "",
        "headline": "",
        "summary": "",
        "url": "",
        "connections_count": None,
        "skills": [],
        "roles": [],
        "raw_text": "",
    }

    # Case 1: LinkedIn Data Export ZIP or Directory
    csv_files = {}
    if li_path.is_dir():
        for f in li_path.iterdir():
            if f.suffix.lower() == ".csv":
                csv_files[f.name.lower()] = f.read_text(encoding="utf-8", errors="replace")
    elif li_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(li_path, "r") as zf:
            for name in zf.namelist():
                base = Path(name).name.lower()
                if base.endswith(".csv"):
                    csv_files[base] = zf.read(name).decode("utf-8", errors="replace")

    if csv_files:
        if "profile.csv" in csv_files:
            reader = csv.DictReader(io.StringIO(csv_files["profile.csv"]))
            for row in reader:
                result["name"] = f"{row.get('First Name', '')} {row.get('Last Name', '')}".strip()
                result["headline"] = row.get("Headline", "").strip()
                result["summary"] = row.get("Summary", "").strip()
                break
        if "positions.csv" in csv_files:
            reader = csv.DictReader(io.StringIO(csv_files["positions.csv"]))
            for row in reader:
                comp = row.get("Company Name", "").strip()
                title = row.get("Title", "").strip()
                started = row.get("Started On", "").strip()
                finished = row.get("Finished On", "").strip()
                span_str = f"{started} - {finished or 'Present'}"
                parsed = extract_roles_from_text(f"{title} | {comp} ({span_str})")
                if parsed:
                    parsed[0]["description"] = row.get("Description", "").strip()
                    result["roles"].append(parsed[0])
        if "skills.csv" in csv_files:
            reader = csv.DictReader(io.StringIO(csv_files["skills.csv"]))
            for row in reader:
                sk = row.get("Name", "").strip()
                if sk:
                    result["skills"].append(sk)
        result["raw_text"] = "\n".join(csv_files.values())
        return result

    # Case 2: PDF or Markdown/Text
    raw = extract_text(li_path)
    result["raw_text"] = raw
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    # Extract URL if present
    m_url = re.search(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9_-]+/?', raw, re.I)
    if m_url:
        result["url"] = m_url.group(0)

    # Extract connection count if present (e.g., "412 connections" or "500+ connections")
    m_conn = re.search(r'\b(\d{1,4})\+?\s+connections\b', raw, re.I)
    if m_conn:
        result["connections_count"] = int(m_conn.group(1))

    # Extract Headline / Name heuristics
    m_hl = re.search(r'^(?:#+\s*)?Headline\s*:\s*(.+)$', raw, re.M | re.I)
    if m_hl:
        result["headline"] = m_hl.group(1).strip()
    elif len(lines) >= 2:
        result["name"] = re.sub(r'^#+\s*', '', lines[0]).strip()
        # In LinkedIn Save-to-PDF or profile paste, Headline is typically right below Name
        for cand in lines[1:5]:
            if "@" not in cand and "linkedin.com" not in cand.lower() and not cand.lower().startswith("contact"):
                result["headline"] = cand
                break

    # Extract Summary / About section
    m_sum = re.search(
        r'(?:^|\n)(?:#+\s*)?(?:Summary|About)\s*\n(.*?)(?=\n(?:#+\s*)?(?:Experience|Work Experience|Education|Skills)\b|\Z)',
        raw,
        re.S | re.I,
    )
    if m_sum:
        result["summary"] = m_sum.group(1).strip()

    # Extract Skills
    m_sk = re.search(r'(?:^|\n)(?:#+\s*)?(?:Top Skills|Skills)\s*\n(.*?)(?=\n(?:#+\s*)?(?:Languages|Certifications|Experience|Education)\b|\Z)', raw, re.S | re.I)
    if m_sk:
        raw_sk = re.split(r'[\n,•·|]+', m_sk.group(1))
        result["skills"] = [s.strip(" -*") for s in raw_sk if 1 < len(s.strip(" -*")) <= 40]

    result["roles"] = extract_roles_from_text(raw)
    return result


def to_ym(year: int, month: int | None, default_month: int = 6) -> int:
    return year * 12 + (month if month else default_month)


def audit_linkedin_vs_resume(li_data: dict, resume_path: Path, profile_path: Path | None = None, prefs_path: Path | None = None) -> dict:
    res_text = extract_text(resume_path)
    res_roles = extract_roles_from_text(res_text)
    prof_text = profile_path.read_text(encoding="utf-8", errors="replace") if (profile_path and profile_path.exists()) else ""
    prefs_text = prefs_path.read_text(encoding="utf-8", errors="replace") if (prefs_path and prefs_path.exists()) else ""

    discrepancies = []
    turn_offs = []
    seo_gaps = []

    li_roles = li_data["roles"]

    # 1. Cross-Examine Roles (Dates, Titles, Omissions)
    matched_res_indices = set()
    for lr in li_roles:
        match_idx = None
        for idx, rr in enumerate(res_roles):
            if idx in matched_res_indices:
                continue
            # Match by normalized company substring or exact start year + title overlap
            c1, c2 = lr["company_norm"], rr["company_norm"]
            if (c1 and c2 and (c1 in c2 or c2 in c1)) or (
                lr["start_year"] == rr["start_year"] and lr["title_norm"] and lr["title_norm"] == rr["title_norm"]
            ):
                match_idx = idx
                break

        if match_idx is None:
            discrepancies.append({
                "severity": "HIGH",
                "type": "Ghost / Unlisted Role on Resume",
                "detail": f"LinkedIn lists `{lr['title']}` at `{lr['company']}` ({lr['start_year']}–{'Present' if lr['is_present'] else lr['end_year']}), which is missing from your Resume.",
                "fix": "Either include a 1-line entry on your Resume or ensure omitting an older/unrelated stint doesn't create an unexplained multi-year gap.",
            })
            continue

        matched_res_indices.add(match_idx)
        rr = res_roles[match_idx]

        # Check Present vs Ended mismatch
        if lr["is_present"] != rr["is_present"]:
            discrepancies.append({
                "severity": "CRITICAL",
                "type": "Active Employment Status Conflict",
                "detail": f"At `{rr['company']}`, LinkedIn shows end date `{'Present' if lr['is_present'] else lr['end_year']}` while Resume shows `{'Present' if rr['is_present'] else rr['end_year']}`.",
                "fix": "Synchronize immediately — recruiters cross-check whether you are currently employed; mismatches look deceptive and fail background verification.",
            })
        else:
            # Check start/end date drift
            if lr["start_month"] and rr["start_month"]:
                s_diff = abs(to_ym(lr["start_year"], lr["start_month"]) - to_ym(rr["start_year"], rr["start_month"]))
                if s_diff > 1:
                    discrepancies.append({
                        "severity": "CRITICAL",
                        "type": "Start Date Mismatch",
                        "detail": f"`{rr['company']}` start date differs by {s_diff} months (LinkedIn: {lr['start_month']}/{lr['start_year']} vs Resume: {rr['start_month']}/{rr['start_year']}).",
                        "fix": "Align exact month and year on both LinkedIn and Resume to match payroll/W-2 records.",
                    })
            elif lr["start_year"] != rr["start_year"]:
                discrepancies.append({
                    "severity": "CRITICAL",
                    "type": "Start Year Mismatch",
                    "detail": f"`{rr['company']}` start year is `{lr['start_year']}` on LinkedIn vs `{rr['start_year']}` on Resume.",
                    "fix": "Fix year mismatch before applying — #1 recruiter trust red flag.",
                })

            if not lr["is_present"] and not rr["is_present"]:
                if lr["end_month"] and rr["end_month"]:
                    e_diff = abs(to_ym(lr["end_year"], lr["end_month"]) - to_ym(rr["end_year"], rr["end_month"]))
                    if e_diff > 1:
                        discrepancies.append({
                            "severity": "CRITICAL",
                            "type": "End Date Mismatch",
                            "detail": f"`{rr['company']}` end date differs by {e_diff} months (LinkedIn: {lr['end_month']}/{lr['end_year']} vs Resume: {rr['end_month']}/{rr['end_year']}).",
                            "fix": "Match exact departure month/year across LinkedIn and Resume.",
                        })
                elif lr["end_year"] != rr["end_year"]:
                    discrepancies.append({
                        "severity": "CRITICAL",
                        "type": "End Year Mismatch",
                        "detail": f"`{rr['company']}` end year is `{lr['end_year']}` on LinkedIn vs `{rr['end_year']}` on Resume.",
                        "fix": "Align departure year across both platforms.",
                    })

        # Check Title Mismatch / Inflation
        if lr["title_norm"] and rr["title_norm"] and lr["title_norm"] != rr["title_norm"]:
            discrepancies.append({
                "severity": "CRITICAL",
                "type": "Job Title Discrepancy / Inflation Risk",
                "detail": f"At `{rr['company']}`, LinkedIn title is `{lr['title']}` while Resume says `{rr['title']}`.",
                "fix": f"Harmonize to `{rr['title']}` on both, OR if HR title was generic, use `{lr['title']} ({rr['title']})` on both LinkedIn and Resume so Checkr/HireRight verification and Recruiter search both pass!",
            })

    for idx, rr in enumerate(res_roles):
        if idx not in matched_res_indices and li_roles:
            discrepancies.append({
                "severity": "CRITICAL",
                "type": "Role on Resume Missing from LinkedIn",
                "detail": f"Resume lists `{rr['title']}` at `{rr['company']}` ({rr['start_year']}–{'Present' if rr['is_present'] else rr['end_year']}), which is completely absent from LinkedIn.",
                "fix": "Add this role to LinkedIn immediately — recruiters view resume-only roles as potential fabrication or hidden termination.",
            })

    # 2. Overlapping Concurrent Full-Time Roles ("OE / Moonlighting Red Flag")
    present_roles = [r for r in li_roles if r["is_present"]]
    if len(present_roles) >= 2:
        names = ", ".join(f"{r['title']} @ {r['company']}" for r in present_roles)
        turn_offs.append({
            "severity": "CRITICAL",
            "category": "Overemployment / Split-Focus Suspicion",
            "detail": f"LinkedIn shows {len(present_roles)} simultaneous 'Present' roles ({names}). Modern hiring managers instantly reject candidates suspected of juggling multiple jobs.",
            "fix": "Close ended roles with an end date, OR explicitly append `(Part-Time Advisory)`, `(Board Member)`, or `(Open-Source Maintainer)` to non-primary roles.",
        })

    # 3. Short Stints (<12 months) Audit
    short_stints = []
    for r in (li_roles or res_roles):
        dur_months = to_ym(r["end_year"], r["end_month"], 12) - to_ym(r["start_year"], r["start_month"], 1)
        if 0 <= dur_months < 11 and not r["is_present"]:
            short_stints.append(f"{r['company']} ({max(1, dur_months)} mos)")
    if len(short_stints) >= 2:
        turn_offs.append({
            "severity": "HIGH",
            "category": "Unframed Short-Stint Pattern",
            "detail": f"Multiple tenures under 1 year detected ({', '.join(short_stints)}). Left unexplained, senior recruiters pattern-match this to performance friction or flight risk.",
            "fix": "Add a 1-line neutral context anchor under each short stint on both LinkedIn & Resume (e.g., 'Fixed-term contract engagement', 'Company acquired by X', or 'Org-wide Series B restructuring').",
        })

    # 4. Headline & #OpenToWork Turn-Offs
    hl = li_data["headline"]
    raw_li = li_data["raw_text"]
    for pat in DESPERATION_HEADLINE_PATTERNS:
        if re.search(pat, hl, re.I) or re.search(r'#opentowork', raw_li, re.I):
            turn_offs.append({
                "severity": "HIGH",
                "category": "Desperation Signal / Public #OpenToWork Banner",
                "detail": f"Detected public job-seeking/desperation marker in Headline or banner (`{hl}`). Studies & executive recruiters note public green `#OpenToWork` triggers negative-selection bias for mid/senior roles.",
                "fix": "Switch LinkedIn 'Open to Work' visibility to **Recruiters Only** (keeps 100% of the LinkedIn Recruiter algorithm boost with zero public stigma!) and replace Headline with `[Target Title] | [Core Stack/Domain] | [Quantified Signature Proof]`.",
            })
            break

    fluff_in_hl = [p.strip(r'\b') for p in HEADLINE_FLUFF_PATTERNS if re.search(p, hl, re.I)]
    if fluff_in_hl:
        turn_offs.append({
            "severity": "MEDIUM",
            "category": "Buzzword / Low-Signal Headline",
            "detail": f"Headline uses low-signal clichés ({', '.join(fluff_in_hl)}) that zero recruiters type into LinkedIn Recruiter Boolean search.",
            "fix": "Replace subjective adjectives with exact searchable titles and hard technical/domain nouns.",
        })

    # 5. URL Slug, Connection Count, About Section, Activity Red Flags
    if li_data["url"] and re.search(r'-[0-9a-f]{6,}/?$', li_data["url"], re.I):
        turn_offs.append({
            "severity": "MEDIUM",
            "category": "Uncustomized Default LinkedIn URL Slug",
            "detail": f"URL `{li_data['url']}` has trailing auto-generated hex digits — signals low digital polish.",
            "fix": "Go to LinkedIn -> 'Edit public profile & URL' and set a clean `/in/firstname-lastname` slug (then update your resume header!).",
        })

    if li_data["connections_count"] is not None and li_data["connections_count"] < 500:
        turn_offs.append({
            "severity": "MEDIUM",
            "category": "Sub-500 Connection Graph Penalty",
            "detail": f"Profile shows `{li_data['connections_count']} connections`. LinkedIn Recruiter ranks 2nd/3rd-degree graph proximity heavily, and `<500+` lowers perceived industry footprint.",
            "fix": "Send 15 targeted connection requests/week to peers, alumni, and engineers/PMs in your domain until crossing the `500+` badge threshold.",
        })

    summary_words = len(li_data["summary"].split()) if li_data["summary"] else 0
    if summary_words < 50:
        seo_gaps.append("Missing or ultra-thin `About` section (<50 words) — forfeits 2,600 chars of high-weight LinkedIn Recruiter keyword indexing.")
    elif not METRIC_REGEX.search(li_data["summary"]):
        seo_gaps.append("`About` section contains zero quantified metrics — add 3 bulleted XYZ career highlights above the fold.")

    bad_activity = [term for term in ACTIVITY_RED_FLAGS if term in raw_li.lower()]
    if bad_activity:
        turn_offs.append({
            "severity": "HIGH",
            "category": "Negative Public Feed / Comment Activity",
            "detail": f"Detected bitter/negative hiring commentary ({', '.join(bad_activity)}). Hiring managers routinely check 'Activity -> Comments' before extending interviews.",
            "fix": "Delete negative public comments/rants about employers or recruiting; replace with 1–2 crisp technical/domain teardowns.",
        })

    # 6. LinkedIn Recruiter Boolean SEO Score
    target_source = (prefs_text + "\n" + res_text + "\n" + prof_text).strip()
    core_kws = extract_jd_keywords(target_source)[:20]
    li_lower = raw_li.lower()
    present_kws = [k for k in core_kws if k.lower() in li_lower]
    missing_kws = [k for k in core_kws if k.lower() not in li_lower]

    kw_cov = (len(present_kws) / len(core_kws)) if core_kws else 0.7
    seo_score = int(round(
        (25 if (hl and len(hl) >= 35 and not fluff_in_hl) else 10)
        + (20 if summary_words >= 80 else 6)
        + (35 * kw_cov)
        + (20 if len(li_data["skills"]) >= 10 else 10)
    ))
    seo_score = min(100, max(0, seo_score - len(discrepancies) * 8 - len(turn_offs) * 5))

    if missing_kws:
        seo_gaps.append(f"High-value skills on your Resume missing from LinkedIn search index: {', '.join(missing_kws[:12])}.")

    # 7. Generate Copy-Pasteable Turnkey Fixes
    cand_name = li_data["name"] or re.sub(r'^#+\s*', '', res_text.splitlines()[0]).strip() if res_text.splitlines() else "Candidate"
    primary_role = res_roles[0]["title"] if res_roles else "Senior Specialist"
    top_skills_display = [k.upper() if len(k) <= 4 else k.title() for k in core_kws[:6]]
    skill_pipe = " | ".join(top_skills_display[:4]) if top_skills_display else "Distributed Systems | Cloud Architecture"

    # Extract top 3 quantified bullets from resume for ready-to-paste About section
    res_quant_bullets = []
    for line in res_text.splitlines():
        s = line.strip()
        if re.match(r'^[-*•]\s+', s) and METRIC_REGEX.search(s):
            res_quant_bullets.append(re.sub(r'^[-*•]\s+', '', s))

    headline_fixes = [
        f"{primary_role} | {skill_pipe} | Scaling High-Impact Production Systems",
        f"{primary_role} — {', '.join(top_skills_display[:3]) or 'Platform & Growth'} | Proven Track Record Delivering Measurable ROI",
        f"{primary_role} | Building Resilient {top_skills_display[0] if top_skills_display else 'Core'} Products & High-Velocity Teams",
    ]
    headline_fixes = [h[:218] for h in headline_fixes]

    highlights_block = "\n".join(f"• {b}" for b in res_quant_bullets[:3]) if res_quant_bullets else (
        "• [Insert #1 XYZ Win: Accomplished X as measured by Y%, by doing Z]\n"
        "• [Insert #2 XYZ Win: Scaled system/revenue from $A to $B across N markets]\n"
        "• [Insert #3 XYZ Win: Reduced latency/cost by X% via architectural redesign]"
    )

    about_fix = (
        f"{primary_role} focused on turning complex {', '.join(top_skills_display[:3]) or 'domain'} problems into measurable business outcomes.\n\n"
        f"Selected Impact Highlights:\n{highlights_block}\n\n"
        f"Core Competencies: {', '.join(top_skills_display + [k.title() for k in core_kws[6:14]])}\n\n"
        f"Always open to connecting with engineering, product, and executive leaders building ambitious systems."
    )

    clean_slug = "linkedin.com/in/" + re.sub(r'[^a-z0-9-]', '', cand_name.lower().replace(" ", "-"))

    return {
        "candidate": cand_name,
        "credibility_and_seo_score": seo_score,
        "discrepancy_count": len(discrepancies),
        "turn_off_count": len(turn_offs),
        "discrepancies": discrepancies,
        "turn_offs": turn_offs,
        "seo_gaps": seo_gaps,
        "turnkey_fixes": {
            "recommended_slug": clean_slug,
            "headlines_220_char": headline_fixes,
            "rewritten_about_section": about_fix,
            "canonical_timeline_to_mirror": [
                {
                    "company": r["company"],
                    "exact_title": r["title"],
                    "exact_dates": f"{r['start_month'] or ''}/{r['start_year']} - {'Present' if r['is_present'] else str(r['end_month'] or '') + '/' + str(r['end_year'])}".lstrip("/").replace(" - /", " - "),
                }
                for r in res_roles
            ],
            "top_skills_to_pin": [k.upper() if len(k) <= 4 else k.title() for k in core_kws[:20]],
        },
    }


def render_markdown_report(audit: dict) -> str:
    md = [
        f"# LinkedIn Discrepancy & Recruiter Turn-Off Audit: {audit['candidate']}\n",
        f"**Overall Credibility & Recruiter SEO Score**: **{audit['credibility_and_seo_score']}/100**  ",
        f"**Critical/High Resume Discrepancies**: `{audit['discrepancy_count']}` | **Recruiter Turn-Offs**: `{audit['turn_off_count']}`\n",
        "---\n",
        "## 1. Resume vs. LinkedIn Discrepancies (Trust & Background-Check Killers)\n",
    ]
    if not audit["discrepancies"]:
        md.append("- **PASS**: Zero date, title, or missing-role discrepancies detected between LinkedIn and Resume!\n")
    else:
        for d in audit["discrepancies"]:
            md.append(f"- **[{d['severity']}] {d['type']}**: {d['detail']}\n  - *Fix*: {d['fix']}")
        md.append("")

    md.append("## 2. Recruiter Turn-Offs & Negative Signals\n")
    if not audit["turn_offs"]:
        md.append("- **PASS**: Zero desperation markers, overlapping OE red flags, or hygiene turn-offs detected!\n")
    else:
        for t in audit["turn_offs"]:
            md.append(f"- **[{t['severity']}] {t['category']}**: {t['detail']}\n  - *Fix*: {t['fix']}")
        md.append("")

    md.append("## 3. LinkedIn Recruiter Boolean Search Gaps\n")
    if not audit["seo_gaps"]:
        md.append("- **PASS**: Strong keyword density across Headline, About, and Skills.\n")
    else:
        for g in audit["seo_gaps"]:
            md.append(f"- {g}")
        md.append("")

    fx = audit["turnkey_fixes"]
    md.extend([
        "---\n",
        "## 4. Copy-Pasteable Turnkey Fixes\n",
        f"### A. Clean Public URL Slug\n`{fx['recommended_slug']}`\n",
        "### B. 3 Recruiter-Optimized Headlines (<= 220 chars)\n",
    ])
    for i, h in enumerate(fx["headlines_220_char"], 1):
        md.append(f"{i}. `{h}` *({len(h)} chars)*")
    md.extend([
        "\n### C. Rewritten 'About' Section (Mobile-Fold Hook + XYZ Proof + Boolean Stack)\n",
        "```text",
        fx["rewritten_about_section"],
        "```\n",
        "### D. Canonical Timeline Lock (Mirror Exactly on LinkedIn & Every Tailored Resume)\n",
        "| Company | Synchronized Title | Synchronized Dates |",
        "| :--- | :--- | :--- |",
    ])
    for row in fx["canonical_timeline_to_mirror"]:
        md.append(f"| **{row['company']}** | {row['exact_title']} | `{row['exact_dates']}` |")

    if fx["top_skills_to_pin"]:
        md.append(f"\n### E. Top Skills to Pin & Reorder for LinkedIn Recruiter Filters\n`{', '.join(fx['top_skills_to_pin'])}`\n")

    md.extend([
        "### F. 5-Minute Settings Checklist\n",
        "- [ ] Set **Open to Work** visibility to **Recruiters Only** (remove public green `#OpenToWork` frame if mid/senior).",
        "- [ ] Populate all 5 target job titles in LinkedIn's Open-to-Work preferences.",
        "- [ ] Pin your top 3 hard skills to the top of your Skills list and request 3 peer endorsements.",
        "- [ ] Ensure every tailored resume you send uses the exact **Canonical Timeline Lock** dates & titles above.",
    ])
    return "\n".join(md) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Audit LinkedIn profile against Resume for discrepancies & turn-offs")
    parser.add_argument("--linkedin", required=True, help="Path to LinkedIn Profile.pdf, export ZIP/dir, or pasted .md/.txt")
    parser.add_argument("--resume", required=True, help="Path to Master or Tailored Resume (.md, .pdf, .docx)")
    parser.add_argument("--profile", default=None, help="Optional path to DATA_DIR/profile.md")
    parser.add_argument("--prefs", default=None, help="Optional path to DATA_DIR/preferences.md")
    parser.add_argument("--output", "-o", default=None, help="Optional output markdown report path")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    li_data = load_linkedin_data(Path(args.linkedin).expanduser().resolve())
    audit = audit_linkedin_vs_resume(
        li_data,
        Path(args.resume).expanduser().resolve(),
        Path(args.profile).expanduser().resolve() if args.profile else None,
        Path(args.prefs).expanduser().resolve() if args.prefs else None,
    )

    if args.output:
        out_p = Path(args.output).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(render_markdown_report(audit), encoding="utf-8")

    if args.json:
        print(json.dumps(audit, indent=2))
    else:
        print(render_markdown_report(audit))


if __name__ == "__main__":
    main()
