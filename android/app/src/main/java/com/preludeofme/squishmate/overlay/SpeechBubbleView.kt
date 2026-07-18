package com.preludeofme.squishmate.overlay

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.util.AttributeSet
import android.view.View
import android.widget.TextView

/**
 * Speech bubble (docs/android_plan.md §3 architecture diagram —
 * `SpeechBubbleView`, previously the one Phase-2 piece that was never
 * built: `PetBridge.Snapshot.speech` was parsed but nothing ever showed
 * it). Deliberately a plain styled [TextView], not a Canvas paint routine
 * like [com.preludeofme.squishmate.render.BlobRenderer] — text rendering
 * doesn't need custom drawing, and this is reused as-is both as
 * [OverlayService]'s floating bubble window content view AND as a plain
 * inline view in `MainActivity`'s in-app fallback layout (no WindowManager
 * needed there).
 *
 * Colors mirror desktop's cream/lavender bubble theme
 * (`ui/pet_window.py`'s `SpeechBubble` — see active-context.md's dialog
 * styling notes) for visual consistency across platforms.
 */
class SpeechBubbleView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : TextView(context, attrs) {

    private var pendingHide: Runnable? = null

    init {
        val density = context.resources.displayMetrics.density
        setPadding((16 * density).toInt(), (10 * density).toInt(), (16 * density).toInt(), (10 * density).toInt())
        textSize = 14f
        setTextColor(Color.parseColor("#3A2E4D"))
        maxWidth = (260 * density).toInt()
        background = GradientDrawable().apply {
            setColor(Color.parseColor("#FFF7E8"))
            setStroke((2 * density).toInt(), Color.parseColor("#C9B6E4"))
            cornerRadius = 20f * density
        }
        visibility = View.GONE
    }

    /**
     * Show [text] and auto-hide after [durationMs] via [handler] (the
     * caller's own UI-thread [Handler] — matches the pattern every other
     * main-thread loop in this app already uses). Calling this again
     * while a bubble is already showing resets the hide timer rather than
     * stacking multiple pending hides.
     */
    fun show(text: String, handler: Handler, durationMs: Long = DEFAULT_DURATION_MS) {
        pendingHide?.let { handler.removeCallbacks(it) }
        this.text = text
        visibility = View.VISIBLE
        val hideNow = Runnable { visibility = View.GONE }
        pendingHide = hideNow
        handler.postDelayed(hideNow, durationMs)
    }

    fun hide(handler: Handler) {
        pendingHide?.let { handler.removeCallbacks(it) }
        pendingHide = null
        visibility = View.GONE
    }

    companion object {
        const val DEFAULT_DURATION_MS = 6_000L
    }
}
