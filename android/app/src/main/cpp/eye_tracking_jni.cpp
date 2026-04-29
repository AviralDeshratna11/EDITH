/**
 * eye_tracking_jni.cpp
 * JNI bridge: Kotlin EyeTrackingService ↔ Magic Leap 2 Eye Tracking API
 *
 * ML2 SDK: MLEyeTracking* APIs
 * Returns gaze data at ~90fps to the Kotlin service.
 */
#include <jni.h>
#include <android/log.h>
#include <cmath>
#include <chrono>
#include <cstring>
#include <dlfcn.h>

#define LOG_TAG "EDITH.Eye.JNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// ── ML2 SDK includes (uncomment when SDK installed) ────────────
#if __has_include(<ml_eye_tracking.h>) && __has_include(<ml_perception.h>) && __has_include(<ml_snapshot.h>)
#include <ml_eye_tracking.h>
#include <ml_perception.h>
#include <ml_snapshot.h>
#define EDITH_HAS_MLSDK 1
#else
#define EDITH_HAS_MLSDK 0
#endif

#if EDITH_HAS_MLSDK
struct MLApi {
    void* lib = nullptr;

    MLResult (*PerceptionInitSettings)(MLPerceptionSettings*) = nullptr;
    MLResult (*PerceptionStartup)(MLPerceptionSettings*) = nullptr;
    MLResult (*PerceptionShutdown)() = nullptr;
    MLResult (*PerceptionGetSnapshot)(MLSnapshot**) = nullptr;
    MLResult (*PerceptionReleaseSnapshot)(MLSnapshot*) = nullptr;

    MLResult (*EyeTrackingCreate)(MLHandle*) = nullptr;
    MLResult (*EyeTrackingDestroy)(MLHandle) = nullptr;
    MLResult (*EyeTrackingGetStaticData)(MLHandle, MLEyeTrackingStaticData*) = nullptr;
    MLResult (*EyeTrackingGetStateEx)(MLHandle, MLEyeTrackingStateEx*) = nullptr;

    MLResult (*SnapshotGetStaticData)(MLSnapshotStaticData*) = nullptr;
    MLResult (*SnapshotGetPoseInBase)(const MLSnapshot*, const MLCoordinateFrameUID*, const MLCoordinateFrameUID*, MLPose*) = nullptr;
};

static bool loadMlApi(MLApi* api) {
    if (!api) return false;
    api->lib = dlopen("libperception.magicleap.so", RTLD_NOW | RTLD_LOCAL);
    if (!api->lib) {
        api->lib = dlopen("perception.magicleap", RTLD_NOW | RTLD_LOCAL);
    }
    if (!api->lib) {
        LOGE("Failed to load perception runtime library via dlopen");
        return false;
    }

#define LOAD_SYM(field, name) \
    api->field = reinterpret_cast<decltype(api->field)>(dlsym(api->lib, name)); \
    if (!api->field) { LOGE("Missing ML symbol: %s", name); return false; }

    LOAD_SYM(PerceptionInitSettings, "MLPerceptionInitSettings");
    LOAD_SYM(PerceptionStartup, "MLPerceptionStartup");
    LOAD_SYM(PerceptionShutdown, "MLPerceptionShutdown");
    LOAD_SYM(PerceptionGetSnapshot, "MLPerceptionGetSnapshot");
    LOAD_SYM(PerceptionReleaseSnapshot, "MLPerceptionReleaseSnapshot");

    LOAD_SYM(EyeTrackingCreate, "MLEyeTrackingCreate");
    LOAD_SYM(EyeTrackingDestroy, "MLEyeTrackingDestroy");
    LOAD_SYM(EyeTrackingGetStaticData, "MLEyeTrackingGetStaticData");
    LOAD_SYM(EyeTrackingGetStateEx, "MLEyeTrackingGetStateEx");

    LOAD_SYM(SnapshotGetStaticData, "MLSnapshotGetStaticData");
    LOAD_SYM(SnapshotGetPoseInBase, "MLSnapshotGetPoseInBase");

#undef LOAD_SYM
    return true;
}

static void unloadMlApi(MLApi* api) {
    if (api && api->lib) {
        dlclose(api->lib);
        api->lib = nullptr;
    }
}
#endif

