# Squish-Mate - Usage Guide

This guide explains how to run, configure, and customize the Squish-Mate desktop pet on your system.

## Prerequisites 

For Squish-Mate to function properly, you need:

1. **Python 3.8+**
2. **Display Server**: A live GUI environment (`DISPLAY` or `WAYLAND_DISPLAY` must be set). Running headlessly (like raw SSH) is not supported.
3. **OS-Specific CLI Tools**:
   - **Linux**: `xdotool` and `wmctrl` are used by the activity monitor to identify the active window title. Install them via your package manager:
     ```bash
     sudo apt-get install xdotool wmctrl
     ```
   - **Windows**: Requires standard Windows GUI subsystem (utilizes internal API bindings via `pywin32` / `psutil`).
   - **macOS**: Utilizes fallback subprocess window querying via AppleScript.

## Installation Steps

1. **Clone this repository**:
   ```bash
   git clone https://github.com/preludeofme/squish-mate.git
   cd squish-mate
   ```

2. **Initialize a Virtual Environment and Install Dependencies**:
   ```bash
   python3 -m venv --system-site-packages .venv
   .venv/bin/pip install PySide6 psutil requests pynput Pillow
   ```

3. **Start the Ollama Server (Optional, for LLM-based commentary)**:
   Ensure you have [Ollama](https://ollama.com) installed and running locally. By default, the pet expects to connect to a running Ollama server to get structured behavioral comments.
   ```bash
   ollama run llama3  # or whatever model you prefer (configured in pet_config.json)
   ```

## Running the Pet

Use the provided wrapper script which automatically handles environment activation and verifies graphical display availability:
```bash
./run_pet.sh
```
Or run the Python entry points directly:
```bash
.venv/bin/python desktop_pet.py
```

## Interactive Features

- **Draggable**: Click and drag the pet anywhere on your screen. The pet has custom drag animation and comment triggers.
- **Shoo/Flee**: Left-clicking the pet causes it to perform a startled hop and run to a random, non-intrusive position on the screen.
- **Right-Click Context Menu**:
  - **Settings...**: Customize the pet name, base color, personality traits, movement/message frequencies, and toggle keystroke commentary.
  - **Transcript...**: Open a scrollable, in-memory log of everything the pet has said, along with the classified emotional tone.
  - **Debug...**: Force-trigger animations (hop, wave, yawn, dance, somersault, stretch, eat, sleep) or emotions to test behaviors instantly.
  - **Quit**: Exit the application safely and persist the current pet state.

## Customization

### 1. Falling back to Canned Responses
If Ollama is not running, the pet falls back to canned responses. You can edit the fallback options in `ui/pet_responses.py`.

### 2. Personality Trait & Prompt Engineering
To customize how the LLM persona behaves:
1. Open **Settings...** via the right-click menu.
2. Edit **Personality traits** (comma-separated list, e.g., `curious, goofy, sarcastic`).
3. Add a custom **Initial prompt** to tailor the behavior guidelines.
4. Or manually edit the persistent configuration in `pet_config.json`.

## Privacy & Security

Squish-Mate is designed with a strict privacy posture:
- **In-Memory Buffer**: Click and keystroke listeners run entirely in-memory. Keystrokes are read from a temporary buffer that is completely wiped on read, and never written to disk or sent anywhere.
- **Opt-In Keystroke Monitoring**: Keystroke tracking is disabled by default. It must be explicitly checked in the **Settings** menu.
- **Sensitive Inputs**: The monitor automatically skips sending typed texts to the brain if the active window title contains security-related keywords (like `password`, `bank`, `ssh`, etc.).
- **Self-Filtering**: The monitor filters out the pet's own debug/transcript windows so it doesn't comment on itself.