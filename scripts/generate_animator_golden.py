#!/usr/bin/env python3
"""
generate_animator_golden.py — regenerates the cross-language golden fixture
used to verify the Kotlin `PetAnimator` port (android/app/.../anim/) matches
`ui/pet_animator.py` frame-for-frame (see docs/android_plan.md §5.2/§8's
"Animator golden tests").

Runs a fully SCRIPTED sequence of explicit `trigger_*(force=True)` calls and
`update()` steps — deliberately avoiding every code path in PetAnimator that
touches Python's `random` module (natural idle scheduling, blinking,
wander/surprise-flee target picking) by setting all frequency ranges to an
effectively-infinite value and disabling auto-blink. Python's Mersenne
Twister and the JVM's `java.util.Random` don't produce identical sequences
from the same seed, so a script that ever depended on RNG output couldn't be
replayed identically in Kotlin — this script's determinism instead comes
entirely from `PetAnimator`'s pose-shaping math (sin/cos/exp of elapsed
state-time), which IS portable, since dt/state_time are just plain floats
driven by this script, not by any RNG.

Usage:
    .venv/bin/python scripts/generate_animator_golden.py
Writes android/app/src/test/resources/animator_golden.json.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.pet_animator import PetAnimator
from ui.pet_expressions import Emotion

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "android", "app", "src", "test", "resources", "animator_golden.json",
)

DT = 1.0 / 30.0
CURSOR = (250.0, 250.0)
SCREEN = (0, 0, 1920, 1080)

POSE_FIELDS = (
    "t", "scale_x", "scale_y", "offset_y", "antenna_sway", "arm_l", "arm_r",
    "eye_open", "eye_scale", "pupil_dx", "pupil_dy", "mouth", "mouth_open",
    "blush", "brow", "body_rotation", "food_visual", "sleeping",
)


def build_animator():
    # Effectively-infinite frequency ranges so `_update_behavior`'s natural
    # random scheduling (hop/wave/wander/action/sleep-from-idle) never fires
    # during this script, regardless of total elapsed time.
    huge = (1.0e6, 1.0e6)
    anim = PetAnimator(
        80, 80,
        hop_range=huge, wave_range=huge, wander_range=huge,
        sleep_after=1.0e6, action_range=huge,
    )
    anim._next_blink = 1.0e6  # kill auto-blink randomness too
    return anim


def main():
    anim = build_animator()
    frames = []

    def run(steps):
        for _ in range(steps):
            pose = anim.update(DT, CURSOR, SCREEN)
            frame = {f: getattr(pose, f) for f in POSE_FIELDS}
            frame["state"] = anim.current_state
            frames.append(frame)

    run(10)  # idle warmup

    anim.trigger_hop(force=True)
    run(45)

    anim.trigger_wave(force=True)
    run(60)

    anim.trigger_yawn(force=True)
    run(50)

    anim.trigger_stretch(force=True)
    run(60)

    anim.trigger_dance(force=True)
    run(85)

    anim.trigger_somersault(force=True)
    run(40)

    anim.trigger_eat(force=True)
    run(65)

    anim.trigger_giggle(force=True)
    run(35)

    anim.trigger_sleep(force=True)
    run(20)
    anim.wake()  # SLEEP -> SURPRISED -> IDLE, no RNG involved
    run(35)

    anim.start_drag()
    run(15)
    anim.end_drag()
    run(10)

    # Deterministic glide (manual target, bypassing the RNG-driven
    # trigger_wander) to exercise _update_movement + antenna-spring reaction
    # to velocity.
    anim.target_x = anim.x + 400
    anim.target_y = anim.y
    anim.moving = True
    run(60)

    # Expression overlay blending on top of IDLE.
    anim.set_expression(Emotion.HAPPY, duration=2.0)
    run(70)
    anim.set_expression(Emotion.SCARED, duration=1.5)
    run(50)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"dt": DT, "cursor": list(CURSOR), "screen": list(SCREEN),
                   "frames": frames}, f, indent=1)
    print(f"Wrote {len(frames)} frames to {OUT_PATH}")


if __name__ == "__main__":
    main()
