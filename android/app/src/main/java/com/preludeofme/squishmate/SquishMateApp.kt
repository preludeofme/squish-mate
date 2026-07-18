package com.preludeofme.squishmate

import android.app.Application
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * Starts the embedded Python interpreter once, application-wide. Chaquopy
 * requires exactly one [Python.start] call before any [Python.getInstance]
 * use — doing it here (rather than lazily in [com.preludeofme.squishmate.bridge.PetBridge])
 * keeps startup ordering simple for both the overlay service and the
 * in-app fallback Activity, which can both need Python independently.
 */
class SquishMateApp : Application() {
    override fun onCreate() {
        super.onCreate()
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(this))
        }
    }
}
