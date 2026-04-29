package com.edith.ml2

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.BatteryManager
import android.os.Bundle
import android.util.Log
import android.webkit.*
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║   E.D.I.T.H  —  Magic Leap 2  |  MainActivity              ║
 * ║   Pure Android + ML2 SDK (No Unity)  |  XRCC 2026          ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * Architecture:
 *   MLWebView  ←→  EdithBridge  ←→  Native ML2 Services
 *
 * HOW TO DEPLOY:
 *   1. adb connect <ML2-IP>:5555
 *   2. ./gradlew installDebug
 *   3. adb shell am start -n com.edith.ml2/.MainActivity
 */
class MainActivity : Activity() {

    companion object {
        private const val TAG = "EDITH"

        // !! CHANGE THIS to your laptop's local IP address !!
        // Find with: ipconfig (Windows) or ifconfig / ip addr (Mac/Linux)
        private const val BACKEND_HOST = "10.41.203.155"
        private const val BACKEND_PORT = 8000
        private val BACKEND_URL = "http://$BACKEND_HOST:$BACKEND_PORT"
        private val FRONTEND_URL = "$BACKEND_URL/ui/index.html"

        private const val PERMISSIONS_CODE = 100
    }

    private lateinit var webView:     WebView
    private lateinit var eyeTracker:  EyeTrackingService
    private lateinit var handTracker: HandTrackingService
    private lateinit var voiceService: VoiceService
    private lateinit var dimming:     DimmingService

    private val isReady = AtomicBoolean(false)

    // ─────────────────────────────────────────────────────────────
    // LIFECYCLE
    // ─────────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Log.i(TAG, "EDITH starting on Magic Leap 2")
        Log.i(TAG, "Backend: $BACKEND_URL")

