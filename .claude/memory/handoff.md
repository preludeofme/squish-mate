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

## On-device LLM provider added: llama.cpp + Ryan's chosen Gemma-4-E2B GGUF (2026-07-17, same day)
Ryan asked for a fully offline on-device model. He picked
https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf (GGUF, ~3.35GB,
`gated: false` — no account/license-acceptance friction, unlike the
MediaPipe/LiteRT path floated earlier this session) — this **superseded**
the earlier MediaPipe `tasks-genai` Gradle dependency added in the prior
turn (removed; GGUF isn't a format MediaPipe's LLM Inference API can load,
llama.cpp is the correct runtime for it). Confirmed `llama.cpp` upstream
(`ggml-org/llama.cpp`, master) already has `LLM_ARCH_GEMMA4` support before
committing to this approach.

**What's actually in place now:**
- Model weights (`/home/trubuck-design/models/gemma-4-E2B_q4_0-it.gguf`,
  3,349,516,256 bytes, verified complete) and vendored `llama.cpp` source
  (`/home/trubuck-design/models/llama.cpp-src`, shallow clone) both live
  OUTSIDE the repo — same reasoning as `core/pyproject.toml`'s own
  comment about Gradle input/output overlap, plus a multi-GB binary and a
  full C++ codebase don't belong in git history either way.
- `android/app/build.gradle.kts`: `ndkVersion = "27.3.13750724"` (installed
  via `sdkmanager`), `externalNativeBuild` pointing at
  `src/main/cpp/CMakeLists.txt` (cmake 3.31.6, also installed via
  `sdkmanager`), `-DLLAMA_SRC_DIR` passed from a `llamaSrcDir` Gradle
  property (defaults to the path above, overridable with `-P`). **`ndk.abiFilters`
  narrowed from `[arm64-v8a, armeabi-v7a]` to `[arm64-v8a]` only** — a 2B+
  param model is impractical on 32-bit ARM's address space/RAM, and this
  avoids per-ABI conditional complexity in the native build; dropped
  app-wide rather than per-library. This also means: **the on-device
  provider is fundamentally untestable on this dev machine's x86_64
  emulator** — it can only be verified on Ryan's real (presumably arm64)
  phone.
- `android/app/src/main/cpp/`: `CMakeLists.txt`, `llm_bridge.cpp`,
  `logging.h` — adapted from llama.cpp's own official
  `examples/llama.android` reference app (Apache-2.0), simplified to a
  single **stateless** `nativeGenerate(system, user, maxTokens)` JNI call
  (reset KV cache + reprocess system+user prompt fresh every call) instead
  of the reference's persistent multi-turn chat-session design — matches
  how every other provider already works (`PetBrain._chat()` sends a
  complete system+user pair per call, no server-side conversation state to
  preserve). One real fix needed during this adaptation:
  `__android_log_is_loggable()` is API 30+ only and this app's minSdk is
  26 — `logging.h`'s log-gating function now always returns true instead
  (logcat itself still filters by tag/priority on the consumption end).
- `android/app/src/main/java/.../llm/OnDeviceEngine.kt`: Kotlin JNI
  wrapper. Deliberately synchronous/blocking (no coroutines/Flow, unlike
  the ARM reference) — matches this app's existing threading convention
  (every caller already runs on `OverlayService`/`MainActivity`'s
  dedicated `workerHandler`) and avoids introducing a new concurrency
  paradigm into a codebase that has never used coroutines.
- **Full compile verified for real** (this sandbox has NDK+cmake+Gradle,
  so this wasn't just "should work" — `./gradlew assembleDebug` actually
  built llama.cpp + ggml (hardware-adaptive ARM CPU kernels, KleidiAI
  SME2, ARMv8.0 through ARMv9.2 dispatch) + our JNI bridge end to end).
  Debug APK 41MB (smaller than the pre-Chaquopy-only 29MB baseline might
  suggest — dropping armeabi-v7a saved more than the new libs cost).
- **Python side** (`core/pet_brain.py`, `core/bridge.py`): new provider
  `"ondevice"`. `PetBrain._chat_ondevice()` calls a registered
  `self._ondevice_generator(system, user, num_predict)` callback instead
  of any HTTP call — same "text or None, never raises" contract as every
  other `_chat_*` path. `core/bridge.py.set_ondevice_generator(callback)`
  is the new bridge entry point Android calls once the model is loaded;
  `callback` is expected to expose a `.generate(system, user, max_tokens)`
  method — Chaquopy makes calling a Kotlin object's method from Python
  transparent, no extra glue needed. The callback is stored on the
  session (`_session.ondevice_generator`) and **re-applied automatically
  after a fresh `init()`** (e.g. app restart) since a new `PetBrain`
  instance would otherwise lose it — the host's already-loaded model is
  still valid across a bridge reset, only the callback registration is
  session-scoped by default.
