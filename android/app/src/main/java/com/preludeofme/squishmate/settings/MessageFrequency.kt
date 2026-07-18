package com.preludeofme.squishmate.settings

/**
 * Mirrors `core/bridge.py`'s `MESSAGE_FREQUENCY_PRESETS` idle-probability
 * values. Real pacing is still enforced server-side (the engine's
 * `minimumSpeechCooldown` — see `core/pet_engine.py`), so this only
 * controls how often a Kotlin tick loop even *attempts* an idle-comment
 * call; it's centralized here (not duplicated per call site) since both
 * `OverlayService` and `MainActivity`'s in-app fallback pet need the same
 * value and are otherwise independent classes.
 */
object MessageFrequency {
    private val IDLE_PROB = mapOf(
        "quiet" to 0.15,
        "normal" to 0.30,
        "chatty" to 0.55,
    )

    fun idleProb(messageFrequencyId: String): Double =
        IDLE_PROB[messageFrequencyId] ?: IDLE_PROB.getValue("normal")
}
