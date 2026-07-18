package com.preludeofme.squishmate.monitor

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import androidx.core.content.ContextCompat

/**
 * Android-only context sources with no desktop equivalent (docs/android_plan.md
 * §5.3/§7 Phase 4: "battery low", "charger plugged/unplugged", "headphones").
 * Unlike [UsageMonitor] (poll-based, gated behind a special-access
 * permission the user must explicitly grant), this needs no permission at
 * all — battery/power/headset broadcasts are ordinary system broadcasts any
 * app can listen to — so it's always-on for the lifetime of the overlay/
 * in-app session, the same posture as `OverlayService`'s own
 * `SCREEN_ON`/`SCREEN_OFF` receiver.
 *
 * Only reports on real state TRANSITIONS (crossing into "low", plugging in,
 * unplugging headphones), never on every raw `ACTION_BATTERY_CHANGED` tick
 * (which fires very frequently, e.g. on trivial percent changes) — otherwise
 * this would spam `PetBridge.onActivity` far more often than a real desktop
 * activity change ever would.
 */
class DeviceEventMonitor(
    private val context: Context,
    /** `source` is a stable per-kind id (e.g. "device.battery_low") so the
     * engine's meaningful-change detector — which keys off event source —
     * treats each distinct device event as its own topic rather than
     * collapsing them together. */
    private val onEvent: (activeApp: String, source: String, reason: String) -> Unit,
) {
    private var lastLowBattery = false
    private var lastCharging: Boolean? = null
    private var registered = false

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(receiverContext: Context, intent: Intent) {
            handle(intent)
        }
    }

    fun start() {
        if (registered) return
        registered = true
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_BATTERY_CHANGED)
            addAction(Intent.ACTION_POWER_CONNECTED)
            addAction(Intent.ACTION_POWER_DISCONNECTED)
            addAction(Intent.ACTION_HEADSET_PLUG)
        }
        // ACTION_BATTERY_CHANGED is sticky — registering for it also
        // returns the current battery state immediately. Priming from that
        // (instead of treating it as a live event) avoids firing a
        // spurious "just crossed the threshold" comment purely from
        // service startup.
        val sticky = ContextCompat.registerReceiver(
            context, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED,
        )
        sticky?.let {
            lastLowBattery = isLow(it)
            lastCharging = isCharging(it)
        }
    }

    fun stop() {
        if (!registered) return
        registered = false
        try {
            context.unregisterReceiver(receiver)
        } catch (e: IllegalArgumentException) {
            // Not registered — fine.
        }
    }

    private fun handle(intent: Intent) {
        when (intent.action) {
            Intent.ACTION_POWER_CONNECTED -> {
                if (lastCharging != true) {
                    lastCharging = true
                    onEvent("Phone plugged in to charge", "device.charger_connected", "charger connected")
                }
            }
            Intent.ACTION_POWER_DISCONNECTED -> {
                if (lastCharging != false) {
                    lastCharging = false
                    onEvent("Phone unplugged from charger", "device.charger_disconnected", "charger disconnected")
                }
            }
            Intent.ACTION_HEADSET_PLUG -> {
                val plugged = intent.getIntExtra("state", -1) == 1
                if (plugged) {
                    onEvent("Headphones plugged in", "device.headphones_connected", "headphones connected")
                } else {
                    onEvent("Headphones unplugged", "device.headphones_disconnected", "headphones disconnected")
                }
            }
            Intent.ACTION_BATTERY_CHANGED -> {
                // Deliberately does NOT touch `lastCharging` here — a real
                // device/emulator test caught this as a race: BATTERY_CHANGED
                // (sticky, re-delivered on every minor state change) can
                // arrive before or interleaved with the explicit
                // POWER_CONNECTED/POWER_DISCONNECTED broadcasts, and used to
                // silently overwrite `lastCharging` first, making the
                // POWER_DISCONNECTED case below think the transition had
                // already been reported and skip firing the event entirely.
                // POWER_CONNECTED/DISCONNECTED are the sole source of truth
                // for charging transitions; this branch only tracks the
                // (unrelated) low-battery threshold.
                val low = isLow(intent)
                if (low && !lastLowBattery) {
                    val level = levelPercent(intent)
                    onEvent("Phone battery low ($level%)", "device.battery_low", "battery low")
                }
                lastLowBattery = low
            }
        }
    }

    private fun levelPercent(intent: Intent): Int {
        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
        if (level < 0 || scale <= 0) return -1
        return (level * 100) / scale
    }

    private fun isLow(intent: Intent): Boolean {
        val pct = levelPercent(intent)
        return pct in 0..LOW_BATTERY_THRESHOLD_PCT
    }

    private fun isCharging(intent: Intent): Boolean {
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        return status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
    }

    companion object {
        private const val LOW_BATTERY_THRESHOLD_PCT = 20
    }
}
