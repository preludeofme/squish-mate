# Squish-Mate

A lightweight, cross-platform desktop pet (Squish-Mate) that monitors your activities and interacts with speech bubbles.

## Features

- **Activity Monitoring**: Tracks what apps you're using (browser, editor, chat, etc.)
- **Interactive Responses**: Speaks relevant messages based on what you're doing
- **Non-Intrusive**: Stays on top of all applications, minimal resources
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Speech Bubbles**: Small text bubbles that appear near the pet
- **Movability**: Pet can be moved around the screen

## Requirements

- Python 3.8+
- PySide6 (procedural vector rendering — no image assets)
- psutil (for system monitoring)
- requests + a local Ollama server (optional, for LLM comments)
- pynput (for mouse/keyboard activity tracking)
- Pillow (for screenshots/image utilities)
- Operating system-specific libraries:
  - Windows: pywin32
  - Linux: xdotool, wmctrl (for active window detection)

## Installation

1. Clone this repository:
```bash
git clone https://github.com/preludeofme/squish-mate.git
cd squish-mate
```

2. Install dependencies:
```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install PySide6 psutil requests pynput Pillow
```

3. Run Squish-Mate:
```bash
./run_pet.sh
# or: .venv/bin/python desktop_pet.py
# or: python3 run_pet.py  (auto-uses .venv if present)
```

## Usage

- The pet will appear in the bottom right corner
- It will monitor your active applications
- Speaks messages appropriate to what you're doing
- Click on the pet to get an interaction
- Drag the pet to a different location
- The pet stays on top of all windows

## File Structure

- `desktop_pet.py` - Main application and coordination logic
- `core/` - Core simulation and behavior components:
  - `pet_engine.py` - Authoritative engine (needs, metabolism, state machine, gating)
  - `pet_brain.py` - Ollama LLM persona connection & safety/anatomy filters
  - `pet_memory.py` - Memory compatibility wrapper routing to engine state
- `ui/` - Interface and rendering layer:
  - `pet_window.py` - Transparent window, frame loop, bubble management
  - `blob_renderer.py` - Procedural QPainter rendering of the alien blob
  - `pet_animator.py` - Animation state machine (hop, wave, yawn, somersault, etc.)
  - `pet_expressions.py` - Facial expressions and classified emotion triggers
  - `pet_settings.py` - Settings dialog and frequency presets
  - `pet_transcript.py` - Speeches log and UI panel
  - `pet_debug.py` - Non-modal debug panel to force actions/emotions
  - `pet_responses.py` - Canned responses/chatter fallback lines
- `monitors/` - Activity monitoring systems:
  - `advanced_monitor.py` - Tracks active app titles (Linux/macOS/Windows)
  - `screen_reader.py` - Downscaled screen capture for LLM vision input
  - `click_monitor.py` - Mouse activity tracker
  - `keystroke_monitor.py` - Opt-in in-memory keystroke activity tracker
- `tests/` - Headless and integration test suite:
  - `test_pet_engine.py` - Engine and state validation unit tests
  - `test_integration.py` - Core integration and LLM response mocking tests
  - `test_pet.py` - Graphical proof-of-life sequence script

## Configuration

The pet will create a `pet_config.json` file with settings:
- Name of the pet
- Size and speed settings
- Whether to use text-to-speech
- Message delays and limits

## Customization

You can modify the fallback responses by editing `ui/pet_responses.py`, or configure the LLM prompt/traits via the Settings menu or `pet_config.json`.

## Development

The project is designed to be:
- Lightweight and resource efficient
- Modular with separate components
- Easy to extend with new app types
- Cross-platform compatible

## Support

If you enjoy using Squish-Mate, please consider supporting its development!

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Donate-orange?style=flat-square&logo=buy-me-a-coffee)](https://buymeacoffee.com/preludeofme)

## License

MIT License - see LICENSE for details.