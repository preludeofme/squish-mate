# Squish-Mate Android Support Plan

Date: 2026-07-17
Status: Proposal (no code changes yet)
Related: `squish-mate_split_plan.md` (earlier repo-split sketch), `docs/architecture_refactor.md`

---

## 1. Executive Summary

**Recommendation: build Android as a separate Kotlin app in a new codebase
(`squish-mate-android`), while reusing the existing pure-Python `core/`
package unmodified by embedding it with Chaquopy.** Do NOT attempt to run the
whole app on Android via Kivy/python-for-android, and do NOT fork the
behavior engine into a second language (yet).

Rationale in one paragraph: the codebase already has a clean seam. Everything
in `core/` (`pet_engine.py`, `pet_brain.py`, `pet_memory.py`,
`pet_library.py`, `pet_performance.py`, `llm_providers.py` — ~2,900 lines)
is pure Python with zero Qt imports (verified by grep), thread-safe, and
covered by headless tests. Everything platform-specific lives in `ui/`
(PySide6) and `monitors/` (xdotool/pynput/psutil) — none of which is
portable to Android anyway, because Android's window system, permission
model, and input-monitoring restrictions are fundamentally different. So the
UI and monitors must be rewritten natively regardless of approach, and the
only real decision is what to do with `core/`. Embedding it keeps a single
source of truth for the engine (metabolism, gating, privacy filtering, LLM
validation) that both platforms share.

---

## 2. Why Not the Alternatives

### 2a. Kivy / python-for-android (full Python app)
- The pet is an **overlay** (floats above other apps). On Android that means
  `TYPE_APPLICATION_OVERLAY` windows created from a foreground `Service` —
  Kivy renders into a single Activity surface and has no supported path for
  service-owned overlay windows. You'd end up writing the overlay in
  Java/Kotlin via pyjnius anyway, with worse tooling.
- Background execution, Doze, foreground-service types, and notification
  channels all need first-class Android API access. Fighting this through a
  Python framework is the hard 80% of the project.
- Verdict: rejected.

### 2b. Full Kotlin rewrite of everything (no Python)
- Cleanest runtime (no embedded interpreter, smallest APK, best battery),
  and the natural long-term end state if Android becomes the primary
  platform.
- Cost: re-porting and re-verifying ~2,900 lines of subtle behavior logic
  (metabolic decay curves, offline-elapsed simulation, meaningful-change
  similarity scoring, privacy regexes, LLM output validation/`_clean_output`
  truncation repair, anti-repeat deque). Every future engine change then has
  to be made twice and can silently diverge.
- Verdict: rejected for v1; kept as a documented **escape hatch** (§10) if
  Chaquopy's APK size (+~30–60 MB) or cold-start cost proves unacceptable.

### 2c. Flutter / React Native / Godot
- Same overlay-from-a-service problem as Kivy, plus a full rewrite of both
  rendering and engine. No reuse advantage. Rejected.

### 2d. Modify the existing repo to "also run on Android"
- Impossible in-place: PySide6 does not target Android, and `monitors/`
  (xdotool, pynput, psutil window inspection) has no Android equivalent API.
  A separate app codebase is required; the only shared artifact is `core/`.

---

## 3. Target Architecture

```
┌─────────────────────────────  Android app (Kotlin)  ─────────────────────────────┐
│                                                                                  │
│  OverlayService (foreground service, TYPE_APPLICATION_OVERLAY window)            │
│    ├── PetView (Kotlin) — Canvas/Path port of blob_renderer.py                   │
│    ├── PetAnimatorKt (Kotlin) — port of ui/pet_animator.py (already pure logic)  │
│    └── SpeechBubbleView (Kotlin)                                                 │
│                                                                                  │
│  UsageMonitor (Kotlin) — UsageStatsManager poll every 3–5 s → activity events    │
│  TouchMonitor — pet-local touch/drag/fling (replaces click_monitor)              │
│                                                                                  │
│  PetBridge (Kotlin ↔ Chaquopy)                                                   │
│    └── Python: core/ package UNMODIFIED                                          │
│         pet_engine.py  pet_brain.py  pet_memory.py                               │
│         pet_library.py pet_performance.py llm_providers.py                       │
│                                                                                  │
│  Settings (Jetpack DataStore ⇄ pet_config.json shape)                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Split rule (frequency-based)
- **High-frequency (30 FPS) stays native**: render loop, animator physics,
  touch handling. Crossing the JNI/Python bridge 30×/s for pose data is
  avoidable and battery-relevant, so `pet_animator.py` gets a Kotlin port —
  acceptable duplication because it is visual polish, not behavior truth,
  and it is already Qt-free/deterministic (easy to port + golden-test).
- **Low-frequency stays Python**: engine tick (every 2 s), activity-event
  intake, LLM calls, memory, validation. This is where all the subtle logic
  lives and where reuse pays off.

### Bridge API (thin, JSON-in/JSON-out)
One Python entry module (new, lives in this repo so it's tested here):

```
core/bridge.py
  init(storage_dir: str, config_json: str) -> None
  tick(now_ms: int) -> str            # {"speech":..., "emotion":..., "action":..., "sleeping":bool, ...}
  on_activity(event_json: str) -> str # same shape; runs gating + brain
  on_interaction(kind: str) -> str    # "tap" | "drag" | "fling" | "longpress"
  get_state() -> str                  # needs/energy snapshot for settings UI
  update_config(config_json: str) -> None
  shutdown() -> None
