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

## Android support: Phase 0 done, Phase 1 skeleton building (2026-07-17)
Branch `feature/android-support` (this repo, uncommitted) has the Phase 0
embeddability work: `core/pet_engine.py` storage-dir/backup-path fixes,
new `core/bridge.py` (+ `tests/test_bridge.py`, 15/15 passing, full suite
39/39 green), new `core/pyproject.toml` (`squish-mate-core` package —
note: lives IN `core/`, not the repo root, see below). The Android app now
lives at `android/` **inside this repo** (moved from an earlier sibling
`squish-mate-android` checkout — no nested `.git`, just a plain tracked
subdirectory) with a Phase-1 Kotlin/Chaquopy overlay-service skeleton that
**actually builds**: `cd android && ./gradlew assembleDebug` succeeds and
pip-installs `core/` live via `chaquopy { pip { install("../../core") } }`.
Pyproject.toml had to move from repo root into `core/` (with a
`package-dir` remap) specifically because nesting `android/` inside the
repo made Gradle detect an input/output directory overlap when the pip
source was the whole repo root — see active-context.md's "Android app
folded into this repo" entry for the full story. See
`docs/android_plan.md` for the phased plan and active-context.md's two
Android entries for full file-by-file detail.
Phase 2 is now also done: `android/app/.../anim/PetAnimator.kt` +
`PetExpressions.kt` + `render/BlobRenderer.kt` are real ports of
`ui/pet_animator.py`/`ui/blob_renderer.py`, wired into `PetView.kt`
(replacing the old placeholder circle) and into `OverlayService`'s tick
loop. There's a genuine cross-language golden test
(`PetAnimatorGoldenTest.kt` + `scripts/generate_animator_golden.py` +
`android/app/src/test/resources/animator_golden.json`) that passes 1/1 —
see active-context.md's "Android Phase 2" entry for the RNG-parity
workaround that made it possible. `./gradlew assembleDebug
testDebugUnitTest` both green; Python suite still 39/39.
Next: Phase 3 (Settings UI + hosted-LLM key entry wired to
`PetBridge.updateConfig` — currently `OverlayService` hardcodes `"{}"`)
or a first emulator smoke-test (renderer has never actually been looked
at on a screen). No commits made anywhere.

## Android Phase 3 continued: Settings UI now wired (2026-07-17, same day)
`OverlayService.onCreate` no longer hardcodes `"{}"` — new `settings/`
package (`PetSettingsStore.kt` + `SettingsActivity.kt` +
`activity_settings.xml`) reads/writes the pet config (name, traits,
prompt, message frequency, LLM provider/key/model-override/base-URL) via
Android Keystore `EncryptedSharedPreferences`, and a Settings save
broadcasts `ACTION_CONFIG_UPDATED` so a running overlay picks it up live
via `PetBridge.updateConfig` (no restart needed). `./gradlew assembleDebug
testDebugUnitTest` green; Python suite still 39/39. See active-context.md for the full breakdown. The LAN-Ollama gap noted
right after (Settings' "Server URL" field not affecting the Ollama
provider) was fixed in the same session: `core/pet_brain.py`'s new
`_effective_ollama_url()` (`self.base_url or self.url`) is now used by
both the Ollama `_chat()` call and `available()`; desktop is unaffected
(never sets `llm_base_url`). Also closed Phase 1's in-app-fallback gap the
same session: `MainActivity` can now embed the real `PetView` directly
(no overlay permission needed) via a "Use Pip in-app instead" toggle,
mutually exclusive with `OverlayService` through a new
`OverlayService.isRunning` flag (only one driver may own
`core/bridge.py`'s singleton session at a time). Still not committed
anywhere; no emulator/device run yet (open items: Phase 4 context
sources, first visual smoke test of anything — renderer, Settings, in-app
fallback, an actual phone-to-LAN-Ollama round trip).

## The app could talk but never did — fixed (2026-07-17, same day)
A codebase-vs-plan review found the actual biggest gap: `PetBridge.onActivity()`/
`idleComment()` were dead code and there was no speech-bubble UI at all —
the Android pet was a mute animated blob. Fixed: new `overlay/SpeechBubbleView.kt`
(reused as both a second `OverlayService` overlay window and an inline
view in `MainActivity`'s fallback), periodic `idleComment()` calls wired
into both tick loops (paced by a local probability roll,
`settings/MessageFrequency.kt`, with the engine's own 60s
`minimumSpeechCooldown` as the real backstop), and a minimal Phase 4
start — `monitor/UsageMonitor.kt` (opt-in `UsageStatsManager` polling,
special-access permission via a new Settings button) feeding real
app-switch context into `onActivity()` for the first time anywhere in the
app. `./gradlew assembleDebug testDebugUnitTest` green, zero warnings;
Python suite 39/39. See active-context.md for the full breakdown. Still
open: battery/charging events (rest of Phase 4), Phase 5, and — still —
zero emulator/device verification of anything visual across this whole
implementation.

## First emulator run — 2 real bugs found and fixed (2026-07-17, same day)
Ryan asked to set up an emulator. Launched the existing `pixel_6` AVD
(already present on this machine from other work) windowed on the real
display, installed and drove the app via adb. **Immediate crash on "Let
Pip out"**: `OverlayService.registerReceiver()` needs an explicit
exported flag on API 33+ — fixed with `ContextCompat.registerReceiver(...,
RECEIVER_NOT_EXPORTED)`. After that fix: the real Bezier-blob renderer
rendered on a screen for the first time ever (looks right), survives
app-switch, stop/restart is clean, in-app fallback works. **Second bug**:
idle chatter fired for real and produced a speech bubble clipped off the
right screen edge — fixed with a bounds clamp
(`OverlayService.clampBubbleX`). Also found: Chaquopy only captures
Python's `logging` output on-device (`python.stderr` logcat tag), not
plain `print()` — `pet_brain.py`'s debug prints are invisible on Android;
worth switching to `logging` there eventually. See active-context.md for
the full walkthrough. Emulator left running for Ryan to keep testing
directly; nothing committed.

## Integration continued: Settings verified on-device, pet_brain.py logging fixed
Ryan confirmed manual drag works fine (earlier `adb input swipe` issues
were just synthetic-input tooling, not a real bug). Then: Settings screen
opened/edited/saved for the first time on-device (EncryptedSharedPreferences
round-trips correctly, confirmed by reopening and seeing "Chatty" persist;
a real speech bubble fired right after, fully on-screen thanks to the
earlier clamp fix). Also converted `core/pet_brain.py`'s `print()` debug
trail to `logging` (matches `pet_engine.py`'s existing pattern) so it's
actually visible via `adb logcat` on Android — desktop `.venv` tests
confirm identical output shape, 39/39 still pass. Could not get a live
on-device repro of the new logger lines specifically: `PetBrain.available()`
correctly returns False with no Ollama reachable from this sandbox, so
the brain call path is never hit at all here (expected, not a bug — the
pet always uses SAFE_FALLBACKS lines in this environment). Emulator still
running; nothing committed.

## How to verify visually (needs graphical session)
```bash
cd ~/Projects/Personal/desktop-pet
.venv/bin/python test_pet.py   # scripted: bubble, wave, hop, wandering
```
Offscreen CI-style check: `QT_QPA_PLATFORM=offscreen` + render Poses through
`BlobRenderer` into a QImage (see git history / smoke tests in /tmp).
