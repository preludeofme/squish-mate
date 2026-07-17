# Handoff — desktop-pet

## What just happened
Replaced the tkinter/static-sprite UI with a PySide6 procedural vector pet
(see active-context.md for the module map). `desktop_pet.py` was rewritten for
the Qt event loop; dead canned-response code (`responses` dict /
`get_appropriate_response`) was dropped — the LLM brain + SAFE_IDLE fallbacks
cover it.

## Threading contract (important)
- Monitor + LLM run in a daemon thread; they reach the GUI ONLY via
  `window.bubble_requested.emit(text)` (queued Qt signal).
- Idle chatter (`_random_bubble`) runs on the GUI thread and must never call
  the LLM (cold model load would freeze the pet).
- `DesktopPet.stop()` / `window.stop()` must be called from the main thread
  (Qt timers can't be stopped cross-thread). Ctrl+C uses SIG_DFL.

## Review findings on the pre-existing code (not all fixed)
- `advanced_monitor.py` Linux path shells out to `xdotool` every 3 s; fails
  silently on Wayland (xdotool X11-only). Consider `kdotool`/DBus for Wayland.
- `pet_config.json` options (size, speed, enable_tts, move intervals) are
  mostly not wired to behavior — config is loaded but barely used.
- `package.json` is cosmetic (this is a Python project); deps listed there
  aren't real. Consider `pyproject.toml`/`requirements.txt` instead.
- `final_demo.py`, `simple_pet.py`, `monitor.py`, `text_simulation.py`,
  `verify_fixes.py`, `ui_component.py.backup` are stale experiments/dupes —
  candidates for deletion when Ryan confirms.
- `pet_brain.available()` does a network round-trip per activity change;
  could cache for ~30 s.

## Idle chatter is now LLM-driven (2026-07-17)
See active-context.md — idle bubbles used to be 100% canned (`SAFE_IDLE`),
which is why the pet felt scripted despite having an LLM brain. Now
`_trigger_idle_comment()` runs `PetBrain.idle_comment()` on a background
thread. Not currently running (no live process to restart) — just start it
fresh with `.venv/bin/python desktop_pet.py`.

## How to verify visually (needs graphical session)
```bash
cd ~/Projects/Personal/desktop-pet
.venv/bin/python test_pet.py   # scripted: bubble, wave, hop, wandering
```
Offscreen CI-style check: `QT_QPA_PLATFORM=offscreen` + render Poses through
`BlobRenderer` into a QImage (see git history / smoke tests in /tmp).
