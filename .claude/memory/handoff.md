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

## Android Phase 4 completed: battery/charging/headphone events + drag/unlock speech suppression (2026-07-17, same day)
Closed the two remaining Phase 4 gaps identified by a docs/android_plan.md-vs-code
review: new `monitor/DeviceEventMonitor.kt` (no permission needed — battery/
power/headset are public system broadcasts) reports on real state
TRANSITIONS only (crossing into ≤20% battery, charger connect/disconnect,
headphones plug/unplug), feeding `OverlayService`'s new shared
`reactToActivity()` helper (factored out of `maybeCheckForegroundApp`, also
now used by the device monitor) into the same `PetBridge.onActivity` path
real app-switch context already uses. Each event kind gets a distinct
`process_name`/source string (`device.battery_low`,
`device.charger_connected`, etc.) so the engine's meaningful-change
detector — which keys off event source — treats them as distinct topics.
Also added `isRecentlyDistracted()`: a 5s-after-drag / 3s-after-screen-on
suppression window gating `maybeCheckForegroundApp`,
`maybeTriggerIdleComment`, and the device-event callback — the mobile
analogue of desktop's typing-suppression (no "is typing" signal exists on
Android, so drag/unlock stand in per the plan's own §7 Phase 4 note).
Direct-touch reactions (`onInteraction`) are NOT gated by this — only
ambient/reactive speech. Not wired into `MainActivity`'s in-app fallback
(device events + suppression are `OverlayService`-only, matching how
`UsageMonitor` polling was already overlay-only). `./gradlew assembleDebug
testDebugUnitTest` green; Python suite unaffected (no Python touched),
39/39 via `.venv/bin/python -m unittest discover -s tests -q` (plain
`pytest` fails in this env — missing `pygments` dep, pre-existing, unrelated).
Still not committed anywhere; no emulator verification of the new device
events specifically (screen-off/on and drag were already emulator-verified
earlier for their own features).

Remaining after this: Phase 5 only — Battery Historian pass, screen-off/
Doze gating verification under real conditions, OEM background-killer
testing (Samsung/Xiaomi), crash-safe state verification on device, APK
size check against the docs/android_plan.md §10 escape-hatch thresholds,
GitHub release packaging + README, Play Store permission declarations
draft. (v2-deferred items — live wallpaper mode, on-device MediaPipe LLM,
MediaProjection screen reading, NotificationListenerService — intentionally
untouched, matching the plan.)

## Android Phase 5 begun: emulator hardening pass + R8 + Play declarations draft (2026-07-17, same day)
Used the still-running `pixel_6` emulator (API 34, already had the app
installed from an earlier session) to work through the measurable parts of
`docs/android_plan.md` §7 Phase 5:
- **Cold start measured**: `OverlayService` start → first successful
  engine tick (`PipEngine ... State successfully loaded and validated`)
  ≈1.7s via logcat timestamps — comfortably under the §10 escape-hatch's
  3s threshold.
- **Screen-off/on gating verified live**: tick loop (`Selected action`
  log lines) stopped immediately on `input keyevent 26` (screen off) and
  resumed cleanly on screen-on, no ticks fired during the off window.
- **Crash-safe state verified live**: `am force-stop` mid-session, then
  relaunch — state reloaded via the engine's existing offline-elapsed
  simulation ("Pip was offline while awake...") with no crash, energy
  continuity correct.
- **Battery/charging/headphone events (Phase 4 close-out, found via this
  same testing pass) — real bug found and fixed**: `DeviceEventMonitor.kt`
  originally updated `lastCharging` from BOTH the sticky
  `ACTION_BATTERY_CHANGED` broadcast AND the explicit
  `ACTION_POWER_CONNECTED`/`DISCONNECTED` broadcasts. `dumpsys battery
  unplug` on the emulator proved BATTERY_CHANGED can race ahead of
  POWER_DISCONNECTED and silently flip `lastCharging` to `false` first,
  so by the time the DISCONNECTED case ran its own `lastCharging != false`
  guard, the event was already considered "reported" and got swallowed —
  charger-connect fired correctly but disconnect silently never did.
  Fixed: BATTERY_CHANGED's handler now only tracks the (unrelated)
  low-battery threshold and never touches `lastCharging` — only the two
  explicit POWER_CONNECTED/DISCONNECTED broadcasts are the source of truth
  for that field. Re-verified live: connect/disconnect/battery-low (via
  `dumpsys battery set ac 1` / `unplug` / `set level 15`) all now fire
  `OverlayService.reactToActivity` exactly once each, in order. Added a
  `Log.d(TAG, "reactToActivity: ...")` trace line (previously only
  `Log.e` on failure existed) — kept permanently, useful for future
  on-device debugging, not spammy (only fires on real activity/device
  events, which are already rate-limited). Headphone plug/unplug
  (`ACTION_HEADSET_PLUG`) is code-reviewed only, NOT live-verified — it's
  a protected broadcast the emulator's shell can't simulate
  (`SecurityException` from `am broadcast`); would need real headphones on
  a real device or a proper instrumented test with system-level access.
