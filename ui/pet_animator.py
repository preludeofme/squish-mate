#!/usr/bin/env python3
"""
pet_animator.py — procedural animation state machine for the desktop pet.

Pure Python (no Qt imports) so it can be unit-tested headlessly. Each frame the
window calls update(dt, cursor, screen) and receives a Pose: the full set of
values the renderer needs to draw the blob (squash/stretch, antenna sway, arm
offsets, eye/mouth expression, hop height, ...).

States: IDLE, HOP, WAVE, SLEEP, SURPRISED, DRAGGED, YAWN, STRETCH, DANCE,
SOMERSAULT, EAT. The last five are spontaneous "action" states — picked at
random while idle (see `action_range`/`_update_behavior`) purely for visual
variety; they carry no meaning beyond "look, something different!".
"""

import math
import os
import random
from dataclasses import dataclass
from enum import Enum, auto

from ui.pet_expressions import DEFAULT_EXPRESSION_DURATION, EMOTION_POSE, Emotion

# Shares the PET_EXPR_DEBUG toggle with pet_expressions.py so both halves of
# the expression pipeline (classification + application) can be traced
# together.
DEBUG = os.environ.get("PET_EXPR_DEBUG", "1") != "0"


class PetState(Enum):
    IDLE = auto()
    HOP = auto()
    WAVE = auto()
    SLEEP = auto()
    SURPRISED = auto()
    DRAGGED = auto()
    YAWN = auto()
    STRETCH = auto()
    DANCE = auto()
    SOMERSAULT = auto()
    EAT = auto()
    GIGGLE = auto()


# Spontaneous idle "action" states — cycled through at random by
# _update_behavior for variety. Kept separate from the transitional
# HOP/WAVE/SURPRISED states above, which have their own dedicated scheduling.
ACTION_STATES = (
    PetState.YAWN, PetState.STRETCH, PetState.DANCE,
    PetState.SOMERSAULT, PetState.EAT,
)


@dataclass
class Pose:
    t: float = 0.0          # animation clock (seconds) for renderer wobbles
    scale_x: float = 1.0    # body squash/stretch, anchored at the bottom
    scale_y: float = 1.0
    offset_y: float = 0.0   # vertical body offset (negative = airborne)
    antenna_sway: float = 0.0
    arm_l: float = 0.0      # arm tip y-offsets (negative = raised)
    arm_r: float = 0.0
    eye_open: float = 1.0   # 0 closed .. 1 open
    eye_scale: float = 1.0  # >1 widened (surprised)
    pupil_dx: float = 0.0   # -1..1 gaze toward cursor
    pupil_dy: float = 0.0
    mouth: float = 0.5      # -1 frown .. 1 smile
    mouth_open: float = 0.0 # 0..1 round "o" mouth overrides the curve
    blush: float = 0.6      # 0..1 cheek intensity
    brow: float = 0.0       # -1 furrowed/angry .. +1 raised/worried; 0 = hidden
    body_rotation: float = 0.0  # degrees, whole-body spin (somersault)
    food_visual: float = 0.0    # 0..1 shrinking snack prop near the mouth (eat)
    sleeping: bool = False


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


