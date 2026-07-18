package com.preludeofme.squishmate.llm

import android.content.Context
import android.util.Log
import java.io.File

/**
 * JNI wrapper around llama.cpp for fully offline, on-device LLM inference
 * (docs/android_plan.md §5.4 item 3 — the "ondevice" provider). Runs
 * Ryan's chosen model, `gemma-4-E2B-it-qat-q4_0-gguf`
 * (https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf) — the same
 * "E2B" tier as the desktop app's smallest Ollama tier
 * (`core/pet_performance.py`'s `"model": "gemma4:e2b"`), just in GGUF form
 * on-device instead of served by Ollama.
 *
 * Deliberately synchronous/blocking (no coroutines/Flow) — matches every
 * other provider's contract (`core/llm_providers.py`'s hosted HTTP calls
 * are blocking `requests.post` calls too) and this app's existing
 * threading convention: every caller here already runs on
 * `OverlayService`/`MainActivity`'s dedicated single-threaded
 * `workerHandler` (the same thread all `PetBridge` calls run on), so a
 * second concurrency model isn't needed. Model loading and generation are
 * both genuinely slow (seconds), so callers MUST NOT call this from the
 * main thread.
 *
 * Single global instance, mirroring `core/bridge.py`'s module-level
 * session and llama.cpp's own global model/context state in
 * `llm_bridge.cpp` (this class owns exactly one loaded model at a time —
 * there is only ever one pet, so this is intentional, not a limitation).
 */
class OnDeviceEngine private constructor(nativeLibDir: String) {

    @Volatile
    var isModelLoaded: Boolean = false
        private set

    private external fun nativeInit(nativeLibDir: String)
    private external fun nativeLoadModel(modelPath: String): Int
    private external fun nativePrepare(): Int
    private external fun nativeGenerate(systemPrompt: String, userPrompt: String, maxTokens: Int): String
    private external fun nativeUnload()
    private external fun nativeShutdown()
    private external fun nativeSystemInfo(): String

    init {
        System.loadLibrary("squishmate-llm")
        nativeInit(nativeLibDir)
        Log.i(TAG, "llama.cpp initialized: ${nativeSystemInfo()}")
    }

    /**
     * Loads `modelPath` (an absolute path to a local `.gguf` file — never
     * bundled in the APK, see `docs/android_plan.md` §5.4 item 3) and
     * prepares a context for generation. Returns false (logged, never
     * throws) on any failure — an unsupported architecture, a corrupt/
     * missing file, or insufficient RAM to allocate the context are all
     * realistic failure modes on real devices and must degrade to "on-device
     * provider unavailable," never crash the pet.
     */
    @Synchronized
    fun loadModel(modelPath: String): Boolean {
        val file = File(modelPath)
        if (!file.isFile || !file.canRead()) {
            Log.e(TAG, "Model file not found or unreadable: $modelPath")
            return false
        }
        return try {
            if (nativeLoadModel(modelPath) != 0) {
                Log.e(TAG, "nativeLoadModel failed for $modelPath")
                return false
            }
            if (nativePrepare() != 0) {
                Log.e(TAG, "nativePrepare failed")
                return false
            }
            isModelLoaded = true
            Log.i(TAG, "Model loaded: $modelPath")
            true
        } catch (e: Exception) {
            Log.e(TAG, "loadModel threw", e)
            false
        }
    }

    /**
     * Generates a reply for one system+user prompt pair. Stateless per
     * call (see `llm_bridge.cpp`'s doc comment) — matches
     * `core/pet_brain.py`'s existing per-call contract for every other
     * provider. Returns null (never throws) on failure/empty output so
     * callers can fall back the same way they already do for a hosted
     * provider being unreachable.
     */
    @Synchronized
    fun generate(systemPrompt: String, userPrompt: String, maxTokens: Int): String? {
        if (!isModelLoaded) {
            Log.e(TAG, "generate() called before a model was loaded")
            return null
        }
        return try {
            val text = nativeGenerate(systemPrompt, userPrompt, maxTokens).trim()
            text.ifEmpty { null }
        } catch (e: Exception) {
            Log.e(TAG, "generate threw", e)
            null
        }
    }

    @Synchronized
    fun unload() {
        if (!isModelLoaded) return
        try {
            nativeUnload()
        } catch (e: Exception) {
            Log.e(TAG, "unload threw", e)
        } finally {
            isModelLoaded = false
        }
    }

    companion object {
        private const val TAG = "OnDeviceEngine"

        /**
         * Expected filename for Ryan's chosen model
         * (https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf) —
         * NOT bundled in the APK (multi-GB, see docs/android_plan.md §5.4
         * item 3); pushed manually into app-private storage for now via
         * `adb push <file> /data/local/tmp/ && adb shell run-as
         * com.preludeofme.squishmate cp /data/local/tmp/<file>
         * files/models/`, or copied in by a future in-app model picker/
         * downloader (not built yet — out of scope until this path is
         * proven to work end-to-end on a real device).
         */
        const val MODEL_FILENAME = "gemma-4-E2B_q4_0-it.gguf"

        fun modelFile(context: Context): File =
            File(File(context.filesDir, "models"), MODEL_FILENAME)

        @Volatile
        private var instance: OnDeviceEngine? = null

        fun getInstance(context: Context): OnDeviceEngine =
            instance ?: synchronized(this) {
                instance ?: OnDeviceEngine(context.applicationInfo.nativeLibraryDir).also { instance = it }
            }
    }
}
