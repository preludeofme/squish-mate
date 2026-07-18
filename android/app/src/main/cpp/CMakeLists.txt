cmake_minimum_required(VERSION 3.22.1)

project("squishmate-llm" VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED true)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED true)

# On-device LLM inference (docs/android_plan.md §5.4 item 3). Builds
# llama.cpp from a vendored source tree — NOT checked into this repo (a C++
# codebase this size doesn't belong in git history; see the comment on
# `llamaSrcDir` in ../../../build.gradle.kts) — against
# gemma-4-E2B-it-qat-q4_0-gguf (Ryan's chosen model: same "E2B" tier as the
# desktop app's smallest Ollama tier, GGUF format, so llama.cpp rather than
# MediaPipe/LiteRT is the right runtime here).
if(NOT DEFINED LLAMA_SRC_DIR)
    message(FATAL_ERROR
        "LLAMA_SRC_DIR not set. Pass -DLLAMA_SRC_DIR=/path/to/llama.cpp "
        "(configured via the llamaSrcDir Gradle property in build.gradle.kts).")
endif()
if(NOT EXISTS "${LLAMA_SRC_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "LLAMA_SRC_DIR (${LLAMA_SRC_DIR}) doesn't look like a llama.cpp checkout.")
endif()

# arm64-v8a only — see the ndk.abiFilters comment in build.gradle.kts for
# why 32-bit ARM was dropped app-wide for this feature.
if(DEFINED ANDROID_ABI AND NOT ANDROID_ABI STREQUAL "arm64-v8a")
    message(FATAL_ERROR "squishmate-llm only supports arm64-v8a, got: ${ANDROID_ABI}")
endif()
set(GGML_CPU_KLEIDIAI ON)
set(GGML_OPENMP ON)

add_subdirectory(${LLAMA_SRC_DIR} build-llama)

add_library(${CMAKE_PROJECT_NAME} SHARED
        llm_bridge.cpp)

target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
        ${LLAMA_SRC_DIR}
        ${LLAMA_SRC_DIR}/common
        ${LLAMA_SRC_DIR}/include
        ${LLAMA_SRC_DIR}/ggml/include
        ${LLAMA_SRC_DIR}/ggml/src)

target_link_libraries(${CMAKE_PROJECT_NAME}
        llama
        llama-common
        android
        log)