- **Kotlin wiring**: `PetBridge.setOnDeviceGenerator(engine: OnDeviceEngine?)`
  — passes `OnDeviceEngine` itself as the callback (its `generate(...)`
  method's name/signature already match what Python calls; no separate
  wrapper class needed). Both `OverlayService` and `MainActivity`
  (in-app-fallback) gained `ensureOnDeviceModelState(provider)`, called
  right after every `PetBridge.init`/`updateConfig`: loads the ~3GB model
  (from `context.filesDir/models/gemma-4-E2B_q4_0-it.gguf` —
  `OnDeviceEngine.MODEL_FILENAME`/`.modelFile()`) only while `llm_provider
  == "ondevice"` is actually selected, unloads it (frees the RAM) the
  moment it isn't, including in both `onDestroy()`/teardown paths.
  Deliberately conservative with RAM — same opt-in-only posture as every
  other heavy feature in this app (Usage Access, device events).
- Settings: `strings.xml`'s `llm_provider_labels`/`llm_provider_ids`
  arrays gained "On-device (Gemma, offline)" / `"ondevice"` — zero other
  Settings-screen changes needed since `llmProvider` was already a
  free-text field round-tripping through `PetSettingsStore` unchanged.
- **Real R8 bug found and fixed while verifying the release build still
  works with all this added**: `OnDeviceEngine.generate()` (and its
  `nativeGenerate` native method) were silently dead-code-eliminated by
  R8 — confirmed via `dexdump` on the actual built APK, not assumed —
  because it's only ever called reflectively FROM Python via Chaquopy
  (`generator.generate(...)`), a call site R8's Kotlin/Java-only call-graph
  analysis can't see. This is the one real exception to
  `proguard-rules.pro`'s existing "nothing here is reflective" comment
  (now corrected) — added `-keep class .../llm/OnDeviceEngine { public *; }`
  and **re-verified via dexdump on a rebuilt release APK** that
  `nativeGenerate` (and everything else) survives intact. AGP's default
  rules already correctly protect native METHOD NAMES (`native <methods>`
  keep rule) — that part was never broken — but that alone doesn't stop
  the surrounding Kotlin method from being eliminated as unreachable.
- Python suite: 42/42 (3 new `test_bridge.py` cases:
  `test_ondevice_generator_wired_into_brain`,
  `test_ondevice_generator_survives_reinit`,
  `test_ondevice_generator_failure_falls_back_safely` — all using a fake
  Python object with a `.generate()` method to simulate what Chaquopy
  would hand across from a real Kotlin `OnDeviceEngine`).
  `./gradlew assembleDebug assembleRelease testDebugUnitTest` all green.

**What's NOT done / genuinely can't be done from this machine:**
- The model file has not been pushed to any device yet, and the whole
  on-device path has never actually run — this sandbox's only available
  emulator is x86_64, and the native build is arm64-v8a only by design
  (see above), so there is no way to runtime-test this here at all. This
  needs Ryan's real (arm64) phone connected via adb: `adb push
  /home/trubuck-design/models/gemma-4-E2B_q4_0-it.gguf /sdcard/ && adb
  shell run-as com.preludeofme.squishmate sh -c 'mkdir -p files/models &&
  cp /sdcard/gemma-4-E2B_q4_0-it.gguf files/models/'` (or equivalent),
  then select "On-device (Gemma, offline)" in Settings.
- No in-app model download/picker UI — out of scope until the manual
  adb-push path is proven to actually work end-to-end on real hardware.
- Generation speed/quality/battery cost on real hardware is completely
  unmeasured (CPU-only inference of a ~4B-equivalent quantized model on a
  phone — could be anywhere from "fine" to "too slow to feel like ambient
  chatter" depending on the device; needs real measurement, not a guess).
- Nothing committed anywhere.

## How to verify visually (needs graphical session)
```bash
cd ~/Projects/Personal/desktop-pet
.venv/bin/python test_pet.py   # scripted: bubble, wave, hop, wandering
```
Offscreen CI-style check: `QT_QPA_PLATFORM=offscreen` + render Poses through
`BlobRenderer` into a QImage (see git history / smoke tests in /tmp).
