package com.preludeofme.squishmate.settings

import android.content.Intent
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import com.preludeofme.squishmate.R
import com.preludeofme.squishmate.databinding.ActivitySettingsBinding

/**
 * Settings screen (docs/android_plan.md Phase 3 "Brain wiring" — settings
 * UI + hosted-LLM key entry). Reads/writes [PetSettingsStore] and, on save,
 * broadcasts [PetSettingsStore.ACTION_CONFIG_UPDATED] so a running
 * `OverlayService` picks the new config up immediately via
 * `PetBridge.updateConfig` instead of requiring a restart — matching
 * desktop's `apply_runtime_settings()` "push on save" pattern.
 *
 * Deliberately plain Views + ViewBinding (matching [com.preludeofme.squishmate.MainActivity]'s
 * existing style) rather than introducing Jetpack Compose for a single
 * form screen — the plan's §6 layout suggested Compose, but adding a new
 * UI toolkit for one screen isn't worth the dependency/build-time cost
 * this early.
 */
class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding

    private val frequencyIds by lazy { resources.getStringArray(R.array.message_frequency_ids) }
    private val providerIds by lazy { resources.getStringArray(R.array.llm_provider_ids) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        title = getString(R.string.settings_title)

        binding.messageFrequencySpinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item,
            resources.getStringArray(R.array.message_frequency_labels),
        )
        binding.providerSpinner.adapter = ArrayAdapter(
            this, android.R.layout.simple_spinner_dropdown_item,
            resources.getStringArray(R.array.llm_provider_labels),
        )

        val settings = PetSettingsStore.load(this)
        binding.nameInput.setText(settings.name)
        binding.traitsInput.setText(settings.personalityTraits)
        binding.initialPromptInput.setText(settings.initialPrompt)
        binding.systemPromptInput.setText(settings.systemPrompt)
        binding.apiKeyInput.setText(settings.llmApiKey)
        binding.modelOverrideInput.setText(settings.llmModelOverride)
        binding.baseUrlInput.setText(settings.llmBaseUrl)
        binding.messageFrequencySpinner.setSelection(
            frequencyIds.indexOf(settings.messageFrequency).coerceAtLeast(0),
        )
        binding.providerSpinner.setSelection(
            providerIds.indexOf(settings.llmProvider).coerceAtLeast(0),
        )

        binding.saveButton.setOnClickListener { save() }
    }

    private fun save() {
        val newSettings = PetSettingsStore.PetSettings(
            name = binding.nameInput.text.toString().trim().ifBlank { "Pip" },
            personalityTraits = binding.traitsInput.text.toString(),
            initialPrompt = binding.initialPromptInput.text.toString(),
            messageFrequency = frequencyIds.getOrElse(binding.messageFrequencySpinner.selectedItemPosition) { "normal" },
            systemPrompt = binding.systemPromptInput.text.toString(),
            llmProvider = providerIds.getOrElse(binding.providerSpinner.selectedItemPosition) { "ollama" },
            llmApiKey = binding.apiKeyInput.text.toString(),
            llmModelOverride = binding.modelOverrideInput.text.toString().trim(),
            llmBaseUrl = binding.baseUrlInput.text.toString().trim(),
        )
        PetSettingsStore.save(this, newSettings)
        sendBroadcast(Intent(PetSettingsStore.ACTION_CONFIG_UPDATED))
        Toast.makeText(this, R.string.settings_saved, Toast.LENGTH_SHORT).show()
        finish()
    }
}
