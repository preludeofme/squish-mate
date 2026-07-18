# Phase 5 (docs/android_plan.md §7 "APK size check") release-shrinking
# rules. Most of this app needs no explicit `-keep` rules: Python only
# receives calls FROM Kotlin (PetBridge -> core.bridge), never the other
# way, so R8 renaming/stripping unused Kotlin/Java classes can't break that
# direction of the bridge; likewise JSON is hand-parsed via org.json (no
# reflection-based (de)serializer to keep).
#
# EXCEPTION, and the reason this comment no longer says "nothing is
# reflective": the on-device LLM provider (docs/android_plan.md §5.4 item
# 3) reverses that direction — `core/bridge.py.set_ondevice_generator`
# calls `generator.generate(...)` on a Kotlin `OnDeviceEngine` instance
# FROM Python via Chaquopy. R8 cannot see that call site (it only exists in
# Python bytecode), and a real release build confirmed the danger:
# `OnDeviceEngine.generate()` (and its `nativeGenerate` native method) were
# silently dead-code-eliminated before this rule was added — verified via
# `dexdump` on the built APK, not just assumed. `native <methods>`
# themselves are already covered by AGP's default
# `proguard-android-optimize.txt` (keeps native method names unchanged —
# also verified via dexdump: `nativeInit`/`nativeLoadModel`/etc. all kept
# their exact names), but that doesn't stop the whole originating Kotlin
# method from being eliminated as apparently-unreachable, which takes the
# native call with it.
-keep class com.preludeofme.squishmate.llm.OnDeviceEngine {
    public *;
}
#
# androidx.security:security-crypto (used for the Settings screen's
# EncryptedSharedPreferences) pulls in Google Tink, which references two
# optional `javax.annotation.*` compile-time-only annotations that aren't
# on the classpath at runtime either way — a known, harmless R8 warning
# (not specific to this app). Suppressed per R8's own generated
# missing_rules.txt rather than adding a fake dependency just to satisfy it.
-dontwarn javax.annotation.Nullable
-dontwarn javax.annotation.concurrent.GuardedBy
