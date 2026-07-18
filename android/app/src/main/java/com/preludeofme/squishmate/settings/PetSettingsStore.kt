package com.preludeofme.squishmate.settings

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import org.json.JSONObject

/**
 * Persists the app-level pet config (see docs/android_plan.md §5.5 and
 * `core/bridge.py`'s `DEFAULT_PET_CONFIG`) and turns it into the JSON shape
 * `PetBridge.init`/`updateConfig` expect. Backed by
 * [EncryptedSharedPreferences] (Android Keystore) rather than plain
 * `SharedPreferences` specifically because `llmApiKey` lives in here too —
 * per the plan: "API keys ... never written to `pet_config.json` on-disk in
 * plain text on device." Everything else (name/traits/prompt/frequency)
 * rides along in the same encrypted file for simplicity; there's no
 * sensitive-vs-not split worth the extra file.
 */
object PetSettingsStore {

    data class PetSettings(
        val name: String = "Pip",
        val personalityTraits: String = "",
        val initialPrompt: String = "",
        val messageFrequency: String = "normal",
        val systemPrompt: String = "",
        val llmProvider: String = "ollama",
        val llmApiKey: String = "",
        val llmModelOverride: String = "",
        val llmBaseUrl: String = "",
    )

    private const val PREFS_FILE = "squish_mate_settings_secure"

    private const val KEY_NAME = "name"
    private const val KEY_TRAITS = "personality_traits"
    private const val KEY_INITIAL_PROMPT = "initial_prompt"
    private const val KEY_MESSAGE_FREQUENCY = "message_frequency"
    private const val KEY_SYSTEM_PROMPT = "system_prompt"
    private const val KEY_LLM_PROVIDER = "llm_provider"
    private const val KEY_LLM_API_KEY = "llm_api_key"
    private const val KEY_LLM_MODEL_OVERRIDE = "llm_model_override"
    private const val KEY_LLM_BASE_URL = "llm_base_url"

    /** Broadcast when [save] is called, so a running [OverlayService] can
     * live-reload via `PetBridge.updateConfig` without restarting. */
    const val ACTION_CONFIG_UPDATED = "com.preludeofme.squishmate.ACTION_CONFIG_UPDATED"

    private fun prefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            PREFS_FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun load(context: Context): PetSettings {
        val p = prefs(context)
        val defaults = PetSettings()
        return PetSettings(
            name = p.getString(KEY_NAME, defaults.name) ?: defaults.name,
            personalityTraits = p.getString(KEY_TRAITS, defaults.personalityTraits) ?: defaults.personalityTraits,
            initialPrompt = p.getString(KEY_INITIAL_PROMPT, defaults.initialPrompt) ?: defaults.initialPrompt,
            messageFrequency = p.getString(KEY_MESSAGE_FREQUENCY, defaults.messageFrequency) ?: defaults.messageFrequency,
            systemPrompt = p.getString(KEY_SYSTEM_PROMPT, defaults.systemPrompt) ?: defaults.systemPrompt,
            llmProvider = p.getString(KEY_LLM_PROVIDER, defaults.llmProvider) ?: defaults.llmProvider,
            llmApiKey = p.getString(KEY_LLM_API_KEY, defaults.llmApiKey) ?: defaults.llmApiKey,
            llmModelOverride = p.getString(KEY_LLM_MODEL_OVERRIDE, defaults.llmModelOverride) ?: defaults.llmModelOverride,
            llmBaseUrl = p.getString(KEY_LLM_BASE_URL, defaults.llmBaseUrl) ?: defaults.llmBaseUrl,
        )
    }

    fun save(context: Context, settings: PetSettings) {
        prefs(context).edit()
            .putString(KEY_NAME, settings.name)
            .putString(KEY_TRAITS, settings.personalityTraits)
            .putString(KEY_INITIAL_PROMPT, settings.initialPrompt)
            .putString(KEY_MESSAGE_FREQUENCY, settings.messageFrequency)
            .putString(KEY_SYSTEM_PROMPT, settings.systemPrompt)
            .putString(KEY_LLM_PROVIDER, settings.llmProvider)
            .putString(KEY_LLM_API_KEY, settings.llmApiKey)
            .putString(KEY_LLM_MODEL_OVERRIDE, settings.llmModelOverride)
            .putString(KEY_LLM_BASE_URL, settings.llmBaseUrl)
            .apply()
    }

    /** JSON shape matching `core/bridge.py`'s `DEFAULT_PET_CONFIG` —
     * consumed directly by `PetBridge.init`/`updateConfig`. */
    fun toConfigJson(settings: PetSettings): String {
        val traits = JSONArray()
        settings.personalityTraits.split(",")
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .forEach { traits.put(it) }

        return JSONObject().apply {
            put("name", settings.name.ifBlank { "Pip" })
            put("personality_traits", traits)
            put("initial_prompt", settings.initialPrompt)
            put("message_frequency", settings.messageFrequency)
            put("llm_provider", settings.llmProvider)
            put("llm_api_key", settings.llmApiKey)
            put("llm_model_override", settings.llmModelOverride)
            put("llm_base_url", settings.llmBaseUrl)
            put("system_prompt", settings.systemPrompt)
        }.toString()
    }

    fun currentConfigJson(context: Context): String = toConfigJson(load(context))
}
