#!/usr/bin/env python3
"""
export_document.py - Export tailored resumes and cover letters from Markdown to ATS-optimized PDF and DOCX.
Part of the Proficiently skill suite.
"""

import sys
import os
import re
import shutil
import tempfile
import argparse
import subprocess
from pathlib import Path

def find_chrome_binary():
    """Locate Chrome / Chromium or chrome-headless-shell."""
    candidates = [
        "/home/slave/.cache/hyperframes/chrome/chrome-headless-shell/linux-158.0.8127.36/chrome-headless-shell-linux64/chrome-headless-shell",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome-headless-shell"),
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser"
    ]
    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None

RESUME_CSS = """
@page {
    size: letter portrait;
    margin: 0.55in 0.6in 0.55in 0.6in;
}
@media print {
    body {
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
    }
}
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1a1a;
    background: #ffffff;
    font-size: 10.2pt;
    line-height: 1.38;
}
h1 {
    font-size: 20pt;
    font-weight: 700;
    color: #111827;
    text-align: center;
    letter-spacing: -0.02em;
    margin-bottom: 4px;
}
.contact-line {
    text-align: center;
    font-size: 9pt;
    color: #4b5563;
    margin-bottom: 12px;
}
.contact-line a {
    color: #1e40af;
    text-decoration: none;
}
h2 {
    font-size: 11.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #1e3a8a;
    border-bottom: 1.5px solid #1e3a8a;
    padding-bottom: 2px;
    margin-top: 10px;
    margin-bottom: 6px;
}
h3 {
    font-size: 10.5pt;
    font-weight: 600;
    color: #111827;
    margin-top: 6px;
    margin-bottom: 2px;
}
p {
    margin-bottom: 6px;
    color: #374151;
}
ul {
    margin-left: 18px;
    margin-bottom: 8px;
}
li {
    margin-bottom: 3.5px;
    color: #1f2937;
    line-height: 1.34;
}
strong {
    font-weight: 600;
    color: #111827;
}
hr {
    border: none;
    border-top: 1px solid #e5e7eb;
    margin: 10px 0;
}
"""

COVER_LETTER_CSS = """
@page {
    size: letter portrait;
    margin: 0.85in 0.9in 0.85in 0.9in;
}
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a1a1a;
    background: #ffffff;
    font-size: 11pt;
    line-height: 1.55;
}
h1 {
    font-size: 18pt;
    font-weight: 700;
    color: #111827;
    margin-bottom: 4px;
}
.contact-line {
    font-size: 9.5pt;
    color: #4b5563;
    margin-bottom: 24px;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 12px;
}
p {
    margin-bottom: 14px;
    color: #27272a;
}
strong {
    font-weight: 600;
    color: #09090b;
}
"""

