#!/usr/bin/env bash
# Employmaxing 1-Click Local Installer (Linux & macOS) — GNU GPL v3.0
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "==> Installing Employmaxing from ${REPO_DIR}..."

python3 -m pip install --user -q -r "${REPO_DIR}/requirements.txt"
chmod +x "${REPO_DIR}/bin/employmaxing" "${REPO_DIR}/employmaxing/"*.py "${REPO_DIR}/shared/scripts/"*.py

# Build fresh Thunderbird Auto-Send Bridge .xpi
python3 "${REPO_DIR}/employmaxing/build_xpi.py"

# Register global CLI shortcut (~/.local/bin/employmaxing)
mkdir -p "${HOME}/.local/bin"
ln -sfn "${REPO_DIR}/bin/employmaxing" "${HOME}/.local/bin/employmaxing"

# Register Antigravity / Agent Skill (~/.agents/skills/employmaxing)
mkdir -p "${HOME}/.agents/skills"
ln -sfn "${REPO_DIR}" "${HOME}/.agents/skills/employmaxing"

# Install Linux desktop application launcher so users never need a terminal
if [[ "$(uname -s)" == "Linux" ]]; then
  APP_DIR="${HOME}/.local/share/applications"
  mkdir -p "${APP_DIR}"
  cat > "${APP_DIR}/employmaxing.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Employmaxing
Comment=Local-First AI Job Hunting & Career Command Center
Exec=${HOME}/.local/bin/employmaxing serve
Terminal=false
Categories=Office;Network;Utility;
EOF
  echo "==> Desktop app icon installed at ${APP_DIR}/employmaxing.desktop"
fi

echo ""
echo "Employmaxing installed!"
echo "Launch the Neo-Brutalist Web App anytime with:"
echo "  employmaxing serve"
echo "(Or click 'Employmaxing' in your desktop application menu!)"
