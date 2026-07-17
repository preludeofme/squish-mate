#!/usr/bin/env python3
"""
pet_expressions.py — facial-expression ("emotion") system for the desktop pet.

Two responsibilities:

1. `Emotion` + `EMOTION_POSE` — a small table of pose deltas (mouth curve,
   blush, eye scale/openness, eyebrow angle, antenna tremble) for HAPPY,
   SAD, SURPRISED, ANGRY, SCARED (+ NEUTRAL). `PetAnimator.set_expression()`
   blends these on top of whatever the movement state machine is already
   doing, so the face can react independently of hops/waves/sleep.

2. `classify_emotion(text)` — a deterministic, LOCAL regex/keyword "tone
   matcher" run over bubble text (LLM output or canned lines) to guess which
   emotion it's expressing.

   NOTE on "tool calls": the local model (a small quantized Gemma) is not
   reliable at emitting structured tool-call JSON — asking it to also output
   an `{"emotion": "..."}` field alongside its one-sentence reply is exactly
   the kind of extra instruction-following small models flake on, and a
   malformed/missing field would either crash parsing or silently always
   fall back to one emotion. So instead of a tool call, this scans the
   NATURAL LANGUAGE text the model already produces (which `pet_brain.py`
   validates/cleans anyway) for tone words after the fact. Cheap, has zero
   extra LLM round-trips, and degrades gracefully (no match -> NEUTRAL).
"""

import os
import re
from enum import Enum, auto

# Verbose expression tracing (which emotion was classified from which text,
# and when PetAnimator actually applies one). On by default; PET_EXPR_DEBUG=0
# to silence.
DEBUG = os.environ.get("PET_EXPR_DEBUG", "1") != "0"


def _debug(msg):
    if DEBUG:
        print(f"[pet_expressions] {msg}")


class Emotion(Enum):
    NEUTRAL = auto()
    HAPPY = auto()
    SAD = auto()
    SURPRISED = auto()
    ANGRY = auto()
    SCARED = auto()


DEFAULT_EXPRESSION_DURATION = 4.0  # seconds, overridden by callers to match bubble duration

# Pose deltas blended on top of the current state pose (see
# PetAnimator._apply_expression). All keys optional:
#   mouth:         -1 (frown) .. 1 (big smile) — pose.mouth blends toward this
#   mouth_open:    0..1 round "o" mouth — takes the max with whatever the
#                  state pose already wants (so e.g. HOP's smile isn't erased)
#   blush:         added to pose.blush, clamped 0..1
#   eye_scale:     pose.eye_scale blends toward this
#   eye_open_cap:  caps pose.eye_open at this value (droopy/squinting)
#   brow:          -1 furrowed-down (angry) .. +1 raised-worried (sad/scared)
#   tremble:       extra antenna jitter amplitude (scared, nervous energy)
EMOTION_POSE = {
    Emotion.HAPPY: {
        "mouth": 1.0, "blush": 0.25, "eye_scale": 1.05,
    },
    Emotion.SAD: {
        "mouth": -0.85, "blush": -0.35, "eye_open_cap": 0.6, "brow": 0.6,
    },
    Emotion.SURPRISED: {
        "mouth_open": 0.75, "eye_scale": 1.3, "blush": -0.1,
    },
    Emotion.ANGRY: {
        "mouth": -0.35, "blush": 0.15, "eye_scale": 0.85, "brow": -0.9,
    },
    Emotion.SCARED: {
        "mouth_open": 0.4, "eye_scale": 1.35, "blush": -0.25, "brow": 0.8,
        "tremble": 4.0,
    },
}


