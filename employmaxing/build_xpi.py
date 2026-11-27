#!/usr/bin/env python3
"""Package thunderbird-extension/ into web/employmaxing-bridge.xpi (deterministic ZIP)."""

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "thunderbird-extension"
OUT_XPI = REPO_ROOT / "web" / "employmaxing-bridge.xpi"


def build_xpi() -> Path:
    OUT_XPI.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT_XPI, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname in ("manifest.json", "background.js", "popup.html", "popup.js"):
            fp = EXT_DIR / fname
            if fp.exists():
                zf.write(fp, arcname=fname)
    return OUT_XPI


if __name__ == "__main__":
    out = build_xpi()
    print(f"Built {out} ({out.stat().st_size:,} bytes)")