// ── Stub tracker state ─────────────────────────────────────────
struct EyeTracker {
    float normX = 0.5f, normY = 0.5f;
    float dirX  = 0.f,  dirY  = 0.f, dirZ = -1.f;
    float pupil = 0.4f;
    bool  fixating = false;
    bool  isNew    = false;
    float durationSec = 0.f;
#if EDITH_HAS_MLSDK
    MLApi api{};
    bool perceptionReady = false;
    bool staticReady = false;
    MLHandle mlHandle = ML_INVALID_HANDLE;
    MLEyeTrackingStaticData eyeStatic{};
    MLSnapshotStaticData snapshotStatic{};
#endif
    float lastNormX = 0.5f;
    float lastNormY = 0.5f;
    uint64_t lastMs = 0;
};

static inline uint64_t nowMs() {
    using namespace std::chrono;
    return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
}

static inline float clamp01(float v) {
    return v < 0.f ? 0.f : (v > 1.f ? 1.f : v);
}

#if EDITH_HAS_MLSDK
static MLVec3f rotateVec(const MLQuaternionf& q, const MLVec3f& v) {
    // Quaternion-vector rotation: v' = 2 dot(u,v) u + (s^2 - dot(u,u)) v + 2s (u x v)
    MLVec3f u{q.x, q.y, q.z};
    const float s = q.w;
    const float uv = u.x * v.x + u.y * v.y + u.z * v.z;
    const float uu = u.x * u.x + u.y * u.y + u.z * u.z;
    MLVec3f cross{
        u.y * v.z - u.z * v.y,
        u.z * v.x - u.x * v.z,
        u.x * v.y - u.y * v.x,
    };
    MLVec3f out{};
    out.x = 2.f * uv * u.x + (s * s - uu) * v.x + 2.f * s * cross.x;
    out.y = 2.f * uv * u.y + (s * s - uu) * v.y + 2.f * s * cross.y;
    out.z = 2.f * uv * u.z + (s * s - uu) * v.z + 2.f * s * cross.z;
    return out;
}

static void normalize(MLVec3f* v) {
    const float mag = std::sqrt(v->x * v->x + v->y * v->y + v->z * v->z);
    if (mag > 1e-6f) {
        v->x /= mag;
        v->y /= mag;
        v->z /= mag;
    }
}
#endif

