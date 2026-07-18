plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.preludeofme.squishmate"
    // TYPE_APPLICATION_OVERLAY (the floating-pet window type) requires
    // API 26+ — see docs/android_plan.md §5.7.
    compileSdk = 34

    // Needed for the on-device llama.cpp JNI build below (CMakeLists.txt
    // targets a recent NDK for the GGML CPU backend variants). Installed
    // via `sdkmanager "ndk;27.3.13750724"`.
    ndkVersion = "27.3.13750724"

    defaultConfig {
        applicationId = "com.preludeofme.squishmate"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-dev"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // arm64-v8a only (was arm64-v8a + armeabi-v7a): the on-device
            // LLM feature added below only targets arm64-v8a (a 2B+
            // parameter model is impractical on 32-bit ARM's constrained
            // address space/RAM anyway), and dropping 32-bit ARM support
            // app-wide avoids having to special-case Chaquopy's own ABI
            // packaging per-library. 32-bit-only Android devices are rare
            // at this point; the base overlay pet was never the reason
            // armeabi-v7a was included (see the Phase 1 comment this
            // replaces) — it was just "cast a wide net" during early
            // development.
            abiFilters += listOf("arm64-v8a")
        }

        // On-device LLM (docs/android_plan.md §5.4 item 3 — the "gemma4"
        // provider): where to find the vendored llama.cpp source tree for
        // the native build below. Deliberately NOT inside this repo (a C++
        // codebase this size doesn't belong in git history, and nesting it
        // under android/ risks the same Gradle input/output-overlap problem
        // `core/pyproject.toml`'s own comment already documents for
        // Chaquopy) — lives alongside the (also not-repo-tracked) model
        // weights. Override with `-PllamaSrcDir=/path/to/llama.cpp` if
        // it's vendored somewhere else.
        val llamaSrcDir = (project.findProperty("llamaSrcDir") as String?)
            ?: "/home/trubuck-design/models/llama.cpp-src"
        externalNativeBuild {
            cmake {
                arguments += "-DLLAMA_SRC_DIR=$llamaSrcDir"
                arguments += "-DCMAKE_BUILD_TYPE=Release"
                arguments += "-DBUILD_SHARED_LIBS=ON"
                arguments += "-DLLAMA_BUILD_COMMON=ON"
                arguments += "-DLLAMA_BUILD_EXAMPLES=OFF"
                arguments += "-DLLAMA_BUILD_TESTS=OFF"
                arguments += "-DLLAMA_BUILD_TOOLS=OFF"
                arguments += "-DLLAMA_BUILD_SERVER=OFF"
                arguments += "-DGGML_NATIVE=OFF"
                arguments += "-DGGML_BACKEND_DL=ON"
                arguments += "-DGGML_CPU_ALL_VARIANTS=ON"
                arguments += "-DGGML_LLAMAFILE=OFF"
            }
        }
    }

    externalNativeBuild {
        cmake {
            path("src/main/cpp/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    buildTypes {
        release {
            // Phase 5 APK-size check (docs/android_plan.md §7/§10): R8
            // shrinking of the Kotlin/Java side. Safe by default here
            // because nothing in this app is called reflectively — Python
            // only ever receives calls FROM Kotlin (PetBridge -> core.bridge),
            // never the reverse, so there are no Kotlin classes Python
            // needs to find by name/reflection that R8 could rename/strip.
            // See proguard-rules.pro for the one Chaquopy-specific note.
            // Does NOT shrink Chaquopy's own payload (Python interpreter +
            // stdlib + core/), which is the dominant contributor to APK
            // size for this app — that's tracked separately per §4 item 4.
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            // TEMPORARY, Phase 5 testing only: reuses the debug keystore so
            // this variant is installable on a dev device/emulator to
            // sanity-check R8 didn't break anything at runtime. MUST be
            // replaced with a real release signing config (see
            // docs/android_plan.md §7 Phase 5 "GitHub release APK") before
            // any build leaves this machine.
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        viewBinding = true
    }
}

chaquopy {
    defaultConfig {
        // Mirrors ui/pet_settings.py's provider deps: only `requests` is
        // needed by the embedded core (see squish-mate/pyproject.toml).
        pip {
            // Local-path dev wiring: pulls the `core` package straight
            // from the parent desktop repo's core/ directory (this
            // Android app lives at squish-mate/android/;
            // core/pyproject.toml is deliberately scoped to core/ only —
            // see the comment there — so Gradle's build-output tree
            // under android/app/build never overlaps with the installed
            // source dir). Both apps share one source of truth while
            // Android support is under active development (see
            // docs/android_plan.md §4 item 4/§6). Before a public
            // release, switch this to a pinned tag, e.g.
            //   install("squish-mate-core @ git+https://github.com/preludeofme/squish-mate.git@vX.Y.Z")
            install("../../core")
        }
    }
    sourceSets {
        getByName("main") {
            srcDir("src/main/python")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-service:2.8.4")
    // Android Keystore-backed EncryptedSharedPreferences for the Settings
    // screen's stored LLM API key (docs/android_plan.md §5.5 — "never
    // written to pet_config.json on-disk in plain text on device").
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    // NOTE: on-device LLM inference does NOT use a Gradle dependency —
    // gemma-4-E2B-it-qat-q4_0-gguf ships as a GGUF file (llama.cpp's
    // format), not MediaPipe's .task/LiteRT format, so there's no
    // off-the-shelf artifact here. Instead `src/main/cpp/` builds
    // llama.cpp from vendored source via CMake/NDK — see
    // `src/main/cpp/CMakeLists.txt` and `llm/OnDeviceEngine.kt`.
    testImplementation("junit:junit:4.13.2")
    // Plain-JVM org.json (NOT the Android SDK stub, which throws in unit
    // tests) — used only by PetAnimatorGoldenTest to read the golden
    // fixture. See docs/android_plan.md §8 "Animator golden tests".
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
