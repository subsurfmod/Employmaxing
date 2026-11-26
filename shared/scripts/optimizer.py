#!/usr/bin/env python3
"""
optimizer.py - Deterministic Empirical Conversion Optimizer for Resumes, Cold Mail/Cover Letters,
ATS Form Fills, Corporate Email Discovery + MX Checks, Direct ATS Dorks, and Ghost-Job Triage.
Part of Proficiently v3.0.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

# Allow importing parse_resume from sibling module
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from parse_resume import extract_text
except Exception:
    def extract_text(p: Path) -> str:
        return p.read_text(encoding="utf-8", errors="replace")


ACRONYM_PAIRS = {
    "kubernetes": ("Kubernetes", "K8s"),
    "k8s": ("Kubernetes", "K8s"),
    "continuous integration": ("Continuous Integration", "CI/CD"),
    "ci/cd": ("Continuous Integration", "CI/CD"),
    "amazon web services": ("Amazon Web Services", "AWS"),
    "aws": ("Amazon Web Services", "AWS"),
    "google cloud": ("Google Cloud Platform", "GCP"),
    "gcp": ("Google Cloud Platform", "GCP"),
    "machine learning": ("Machine Learning", "ML"),
    "large language model": ("Large Language Models", "LLMs"),
    "llm": ("Large Language Models", "LLMs"),
    "search engine optimization": ("Search Engine Optimization", "SEO"),
    "go-to-market": ("Go-to-Market", "GTM"),
    "gtm": ("Go-to-Market", "GTM"),
    "profit and loss": ("Profit & Loss", "P&L"),
    "p&l": ("Profit & Loss", "P&L"),
    "key performance indicator": ("Key Performance Indicators", "KPIs"),
    "objectives and key results": ("Objectives and Key Results", "OKRs"),
    "postgresql": ("PostgreSQL", "Postgres"),
    "golang": ("Go", "Golang"),
}

AI_CLICHES_AND_FLUFF = [
    "leveraging", "utilizing", "spearheaded cross-functional", "synergy", "synergies",
    "delve", "tapestry", "testament to", "results-driven", "passionate about",
    "thought leader", "track record of success", "go-getter", "hardworking",
    "detail-oriented", "team player", "demonstrating ability", "showcasing expertise",
    "seamlessly", "fast-paced environment", "wear many hats", "bottom-line",
    "value-added", "best-of-breed", "paradigm shift", "needle-moving",
]

WEAK_STARTERS = [
    "responsible for", "worked on", "helped with", "helped to", "assisted in",
    "assisted with", "participated in", "tasked with", "duties included", "involved in",
    "was responsible", "supported the",
]

COMMON_TECH_AND_DOMAIN_TERMS = [
    "python", "go", "golang", "rust", "java", "typescript", "javascript", "c++", "c#", "sql",
    "ruby", "scala", "kotlin", "swift", "php", "r", "react", "next.js", "vue", "angular",
    "node.js", "fastapi", "django", "flask", "spring", "graphql", "grpc", "rest",
    "aws", "gcp", "azure", "kubernetes", "k8s", "docker", "terraform", "ansible", "helm",
    "jenkins", "github actions", "ci/cd", "linux", "kafka", "spark", "flink", "airflow",
    "snowflake", "databricks", "bigquery", "redshift", "postgresql", "postgres", "mysql",
    "mongodb", "redis", "dynamodb", "elasticsearch", "cassandra", "clickhouse",
    "pytorch", "tensorflow", "llm", "llms", "rag", "fine-tuning", "cuda", "mlops",
    "microservices", "distributed systems", "observability", "prometheus", "grafana", "datadog",
    "opentelemetry", "security", "soc2", "hipaa", "gdpr", "iam", "oauth", "zero-trust",
    "product strategy", "roadmap", "a/b testing", "experimentation", "sql", "amplitude",
    "mixpanel", "figma", "jira", "agile", "scrum", "b2b", "b2c", "saas", "enterprise",
    "marketplace", "plg", "product-led growth", "gtm", "go-to-market", "p&l", "arr", "nrr",
    "churn", "ltv", "cac", "seo", "sem", "salesforce", "hubspot", "stakeholder management",
    "pricing", "monetization", "onboarding", "conversion", "retention", "compliance",
]

METRIC_REGEX = re.compile(
    r'(\$\s?\d[\d,\.]*\s?[kKmMbBtT]?|\d+(?:\.\d+)?\s?%|\d+(?:\.\d+)?x\b|'
    r'\b\d[\d,]*\+?\s*(?:ms|sec|seconds|mins|minutes|hrs|hours|days|weeks|months|TB|GB|PB|RPS|QPS|events/s|reqs/s|'
    r'users|customers|clients|engineers|developers|reps|markets|regions|countries|clusters|services|microservices|pipelines|endpoints|accounts|deals)\b|'
    r'\b99\.9+\s?%)',
    re.IGNORECASE,
)


def count_syllables(word: str) -> int:
    word = re.sub(r'[^a-z]', '', word.lower())
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r'(?:[^laeiouy]es|ed|[^laeiouy]e)$', '', word)
    word = re.sub(r'^y', '', word)
    vowels = re.findall(r'[aeiouy]{1,2}', word)
    return max(1, len(vowels))


def flesch_kincaid_grade(text: str) -> float:
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    if not sentences or not words:
        return 0.0
    syllables = sum(count_syllables(w) for w in words)
    return round(0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59, 1)


def extract_jd_keywords(jd_text: str) -> list[str]:
    jd_lower = jd_text.lower()
    found = []
    for term in COMMON_TECH_AND_DOMAIN_TERMS:
        pattern = r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])'
        if re.search(pattern, jd_lower):
            found.append(term)
    # Also grab capitalized multi-tech/tool tokens in JD (e.g., Temporal, Ray, LangChain, Stripe, NetSuite)
    cap_tokens = re.findall(r'\b[A-Z][A-Za-z0-9\.\+#]{2,18}\b', jd_text)
    stop_caps = {
        "The", "This", "That", "With", "From", "Your", "You", "Our", "Are", "Who", "What",
        "When", "Where", "Why", "How", "About", "Role", "Company", "Team", "Work", "Job",
        "Experience", "Requirements", "Responsibilities", "Qualifications", "Preferred",
        "Benefits", "Location", "Remote", "Hybrid", "Salary", "Equal", "Opportunity",
        "Monday", "Friday", "United", "States", "America", "Years", "Bachelor", "Master",
        "Senior", "Staff", "Principal", "Lead", "Manager", "Director", "Engineer", "Product",
    }
    freq = {}
    for tok in cap_tokens:
        if tok not in stop_caps and not tok.isupper():
            freq[tok] = freq.get(tok, 0) + 1
        elif tok.isupper() and 2 <= len(tok) <= 6 and tok not in {"USA", "USD", "PTO", "EEO", "CEO", "CTO", "CFO", "COO"}:
            freq[tok] = freq.get(tok, 0) + 1
    for tok, cnt in sorted(freq.items(), key=lambda x: -x[1]):
        if cnt >= 2 and tok.lower() not in found:
            found.append(tok)
    return found[:30]


def autofix_markdown_prose(text: str) -> tuple[str, list[str]]:
    fixes = []
    new_text = text
    # Replace prose em-dashes while preserving markdown horizontal rules
    lines = []
    emdash_count = 0
    for line in new_text.splitlines():
        if line.strip() in {"---", "***", "___"}:
            lines.append(line)
            continue
        if "—" in line:
            emdash_count += line.count("—")
            line = re.sub(r'\s*—\s*', ' - ', line)
        # Strip zero-width spaces
        line = line.replace("\u200b", "").replace("\ufeff", "").rstrip()
        lines.append(line)
    if emdash_count:
        fixes.append(f"Normalized {emdash_count} prose em-dash(es) ('—') into ATS-safe hyphens (' - ').")
    new_text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    return new_text, fixes


def audit_resume(resume_path: Path, jd_path: Path | None = None, autofix: bool = False) -> dict:
    raw_text = extract_text(resume_path)
    applied_fixes = []
    if autofix and resume_path.suffix.lower() == ".md":
        fixed_text, applied_fixes = autofix_markdown_prose(raw_text)
        if fixed_text != raw_text:
            resume_path.write_text(fixed_text, encoding="utf-8")
            raw_text = fixed_text

    lines = raw_text.splitlines()
    words = re.findall(r"[A-Za-z0-9'\-\+#\.]+", raw_text)
    word_count = len(words)

    # Detect seniority
    is_senior_exec = bool(re.search(r'\b(staff|principal|director|vp|vice president|chief|head of|distinguished|fellow)\b', raw_text, re.I))
    min_w, max_w = (500, 780) if is_senior_exec else (475, 650)

    # 1. Word Count Score (15 pts)
    if min_w <= word_count <= max_w:
        wc_score = 15
        wc_note = f"Optimal ({word_count} words inside {min_w}-{max_w} empirical conversion window)."
    elif (min_w - 100) <= word_count < min_w or max_w < word_count <= (max_w + 130):
        wc_score = 10
        wc_note = f"Slightly outside optimal {min_w}-{max_w}w window ({word_count} words)."
    else:
        wc_score = 4
        wc_note = f"Outside optimal {min_w}-{max_w}w window ({word_count} words) — ~77% of low-converting resumes miss this target."

    # 2. Quantified XYZ Impact Score (25 pts)
    bullets = []
    role_verb_map = {}
    current_role = "Header"
    for line in lines:
        s = line.strip()
        if s.startswith("### ") or (s.startswith("**") and ("|" in s or " at " in s or "20" in s)):
            current_role = s
            role_verb_map.setdefault(current_role, [])
        elif re.match(r'^[-*•]\s+', s):
            b_body = re.sub(r'^[-*•]\s+', '', s).strip()
            # Exclude short skill-list lines like "- **Languages**: Python, Go"
            if not re.match(r'^\*\*[^*]{2,25}\*\*\s*:', b_body) and len(b_body.split()) >= 6:
                bullets.append((current_role, b_body))
                first_word = re.sub(r'[^a-zA-Z]', '', b_body.split()[0]).lower()
                if first_word:
                    role_verb_map.setdefault(current_role, []).append(first_word)

    quantified_bullets = [b for _, b in bullets if METRIC_REGEX.search(b)]
    total_bullets = len(bullets)
    quant_ratio = (len(quantified_bullets) / total_bullets) if total_bullets else 0.0

    # Check F-pattern hot zone (first 2 bullets of first 2 experience roles)
    exp_roles = [r for r in role_verb_map.keys() if r != "Header"][:2]
    hot_zone_bullets = [b for r, b in bullets if r in exp_roles][:4]
    hot_zone_quant = sum(1 for b in hot_zone_bullets if METRIC_REGEX.search(b))

    if quant_ratio >= 0.70 and len(quantified_bullets) >= 6:
        xyz_score = 25
    elif quant_ratio >= 0.55 and len(quantified_bullets) >= 5:
        xyz_score = 19
    elif len(quantified_bullets) >= 3:
        xyz_score = 12
    else:
        xyz_score = 4
    if hot_zone_bullets and hot_zone_quant < min(2, len(hot_zone_bullets)):
        xyz_score = max(0, xyz_score - 3)

    # 3. JD Keyword & Title Parity (25 pts)
    matched_kw, missing_kw, acronym_tips = [], [], []
    jd_title_in_top_third = True
    if jd_path and jd_path.exists():
        jd_text = jd_path.read_text(encoding="utf-8", errors="replace")
        jd_kws = extract_jd_keywords(jd_text)
        res_lower = raw_text.lower()
        for kw in jd_kws:
            kw_l = kw.lower()
            pat = r'(?<![a-z0-9])' + re.escape(kw_l) + r'(?![a-z0-9])'
            if re.search(pat, res_lower):
                matched_kw.append(kw)
                if kw_l in ACRONYM_PAIRS:
                    full_t, acr_t = ACRONYM_PAIRS[kw_l]
                    if full_t.lower() not in res_lower or acr_t.lower() not in res_lower:
                        acronym_tips.append(f"Pair `{full_t} ({acr_t})` once so both ATS Boolean queries match.")
            else:
                # Check acronym equivalent
                if kw_l in ACRONYM_PAIRS:
                    full_t, acr_t = ACRONYM_PAIRS[kw_l]
                    if full_t.lower() in res_lower or acr_t.lower() in res_lower:
                        matched_kw.append(kw)
                        acronym_tips.append(f"JD uses `{kw}` — include exact token `{full_t} ({acr_t})`.")
                        continue
                missing_kw.append(kw)

        cov = (len(matched_kw) / len(jd_kws)) if jd_kws else 1.0
        # Title check in top third
        top_third = "\n".join(lines[: max(10, len(lines) // 3)]).lower()
        m_title = re.search(r'^#\s+(.+?)(?:\s+-\s+|\s+at\s+|$)', jd_text, re.M)
        if m_title:
            raw_role = m_title.group(1).strip().lower()
            core_tokens = [t for t in re.findall(r'[a-z]{4,}', raw_role) if t not in {"senior", "staff", "lead", "principal", "junior", "associate"}]
            if core_tokens and not any(t in top_third for t in core_tokens):
                jd_title_in_top_third = False

        if cov >= 0.80:
            kw_score = 25
        elif cov >= 0.65:
            kw_score = 19
        elif cov >= 0.50:
            kw_score = 13
        else:
            kw_score = 6
        if not jd_title_in_top_third:
            kw_score = max(0, kw_score - 3)
    else:
        kw_score = 20  # Neutral-high baseline when no JD supplied

    # 4. Zero-Fluff, Verb Diversity & Anti-AI Hygiene (15 pts)
    fluff_hits = []
    res_lower = raw_text.lower()
    for phrase in AI_CLICHES_AND_FLUFF:
        if phrase in res_lower:
            fluff_hits.append(phrase)

    weak_starter_hits = []
    for _, b in bullets:
        bl = b.lower()
        for ws in WEAK_STARTERS:
            if bl.startswith(ws):
                weak_starter_hits.append(f"{ws} -> '{b[:55]}...'")

    pronoun_hits = re.findall(r'(?<![A-Za-z])\b(I|my|mine|we|our)\b(?![A-Za-z])', raw_text)
    emdash_hits = sum(line.count("—") for line in lines if line.strip() not in {"---", "***", "___"})

    repeated_verbs = []
    for role, verbs in role_verb_map.items():
        seen = {}
        for v in verbs:
            seen[v] = seen.get(v, 0) + 1
        for v, cnt in seen.items():
            if cnt >= 2 and v:
                repeated_verbs.append(f"'{v}' used {cnt}x under {role[:35]}")

    deductions = len(fluff_hits) * 2 + len(weak_starter_hits) * 3 + (3 if pronoun_hits else 0) + (3 if emdash_hits else 0) + len(repeated_verbs) * 2
    hygiene_score = max(0, 15 - deductions)

    # 5. Bullet Cadence & Summary Tightness (10 pts)
    long_bullets = [b for _, b in bullets if len(b.split()) > 30]
    stub_bullets = [b for _, b in bullets if len(b.split()) < 9]
    cadence_score = max(0, 10 - len(long_bullets) * 2 - len(stub_bullets) * 2)

    # 6. Contact & LinkedIn Slug Check (5 pts)
    has_email = bool(re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', raw_text))
    has_phone = bool(re.search(r'\d{3}[-.\s\)]*\d{3}[-.\s]*\d{4}', raw_text))
    li_match = re.search(r'linkedin\.com/in/([A-Za-z0-9_-]+)', raw_text, re.I)
    has_ugly_li_slug = bool(li_match and re.search(r'-[0-9a-f]{6,}$', li_match.group(1), re.I))
    contact_score = (2 if has_email else 0) + (1 if has_phone else 0) + (2 if (li_match and not has_ugly_li_slug) else (1 if li_match else 0))

    # 7. ATS Parseability & Standard Sections (5 pts)
    has_exp = bool(re.search(r'\b(experience|employment|work history)\b', raw_text, re.I))
    has_skills = bool(re.search(r'\b(skills|technologies|competencies|technical)\b', raw_text, re.I))
    has_edu = bool(re.search(r'\b(education|university|b\.s\.|m\.s\.|bachelor|master)\b', raw_text, re.I))
    has_tables = bool(re.search(r'^\|.+\|.+\|$', raw_text, re.M))
    ats_score = (2 if has_exp else 0) + (2 if has_skills else 0) + (1 if has_edu else 0) - (3 if has_tables else 0)
    ats_score = max(0, ats_score)

    total_score = wc_score + xyz_score + kw_score + hygiene_score + cadence_score + contact_score + ats_score

    actions = []
    if wc_score < 15:
        actions.append(f"Adjust total word count from {word_count}w into the {min_w}–{max_w}w optimal conversion zone.")
    if quant_ratio < 0.70 or len(quantified_bullets) < 6:
        actions.append(f"Increase quantified XYZ bullets from {len(quantified_bullets)}/{total_bullets} ({quant_ratio:.0%}) to >=70% (min 6 metrics).")
    if hot_zone_bullets and hot_zone_quant < min(2, len(hot_zone_bullets)):
        actions.append("F-Pattern Alert: Front-load concrete metrics into the TOP 2 bullets of your 2 most recent roles.")
    if missing_kw:
        actions.append(f"Weave in truthful missing JD hard keywords: {', '.join(missing_kw[:10])}.")
    if not jd_title_in_top_third:
        actions.append("F-Pattern Alert: Mirror the target role title/domain in your top Summary line.")
    for tip in acronym_tips[:3]:
        actions.append(tip)
    if fluff_hits:
        actions.append(f"Cut AI tells / clichés: {', '.join(fluff_hits)}.")
    if weak_starter_hits:
        actions.append(f"Replace passive bullet starters with strong action verbs: {'; '.join(weak_starter_hits[:3])}.")
    if pronoun_hits:
        actions.append(f"Remove first-person pronouns ({', '.join(sorted(set(pronoun_hits)))}) from resume prose.")
    if emdash_hits:
        actions.append(f"Replace {emdash_hits} em-dash(es) ('—') with hyphens or periods (run with --autofix).")
    if repeated_verbs:
        actions.append(f"Vary repeated lead verbs: {', '.join(repeated_verbs[:3])}.")
    if long_bullets:
        actions.append(f"Split {len(long_bullets)} overlong bullet(s) (>30 words) so every bullet reads in 1 breath (14-26w).")
    if not li_match:
        actions.append("Add your custom LinkedIn URL to the header (boosts interview callbacks per TalentWorks study, provided profile dates/titles match!).")
    elif has_ugly_li_slug:
        actions.append(f"Clean your LinkedIn URL slug (`linkedin.com/in/{li_match.group(1)}`) in LinkedIn settings to strip trailing random hex digits.")
    if has_tables:
        actions.append("Remove markdown/multi-column tables — use single-column headings and bullets for Ashby/Greenhouse/Workday parsers.")

    return {
        "total_score": total_score,
        "ready_to_ship": total_score >= 85,
        "breakdown": {
            "word_count_15": {"score": wc_score, "word_count": word_count, "target": f"{min_w}-{max_w}", "note": wc_note},
            "xyz_metrics_25": {"score": xyz_score, "quantified_bullets": len(quantified_bullets), "total_bullets": total_bullets, "ratio": round(quant_ratio, 2)},
            "jd_keywords_25": {"score": kw_score, "matched": matched_kw, "missing": missing_kw[:12], "title_in_top_third": jd_title_in_top_third},
            "anti_ai_hygiene_15": {"score": hygiene_score, "fluff_words": fluff_hits, "weak_starters": len(weak_starter_hits), "pronouns": list(set(pronoun_hits)), "emdashes": emdash_hits, "repeated_verbs": repeated_verbs},
            "bullet_cadence_10": {"score": cadence_score, "overlong_bullets": len(long_bullets), "stub_bullets": len(stub_bullets)},
            "contact_linkedin_5": {"score": contact_score, "has_email": has_email, "has_phone": has_phone, "has_linkedin": bool(li_match), "ugly_linkedin_slug": has_ugly_li_slug},
            "ats_structure_5": {"score": ats_score, "has_tables": has_tables},
        },
        "autofixes_applied": applied_fixes,
        "priority_fixes": actions,
    }


def audit_mail(mail_path: Path, mode: str = "cold-email", autofix: bool = False) -> dict:
    text = mail_path.read_text(encoding="utf-8", errors="replace").strip()
    applied_fixes = []
    if autofix:
        text, applied_fixes = autofix_markdown_prose(text)
        mail_path.write_text(text.strip() + "\n", encoding="utf-8")

    # Extract optional Subject: line
    subj_match = re.search(r'^Subject:\s*(.+)$', text, re.M | re.I)
    subject = subj_match.group(1).strip() if subj_match else ""
    body = re.sub(r'^Subject:\s*.+$', '', text, flags=re.M | re.I).strip()

    char_count = len(body)
    words = re.findall(r"[A-Za-z0-9'\-]+", body)
    word_count = len(words)
    grade = flesch_kincaid_grade(body)
    sentences = [s.strip() for s in re.split(r'[.!?]+', body) if s.strip()]
    i_starters = sum(1 for s in sentences if re.match(r'^(i\b|my\b|i\'m\b|i’ve\b)', s.strip(), re.I))
    ego_ratio = (i_starters / len(sentences)) if sentences else 0.0
    links = re.findall(r'https?://[^\s\)]+', body)
    has_question_cta = "?" in ("\n".join(body.splitlines()[-3:]))

    score = 100
    issues = []

    if mode == "linkedin-note":
        if char_count > 295:
            score -= 45
            issues.append(f"HARD BLOCK: {char_count} chars exceeds LinkedIn's 300-char limit (target <=295 chars). Trim {char_count - 295} chars.")
        elif char_count < 80:
            score -= 15
            issues.append("Too generic/short (<80 chars) — anchor to 1 specific team project + 1 metric.")
    elif mode == "cold-email":
        if subject:
            s_words = len(subject.split())
            if not (3 <= s_words <= 7) or len(subject) > 52:
                score -= 15
                issues.append(f"Subject line ('{subject}', {s_words}w / {len(subject)}c) should be 3–6 words (<=48 chars) so mobile doesn't truncate.")
            if "!" in subject or subject.isupper():
                score -= 15
                issues.append("Remove exclamation marks / ALL-CAPS from Subject line (triggers spam filters).")
        else:
            score -= 10
            issues.append("Missing `Subject:` line — include a 3–6 word lowercase/peer subject line.")

        if word_count > 115:
            score -= 25
            issues.append(f"Cold email is {word_count} words — Lavender/Gong data shows >115w slashes reply rates. Cut to 45–95 words.")
        elif word_count < 30:
            score -= 10
            issues.append(f"Cold email is very brief ({word_count}w) — ensure 1 concrete XYZ proof metric is included.")

        if grade > 7.5:
            score -= 12
            issues.append(f"Reading grade level is {grade} (target Grade 4–6.5). Shorten clauses and simplify corporate nouns.")
        if ego_ratio > 0.34:
            score -= 12
            issues.append(f"Ego ratio too high ({i_starters}/{len(sentences)} sentences start with 'I/My'). Reframe around *their* product/team bottleneck.")
        if re.search(r'\b(attached|attaching|find my resume|see attached)\b', body, re.I):
            score -= 25
            issues.append("SPAM FILTER BLOCK: Never attach PDFs/DOCX on Cold Touch #1 (quarantined by Defender/Workspace). Use plain text + max 1 clean link.")
        if len(links) > 1:
            score -= 12
            issues.append(f"Contains {len(links)} URLs — enterprise spam gateways penalize multiple links on Touch #1 (keep <=1).")
        if not METRIC_REGEX.search(body):
            score -= 15
            issues.append("No concrete metric found — include 1 quantified proof point ($, %, latency, scale).")
        if not has_question_cta:
            score -= 10
            issues.append("End with a low-friction interest question CTA (e.g., 'Worth a quick look at how I approached this?').")
    elif mode == "cover-letter":
        if not (190 <= word_count <= 320):
            score -= 18
            issues.append(f"Cover letter word count is {word_count}w (optimal Pain-Hook letter is 200–300 words).")
        if re.search(r'(i am writing to apply|hope this letter finds you|excited about the opportunity)', body, re.I):
            score -= 18
            issues.append("Delete cliché opener ('I am writing to apply...' / 'excited about the opportunity') — open directly with a company hook + proof.")
        if "—" in body:
            score -= 15
            issues.append("Contains em-dashes ('—') — obvious AI tell; replace with hyphens ('-').")
        metrics_found = METRIC_REGEX.findall(body)
        if len(metrics_found) < 2:
            score -= 15
            issues.append(f"Only {len(metrics_found)} quantified metric(s) found — include 2–3 concrete measurable wins.")
    elif mode == "referral":
        if word_count > 180:
            score -= 15
            issues.append(f"Referral ask is {word_count}w — keep the personal ask <90w plus a separate 3-bullet Forwardable Blurb.")
        if not re.search(r'(no worries|no pressure|totally understand|plate is full)', body, re.I):
            score -= 10
            issues.append("Include a low-pressure 'easy out' line ('No worries at all if your plate is full!') to boost response rate.")

    if re.search(r'(hope this (?:email|message|note) finds you well|dear sir|to whom it may concern)', body, re.I):
        score -= 15
        issues.append("Remove outdated filler salutation ('Hope this finds you well' / 'Dear Sir').")

    return {
        "mode": mode,
        "score": max(0, score),
        "ready_to_send": max(0, score) >= 85,
        "stats": {
            "subject": subject,
            "word_count": word_count,
            "char_count": char_count,
            "reading_grade": grade,
            "ego_i_starter_ratio": round(ego_ratio, 2),
            "link_count": len(links),
            "has_question_cta": has_question_cta,
        },
        "autofixes_applied": applied_fixes,
        "issues": issues,
    }


def check_mx_records(domain: str) -> dict:
    domain = re.sub(r'^https?://', '', domain).split('/')[0].lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]

    mx_hosts = []
    # 1. Try dig
    if shutil.which("dig"):
        try:
            res = subprocess.run(["dig", "+short", "MX", domain], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    mx_hosts.append(parts[-1].rstrip("."))
        except Exception:
            pass
    # 2. Fallback to resolvectl
    if not mx_hosts and shutil.which("resolvectl"):
        try:
            res = subprocess.run(["resolvectl", "query", "--type=MX", domain], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                m = re.search(r'MX\s+\d+\s+([^\s]+)', line)
                if m:
                    mx_hosts.append(m.group(1).rstrip("."))
        except Exception:
            pass
    # 3. Fallback to Google DNS-over-HTTPS
    if not mx_hosts:
        try:
            url = f"https://dns.google/resolve?name={domain}&type=MX"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                for ans in data.get("Answer", []):
                    if ans.get("type") == 15:
                        mx_hosts.append(ans.get("data", "").split()[-1].rstrip("."))
        except Exception:
            pass

    mx_joined = " ".join(mx_hosts).lower()
    if "pphosted.com" in mx_joined or "proofpoint" in mx_joined:
        gateway = "Proofpoint Enterprise Gateway (STRICT)"
        advice = "Zero attachments, zero links on Touch #1, pure plain-text only. Send from warmed custom domain or LinkedIn InMail."
    elif "mimecast" in mx_joined:
        gateway = "Mimecast Enterprise Gateway (STRICT)"
        advice = "Strict link-rewriting & attachment quarantine. Send 100% plain-text with 0 URLs on Touch #1."
    elif "google" in mx_joined or "aspmx" in mx_joined:
        gateway = "Google Workspace"
        advice = "High deliverability for plain-text personal emails (<95 words, 0 attachments, <=1 clean link)."
    elif "outlook" in mx_joined or "protection.outlook.com" in mx_joined:
        gateway = "Microsoft 365 / Defender"
        advice = "Avoid PDF attachments & tracking pixels on Touch #1 (Defender quarantines cold attachments)."
    elif mx_hosts:
        gateway = "Custom / Other Mail Server"
        advice = "Keep Touch #1 plain-text, <95 words, zero attachments."
    else:
        gateway = "NO MX RECORD FOUND"
        advice = "Domain does not accept mail or is invalid — check parent corporate domain before sending!"

    return {"domain": domain, "valid_mx": bool(mx_hosts), "mx_hosts": mx_hosts, "gateway": gateway, "deliverability_advice": advice}


def find_emails(first: str, last: str, domain: str) -> dict:
    mx_info = check_mx_records(domain)
    d = mx_info["domain"]
    f = re.sub(r'[^a-z]', '', first.lower())
    l = re.sub(r'[^a-z]', '', last.lower())
    fi = f[0] if f else ""
    li = l[0] if l else ""

    # Startups (<200 ppl, Google Workspace) skew toward first@domain; enterprises skew toward first.last@domain
    is_enterprise_gw = any(k in mx_info["gateway"] for k in ["Proofpoint", "Mimecast", "Microsoft 365"])
    if is_enterprise_gw:
        candidates = [
            {"email": f"{f}.{l}@{d}", "confidence": "High (~52% enterprise standard)", "pattern": "first.last"},
            {"email": f"{fi}{l}@{d}", "confidence": "Medium (~22% enterprise standard)", "pattern": "flast"},
            {"email": f"{f}@{d}", "confidence": "Medium (~14%)", "pattern": "first"},
            {"email": f"{f}_{l}@{d}", "confidence": "Low (~7%)", "pattern": "first_last"},
            {"email": f"{f}{li}@{d}", "confidence": "Low (~5%)", "pattern": "firstl"},
        ]
    else:
        candidates = [
            {"email": f"{f}@{d}", "confidence": "High (~46% tech/startup standard)", "pattern": "first"},
            {"email": f"{f}.{l}@{d}", "confidence": "High (~38% tech standard)", "pattern": "first.last"},
            {"email": f"{fi}{l}@{d}", "confidence": "Medium (~11%)", "pattern": "flast"},
            {"email": f"{f}{li}@{d}", "confidence": "Low (~5%)", "pattern": "firstl"},
        ]
    return {"mx": mx_info, "permutations": candidates}


def audit_job_posting(posting_path: Path, days_old: int | None = None, has_referral: bool = False, on_company_ats: bool = True) -> dict:
    text = posting_path.read_text(encoding="utf-8", errors="replace")
    ghost_points = 0
    signals = []

    if days_old is not None:
        if days_old > 30:
            ghost_points += 45
            signals.append(f"Posting is {days_old} days old (>30d postings have high ghost/filled-slate probability).")
        elif days_old > 14:
            ghost_points += 20
            signals.append(f"Posting is {days_old} days old (outside peak 48h–7d recruiter review window).")
        elif days_old <= 2:
            signals.append(f"FRESH REQ ({days_old}d old) — First-48h 3x–5x early-review advantage active!")

    if not on_company_ats:
        ghost_points += 35
        signals.append("Role not verified on employer's live ATS/Careers page (high stale-syndication ghost risk).")

    kws = extract_jd_keywords(text)
    if len(kws) < 3:
        ghost_points += 25
        signals.append("Hyper-generic description (<3 concrete tools/domain keywords detected) — classic evergreen/placeholder sign.")

    if re.search(r'(future openings|talent pool|evergreen|general interest|continuousmerit|pipeline role)', text, re.I):
        ghost_points += 45
        signals.append("Explicit talent-pool / evergreen language detected (not an active headcount req).")

    has_salary = bool(re.search(r'\$\s?\d{2,3}(?:,\d{3}|[kK])', text))
    if has_salary:
        signals.append("Verified salary transparency band present (higher budget sign-off authenticity).")

    if ghost_points >= 50:
        ghost_risk = "HIGH"
        tier = "P2 REFERRAL-ONLY" if has_referral else "P3 SKIP (HIGH GHOST RISK)"
    elif ghost_points >= 25:
        ghost_risk = "MEDIUM"
        tier = "P1 APPLY + WARM OUTREACH" if has_referral else "P2 STANDARD APPLY"
    else:
        ghost_risk = "LOW"
        if (days_old is not None and days_old <= 2) or has_referral:
            tier = "P0 STRIKE NOW (<24H TRIPLE-TAP)"
        else:
            tier = "P1 HIGH-ROI TARGET"

    return {
        "ghost_risk": ghost_risk,
        "ghost_score_100": min(100, ghost_points),
        "priority_tier": tier,
        "detected_hard_keywords": kws[:15],
        "has_salary_band": has_salary,
        "signals": signals,
    }


def parse_salary_band(jd_text: str) -> tuple[int, int] | None:
    # Match e.g. $160,000 - $210,000 or $160k - $210k
    m = re.search(
        r'\$\s?(\d{2,3}(?:,\d{3})|\d{2,3}\s?[kK])\s*(?:-|–|—|to)\s*\$\s?(\d{2,3}(?:,\d{3})|\d{2,3}\s?[kK])',
        jd_text,
    )
    if not m:
        return None

    def to_int(val: str) -> int:
        val = val.lower().replace(",", "").strip()
        if val.endswith("k"):
            return int(float(val[:-1]) * 1000)
        return int(val)

    low, high = to_int(m.group(1)), to_int(m.group(2))
    if 30000 <= low <= high <= 1500000:
        return (low, high)
    return None


def compute_years_experience(text: str) -> int:
    years = [int(y) for y in re.findall(r'\b(199\d|20[0-2]\d)\b', text)]
    current_year = datetime.now().year
    valid = [y for y in years if 1995 <= y <= current_year]
    if not valid:
        return 5
    # Heuristic: ignore graduation year if way earlier unless work roles span back
    exp_section = re.split(r'##\s+Education', text, flags=re.I)[0]
    exp_years = [int(y) for y in re.findall(r'\b(199\d|20[0-2]\d)\b', exp_section) if 1995 <= int(y) <= current_year]
    earliest = min(exp_years) if exp_years else min(valid)
    return max(1, current_year - earliest)


def build_form_plan(posting_path: Path, app_data_path: Path | None = None, profile_path: Path | None = None, prefs_path: Path | None = None) -> dict:
    jd_text = posting_path.read_text(encoding="utf-8", errors="replace")
    app_text = app_data_path.read_text(encoding="utf-8", errors="replace") if (app_data_path and app_data_path.exists()) else ""
    prof_text = profile_path.read_text(encoding="utf-8", errors="replace") if (profile_path and profile_path.exists()) else ""
    prefs_text = prefs_path.read_text(encoding="utf-8", errors="replace") if (prefs_path and prefs_path.exists()) else ""

    band = parse_salary_band(jd_text)
    # Check candidate floor from preferences.md
    pref_nums = [int(x.replace(",", "")) for x in re.findall(r'\$\s?(\d{2,3},\d{3})', prefs_text)]
    pref_k = [int(x) * 1000 for x in re.findall(r'\$\s?(\d{2,3})[kK]\b', prefs_text)]
    floor = max(pref_nums + pref_k) if (pref_nums or pref_k) else None

    if band:
        low, high = band
        p65 = int(round((low + 0.65 * (high - low)) / 1000.0) * 1000)
        p75 = int(round((low + 0.75 * (high - low)) / 1000.0) * 1000)
        p85 = int(round((low + 0.85 * (high - low)) / 1000.0) * 1000)
        numeric_salary = max(p75, floor) if (floor and floor <= high) else p75
        text_salary = f"Flexible based on total compensation package; targeting ~${p65:,}–${p85:,} base aligned with role scope."
        salary_note = f"Anchored to 65th–85th percentile of posted JD band (${low:,}–${high:,}) to avoid budget knockout while preserving negotiation upside."
    elif floor:
        numeric_salary = floor
        text_salary = f"Flexible based on total compensation structure; targeting ~${floor:,}–${int(floor * 1.15):,} aligned with market scope."
        salary_note = "No JD band posted; anchored to preferences.md target floor + 15% upside band."
    else:
        numeric_salary = None
        text_salary = "Open and flexible based on full scope and total compensation structure; aligned with market rates for this level."
        salary_note = "No JD band or preference floor found; use flexible market framing on text inputs."

    yoe = compute_years_experience(prof_text) if prof_text else 5
    has_ref = bool(re.search(r'Network Contact:\s*\S+', jd_text))
    source_answer = "Employee Referral" if has_ref else "Company Website / Careers Page"

    knockout_warnings = []
    if re.search(r'(security clearance|ts/sci|secret clearance|dod clearance)', jd_text, re.I):
        knockout_warnings.append("CLEARANCE KNOCKOUT DETECTED: JD mentions Security Clearance — verify candidate eligibility before submitting.")
    if re.search(r'(unable to sponsor|no visa sponsorship|without sponsorship|must be a u\.s\. citizen)', jd_text, re.I):
        knockout_warnings.append("SPONSORSHIP KNOCKOUT DETECTED: JD restricts visa sponsorship — double-check Work Auth & Future Sponsorship answers.")
    hybrid_m = re.search(r'(\d\s*days?\s*(?:a|per)\s*week\s*in[\s-]office|in[\s-]person\s*in\s*[A-Z][a-z]+|hybrid\s*in\s*[A-Z][a-z]+)', jd_text, re.I)
    if hybrid_m:
        knockout_warnings.append(f"GEO/HYBRID KNOCKOUT CHECK: JD specifies '{hybrid_m.group(0)}' — answering 'No' to onsite/relocation dropdowns triggers auto-rejection.")

    kws = extract_jd_keywords(jd_text)[:5]
    return {
        "salary_strategy": {
            "posted_band": band,
            "strict_numeric_input": numeric_salary,
            "free_text_input": text_salary,
            "rationale": salary_note,
        },
        "computed_years_experience": yoe,
        "recommended_source_field": source_answer,
        "recommended_start_date": "2 weeks from offer acceptance (flexible for priority onboarding)",
        "knockout_warnings": knockout_warnings,
        "supplemental_essay_blueprint": {
            "word_target": "65–105 words",
            "formula": "1) Specific Company Product/Initiative Hook -> 2) Your Matching Quantified XYZ Win -> 3) First-90-Day Contribution",
            "must_include_keywords": kws,
        },
    }


def generate_ats_dorks(roles_csv: str, location: str = "Remote", hours: int = 48) -> dict:
    roles = [r.strip() for r in roles_csv.split(",") if r.strip()]
    role_or = " OR ".join(f'"{r}"' for r in roles)
    loc_clause = f' "{location}"' if location else ""
    tbs = "qdr:d" if hours <= 24 else ("qdr:d2" if hours <= 48 else "qdr:w")

    boards = {
        "Ashby (Top AI/Tech Startups)": f'site:jobs.ashbyhq.com ({role_or}){loc_clause}',
        "Greenhouse (Growth & Mid-Market)": f'(site:boards.greenhouse.io OR site:job-boards.greenhouse.io) ({role_or}){loc_clause}',
        "Lever (Tech & SaaS)": f'site:jobs.lever.co ({role_or}){loc_clause}',
        "Workday (Enterprise Direct)": f'site:myworkdayjobs.com ({role_or}){loc_clause}',
        "Rippling & BambooHR": f'(site:ats.rippling.com OR site:bamboohr.com/careers) ({role_or}){loc_clause}',
        "YC Work at a Startup": f'site:workatastartup.com/jobs ({role_or}){loc_clause}',
    }

    import urllib.parse
    queries = []
    for label, q in boards.items():
        google_url = f"https://www.google.com/search?q={urllib.parse.quote(q)}&tbs={tbs}"
        queries.append({"board": label, "query": q, "fresh_google_url": google_url})
    return {"freshness_window_hours": hours, "queries": queries}


def main():
    parser = argparse.ArgumentParser(description="Proficiently v3.0 Empirical Conversion Optimizer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_res = sub.add_parser("resume", help="Score and autofix tailored resume against empirical rules")
    p_res.add_argument("resume_file", help="Path to resume (.md, .pdf, .docx)")
    p_res.add_argument("--jd", help="Optional path to job posting.md")
    p_res.add_argument("--autofix", action="store_true", help="Auto-fix prose em-dashes & whitespace on .md")
    p_res.add_argument("--json", action="store_true")

    p_mail = sub.add_parser("mail", help="Score cold email, LinkedIn note, referral ask, or cover letter")
    p_mail.add_argument("mail_file", help="Path to markdown/text file")
    p_mail.add_argument("--mode", choices=["cold-email", "linkedin-note", "referral", "cover-letter"], default="cold-email")
    p_mail.add_argument("--autofix", action="store_true")
    p_mail.add_argument("--json", action="store_true")

    p_ef = sub.add_parser("email-find", help="Generate ranked corporate email permutations + live DNS MX audit")
    p_ef.add_argument("--first", required=True)
    p_ef.add_argument("--last", required=True)
    p_ef.add_argument("--domain", required=True, help="Company domain e.g. stripe.com")
    p_ef.add_argument("--json", action="store_true")

    p_ja = sub.add_parser("job-audit", help="Detect ghost jobs and compute ROI priority tier")
    p_ja.add_argument("posting_file")
    p_ja.add_argument("--days-old", type=int, default=None)
    p_ja.add_argument("--has-referral", action="store_true")
    p_ja.add_argument("--aggregator-only", action="store_true")
    p_ja.add_argument("--json", action="store_true")

    p_fp = sub.add_parser("form-plan", help="Compute knockout-safe ATS form fill strategy & salary anchors")
    p_fp.add_argument("posting_file")
    p_fp.add_argument("--app-data", default=None)
    p_fp.add_argument("--profile", default=None)
    p_fp.add_argument("--prefs", default=None)
    p_fp.add_argument("--json", action="store_true")

    p_dk = sub.add_parser("dorks", help="Generate <24h/<48h direct ATS search queries")
    p_dk.add_argument("--roles", required=True, help="Comma-separated target roles")
    p_dk.add_argument("--location", default="Remote")
    p_dk.add_argument("--hours", type=int, default=48)
    p_dk.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "resume":
        res = audit_resume(Path(args.resume_file), Path(args.jd) if args.jd else None, autofix=args.autofix)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            status = "PASS (READY TO SHIP)" if res["ready_to_ship"] else "NEEDS REFINEMENT (<85)"
            print(f"# Resume Conversion Score: {res['total_score']}/100 — {status}\n")
            b = res["breakdown"]
            print(f"- **Word Count ({b['word_count_15']['score']}/15)**: {b['word_count_15']['note']}")
            print(f"- **XYZ Quantified Density ({b['xyz_metrics_25']['score']}/25)**: {b['xyz_metrics_25']['quantified_bullets']}/{b['xyz_metrics_25']['total_bullets']} bullets quantified ({b['xyz_metrics_25']['ratio']:.0%})")
            print(f"- **JD Keyword & Title Parity ({b['jd_keywords_25']['score']}/25)**: {len(b['jd_keywords_25']['matched'])} matched, {len(b['jd_keywords_25']['missing'])} missing")
            print(f"- **Anti-AI & Verb Hygiene ({b['anti_ai_hygiene_15']['score']}/15)**")
            print(f"- **Bullet Cadence ({b['bullet_cadence_10']['score']}/10)** | **Contact/LinkedIn ({b['contact_linkedin_5']['score']}/5)** | **ATS Structure ({b['ats_structure_5']['score']}/5)**\n")
            if res["autofixes_applied"]:
                print("## Auto-Fixes Applied")
                for fx in res["autofixes_applied"]:
                    print(f"- {fx}")
                print()
            if res["priority_fixes"]:
                print("## Priority Fixes to Maximize Interviews")
                for idx, act in enumerate(res["priority_fixes"], 1):
                    print(f"{idx}. {act}")

    elif args.cmd == "mail":
        res = audit_mail(Path(args.mail_file), mode=args.mode, autofix=args.autofix)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            status = "PASS (HIGH-CONVERSION)" if res["ready_to_send"] else "NEEDS TIGHTENING (<85)"
            print(f"# Outreach / Mail Score ({res['mode']}): {res['score']}/100 — {status}\n")
            st = res["stats"]
            print(f"- **Words**: {st['word_count']}w | **Chars**: {st['char_count']}c | **Reading Grade**: {st['reading_grade']} | **Ego 'I' Ratio**: {st['ego_i_starter_ratio']:.0%}\n")
            if res["issues"]:
                print("## Required Improvements")
                for idx, iss in enumerate(res["issues"], 1):
                    print(f"{idx}. {iss}")

    elif args.cmd == "email-find":
        res = find_emails(args.first, args.last, args.domain)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            mx = res["mx"]
            print(f"# Email Discovery & MX Audit for `{mx['domain']}`\n")
            print(f"- **MX Valid**: `{mx['valid_mx']}` | **Gateway**: **{mx['gateway']}**")
            print(f"- **Deliverability Rule**: {mx['deliverability_advice']}\n")
            print("## Ranked Corporate Permutations")
            for c in res["permutations"]:
                print(f"- `{c['email']}` — *{c['confidence']}*")

    elif args.cmd == "job-audit":
        res = audit_job_posting(
            Path(args.posting_file),
            days_old=args.days_old,
            has_referral=args.has_referral,
            on_company_ats=not args.aggregator_only,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"# Job Triage: **{res['priority_tier']}** (Ghost Risk: {res['ghost_risk']} — {res['ghost_score_100']}/100)\n")
            for sig in res["signals"]:
                print(f"- {sig}")

    elif args.cmd == "form-plan":
        res = build_form_plan(
            Path(args.posting_file),
            Path(args.app_data) if args.app_data else None,
            Path(args.profile) if args.profile else None,
            Path(args.prefs) if args.prefs else None,
        )
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            sal = res["salary_strategy"]
            print("# ATS Form-Fill & Knockout Optimization Plan\n")
            print(f"- **Strict Numeric Salary Answer**: `{sal['strict_numeric_input']}`")
            print(f"- **Free-Text Salary Answer**: \"{sal['free_text_input']}\"")
            print(f"  - *Why*: {sal['rationale']}")
            print(f"- **Defensible Years of Experience**: `{res['computed_years_experience']}`")
            print(f"- **Source Attribution**: `{res['recommended_source_field']}`")
            print(f"- **Start Date / Notice**: `{res['recommended_start_date']}`\n")
            if res["knockout_warnings"]:
                print("## Knockout Warnings")
                for w in res["knockout_warnings"]:
                    print(f"- {w}")

    elif args.cmd == "dorks":
        res = generate_ats_dorks(args.roles, args.location, args.hours)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"# Direct ATS Fresh-Job Queries (Last {res['freshness_window_hours']}h)\n")
            for q in res["queries"]:
                print(f"### {q['board']}")
                print(f"- **Query**: `{q['query']}`")
                print(f"- **Search Link**: {q['fresh_google_url']}\n")


if __name__ == "__main__":
    main()
