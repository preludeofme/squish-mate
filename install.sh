#!/usr/bin/env bash
# Installer for Squish-Mate on Linux and macOS.
#
# Creates a project-local virtualenv at .venv, installs the Python
# dependencies, and (on Linux) offers to install the xdotool/wmctrl CLI
# tools the activity monitor uses to read the active window title.
set -euo pipefail
cd "$(dirname "$0")"

PY_DEPS=(PySide6 psutil requests pynput Pillow)

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
error() { printf '\033[1;31mERROR:\033[0m %s\n' "$1" >&2; }

# --- Locate a usable Python interpreter -------------------------------
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "No Python interpreter found. Install Python 3.8+ and re-run this script."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info[0])')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info[1])')
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 8) )); then
    error "Python 3.8+ is required (found $PY_VERSION)."
    exit 1
fi
info "Using $($PYTHON --version) at $(command -v "$PYTHON")"

# --- OS-specific system dependencies -----------------------------------
OS="$(uname -s)"
case "$OS" in
    Linux)
        if ! command -v xdotool >/dev/null 2>&1 || ! command -v wmctrl >/dev/null 2>&1; then
            warn "xdotool and/or wmctrl not found. These let the activity monitor read the active window title."
            PKG_CMD=""
            if command -v apt-get >/dev/null 2>&1; then
                PKG_CMD="sudo apt-get install -y xdotool wmctrl"
            elif command -v dnf >/dev/null 2>&1; then
                PKG_CMD="sudo dnf install -y xdotool wmctrl"
            elif command -v pacman >/dev/null 2>&1; then
                PKG_CMD="sudo pacman -S --noconfirm xdotool wmctrl"
            elif command -v zypper >/dev/null 2>&1; then
                PKG_CMD="sudo zypper install -y xdotool wmctrl"
            fi

            if [[ -n "$PKG_CMD" ]]; then
                read -r -p "Install them now with '$PKG_CMD'? [y/N] " reply
                if [[ "$reply" =~ ^[Yy]$ ]]; then
                    eval "$PKG_CMD"
                else
                    warn "Skipping. Window-title detection will be degraded until you install them."
                fi
            else
                warn "Could not detect your package manager. Install xdotool and wmctrl manually."
            fi
        fi
        ;;
    Darwin)
        info "macOS detected — window title lookups fall back to AppleScript, no extra system packages needed."
        ;;
    *)
        warn "Unrecognized OS '$OS' — continuing, but this script is only tested on Linux and macOS."
        ;;
esac

# --- Virtualenv + Python deps -------------------------------------------
if [[ ! -d .venv ]]; then
    info "Creating virtual environment at .venv"
    "$PYTHON" -m venv --system-site-packages .venv
else
    info ".venv already exists, reusing it"
fi

info "Installing Python dependencies: ${PY_DEPS[*]}"
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install "${PY_DEPS[@]}"

info "Done. Start the pet with:"
echo "    ./run_pet.sh"
echo ""
echo "Optional: for LLM-based commentary, install and run Ollama (https://ollama.com), e.g.:"
echo "    ollama run llama3"
