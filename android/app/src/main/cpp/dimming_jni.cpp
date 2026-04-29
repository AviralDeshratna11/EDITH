/**
 * dimming_jni.cpp
 * JNI bridge for ML2 Segmented Dimming API.
 */
#include <jni.h>
#include <android/log.h>

#define LOG_TAG "EDITH.Dimming.JNI"
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)

extern "C" {

JNIEXPORT void JNICALL
Java_com_edith_ml2_DimmingService_nativeEnable(JNIEnv* env, jobject thiz, jfloat level) {
    LOGD("Enabling segmented dimming at level %.2f", level);
    /* Real ML2:
       MLGraphicsEnableGlobalDimmer(graphics_client, level);
       MLSegmentedDimmerEnable();
       MLSegmentedDimmerSetOpacity(0, level);
    */
}

JNIEXPORT void JNICALL
Java_com_edith_ml2_DimmingService_nativeSetLevel(JNIEnv* env, jobject thiz, jfloat level) {
    LOGD("Dimming level: %.2f", level);
}

JNIEXPORT void JNICALL
Java_com_edith_ml2_DimmingService_nativeDisable(JNIEnv* env, jobject thiz) {
    LOGD("Dimming disabled");
}

} // extern "C"
