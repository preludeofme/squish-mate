# Installer for Squish-Mate on Windows.
#
# Creates a project-local virtualenv at .venv and installs the Python
# dependencies (including pywin32, needed for active-window detection).
#
# Usage (from a PowerShell prompt in the repo root):
#   .\install.ps1
# If script execution is blocked, run once:
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$PyDeps = @("PySide6", "psutil", "requests", "pynput", "Pillow", "pywin32")

function Info($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg)  { Write-Host "!! $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "ERROR: $msg" -ForegroundColor Red }

# --- Locate a usable Python interpreter ---------------------------------
$PythonCmd = $null
foreach ($candidate in @("py", "python", "python3")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $PythonCmd = $candidate
        break
    }
}

if (-not $PythonCmd) {
    Err "No Python interpreter found. Install Python 3.8+ from python.org and re-run this script."
    exit 1
}

$LauncherArgs = @()
if ($PythonCmd -eq "py") { $LauncherArgs = @("-3") }

$VersionOutput = & $PythonCmd @LauncherArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
$Major, $Minor = $VersionOutput.Split(".")
if ([int]$Major -lt 3 -or ([int]$Major -eq 3 -and [int]$Minor -lt 8)) {
    Err "Python 3.8+ is required (found $VersionOutput)."
    exit 1
}
Info "Using Python $VersionOutput via '$PythonCmd'"

# --- Virtualenv + Python deps --------------------------------------------
if (-not (Test-Path ".venv")) {
    Info "Creating virtual environment at .venv"
    & $PythonCmd @LauncherArgs -m venv .venv
} else {
    Info ".venv already exists, reusing it"
}

$VenvPip = Join-Path ".venv" "Scripts\pip.exe"
$VenvPython = Join-Path ".venv" "Scripts\python.exe"

Info "Installing Python dependencies: $($PyDeps -join ', ')"
& $VenvPip install --upgrade pip | Out-Null
& $VenvPip install @PyDeps

Info "Done. Start the pet with:"
Write-Host "    .venv\Scripts\python.exe desktop_pet.py"
Write-Host ""
Write-Host "Optional: for LLM-based commentary, install and run Ollama (https://ollama.com), e.g.:"
Write-Host "    ollama run llama3"
