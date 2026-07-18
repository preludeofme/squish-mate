package com.preludeofme.squishmate.overlay

import android.content.Context
import android.graphics.Canvas
import android.view.Choreographer
import android.view.GestureDetector
import android.view.MotionEvent
import android.view.View
import com.preludeofme.squishmate.anim.Emotion
import com.preludeofme.squishmate.anim.PetAnimator
import com.preludeofme.squishmate.anim.Pose
import com.preludeofme.squishmate.render.BlobRenderer
import kotlin.math.abs

/**
 * The floating pet's on-screen surface (Phase 2 — see
 * docs/android_plan.md §5.2/§7): owns a [PetAnimator] (pose/state
 * simulation, ported 1:1 from `ui/pet_animator.py`, see
 * `PetAnimatorGoldenTest`) and a [BlobRenderer] (Canvas paint routine
 * ported from `ui/blob_renderer.py`), driven by a [Choreographer]-synced
 * render loop. ("Drop to ~10 FPS when idle, 0 FPS screen off" is a Phase 5
 * battery optimization, not implemented yet — this runs at full refresh
 * rate whenever the overlay view is attached.)
 *
 * Position (window x/y on screen) is owned by [OverlayService]'s
 * `WindowManager.LayoutParams`, NOT by [PetAnimator.x]/[PetAnimator.y] —
 * the animator's own position simulation (used internally for antenna
 * spring reaction to velocity, and normally driven by autonomous
 * "wander"/screen-traversal behavior on desktop) is intentionally
 * decoupled from the real window position for now: `wanderRange` is set
 * effectively infinite so the animator never picks its own glide targets,
 * avoiding silent drift out of sync with the real overlay window
 * position. Wiring animator-driven autonomous window movement across the
 * screen (reading `animator.x`/`animator.y` back into `WindowManager`) is
 * a deliberate follow-up, not done in this pass.
 */
class PetView(
    context: Context,
    private val listener: Listener,
) : View(context) {

    interface Listener {
        /** kind: "tap" | "drag" | "fling" | "longpress" */
        fun onInteraction(kind: String)
        fun onDragBy(dxPx: Int, dyPx: Int)
    }

    val animator = PetAnimator(
        VIEW_SIZE_PX, VIEW_SIZE_PX,
        wanderRange = Pair(1.0e6, 1.0e6),
    )
    private val renderer = BlobRenderer(VIEW_SIZE_PX.toFloat(), VIEW_SIZE_PX.toFloat())
    private var currentPose: Pose = Pose()

    private var lastFrameTimeNanos: Long = 0L
    private var touchCursor = doubleArrayOf(VIEW_SIZE_PX / 2.0, VIEW_SIZE_PX / 2.0)
    private var running = false

    private val frameCallback = object : Choreographer.FrameCallback {
        override fun doFrame(frameTimeNanos: Long) {
            if (!running) return
            val dt = if (lastFrameTimeNanos == 0L) 1.0 / 60.0
            else (frameTimeNanos - lastFrameTimeNanos) / 1_000_000_000.0
            lastFrameTimeNanos = frameTimeNanos
            currentPose = animator.update(dt, touchCursor, SCREEN_PLACEHOLDER)
            invalidate()
            Choreographer.getInstance().postFrameCallback(this)
        }
    }

    private val gestureDetector = GestureDetector(context, object : GestureDetector.SimpleOnGestureListener() {
        override fun onSingleTapConfirmed(e: MotionEvent): Boolean {
            animator.triggerHop(force = true)
            listener.onInteraction("tap")
            return true
        }

        override fun onLongPress(e: MotionEvent) {
            animator.triggerWave(force = true)
            listener.onInteraction("longpress")
        }

        override fun onFling(
            e1: MotionEvent?,
            e2: MotionEvent,
            velocityX: Float,
            velocityY: Float,
        ): Boolean {
            if (abs(velocityX) > FLING_VELOCITY_THRESHOLD || abs(velocityY) > FLING_VELOCITY_THRESHOLD) {
                animator.triggerGiggle(force = true)
                listener.onInteraction("fling")
                return true
            }
            return false
        }
    })

    private var lastRawX = 0f
    private var lastRawY = 0f
    private var dragTotalPx = 0f
    private var isDragging = false

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()
        running = true
        lastFrameTimeNanos = 0L
        Choreographer.getInstance().postFrameCallback(frameCallback)
    }

    override fun onDetachedFromWindow() {
        running = false
        Choreographer.getInstance().removeFrameCallback(frameCallback)
        super.onDetachedFromWindow()
    }

    /** Feed the engine's suggested emotion/action/sleeping into the
     * animator — the bridge equivalent of desktop's `_tick_engine`'s
     * `trigger_method = f"trigger_{action}"` dispatch (see
     * `PetAnimator.triggerAction`). Call from the main thread only. */
    fun applyEngineSnapshot(emotion: String, action: String, sleeping: Boolean) {
        animator.setExpression(Emotion.fromEngineString(emotion))
        when {
            sleeping -> animator.triggerSleep()
            animator.currentState == "sleep" -> animator.wake()
            animator.currentState == "idle" && !animator.moving -> animator.triggerAction(action)
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        gestureDetector.onTouchEvent(event)
        touchCursor = doubleArrayOf(event.x.toDouble(), event.y.toDouble())

        when (event.action) {
            MotionEvent.ACTION_DOWN -> {
                lastRawX = event.rawX
                lastRawY = event.rawY
                dragTotalPx = 0f
                isDragging = false
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = (event.rawX - lastRawX).toInt()
                val dy = (event.rawY - lastRawY).toInt()
                if (dx != 0 || dy != 0) {
                    dragTotalPx += abs(dx) + abs(dy)
                    if (dragTotalPx > DRAG_SLOP_PX && !isDragging) {
                        isDragging = true
                        animator.startDrag()
                    }
                    listener.onDragBy(dx, dy)
                    lastRawX = event.rawX
                    lastRawY = event.rawY
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                if (isDragging) {
                    animator.endDrag()
                    listener.onInteraction("drag")
                }
                touchCursor = doubleArrayOf(VIEW_SIZE_PX / 2.0, VIEW_SIZE_PX / 2.0)
            }
        }
        return true
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        renderer.draw(canvas, currentPose)
    }

    companion object {
        private const val DRAG_SLOP_PX = 24f
        private const val FLING_VELOCITY_THRESHOLD = 800f
        // Raw pixel size (not dp-scaled yet — a Phase-5-ish polish item)
        // used both as PetAnimator/BlobRenderer's internal coordinate
        // space AND as the actual overlay window's pixel dimensions (see
        // OverlayService.PET_SIZE_PX, which reads this constant so the
        // two never drift out of sync).
        const val VIEW_SIZE_PX = 220.0
        private val SCREEN_PLACEHOLDER = intArrayOf(0, 0, 1920, 1080)
    }
}
