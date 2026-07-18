// Adapted from llama.cpp's examples/llama.android/lib/src/main/cpp/logging.h
// (upstream ggml-org/llama.cpp, Apache-2.0) — see docs/android_plan.md §5.4
// item 3 for why this file exists here (on-device LLM inference).
#pragma once
#include <android/log.h>

#ifndef LOG_TAG
#define LOG_TAG "squishmate-llm"
#endif

#ifndef LOG_MIN_LEVEL
#if defined(NDEBUG)
#define LOG_MIN_LEVEL ANDROID_LOG_INFO
#else
#define LOG_MIN_LEVEL ANDROID_LOG_VERBOSE
#endif
#endif

// __android_log_is_loggable() would be the "proper" way to gate on the
// device's actual logcat tag-priority setting, but it's API 30+ only and
// this app's minSdk is 26 (see ndk.abiFilters' comment in build.gradle.kts
// for why 26 is the floor) — always attempt the log call instead; logcat
// itself still filters by priority/tag on the consuming end, and the
// LOG_MIN_LEVEL macro guards below already compile out LOGv/LOGd entirely
// in release (NDEBUG) builds.
static inline int sm_should_log(int /*prio*/) {
    return 1;
}

#if LOG_MIN_LEVEL <= ANDROID_LOG_VERBOSE
#define LOGv(...) do { if (sm_should_log(ANDROID_LOG_VERBOSE)) __android_log_print(ANDROID_LOG_VERBOSE, LOG_TAG, __VA_ARGS__); } while (0)
#else
#define LOGv(...) ((void)0)
#endif

#if LOG_MIN_LEVEL <= ANDROID_LOG_DEBUG
#define LOGd(...) do { if (sm_should_log(ANDROID_LOG_DEBUG)) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__); } while (0)
#else
#define LOGd(...) ((void)0)
#endif

#define LOGi(...)   do { if (sm_should_log(ANDROID_LOG_INFO )) __android_log_print(ANDROID_LOG_INFO , LOG_TAG, __VA_ARGS__); } while (0)
#define LOGw(...)   do { if (sm_should_log(ANDROID_LOG_WARN )) __android_log_print(ANDROID_LOG_WARN , LOG_TAG, __VA_ARGS__); } while (0)
#define LOGe(...)   do { if (sm_should_log(ANDROID_LOG_ERROR)) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__); } while (0)

static inline int android_log_prio_from_ggml(enum ggml_log_level level) {
    switch (level) {
        case GGML_LOG_LEVEL_ERROR: return ANDROID_LOG_ERROR;
        case GGML_LOG_LEVEL_WARN:  return ANDROID_LOG_WARN;
        case GGML_LOG_LEVEL_INFO:  return ANDROID_LOG_INFO;
        case GGML_LOG_LEVEL_DEBUG: return ANDROID_LOG_DEBUG;
        default:                   return ANDROID_LOG_DEFAULT;
    }
}

static inline void squishmate_llm_log_callback(enum ggml_log_level level,
                                                const char* text,
                                                void* /*user*/) {
    const int prio = android_log_prio_from_ggml(level);
    if (!sm_should_log(prio)) return;
    __android_log_write(prio, LOG_TAG, text);
}
