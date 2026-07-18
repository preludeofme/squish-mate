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

    defaultConfig {
        applicationId = "com.preludeofme.squishmate"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-dev"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            // Chaquopy needs an explicit ABI list; keep it to the two
            // ABIs that cover the overwhelming majority of real devices
            // to hold down APK size during early development (see the
            // Phase 5 "APK size check" exit criterion in the plan).
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
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
    testImplementation("junit:junit:4.13.2")
    // Plain-JVM org.json (NOT the Android SDK stub, which throws in unit
    // tests) — used only by PetAnimatorGoldenTest to read the golden
    // fixture. See docs/android_plan.md §8 "Animator golden tests".
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.6.1")
}
