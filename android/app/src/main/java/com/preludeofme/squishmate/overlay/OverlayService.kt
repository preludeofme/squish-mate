package com.preludeofme.squishmate.overlay

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.util.Log
import android.view.Gravity
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import com.preludeofme.squishmate.MainActivity
import com.preludeofme.squishmate.R
import com.preludeofme.squishmate.bridge.PetBridge
import com.preludeofme.squishmate.monitor.DeviceEventMonitor
import com.preludeofme.squishmate.monitor.UsageMonitor
import com.preludeofme.squishmate.settings.MessageFrequency
import com.preludeofme.squishmate.settings.PetSettingsStore
import kotlin.random.Random

/**
 * Foreground service that owns the floating [PetView] overlay window (see
 * docs/android_plan.md §5.1/§5.6). The window floats, survives app-switch,
 * is draggable, and drives a real engine tick through [PetBridge]; each
 * tick's emotion/action/sleeping snapshot is fed into [PetView]'s real
 * `PetAnimator`/`BlobRenderer` (Phase 2) via [PetView.applyEngineSnapshot].
 * A second overlay window, [bubbleView] ([SpeechBubbleView]), shows what
 * the pet says — fed by periodic ambient chatter ([maybeTriggerIdleComment])
 * and, opt-in, real app-switch context via [UsageMonitor]
 * ([maybeCheckForegroundApp], Phase 4).
 *
 * Threading: engine/bridge calls happen on [workerHandler] (a dedicated
 * background [HandlerThread]) — never on the main thread, since
 * `PetBridge.onActivity`/`idleComment` can block on network. UI mutations
 * (adding the view, moving it, redrawing, feeding a tick snapshot into the
 * animator) stay on the main thread via [uiHandler].
 *
 * [deviceEventMonitor] ([DeviceEventMonitor], Phase 4) feeds Android-only
 * context (battery low, charger plugged/unplugged, headphones) into the
 * same [PetBridge.onActivity] path as [maybeCheckForegroundApp]. Both, plus
 * [maybeTriggerIdleComment], are suppressed for a short window after a drag
 * or a screen unlock ([isRecentlyDistracted]) — the mobile equivalent of
 * desktop's typing-suppression: a user who just touched the pet or just
 * unlocked their phone doesn't want it immediately talking over them.
 */
class OverlayService : Service(), PetView.Listener {

    private lateinit var windowManager: WindowManager
    private lateinit var petView: PetView
    private lateinit var layoutParams: WindowManager.LayoutParams
    private lateinit var bubbleView: SpeechBubbleView
    private lateinit var bubbleParams: WindowManager.LayoutParams

    private lateinit var workerThread: HandlerThread
    private lateinit var workerHandler: Handler
    private val uiHandler = Handler(Looper.getMainLooper())

    private var ticking = false
    private var lastTickMs = System.currentTimeMillis()
    private var lastIdleAttemptMs = 0L
    private var lastForegroundCheckMs = 0L
    private var lastForegroundPackage: String? = null
    private var lastDragMs = 0L
    private var lastScreenOnMs = 0L
    private lateinit var deviceEventMonitor: DeviceEventMonitor

    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                Intent.ACTION_SCREEN_OFF -> stopTicking()
                Intent.ACTION_SCREEN_ON -> {
                    lastScreenOnMs = System.currentTimeMillis()
                    startTicking()
                }
                PetSettingsStore.ACTION_CONFIG_UPDATED -> reloadConfig()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        workerThread = HandlerThread("squish-mate-bridge-worker").apply { start() }
        workerHandler = Handler(workerThread.looper)

        startForeground(NOTIFICATION_ID, buildNotification())
        addOverlayView()
        // API 33+ requires an explicit exported flag on every dynamically
        // registered receiver (a real crash caught only by running this on
        // a device/emulator — see active-context.md's Phase 1 emulator
        // smoke-test entry). RECEIVER_NOT_EXPORTED is correct here: SCREEN_ON/
        // OFF are system-protected broadcasts anyway (only the OS can send
        // them), and ACTION_CONFIG_UPDATED is an internal same-app signal
        // that should never be receivable from another app.
        // ContextCompat.registerReceiver (not the raw 3-arg Context API,
        // which only exists on API 33+) keeps this working down to minSdk 26.
        ContextCompat.registerReceiver(
            this,
            screenReceiver,
            IntentFilter().apply {
                addAction(Intent.ACTION_SCREEN_OFF)
                addAction(Intent.ACTION_SCREEN_ON)
                addAction(PetSettingsStore.ACTION_CONFIG_UPDATED)
            },
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )

