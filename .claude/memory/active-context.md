# Active Context — desktop-pet

## Current state (2026-07-16)
Migrated rendering from tkinter + static PNG sprite to **PySide6 procedural
vector rendering** (per Ryan's spec). Pet is now an alien blob drawn entirely
with QPainter/QPainterPath every frame — no image assets used at runtime.

### New architecture
- `desktop_pet.py` — Qt app coordinator (rewritten from tkinter).
- `pet_window.py` — `DesktopPetWindow` (transparent, frameless, on-top, Tool
  flag) + `SpeechBubble` (separate translucent window). QTimer at ~30 FPS.
  `bubble_requested = Signal(str)` is the thread-safe entry for the brain.
- `pet_animator.py` — `PetAnimator` + `PetState` (IDLE/HOP/WAVE/SLEEP/
  SURPRISED/DRAGGED). Pure Python, no Qt — headless-testable. Owns position,
  velocity, wandering, blink/hop/wave scheduling, antenna spring physics.
- `blob_renderer.py` — `BlobRenderer`. One continuous Bézier silhouette with
  tentacle arms in the outline, antenna with bulb, gradient body, jelly
  highlights/bubbles, blush, mood mouth, ground shadow. Squash/stretch is
  anchored at the body bottom.
- Unchanged: `advanced_monitor.py`, `pet_memory.py`. `pet_brain.py` persona
  updated (blob now HAS tentacle arms + antenna; still no legs/tail/fur —
  `_ANATOMY_RE` relaxed accordingly).
- `ui_component.py` + `assets/` + `scripts/make_sprite.py` are now **legacy**
  (tkinter/sprite path). Kept, not deleted.

### Environment
- Python 3.12, `.venv` created with `--system-site-packages`; PySide6 6.11.1
  installed there. requests/psutil/PIL come from system packages.
- Run: `.venv/bin/python desktop_pet.py` or `python3 run_pet.py` (re-execs
  into .venv automatically).
- LLM: local Ollama at :11434, model `gemma-4-E4B-it-qat-q4_0-gguf:latest`.

### Verified
- Offscreen smoke tests: all states render, full app ran end-to-end offscreen
  (monitor detected firefox → Ollama comment → bubble → clean shutdown).
- Not yet verified on the real display/compositor (needs Ryan's session).

## Bug fix (2026-07-17) — speech bubble text getting cut off mid-sentence
Ryan saw the bubble truncate mid-clause (e.g. "Ooo, are you poking at my").
The `SpeechBubble` widget itself auto-sizes to its text (no UI clipping) —
the real cause was `pet_brain.PetBrain._chat`'s `num_predict` (Ollama output
token cap) running out before the model finished its sentence. Fixed in
`pet_brain.py`:
- Raised default `num_predict` 120→200 (`think()`/vision calls) and
  `idle_comment` 80→150, giving the ~16-word target sentence real headroom.
- `_clean_output` now detects a hard mid-clause cutoff (no terminal
  punctuation) via `_finish_incomplete()` and backs up to the last clean
  clause/word boundary + "…" instead of showing the raw truncated tail — so
  even an unlucky truncation reads as an intentional trail-off, not a glitch.
- Needs Ryan to restart `desktop_pet.py` to pick this up (Python doesn't
  hot-reload a running process).

## Idle chatter now LLM-generated + anti-repeat variety (2026-07-17)
Ryan: the pet felt "canned"/pre-written, not smart. Root cause: idle chatter
(the MOST frequent bubble, firing every ~25-70s at 30% chance) was
deliberately never calling the LLM — it always picked from a fixed 7-line
`SAFE_IDLE` list in `desktop_pet.py` (to avoid a cold-model-load freezing the
GUI thread). Fixed without reintroducing the freeze risk:
- `desktop_pet.py`: `_random_bubble()` (still a GUI-thread QTimer) now calls
  `_trigger_idle_comment()`, which spawns a short-lived daemon
  `threading.Thread` (same pattern as the monitor thread) to run
  `PetBrain.idle_comment()` off the GUI thread, then delivers the result via
  the existing `window.bubble_requested` signal (queued, thread-safe). Falls
  back to `SAFE_IDLE` only if `self.brain` is missing, already busy
  (`_brain_busy`), or `idle_comment()` returns `None` (still on cooldown from
  a real activity-change call). `idle_comment()` was previously dead code.
- `pet_brain.py`: added `self._recent_lines` (deque, maxlen 6, RAM-only, not
  persisted) + `_remember_line()`/`_recent_lines_note()`. Every accepted
  line (real or fallback) from `think()`/`idle_comment()`/
  `comment_on_typing()` is appended, and the note "things you already said
  recently, don't repeat/reuse the opening word" is injected into the next
  prompt for all three — this is what actually kills the repetitive "Ooo,
  ...” feel, more than the system-prompt wording alone.
- `SYSTEM_PROMPT` rewritten: dropped the one hardcoded example joke (model
  was reusing it near-verbatim), added explicit instructions to vary reply
  *shape* (question/observation/one-word blurt/trail-off) and never default
  to "Ooo" as an opener.
- `idle_comment()` no longer sends one generic "give a silly quip" prompt —
  it now randomly picks a topic (own body, boredom, a mini pretend-story,
  a passing mood, a nonsense sound, curiosity about the desktop) each call
  so idle lines don't converge on the same shape either.
- `SAFE_FALLBACKS` (pet_brain.py, used only when Ollama is down or output is
  rejected) expanded 5→10 lines for when the true fallback path is hit.
- Verified live against local Ollama: 3 consecutive `idle_comment()` calls
  produced 3 distinct, non-"Ooo"-opening, genuinely varied lines and the
  recent-lines note was correctly included in prompts 2 and 3. Full offscreen
  app smoke test confirmed `_trigger_idle_comment()` → background thread →
  `bubble_requested` signal → bubble text end-to-end.
- Not changed: window-close/drag reactions in `pet_responses.py` stay
  canned-instant on purpose (network round-trip would feel laggy for a
  physical/instant reaction) — Ryan didn't flag those specifically and the
  goodbye/drag lines are still large randomized pools (55 each).

## Facial expressions + tone classification (2026-07-17)
Ryan asked for the pet's face to react with emotions (happy/sad/surprised/
angry/scared) and to explore tying the LLM into "tool calls" for picking
them — with the caveat the local model is probably too small for reliable
structured output, so a regex/keyword fallback. Went with regex-only (no
tool-call attempt): a small quantized Gemma is exactly the kind of model
that flakes on an extra "also output JSON" instruction, and pet_brain.py's
existing `_clean_output` pipeline already treats raw model text as the only
trustworthy artifact — piggybacking a second structured field on top would
add a new failure mode for no real benefit when the output is one short
sentence anyway.
- New `pet_expressions.py`: `Emotion` enum (NEUTRAL/HAPPY/SAD/SURPRISED/
  ANGRY/SCARED), `EMOTION_POSE` (pose-delta table: mouth curve, blush,
  eye_scale, eye_open cap, brow angle, antenna tremble), `TONE_WORDS` (the
  requested "list of words that match tone" — per-emotion regex fragments,
  e.g. SCARED: yikes/eek/nervous/spooky/creepy/uh-oh/tremble/shaky...) and
  `classify_emotion(text)` — scores every emotion by regex hit count over
  the text, returns the highest (NEUTRAL if no match). Logged via
  `PET_EXPR_DEBUG` (on by default, same on/off convention as
  `PET_BRAIN_DEBUG`): prints the matched-emotion + score breakdown for every
  classification, and `PetAnimator.set_expression()` logs which expression
  was applied and for how long — this is the "log them" Ryan asked for, and
  doubles as the tuning feedback loop for the tone word lists.
