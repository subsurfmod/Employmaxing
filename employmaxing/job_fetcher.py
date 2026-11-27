#!/usr/bin/env python3
"""
job_fetcher.py - Zero-CLI Job Posting Fetcher for Ashby, Greenhouse, Lever, BambooHR, and generic URLs.
Uses clean public ATS JSON APIs first (Greenhouse Boards API, Lever Postings API) with BeautifulSoup
HTML extraction fallback so JS-heavy job boards parse cleanly right inside the Web UI.
Licensed under GNU GPL v3.0.
"""

import json
import re
import urllib.parse
from bs4 import BeautifulSoup
import requests

from employmaxing.form_filler import detect_ats

UA = "Employmaxing-JobFetcher/1.4 (+https://github.com/subsurfmod/Employmaxing)"


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_salary(text: str) -> str:
    m = re.search(r'\$\s?\d{2,3}(?:,\d{3}|[kK])\s*(?:-|–|—|to)\s*\$\s?\d{2,3}(?:,\d{3}|[kK])', text)
    return m.group(0) if m else ""


def _try_greenhouse_api(url: str) -> dict | None:
    m = re.search(r'(?:boards|job-boards)\.greenhouse\.io/([^/\?]+)/jobs/(\d+)', url, re.I)
    if not m:
        return None
    board, job_id = m.group(1), m.group(2)
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}", headers={"User-Agent": UA}, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    desc = _clean_html(data.get("content", ""))
    title = data.get("title", "").strip()
    loc = (data.get("location") or {}).get("name", "")
    company = board.replace("-", " ").title()
    return {
        "company": company,
        "role": title,
        "location": loc,
        "ats_type": "greenhouse",
        "salary_band": _extract_salary(desc),
        "posting_text": f"# {title} - {company}\nLocation: {loc}\nURL: {url}\n\n{desc}",
    }


def _try_lever_api(url: str) -> dict | None:
    m = re.search(r'jobs\.lever\.co/([^/\?]+)/([a-f0-9\-]{8,})', url, re.I)
    if not m:
        return None
    company_slug, job_id = m.group(1), m.group(2)
    r = requests.get(f"https://api.lever.co/v0/postings/{company_slug}/{job_id}", headers={"User-Agent": UA}, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    title = data.get("text", "").strip()
    cats = data.get("categories") or {}
    loc = cats.get("location", "")
    parts = [data.get("descriptionPlain") or _clean_html(data.get("description", ""))]
    for lst in data.get("lists", []):
        parts.append(f"\n## {lst.get('text', '')}\n" + _clean_html(lst.get("content", "")))
    if data.get("additionalPlain"):
        parts.append("\n" + data["additionalPlain"])
    body = "\n".join(p for p in parts if p).strip()
    company = company_slug.replace("-", " ").title()
    return {
        "company": company,
        "role": title,
        "location": loc,
        "ats_type": "lever",
        "salary_band": _extract_salary(body),
        "posting_text": f"# {title} - {company}\nLocation: {loc}\nURL: {url}\n\n{body}",
    }


def fetch_job_from_url(url: str) -> dict:
    """Fetch and extract structured metadata + clean description from any job posting URL."""
    url = (url or "").strip()
    if not url.startswith("http"):
        raise ValueError("Please provide a valid http(s) job posting URL.")

    ats = detect_ats(url)

    # 1. Fast public JSON APIs for Greenhouse & Lever
    try:
        if ats == "greenhouse":
            gh = _try_greenhouse_api(url)
            if gh:
                return gh
        elif ats == "lever":
            lv = _try_lever_api(url)
            if lv:
                return lv
    except Exception:
        pass

    # 2. General HTML + JSON-LD JobPosting extractor (works great for Ashby, BambooHR, company sites)
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=12)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    company, role, location, body_text = "", "", "", ""

    # Check schema.org JSON-LD JobPosting block (Ashby, Workday, BambooHR & most modern boards embed this!)
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = json.loads(script.string or "")
            objs = raw if isinstance(raw, list) else [raw]
            for obj in objs:
                if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
                    role = obj.get("title", "") or role
                    org = obj.get("hiringOrganization")
                    if isinstance(org, dict):
                        company = org.get("name", "") or company
                    jl = obj.get("jobLocation")
                    if isinstance(jl, list) and jl:
                        jl = jl[0]
                    if isinstance(jl, dict):
                        addr = jl.get("address") or {}
                        if isinstance(addr, dict):
                            location = ", ".join(x for x in (addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")) if x)
                    if obj.get("description"):
                        body_text = _clean_html(obj["description"])
        except Exception:
            continue

    # Fallback title/meta extraction
    if not role or not company:
        page_title = (soup.title.string or "").strip() if soup.title else ""
        if " at " in page_title:
            r_p, c_p = page_title.split(" at ", 1)
            role = role or r_p.strip()
            company = company or c_p.split("|")[0].split("-")[0].strip()
        elif " - " in page_title:
            parts = [p.strip() for p in page_title.split(" - ")]
            role = role or parts[0]
            if len(parts) > 1:
                company = company or parts[-1]
        elif " @ " in page_title:
            r_p, c_p = page_title.split(" @ ", 1)
            role = role or r_p.strip()
            company = company or c_p.strip()

    if not company:
        parsed = urllib.parse.urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        if ats in {"ashby", "greenhouse", "lever"} and path_parts:
            company = path_parts[0].replace("-", " ").title()
        else:
            host = parsed.netloc.replace("www.", "").split(".")[0]
            company = host.title()

    if not body_text:
        main_el = soup.find("main") or soup.find("article") or soup.body
        body_text = _clean_html(str(main_el))[:12000] if main_el else ""

    return {
        "company": company or "Company",
        "role": role or "Open Role",
        "location": location or ("Remote" if "remote" in body_text.lower()[:1200] else ""),
        "ats_type": ats,
        "salary_band": _extract_salary(body_text),
        "posting_text": f"# {role or 'Open Role'} - {company or 'Company'}\nLocation: {location}\nURL: {url}\n\n{body_text}",
    }