- **APK size / R8 (`docs/android_plan.md` §7 "APK size check")**:
  `app/build.gradle.kts`'s `release` build type now has `isMinifyEnabled
  = true` + `isShrinkResources = true`. One real R8 failure surfaced
  (`androidx.security:security-crypto`'s Tink dependency references two
  optional `javax.annotation.*` annotations not on the runtime classpath)
  — fixed with the exact `-dontwarn` rules R8 itself generated into
  `missing_rules.txt`, added to `proguard-rules.pro` with a comment
  explaining why (not a real risk — those annotations are compile-only in
  the first place). No `-keep` rules were needed for app code: the
  Kotlin↔Python boundary is one-directional (Kotlin calls into
  `core.bridge` via Chaquopy; nothing in Python ever reflects back into
  Kotlin classes), and JSON is hand-parsed via `org.json` (no
  reflection-based serializer), so R8 has nothing unsafe to rename/strip
  here. **Verified on-device, not just "it compiles"**: installed the
  release APK on the emulator (temporarily via `signingConfig =
  signingConfigs.getByName("debug")` — see the loud comment in
  `build.gradle.kts`, this MUST be replaced with a real release keystore
  before any actual distribution), confirmed the overlay renders/ticks
  with no `ClassNotFoundException`/`NoSuchMethodError`, and specifically
  opened the Settings screen (the one screen touching the exact
  Tink/EncryptedSharedPreferences code path the R8 warning was about) —
  loaded correctly with no crash. **Sizes**: debug APK 29MB, release (R8 +
  shrunk resources) 23MB — both far under the §10 80MB threshold; the
  Chaquopy Python payload (interpreter + stdlib + `core/`) dominates
  either way and isn't something R8 can shrink (that's tracked separately,
  not attempted this pass — plan §4 item 4 already scopes `core/pyproject.toml`
  minimally).
- **Play Store declarations drafted**: new `docs/play_store_declarations.md`
  — permission-by-permission justification (heaviest focus on
  `SYSTEM_ALERT_WINDOW` and the opt-in `PACKAGE_USAGE_STATS`, the two
  Play reviewers scrutinize most), a Data Safety form draft, content
  rating notes, and an explicit "before actually submitting" checklist
  (real signing config, privacy policy URL, store assets, closed-testing
  track first) so this doesn't get mistaken for ready-to-submit.
- `android/README.md` status line updated to reflect all of the above.
- Emulator left in a clean debug-build state afterward (release APK was
  uninstalled, debug reinstalled, permissions re-granted via `appops`/`pm
  grant`, `dumpsys battery reset`) so Ryan's next session starts from the
  normal dev configuration, not the temporary release-testing one.
- `./gradlew assembleDebug assembleRelease testDebugUnitTest` all green.
  Nothing committed anywhere.

**Still open (rest of Phase 5, needs real hardware/longer sessions Ryan
would need to be involved in or explicitly schedule):**
- Real (non-emulator) device testing, especially at least one Samsung and
  one Xiaomi/aggressive-background-killer OEM per the plan's manual
  testing matrix (§8).
- A genuine multi-hour/overnight Battery Historian pass (`< 2%/day idle`
  target, §5.6) — what was done this session is real but short (~minutes,
  live logcat observation), not the sustained real-world battery
  measurement the plan calls for.
- Live headphone-plug verification on real hardware.
- Real release signing config + GitHub release packaging (the release
  build type currently uses the debug keystore, explicitly marked
  temporary/must-not-ship in both `build.gradle.kts` and the README).

## How to verify visually (needs graphical session)
```bash
cd ~/Projects/Personal/desktop-pet
.venv/bin/python test_pet.py   # scripted: bubble, wave, hop, wandering
```
Offscreen CI-style check: `QT_QPA_PLATFORM=offscreen` + render Poses through
`BlobRenderer` into a QImage (see git history / smoke tests in /tmp).
