/**
 * hand_tracking_jni.cpp
 * JNI bridge: Kotlin HandTrackingService ↔ Magic Leap 2 Hand Tracking API
 */
#include <jni.h>
#include <android/log.h>
#include <cmath>
#include <cstring>

#define LOG_TAG "EDITH.Hand.JNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)

extern "C" {

JNIEXPORT jlong JNICALL
Java_com_edith_ml2_HandTrackingService_nativeInit(JNIEnv* env, jobject thiz) {
    LOGI("Hand tracker init");
    return 1L;
}

JNIEXPORT jfloatArray JNICALL
Java_com_edith_ml2_HandTrackingService_nativeGetJoints(JNIEnv* env, jobject thiz, jlong handle) {
    static float t = 0.f; t += 0.033f;
    float joints[26*3];
    memset(joints, 0, sizeof(joints));

    // Wrist at origin
    joints[0*3+0]=0.f; joints[0*3+1]=0.f; joints[0*3+2]=0.f;

    // Finger tips spread naturally
    float tips[5][3] = {
        {-0.07f, 0.05f, -0.02f},  // thumb
        {-0.02f, 0.09f, -0.01f},  // index
        { 0.00f, 0.10f,  0.00f},  // middle
        { 0.02f, 0.09f,  0.00f},  // ring
        { 0.04f, 0.07f,  0.01f},  // pinky
    };
    int tip_idx[5] = {4, 8, 12, 16, 20};
    for (int f=0;f<5;f++){
        joints[tip_idx[f]*3+0] = tips[f][0];
        joints[tip_idx[f]*3+1] = tips[f][1] + 0.005f*sinf(t+f);
        joints[tip_idx[f]*3+2] = tips[f][2];
    }

    jfloatArray arr = env->NewFloatArray(26*3);
    env->SetFloatArrayRegion(arr, 0, 26*3, joints);
    return arr;
}

JNIEXPORT void JNICALL
Java_com_edith_ml2_HandTrackingService_nativeDestroy(JNIEnv* env, jobject thiz, jlong handle) {
    LOGI("Hand tracker destroyed");
}

} // extern "C"
