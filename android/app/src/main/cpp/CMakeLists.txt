# ═══════════════════════════════════════════════════════
# CMakeLists.txt — EDITH AR Native Bindings
# Builds JNI stubs for ML2 eye/hand tracking + dimming
# ═══════════════════════════════════════════════════════
cmake_minimum_required(VERSION 3.22.1)
project("edith_native")

# ── Magic Leap SDK path ───────────────────────────────
# Set via local.properties: ml2.sdk=/path/to/MagicLeap/mlsdk/v1.6.0
set(ML2_SDK $ENV{MLSDK})
if (NOT ML2_SDK)
    set(ML2_SDK "$ENV{USERPROFILE}/MagicLeap/mlsdk/v1.12.0")
endif()

message(STATUS "EDITH ML2_SDK path: ${ML2_SDK}")

# ── Eye Tracking JNI library ──────────────────────────
add_library(edith_eye SHARED eye_tracking_jni.cpp)

target_include_directories(edith_eye PRIVATE
    ${ML2_SDK}/include
    ${ANDROID_NDK}/sources/android/native_app_glue
)

target_link_libraries(edith_eye
    android log
)

# ── Hand Tracking JNI library ─────────────────────────
add_library(edith_hand SHARED hand_tracking_jni.cpp)

target_include_directories(edith_hand PRIVATE ${ML2_SDK}/include)

target_link_libraries(edith_hand
    android log
)

# ── Segmented Dimming JNI library ─────────────────────
add_library(edith_dimming SHARED dimming_jni.cpp)

target_include_directories(edith_dimming PRIVATE ${ML2_SDK}/include)

target_link_libraries(edith_dimming
    android log
)
