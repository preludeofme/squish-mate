# Phase 5 (docs/android_plan.md §7 "APK size check") release-shrinking
# rules. No app code needs explicit `-keep` rules here: nothing in this app
# is invoked reflectively — Python only ever receives calls FROM Kotlin
# (PetBridge -> core.bridge), never the other way, so R8 renaming/stripping
# unused Kotlin/Java classes can't break the bridge; likewise JSON is
# hand-parsed via org.json (no reflection-based (de)serializer to keep).
#
# androidx.security:security-crypto (used for the Settings screen's
# EncryptedSharedPreferences) pulls in Google Tink, which references two
# optional `javax.annotation.*` compile-time-only annotations that aren't
# on the classpath at runtime either way — a known, harmless R8 warning
# (not specific to this app). Suppressed per R8's own generated
# missing_rules.txt rather than adding a fake dependency just to satisfy it.
-dontwarn javax.annotation.Nullable
-dontwarn javax.annotation.concurrent.GuardedBy
