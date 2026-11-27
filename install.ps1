# Employmaxing 1-Click Installer for Windows PowerShell (GNU GPL v3.0)
$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "==> Installing Employmaxing dependencies..." -ForegroundColor Green
python -m pip install --user -q -r "$RepoDir\requirements.txt"
python "$RepoDir\employmaxing\build_xpi.py"

$SkillDir = Join-Path $HOME ".agents\skills"
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
Write-Host "==> Launch Employmaxing anytime via:" -ForegroundColor Cyan
Write-Host "    python `"$RepoDir\bin\employmaxing`" serve" -ForegroundColor Yellow
