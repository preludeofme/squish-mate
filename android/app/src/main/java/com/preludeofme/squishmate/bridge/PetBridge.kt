package com.preludeofme.squishmate.bridge

import com.chaquo.python.PyObject
import com.chaquo.python.Python
import org.json.JSONArray
import org.json.JSONObject

/**
 * Kotlin-side wrapper around `core/bridge.py` (see docs/android_plan.md
 * §3 "Bridge API"). This is the ONLY place in the app that talks to
 * Python — every other Kotlin class talks to [PetBridge], never to
 * [Python] directly, so the JSON contract stays centralized in one file.
 *
 * All functions here are blocking (`think()`/hosted-LLM calls do real
 * network I/O) — callers MUST invoke this from a background thread, never
 * from the main/UI thread. [com.preludeofme.squishmate.overlay.OverlayService]
 * owns a dedicated worker thread for this.
 */
object PetBridge {

    data class Snapshot(
        val speech: String?,
        val emotion: String,
        val action: String,
        val sleeping: Boolean,
        val energy: Double,
    )

    private val module: PyObject by lazy {
        Python.getInstance().getModule("core.bridge")
    }

    private fun snapshotFrom(json: String): Snapshot {
        val obj = JSONObject(json)
        return Snapshot(
            speech = if (obj.isNull("speech")) null else obj.getString("speech"),
            emotion = obj.getString("emotion"),
            action = obj.getString("action"),
            sleeping = obj.getBoolean("sleeping"),
            energy = obj.getDouble("energy"),
        )
    }

    /**
     * `storageDir` must be app-private (e.g. `context.filesDir.absolutePath`)
     * — never a shared/external directory. `configJson` mirrors desktop
     * `pet_config.json`'s general settings; see `core/bridge.py`'s
     * `DEFAULT_PET_CONFIG` for the accepted keys.
     */
    fun init(storageDir: String, configJson: String) {
        module.callAttr("init", storageDir, configJson)
    }

    fun updateConfig(configJson: String) {
        module.callAttr("update_config", configJson)
    }

    fun tick(nowMs: Long): Snapshot =
        snapshotFrom(module.callAttr("tick", nowMs).toString())

    fun onActivity(activeApp: String, windowTitle: String?, processName: String?, reason: String): Snapshot {
        val payload = JSONObject().apply {
            put("active_app", activeApp)
            put("window_title", windowTitle ?: JSONObject.NULL)
            put("process_name", processName ?: JSONObject.NULL)
            put("reason", reason)
            put("recent_apps", JSONArray())
        }
        return snapshotFrom(module.callAttr("on_activity", payload.toString()).toString())
    }

    /** `kind` is one of "tap" | "drag" | "fling" | "longpress". */
    fun onInteraction(kind: String): Snapshot =
        snapshotFrom(module.callAttr("on_interaction", kind).toString())

    fun idleComment(): Snapshot =
        snapshotFrom(module.callAttr("idle_comment").toString())

    fun getState(): String = module.callAttr("get_state").toString()

    fun shutdown() {
        module.callAttr("shutdown")
    }
}
