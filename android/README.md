# Squish-Mate — Android

Android port of [Squish-Mate](https://github.com/preludeofme/squish-mate), a
floating desktop pet. This directory lives inside the main squish-mate repo
(`squish-mate/android/`) alongside the desktop app. See
[`../docs/android_plan.md`](../docs/android_plan.md) for the full
architecture, rationale, and phased plan this app is being built against.

**Status: Phase 3 done, Phase 4 started.** The real Bézier-blob
renderer/animator (Phase 2) drives the overlay, a `SpeechBubbleView`
overlay window shows what the pet says, a Settings screen feeds
name/persona/message-frequency/LLM-provider config (including a live LAN
Ollama URL override) into `PetBridge`, and denying/skipping the overlay
permission no longer strands the pet — `MainActivity` can embed the same
`PetView` in-app instead (mutually exclusive with the floating overlay).
The pet now actually talks: periodic ambient chatter (`PetBridge.idleComment`)
runs on both the overlay and the in-app fallback, and an opt-in
`UsageStatsManager`-based `UsageMonitor` (Phase 4, minimal) feeds real
app-switch context into `PetBridge.onActivity`. Still open: battery-event
context sources, and a first real emulator/device smoke test (nothing in
this app has been visually verified on an actual screen yet).

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
├── monitor/   UsageMonitor — opt-in UsageStatsManager foreground-app polling (Phase 4,
│              battery/charging events still not started)
├── settings/  PetSettingsStore (EncryptedSharedPreferences), SettingsActivity,
│              MessageFrequency (idle-chatter probability, mirrors core/bridge.py)
└── MainActivity.kt   onboarding + permission flows + in-app fallback PetView
```