def markdown_to_html(md_text: str, doc_type: str = "resume") -> str:
    """Convert markdown text to styled HTML document."""
    import markdown

    css = RESUME_CSS if doc_type == "resume" else COVER_LETTER_CSS

    # Clean and parse header contact info if present
    lines = md_text.splitlines()
    body_lines = []
    contact_html = ""
    title_html = ""

    i = 0
    while i < len(lines):
        line = lines[i]
        if i == 0 and line.startswith("# "):
            title_html = f"<h1>{line[2:].strip()}</h1>"
            i += 1
            continue
        if i == 1 and ("@" in line or "|" in line or "linkedin.com" in line or "http" in line):
            # Format contact line nicely
            parts = [p.strip() for p in re.split(r'\s*\|\s*', line)]
            formatted_parts = []
            for p in parts:
                if re.match(r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$', p):
                    formatted_parts.append(f'<a href="mailto:{p}">{p}</a>')
                elif p.startswith("http://") or p.startswith("https://"):
                    label = p.replace("https://", "").replace("http://", "").rstrip("/")
                    formatted_parts.append(f'<a href="{p}">{label}</a>')
                else:
                    formatted_parts.append(p)
            contact_html = f'<div class="contact-line">{" &nbsp;|&nbsp; ".join(formatted_parts)}</div>'
            i += 1
            # Skip subsequent separator if present
            if i < len(lines) and lines[i].strip() in ["---", "***", "___"]:
                i += 1
            continue
        body_lines.append(line)
        i += 1

    clean_md = "\n".join(body_lines)
    html_body = markdown.markdown(clean_md, extensions=['extra', 'sane_lists'])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{doc_type.capitalize()}</title>
<style>
{css}
</style>
</head>
<body>
{title_html}
{contact_html}
{html_body}
</body>
</html>
"""

def render_pdf_with_chrome(html_content: str, output_pdf: Path) -> bool:
    """Use Chrome headless to render HTML to PDF."""
    chrome_bin = find_chrome_binary()
    if not chrome_bin:
        sys.stderr.write("No Chrome or chrome-headless-shell binary found.\n")
        return False

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_content)
        temp_html = f.name

    try:
        cmd = [
            chrome_bin,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={str(output_pdf)}",
            f"file://{temp_html}"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        return output_pdf.exists() and output_pdf.stat().st_size > 500
    except Exception as e:
        sys.stderr.write(f"PDF rendering error: {e}\n")
        return False
    finally:
        try:
            os.remove(temp_html)
        except OSError:
            pass

def export_docx(md_text: str, output_docx: Path, doc_type: str = "resume"):
    """Convert markdown resume or cover letter to DOCX using python-docx."""
    import docx
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = docx.Document()

    # Set page margins (0.55 in for resume, 0.85 in for cover letter)
    margin = 0.55 if doc_type == "resume" else 0.85
    for section in doc.sections:
        section.top_margin = Inches(margin)
        section.bottom_margin = Inches(margin)
        section.left_margin = Inches(margin)
        section.right_margin = Inches(margin)

    lines = md_text.splitlines()
    for idx, line in enumerate(lines):
        line_str = line.strip()
        if not line_str:
            continue
        
        # Heading 1 (Candidate Name / Document Title)
        if line_str.startswith("# "):
            p = doc.add_paragraph()
            if doc_type == "resume":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(line_str[2:].strip())
            run.font.name = "Arial"
            run.font.size = Pt(20 if doc_type == "resume" else 18)
            run.bold = True
            run.font.color.rgb = RGBColor(17, 24, 39)
            p.paragraph_format.space_after = Pt(2)
            continue

        # Contact line
        if idx == 1 and ("@" in line_str or "|" in line_str or "linkedin" in line_str):
            p = doc.add_paragraph()
            if doc_type == "resume":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(line_str)
            run.font.name = "Arial"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(75, 85, 99)
            p.paragraph_format.space_after = Pt(10)
            continue

        # Heading 2 (Sections)
        if line_str.startswith("## "):
            p = doc.add_paragraph()
            run = p.add_run(line_str[3:].strip().upper())
            run.font.name = "Arial"
            run.font.size = Pt(11.5)
            run.bold = True
            run.font.color.rgb = RGBColor(30, 58, 138)
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(3)
            continue

        # Heading 3 (Role / Company)
        if line_str.startswith("### "):
            p = doc.add_paragraph()
            run = p.add_run(line_str[4:].strip())
            run.font.name = "Arial"
            run.font.size = Pt(10.5)
            run.bold = True
            run.font.color.rgb = RGBColor(17, 24, 39)
            p.paragraph_format.space_before = Pt(4)
            p.paragraph_format.space_after = Pt(2)
            continue

        # Horizontal rules
        if line_str in ["---", "***", "___"]:
            continue

        # Bullet items
        if line_str.startswith("- ") or line_str.startswith("* "):
            bullet_text = line_str[2:].strip()
            p = doc.add_paragraph(style='List Bullet')
            # Handle inline bolding (**text**)
            parts = re.split(r'(\*\*.*?\*\*)', bullet_text)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    r = p.add_run(part[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(part)
                r.font.name = "Arial"
                r.font.size = Pt(10)
            p.paragraph_format.space_after = Pt(2)
            continue

        # Regular paragraphs
        p = doc.add_paragraph()
        parts = re.split(r'(\*\*.*?\*\*)', line_str)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                r = p.add_run(part[2:-2])
                r.bold = True
            else:
                r = p.add_run(part)
            r.font.name = "Arial"
            r.font.size = Pt(10.5 if doc_type == "resume" else 11)
        p.paragraph_format.space_after = Pt(6)

    doc.save(str(output_docx))

def main():
    parser = argparse.ArgumentParser(description="Export markdown resume/cover letter to PDF and DOCX")
    parser.add_argument("input_md", help="Path to markdown document")
    parser.add_argument("--type", choices=["resume", "cover-letter"], default="resume", help="Document type")
    parser.add_argument("--format", choices=["all", "pdf", "docx"], default="all", help="Output format(s)")
    parser.add_argument("--output-pdf", help="Optional output PDF path")
    parser.add_argument("--output-docx", help="Optional output DOCX path")

    args = parser.parse_args()
    input_path = Path(args.input_md).expanduser().resolve()
    if not input_path.exists():
        sys.stderr.write(f"File not found: {input_path}\n")
        sys.exit(1)

    md_text = input_path.read_text(encoding="utf-8")

    out_base = input_path.with_suffix("")
    pdf_path = Path(args.output_pdf) if args.output_pdf else out_base.with_suffix(".pdf")
    docx_path = Path(args.output_docx) if args.output_docx else out_base.with_suffix(".docx")

    success = True
    if args.format in ["all", "pdf"]:
        html = markdown_to_html(md_text, doc_type=args.type)
        if render_pdf_with_chrome(html, pdf_path):
            print(f"Generated PDF: {pdf_path}")
        else:
            sys.stderr.write(f"Failed to generate PDF at {pdf_path}\n")
            success = False

    if args.format in ["all", "docx"]:
        try:
            export_docx(md_text, docx_path, doc_type=args.type)
            print(f"Generated DOCX: {docx_path}")
        except Exception as e:
            sys.stderr.write(f"Failed to generate DOCX: {e}\n")
            success = False

    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