- `pet_animator.py`: `PetAnimator.expression` is a SEPARATE concept from
  `PetState` (movement state machine) — `Emotion.SURPRISED` (facial reaction
  to something Pip *said*) is intentionally decoupled from
  `PetState.SURPRISED` (the physical startle-and-flee on click). New
  `set_expression(emotion, duration)` + `_apply_expression(pose)` (called at
  the end of `update()`) blend `EMOTION_POSE` deltas onto the pose with a
  0.3s fade-in / 0.8s fade-out so expressions never snap in/out. Skipped
  entirely while `state` is SLEEP/DRAGGED/PetState.SURPRISED (those states
  already own a strong physical reaction of their own). New `Pose.brow`
  field (-1 furrowed/angry .. +1 raised/worried, 0 = hidden).
- `blob_renderer.py`: draws two short eyebrow line segments (mirrored per
  eye) only when `abs(pose.brow) > 0.05`, so the pet's normal
  neutral/happy look is completely unchanged when no expression is active.
- `pet_window.py`: `show_bubble()` — the single choke point ALL bubble text
  already flows through (LLM `think()`/`idle_comment()`/
  `comment_on_typing()`, canned window-close/drag lines, click reaction,
  startup line) — now calls `classify_emotion(text)` then
  `animator.set_expression(...)` before displaying the bubble, so every
  existing reaction pathway gets an expression for free with no other call
  sites touched.
- Verified offscreen: `pet_expressions.py` run standalone shows correct
  classification for 7 sample lines (incl. `*wobbles happily*` after fixing
  the HAPPY pattern to also match "happily"/"happiness", not just bare
  "happy"); full `DesktopPetWindow` smoke test fired 5 different-toned
  bubbles back to back, animator logged the matching expression each time,
  and a manual `renderer.draw()` call with the resulting pose (brow≈0.55,
  mouth≈-0.72 after the "sad" line) rendered without error.
- Tuning note for future agents: `TONE_WORDS` in pet_expressions.py is a
  living list — if Ryan reports a line getting the wrong face, check the
  `[pet_expressions] classify_emotion: ... scores={...}` debug line first
  (shows exactly which patterns fired) before guessing.

## Transcript viewer + emotion tuning + action variety (2026-07-17)
Three asks in one pass:

**1. Right-click "Transcript…" menu (Settings / Transcript / Quit).**
New `pet_transcript.py`: `TranscriptLog` (RAM-only, capped deque(300),
thread-safe — same privacy posture as keystroke commentary: nothing new
touches disk) + `TranscriptDialog` (styled non-modal `QDialog`: cream/
lavender theme matching the speech bubble, `QTextEdit` rendering timestamped
rows with a colored per-emotion chip, Clear/Close buttons). `pet_window.py`
`show_bubble()` — the one choke point ALL bubble text already flows through
— now calls `self.transcript.add(text, emotion.name.lower())` right after
classifying tone, and refreshes the dialog live if it's open when a new line
comes in. `contextMenuEvent` gained `Transcript…` between Settings and Quit,
wired to `DesktopPetWindow.open_transcript()` (self-contained in the window,
no DesktopPet/signal plumbing needed — the log has no dependency on config).
The dialog instance is deliberately NOT `WA_DeleteOnClose` (kept as a live
Python reference for reuse/raise on the next click); closing just hides it.

**2. Expression variety / "once in a while" gating.**
Root cause of SURPRISED dominating: the SYSTEM_PROMPT rewrite from the
earlier "make idle chatter LLM-generated" pass explicitly suggested "Wait,
..." and "Huh, ..." as example sentence openers for variety — and
`pet_expressions.py`'s SURPRISED tone list matched bare "huh"/"wait," with
no punctuation requirement, so the model's own (intentionally varied)
phrasing kept tripping the same emotion. Fixed the word list (now requires
`huh?`/`what?` with an actual question mark, dropped bare `wait,`) — see the
comment left in `pet_expressions.py` explaining why those two are excluded,
so a future agent doesn't just add them back. Separately, Ryan wants
emotions to be occasional, not per-message: `pet_window.py` added
`EXPRESSION_SHOW_PROB` (0.45) and `EXPRESSION_MIN_GAP_S` (6.0) —
`_maybe_show_expression()` still classifies + logs every line to the
transcript, but only actually calls `animator.set_expression()` some of the
time and never more often than the cooldown. Verified: 6 identical ANGRY
lines back-to-back fired the animator expression exactly once (cooldown-
gated) while the transcript recorded all 6 as "angry" regardless.