class PetAnimator:
    """Owns state, animation time, position and velocity, and transitions."""

    WANDER_SPEED = 90.0      # px/sec max glide speed
    HOP_HEIGHT = 26.0
    SLEEP_AFTER = 120.0      # default seconds of no interaction before napping

    def __init__(self, win_w, win_h, hop_range=(8, 16), wave_range=(25, 50),
                 wander_range=(25, 60), sleep_after=SLEEP_AFTER,
                 action_range=(45, 110)):
        self.win_w = win_w
        self.win_h = win_h
        self.state = PetState.IDLE
        self.t = 0.0
        self.state_time = 0.0

        # Behavior frequency ranges (seconds) — live-tunable via
        # set_frequencies() from Settings. Lower = more frequent.
        self.hop_range = hop_range
        self.wave_range = wave_range
        self.wander_range = wander_range
        self.sleep_after = sleep_after
        self.action_range = action_range  # yawn/stretch/dance/somersault/eat

        # Position (window top-left, float precision) and motion.
        self.x = 200.0
        self.y = 200.0
        self.target_x = self.x
        self.target_y = self.y
        self.moving = False
        self._vx = 0.0

        # Antenna spring (lags body motion, wobbles on landing).
        self._ant = 0.0
        self._ant_vel = 0.0
        self._prev_offset_y = 0.0

        # Store screen geometry updated on each frame
        self.last_screen = (0, 0, 1920, 1080)

        # Blink scheduling.
        self._next_blink = 2.5
        self._blink_start = -1.0

        # Behavior scheduling.
        self._next_hop = self._sched(*self.hop_range)
        self._next_wave = self._sched(*self.wave_range)
        self._next_wander = self._sched(*self.wander_range)  # big travel moves: rare
        self._next_action = self._sched(*self.action_range)
        self._last_interaction = 0.0
        self.stay_still = False

        # Facial expression overlay (see pet_expressions.py) — independent of
        # `self.state` above, which drives BODY/movement behavior (hop, wave,
        # sleep...). `Emotion.SURPRISED` (a facial reaction to something Pip
        # *said*) is deliberately a different concept from
        # `PetState.SURPRISED` (the physical startle-and-flee on click).
        self.expression = Emotion.NEUTRAL
        self._expr_start = 0.0
        self._expr_end = 0.0

    @property
    def current_state(self):
        """Returns the lowercase name of the current animation state."""
        return self.state.name.lower()

    # ----------------------------------------------------------- transitions
    def _sched(self, lo, hi):
        return self.t + random.uniform(lo, hi)

    def set_frequencies(self, hop_range=None, wave_range=None,
                         wander_range=None, sleep_after=None,
                         action_range=None):
        """Live-update behavior cadence (e.g. from the Settings dialog). Takes
        effect the next time each behavior is rescheduled."""
        if hop_range is not None:
            self.hop_range = hop_range
        if wave_range is not None:
            self.wave_range = wave_range
        if wander_range is not None:
            self.wander_range = wander_range
        if sleep_after is not None:
            self.sleep_after = sleep_after
        if action_range is not None:
            self.action_range = action_range

    def _enter(self, state):
        self.state = state
        self.state_time = 0.0

    def set_pos(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.target_x = self.x
        self.target_y = self.y

    def start_drag(self):
        self.wake()
        self.moving = False
        self._enter(PetState.DRAGGED)

    def end_drag(self):
        self.target_x, self.target_y = self.x, self.y
        self._enter(PetState.IDLE)
        self._next_wander = self._sched(*self.wander_range)

    def surprise_and_flee(self, screen):
        """Click reaction: startled pop, then scoot to the opposite side."""
        self.wake()
        self._enter(PetState.SURPRISED)
        sx, sy, sw, sh = screen
        max_x = sx + max(0, sw - self.win_w)
        max_y = sy + max(60, sh - self.win_h)
        cx = self.x + self.win_w / 2
        cy = self.y + self.win_h / 2
        if cx < sx + sw / 2:
            x_lo, x_hi = sx + int(sw * 0.60), max_x
        else:
            x_lo, x_hi = sx, sx + int(sw * 0.40)
        if cy < sy + sh / 2:
            y_lo, y_hi = sy + int(sh * 0.55), max_y
        else:
            y_lo, y_hi = sy + 60, sy + int(sh * 0.40)
        x_lo, x_hi = sorted((_clamp(x_lo, sx, max_x), _clamp(x_hi, sx, max_x)))
        y_lo, y_hi = sorted((_clamp(y_lo, sy, max_y), _clamp(y_hi, sy, max_y)))
        self.target_x = random.uniform(x_lo, x_hi)
        self.target_y = random.uniform(y_lo, y_hi)

    def set_expression(self, emotion, duration=DEFAULT_EXPRESSION_DURATION):
        """Overlay a temporary facial expression (see pet_expressions.py) on
        top of whatever `self.state` is already doing. Blended in/out over
        `update()` calls so it never snaps; ignored while SLEEP/DRAGGED/
        PetState.SURPRISED already own the face with their own reaction."""
        if not isinstance(emotion, Emotion):
            return
        self.expression = emotion
        self._expr_start = self.t
        self._expr_end = self.t + max(0.5, duration)
        if DEBUG:
            print(f"[pet_animator] expression -> {emotion.name} for {duration:.1f}s")

    # `force=True` bypasses the normal state guard (only fires from IDLE, or
    # IDLE/WAVE for hop) — used by pet_debug.py's DebugDialog so a tester can
    # spam buttons without waiting for the pet to settle back into IDLE.
    def trigger_hop(self, force=False):
        if force or self.state in (PetState.IDLE, PetState.WAVE):
            self._enter(PetState.HOP)

    def trigger_wave(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.WAVE)

    def trigger_yawn(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.YAWN)

    def trigger_stretch(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.STRETCH)

    def trigger_dance(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.DANCE)

    def trigger_somersault(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.SOMERSAULT)

    def trigger_eat(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.EAT)

    def trigger_sleep(self, force=False):
        if force or self.state is PetState.IDLE:
            self._enter(PetState.SLEEP)

    def trigger_giggle(self, force=False):
        """Tickled reaction — fired when the user wiggles the cursor over
        the pet (see DesktopPetWindow._track_wiggle)."""
        if force or self.state is PetState.IDLE:
            self._enter(PetState.GIGGLE)

    def trigger_wander(self, force=False):
        if force or self.state is PetState.IDLE:
            sx, sy, sw, sh = self.last_screen
            self.target_x = random.uniform(sx, sx + max(0, sw - self.win_w))
            self.target_y = random.uniform(sy + 60, sy + max(60, sh - self.win_h))
            self.moving = True
            if self.state is not PetState.IDLE:
                self._enter(PetState.IDLE)

    def trigger_screen_traversal(self, force=False):
        if force or self.state is PetState.IDLE:
            sx, sy, sw, sh = self.last_screen
            cx = self.x + self.win_w / 2
            if cx < sx + sw / 2:
                self.target_x = random.uniform(sx + sw * 0.6, sx + max(0, sw - self.win_w))
            else:
                self.target_x = random.uniform(sx, sx + sw * 0.4)
            self.target_y = random.uniform(sy + 60, sy + max(60, sh - self.win_h))
            self.moving = True
            if self.state is not PetState.IDLE:
                self._enter(PetState.IDLE)

    def trigger_wobble(self, force=False):
        self.trigger_hop(force=force)

    def trigger_bounce(self, force=False):
        self.trigger_hop(force=force)

    def trigger_excited(self, force=False):
        self.trigger_dance(force=force)

    def trigger_settle(self, force=False):
        self.trigger_stretch(force=force)

    def trigger_rest(self, force=False):
        self.trigger_yawn(force=force)

    def trigger_peek(self, force=False):
        self.trigger_wave(force=force)

    def notify_activity(self):
        """Something happened (bubble shown, user interacted) — stay awake."""
        self._last_interaction = self.t
        if self.state is PetState.SLEEP:
            self.wake()

    def wake(self):
        self._last_interaction = self.t
        if self.state is PetState.SLEEP:
            self._enter(PetState.SURPRISED)

    # ----------------------------------------------------------------- update
    def update(self, dt, cursor, screen):
        """Advance the simulation.

        dt: seconds since last frame.
        cursor: (x, y) global cursor position.
        screen: (x, y, w, h) available screen geometry.
        Returns a Pose for the renderer.
        """
        dt = _clamp(dt, 0.0, 0.1)
        self.t += dt
        self.state_time += dt
        self.last_screen = screen

        pose = Pose(t=self.t)

        self._update_behavior(screen)
        self._update_movement(dt)
        self._update_state_pose(pose)
        self._update_antenna(dt, pose)
        self._update_eyes(cursor, pose)
        self._apply_expression(pose)
        return pose

    # -------------------------------------------------------------- expression
    def _apply_expression(self, pose):
        if self.expression is Emotion.NEUTRAL:
            return
        if self.state in (PetState.SLEEP, PetState.DRAGGED, PetState.SURPRISED):
            return  # these states already have their own strong reaction
        remaining = self._expr_end - self.t
        if remaining <= 0:
            self.expression = Emotion.NEUTRAL
            return
        elapsed = self.t - self._expr_start
        fade_in = _clamp(elapsed / 0.3, 0.0, 1.0)
        fade_out = _clamp(remaining / 0.8, 0.0, 1.0)
        k = min(fade_in, fade_out)
        if k <= 0.0:
            return
        params = EMOTION_POSE.get(self.expression, {})
        if "mouth" in params:
            pose.mouth = pose.mouth * (1 - k) + params["mouth"] * k
        if "mouth_open" in params:
            pose.mouth_open = max(pose.mouth_open, params["mouth_open"] * k)
        if "blush" in params:
            pose.blush = _clamp(pose.blush + params["blush"] * k, 0.0, 1.0)
        if "eye_scale" in params:
            pose.eye_scale = pose.eye_scale * (1 - k) + params["eye_scale"] * k
        if "eye_open_cap" in params and pose.eye_open > params["eye_open_cap"]:
            pose.eye_open = (pose.eye_open * (1 - k)
                              + params["eye_open_cap"] * k)
        pose.brow = params.get("brow", 0.0) * k
        tremble = params.get("tremble")
        if tremble:
            pose.antenna_sway += math.sin(self.t * 42.0) * tremble * k

    # -------------------------------------------------------------- behaviors
    def _update_behavior(self, screen):
        if self.state is not PetState.IDLE:
            return
        if self.t - self._last_interaction > self.sleep_after:
            self.moving = False
            self._enter(PetState.SLEEP)
            return
        if self.t >= self._next_hop:
            self._next_hop = self._sched(*self.hop_range)
            self._enter(PetState.HOP)
            return
        if self.t >= self._next_wave and not self.moving:
            self._next_wave = self._sched(*self.wave_range)
            self._enter(PetState.WAVE)
            return
        if not self.moving and self.t >= self._next_action:
            self._next_action = self._sched(*self.action_range)
            self._enter(random.choice(ACTION_STATES))
            return
        if not self.stay_still and not self.moving and self.t >= self._next_wander:
            sx, sy, sw, sh = screen
            self.target_x = random.uniform(sx, sx + max(0, sw - self.win_w))
            self.target_y = random.uniform(sy + 60, sy + max(60, sh - self.win_h))
            self.moving = True

    def _update_movement(self, dt):
        if self.state in (PetState.DRAGGED, PetState.SLEEP, PetState.WAVE,
                          PetState.HOP, PetState.GIGGLE) or self.state in ACTION_STATES:
            self._vx *= max(0.0, 1.0 - dt * 6)
            return
        dx = self.target_x - self.x
        dy = self.target_y - self.y
        dist = math.hypot(dx, dy)
        if dist < 2.0:
            if self.moving:
                self.moving = False
                self._next_wander = self._sched(*self.wander_range)
            self._vx *= max(0.0, 1.0 - dt * 6)
            return
        speed = _clamp(dist * 1.2, 25.0, self.WANDER_SPEED)
        step = min(dist, speed * dt)
        nx = self.x + dx / dist * step
        self._vx = (nx - self.x) / dt if dt > 0 else 0.0
        self.x = nx
        self.y += dy / dist * step
        self.moving = True

    # ------------------------------------------------------------- state pose
    def _update_state_pose(self, pose):
        t = self.t
        st = self.state_time

        # Baseline breathing (multiplied into every grounded state).
        breath_x = 1.0 + math.sin(t * 2.0) * 0.02
        breath_y = 1.0 - math.sin(t * 2.0) * 0.025

        # Gentle alternating idle arm sway.
        pose.arm_l = math.sin(t * 2.2) * 2.5
        pose.arm_r = -math.sin(t * 2.2) * 2.5

        if self.state is PetState.IDLE:
            pose.scale_x, pose.scale_y = breath_x, breath_y
            pose.mouth = 0.55
            if self.moving:  # lean into travel with a light bounce
                pose.offset_y = -abs(math.sin(t * 7.0)) * 3.0

        elif self.state is PetState.HOP:
            self._pose_hop(st, pose)
            if self.state_time > 1.24:
                self._enter(PetState.IDLE)

        elif self.state is PetState.WAVE:
            pose.scale_x, pose.scale_y = breath_x, breath_y
            pose.arm_r = -14.0 + math.sin(st * 11.0) * 6.0
            pose.mouth = 0.9
            pose.blush = 0.9
            if st > 1.8:
                self._enter(PetState.IDLE)

        elif self.state is PetState.SLEEP:
            pose.scale_x = 1.0 + math.sin(t * 1.1) * 0.035
            pose.scale_y = 1.0 - math.sin(t * 1.1) * 0.04
            pose.eye_open = 0.0
            pose.mouth = 0.15
            pose.sleeping = True
            pose.arm_l = pose.arm_r = 2.0

        elif self.state is PetState.SURPRISED:
            k = math.exp(-st * 3.0)
            pose.scale_x = 1.0 - 0.10 * k
            pose.scale_y = 1.0 + 0.14 * k
            pose.offset_y = -8.0 * math.sin(_clamp(st / 0.35, 0, 1) * math.pi)
            pose.eye_scale = 1.0 + 0.35 * k
            pose.mouth_open = k
            pose.arm_l = pose.arm_r = -8.0 * k
            if st > 0.9:
                self._enter(PetState.IDLE)

        elif self.state is PetState.DRAGGED:
            pose.scale_x = 0.94
            pose.scale_y = 1.08 + math.sin(t * 9.0) * 0.02
            pose.eye_scale = 1.25
            pose.mouth_open = 0.7
            pose.arm_l = pose.arm_r = -9.0

        elif self.state is PetState.YAWN:
            self._pose_yawn(st, pose)
            if st > 1.5:
                self._enter(PetState.IDLE)

        elif self.state is PetState.STRETCH:
            self._pose_stretch(st, pose)
            if st > 1.85:
                self._enter(PetState.IDLE)

        elif self.state is PetState.DANCE:
            self._pose_dance(st, pose)
            if st > 2.6:
                self._enter(PetState.IDLE)

        elif self.state is PetState.SOMERSAULT:
            self._pose_somersault(st, pose)
            if st > 1.15:
                self._enter(PetState.IDLE)

        elif self.state is PetState.EAT:
            self._pose_eat(st, pose)
            if st > 1.9:
                self._enter(PetState.IDLE)

        elif self.state is PetState.GIGGLE:
            self._pose_giggle(st, pose)
            if st > 1.0:
                self._enter(PetState.IDLE)

    def _pose_yawn(self, st, pose):
        """Big stretchy open-mouth yawn: open, hold, close, with a small
        matching arm stretch and squinty eyes."""
        T1, T2, T3 = 0.45, 0.55, 0.45
        if st < T1:
            pose.mouth_open = (st / T1) * 0.9
        elif st < T1 + T2:
            pose.mouth_open = 0.9
        elif st < T1 + T2 + T3:
            pose.mouth_open = 0.9 * (1.0 - (st - T1 - T2) / T3)
        else:
            pose.mouth_open = 0.0
        pose.eye_open = _clamp(1.0 - pose.mouth_open * 0.7, 0.2, 1.0)
        stretch = min(1.0, st / (T1 + T2))
        pose.arm_l = pose.arm_r = -6.0 * stretch
        pose.scale_y = 1.0 + 0.05 * pose.mouth_open
        pose.scale_x = 1.0 - 0.03 * pose.mouth_open

    def _pose_stretch(self, st, pose):
        """Arms-out full-body stretch, held, then relaxed."""
        T1, T2, T3 = 0.5, 0.7, 0.5
        if st < T1:
            p = st / T1
        elif st < T1 + T2:
            p = 1.0
        elif st < T1 + T2 + T3:
            p = 1.0 - (st - T1 - T2) / T3
        else:
            p = 0.0
        pose.arm_l = pose.arm_r = -22.0 * p
        pose.scale_y = 1.0 + 0.12 * p
        pose.scale_x = 1.0 - 0.08 * p
        pose.mouth = 0.7
        pose.blush = 0.7

    def _pose_dance(self, st, pose):
        """Silly side-to-side wiggle dance with alternating tentacle waves."""
        beat = st * 8.0
        pose.scale_x = 1.0 + math.sin(beat) * 0.06
        pose.scale_y = 1.0 - math.sin(beat) * 0.05
        pose.offset_y = -abs(math.sin(beat)) * 6.0
        pose.arm_l = math.sin(beat) * 14.0
        pose.arm_r = -math.sin(beat + math.pi) * 14.0
        pose.body_rotation = math.sin(st * 4.0) * 8.0
        pose.mouth = 0.9
        pose.blush = 0.9

    def _pose_somersault(self, st, pose):
        """Quick forward flip: one full rotation with a hop-like arc."""
        T = 1.0
        p = _clamp(st / T, 0.0, 1.0)
        pose.body_rotation = 360.0 * p
        pose.offset_y = -self.HOP_HEIGHT * 1.4 * math.sin(math.pi * p)
        pose.scale_x = 1.0 - 0.10 * math.sin(math.pi * p)
        pose.scale_y = 1.0 + 0.10 * math.sin(math.pi * p)
        pose.arm_l = pose.arm_r = -10.0 * math.sin(math.pi * p)

    def _pose_eat(self, st, pose):
        """Rhythmic nibbling on a tiny snack that shrinks away to nothing."""
        T = 1.9
        chew = (math.sin(st * 10.0) + 1.0) / 2.0
        pose.mouth_open = 0.15 + chew * 0.35
        pose.food_visual = max(0.0, 1.0 - st / T)
        pose.mouth = 0.6
        pose.blush = 0.8

    def _pose_giggle(self, st, pose):
        """Tickled squirm: quick side-to-side jiggle with a wide grin, decays
        out over ~1s. Triggered by mouse-wiggle hover, not the random
        idle-action scheduler."""
        beat = st * 15.0
        decay = math.exp(-st * 2.2)
        pose.scale_x = 1.0 + math.sin(beat) * 0.09 * decay
        pose.scale_y = 1.0 - math.sin(beat) * 0.07 * decay
        pose.offset_y = -abs(math.sin(beat * 0.5)) * 5.0 * decay
        pose.arm_l = math.sin(beat) * 10.0 * decay
        pose.arm_r = -math.sin(beat + math.pi) * 10.0 * decay
        pose.mouth = 1.0
        pose.mouth_open = 0.3 * decay
        pose.blush = 1.0
        pose.eye_open = _clamp(1.0 - 0.3 * decay, 0.6, 1.0)

    def _pose_hop(self, st, pose):
        """Squash-and-stretch hop: anticipate → airborne → land → recover."""
        T1, T2, T3 = 0.14, 0.46, 0.14  # anticipation, airtime, landing squash
        if st < T1:
            p = st / T1
            pose.scale_x = 1.0 + 0.16 * p
            pose.scale_y = 1.0 - 0.16 * p
        elif st < T1 + T2:
            p = (st - T1) / T2
            pose.offset_y = -self.HOP_HEIGHT * math.sin(math.pi * p)
            speed = abs(math.cos(math.pi * p))   # fast at takeoff/landing
            pose.scale_x = 1.0 - 0.12 * speed
            pose.scale_y = 1.0 + 0.15 * speed
        elif st < T1 + T2 + T3:
            p = (st - T1 - T2) / T3
            k = 1.0 - p * 0.35
            pose.scale_x = 1.0 + 0.18 * k
            pose.scale_y = 1.0 - 0.18 * k
        else:
            p = st - T1 - T2 - T3
            wob = math.sin(p * 18.0) * 0.08 * math.exp(-p * 4.0)
            pose.scale_x = 1.0 + wob
            pose.scale_y = 1.0 - wob
        pose.mouth = 0.8

    # ---------------------------------------------------------------- antenna
    def _update_antenna(self, dt, pose):
        body_vy = (pose.offset_y - self._prev_offset_y) / dt if dt > 0 else 0.0
        self._prev_offset_y = pose.offset_y
        drive = _clamp(-self._vx * 0.06 - body_vy * 0.05, -12.0, 12.0)
        # Underdamped spring so the antenna lags motion and wobbles on landing.
        self._ant_vel += ((drive - self._ant) * 40.0 - self._ant_vel * 5.0) * dt
        self._ant += self._ant_vel * dt
        idle_sway = math.sin(self.t * 3.0) * 3.5
        pose.antenna_sway = idle_sway + _clamp(self._ant, -14.0, 14.0)

    # ------------------------------------------------------------------- eyes
    def _update_eyes(self, cursor, pose):
        if self.state is PetState.SLEEP:
            return
        # Blink.
        if self._blink_start < 0 and self.t >= self._next_blink:
            self._blink_start = self.t
        if self._blink_start >= 0:
            p = (self.t - self._blink_start) / 0.24
            if p >= 1.0:
                self._blink_start = -1.0
                self._next_blink = self._sched(2.5, 6.0)
            else:
                pose.eye_open = abs(p * 2.0 - 1.0)  # 1 → 0 → 1
        if self.state in (PetState.SURPRISED, PetState.DRAGGED):
            pose.eye_open = 1.0
        # Pupils follow the cursor.
        cx = self.x + self.win_w / 2
        cy = self.y + self.win_h / 2
        pose.pupil_dx = _clamp((cursor[0] - cx) / 300.0, -1.0, 1.0)
        pose.pupil_dy = _clamp((cursor[1] - cy) / 300.0, -1.0, 1.0)
        if self.moving:
            direction = 1 if self.target_x > self.x else -1
            pose.pupil_dx = _clamp(pose.pupil_dx + direction * 0.4, -1.0, 1.0)
