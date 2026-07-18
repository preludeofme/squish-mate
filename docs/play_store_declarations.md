# Play Store Data Safety / Permission Declarations (draft)

Date: 2026-07-17
Status: Draft for future submission — see `docs/android_plan.md` §5.7/§7
Phase 5 ("Play Store declarations drafted for later"). Not submitted
anywhere; sideload/GitHub-releases + F-Droid ship first per the plan.
Nothing here has been reviewed against the live Play Console form fields
(they change over time) — use this as source content to paste in, not a
guarantee it matches the current form layout.

---

## Permissions declared in `AndroidManifest.xml` and their justification

### `SYSTEM_ALERT_WINDOW` ("Display over other apps" — special access)
**Why the app needs it:** Squish-Mate's entire premise is a floating pet
companion that overlays other apps (see `docs/android_plan.md` §5.1).
**Play Console "Permission declaration form" answer:** Core functionality
— the app's primary purpose is to display an animated overlay character
that floats above other apps; declining/revoking this permission does not
remove core functionality, since the app falls back to an in-app-only pet
(`MainActivity`'s "Use Pip in-app instead" mode).
**User-facing disclosure:** `MainActivity` explains the request inline
before the deep-link to Settings; no permission is requested without a
proximate user action (tapping "Allow floating over other apps").

### `FOREGROUND_SERVICE` / `FOREGROUND_SERVICE_SPECIAL_USE`
**Why:** `OverlayService` must keep running (and the overlay window must
stay attached) while the user has other apps in the foreground — this is
what makes it a persistent companion rather than something that dies the
moment the user switches away. `specialUse` because none of the other
Android 14 foreground-service types (location, camera, media playback,
etc.) describe "floating companion character."
**`PROPERTY_SPECIAL_USE_FGS_SUBTYPE` value:** "Floating desktop-pet
companion overlay" (already set in the manifest — this exact string is
what Play reviews).

### `POST_NOTIFICATIONS`
**Why:** Android requires an ongoing, low-priority notification for any
foreground service (`OverlayService`'s persistent "Pip is out" notice) —
this is not optional infrastructure, it is the mandatory visible indicator
Android itself requires for foreground services, not a marketing/engagement
notification.

### `INTERNET` / `ACCESS_NETWORK_STATE`
**Why:** Opt-in hosted-LLM provider calls (OpenAI/Anthropic/OpenRouter via
`core/llm_providers.py`) and opt-in LAN Ollama URL calls
(`core/pet_brain.py`). The app is fully functional offline — network
failures fall back to `SAFE_FALLBACKS` canned lines
(`core/bridge.py`/`core/pet_brain.py`) — network access only enriches
responses, it is never required to use the app.

### `PACKAGE_USAGE_STATS` (special access, opt-in — "Usage access")
**Why:** Lets the pet react to which app is in the foreground (Android's
shallower equivalent of desktop's window-title monitor — package + app
label only, no titles/content). **This is the single riskiest declaration
for Play review** and is architected to be maximally defensible:
- Off by default. The in-app "Activity-aware chatter" button is the only
  way to grant it, and it deep-links straight to the OS's own
  `ACTION_USAGE_ACCESS_SETTINGS` screen — the app never claims this
  permission is required.
- `UsageMonitor.currentForegroundPackage()` only ever reads the
  **foreground package name** over a short rolling window (§5.3) to
  produce a coarse label ("you're in a messaging app") — no usage
  history, no per-app time totals, no data retention, nothing persisted
  to disk beyond the engine's own topic/emotion state (never raw
  package/app names).
- **Play Console "Usage Access permission declaration" form**: category
  = "Provides users insight into their own app usage" is NOT accurate for
  this app (it's the opposite — ambient companion commentary); the
  correct category is closer to "Enables core app functionality" with a
  written explanation along the lines of: *"Squish-Mate is a virtual pet
  companion. With the user's explicit, separate opt-in, it uses the
  current foreground app's name (not usage history) to make occasional,
  lightweight in-character remarks about what the user appears to be
  doing (e.g. 'ooh, a messaging app!'). No usage statistics, history, or
  per-app duration data is read, stored, or transmitted."*

---

## Data Safety form (draft answers)

| Question | Answer |
|---|---|
| Does your app collect or share any of the required user data types? | No user data is collected/shared with the developer or third parties by default. |
| Is data encrypted in transit? | N/A by default (offline-capable); when a user opts into a hosted LLM provider, calls go directly device→provider over HTTPS (OpenAI/Anthropic/OpenRouter), never through a Squish-Mate server — there is no Squish-Mate backend. |
| Is data encrypted at rest? | The one sensitive value stored locally — an optional user-supplied LLM API key — is stored via Android Keystore-backed `EncryptedSharedPreferences` (`settings/PetSettingsStore.kt`), never in plaintext, never in `pet_config.json`-equivalent files. |
| Can users request data deletion? | Uninstalling the app deletes all app-private storage (engine state, memory, settings) — there is no server-side copy to separately delete. |
| Third-party data sharing | Only if the user opts into a hosted LLM provider: their own prompt context (foreground app label, a short recent-context summary — never keystrokes, never screen content) is sent directly to that provider using the user's own API key. No analytics/ads SDKs are included. |
| Location, contacts, photos, etc. | Not requested, not accessed. |

---

## Content rating / target audience notes
- No user-generated content shared publicly, no chat between users (the
  LLM conversation is entirely local pet↔user, one-directional display).
- Suitable for a general/everyone rating pending standard content-rating
  questionnaire; nothing in the app's own copy targets children
  specifically, so default to a general audience rather than "designed
  for families" unless Ryan wants to pursue that (would add COPPA-related
  constraints on the hosted-LLM opt-in that aren't in scope here).

## Before actually submitting (not done, tracked here for the next pass)
1. Real release signing config + keystore (current `release` build type
   temporarily reuses the debug keystore for local R8 testing only — see
   `app/build.gradle.kts`'s Phase 5 comment — this must never ship).
2. Privacy policy URL (required once `PACKAGE_USAGE_STATS` and/or a hosted
   LLM provider are enabled) — doesn't exist yet.
3. Store listing assets (icon variants, screenshots, feature graphic) —
   none exist yet; `ic_launcher_foreground.xml`/`ic_launcher_background.xml`
   are placeholder vector art from the Phase 1 skeleton.
4. Closed testing track first, given the `PACKAGE_USAGE_STATS` +
   `SYSTEM_ALERT_WINDOW` combination is exactly the profile Play reviewers
   scrutinize most; sideload/GitHub release + F-Droid remain the primary
   v1 distribution channel per `docs/android_plan.md` §5.7.