**3. More idle actions (yawn, stretch, dance, somersault, eat).**
`pet_animator.py`: 5 new `PetState` values (`ACTION_STATES` tuple), each
with a small `_pose_*` helper following the existing `_pose_hop` pattern —
pure math over `state_time`, no new assets. Picked at random on a new
`_next_action` schedule (default every 45-110s while idle and not
wandering; tunable via `action_range`/`set_frequencies()`, same pattern as
hop/wave/wander). New `Pose` fields: `body_rotation` (degrees — full-
character spin for SOMERSAULT and a subtle wiggle for DANCE, applied via
`painter.rotate()` in `blob_renderer.draw()` right after the existing
translate/scale) and `food_visual` (0..1 shrinking snack circle drawn near
the mouth during EAT, in `_draw_face`). All 5 new states were added to
`_update_movement`'s "stay put" tuple so the pet doesn't wander mid-action.
Public `trigger_yawn/stretch/dance/somersault/eat()` exist for future call
sites (not currently wired to anything but the random scheduler — e.g. a
future "eat" reaction to a food-related bubble would just call
`animator.trigger_eat()`).
- Verified headless: forced `action_range=(0.05, 0.06)` and confirmed all 5
  states get scheduled and their pose values (`body_rotation`,
  `food_visual`) stay in valid ranges across ~4000 update() ticks.

## Bug fix (2026-07-17) — tone-word false positives from unbounded regex
Ryan shared a real transcript and asked for a quality/emotion review. Found
3 concrete `pet_expressions.py` bugs, all the same root cause (missing
`\b` word-boundary letting a short pattern match mid-word):
- ANGRY's `ugh+` (no boundary) matched inside "**th-OUGH-ts**" → "Tiny blob
  thoughts..." (a totally neutral canned fallback line) was misclassified
  ANGRY. Fixed to `\bugh+\b` (and `argh+`/`grr+` similarly bounded); dropped
  the now-redundant duplicate unbounded `\bugh\b` entry.
- SCARED's `\bhide\b` fired on "...where all the good starting ideas
  **hide**?" (benign, curious tone) → misclassified SCARED. `\bhelp\b` and
  `\brun\b` have the same problem (way too generic — "run this script",
  "can you help me" are everyday dev phrases, not fear). Removed all three
  from SCARED; `jump(ed|y)`/`startled`/`tremb(le|ling)`/`shak(e|ing|y)` are
  distinctive enough to stay.
- SCARED's `eek+` (no boundary) matched inside **week/geek/peek/creek**
  (extremely common words). Fixed to `\beek+\b`.
- Also proactively bounded SAD's `cry(ing)?`/`tear(s|y)?` (unbounded `cry`
  matches inside "**cry**stal"; unbounded `tear` matches inside
  "**tear**down", a real ops term) and HAPPY's `happ(y|ily|iness)` (was
  matching inside "un**happy**", double-counting against SAD's own
  dedicated "unhappy" pattern and sometimes winning the tie).
- Verified with a 15-case regression table (false-positive repros exactly
  matching Ryan's transcript + week/geek/crystal/teardown/run/help
  edge cases + the existing HAPPY/SAD/SURPRISED/ANGRY/SCARED positive
  samples) — all pass after the fix.
- Pattern for future additions to `TONE_WORDS`: any short/common-looking
  fragment (interjections, 3-5 letter words) MUST be `\b`-bounded, and
  should be sanity-checked against common English words that could contain
  it as a substring before landing (this is exactly how `ugh`/`eek`/`hide`/
  `help`/`run` slipped through the first time).
- Other transcript observation (not changed): roughly a third of the
  sampled lines were canned `SAFE_IDLE`/`SAFE_FALLBACKS` text rather than
  fresh LLM output, most likely `PetBrain.idle_comment()` hitting its own
  cooldown because real activity-change `think()` calls (force=True) were
  firing frequently in that session (lots of app switching) and resetting
  `_last_call`. That's the cooldown working as designed to avoid hammering
  Ollama, not a bug — but worth a closer look if Ryan wants idle chatter to
  feel fresher during bursts of activity (e.g. a separate, shorter cooldown
  just for `idle_comment`).

## Debug panel: right-click → Debug… (2026-07-17)
New `pet_debug.py`: `DebugDialog`, a non-modal styled panel (same cream/
lavender theme as Transcript/Settings) wired directly to the live
`DesktopPetWindow` — button clicks act on the real, currently-running pet,
nothing is simulated separately.
- **Actions** grid: Hop/Wave/Yawn/Stretch/Dance/Somersault/Eat/Sleep (all
  `PetAnimator.trigger_*`) + Wake, Surprise+Flee, and a 3s "Drag pose".
- **Emotions** grid: Neutral/Happy/Sad/Surprised/Angry/Scared, calling
  `animator.set_expression()` directly — bypasses `pet_window`'s normal
  odds/cooldown gate (`EXPRESSION_SHOW_PROB`/`EXPRESSION_MIN_GAP_S`) so
  testing is deterministic instead of probabilistic.
- **Test bubble box**: free-text input that calls the real `show_bubble()`,
  so you can verify `classify_emotion()` end-to-end (including the
  transcript logging) on arbitrary text without waiting for the LLM.
- `pet_animator.py`: all `trigger_*` methods gained a `force=False` param
  (default preserves existing guarded behavior for real call sites) — the
  debug dialog always calls with `force=True` so button mashing works
  regardless of the pet's current state. Added `trigger_sleep()` (previously
  only reachable via the idle timeout).
- Wired via `contextMenuEvent`: menu is now Settings… / Transcript… /
  Debug… / Quit. `DesktopPetWindow.open_debug()` follows the same
  lazy-create-and-reuse-instance pattern as `open_transcript()`.
- Verified offscreen: every action button flips `animator.state` to the
  expected `PetState`; every emotion button sets `animator.expression`;
  surprise+flee and drag-pose handlers run without needing a real mouse
  event; the bubble box round-trips through `show_bubble()` into the
  transcript; reopening `Debug…` reuses the same dialog instance.

## System prompt moved into pet_config.json, NOT exposed in Settings UI (2026-07-17)
Ryan wants to experiment with system-prompt variations by editing the config
file directly, without a UI field (so it can't be fat-fingered from the
Settings dialog).
- `pet_brain.py`: `SYSTEM_PROMPT` module constant stays as the built-in
  default/fallback. `PetBrain.__init__` gained `system_prompt=None`;
  `self._base_system_prompt = (system_prompt or "").strip() or
  SYSTEM_PROMPT` (blank/missing always falls back safely — can never end up
  with an empty prompt). New `set_system_prompt(text)` for live swaps
  (same plain-string-swap pattern as `set_persona`). `_system_prompt()`
  now layers `_persona_extra` (traits/initial_prompt) on top of
  `_base_system_prompt` instead of the hardcoded constant.
