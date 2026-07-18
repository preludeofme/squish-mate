package com.preludeofme.squishmate.monitor

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Process
import android.provider.Settings

/**
 * Android's shallower equivalent of desktop's `advanced_monitor.py`
 * window-title polling (docs/android_plan.md §5.3): `UsageStatsManager`
 * only exposes the foreground **package**, no window titles. Resolves the
 * package's display label via [PackageManager] and hands both to
 * `PetBridge.onActivity` (`active_app` = label, `process_name` = package
 * id, `window_title` omitted) — exactly the "reduced context" shape the
 * plan calls for.
 *
 * Opt-in by construction: `PACKAGE_USAGE_STATS` is a special access the
 * user must grant via [ACTION_USAGE_ACCESS_SETTINGS], not a runtime
 * permission dialog — [hasPermission] must be checked before every call,
 * there is no persistent "granted" callback.
 */
object UsageMonitor {

    fun hasPermission(context: Context): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.packageName,
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun permissionSettingsIntent(): Intent = Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS)

    /**
     * Best-effort foreground package over the last [windowMs] of usage
     * events. Returns null if permission isn't granted or no
     * foreground-change event was recorded in the window (e.g. the same
     * app has simply stayed foregrounded). Blocking (queries the OS usage
     * events database) — call off the main thread, same contract as
     * [com.preludeofme.squishmate.bridge.PetBridge].
     */
    @Suppress("DEPRECATION") // MOVE_TO_FOREGROUND deprecated in favor of
    // ACTIVITY_RESUMED (API 29+); minSdk is 26, so the older constant is
    // kept intentionally rather than raising the floor for this alone.
    fun currentForegroundPackage(context: Context, windowMs: Long = 10_000L): String? {
        if (!hasPermission(context)) return null
        val manager = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val end = System.currentTimeMillis()
        val events = manager.queryEvents(end - windowMs, end)
        val event = UsageEvents.Event()
        var lastForeground: String? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                lastForeground = event.packageName
            }
        }
        return lastForeground
    }

    fun appLabel(context: Context, packageName: String): String {
        return try {
            val pm = context.packageManager
            val info = pm.getApplicationInfo(packageName, 0)
            pm.getApplicationLabel(info).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName
        }
    }
}
