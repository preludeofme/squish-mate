package com.preludeofme.squishmate

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.provider.Settings
import android.util.Log
import android.view.View
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.preludeofme.squishmate.bridge.PetBridge
import com.preludeofme.squishmate.databinding.ActivityMainBinding
import com.preludeofme.squishmate.llm.OnDeviceEngine
import com.preludeofme.squishmate.monitor.UsageMonitor
import com.preludeofme.squishmate.overlay.OverlayService
import com.preludeofme.squishmate.overlay.PetView
import com.preludeofme.squishmate.settings.MessageFrequency
import com.preludeofme.squishmate.settings.PetSettingsStore
import com.preludeofme.squishmate.settings.SettingsActivity
import kotlin.random.Random

/**
 * Onboarding + fallback host Activity (see docs/android_plan.md §5.1). If
 * the user denies (or simply never grants) the overlay permission, Pip is
 * still fully usable via the "Use Pip in-app instead" toggle below, which
 * embeds the exact same [PetView] (Phase 2 renderer/animator) as a normal
 * child view instead of a floating [OverlayService] window — this closes
 * the Phase-1 gap noted in `handoff.md`/`active-context.md` ("no in-app
 * fallback pet view for denied overlay permission").
 *
 * Mutual exclusivity: `core/bridge.py`'s session is a module-level
 * singleton (one Python interpreter per process), so only ONE driver may
 * own/tick it at a time. [OverlayService.isRunning] is checked before
 * activating the in-app pet, and the overlay start button is disabled
 * while the in-app pet is active (and vice versa) — see [refreshPermissionState].
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var serviceRunning = false

    private var petView: PetView? = null
    private var workerThread: HandlerThread? = null
    private var workerHandler: Handler? = null
    private val uiHandler = Handler(Looper.getMainLooper())
    private var inAppPetActive = false
    private var lastIdleAttemptMs = 0L

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* no-op either way */ }

    private val inAppPetListener = object : PetView.Listener {
        override fun onInteraction(kind: String) {
            workerHandler?.post {
                try {
                    PetBridge.onInteraction(kind)
                } catch (e: Exception) {
                    Log.e(TAG, "in-app onInteraction($kind) failed", e)
                }
            }
        }

        override fun onDragBy(dxPx: Int, dyPx: Int) {
            // No separate window to move for the in-app embed — PetView's
            // own squash/drag pose already reacts visually on its own.
        }
    }

    private val inAppTickRunnable = object : Runnable {
        override fun run() {
            val now = System.currentTimeMillis()
            workerHandler?.post {
                try {
                    val snapshot = PetBridge.tick(now)
                    uiHandler.post {
                        petView?.applyEngineSnapshot(snapshot.emotion, snapshot.action, snapshot.sleeping)
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "in-app tick failed", e)
                }
            }
            maybeTriggerIdleComment(now)
            if (inAppPetActive) {
                uiHandler.postDelayed(this, TICK_INTERVAL_MS)
            }
        }
    }

    /** Same ambient-chatter pattern as `OverlayService.maybeTriggerIdleComment`
     * — the in-app fallback pet previously never spoke either, since
     * `PetBridge.idleComment()` was dead code everywhere in the app. */
    private fun maybeTriggerIdleComment(now: Long) {
        if (now - lastIdleAttemptMs < IDLE_COMMENT_INTERVAL_MS) return
        lastIdleAttemptMs = now
        val prob = MessageFrequency.idleProb(PetSettingsStore.load(this).messageFrequency)
        if (Random.nextDouble() > prob) return
        workerHandler?.post {
            try {
                val snapshot = PetBridge.idleComment()
                val text = snapshot.speech
                if (!text.isNullOrBlank()) {
                    uiHandler.post { binding.inAppBubble.show(text, uiHandler) }
                }
            } catch (e: Exception) {
                Log.e(TAG, "in-app idleComment failed", e)
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.grantOverlayButton.setOnClickListener { requestOverlayPermission() }
        binding.toggleServiceButton.setOnClickListener { toggleService() }
        binding.openSettingsButton.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        binding.inAppPetButton.setOnClickListener { toggleInAppPet() }
        binding.usageAccessButton.setOnClickListener {
            startActivity(UsageMonitor.permissionSettingsIntent())
        }

        maybeRequestNotificationPermission()
    }

    override fun onResume() {
        super.onResume()
        refreshPermissionState()
        refreshUsageAccessState()
    }

    override fun onDestroy() {
        if (inAppPetActive) {
            teardownInAppPet()
        }
        super.onDestroy()
    }

    private fun refreshPermissionState() {
        val hasOverlay = Settings.canDrawOverlays(this)
        binding.grantOverlayButton.isEnabled = !hasOverlay
        binding.toggleServiceButton.isEnabled = hasOverlay && !inAppPetActive
        binding.inAppPetButton.isEnabled = !serviceRunning
        binding.statusText.text = if (hasOverlay) {
            getString(R.string.start_pet)
        } else {
            getString(R.string.grant_overlay_permission_body)
        }
    }

    private fun requestOverlayPermission() {
        val intent = Intent(
            Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
            Uri.parse("package:$packageName"),
        )
        startActivity(intent)
    }

    private fun maybeRequestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    private fun toggleService() {
        if (!Settings.canDrawOverlays(this)) {
            refreshPermissionState()
            return
        }
        val intent = Intent(this, OverlayService::class.java)
        if (serviceRunning) {
            stopService(intent)
            binding.toggleServiceButton.text = getString(R.string.start_pet)
        } else {
            ContextCompat.startForegroundService(this, intent)
            binding.toggleServiceButton.text = getString(R.string.stop_pet)
        }
        serviceRunning = !serviceRunning
        refreshPermissionState()
    }

    // ------------------------------------------------------------ in-app fallback pet
    private fun toggleInAppPet() {
        if (inAppPetActive) {
            teardownInAppPet()
            refreshPermissionState()
            return
        }
        if (OverlayService.isRunning) {
            Toast.makeText(this, R.string.in_app_pet_blocked_by_overlay, Toast.LENGTH_SHORT).show()
            return
        }
        setupInAppPet()
        refreshPermissionState()
    }

    private fun setupInAppPet() {
        val view = PetView(this, inAppPetListener)
        petView = view
        val sizePx = PetView.VIEW_SIZE_PX.toInt()
        binding.petContainer.removeAllViews()
        binding.petContainer.addView(view, FrameLayout.LayoutParams(sizePx, sizePx))
        binding.petContainer.visibility = View.VISIBLE
        binding.inAppPetButton.text = getString(R.string.hide_in_app_pet)
        inAppPetActive = true

        val thread = HandlerThread("squish-mate-inapp-bridge-worker").apply { start() }
        workerThread = thread
        workerHandler = Handler(thread.looper)
        val configJson = PetSettingsStore.currentConfigJson(this)
        workerHandler?.post {
            try {
                PetBridge.init(filesDir.absolutePath, configJson)
            } catch (e: Exception) {
                Log.e(TAG, "in-app PetBridge.init failed", e)
            }
            ensureOnDeviceModelState(PetSettingsStore.load(this).llmProvider)
        }
        uiHandler.post(inAppTickRunnable)
    }

    /** Same on-device-model load/unload logic as `OverlayService`'s own
     * copy — see its doc comment. Duplicated rather than shared because
     * this Activity and that Service already duplicate the rest of their
     * bridge-driving logic (tick loop, idle comment) for the same reason:
     * they're mutually exclusive drivers of a single `PetBridge` session,
     * not variations of a shared component. */
    private fun ensureOnDeviceModelState(provider: String) {
        val engine = OnDeviceEngine.getInstance(this)
        if (provider == "ondevice") {
            if (engine.isModelLoaded) return
            val modelFile = OnDeviceEngine.modelFile(this)
            if (engine.loadModel(modelFile.absolutePath)) {
                PetBridge.setOnDeviceGenerator(engine)
            } else {
                Log.e(TAG, "On-device model failed to load from ${modelFile.absolutePath}")
            }
        } else if (engine.isModelLoaded) {
            PetBridge.setOnDeviceGenerator(null)
            engine.unload()
        }
    }

    /** Stops ticking + shuts down the shared bridge session; safe to call
     * from [onDestroy] (skips further UI mutation there via the
     * `isFinishing`-agnostic guards already in place — no view access
     * beyond what's already torn down by the framework). */
    private fun teardownInAppPet() {
        inAppPetActive = false
        uiHandler.removeCallbacks(inAppTickRunnable)
        workerHandler?.post {
            try {
                PetBridge.shutdown()
            } catch (e: Exception) {
                Log.e(TAG, "in-app PetBridge.shutdown failed", e)
            }
            OnDeviceEngine.getInstance(this).unload()
        }
        workerThread?.quitSafely()
        workerThread = null
        workerHandler = null
        petView = null
        if (!isFinishing) {
            binding.petContainer.removeAllViews()
            binding.petContainer.visibility = View.GONE
            binding.inAppBubble.hide(uiHandler)
            binding.inAppPetButton.text = getString(R.string.use_pet_in_app)
        }
    }

    // ------------------------------------------------------------ Phase 4: usage access opt-in
    private fun refreshUsageAccessState() {
        val granted = UsageMonitor.hasPermission(this)
        binding.usageAccessButton.isEnabled = !granted
        binding.usageAccessButton.text = if (granted) {
            getString(R.string.usage_access_enabled)
        } else {
            getString(R.string.enable_usage_access)
        }
    }

    companion object {
        private const val TAG = "MainActivity"
        private const val TICK_INTERVAL_MS = 2_000L
        private const val IDLE_COMMENT_INTERVAL_MS = 20_000L
    }
}