        val configJson = PetSettingsStore.currentConfigJson(this)
        workerHandler.post {
            try {
                PetBridge.init(filesDir.absolutePath, configJson)
            } catch (e: Exception) {
                Log.e(TAG, "PetBridge.init failed", e)
            }
        }
        deviceEventMonitor = DeviceEventMonitor(this) { activeApp, source, reason ->
            val now = System.currentTimeMillis()
            if (isRecentlyDistracted(now)) return@DeviceEventMonitor
            reactToActivity(activeApp, source, reason)
        }
        deviceEventMonitor.start()
        startTicking()
    }

    /** [PetSettingsStore.ACTION_CONFIG_UPDATED] handler — pushes a saved
     * Settings change into the already-running engine/brain session via
     * `PetBridge.updateConfig`, mirroring desktop's `apply_runtime_settings()`
     * "push on save" behavior (no service restart required). */
    private fun reloadConfig() {
        val configJson = PetSettingsStore.currentConfigJson(this)
        workerHandler.post {
            try {
                PetBridge.updateConfig(configJson)
            } catch (e: Exception) {
                Log.e(TAG, "PetBridge.updateConfig failed", e)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isRunning = false
        stopTicking()
        if (::deviceEventMonitor.isInitialized) {
            deviceEventMonitor.stop()
        }
        try {
            unregisterReceiver(screenReceiver)
        } catch (e: IllegalArgumentException) {
            // Not registered — fine.
        }
        if (::petView.isInitialized) {
            windowManager.removeView(petView)
        }
        if (::bubbleView.isInitialized) {
            windowManager.removeView(bubbleView)
        }
        workerHandler.post {
            try {
                PetBridge.shutdown()
            } catch (e: Exception) {
                Log.e(TAG, "PetBridge.shutdown failed", e)
            }
            workerThread.quitSafely()
        }
        super.onDestroy()
    }

    // ------------------------------------------------------------ overlay window
    private fun overlayWindowType(): Int = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
    } else {
        @Suppress("DEPRECATION")
        WindowManager.LayoutParams.TYPE_PHONE
    }

    private fun addOverlayView() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        petView = PetView(this, this)

        layoutParams = WindowManager.LayoutParams(
            PET_SIZE_PX,
            PET_SIZE_PX,
            overlayWindowType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 100
            y = 300
        }

        windowManager.addView(petView, layoutParams)
        addBubbleView()
    }

    /** Separate overlay window for [SpeechBubbleView] (docs/android_plan.md
     * §3 — a distinct window from the pet itself, matching desktop's own
     * `SpeechBubble` being a separate translucent Qt window). Added once
     * (empty/hidden) at startup and repositioned/shown via [showBubble] —
     * never torn down and recreated per-line. `FLAG_NOT_TOUCHABLE` (on top
     * of the pet window's own `FLAG_NOT_FOCUSABLE`) keeps it from ever
     * intercepting a touch meant for [petView] or the app underneath. */
    private fun addBubbleView() {
        bubbleView = SpeechBubbleView(this)
        bubbleParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            overlayWindowType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = clampBubbleX(layoutParams.x)
            y = (layoutParams.y - BUBBLE_Y_OFFSET_PX).coerceAtLeast(0)
        }
        windowManager.addView(bubbleView, bubbleParams)
    }

    /** Keeps the bubble window's left edge far enough from the right edge
     * of the screen that [SpeechBubbleView]'s wrapped text is never
     * clipped — a real bug caught only by an actual emulator run (the pet
     * window can end up near the screen edge, e.g. after being dragged;
     * the bubble tracks its x unconditionally otherwise). Only clamps X:
     * the bubble's height is small/bounded enough in practice that the Y
     * clamp already in place (`coerceAtLeast(0)`) is sufficient. */
    private fun clampBubbleX(petX: Int): Int {
        val maxX = (resources.displayMetrics.widthPixels - bubbleView.maxWidth).coerceAtLeast(0)
        return petX.coerceIn(0, maxX)
    }

    /** Shows `text` in the bubble window, repositioned just above the
     * pet's current window position. Safe to call from the main thread
     * only. */
    private fun showBubble(text: String) {
        if (!::bubbleView.isInitialized) return
        bubbleParams.x = clampBubbleX(layoutParams.x)
        bubbleParams.y = (layoutParams.y - BUBBLE_Y_OFFSET_PX).coerceAtLeast(0)
        windowManager.updateViewLayout(bubbleView, bubbleParams)
        bubbleView.show(text, uiHandler)
    }

    // ------------------------------------------------------------ PetView.Listener
    override fun onInteraction(kind: String) {
        workerHandler.post {
            try {
                PetBridge.onInteraction(kind)
            } catch (e: Exception) {
                Log.e(TAG, "onInteraction($kind) failed", e)
            }
        }
    }

    override fun onDragBy(dxPx: Int, dyPx: Int) {
        lastDragMs = System.currentTimeMillis()
        layoutParams.x += dxPx
        layoutParams.y += dyPx
        uiHandler.post {
            if (::petView.isInitialized) {
                windowManager.updateViewLayout(petView, layoutParams)
            }
            if (::bubbleView.isInitialized) {
                bubbleParams.x = clampBubbleX(layoutParams.x)
                bubbleParams.y = (layoutParams.y - BUBBLE_Y_OFFSET_PX).coerceAtLeast(0)
                windowManager.updateViewLayout(bubbleView, bubbleParams)
            }
        }
    }

    // ------------------------------------------------------------ engine tick loop
    private val tickRunnable = object : Runnable {
        override fun run() {
            val now = System.currentTimeMillis()
            lastTickMs = now
            workerHandler.post {
                try {
                    val snapshot = PetBridge.tick(now)
                    uiHandler.post {
                        if (::petView.isInitialized) {
                            petView.applyEngineSnapshot(
                                snapshot.emotion, snapshot.action, snapshot.sleeping,
                            )
                        }
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "tick failed", e)
                }
            }
            maybeCheckForegroundApp(now)
            maybeTriggerIdleComment(now)
            if (ticking) {
                uiHandler.postDelayed(this, TICK_INTERVAL_MS)
            }
        }
    }

    private fun startTicking() {
        if (ticking) return
        ticking = true
        uiHandler.post(tickRunnable)
    }

    private fun stopTicking() {
        ticking = false
        uiHandler.removeCallbacks(tickRunnable)
    }

    /**
     * Phase 4 (docs/android_plan.md §5.3/§7): opt-in `UsageStatsManager`
     * polling. No-ops entirely (including the [UsageMonitor.hasPermission]
     * check, cheap) if the user hasn't granted "Usage access" — there is
     * no separate app-level toggle, granting the special-access permission
     * IS the opt-in, mirroring how desktop's keystroke commentary opt-in
     * works via a single settings checkbox. Feeds real activity context
     * into `PetBridge.onActivity` — previously dead code, never called
     * from anywhere in the app.
     */
    private fun maybeCheckForegroundApp(now: Long) {
        if (now - lastForegroundCheckMs < FOREGROUND_CHECK_INTERVAL_MS) return
        lastForegroundCheckMs = now
        if (isRecentlyDistracted(now)) return
        workerHandler.post {
            try {
                if (!UsageMonitor.hasPermission(this)) return@post
                val pkg = UsageMonitor.currentForegroundPackage(this) ?: return@post
                if (pkg == packageName || pkg == lastForegroundPackage) return@post
                lastForegroundPackage = pkg
                val label = UsageMonitor.appLabel(this, pkg)
                reactToActivity(label, pkg, "app switch")
            } catch (e: Exception) {
                Log.e(TAG, "onActivity failed", e)
            }
        }
    }

    /**
     * Shared `PetBridge.onActivity` call site for both real app-switch
     * context ([maybeCheckForegroundApp]) and Android-only device events
     * ([deviceEventMonitor]) — must be called on [workerHandler].
     */
    private fun reactToActivity(activeApp: String, processName: String, reason: String) {
        try {
            Log.d(TAG, "reactToActivity: reason=\"$reason\" activeApp=\"$activeApp\"")
            val snapshot = PetBridge.onActivity(activeApp, null, processName, reason)
            uiHandler.post {
                if (::petView.isInitialized) {
                    petView.applyEngineSnapshot(snapshot.emotion, snapshot.action, snapshot.sleeping)
                }
                val text = snapshot.speech
                if (!text.isNullOrBlank()) showBubble(text)
            }
        } catch (e: Exception) {
            Log.e(TAG, "onActivity($reason) failed", e)
        }
    }

    /**
     * True for a short window after the pet was dragged or the screen was
     * just turned on — the mobile analogue of desktop's typing-suppression
     * (docs/android_plan.md §7 Phase 4: "suppress speech ... while pet was
     * recently dragged / screen just unlocked", since there's no mobile
     * equivalent of "user is actively typing"). Gates
     * [maybeCheckForegroundApp], [maybeTriggerIdleComment], and
     * [deviceEventMonitor]'s callback — but never the direct-touch
     * reactions in [onInteraction], which should always fire immediately.
     */
    private fun isRecentlyDistracted(now: Long): Boolean =
        now - lastDragMs < SUPPRESS_AFTER_DRAG_MS || now - lastScreenOnMs < SUPPRESS_AFTER_SCREEN_ON_MS

    /**
     * Periodic ambient chatter (the bridge equivalent of desktop's
     * `_trigger_idle_comment` QTimer) — previously `PetBridge.idleComment()`
     * was defined but never called from anywhere in the app, so the pet
     * never spoke unless something else triggered a reaction (nothing
     * did). Real pacing is enforced by the engine's own
     * `minimumSpeechCooldown` server-side; this local probability roll
     * (per [MessageFrequency], keyed off the Settings message-frequency
     * choice) just controls how often an attempt is even made.
     */
    private fun maybeTriggerIdleComment(now: Long) {
        if (now - lastIdleAttemptMs < IDLE_COMMENT_INTERVAL_MS) return
        lastIdleAttemptMs = now
        if (isRecentlyDistracted(now)) return
        val prob = MessageFrequency.idleProb(PetSettingsStore.load(this).messageFrequency)
        if (Random.nextDouble() > prob) return
        workerHandler.post {
            try {
                val snapshot = PetBridge.idleComment()
                val text = snapshot.speech
                if (!text.isNullOrBlank()) {
                    uiHandler.post { showBubble(text) }
                }
            } catch (e: Exception) {
                Log.e(TAG, "idleComment failed", e)
            }
        }
    }

    // ------------------------------------------------------------ notification
    private fun buildNotification(): Notification {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                getString(R.string.overlay_notification_channel_name),
                NotificationManager.IMPORTANCE_MIN,
            )
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }

        val openAppIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.overlay_notification_title))
            .setContentText(getString(R.string.overlay_notification_text))
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(openAppIntent)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val TAG = "OverlayService"
        private const val CHANNEL_ID = "squish_mate_overlay"
        private const val NOTIFICATION_ID = 1
        private val PET_SIZE_PX = PetView.VIEW_SIZE_PX.toInt()
        // Matches desktop's 2s QTimer engine-tick cadence (see
        // desktop_pet.py's _tick_engine / docs/android_plan.md §5.6).
        private const val TICK_INTERVAL_MS = 2_000L
        private const val BUBBLE_Y_OFFSET_PX = 150
        // How often an idle-comment ATTEMPT is made — not how often the
        // pet actually speaks (see maybeTriggerIdleComment's doc comment).
        private const val IDLE_COMMENT_INTERVAL_MS = 20_000L
        // Plan §5.3 recommends polling UsageStats every 3-5s; piggybacked
        // on the 2s tick loop's own cadence rather than a separate timer.
        private const val FOREGROUND_CHECK_INTERVAL_MS = 4_000L
        // Mobile equivalent of desktop's typing-suppression window — see
        // isRecentlyDistracted's doc comment.
        private const val SUPPRESS_AFTER_DRAG_MS = 5_000L
        private const val SUPPRESS_AFTER_SCREEN_ON_MS = 3_000L

        /** True while this service owns the `PetBridge` session (between
         * `onCreate`/`onDestroy`). `PetBridge`'s Python-side session is a
         * module-level singleton (see `core/bridge.py`), so exactly one
         * driver — this service's overlay window, or [MainActivity]'s
         * in-app fallback pet (docs/android_plan.md §5.1) — may tick it at
         * a time. [MainActivity] checks this before activating its
         * fallback view. Main-thread reads/writes only (both call sites
         * are on the UI thread). */
        var isRunning: Boolean = false
    }
}