```

Kotlin never imports engine internals; Python never imports Android APIs.
All strings are JSON. LLM calls run on Chaquopy's own Python thread (the
engine is already thread-safe and PetBrain already runs threaded on desktop).

---

## 4. Prerequisite Changes in THIS Repo (Phase 0)

Small, desktop-safe refactors so `core/` is embeddable as-is:

1. **Injectable storage dir.** `core/pet_engine.py:36` hardcodes
   `~/.config/squish-mate/pet_state.json` (plus `BACKUP_PATH` and the legacy
   `~/.config/desktop-pet` migration at lines 289–291). Add a module-level
   `set_data_dir(path)` (or constructor param already exists — `state_path` —
   so mainly fix `BACKUP_PATH` and the migration block to derive from
   `state_path`). Audit `pet_performance.py`, `pet_memory.py`,
   `pet_library.py` for the same pattern. Desktop behavior unchanged
   (defaults stay).
2. **`core/bridge.py`** (new) — the JSON facade above, with unit tests in
   `tests/test_bridge.py`. This is also useful for the future web port.
3. **Guard desktop-only imports.** `pet_performance.py` imports
   `subprocess`/`platform` probing — verify its hardware-tier detection
   degrades gracefully on Android (wrap in try/except, add an explicit
   `"mobile"` tier that skips Ollama probing).
4. **Packaging.** Add `pyproject.toml` declaring `squish_mate_core`
   (package = current `core/`), deps: `requests` only. (`package.json` is
   already flagged in handoff as cosmetic debt — this supersedes it for the
   core.) Chaquopy installs it straight from a git URL or local path.
5. Keep repos: **do not split repos yet.** The earlier
   `squish-mate_split_plan.md` proposed 3–4 repos; that's premature. This
   repo stays the desktop app + canonical core; `squish-mate-android` is the
   only new repo. Split core out later only if a third platform materializes.

---

## 5. Android App Design

### 5.1 Product shape
- **Primary mode: floating overlay pet** — closest to the desktop
  experience. Requires `SYSTEM_ALERT_WINDOW` ("Display over other apps",
  user-granted via Settings deep-link) and a **foreground service**
  (`foregroundServiceType="specialUse"`, persistent low-priority
  notification — mandatory, no way around it on modern Android).
- **Fallback mode: in-app pet** — if overlay permission is denied, the pet
  lives in a normal Activity (still fully functional minus floating).
- **Optional later: live-wallpaper mode** (`WallpaperService`) — pet on the
  home screen with zero overlay permission. Good Play-Store-friendly mode;
  v2.

### 5.2 Rendering
- Port `ui/blob_renderer.py` (464 lines) QPainter → `android.graphics.Canvas`
  + `Path`. The mapping is nearly 1:1: `QPainterPath.cubicTo` → `Path.cubicTo`,
  radial/linear `QGradient` → `RadialGradient`/`LinearGradient` shaders.
  Squash/stretch anchoring and the pose-delta tables from
  `ui/pet_expressions.py` (`EMOTION_POSE`) port as plain data.
- Port `ui/pet_animator.py` (647 lines, already pure Python, no Qt) →
  Kotlin. Add a **golden test**: run both animators over a scripted seed and
  compare pose keyframes to catch porting drift.
- Render on a `Choreographer`-driven loop in the overlay view; drop to
  ~10 FPS when idle, 0 FPS when screen off (register `SCREEN_ON/OFF`
  receiver) — battery is the #1 mobile constraint.

### 5.3 Activity monitoring (the desktop `monitors/` equivalent)
Android reality check — what desktop features survive:

| Desktop feature | Android equivalent | Verdict |
|---|---|---|
| Active window title (`advanced_monitor.py`) | `UsageStatsManager` → foreground **package + app label only**, no titles. Needs `PACKAGE_USAGE_STATS` special access (user grants in Settings). | Reduced: "app category" context ("you're in YouTube") instead of "watching X video" |
| Keystroke monitor | Only via AccessibilityService/custom IME; Play policy hostile; creepy on mobile | **Dropped** on Android |
| Click monitor | Touches on the pet itself (tap/drag/fling/long-press) | Replaced, richer |
| Screen reader / vision (`screen_reader.py`) | `MediaProjection` — per-session consent dialog + capture notification | **Deferred to v2**, opt-in |
| psutil system stats | `BatteryManager`, `ActivityManager` | New context sources: battery level, charging, time-of-day |

The engine doesn't care: it consumes `PetEvent(event_type, source, summary,
topic, ...)` — the Kotlin `UsageMonitor` just emits shallower summaries. The
existing privacy filter and meaningful-change detector still apply. Add
Android-only event sources that desktop lacks: battery low ("I'm getting
sleepy… oh wait, that's YOUR battery"), charger plugged, headphones,
notifications count (via `NotificationListenerService`, opt-in, v2).

### 5.4 LLM strategy
- **No localhost Ollama on-device.** Three paths, all through existing code:
  1. **Hosted providers (v1 default)** — `core/llm_providers.py` already
     implements OpenAI/Anthropic/OpenRouter with bring-your-own-key and
     `requests`; works under Chaquopy unchanged. This module is the single
     biggest reuse win for Android.
  2. **Ollama over LAN** — `PetBrain` already takes `ollama_url`; expose a
     "server URL" setting so Ryan's desktop Ollama serves the phone at home.
  3. **On-device (v2)** — MediaPipe LLM Inference API running Gemma 3 1B on
     device; add a fourth provider (`"mediapipe"`) whose call is delegated
     back to Kotlin through the bridge (Python asks Kotlin to run inference).
- API keys: stored in Android Keystore-encrypted prefs, injected into config
  JSON at bridge init; never written to `pet_config.json` on-disk in plain
  text on device.
- `SAFE_FALLBACKS`/canned lines already cover offline — pet stays alive with
  no network.

### 5.5 Persistence & config
- `storage_dir` = `context.filesDir` → engine state JSON, performance state,
  library all land in app-private storage (atomic-rename writes in
  `pet_engine._save()` work fine there).
- Settings UI in Kotlin (Compose), persisted via DataStore, mirrored into
  the `pet_config.json` dict shape at `update_config()` so the Python side
  needs zero changes. Same keys: name, color, species, traits, frequencies,
  provider, model override, system_prompt.
- Offline-elapsed sleep simulation (already in engine) is a perfect mobile
  fit: app killed overnight → pet "slept", recovered energy.

### 5.6 Lifecycle & battery
- Foreground service starts on user action (not boot, v1). Handle
  `onTaskRemoved`, Doze (no wakelocks — the pet simply pauses; engine's
  offline simulation covers gaps), and OEM task killers (document
  dontkillmyapp.com guidance in-app).
- Engine tick via `Handler` every 2 s **only while screen on**; monitors
  poll UsageStats every 5 s screen-on only.
- Target: < 2%/day battery attributable when idle. Measure with Battery
  Historian in Phase 5.

### 5.7 Permissions & Play Store
- Required: `SYSTEM_ALERT_WINDOW` (special), `FOREGROUND_SERVICE` +
  `FOREGROUND_SERVICE_SPECIAL_USE`, `POST_NOTIFICATIONS`, `INTERNET`.
- Optional/gated: `PACKAGE_USAGE_STATS` (special access), notification
  listener (v2), MediaProjection (v2).
- Play policy risk is real for overlay + usage access: prepare permission
  declarations, make usage-access strictly opt-in with in-app explanation,
  and ship **sideload/GitHub-releases + F-Droid first**, Play Store after
  the app is stable and the declarations are drafted.
- Min SDK 26 (TYPE_APPLICATION_OVERLAY floor); target latest.

---

## 6. New Repo Layout (`squish-mate-android`)

```
squish-mate-android/
├── app/src/main/
│   ├── java/com/preludeofme/squishmate/
│   │   ├── overlay/        # OverlayService, PetView, SpeechBubbleView
│   │   ├── anim/           # PetAnimatorKt (port), poses, expressions data
│   │   ├── render/         # BlobRenderer port (Canvas)
│   │   ├── bridge/         # PetBridge (Chaquopy calls, JSON models)
│   │   ├── monitor/        # UsageMonitor, BatteryMonitor
│   │   ├── settings/       # Compose settings UI, DataStore, Keystore keys
│   │   └── MainActivity.kt # onboarding, permission flows, in-app fallback pet
│   └── python/             # (empty — core installed via pip from this repo)
├── app/build.gradle.kts    # Chaquopy plugin; pip: squish-mate-core @ git+…
└── docs/
```

Kotlin, Jetpack Compose for settings/onboarding, classic `View` for the
overlay pet (Compose-in-overlay-service is possible but adds lifecycle-owner
plumbing; plain custom View is simpler and faster for a Canvas toy).

---

## 7. Phased Implementation

### Phase 0 — Core embeddability (this repo) — ~2–3 days
- Storage-dir injection, `core/bridge.py` + tests, mobile perf-tier guard,
  `pyproject.toml`. Verify: `python -m pytest tests/` still green; new
  bridge tests simulate a full day of ticks + activity events headlessly.

### Phase 1 — Android skeleton — ~1 week
- New repo, Gradle + Chaquopy, `bridge.init()` smoke test on device.
- Overlay foreground service + draggable placeholder circle + permission
  onboarding (overlay grant flow, notification).
- Exit criteria: circle floats over other apps, survives app-switch,
  drag works, service restarts cleanly.

### Phase 2 — Rendering & animation port — ~1–2 weeks
- BlobRenderer Canvas port (silhouette, gradient, eyes, antenna, shadow).
- PetAnimatorKt port + golden-comparison test against Python animator.
- Speech bubble view; touch → hop/wave/startle parity with desktop.

### Phase 3 — Brain wiring — ~1 week
- Engine tick loop through bridge; emotions/actions from engine drive
  animator (same contract as `desktop_pet.py`'s 2 s tick).
- Hosted-LLM settings (provider, key in Keystore, model override); LAN
  Ollama URL option. Verify idle chatter + fallbacks offline.

### Phase 4 — Android context sources — ~1 week
- UsageStats monitor (opt-in) → `on_activity` events; battery/charging
  events; suppress speech while user is typing? (not detectable — instead
  suppress while pet was recently dragged / screen just unlocked).

### Phase 5 — Hardening & release — ~1 week
- Battery Historian pass, screen-off gating verified, OEM-killer testing
  (Samsung/Xiaomi), crash-safe state (engine already has backup/recovery
  path — verify on device), APK size check (r8 + Python stdlib trimming).
- GitHub release APK + README; Play declarations drafted for later.

Total: roughly 5–7 weeks of focused part-time work; Phases 2 and 3 can
overlap once the bridge exists.

---

## 8. Testing Strategy

- **Core stays tested here** — desktop test suite is the behavior contract;
  bridge tests added in Phase 0 run in CI on plain Linux (no Android).
- **Animator golden tests** — scripted seed → pose keyframe JSON produced by
  Python animator (checked into android repo as fixture) compared against
  Kotlin port output.
- **Instrumented tests** — overlay service lifecycle, permission flows,
  bridge round-trip on emulator (API 26 + latest).
- **Manual matrix** — one Samsung, one Pixel, one aggressive-killer OEM.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Chaquopy APK bloat / cold start | Measure in Phase 1 with real core; abort criterion below |
| Play rejects overlay/usage-access | Sideload + F-Droid first; wallpaper mode as compliant alternative |
| Reduced context (no window titles) makes pet feel dumb | Lean on richer mobile-native events (battery, charging, time, app-category humor); tune prompts for app-level context |
| OEM background killers | Foreground service + user guidance; engine's offline simulation makes kills non-destructive |
| Behavior drift between animator ports | Golden tests (§8) |

## 10. Escape hatch (documented up front)
If after Phase 1 the Chaquopy runtime measures > ~80 MB installed or > 3 s
bridge cold-start on a mid-range device: switch Phase 3 to a Kotlin port of
`pet_engine.py` + `pet_brain.py` validation only (keep prompts/config
identical, port test suite first), and keep `llm_providers.py` logic as
plain Retrofit/OkHttp calls. Everything in Phases 1, 2, 4, 5 is unchanged
either way — that's why rendering/animation are native from the start.
