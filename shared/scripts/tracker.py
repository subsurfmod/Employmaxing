#!/usr/bin/env python3
"""
tracker.py - Manage application pipeline, sync from jobs directory, and render pipeline dashboard.
Part of the Proficiently skill suite.
"""

import sys
import os
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

STAGES = [
    "Saved",
    "Applied",
    "Phone Screen",
    "Technical Assessment",
    "Onsite / Final",
    "Offer",
    "Accepted",
    "Rejected",
    "Withdrawn"
]

def load_tracker(data_dir: Path) -> dict:
    tracker_file = data_dir / "tracker.json"
    if tracker_file.exists():
        try:
            return json.loads(tracker_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"applications": [], "last_synced": None}

def save_tracker(data_dir: Path, data: dict):
    tracker_file = data_dir / "tracker.json"
    data["last_synced"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tracker_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

def sync_from_jobs_dir(data_dir: Path, tracker_data: dict) -> dict:
    """Scan DATA_DIR/jobs/ and discover new folders or applied logs."""
    jobs_dir = data_dir / "jobs"
    if not jobs_dir.exists():
        return tracker_data

    apps_by_id = {app["id"]: app for app in tracker_data.get("applications", [])}

    for folder in sorted(jobs_dir.iterdir()):
        if not folder.is_dir():
            continue
        folder_id = folder.name
        posting_file = folder / "posting.md"
        applied_file = folder / "applied.md"
        resume_file = folder / "resume.md"

        role = "Unknown Role"
        company = folder_id.split("-")[0].capitalize()
        url = None
        date_created = datetime.fromtimestamp(folder.stat().st_mtime).strftime("%Y-%m-%d")

        if posting_file.exists():
            content = posting_file.read_text(encoding="utf-8", errors="replace")
            # Try to extract title & company
            m_title = re.search(r'^#\s+(.+)', content, re.MULTILINE)
            if m_title:
                title_line = m_title.group(1).strip()
                if " - " in title_line:
                    role, company = title_line.split(" - ", 1)
                elif " at " in title_line:
                    role, company = title_line.split(" at ", 1)
                else:
                    role = title_line

            m_url = re.search(r'https?://[^\s\)]+', content)
            if m_url:
                url = m_url.group(0)

        stage = "Saved"
        date_applied = None
        ats_type = "Unknown"

        if applied_file.exists():
            stage = "Applied"
            date_applied = datetime.fromtimestamp(applied_file.stat().st_mtime).strftime("%Y-%m-%d")
            content_app = applied_file.read_text(encoding="utf-8", errors="replace").lower()
            if "greenhouse" in content_app:
                ats_type = "Greenhouse"
            elif "lever" in content_app:
                ats_type = "Lever"
            elif "workday" in content_app:
                ats_type = "Workday"
            elif "ashby" in content_app:
                ats_type = "Ashby"

        if folder_id in apps_by_id:
            # Update existing application if new info
            app = apps_by_id[folder_id]
            if stage == "Applied" and app.get("stage") == "Saved":
                app["stage"] = "Applied"
                app["date_applied"] = date_applied
            if not app.get("url") and url:
                app["url"] = url
        else:
            # Create new application record
            next_followup = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d") if stage == "Applied" else None
            new_app = {
                "id": folder_id,
                "company": company.strip(),
                "role": role.strip(),
                "url": url,
                "stage": stage,
                "date_saved": date_created,
                "date_applied": date_applied,
                "last_updated": date_created,
                "ats_type": ats_type,
                "next_followup": next_followup,
                "notes": ""
            }
            apps_by_id[folder_id] = new_app

    tracker_data["applications"] = list(apps_by_id.values())
    return tracker_data

def render_pipeline_markdown(tracker_data: dict) -> str:
    apps = tracker_data.get("applications", [])
    
    total = len(apps)
    applied_count = sum(1 for a in apps if a.get("stage") != "Saved")
    active_interviews = sum(1 for a in apps if a.get("stage") in ["Phone Screen", "Technical Assessment", "Onsite / Final"])
    offers = sum(1 for a in apps if a.get("stage") in ["Offer", "Accepted"])

    md = []
    md.append("# Job Application Pipeline Dashboard\n")
    md.append(f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    
    md.append("## Funnel Overview\n")
    md.append(f"| Total Tracked | Applied | In Interview Loop | Offers |")
    md.append(f"| :---: | :---: | :---: | :---: |")
    md.append(f"| **{total}** | **{applied_count}** | **{active_interviews}** | **{offers}** |\n")

    # Group by stage
    for stage in STAGES:
        stage_apps = [a for a in apps if a.get("stage") == stage]
        if not stage_apps:
            continue
        md.append(f"### {stage} ({len(stage_apps)})\n")
        md.append("| Company | Role | Date | Next Action / Notes | Link |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for a in stage_apps:
            date_col = a.get("date_applied") or a.get("date_saved") or "-"
            notes = a.get("notes") or ""
            if a.get("next_followup"):
                notes = f"Follow-up: {a['next_followup']} | " + notes
            notes = notes.strip(" |")
            link = f"[Link]({a['url']})" if a.get("url") else "-"
            md.append(f"| **{a['company']}** | {a['role']} | {date_col} | {notes} | {link} |")
        md.append("")

    return "\n".join(md)

def main():
    if len(sys.argv) < 2:
        print("Usage: tracker.py <DATA_DIR> [command] [args...]")
        sys.exit(1)

    data_dir = Path(sys.argv[1]).expanduser().resolve()
    cmd = sys.argv[2] if len(sys.argv) > 2 else "view"

    tracker_data = load_tracker(data_dir)
    tracker_data = sync_from_jobs_dir(data_dir, tracker_data)

    if cmd == "update" and len(sys.argv) >= 5:
        target_name = sys.argv[3].lower()
        new_stage_arg = sys.argv[4].lower()
        
        # Match stage
        matched_stage = None
        for s in STAGES:
            if new_stage_arg in s.lower():
                matched_stage = s
                break
        
        if not matched_stage:
            print(f"Unknown stage: {new_stage_arg}. Choose from: {', '.join(STAGES)}")
            sys.exit(1)

        found = False
        for a in tracker_data.get("applications", []):
            if target_name in a["company"].lower() or target_name in a["id"].lower():
                a["stage"] = matched_stage
                a["last_updated"] = datetime.now().strftime("%Y-%m-%d")
                if len(sys.argv) >= 6:
                    a["notes"] = " ".join(sys.argv[5:])
                print(f"Updated {a['company']} ({a['role']}) to: {matched_stage}")
                found = True
                break
        if not found:
            print(f"No application found matching '{target_name}'")

    save_tracker(data_dir, tracker_data)
    dashboard_md = render_pipeline_markdown(tracker_data)
    (data_dir / "pipeline.md").write_text(dashboard_md, encoding="utf-8")

    print(dashboard_md)

if __name__ == "__main__":
    main()
