#!/usr/bin/env python3
"""
parse_resume.py - Extract structured text and metadata from PDF, DOCX, and TXT resumes.
Part of the Proficiently skill suite.
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path

def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from PDF using pypdf."""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        text_parts = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
        return "\n\n".join(text_parts).strip()
    except Exception as e:
        sys.stderr.write(f"Error reading PDF with pypdf: {e}\n")
        return ""

def extract_text_from_docx(docx_path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        import docx
        doc = docx.Document(str(docx_path))
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text.strip())
        for table in doc.tables:
            for row in table.rows:
                row_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_text:
                    text_parts.append(" | ".join(row_text))
        return "\n".join(text_parts).strip()
    except Exception as e:
        sys.stderr.write(f"Error reading DOCX: {e}\n")
        return ""

def extract_text(file_path: Path) -> str:
    """Extract text based on file extension."""
    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in [".docx", ".doc"]:
        return extract_text_from_docx(file_path)
    else:
        # plain text or markdown
        return file_path.read_text(encoding="utf-8", errors="replace").strip()

def extract_metadata(text: str) -> dict:
    """Basic extraction of email, phone, linkedin, and likely name."""
    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
    email = email_match.group(0) if email_match else None

    phone_match = re.search(r'(\+?\d{1,3}[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}', text)
    phone = phone_match.group(0) if phone_match else None

    linkedin_match = re.search(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_-]+/?', text)
    linkedin = linkedin_match.group(0) if linkedin_match else None

    github_match = re.search(r'(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9_-]+/?', text)
    github = github_match.group(0) if github_match else None

    # First non-empty line often contains the candidate's name
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    name = lines[0] if lines else "Candidate"
    # Clean markdown headers if present
    name = re.sub(r'^[#*_\s]+', '', name).strip()

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "linkedin": linkedin,
        "github": github,
        "raw_text_length": len(text)
    }

def main():
    parser = argparse.ArgumentParser(description="Parse resume files (PDF, DOCX, TXT)")
    parser.add_argument("input_file", help="Path to resume file or directory containing resume")
    parser.add_argument("--output", "-o", help="Optional output markdown file path")
    parser.add_argument("--json", action="store_true", help="Output metadata and text as JSON")

    args = parser.parse_args()
    input_path = Path(args.input_file).expanduser().resolve()

    if input_path.is_dir():
        # Look for first candidate resume file
        candidates = list(input_path.glob("*.pdf")) + list(input_path.glob("*.docx")) + list(input_path.glob("*.md")) + list(input_path.glob("*.txt"))
        if not candidates:
            sys.stderr.write(f"No resume files found in directory: {input_path}\n")
            sys.exit(1)
        input_path = candidates[0]

    if not input_path.exists():
        sys.stderr.write(f"File not found: {input_path}\n")
        sys.exit(1)

    text = extract_text(input_path)
    if not text:
        sys.stderr.write(f"Could not extract text from {input_path}\n")
        sys.exit(1)

    meta = extract_metadata(text)

    if args.json:
        result = {
            "source_file": str(input_path),
            "metadata": meta,
            "text": text
        }
        print(json.dumps(result, indent=2))
        return

    # Default: Output markdown
    md_content = f"# {meta['name']}\n\n"
    contacts = []
    if meta['email']:
        contacts.append(meta['email'])
    if meta['phone']:
        contacts.append(meta['phone'])
    if meta['linkedin']:
        contacts.append(meta['linkedin'])
    if meta['github']:
        contacts.append(meta['github'])
    
    if contacts:
        md_content += f"{' | '.join(contacts)}\n\n---\n\n"
    
    md_content += text

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_content, encoding="utf-8")
        print(f"Resume text written to {out_path}")
    else:
        print(md_content)

if __name__ == "__main__":
    main()