# --------------------------------------------------------------- tone words
# Biased toward how Pip actually talks (goofy alien blob, short lines,
# `*action*` asides) rather than generic sentiment-analysis vocabulary.
# Word-boundary-ish regex fragments, case-insensitive, joined per emotion.
TONE_WORDS = {
    Emotion.HAPPY: [
        r"yay+", r"woo+h?o+", r"wheee+", r"weee+", r"yippee", r"hooray",
        r"\bhapp(y|ily|iness)\b", r"glad", r"delight(ed|ful)?", r"\blove\b", r"\bloves\b",
        r"awesome", r"amazing", r"fantastic", r"\bgreat\b", r"\bbest\b",
        r"\bfun\b", r"funny", r"giggl(e|es|ing)", r"laugh(s|ing)?",
        r"excit(ed|ing)", r"yes+!", r"\bnice\b", r"\bsweet\b", r"\bcute\b",
        r"\bcozy\b", r"\bproud\b", r"wonderful", r"\bperfect\b", r"heh+",
        r"haha+", r"smil(e|es|ing)", r"cheer(ful|s)?", r"\bbliss(ful)?\b",
    ],
    Emotion.SAD: [
        r"\bsad\b", r"\baw+\b", r"awww+", r"\bsigh\b", r"miss(ing)? you",
        r"\blonely\b", r"\bsorry\b", r"\bbummer\b", r"disappoint(ed|ing)?",
        r"\bcry(ing)?\b", r"\btear(s|y)?\b", r"\bblue\b", r"\bdown\b",
        r"heartbroken", r"\bgloomy\b", r"\bupset\b", r"\bhurts?\b",
        r"\bouch\b", r"\bmeh\b", r"unhappy", r"\blost\b", r"sorrowful",
        r"whimper", r"\bmoping\b",
    ],
    Emotion.SURPRISED: [
        # NOTE: deliberately excludes bare "wait," / "huh," — the desktop
        # pet's own system prompt (pet_brain.py) suggests those as generic
        # sentence openers for variety, so they fire constantly and aren't a
        # real surprise signal on their own. Require a genuinely surprised
        # marker (a "?" on huh/what, or a stronger phrase) instead.
        r"whoa+", r"wow+", r"wh?at\?", r"\bhuh\?", r"no way",
        r"seriously\??", r"surpris(ed|ing)", r"shock(ed|ing)?", r"\bgasp\b",
        r"\bomg\b", r"\bjeez\b", r"\bgeez\b", r"\bholy\b", r"since when",
        r"didn'?t (see|expect) that", r"out of nowhere", r"\bsuddenly\b",
        r"no freaking way", r"wait,?\s*what",
    ],
    Emotion.ANGRY: [
        # \b-bounded so these interjections don't fire on ordinary words that
        # happen to contain them mid-string (e.g. unbounded "ugh+" matched
        # inside "thoughts" — th-OUGH-ts — a real false positive Ryan hit).
        r"\bugh+\b", r"\bargh+\b", r"\bgrr+\b", r"\bhmph\b", r"\bmad\b",
        r"annoy(ed|ing)", r"irritat(ed|ing)", r"\brude\b", r"not cool",
        r"stop it", r"knock it off", r"frustrat(ed|ing)", r"\bfurious\b",
        r"\bangry\b", r"seriously\?!", r"\bcome on\b", r"unbelievable",
        r"\bridiculous\b", r"\bnope\b",
    ],
    Emotion.SCARED: [
        # "help"/"run"/"hide" were dropped — too generic on their own (they
        # fired on completely benign lines like "...ideas hide?" or "run
        # this script"); "eek+" was un-bounded and matched inside "week",
        # "geek", "peek" etc. — another real false positive Ryan hit.
        r"scar(y|ed|ing)", r"\bafraid\b", r"\byikes\b", r"\beek+\b",
        r"\bnervous\b", r"\bspooky\b", r"\bcreepy\b", r"uh[\s-]?oh",
        r"freak(ed|ing)? out", r"terrifi(ed|ying)", r"panick(ed|ing)?",
        r"jump(ed|y)", r"\bstartled\b",
        r"\btremb(le|ling)\b", r"\bshak(e|ing|y)\b", r"\bgulp\b",
    ],
}

_TONE_RE = {
    emotion: re.compile("|".join(patterns), re.IGNORECASE)
    for emotion, patterns in TONE_WORDS.items()
}


def classify_emotion(text):
    """Best-guess `Emotion` for `text` via keyword/regex tone matching.

    Scores every emotion by how many tone-word patterns hit, picks the
    highest, and returns Emotion.NEUTRAL if nothing matched (or text is
    empty). Ties break toward whichever emotion is checked first in
    dict-insertion order (HAPPY, SAD, SURPRISED, ANGRY, SCARED).
    """
    if not text:
        return Emotion.NEUTRAL
    scores = {}
    for emotion, pattern in _TONE_RE.items():
        n = len(pattern.findall(text))
        if n:
            scores[emotion] = n
    if not scores:
        _debug(f"classify_emotion: no tone match -> NEUTRAL  text={text!r}")
        return Emotion.NEUTRAL
    best = max(scores.items(), key=lambda kv: kv[1])[0]
    readable = {k.name: v for k, v in scores.items()}
    _debug(f"classify_emotion: {text!r} -> {best.name}  scores={readable}")
    return best


if __name__ == "__main__":
    samples = [
        "Yay! I love watching you code!",
        "Aw, that's kind of a bummer, I'm sorry.",
        "Whoa, wait, since when do you have 40 tabs open?!",
        "Ugh, seriously? That's so annoying.",
        "Yikes, that error looks scary, I'm a little nervous.",
        "Ooo, cozy over here.",
        "*wobbles happily*",
    ]
    for s in samples:
        print(f"{s!r:60} -> {classify_emotion(s).name}")