        setupWebView()
        requestML2Permissions()
    }

    private fun onPermissionsGranted() {
        initServices()
        loadUI()
    }

    override fun onResume() {
        super.onResume()
        if (isReady.get()) {
            eyeTracker.resume()
            handTracker.resume()
        }
    }

    override fun onPause() {
        super.onPause()
        eyeTracker.pause()
        handTracker.pause()
        voiceService.pause()
    }

    override fun onDestroy() {
        super.onDestroy()
        eyeTracker.stop()
        handTracker.stop()
        voiceService.stop()
        dimming.disable()
    }

    // ─────────────────────────────────────────────────────────────
    // WEBVIEW SETUP
    // ─────────────────────────────────────────────────────────────

    private fun setupWebView() {
        webView = WebView(this)
        setContentView(webView)

        // Required WebView settings for EDITH
        webView.settings.apply {
            javaScriptEnabled                = true
            domStorageEnabled                = true
            mediaPlaybackRequiresUserGesture = false   // Auto-play TTS audio
            allowContentAccess               = true
            allowFileAccess                  = true
            mixedContentMode                 = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            cacheMode                        = WebSettings.LOAD_NO_CACHE
            useWideViewPort                  = true
            loadWithOverviewMode             = false
            setSupportZoom(false)
            builtInZoomControls              = false
        }

        // JavaScript ↔ Kotlin bridge
        webView.addJavascriptInterface(EdithBridge(), "EdithNative")

        // Enable Chrome DevTools remote debugging (for development)
        WebView.setWebContentsDebuggingEnabled(true)

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                Log.i(TAG, "EDITH UI loaded: $url")
                isReady.set(true)
                // Push initial battery level
                pushBattery()
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?,
                                         error: WebResourceError?) {
                Log.e(TAG, "WebView error: ${error?.description} on ${request?.url}")
                // Show error in JS console
                view?.evaluateJavascript(
                    "console.error('WebView error: ${error?.description}')", null
                )
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            // Grant microphone permission automatically
            override fun onPermissionRequest(request: PermissionRequest?) {
                request?.grant(request.resources)
            }
            // Allow fullscreen for YouTube
            override fun onShowCustomView(view: android.view.View?, callback: CustomViewCallback?) {
                setContentView(view)
            }
            override fun onHideCustomView() {
                setContentView(webView)
            }
        }
    }

    private fun loadUI() {
        Log.i(TAG, "Loading EDITH UI from $FRONTEND_URL")
        webView.loadUrl(FRONTEND_URL)
    }

    // ─────────────────────────────────────────────────────────────
    // SERVICE INITIALISATION
    // ─────────────────────────────────────────────────────────────

    private fun initServices() {
        // Store OpenRouter key in SharedPrefs so EyeTrackingService can read it
        // Key is fetched from backend /api/config at runtime
        fetchAndStoreOpenRouterKey()

        eyeTracker = EyeTrackingService(this, BACKEND_URL) { gaze ->
            if (!isReady.get()) return@EyeTrackingService
            val label = gaze.label.replace("'", "\\'").replace("\"","")
            val js = "window.EDITH.updateGaze('$label'," +
                     "${gaze.normX},${gaze.normY},${gaze.durationMs})"
            runOnUiThread { webView.evaluateJavascript(js, null) }

            // Auto-identify if staring > 1.5s at new target
            if (gaze.durationMs > 1500 && gaze.isNewTarget && gaze.imageCrop != null) {
                runOnUiThread {
                    webView.evaluateJavascript(
                        "window.EDITH.identifyObject('${gaze.imageCrop}','$label')", null
                    )
                }
            }
        }

        handTracker = HandTrackingService(this) { gesture ->
            if (!isReady.get()) return@HandTrackingService
            Log.d(TAG, "Gesture: $gesture")
            val js = "window.EDITH.sendGesture('$gesture')"
            runOnUiThread { webView.evaluateJavascript(js, null) }
        }

        voiceService = VoiceService(this, "$BACKEND_URL".replace("http","ws") + "/ws/edith-main") { chunk, isFinal ->
            if (!isReady.get()) return@VoiceService
            // AudioRecord fallback path — push raw PCM to JS (backend STT)
            if (chunk.isNotEmpty()) {
                val js = "window.EDITH.pushAudio('$chunk',${if (isFinal) "true" else "false"})"
                runOnUiThread { webView.evaluateJavascript(js, null) }
            }
        }

        // ── Wire SpeechRecognizer results back to JS ────────────────
        // This is the primary path: native Android STT → JS → LLM
        voiceService.setResultCallback { text, isFinal ->
            runOnUiThread {
                if (text.startsWith("__error:")) {
                    // Surface error to JS HUD
                    val errMsg = text.removePrefix("__error:")
                    val js = "window.EDITH.onSpeechError('${errMsg.replace("'","\\'")}');"
                    webView.evaluateJavascript(js, null)
                } else {
                    // Deliver transcript to JS
                    val escaped = text.replace("\\", "\\\\").replace("'", "\\'")
                    val js = "window.EDITH.onSpeechResult('$escaped', $isFinal);"
                    webView.evaluateJavascript(js, null)
                    Log.i(TAG, "Speech→JS: \"$text\" final=$isFinal")
                }
            }
        }

        dimming = DimmingService(this)
        dimming.enableSegmented(0.65f)

        eyeTracker.start()
        handTracker.start()

        isReady.set(true)
        Log.i(TAG, "All ML2 services started")
    }

    // ─────────────────────────────────────────────────────────────
    // JAVASCRIPT → KOTLIN BRIDGE
    // ─────────────────────────────────────────────────────────────

    inner class EdithBridge {

        @JavascriptInterface
        fun startVoice() {
            Log.i(TAG, "JS→Kotlin: startVoice()")
            voiceService.start()
        }

        @JavascriptInterface
        fun stopVoice() {
            Log.i(TAG, "JS→Kotlin: stopVoice()")
            voiceService.stop()
        }

        @JavascriptInterface
        fun toggleVoice() {
            Log.i(TAG, "JS→Kotlin: toggleVoice()")
            voiceService.toggle()
        }

        @JavascriptInterface
        fun setDimming(level: Float) { dimming.setLevel(level) }

        @JavascriptInterface
        fun haptic(type: String) {
            val ms = when(type) { "confirm"->80L; "error"->250L; else->30L }
            triggerHaptic(ms)
        }

        @JavascriptInterface
        fun log(msg: String) { Log.d(TAG, "[JS] $msg") }

        @JavascriptInterface
        fun getBackendUrl(): String = BACKEND_URL
    }

    // ─────────────────────────────────────────────────────────────
    // PERMISSIONS
    // ─────────────────────────────────────────────────────────────

    private fun requestML2Permissions() {
        val needed = arrayOf(
            "com.magicleap.permission.EYE_TRACKING",
            "com.magicleap.permission.HAND_TRACKING",
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.CAMERA,
            Manifest.permission.INTERNET,
            Manifest.permission.ACCESS_NETWORK_STATE,
        ).filter {
            checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED
        }.toTypedArray()

        if (needed.isEmpty()) {
            onPermissionsGranted()
        } else {
            requestPermissions(needed, PERMISSIONS_CODE)
        }
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<String>,
                                            results: IntArray) {
        super.onRequestPermissionsResult(code, perms, results)
        if (code == PERMISSIONS_CODE) {
            onPermissionsGranted()  // Proceed even if some perms denied (graceful degradation)
        }
    }

    // ─────────────────────────────────────────────────────────────
    // UTILITIES
    // ─────────────────────────────────────────────────────────────

    private fun pushBattery() {
        val bm  = getSystemService(BATTERY_SERVICE) as BatteryManager
        val pct = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        webView.evaluateJavascript("window.EDITH.updateBattery($pct)", null)
    }

    /**
     * Fetch the OpenRouter key from backend config and store it in SharedPreferences
     * so EyeTrackingService can use it for vision API calls.
     */
    private fun fetchAndStoreOpenRouterKey() {
        Thread {
            try {
                val url = java.net.URL("$BACKEND_URL/api/config")
                val conn = url.openConnection() as java.net.HttpURLConnection
                conn.connectTimeout = 5000; conn.readTimeout = 5000
                if (conn.responseCode == 200) {
                    val json = org.json.JSONObject(conn.inputStream.bufferedReader().readText())
                    val key  = json.optString("openrouter_key_prefix", "")
                    // We only get a prefix for security — enough to confirm key exists
                    val hasKey = json.optBoolean("has_openrouter_key", false)
                    Log.i(TAG, "Backend config: has_key=$hasKey")
                    // Store backend URL so EyeTrackingService can build its own requests
                    getSharedPreferences("edith", MODE_PRIVATE).edit()
                        .putString("backend_url", BACKEND_URL)
                        .putBoolean("has_openrouter_key", hasKey)
                        .apply()
                }
            } catch (e: Exception) {
                Log.w(TAG, "fetchAndStoreOpenRouterKey: $e")
            }
        }.also { it.isDaemon = true; it.start() }
    }

    private fun triggerHaptic(ms: Long) {
        val vib = getSystemService(VIBRATOR_SERVICE) as android.os.Vibrator
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
            vib.vibrate(android.os.VibrationEffect.createOneShot(ms,
                android.os.VibrationEffect.DEFAULT_AMPLITUDE))
        } else {
            @Suppress("DEPRECATION") vib.vibrate(ms)
        }
    }
}