- `desktop_pet.py`: `load_config()`'s `default_config` now includes
  `"system_prompt": DEFAULT_SYSTEM_PROMPT` (imported from `pet_brain`). On
  first run after this change, if `pet_config.json` doesn't have the key
  yet, it's written into the file immediately (new `_write_config_file()`
  helper, shared with `save_config()`) so it's visible/editable right away
  instead of only existing in-memory. `apply_runtime_settings()` now also
  calls `self.brain.set_system_prompt(self.config.get("system_prompt", ""))`
  alongside the existing `set_persona()` call.
- `pet_settings.py`: deliberately UNTOUCHED — no new field, and
  `PetSettingsDialog.get_values()` doesn't include `"system_prompt"`, so
  `self.config.update(dialog.get_values())` in `open_settings()` can never
  overwrite it; it round-trips through `save_config()` untouched.
- To test a variation: edit `"system_prompt"` in `pet_config.json` directly,
  then restart `desktop_pet.py` (or it'll pick up on the next Settings…
  save too, since `apply_runtime_settings()` re-reads `self.config` either
  way). Ryan's real `pet_config.json` doesn't have the field yet — it'll be
  written in automatically the next time the pet actually starts.
- Verified with a scratch config copy (not Ryan's real `pet_config.json`,
  which was left untouched): migration-writes the key on first load,
  editing it to a deliberately different (pirate-themed) prompt and calling
  `apply_runtime_settings()` correctly swaps `brain._system_prompt()`'s
  base text while still layering the existing persona traits/initial
  prompt underneath.

## Chattiness debugging session — gating engine bugs + performance tier fix (2026-07-17)
Ryan: pet barely talks, typing/click reactions never fire, and what little it
says looks canned/fallback. Codebase has since gained a full `core/pet_engine.py`
(`PetEngine`, `MeaningfulChangeDetector`, `get_behavior_gating`) that supersedes
the simpler cooldown notes above — this section documents that newer system.
Found and fixed a chain of real bugs, not just tuning:
- **`pynput` was never installed** in `.venv` — click/keystroke monitors were
  silently fully disabled the whole time regardless of config. Installed it;
  fixed `run_pet.sh`'s install-hint (was missing `pynput`, README/USAGE.md
  already had it correctly).
- **`_trigger_idle_comment()` built a raw `Event()` directly instead of going
  through `engine.register_event()`**, so `isMeaningfulChange` stayed at its
  `False` default forever → every periodic idle bubble was blocked
  `not_meaningful`. Fix: idle comments are periodic/ambient by design and are
  now explicitly marked meaningful before gating.
- **Topic/application cooldowns (`topic_cooldown_*`/`application_cooldown_*`)
  were fake** — `get_behavior_gating` checked *membership in a small
  fixed-size rolling window* (last 10 topics / last 3 apps spoken about),
  not elapsed time, even though `sameTopicCooldown`/`sameApplicationCooldown`
  config values already existed (300s) and were dead/unused. For anyone whose
  activity spans only 1-3 topics (extremely common: "general" + "coding"),
  this was a near-permanent lock, not a cooldown. Rewired both to use real
  elapsed-time checks against those existing config values; `history["topics"]`
  entries are now `{"topic": ..., "timestamp": ...}` dicts (was bare strings —
  gating code defensively handles old-format string entries in existing state
  files).
- **`MeaningfulChangeDetector.is_meaningful()` compared `event.topic`
  (category bucket) instead of `event.source` (actual app/process) for
  `application_changed` events** — switching between two different apps that
  happen to guess to the same topic (e.g. a terminal and an editor both
  bucketing to "general") was treated as *no change at all*. This was the
  literal cause of a real transcript: `python` → `antigravity` both stayed
  silent. Fixed to compare `event.source`.
- **`click_activity` events were entirely unhandled** in `is_meaningful()`
  (fell through to the catch-all `return False`) — click reactions could
  never fire even after `pynput` was installed and `typing_suppression` was
  fixed. Now explicitly meaningful (rate-limited elsewhere by
  `CLICK_REACT_COOLDOWN` + the topic/app cooldowns).
- **`typing_suppression` blocked `application_changed`/`click_activity`
  events too** — a real app switch or a click IS itself a deliberate break
  from typing, so both are now exempt (only truly passive events like
  periodic `idle_comment` still get suppressed while actively typing).
- **Typing-commentary gating/cooldown/probability rejections were silent** —
  `_maybe_react_to_keystrokes()` just `return`ed with zero console output on
  every rejection path, making it impossible to tell why it wasn't firing.
  Added `[gating] Typing commentary blocked: <reason>` for all four paths
  (engine gating, its own cooldown, buffer-too-short, probability roll).
  Also loosened pacing: cooldown 45s→25s, min buffered chars 24→16, react
  probability 0.35→0.55. `CLICK_REACT_COOLDOWN` 20s→12s. `message_frequency`
  in `pet_config.json` bumped `normal`→`chatty`.
- **`validate_llm_response()` discarded the ENTIRE comment if it contained a
  `?`** and less than `questionCooldown` (600s) had passed since the last
  comment — not just the question, the whole otherwise-good LLM line, forcing
  a `SAFE_FALLBACKS` line instead. Since the system prompt explicitly
  encourages varying reply shape *including questions*, this was very likely
  the single biggest cause of the "canned/fallback" feel. Fixed to strip the
  `?` into a statement instead of discarding the response.
- **Reasoning-model "thinking" tokens ate the entire `num_predict` budget**
  (`gemma4:e4b` et al. emit a separate hidden `"thinking"` field before the
  real reply) — with a 150-token cap, some calls never got past the thinking
  phase, leaving `content: ""`, silently falling back. Fixed by adding
  `"think": false` to every `/api/chat` request in `PetBrain._chat()`.
- **Full LLM call/response logging added** (`core/pet_brain.py`, always-on,
  no env var gate anymore — removed the now-dead `PET_BRAIN_DEBUG`/`_debug`
  helper in favor of plain `print`): every `_chat()` call logs the outgoing
  request (model/attempt/timeout/num_predict/truncated prompt), the raw
  response or failure reason, cooldown skips, validation failures, and
  whether the final bubble used real LLM output vs a fallback line. This is
  the fastest way to confirm whether a given message was actually
  LLM-generated — grep the console for `[pet_brain]`.
