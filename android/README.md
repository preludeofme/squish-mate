# Squish-Mate — Android

Android port of [Squish-Mate](https://github.com/preludeofme/squish-mate), a
floating desktop pet. This directory lives inside the main squish-mate repo
(`squish-mate/android/`) alongside the desktop app. See
[`../docs/android_plan.md`](../docs/android_plan.md) for the full
architecture, rationale, and phased plan this app is being built against.

**Status: Phases 0-4 done, Phase 5 (hardening/release) underway.** The real
Bézier-blob renderer/animator (Phase 2) drives the overlay, a
`SpeechBubbleView` overlay window shows what the pet says, a Settings
screen feeds name/persona/message-frequency/LLM-provider config (including
a live LAN Ollama URL override) into `PetBridge`, and denying/skipping the
overlay permission no longer strands the pet — `MainActivity` can embed
the same `PetView` in-app instead (mutually exclusive with the floating
overlay). The pet talks: periodic ambient chatter
(`PetBridge.idleComment`) runs on both the overlay and the in-app
fallback, an opt-in `UsageStatsManager`-based `UsageMonitor` feeds real
app-switch context into `PetBridge.onActivity`, and `DeviceEventMonitor`
(no permission needed) reports battery-low/charger-connect-disconnect/
headphone-plug transitions the same way, with a short post-drag/
post-screen-unlock speech-suppression window (`OverlayService.
isRecentlyDistracted`). Live-verified end to end on a Pixel 6 emulator
(API 34): cold start (service start → first successful engine tick)
measures ~1.7s, well under the `docs/android_plan.md` §10 3s escape-hatch
threshold; screen-off/on correctly pauses/resumes the tick loop; a
force-stop mid-session and relaunch reload state cleanly via the engine's
existing offline-elapsed simulation with no crash; battery/charging
transitions were confirmed firing via `dumpsys battery` (a real bug —
`ACTION_BATTERY_CHANGED` racing `ACTION_POWER_DISCONNECTED` and silently
swallowing the disconnect event — was caught and fixed this way).
`release` now builds with R8 + resource shrinking on (`isMinifyEnabled =
true`), verified crash-free on-device including the Settings screen's
Keystore-backed `EncryptedSharedPreferences` path (23MB release vs 29MB
debug APK, both far under the §10 threshold) — **the release
`signingConfig` currently reuses the debug keystore for this local testing
only and must be replaced before any real distribution.** A draft of the
Play Store data-safety/permission declarations lives at
`../docs/play_store_declarations.md`. Still open (rest of Phase 5):
real-hardware (non-emulator) testing, especially OEM background-killer
behavior (Samsung/Xiaomi) and a full multi-hour Battery Historian pass;
headphone-plug events are code-reviewed but not live-tested (the emulator
can't simulate `ACTION_HEADSET_PLUG`, a protected broadcast); a real
release signing config and GitHub release packaging.

## Architecture in one line

Rendering/animation/touch are native Kotlin (30 FPS path); the behavior
engine (needs, emotions, memory, LLM calls) is the desktop repo's pure-Python
`core/` package, embedded unmodified via [Chaquopy](https://chaquo.com/chaquopy/)
and driven through the JSON facade `core/bridge.py` (see `PetBridge.kt`).

## Local dev setup

This directory lives inside the squish-mate repo:

```
squish-mate/
├── core/          # canonical pure-Python behavior engine
├── docs/
│   └── android_plan.md
└── android/       # this directory (Gradle root)
    └── app/
```

`app/build.gradle.kts`'s Chaquopy `pip { install("../../core") }` line
installs the `core` package straight from the parent checkout's `core/`
directory (built via `core/pyproject.toml` — deliberately scoped to
`core/` only, not the repo root, so this Gradle project's own build
outputs never overlap with the installed source dir) so both apps share
one source of truth while Android support is under active development.
Before a public release this switches to a pinned tag:
`squish-mate-core @ git+https://github.com/preludeofme/squish-mate.git@vX.Y.Z`.

## Build

```bash
./gradlew assembleDebug
```

Requires an Android SDK (`ANDROID_HOME`/`local.properties`), NDK-capable
`abiFilters` for Chaquopy (`arm64-v8a`, `armeabi-v7a` — see comment in
`app/build.gradle.kts`), and network access to PyPI + Chaquopy's package
index the first time (subsequent builds use the Gradle/pip caches).

## Module map

```
app/src/main/java/com/preludeofme/squishmate/
├── overlay/   OverlayService (foreground service + TYPE_APPLICATION_OVERLAY window),
│              PetView, SpeechBubbleView (a second overlay window for pet speech)
├── bridge/    PetBridge — the only Kotlin class that talks to Python (core.bridge)
├── anim/      PetAnimator port (Phase 2)
├── render/    BlobRenderer Canvas port (Phase 2)
├── monitor/   UsageMonitor (opt-in UsageStatsManager foreground-app polling) +
│              DeviceEventMonitor (no-permission battery/charging/headphone events)
├── settings/  PetSettingsStore (EncryptedSharedPreferences), SettingsActivity,
│              MessageFrequency (idle-chatter probability, mirrors core/bridge.py)
└── MainActivity.kt   onboarding + permission flows + in-app fallback PetView
```
