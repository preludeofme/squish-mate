// On-device LLM inference JNI bridge (docs/android_plan.md §5.4 item 3).
// Adapted from llama.cpp's own examples/llama.android/lib/src/main/cpp/ai_chat.cpp
// (upstream ggml-org/llama.cpp, Apache-2.0) — the prompt/decode/sampling
// mechanics below are that reference's proven logic, simplified to a single
// stateless `generate()` call (reset + reprocess system+user prompt fresh
// every time) instead of a persistent multi-turn chat session, to match how
// every other provider in this app already works: `core/pet_brain.py`
// sends a complete system+user message pair per call with no server-side
// conversation state (see PetBrain._chat()) — so there is no "conversation"
// to keep incremental KV-cache state for here either.
#include <android/log.h>
#include <jni.h>
#include <cmath>
#include <sstream>
#include <string>
#include <unistd.h>
#include <sampling.h>

#include "logging.h"
#include "chat.h"
#include "common.h"
#include "llama.h"

constexpr int   N_THREADS_MIN        = 2;
constexpr int   N_THREADS_MAX        = 6;
constexpr int   N_THREADS_HEADROOM   = 2;
constexpr int   DEFAULT_CONTEXT_SIZE = 8192;
constexpr int   OVERFLOW_HEADROOM    = 4;
constexpr int   BATCH_SIZE           = 512;
constexpr float DEFAULT_SAMPLER_TEMP = 0.7f; // matches PetBrain's hosted-provider default temperature

static llama_model             * g_model    = nullptr;
static llama_context            * g_context  = nullptr;
static llama_batch                g_batch;
static common_chat_templates_ptr  g_chat_templates;
static common_sampler            * g_sampler = nullptr;