- **Performance tier config bug**: `PERFORMANCE_MODES["extreme"]["model"]`
  pointed at `"gemma4:12b"`, which was **never actually installed** on this
  Ollama host (only `e2b`/`e4b`/`26b`/`31b`/etc. variants exist) — so
  `resolvedMode: "extreme"` would have 404'd on every call. Fixed to
  `"gemma4:26b"` (installed, 17.99GB/25.8B). Empirically tested cold-load
  latency before committing to a default: `gemma4:26b` cold-loads in **~105s**
  on this shared multi-model Ollama host (way past PetBrain's timeout) vs
  `gemma4:e4b` at **~8s** — so despite `recommendedMode` (hardware-spec-only
  static calculation) saying `"extreme"`, the persisted
  `selectedMode`/`resolvedMode` were pinned to `"high"` (`gemma4:e4b`,
  4096 ctx, 5m keep-alive) as the actually-reliable choice on this host.
  `recommendedMode` was deliberately left as `"extreme"` (still accurate
  hardware-capability info) — only the *active* selection changed. Also
  bumped `PetBrain`'s default request `timeout` 25s→45s for cold-load
  headroom. If Ryan wants true `extreme` quality and is fine with an
  occasional ~1-2 min first-response after the model's been idle, set
  Performance Tier → Extreme in Settings; otherwise leave on High.
- All 24 tests in `tests/` still pass after every fix above; two tests
  (`test_typing_suppression`, `test_energy_drain_and_costs`) were updated to
  match intentionally-changed behavior (the exemptions above, and `eat` now
  restoring energy — see next note).
- Also: `eat` action (`core/pet_engine.py` `ACTION_METADATA`/`select_action`)
  now **restores** 25 energy (capped at `energyMaximum`) instead of costing
  0.5 like every other action — was previously just another drain despite
  the name.
- Needs Ryan to restart `desktop_pet.py` to pick any of this up.

## Latency-budget enforcement for performance tiers (2026-07-17, same day)
Ryan: if he upgrades hardware and bumps to a bigger model, he wants a hard
guarantee responses still come back fast — never a silent 30s+ (or the
105s cold-load we measured for `gemma4:26b`) wait just because a tier
"should" work on paper. Two-layer fix, both new and real (not just tuning):

**1. Runtime enforcement — `PetBrain._effective_timeout()`** (`pet_brain.py`):
`llmTimeout` in `DEFAULT_CONFIG` (pet_engine.py) was ANOTHER dead config
value (same pattern as `sameTopicCooldown` earlier) — defined but never
read. Now `_chat()` uses `engine.config["llmTimeout"]` (falls back to the
constructor default only if no engine) as the actual per-request
`requests.post(..., timeout=...)`. This is the hard ceiling: no matter how
big/slow a selected model is, a single call can never block past this
budget — it fails fast to `SAFE_FALLBACKS` instead of hanging.

**2. Selection-time enforcement — latency-budget-aware benchmarking**
(`core/pet_performance.py`):
- `DEFAULT_LATENCY_BUDGET_S = 20.0` (mirrors `llmTimeout`, both budgets
  agree on "fast enough"). New `TIER_ORDER`/`step_down_tier()` (dedupes what
  was a copy-pasted `tiers_order` list in two places in `pet_settings.py`).
- `BenchmarkService.run_benchmark()` already measured `cold_load_time` but
  never used it for classification (only warm-latency/tokens-per-sec) — a
  model could be "excellent" by that measure while still taking 30-100+s to
  cold-load, which is exactly the failure mode that bit this session (see
  the "performance tier" note above: `gemma4:26b` measured anywhere from
  ~26s to ~105s cold load across different runs, depending on OS disk-cache
  state — highly variable, hence why this MUST be empirically benchmarked
  per-tier rather than assumed from a single number). Now factors
  `cold_load_time` into `classification`: exceeds budget → capped at
  `"marginal"`; exceeds `2×budget` → `"failed"`. Also bumped the initial
  cold-probe request's own timeout way up (40s→150s) so a slow cold load
  gets *measured and reported* instead of just raising a bare timeout
  exception with no diagnostic numbers.
- **Found and fixed a real bug while testing this**: the benchmark's
  `valid_json` check did a raw `json.loads(content)`, which fails on
  markdown-fenced JSON (` ```json {...} ``` `) — something these gemma4
  models do routinely (confirmed live). This was producing FALSE "failed"
  classifications purely from formatting, unrelated to speed — verified via
  a live run: `gemma4:e4b` scored `"failed"` (`valid_json: false`) before
  the fix, `"excellent"` (`valid_json: true`) after, with identical
  ~0.6-0.8s warm latency both times. Fixed to use the same lenient
  `re.search(r'\{.*\}', ...)` extraction `validate_llm_response()` already
  uses in production, so the benchmark's definition of "valid" matches what
  the running app actually accepts. Also bumped the benchmark's own
  `num_predict` 48→96 (was truncating mid-JSON-value at 48, another false
  "invalid" cause) and tightened its system prompt to explicitly forbid
  markdown fences.
- **Auto-downgrade wired into both places a tier gets (re)activated**, not
  just an advisory warning dialog you could dismiss and forget:
  - `ui/pet_settings.py` `run_diagnostic_and_benchmark()` (manual "Run
    Diagnostic" button): `"failed"` now actually steps `selectedMode` down
    one tier via `step_down_tier()` and updates the combo box, with a
    dialog showing the real numbers (cold load / warm latency vs budget).
    `"marginal"` still just warns (usable, but flagged).
  - `desktop_pet.py` new `_benchmark_and_enforce_budget(tier, model_name)`,
    called from `_check_first_run_setup()` right after a tier's model is
    confirmed installed (whether freshly downloaded or already present —
    previously NEITHER path ever benchmarked anything, first-run just
    trusted the static hardware-spec recommendation blindly). Same
    step-down-one-tier-on-"failed" behavior, reuses the existing
    `BenchmarkDialog` for a consistent progress UI.
- **Also fixed the actual root config bug this whole investigation started
  from**: `PERFORMANCE_MODES["extreme"]["model"]` was `"gemma4:12b"`, which
  was never installed on this Ollama host at all (only `e2b`/`e4b`/`26b`/
  `31b` variants exist) — every tier's `model` field is now verified to
  point at something that's actually pullable/installed. `extreme` →
  `gemma4:26b` (17.99GB, confirmed installed). Settings UI label updated to
  match ("Extreme (12B..." → "Extreme (26B...").
- Persisted state (`~/.config/squish-mate/pet_state.json`) left pinned at
  `selectedMode: "high"` / `resolvedMode: "high"` (the empirically-fast,
  already-installed `gemma4:e4b`) rather than auto-promoting to `extreme` —
  `recommendedMode` stays `"extreme"` as informational hardware-capability
  output only. Ryan can opt into `extreme` via Settings → Run Diagnostic any
  time; it'll now correctly warn/auto-downgrade if the cold-load budget
  isn't met on a given day's cache state.
- All 24 tests still pass. Live-verified end-to-end against the real local
  Ollama instance (not just unit tests): `gemma4:e4b` → `"excellent"`,
  `gemma4:26b` cold → `"marginal"` (cold load 26.5s > 20s budget, warm
  latency fine) — both exactly as intended.
- Needs Ryan to restart `desktop_pet.py` to pick any of this up.

## Response length bumped 14→20-30 words (2026-07-17, same day)
Ryan wanted longer, fuller replies. Updated everywhere the old 14/16-word
cap was encoded (there were 3 separate copies — easy to miss one):
- `pet_engine.py` `DEFAULT_CONFIG`: `maximumCommentWords` 14→30,
  `maximumCommentCharacters` 120→210 (the actual truncation safety net —
  verified a 25-word reply passes through untouched, a runaway 40-word one
  still gets capped to exactly 30).
- `pet_brain.py` module `SYSTEM_PROMPT`/`FORMAT_INSTRUCTION` (the built-in
  fallback prompt, used only if `pet_config.json` has no `system_prompt`).
- `pet_config.json`'s actual active `system_prompt` (this is the one really
  driving live behavior, per the "system prompt moved into config" note
  above) — "Under 16 words, short trailed-off phrase" → "Aim for 20-30
  words... but still land around 20-30 words most of the time", softened
  the "one-word blurt" example shape since that's no longer the default.
- **`PERFORMANCE_MODES` `num_predict` was the real ceiling** (both the
  display-only `numPredict` key and the actual-request `options.num_predict`
  — the latter always wins via `req_options.update(mode_opts)` in
  `_chat()`, so per-call `num_predict` args passed by `think()`/
  `idle_comment()`/etc. are dead weight whenever an engine+performance
  state is present). Was 64 (low/medium/high) / 72 (extreme) — nowhere near
  enough for a 30-word reply + JSON wrapper overhead, would have silently
  truncated mid-sentence exactly like the earlier "thinking tokens ate the
  budget" bug. Bumped all 4 tiers to 128 uniformly.
- Live-verified against the real Ollama instance (not just unit tests):
  warm replies landed at 17-25 words in ~1-1.5s, no truncation, JSON parsed
  cleanly every time.
- All 24 tests still pass. Needs Ryan to restart `desktop_pet.py`.

## Next ideas (Ryan's stated goals)
- Two-way chat with the user (input box or click-to-chat).
- Screen reading: screenshots + vision model to parse desktop details.
- Richer reactions wired from brain mood → animator states (e.g. brain picks
  hop/wave/sleep; `animator.trigger_*` methods already exist).

## Instant canned reactions: window close + drag (2026-07-17)
Added `pet_responses.py` — 55 canned "goodbye" lines (`WINDOW_CLOSE_TEMPLATES`,
`{app}` placeholder + `format_app_name()`) and 55 canned drag lines
(`DRAG_RESPONSES`), picked via `random.choice` so repeats aren't obvious.
These bypass the LLM brain entirely so they land instantly instead of ~a
minute later:
- `advanced_monitor.py`: `poll_closed_windows()` diffs `wmctrl -lx` output
  poll-to-poll (Linux-only; no-op elsewhere) to detect app windows closing.
  Skips WM_CLASS containing "python" so quitting the pet itself doesn't
  trigger a self-goodbye. First call only baselines (no false positives).
- `desktop_pet.py`: `_monitor_loop()` calls `poll_closed_windows()` every
  tick (~2s) and fires `_react_to_window_close()` → emits the new
  `window.window_closed_reaction` Qt signal (same queued cross-thread
  pattern as `bubble_requested`).
- `pet_window.py`: `window_closed_reaction` signal → `_on_window_closed()`
  shows the bubble + `animator.trigger_wave()`. Drag reaction is simpler and
  stays GUI-thread-only: `mouseMoveEvent()` shows a random drag line the
  moment `_dragging` flips True (drag start), no signal needed.
- Pattern for future "instant reaction" scenarios: add templates to
  `pet_responses.py`, detect the event cheaply (poll or existing Qt event),
  and fire straight to `show_bubble`/a signal — never route time-sensitive
  reactions through `PetBrain` (30s+ cooldown, network round-trip).
- Suggested next instant-reaction scenarios (not yet implemented): new app
  launch/open (diff `poll_closed_windows`'s window-id set the other
  direction), screen lock/unlock or system sleep/resume, and idle-cursor
  hover directly over the pet (no click) for a "tickle" reaction.

### Bug fix (2026-07-17) — "goodbye py" spam from the pet's own speech bubble
Ryan saw repeated `Window closed: py -> ...` firing constantly. Root cause:
`_list_open_windows_linux()` originally excluded the pet's own windows by
name (`'python' in app.lower()`), but its WM_CLASS reported as literally
`"py"` (doesn't contain "python", filter missed it) — and worse, the
`SpeechBubble` widget is its own top-level window that un-maps/re-maps every
time a bubble hides/shows, which looks exactly like a window closing on
every bubble dismissal. Fixed by excluding by **PID** instead of name: the
pet is a single in-process Qt app, so `os.getpid()` matches `_NET_WM_PID`
for every one of its native windows (main window + bubble). Cross-referenced
via `wmctrl -lp` (id→pid) joined with `wmctrl -lx` (id→WM_CLASS) in
`advanced_monitor._list_open_windows_linux()`. Verified live against
Ryan's real X session (`DISPLAY=:0`): a real Qt window's own PID is excluded
from tracking and closing it produces zero false "closed" events.

## Opt-in keystroke commentary (2026-07-17)
Added `pet_config["keystroke_commentary"]` (default **False**) — when on,
the pet occasionally reacts to what the user is typing (e.g. "this guy! I
can't stand him" while writing an email).
- `keystroke_monitor.py`: new `KeystrokeMonitor`, same shape as
  `click_monitor.py` (global pynput listener, daemon thread). Buffers only
  printable chars + space/enter/backspace into an in-memory list capped at
  240 chars (rolling — oldest drop off). `set_enabled(False)` wipes the
  buffer immediately. `snapshot_and_clear()` is the ONLY read path and
  clears in the same step — there is no peek-without-clearing. Nothing is
  ever written to disk or logged by this module.
- `pet_brain.py`: new `PetBrain.comment_on_typing(typed_text)` — sends the
  snapshot through the same sanitize/banned-phrase/anatomy pipeline as
  `think()`, explicit prompt instruction not to quote it back verbatim,
  `_debug` only ever logs the buffer LENGTH, never the content.
- `desktop_pet.py`: `_maybe_react_to_keystrokes()` runs each monitor-loop
  tick (~2s), gated by `KEYSTROKE_MIN_CHARS` (24), `KEYSTROKE_REACT_PROB`
  (0.35 — "sometimes", not every eligible moment), and
  `KEYSTROKE_REACT_COOLDOWN` (45s). Also checks the current window
  title/app against `_KEYSTROKE_SENSITIVE_KEYWORDS` (password/bank/2FA/
  password-manager names etc.) and discards (still clears) the buffer
  without ever calling the brain if matched — best-effort extra guard on
  top of the setting being opt-in. Result is NOT persisted to
  `PetMemory`/disk, only appended to the existing in-memory
  `interaction_history` deque (maxlen 20, RAM-only, same as other
  reactions).
- `pet_settings.py`: new checkbox "Occasionally comment on what I'm typing"
  (unchecked by default) + an explicit QLabel privacy note directly in the
  dialog explaining nothing is stored/logged, buffer is wiped on use or on
  turning the setting off.
- Verified live against the real local Ollama instance: sensitive-title
  buffer gets discarded without a brain call; normal-title buffer produces
  a real, on-vibe (non-verbatim-quoting) comment; debug output never prints
  raw typed text, only its length.

## Console-log the LLM prompt (2026-07-17)
`PetBrain._chat()` now has `log_prompt=True` (default) which prints the full
system + user message text to the console (`_debug`) right before the POST,
so Ryan can see exactly what's being sent to Ollama for `think()`/
`idle_comment()`/`summarize()`. `comment_on_typing()` explicitly passes
`log_prompt=False` — it stays redacted (only buffer length is ever logged),
preserving the "keystrokes are never logged" promise made in the Settings
dialog. Any future call site that touches keystroke-buffer content should
also pass `log_prompt=False`.

## Right-click Settings menu (2026-07-17)
Added a real settings system, closing the gap noted in handoff.md ("config
options mostly not wired to behavior").
- New `pet_settings.py`: `PetSettingsDialog` (QDialog — name, color picker,
  personality traits, initial prompt/extra persona guidance, movement
  frequency, message frequency, nap-after-idle seconds) + the shared presets
  `MOVE_FREQUENCY_PRESETS` / `MESSAGE_FREQUENCY_PRESETS` (calm/normal/hyper,
  quiet/normal/chatty → hop/wave/wander scheduling ranges + idle chatter
  cadence + brain cooldown).
- `pet_window.py`: `DesktopPetWindow.contextMenuEvent` (right-click) shows a
  `QMenu` with Settings…/Quit, emitting new `settings_requested`/
  `quit_requested` signals. `apply_settings(config)` pushes color →
  `renderer.apply_color()` and movement preset → `animator.set_frequencies()`.
- `blob_renderer.py`: body palette (`BODY_LIGHT/MID/DARK/EDGE`) is now
  per-instance, derived from one base hex via `apply_color()` (lighter/
  darker of the base) instead of fixed module constants. Eye/blush/shadow
  colors unchanged.
- `pet_animator.py`: `hop_range`/`wave_range`/`wander_range`/`sleep_after`
  are instance attrs (constructor args + `set_frequencies()` for live
  updates) instead of hardcoded literals scattered through the state
  machine.
- `pet_brain.py`: `PetBrain.set_persona(traits, initial_prompt)` appends
  owner-configured flavor text to the system prompt (`_system_prompt()`);
  the banned-phrase/anatomy filters in `_clean_output` still run
  post-generation regardless, so persona text can't disable safety.
- `desktop_pet.py`: `apply_runtime_settings()` is the single place that
  pushes `self.config` into window/animator/renderer/brain; called once in
  `start()` and again from `open_settings()` after the dialog is accepted.
  Idle-chatter cadence (`_idle_range_s`/`_idle_prob`) now comes from
  `MESSAGE_FREQUENCY_PRESETS` instead of the old hardcoded (25,70)/0.30.
- `pet_config.json` schema replaced: `name`, `color`, `personality_traits`
  (list), `initial_prompt`, `move_frequency`, `message_frequency`,
  `sleep_after`, `max_bubble_length`. Old unused fields (`size`, `speed`,
  `auto_movement`, `min/max_move_interval`, etc.) removed.
- Verified offscreen (`QT_QPA_PLATFORM=offscreen`): apply_settings mutates
  renderer/animator live, dialog round-trips values, persona text lands in
  the system prompt, `apply_runtime_settings()` is a safe no-op before the
  window exists. Not yet verified visually on the real display (right-click
  → menu → dialog interaction needs Ryan's session).

## TASKS.md pass: pet library, mouse-wiggle tickle, hosted LLM providers (2026-07-17)
All three open TASKS.md items implemented in one pass. All 24 existing tests
still pass; verified new code paths offscreen end-to-end (see below), not
yet on Ryan's real display.

**1. Mouse-wiggle "tickle" interaction.**
`pet_window.py`: the existing `mouseMoveEvent` hover branch already emitted
a `pet_clicked("hover")` signal (engine-gating only, no direct animation) —
added `_track_wiggle(global_x, now)` on top of it: keeps a `deque(maxlen=20)`
of `(t, x)` samples, counts horizontal direction reversals within the last
`WIGGLE_WINDOW_S` (0.6s); `WIGGLE_MIN_REVERSALS` (3) + `WIGGLE_MIN_TRAVEL_PX`
(40px) filters out a merely-resting cursor from an actual rapid wiggle.
`TICKLE_COOLDOWN_S` (6s) gates re-triggering. On trigger, `_react_to_tickle()`
shows an instant canned line (new `pet_responses.TICKLE_GIGGLE_LINES`/
`TICKLE_FLEE_LINES` + `random_tickle_line(fleeing=)`, same "instant canned
reaction, never route through PetBrain" pattern as drag/window-close) and
either plays a new `PetAnimator.trigger_giggle()` (new `PetState.GIGGLE`,
`_pose_giggle`: quick decaying side-to-side jiggle + wide grin, added to the
"stay put" state tuple in `_update_movement`) or, `TICKLE_FLEE_PROB` (0.35)
of the time, calls the existing `surprise_and_flee()` instead (giggle pose
would just be instantly overwritten by it, so skipped in that branch).
`pet_debug.py` ACTION_BUTTONS gained a "Giggle" button for consistency.

**2. Pet library / "Change Pet…".**
New `core/pet_library.py`: `PET_LIBRARY` (7 entries: pip/mochi/kelp/ember/
nocturne/honeydew/coral — id, name, color, pattern, blurb) + `get_pet(id)`
(unknown id safely falls back to the first entry). Per Ryan's spec ("overall
shape/style should remain the same... squishy") every entry reuses the
exact same `BlobRenderer`/`PetAnimator` — only body color (already
customizable via `apply_color`) and a new light decorative `pattern` differ,
so "all pets have the same functionality" is true by construction, not by
separate testing.
- `blob_renderer.py`: new `apply_pattern(pattern)` (validates against
  `PATTERNS = ("plain","spots","stripes","stars")`, invalid/missing falls
  back to "plain") + `_draw_pattern`/`_draw_star`, called from inside
  `_draw_body`'s existing silhouette-clipped block so decorations never
  bleed outside the body outline. Spots/stripes reuse `BODY_DARK` at low
  alpha (same jelly-shading language as existing bubbles/highlight); stars
  draws small 5-point sparkle shapes.
- New `ui/pet_library_dialog.py`: `ChangePetDialog(current_id, parent)` —
  modal grid of color-swatch buttons (name + blurb + ✓ on the current pick),
  `.selected_id` set on accept. Same cream/lavender-adjacent styling
  language as the other dialogs (transcript/debug).
- `pet_window.py`: new `change_pet_requested` signal, "Change Pet…" added to
  the right-click menu between Settings and Transcript; `apply_settings()`
  now also calls `renderer.apply_pattern(config.get("pattern","plain"))`.
- `desktop_pet.py`: new `open_change_pet()` (same lazy dialog-open pattern
  as `open_settings`) — on accept, looks up the species via `get_pet()`,
  sets `config["pet_species"]`/`config["color"]`/`config["pattern"]`, saves,
  calls `apply_runtime_settings()`, shows a "Ta-da, I'm {name} now!" bubble.
  `default_config` gained `"pet_species": "pip"` / `"pattern": "plain"`.
  Deliberately does NOT touch the Settings dialog's existing custom color
  picker — picking a species sets a starting color/pattern, but the user can
  still fine-tune color further via Settings afterward (pattern is only
  changed by Change Pet, so it survives a later Settings save).

**3. Hosted LLM provider support (OpenAI/Anthropic/OpenRouter).**
New `core/llm_providers.py` — deliberately NOT touching the existing,
tightly-tuned Ollama path in `pet_brain.py` (performance tiers, `keep_alive`,
`think:false`, vision-preference gating are all Ollama-specific and stay
exactly as-is). Only covers the three opt-in hosted alternatives:
- `chat(provider, *, model, system, user, api_key, base_url, num_predict,
  temperature, image_b64, timeout)` dispatches to `_chat_openai` (also
  reused for `openrouter`, same request/response shape, different
  `base_url`) or `_chat_anthropic`. Raises `ProviderError` on any failure
  (no key, network error, etc.) — same "return None / fall back to
  SAFE_FALLBACKS" contract PetBrain already has for Ollama failures.
  `DEFAULT_MODELS` gives each hosted provider a sane default
  (`gpt-4o-mini` / `claude-3-5-haiku-20241022` /
  `meta-llama/llama-3.1-8b-instruct`) used when no override is configured.
  Basic vision passthrough included for parity (OpenAI/OpenRouter:
  `image_url` data-URI content block; Anthropic: base64 `image` content
  block) — untested against real hosted APIs (no key available in this
  session), only unit-verified via a mocked `requests.post`.
- `pet_brain.py`: `PetBrain.__init__`/`set_provider(provider, api_key=,
  model_override=, base_url=)` — `self.provider` defaults to `"ollama"` so
  existing behavior/callers are unaffected unless explicitly switched.
  `model` property and `available()` both branch on `self.provider != "ollama"`
  first. `_chat()` branches to a new `_chat_hosted()` at the very top
  (before any Ollama-specific option-building) when provider isn't Ollama;
  logging follows the exact same `[pet_brain] _chat: ...` convention as the
  Ollama path so debugging is consistent regardless of backend.
- `desktop_pet.py`: `default_config` gained `"llm_provider": "ollama"`,
  `"llm_api_key": ""`, `"llm_model_override": ""`. `apply_runtime_settings()`
  calls `brain.set_provider(...)` alongside the existing `set_persona`/
  `set_system_prompt` calls.
- `pet_settings.py`: General tab gained an "AI Provider" combo (uses
  `llm_providers.PROVIDER_LABELS`), a password-masked "API Key" field, an
  optional "Model override" field, and an explanatory note (Ollama tab below
  it — the "AI Performance" tier tab — is explicitly noted as Ollama-only).
  `get_values()["general"]` includes the three new keys so they round-trip
  through the existing `self.config.update(vals["general"])` /
  `save_config()` flow with no other plumbing changes needed.
- Verified offscreen: `llm_providers.chat("openai", ...)` with no key raises
  `ProviderError` as expected; `PetBrain.set_provider("openai", api_key=...,
  model_override=...)` correctly changes `.model`/`.available()`, and a
  mocked `requests.post` round-trips through `PetBrain._chat()` end-to-end
  returning the mocked content. Not tested against real OpenAI/Anthropic/
  OpenRouter endpoints (no API keys available in this environment) — worth
  a live smoke test with Ryan's own key before he relies on it.
- Also noted, not changed: a full end-to-end `DesktopPet` smoke test
  (scratch config, not Ryan's real `pet_config.json`) incidentally wrote to
  the real `~/.config/squish-mate/pet_state.json` (PetEngine's default
  `STATE_PATH` — the engine autoloads/saves that file regardless of which
  `pet_config.json` is passed in). No functional harm (self-healing runtime
  state, same file real usage already writes to), but worth remembering:
  future test-only `PetEngine()` construction should pass an explicit
  `state_path=` pointing at a scratch file to avoid touching Ryan's real
  persisted state.
- Needs Ryan to restart `desktop_pet.py` to pick any of this up, and to
  supply a real API key in Settings to actually exercise a hosted provider.
