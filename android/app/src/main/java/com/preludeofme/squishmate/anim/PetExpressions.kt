package com.preludeofme.squishmate.anim

/**
 * Port of `ui/pet_expressions.py`'s `Emotion`/`EMOTION_POSE` table (pose
 * deltas only — `classify_emotion(text)`'s tone-word regex matching is NOT
 * ported here; the engine already returns a `suggestedEmotion` string
 * directly via `core/bridge.py`'s JSON snapshots, so Android has no need to
 * re-derive emotion from raw text the way the desktop app's local-model
 * fallback path does).
 */
enum class Emotion {
    NEUTRAL, HAPPY, SAD, SURPRISED, ANGRY, SCARED;

    companion object {
        /** Mirrors `desktop_pet`/`pet_brain`'s `suggestedEmotion` strings
         * (see `core/pet_engine.py` EMOTIONS) — note the engine has more
         * emotion names than this pose-overlay table covers; unmapped ones
         * (curious, concerned, hurt, sleepy, excited, content) intentionally
         * fall back to NEUTRAL (no facial overlay) here, matching how
         * desktop's own `set_expression()` callers only pass emotions that
         * have an `EMOTION_POSE` entry. */
        fun fromEngineString(value: String?): Emotion = when (value?.lowercase()) {
            "happy" -> HAPPY
            "sad" -> SAD
            "surprised" -> SURPRISED
            "annoyed", "angry" -> ANGRY
            "scared", "hurt" -> SCARED
            else -> NEUTRAL
        }
    }
}

const val DEFAULT_EXPRESSION_DURATION = 4.0

/** Pose deltas blended on top of the current state pose — see
 * `PetAnimator.applyExpression`. All fields nullable/zero-default,
 * matching the Python dict's "all keys optional" contract. */
data class EmotionPoseDelta(
    val mouth: Double? = null,
    val mouthOpen: Double? = null,
    val blush: Double? = null,
    val eyeScale: Double? = null,
    val eyeOpenCap: Double? = null,
    val brow: Double = 0.0,
    val tremble: Double? = null,
)

val EMOTION_POSE: Map<Emotion, EmotionPoseDelta> = mapOf(
    Emotion.HAPPY to EmotionPoseDelta(mouth = 1.0, blush = 0.25, eyeScale = 1.05),
    Emotion.SAD to EmotionPoseDelta(mouth = -0.85, blush = -0.35, eyeOpenCap = 0.6, brow = 0.6),
    Emotion.SURPRISED to EmotionPoseDelta(mouthOpen = 0.75, eyeScale = 1.3, blush = -0.1),
    Emotion.ANGRY to EmotionPoseDelta(mouth = -0.35, blush = 0.15, eyeScale = 0.85, brow = -0.9),
    Emotion.SCARED to EmotionPoseDelta(
        mouthOpen = 0.4, eyeScale = 1.35, blush = -0.25, brow = 0.8, tremble = 4.0,
    ),
)