extern "C"
JNIEXPORT void JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeInit(JNIEnv *env, jobject, jstring nativeLibDir) {
    llama_log_set(squishmate_llm_log_callback, nullptr);
    const auto *path = env->GetStringUTFChars(nativeLibDir, nullptr);
    LOGi("Loading GGML CPU backend variants from %s", path);
    ggml_backend_load_all_from_path(path);
    env->ReleaseStringUTFChars(nativeLibDir, path);
    llama_backend_init();
    LOGi("llama backend initialized");
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeLoadModel(JNIEnv *env, jobject, jstring jModelPath) {
    llama_model_params model_params = llama_model_default_params();
    const auto *model_path = env->GetStringUTFChars(jModelPath, nullptr);
    LOGi("%s: loading model from %s", __func__, model_path);
    auto *model = llama_model_load_from_file(model_path, model_params);
    env->ReleaseStringUTFChars(jModelPath, model_path);
    if (!model) {
        LOGe("%s: llama_model_load_from_file() returned null", __func__);
        return 1;
    }
    g_model = model;
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativePrepare(JNIEnv *, jobject) {
    if (!g_model) {
        LOGe("%s: no model loaded", __func__);
        return 1;
    }

    const int n_threads = std::max(N_THREADS_MIN, std::min(N_THREADS_MAX,
        (int) sysconf(_SC_NPROCESSORS_ONLN) - N_THREADS_HEADROOM));
    LOGi("%s: using %d threads", __func__, n_threads);

    llama_context_params ctx_params = llama_context_default_params();
    ctx_params.n_ctx = DEFAULT_CONTEXT_SIZE;
    ctx_params.n_batch = BATCH_SIZE;
    ctx_params.n_ubatch = BATCH_SIZE;
    ctx_params.n_threads = n_threads;
    ctx_params.n_threads_batch = n_threads;

    auto *context = llama_init_from_model(g_model, ctx_params);
    if (!context) {
        LOGe("%s: llama_init_from_model() returned null", __func__);
        return 1;
    }
    g_context = context;
    g_batch = llama_batch_init(BATCH_SIZE, 0, 1);
    g_chat_templates = common_chat_templates_init(g_model, "");

    common_params_sampling sparams;
    sparams.temp = DEFAULT_SAMPLER_TEMP;
    g_sampler = common_sampler_init(g_model, sparams);
    return 0;
}

static int decode_in_batches(const llama_tokens &tokens, llama_pos start_pos, bool want_last_logit) {
    for (size_t i = 0; i < tokens.size(); i += BATCH_SIZE) {
        const size_t cur = std::min(tokens.size() - i, (size_t) BATCH_SIZE);
        common_batch_clear(g_batch);
        for (size_t j = 0; j < cur; j++) {
            const bool logit = want_last_logit && (i + j == tokens.size() - 1);
            common_batch_add(g_batch, tokens[i + j], start_pos + (llama_pos) (i + j), {0}, logit);
        }
        if (llama_decode(g_context, g_batch) != 0) {
            LOGe("%s: llama_decode() failed", __func__);
            return 1;
        }
    }
    return 0;
}

static bool is_valid_utf8(const std::string &s) {
    const auto *bytes = (const unsigned char *) s.c_str();
    int num;
    while (*bytes != 0x00) {
        if ((*bytes & 0x80) == 0x00) num = 1;
        else if ((*bytes & 0xE0) == 0xC0) num = 2;
        else if ((*bytes & 0xF0) == 0xE0) num = 3;
        else if ((*bytes & 0xF8) == 0xF0) num = 4;
        else return false;
        bytes += 1;
        for (int i = 1; i < num; ++i) {
            if ((*bytes & 0xC0) != 0x80) return false;
            bytes += 1;
        }
    }
    return true;
}

// Stateless single-turn generation: reset the KV cache, format+decode a
// fresh system+user turn via the model's own chat template, then sample
// until EOG or maxTokens. Returns "" (with the failure logged) rather than
// throwing across the JNI boundary — matches every other provider's
// contract in this app (`_speak_or_fallback` in core/bridge.py treats an
// empty/failed result as "fall back to a canned line", never a hard error).
extern "C"
JNIEXPORT jstring JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeGenerate(
        JNIEnv *env, jobject,
        jstring jSystemPrompt, jstring jUserPrompt, jint maxTokens) {
    if (!g_model || !g_context || !g_sampler) {
        LOGe("%s: engine not ready (model/context/sampler missing)", __func__);
        return env->NewStringUTF("");
    }

    llama_memory_clear(llama_get_memory(g_context), false);
    common_sampler_reset(g_sampler);

    const auto *sys_chars = env->GetStringUTFChars(jSystemPrompt, nullptr);
    const auto *usr_chars = env->GetStringUTFChars(jUserPrompt, nullptr);
    std::string system_prompt(sys_chars);
    std::string user_prompt(usr_chars);
    env->ReleaseStringUTFChars(jSystemPrompt, sys_chars);
    env->ReleaseStringUTFChars(jUserPrompt, usr_chars);

    std::vector<common_chat_msg> chat_msgs;
    const bool has_template = common_chat_templates_was_explicit(g_chat_templates.get());

    common_chat_msg sys_msg;
    sys_msg.role = "system";
    sys_msg.content = system_prompt;
    std::string formatted_system = has_template
        ? common_chat_format_single(g_chat_templates.get(), chat_msgs, sys_msg, false, false)
        : system_prompt;
    chat_msgs.push_back(sys_msg);

    common_chat_msg usr_msg;
    usr_msg.role = "user";
    usr_msg.content = user_prompt;
    std::string formatted_user = has_template
        ? common_chat_format_single(g_chat_templates.get(), chat_msgs, usr_msg, true, false)
        : ("\n" + user_prompt + "\n");
    chat_msgs.push_back(usr_msg);

    const int max_ctx = DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM;
    auto system_tokens = common_tokenize(g_context, formatted_system, has_template, has_template);
    auto user_tokens = common_tokenize(g_context, formatted_user, false, has_template);

    if ((int) system_tokens.size() >= max_ctx) {
        LOGe("%s: system prompt alone (%d tokens) doesn't fit context (%d)",
             __func__, (int) system_tokens.size(), max_ctx);
        return env->NewStringUTF("");
    }
    llama_pos pos = 0;
    if (decode_in_batches(system_tokens, pos, false) != 0) {
        return env->NewStringUTF("");
    }
    pos += (llama_pos) system_tokens.size();

    if ((int) (pos + (llama_pos) user_tokens.size()) >= max_ctx) {
        const int max_user = max_ctx - pos;
        LOGw("%s: user prompt too long, truncating to %d tokens", __func__, max_user);
        user_tokens.resize(std::max(0, max_user));
    }
    if (decode_in_batches(user_tokens, pos, true) != 0) {
        return env->NewStringUTF("");
    }
    pos += (llama_pos) user_tokens.size();

    const llama_pos stop_pos = pos + maxTokens;
    std::string cached_chars;
    std::ostringstream result;

    while (pos < stop_pos && pos < max_ctx) {
        const auto new_token = common_sampler_sample(g_sampler, g_context, -1);
        common_sampler_accept(g_sampler, new_token, true);

        if (llama_vocab_is_eog(llama_model_get_vocab(g_model), new_token)) {
            LOGd("%s: EOG at position %d", __func__, pos);
            break;
        }

        cached_chars += common_token_to_piece(g_context, new_token);
        if (is_valid_utf8(cached_chars)) {
            result << cached_chars;
            cached_chars.clear();
        }

        common_batch_clear(g_batch);
        common_batch_add(g_batch, new_token, pos, {0}, true);
        if (llama_decode(g_context, g_batch) != 0) {
            LOGe("%s: llama_decode() failed for generated token", __func__);
            break;
        }
        pos++;
    }

    const std::string text = result.str();
    LOGi("%s: generated %d chars", __func__, (int) text.size());
    return env->NewStringUTF(text.c_str());
}

extern "C"
JNIEXPORT void JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeUnload(JNIEnv *, jobject) {
    if (g_sampler) { common_sampler_free(g_sampler); g_sampler = nullptr; }
    g_chat_templates.reset();
    if (g_context) { llama_free(g_context); g_context = nullptr; }
    llama_batch_free(g_batch);
    if (g_model) { llama_model_free(g_model); g_model = nullptr; }
}

extern "C"
JNIEXPORT void JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeShutdown(JNIEnv *, jobject) {
    llama_backend_free();
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_preludeofme_squishmate_llm_OnDeviceEngine_nativeSystemInfo(JNIEnv *env, jobject) {
    return env->NewStringUTF(llama_print_system_info());
}
