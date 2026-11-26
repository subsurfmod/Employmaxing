#!/usr/bin/env python3
"""
enricher.py - Transparent Personal & Career Profile Builder.
Extracts structured data from Resume/CV, LinkedIn, GitHub public API, and Personal Portfolio/Websites.
EVERY discovered fact is logged to EmploymaxingStore with provenance + consent_status ('pending_review')
so the user always knows and approves what information will be used in resumes, emails, and form fills.
Licensed under GNU GPL v3.0.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
SHARED_SCRIPTS = BASE_DIR / "shared" / "scripts"
for p in (str(BASE_DIR), str(SHARED_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from employmaxing.store import EmploymaxingStore
from linkedin_audit import extract_roles_from_text, load_linkedin_data
from optimizer import METRIC_REGEX, extract_jd_keywords
from parse_resume import extract_metadata, extract_text

USER_AGENT = "Employmaxing-ProfileEnricher/1.0 (+https://github.com/subsurfmod/Employmaxing)"


def ingest_resume(store: EmploymaxingStore, resume_path: Path, auto_approve_direct: bool = False) -> dict:
    """Parse resume/CV and register every extracted identity, role, skill, and quantified achievement."""
    text = extract_text(resume_path)
    meta = extract_metadata(text)
    roles = extract_roles_from_text(text)
    skills = extract_jd_keywords(text)
    status = "approved" if auto_approve_direct else "pending_review"
    src = f"resume:{resume_path.name}"
    count = 0

    for key in ("name", "email", "phone", "linkedin", "github"):
        val = meta.get(key)
        if val:
            cat = "identity" if key == "name" else ("social_link" if key in {"linkedin", "github"} else "contact")
            store.upsert_fact(cat, key, str(val), source=src, confidence=0.98, consent_status=status, planned_usage="resume,outreach_mail,form_fill")
            count += 1

    # Detect personal website / portfolio links beyond LinkedIn/GitHub
    for url in re.findall(r'https?://[A-Za-z0-9\.\-_]+(?:/[^\s\)\],]*)?', text):
        ul = url.lower()
        if any(skip in ul for skip in ("linkedin.com", "github.com", "mailto:")):
            continue
        store.upsert_fact("social_link", f"website:{ul.split('/')[2]}", url.rstrip(".,)"), source=src, source_url=url, confidence=0.9, consent_status=status, planned_usage="resume,form_fill")
        count += 1

    for idx, r in enumerate(roles):
        span = f"{r['start_month'] or ''}/{r['start_year']} - {'Present' if r['is_present'] else str(r['end_month'] or '') + '/' + str(r['end_year'])}".lstrip("/").replace(" - /", " - ")
        val = json.dumps({"company": r["company"], "title": r["title"], "dates": span, "is_present": r["is_present"]})
        store.upsert_fact("work_history", f"role_{idx+1}_{r['company_norm']}", val, source=src, confidence=0.95, consent_status=status, planned_usage="resume,form_fill,linkedin_fix")
        count += 1

    # Quantified XYZ achievements
    ach_idx = 0
    for line in text.splitlines():
        s = line.strip()
        if re.match(r'^[-*•]\s+', s) and METRIC_REGEX.search(s):
            ach_idx += 1
            clean = re.sub(r'^[-*•]\s+', '', s)
            store.upsert_fact("achievement", f"metric_win_{ach_idx}", clean, source=src, confidence=0.95, consent_status=status, planned_usage="resume,outreach_mail,cover_letter")
            count += 1

    if skills:
        store.upsert_fact("skill", "resume_core_skills", ", ".join(skills[:25]), source=src, confidence=0.95, consent_status=status, planned_usage="resume,form_fill,linkedin_fix")
        count += 1

    # Save canonical copy into DATA_DIR/resume/
    dest_md = store.data_dir / "resume" / "resume.md"
    dest_md.write_text(text, encoding="utf-8")
    store.log_event("resume_ingested", f"Extracted {count} facts from {resume_path.name}", {"file": str(resume_path), "facts": count})
    return {"facts_added": count, "metadata": meta, "roles_count": len(roles), "achievements_count": ach_idx}


def enrich_from_github(store: EmploymaxingStore, username_or_url: str) -> dict:
    """Discover public GitHub proof points (bio, stars, top repos, languages) as pending_review facts."""
    username = username_or_url.rstrip("/").split("/")[-1].strip()
    if not username:
        return {"error": "Empty GitHub username"}

    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    u_resp = requests.get(f"https://api.github.com/users/{username}", headers=headers, timeout=10)
    if u_resp.status_code != 200:
        return {"error": f"GitHub API returned {u_resp.status_code} for '{username}'"}
    user = u_resp.json()

    r_resp = requests.get(
        f"https://api.github.com/users/{username}/repos?sort=updated&per_page=30&type=owner",
        headers=headers,
        timeout=10,
    )
    repos = r_resp.json() if r_resp.status_code == 200 else []
    non_fork = [r for r in repos if not r.get("fork")]
    non_fork.sort(key=lambda r: (r.get("stargazers_count", 0), r.get("forks_count", 0)), reverse=True)

    count = 0
    profile_url = user.get("html_url", f"https://github.com/{username}")
    if user.get("bio"):
        store.upsert_fact("identity", "github_bio", user["bio"].strip(), source="github_api", source_url=profile_url, confidence=0.85, consent_status="pending_review", planned_usage="resume,linkedin_fix")
        count += 1
    if user.get("location"):
        store.upsert_fact("contact", "github_location", user["location"].strip(), source="github_api", source_url=profile_url, confidence=0.85, consent_status="pending_review", planned_usage="form_fill")
        count += 1
    if user.get("blog"):
        blog = user["blog"].strip()
        if blog and not blog.startswith("http"):
            blog = "https://" + blog
        store.upsert_fact("social_link", "github_website", blog, source="github_api", source_url=profile_url, confidence=0.9, consent_status="pending_review", planned_usage="resume,form_fill")
        count += 1

    total_stars = sum(r.get("stargazers_count", 0) for r in non_fork)
    langs = {}
    for r in non_fork:
        lg = r.get("language")
        if lg:
            langs[lg] = langs.get(lg, 0) + 1
    top_langs = [k for k, _ in sorted(langs.items(), key=lambda x: -x[1])[:8]]

    if top_langs:
        store.upsert_fact("skill", "github_languages", ", ".join(top_langs), source="github_api", source_url=profile_url, confidence=0.92, consent_status="pending_review", planned_usage="resume,form_fill,linkedin_fix")
        count += 1

    if total_stars > 0 or len(non_fork) >= 3:
        oss_summary = f"Maintains {len(non_fork)} public repositories on GitHub ({total_stars} total stars) across {', '.join(top_langs[:4]) or 'software engineering'}."
        store.upsert_fact("achievement", "github_oss_footprint", oss_summary, source="github_api", source_url=profile_url, confidence=0.9, consent_status="pending_review", planned_usage="resume,outreach_mail,linkedin_fix")
        count += 1

    for r in non_fork[:5]:
        desc = (r.get("description") or "Open-source project").strip()
        stars = r.get("stargazers_count", 0)
        lang = r.get("language") or "Code"
        val = f"{r['name']} ({lang}, {stars} stars): {desc}"
        store.upsert_fact("github_repo", f"repo:{r['name']}", val, source="github_api", source_url=r.get("html_url", profile_url), confidence=0.9, consent_status="pending_review", planned_usage="resume,outreach_mail")
        count += 1

    store.log_event("github_enriched", f"Discovered {count} pending facts from GitHub @{username}", {"username": username, "stars": total_stars, "repos": len(non_fork)})
    return {"username": username, "facts_discovered": count, "total_stars": total_stars, "top_languages": top_langs, "top_repos": [r["name"] for r in non_fork[:5]]}


def enrich_from_website(store: EmploymaxingStore, url: str) -> dict:
    """Scrape a personal portfolio/blog URL to uncover projects, talks, publications, and bio."""
    if not url.startswith("http"):
        url = "https://" + url
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code} fetching {url}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    title = (soup.title.string or "").strip() if soup.title else ""
    meta_desc = ""
    md_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if md_tag and md_tag.get("content"):
        meta_desc = md_tag["content"].strip()

    body_text = " ".join(soup.get_text(" ").split())
    count = 0
    if title or meta_desc:
        store.upsert_fact("portfolio", "site_summary", f"{title} — {meta_desc}".strip(" —"), source="portfolio_scrape", source_url=url, confidence=0.8, consent_status="pending_review", planned_usage="resume,outreach_mail,linkedin_fix")
        count += 1

    # Extract notable external proof links (Google Scholar, Substack, Medium, PyPI, npm, X)
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        hl = href.lower()
        for label, host in [
            ("google_scholar", "scholar.google.com"),
            ("pypi", "pypi.org"),
            ("npm", "npmjs.com"),
            ("crates", "crates.io"),
            ("substack", "substack.com"),
            ("medium", "medium.com"),
            ("arxiv", "arxiv.org"),
        ]:
            if host in hl:
                store.upsert_fact("publication", f"link:{label}", href, source="portfolio_scrape", source_url=url, confidence=0.85, consent_status="pending_review", planned_usage="resume,form_fill")
                count += 1

    # Extract any hard tech keywords mentioned on portfolio
    kws = extract_jd_keywords(body_text[:15000])
    if kws:
        store.upsert_fact("skill", "portfolio_keywords", ", ".join(kws[:15]), source="portfolio_scrape", source_url=url, confidence=0.75, consent_status="pending_review", planned_usage="resume")
        count += 1

    store.log_event("website_enriched", f"Discovered {count} pending facts from {url}", {"url": url})
    return {"url": url, "title": title, "facts_discovered": count}


def ingest_linkedin(store: EmploymaxingStore, li_path: Path) -> dict:
    """Ingest LinkedIn Save-to-PDF, Data Export ZIP, or text into the Consent Ledger."""
    li = load_linkedin_data(li_path)
    src = f"linkedin:{li_path.name}"
    count = 0
    if li.get("headline"):
        store.upsert_fact("identity", "linkedin_headline", li["headline"], source=src, confidence=0.95, consent_status="pending_review", planned_usage="linkedin_fix")
        count += 1
    if li.get("summary"):
        store.upsert_fact("identity", "linkedin_about", li["summary"][:1000], source=src, confidence=0.9, consent_status="pending_review", planned_usage="linkedin_fix,resume")
        count += 1
    if li.get("url"):
        store.upsert_fact("social_link", "linkedin_url", li["url"], source=src, source_url=li["url"], confidence=0.98, consent_status="pending_review", planned_usage="resume,form_fill")
        count += 1
    if li.get("skills"):
        store.upsert_fact("skill", "linkedin_skills", ", ".join(li["skills"][:30]), source=src, confidence=0.95, consent_status="pending_review", planned_usage="resume,linkedin_fix")
        count += 1
    for idx, r in enumerate(li.get("roles", [])):
        val = json.dumps({"company": r["company"], "title": r["title"], "start_year": r["start_year"], "end_year": r["end_year"], "is_present": r["is_present"]})
        store.upsert_fact("work_history", f"li_role_{idx+1}_{r['company_norm']}", val, source=src, confidence=0.95, consent_status="pending_review", planned_usage="linkedin_fix")
        count += 1
    store.log_event("linkedin_ingested", f"Imported {count} facts from LinkedIn ({li_path.name})", {"file": str(li_path)})
    return {"facts_added": count, "roles_count": len(li.get("roles", []))}


def compile_master_profile(store: EmploymaxingStore) -> dict:
    """
    Build master-profile.json, profile.md (STRICTLY Approved facts only),
    and DISCLOSURE-REPORT.md (Transparent ledger of EVERY fact planned for use + pending review).
    """
    all_facts = store.list_facts()
    approved = [f for f in all_facts if f["consent_status"] == "approved"]
    pending = [f for f in all_facts if f["consent_status"] == "pending_review"]
    rejected = [f for f in all_facts if f["consent_status"] in {"rejected", "redacted"}]

    master = {
        "approved_count": len(approved),
        "pending_review_count": len(pending),
        "rejected_count": len(rejected),
        "approved_by_category": {},
        "pending_review": pending,
    }
    for f in approved:
        master["approved_by_category"].setdefault(f["category"], []).append(f)

    (store.data_dir / "master-profile.json").write_text(json.dumps(master, indent=2), encoding="utf-8")

    # Build clean approved-only profile.md for all downstream skills
    prof_lines = [
        "# Master Career & Personal Profile (User-Approved Facts Only)\n",
        f"*Approved Facts: {len(approved)} | Pending Your Review: {len(pending)} | Excluded: {len(rejected)}*\n",
    ]
    for cat, items in master["approved_by_category"].items():
        prof_lines.append(f"## {cat.replace('_', ' ').title()}\n")
        for it in items:
            prof_lines.append(f"- **{it['fact_key']}**: {it['fact_value']} *(source: `{it['source']}`)*")
        prof_lines.append("")
    (store.data_dir / "profile.md").write_text("\n".join(prof_lines), encoding="utf-8")

    # Build Transparent Disclosure Report
    disc = [
        "# Employmaxing — Information Disclosure & Consent Ledger\n",
        "Every piece of personal or public data Employmaxing discovered and plans to use is listed below.",
        "**Nothing marked `pending_review` is ever sent in an email, resume, or application form until you approve it.**\n",
        f"## Pending Your Approval ({len(pending)})\n",
    ]
    if not pending:
        disc.append("_None — all discovered facts have been reviewed._\n")
    else:
        disc.append("| ID | Category | Fact | Source | Planned Usage |")
        disc.append("|---:|:---|:---|:---|:---|")
        for f in pending:
            val_preview = f["fact_value"].replace("\n", " ")[:95]
            disc.append(f"| `{f['id']}` | `{f['category']}` | **{f['fact_key']}**: {val_preview} | `{f['source']}` | `{f['planned_usage']}` |")
        disc.append("")

    disc.append(f"## Approved & Active ({len(approved)})\n")
    for f in approved:
        disc.append(f"- `[#{f['id']}]` **{f['category']}.{f['fact_key']}**: {f['fact_value'][:140]} *(used in: `{f['planned_usage']}`)*")

    (store.data_dir / "DISCLOSURE-REPORT.md").write_text("\n".join(disc) + "\n", encoding="utf-8")
    return master


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Transparent Profile Enricher")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--resume", default=None, help="Path to resume PDF/DOCX/MD")
    parser.add_argument("--linkedin", default=None, help="Path to LinkedIn Profile.pdf or export ZIP")
    parser.add_argument("--github", default=None, help="GitHub username or profile URL")
    parser.add_argument("--website", default=None, help="Personal website / portfolio URL")
    parser.add_argument("--auto-approve-resume", action="store_true", help="Auto-approve direct resume facts")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    store = EmploymaxingStore(args.data_dir)
    summary = {}
    if args.resume:
        summary["resume"] = ingest_resume(store, Path(args.resume).expanduser().resolve(), auto_approve_direct=args.auto_approve_resume)
    if args.linkedin:
        summary["linkedin"] = ingest_linkedin(store, Path(args.linkedin).expanduser().resolve())
    if args.github:
        summary["github"] = enrich_from_github(store, args.github)
    if args.website:
        summary["website"] = enrich_from_website(store, args.website)

    master = compile_master_profile(store)
    summary["ledger"] = {
        "approved": master["approved_count"],
        "pending_review": master["pending_review_count"],
        "disclosure_report": str(store.data_dir / "DISCLOSURE-REPORT.md"),
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print((store.data_dir / "DISCLOSURE-REPORT.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
