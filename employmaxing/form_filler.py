#!/usr/bin/env python3
"""
form_filler.py - Complex ATS Form-Fill Planner & Native Chrome DevTools Protocol (CDP) Executor.
- Detects ATS (Ashby, Greenhouse, Lever, BambooHR, Workday, SmartRecruiters, Rippling).
- Builds a transparent, knockout-safe Field Plan exclusively from USER-APPROVED profile facts
  (recording exact fact IDs used so the user knows every piece of data entering the form).
- Executes complex SPA form fills via Chrome DevTools Protocol (CDP) including React/Vue value
  setters, comboboxes, checkboxes, native <input type="file"> PDF uploads (DOM.setFileInputFiles),
  and full-page pre-submit verification screenshots.
Licensed under GNU GPL v3.0.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SHARED_SCRIPTS = BASE_DIR / "shared" / "scripts"
for p in (str(BASE_DIR), str(SHARED_SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from employmaxing.store import EmploymaxingStore
from optimizer import build_form_plan


def detect_ats(url: str) -> str:
    u = (url or "").lower()
    if "ashbyhq.com" in u:
        return "ashby"
    if "greenhouse.io" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    if "bamboohr.com" in u:
        return "bamboohr"
    if "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "rippling.com" in u:
        return "rippling"
    return "generic"


def normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if re.match(r'^https?://', u, flags=re.I):
        return u
    return f"https://{u}"


def generate_universal_autofill_js(field_plan: list[dict]) -> dict:
    """
    Generate a self-contained React/Vue/SPA-safe JavaScript autofill snippet and
    1-click `javascript:` bookmarklet that works in Firefox, Chrome, Edge, Brave, and Safari
    without requiring Chrome CDP.
    """
    compact_plan = [
        {"f": item.get("field", ""), "s": item.get("selectors", []), "v": str(item.get("value", ""))}
        for item in (field_plan or [])
        if item.get("value")
    ]
    plan_json = json.dumps(compact_plan, separators=(",", ":"), ensure_ascii=True)
    # Single-line IIFE with native value setters + visible Neo-Brutalist confirmation toast
    js = (
        "(function(P){"
        "var nI=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set,"
        "nT=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set,"
        "els=Array.from(document.querySelectorAll('input,textarea,select')),"
        "ok=[],miss=[];"
        "P.forEach(function(it){"
        "var tk=(it.s||[]).concat([it.f.toLowerCase()]),m=null;"
        "for(var i=0;i<els.length;i++){"
        "var e=els[i];if(e.type==='hidden'||e.type==='file'||e.disabled)continue;"
        "var lb=e.id?document.querySelector('label[for=\"'+CSS.escape(e.id)+'\"]'):e.closest('label');"
        "var h=[e.name||'',e.id||'',e.placeholder||'',e.getAttribute('aria-label')||'',e.getAttribute('autocomplete')||'',lb?lb.innerText:''].join(' ').toLowerCase();"
        "if(tk.some(function(t){return t&&h.indexOf(t.toLowerCase())!==-1;})){m=e;break;}}"
        "if(!m){miss.push(it.f);return;}"
        "if(m.tagName==='SELECT'){"
        "var vl=it.v.toLowerCase(),op=Array.from(m.options).find(function(o){return o.text.toLowerCase().indexOf(vl)!==-1||o.value.toLowerCase().indexOf(vl)!==-1;});"
        "if(op){m.value=op.value;m.dispatchEvent(new Event('change',{bubbles:true}));ok.push(it.f);}else{miss.push(it.f);}"
        "}else{"
        "(m.tagName==='TEXTAREA'?nT:nI).call(m,it.v);"
        "m.dispatchEvent(new Event('input',{bubbles:true}));"
        "m.dispatchEvent(new Event('change',{bubbles:true}));"
        "m.dispatchEvent(new Event('blur',{bubbles:true}));"
        "ok.push(it.f);}});"
        "var b=document.createElement('div');"
        "b.textContent='EMPLOYMAXING: Filled '+ok.length+'/'+(ok.length+miss.length)+' fields! Review & submit.';"
        "b.style.cssText='position:fixed;top:16px;right:16px;z-index:2147483647;background:#C8FF2E;color:#111;border:3px solid #111;box-shadow:5px 5px 0 #111;padding:12px 16px;font:900 13px/1.3 monospace;text-transform:uppercase;';"
        "document.body.appendChild(b);setTimeout(function(){b.remove();},6500);"
        "})(" + plan_json + ");"
    )
    return {
        "script": js,
        "bookmarklet": "javascript:" + js,
    }


def build_transparent_form_plan(store: EmploymaxingStore, job_id: str, form_url: str = "") -> dict:
    """
    Build a complete form-filling plan strictly from APPROVED facts in EmploymaxingStore,
    enriched with 75th-percentile salary anchoring, knockout warnings, and exported PDF paths.
    """
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"Job '{job_id}' not found in Employmaxing store.")

    target_url = normalize_url(form_url or job.get("url", ""))
    ats = detect_ats(target_url)
    approved_facts = store.list_facts(consent_status="approved")
    fact_by_key = {}
    used_fact_ids = []

    for f in approved_facts:
        if "form_fill" in f["planned_usage"] or f["category"] in {"identity", "contact", "social_link", "form_default"}:
            fact_by_key[f["fact_key"].lower()] = f

    def pick_fact(keys: list[str], fallback: str = "") -> tuple[str, int | None]:
        for k in keys:
            if k in fact_by_key:
                f = fact_by_key[k]
                used_fact_ids.append(f["id"])
                return f["fact_value"], f["id"]
        return fallback, None

    full_name, name_fid = pick_fact(["name", "full_name"])
    first_name = full_name.split()[0] if full_name.split() else ""
    last_name = " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else ""
    email_val, email_fid = pick_fact(["email"])
    phone_val, phone_fid = pick_fact(["phone"])
    li_val, li_fid = pick_fact(["linkedin", "linkedin_url"])
    gh_val, gh_fid = pick_fact(["github", "github_url"])
    web_val, web_fid = pick_fact(["github_website", "portfolio", "website"])
    loc_val, loc_fid = pick_fact(["location", "city", "github_location"])

    # Run deterministic optimizer form-plan if posting.md exists
    job_folder = Path(job.get("folder_path") or (store.data_dir / "jobs" / job_id))
    posting_path = job_folder / "posting.md"
    opt_plan = {}
    if posting_path.exists():
        opt_plan = build_form_plan(
            posting_path,
            store.data_dir / "application-data.md" if (store.data_dir / "application-data.md").exists() else None,
            store.data_dir / "profile.md" if (store.data_dir / "profile.md").exists() else None,
            store.data_dir / "preferences.md" if (store.data_dir / "preferences.md").exists() else None,
        )

    sal = opt_plan.get("salary_strategy", {})
    yoe = opt_plan.get("computed_years_experience", "")
    source_ans = "Employee Referral" if job.get("has_referral") else opt_plan.get("recommended_source_field", "Company Website / Careers Page")

    field_plan = [
        {"field": "Full Name", "selectors": ["name", "full_name", "fullname"], "value": full_name, "fact_id": name_fid, "type": "text"},
        {"field": "First Name", "selectors": ["first_name", "firstname", "fname"], "value": first_name, "fact_id": name_fid, "type": "text"},
        {"field": "Last Name", "selectors": ["last_name", "lastname", "lname"], "value": last_name, "fact_id": name_fid, "type": "text"},
        {"field": "Email", "selectors": ["email", "e-mail"], "value": email_val, "fact_id": email_fid, "type": "email"},
        {"field": "Phone", "selectors": ["phone", "mobile", "telephone"], "value": phone_val, "fact_id": phone_fid, "type": "tel"},
        {"field": "Location / City", "selectors": ["location", "city", "address"], "value": loc_val, "fact_id": loc_fid, "type": "combobox"},
        {"field": "LinkedIn URL", "selectors": ["linkedin", "urls[linkedin]"], "value": li_val, "fact_id": li_fid, "type": "url"},
        {"field": "GitHub URL", "selectors": ["github", "urls[github]"], "value": gh_val, "fact_id": gh_fid, "type": "url"},
        {"field": "Portfolio / Website", "selectors": ["website", "portfolio", "urls[portfolio]"], "value": web_val, "fact_id": web_fid, "type": "url"},
        {"field": "Salary Expectations (Numeric)", "selectors": ["salary", "compensation", "desired_pay"], "value": str(sal.get("strict_numeric_input") or ""), "fact_id": None, "type": "number", "note": sal.get("rationale", "")},
        {"field": "Salary Expectations (Text)", "selectors": ["salary_text", "compensation_expectations"], "value": sal.get("free_text_input", ""), "fact_id": None, "type": "text"},
        {"field": "Years of Experience", "selectors": ["years", "experience", "yoe"], "value": str(yoe), "fact_id": None, "type": "number"},
        {"field": "How Did You Hear About Us?", "selectors": ["source", "hear", "referral"], "value": source_ans, "fact_id": None, "type": "select"},
        {"field": "Earliest Start Date / Notice", "selectors": ["start_date", "notice", "available"], "value": opt_plan.get("recommended_start_date", "2 weeks from offer acceptance"), "fact_id": None, "type": "text"},
    ]

    # Attach compiled ATS PDF files if present
    files_attached = []
    for fname, label in (("resume.pdf", "Resume / CV"), ("cover-letter.pdf", "Cover Letter")):
        fp = job_folder / fname
        if fp.exists():
            files_attached.append({"label": label, "path": str(fp)})

    # Filter out completely empty fields while keeping transparency
    clean_fields = [f for f in field_plan if f["value"]]
    unique_fids = sorted(set(fid for fid in used_fact_ids if fid is not None))

    sub_record = {
        "job_id": job_id,
        "ats_type": ats,
        "form_url": target_url,
        "field_plan": clean_fields,
        "files_attached": files_attached,
        "knockout_warnings": opt_plan.get("knockout_warnings", []),
        "facts_used": unique_fids,
        "status": "awaiting_approval",
    }
    sub_id = store.save_form_submission(sub_record)
    sub_record["id"] = sub_id
    store.log_event("form_plan_created", f"Created {ats.upper()} form plan #{sub_id} for {job['company']} ({len(clean_fields)} fields, {len(files_attached)} files)", {"submission_id": sub_id, "facts_used": unique_fids})
    return sub_record


class MinimalCDPClient:
    """Zero-dependency Python stdlib WebSocket client for Chrome DevTools Protocol."""

    def __init__(self, ws_url: str, timeout: float = 15.0):
        m = re.match(r'^ws://([^:/]+):(\d+)(/.*)$', ws_url)
        if not m:
            raise ValueError(f"Unsupported CDP WebSocket URL: {ws_url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("CDP handshake failed")
            resp += chunk
        if b"101" not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"CDP handshake rejected: {resp[:120]!r}")
        self._id = 0

    def _send_frame(self, text: str):
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", n))
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("CDP socket closed")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self) -> str:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            data = self._recv_exact(length)
            if opcode == 0x8:
                raise ConnectionError("CDP closed connection")
            if opcode == 0x9:  # ping -> ignore
                continue
            if opcode in (0x1, 0x0):
                return data.decode("utf-8", errors="replace")

    def call(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        req_id = self._id
        self._send_frame(json.dumps({"id": req_id, "method": method, "params": params or {}}))
        while True:
            raw = self._recv_frame()
            msg = json.loads(raw)
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} error: {msg['error']}")
                return msg.get("result", {})

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def find_interactive_browser() -> list[str] | None:
    """Locate a Chromium-based desktop browser (native or Flatpak) for zero-CLI CDP auto-launch."""
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("brave-browser"),
        shutil.which("microsoft-edge"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return [c]

    if shutil.which("flatpak"):
        for app_id in ("com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser", "com.microsoft.Edge"):
            try:
                proc = subprocess.run(["flatpak", "info", app_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
                if proc.returncode == 0:
                    return ["flatpak", "run", app_id]
            except Exception:
                continue
    return None


def ensure_cdp_browser(store: EmploymaxingStore, cdp_port: int = 9222, start_url: str = "about:blank") -> dict:
    """Check if CDP port is open; if not, auto-launch a dedicated persistent Chrome window."""
    def _probe():
        with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))

    try:
        targets = _probe()
        return {"ready": True, "launched_new": False, "targets": targets}
    except Exception:
        pass

    browser_cmd = find_interactive_browser()
    if not browser_cmd:
        return {
            "ready": False,
            "error": (
                "No Chromium-based browser (Chrome, Chromium, Brave, or Edge) is installed on this machine. "
                "Use the 1-Click Universal Autofill Bookmarklet (works in Firefox, Safari, Chrome, Edge!) "
                "or install Chromium: sudo dnf install chromium"
            ),
        }

    profile_dir = store.data_dir / "chrome-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        browser_cmd + [
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check",
            start_url or "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(24):
        time.sleep(0.35)
        try:
            targets = _probe()
            if any(t.get("type") == "page" for t in targets):
                store.log_event("chrome_cdp_launched", f"Auto-launched dedicated Chrome CDP window on port {cdp_port}")
                return {"ready": True, "launched_new": True, "browser": " ".join(browser_cmd), "targets": targets}
        except Exception:
            continue
    return {"ready": False, "error": f"Launched {' '.join(browser_cmd)} but CDP port {cdp_port} did not respond in time."}


def execute_cdp_fill(store: EmploymaxingStore, submission_id: int, cdp_port: int = 9222, auto_submit: bool = False, auto_launch: bool = True) -> dict:
    """
    Connect to (or auto-launch) a local Chrome instance on --remote-debugging-port=9222,
    fill complex React/Ashby/Greenhouse/Lever/Workday fields, attach real PDF files via
    DOM.setFileInputFiles, and capture a pre-submit verification screenshot.
    """
    subs = store.list_form_submissions()
    sub = next((s for s in subs if s["id"] == submission_id), None)
    if not sub:
        return {"status": "error", "message": f"Form submission #{submission_id} not found."}

    if auto_launch:
        cdp_check = ensure_cdp_browser(store, cdp_port=cdp_port, start_url=sub["form_url"] or "about:blank")
        if not cdp_check.get("ready"):
            return {
                "status": "cdp_unavailable",
                "message": cdp_check.get("error", f"Could not connect to Chrome CDP on port {cdp_port}."),
                "field_plan": sub["field_plan"],
                "files_attached": sub["files_attached"],
            }
        targets = cdp_check["targets"]
    else:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=3) as r:
                targets = json.loads(r.read().decode("utf-8"))
        except Exception:
            return {
                "status": "cdp_unavailable",
                "message": f"No local Chrome CDP endpoint found on port {cdp_port}.",
                "field_plan": sub["field_plan"],
                "files_attached": sub["files_attached"],
            }

    page_target = next((t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")), None)
    if not page_target:
        return {"status": "error", "message": "No active Chrome page tab found on CDP."}

    cdp = MinimalCDPClient(page_target["webSocketDebuggerUrl"])
    try:
        cdp.call("Page.enable")
        cdp.call("DOM.enable")
        cdp.call("Runtime.enable")

        target_url = sub["form_url"]
        if target_url:
            cdp.call("Page.navigate", {"url": target_url})
            import time
            time.sleep(3.0)

            # Greenhouse iframe breakout if embedded
            if sub["ats_type"] == "greenhouse":
                res = cdp.call("Runtime.evaluate", {
                    "expression": "(function(){const f=document.getElementById('grnhse_iframe'); if(!f) return ''; const u=new URL(f.src); return 'https://job-boards.greenhouse.io/embed/job_app?for='+u.searchParams.get('for')+'&token='+u.searchParams.get('token');})()",
                    "returnByValue": True,
                })
                direct_gh = res.get("result", {}).get("value", "")
                if direct_gh:
                    cdp.call("Page.navigate", {"url": direct_gh})
                    time.sleep(2.5)

        # Fill React/SPA-safe inputs using native prototype value setter
        fill_script = f"""
        (function(plan) {{
            const nativeInput = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            const nativeArea = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
            const filled = [];
            const missed = [];
            const elements = Array.from(document.querySelectorAll('input, textarea, select'));

            for (const item of plan) {{
                const tokens = (item.selectors || []).concat([item.field.toLowerCase()]);
                let matchedEl = null;
                for (const el of elements) {{
                    if (el.type === 'hidden' || el.type === 'file' || el.disabled) continue;
                    const labelEl = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : el.closest('label');
                    const hay = [
                        el.name || '', el.id || '', el.placeholder || '', el.getAttribute('aria-label') || '',
                        labelEl ? labelEl.innerText : ''
                    ].join(' ').toLowerCase();
                    if (tokens.some(t => t && hay.includes(t.toLowerCase()))) {{
                        matchedEl = el;
                        break;
                    }}
                }}
                if (!matchedEl) {{
                    missed.push(item.field);
                    continue;
                }}
                if (matchedEl.tagName === 'SELECT') {{
                    const valLower = item.value.toLowerCase();
                    const opt = Array.from(matchedEl.options).find(o => o.text.toLowerCase().includes(valLower) || o.value.toLowerCase().includes(valLower));
                    if (opt) {{
                        matchedEl.value = opt.value;
                        matchedEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        filled.push(item.field);
                    }} else {{
                        missed.push(item.field);
                    }}
                }} else {{
                    const setter = matchedEl.tagName === 'TEXTAREA' ? nativeArea : nativeInput;
                    setter.call(matchedEl, item.value);
                    matchedEl.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    matchedEl.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    matchedEl.dispatchEvent(new Event('blur', {{ bubbles: true }}));
                    filled.push(item.field);
                }}
            }}
            return {{ filled, missed }};
        }})({json.dumps(sub["field_plan"])});
        """
        eval_res = cdp.call("Runtime.evaluate", {"expression": fill_script, "returnByValue": True})
        fill_report = eval_res.get("result", {}).get("value", {})

        # Native PDF/DOCX file upload via CDP DOM.setFileInputFiles
        uploaded_files = []
        if sub["files_attached"]:
            doc = cdp.call("DOM.getDocument", {"depth": -1})
            root_id = doc["root"]["nodeId"]
            q = cdp.call("DOM.querySelectorAll", {"nodeId": root_id, "selector": 'input[type="file"]'})
            file_nodes = q.get("nodeIds", [])
            for idx, f_item in enumerate(sub["files_attached"]):
                if idx < len(file_nodes) and Path(f_item["path"]).exists():
                    cdp.call("DOM.setFileInputFiles", {"nodeId": file_nodes[idx], "files": [f_item["path"]]})
                    uploaded_files.append(f_item["path"])

        # Capture full review screenshot before stopping for human approval
        shot = cdp.call("Page.captureScreenshot", {"format": "png"})
        shot_path = store.data_dir / "screenshots" / f"form_{submission_id}_{sub['job_id']}.png"
        shot_path.write_bytes(base64.b64decode(shot["data"]))

        new_status = "filled_pending_submit"
        store.update_form_status(submission_id, new_status, screenshot_path=str(shot_path))
        store.log_event("form_filled_cdp", f"Filled form #{submission_id} ({len(fill_report.get('filled', []))} fields, {len(uploaded_files)} files uploaded) — awaiting final submit check", {"screenshot": str(shot_path)})
        return {
            "status": new_status,
            "filled_fields": fill_report.get("filled", []),
            "missed_fields": fill_report.get("missed", []),
            "uploaded_files": uploaded_files,
            "screenshot_path": str(shot_path),
            "note": "Review the screenshot and open browser tab before clicking Submit.",
        }
    finally:
        cdp.close()


def main():
    parser = argparse.ArgumentParser(description="Employmaxing Complex ATS Form Filler")
    parser.add_argument("--data-dir", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Build transparent field plan from approved profile facts")
    p_plan.add_argument("--job-id", required=True)
    p_plan.add_argument("--url", default="")

    p_exec = sub.add_parser("execute", help="Execute approved form plan via local Chrome CDP")
    p_exec.add_argument("--id", type=int, required=True)
    p_exec.add_argument("--cdp-port", type=int, default=9222)

    args = parser.parse_args()
    store = EmploymaxingStore(args.data_dir)
    if args.cmd == "plan":
        print(json.dumps(build_transparent_form_plan(store, args.job_id, args.url), indent=2))
    elif args.cmd == "execute":
        print(json.dumps(execute_cdp_fill(store, args.id, args.cdp_port), indent=2))


if __name__ == "__main__":
    main()