extern "C" {

/**
 * Called from Kotlin: EyeTrackingService.nativeInit()
 * Returns a pointer to our tracker struct cast to jlong.
 */
JNIEXPORT jlong JNICALL
Java_com_edith_ml2_EyeTrackingService_nativeInit(JNIEnv* env, jobject thiz) {
    LOGI("Initialising ML2 eye tracker");

    auto* tracker = new EyeTracker();
#if EDITH_HAS_MLSDK
    if (!loadMlApi(&tracker->api)) {
        LOGE("ML runtime symbols unavailable; falling back to stub mode");
    }

    MLPerceptionSettings settings{};
    MLResult result = MLResult_UnspecifiedFailure;
    if (tracker->api.PerceptionInitSettings) {
        result = tracker->api.PerceptionInitSettings(&settings);
    }
    if (result == MLResult_Ok) {
        result = tracker->api.PerceptionStartup(&settings);
    }
    if (result == MLResult_Ok) {
        tracker->perceptionReady = true;
    } else {
        LOGE("MLPerception startup failed: %d", result);
    }

    if (tracker->perceptionReady) {
        result = tracker->api.EyeTrackingCreate(&tracker->mlHandle);
        if (result != MLResult_Ok) {
            LOGE("MLEyeTrackingCreate failed: %d", result);
            tracker->mlHandle = ML_INVALID_HANDLE;
        }
    }

    if (tracker->mlHandle != ML_INVALID_HANDLE) {
        result = tracker->api.EyeTrackingGetStaticData(tracker->mlHandle, &tracker->eyeStatic);
        if (result == MLResult_Ok) {
            MLSnapshotStaticDataInit(&tracker->snapshotStatic);
            if (tracker->api.SnapshotGetStaticData(&tracker->snapshotStatic) == MLResult_Ok) {
                tracker->staticReady = true;
            }
        }
        LOGI("Eye tracker initialised (MLSDK) at %p handle=%lu", tracker, tracker->mlHandle);
    } else {
        LOGI("Eye tracker fallback to stub mode at %p", tracker);
    }
#else
    LOGI("Eye tracker (stub) initialised at %p", tracker);
#endif
    return reinterpret_cast<jlong>(tracker);
}

/**
 * Called from Kotlin at ~90fps.
 * Returns float[10]: [normX, normY, dirX, dirY, dirZ, pupil, fixating, isNew, durationSec, confidence]
 */
JNIEXPORT jfloatArray JNICALL
Java_com_edith_ml2_EyeTrackingService_nativeGetGaze(JNIEnv* env, jobject thiz, jlong handle) {
    auto* t = reinterpret_cast<EyeTracker*>(handle);
    if (!t) return nullptr;

    bool haveRealGaze = false;
#if EDITH_HAS_MLSDK
    if (t->mlHandle != ML_INVALID_HANDLE && t->staticReady) {
        MLEyeTrackingStateEx state{};
        MLEyeTrackingStateInit(&state);
        MLResult st = t->api.EyeTrackingGetStateEx(t->mlHandle, &state);
        if (st == MLResult_Ok) {
            MLSnapshot* snapshot = nullptr;
            MLResult sr = t->api.PerceptionGetSnapshot(&snapshot);
            if (sr == MLResult_Ok && snapshot != nullptr) {
                MLPose leftPose{};
                MLResult pr = t->api.SnapshotGetPoseInBase(
                    snapshot,
                    &t->snapshotStatic.coord_world_origin,
                    &t->eyeStatic.left_center,
                    &leftPose
                );

                if (pr == MLResult_Ok && state.left_center_confidence > 0.2f) {
                    MLVec3f fwdLocal{0.f, 0.f, -1.f};
                    MLVec3f fwdWorld = rotateVec(leftPose.transform.rotation, fwdLocal);
                    normalize(&fwdWorld);

                    t->dirX = fwdWorld.x;
                    t->dirY = fwdWorld.y;
                    t->dirZ = fwdWorld.z;
                    t->normX = clamp01(0.5f + 0.5f * t->dirX);
                    t->normY = clamp01(0.5f - 0.5f * t->dirY);
                    t->pupil = 0.5f * (state.left_eye_openness + state.right_eye_openness);
                    t->fixating = state.left_center_confidence > 0.6f && !state.left_blink && !state.right_blink;
                    haveRealGaze = true;
                }
                t->api.PerceptionReleaseSnapshot(snapshot);
            }
        }
    }
#endif

    if (!haveRealGaze) {
        // Stub fallback: keep cursor stable in center rather than random movement.
        t->normX = 0.5f;
        t->normY = 0.5f;
        t->dirX = 0.f;
        t->dirY = 0.f;
        t->dirZ = -1.f;
        t->pupil = 0.4f;
        t->fixating = false;
    }

    const uint64_t now = nowMs();
    const float dx = std::fabs(t->normX - t->lastNormX);
    const float dy = std::fabs(t->normY - t->lastNormY);
    const bool moved = (dx + dy) > 0.03f;
    if (moved || t->lastMs == 0) {
        t->isNew = true;
        t->durationSec = 0.f;
    } else if (t->lastMs > 0) {
        t->durationSec += (now - t->lastMs) / 1000.f;
        t->isNew = false;
    }
    t->lastNormX = t->normX;
    t->lastNormY = t->normY;
    t->lastMs = now;

    float data[10] = {
        t->normX, t->normY,
        t->dirX, t->dirY, t->dirZ,
        t->pupil,
        t->fixating ? 1.f : 0.f,
        t->isNew    ? 1.f : 0.f,
        t->durationSec,
        0.92f   // confidence
    };
    t->isNew = false;

    jfloatArray arr = env->NewFloatArray(10);
    env->SetFloatArrayRegion(arr, 0, 10, data);
    return arr;
}

JNIEXPORT void JNICALL
Java_com_edith_ml2_EyeTrackingService_nativeDestroy(JNIEnv* env, jobject thiz, jlong handle) {
    auto* t = reinterpret_cast<EyeTracker*>(handle);
    if (!t) return;
#if EDITH_HAS_MLSDK
    if (t->mlHandle != ML_INVALID_HANDLE) {
        t->api.EyeTrackingDestroy(t->mlHandle);
    }
    if (t->perceptionReady) {
        t->api.PerceptionShutdown();
    }
    unloadMlApi(&t->api);
#endif
    delete t;
    LOGI("Eye tracker destroyed");
}

} // extern "C"
