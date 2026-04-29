package com.edith.ml2

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.ImageFormat
import android.hardware.camera2.*
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.ImageReader
import android.media.MediaRecorder
import android.os.Handler
import android.os.HandlerThread
import android.util.Base64
import android.util.Log
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.TimeUnit
import kotlin.math.sqrt

private const val TAG = "EDITH.Sensors"

data class GazeResult(
    val label:       String,
    val normX:       Float,
    val normY:       Float,
    val durationMs:  Long,
    val isNewTarget: Boolean,
    val imageCrop:   String?,
)


// ═══════════════════════════════════════════════════════════════════
// EYE TRACKING — Camera2 + OpenRouter Vision (REAL object detection)
// ═══════════════════════════════════════════════════════════════════
class EyeTrackingService(
    private val context:    Context,
    private val backendUrl: String,
    private val onGaze:     (GazeResult) -> Unit,
) {
    private var running      = AtomicBoolean(false)
    private var thread:      Thread? = null
    private var cameraDevice:  CameraDevice?  = null
    private var imageReader:   ImageReader?   = null
    private var cameraThread:  HandlerThread? = null
    private var cameraHandler: Handler?       = null
    private var lastImageB64:  String?        = null
    private var lastLabel      = ""
    private var labelStartMs   = System.currentTimeMillis()
    private var lastVisionMs   = 0L
    private val VISION_INTERVAL = 2000L
    private var gazeX = 0.5f; private var gazeVx = 0f
    private var gazeY = 0.5f; private var gazeVy = 0f

    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS).build()

    fun start() {
        running.set(true)
        startCamera()
        thread = Thread(::loop, "EDITH-Eye").also { it.isDaemon = true; it.start() }
        Log.i(TAG, "EyeTracking started — Camera2 + Vision AI")
    }

    @SuppressLint("MissingPermission")
    private fun startCamera() {
        try {
            cameraThread  = HandlerThread("EDITH-Cam").also { it.start() }
            cameraHandler = Handler(cameraThread!!.looper)
            val mgr       = context.getSystemService(Context.CAMERA_SERVICE) as CameraManager
            val camId     = mgr.cameraIdList.firstOrNull { id ->
                val f = mgr.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING)
                f == CameraCharacteristics.LENS_FACING_BACK ||
                f == CameraCharacteristics.LENS_FACING_EXTERNAL
            } ?: mgr.cameraIdList.firstOrNull() ?: return

            imageReader = ImageReader.newInstance(320, 240, ImageFormat.JPEG, 2)
            imageReader!!.setOnImageAvailableListener({ reader ->
                reader.acquireLatestImage()?.use { img ->
                    val buf   = img.planes[0].buffer
                    val bytes = ByteArray(buf.remaining()).also { buf.get(it) }
                    lastImageB64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
                }
            }, cameraHandler)

            mgr.openCamera(camId, object : CameraDevice.StateCallback() {
                override fun onOpened(cam: CameraDevice) {
                    cameraDevice = cam
                    cam.createCaptureSession(listOf(imageReader!!.surface),
                        object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(s: CameraCaptureSession) {
                                val req = cam.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                                    .apply { addTarget(imageReader!!.surface) }.build()
                                s.setRepeatingRequest(req, null, cameraHandler)
                                Log.i(TAG, "Camera session ready: $camId")
                            }
                            override fun onConfigureFailed(s: CameraCaptureSession) {
                                Log.e(TAG, "Camera config failed")
                            }
                        }, cameraHandler)
                }
                override fun onDisconnected(cam: CameraDevice) = cam.close()
                override fun onError(cam: CameraDevice, e: Int) {
                    Log.e(TAG, "Camera error $e"); cam.close()
                }
            }, cameraHandler)
        } catch (e: Exception) {
            Log.w(TAG, "Camera2 unavailable: $e — gaze simulation only")
        }
    }

    private fun loop() {
        while (running.get()) {
            val now = System.currentTimeMillis()
            val img = lastImageB64
            if (img != null && now - lastVisionMs >= VISION_INTERVAL) {
                lastVisionMs = now
                val detected = visionCall(img)
                if (detected != null && detected != lastLabel) {
                    lastLabel    = detected
                    labelStartMs = now
                    Log.i(TAG, "Object detected: $detected")
                }
            }
            // Smooth gaze simulation
            gazeVx = gazeVx*.85f + (.5f-gazeX)*.02f + (Math.random().toFloat()-.5f)*.01f
            gazeVy = gazeVy*.85f + (.5f-gazeY)*.02f + (Math.random().toFloat()-.5f)*.01f
            gazeX  = (gazeX + gazeVx).coerceIn(.05f,.95f)
            gazeY  = (gazeY + gazeVy).coerceIn(.05f,.95f)

            val dur   = now - labelStartMs
            onGaze(GazeResult(lastLabel.ifBlank{"scanning"}, gazeX, gazeY, dur, dur < 150, null))
            Thread.sleep(100)
        }
    }

    private fun visionCall(imgB64: String): String? = try {
        // Route through our backend — it has the OpenRouter key server-side
        val body = """{"data":"$imgB64","gaze_target":"camera view","session_id":"ml2-eye"}"""
            .toRequestBody("application/json".toMediaType())
        val req  = Request.Builder()
            .url("$backendUrl/api/identify")
            .post(body)
            .build()
        val resp = http.newCall(req).execute()
        if (!resp.isSuccessful) { Log.w(TAG, "Vision API ${resp.code}"); null }
        else {
            val json  = JSONObject(resp.body!!.string())
            val label = json.optString("label","").trim().lowercase()
                .replace(Regex("[^a-z0-9 ]"),"").take(30)
            label.ifBlank { null }
        }
    } catch (e: Exception) { Log.e(TAG, "visionCall: $e"); null }

    fun pause()  { running.set(false) }
    fun resume() { running.set(true) }
    fun stop()   {
        running.set(false); thread?.interrupt()
        try { imageReader?.close(); cameraDevice?.close(); cameraThread?.quit() }
        catch (e: Exception) {}
    }
}


// ═══════════════════════════════════════════════════════════════════
// VOICE SERVICE — AudioRecord → WAV → Whisper via backend
// Works on AOSP ML2 (no Google Play Services needed)
// ═══════════════════════════════════════════════════════════════════
class VoiceService(
    private val context: Context,
    private val wsUrl:   String,
    private val onChunk: (b64: String, isFinal: Boolean) -> Unit,
) {
    private val SAMPLE_RATE = 16000
    private val BUFFER_SIZE = AudioRecord.getMinBufferSize(
        SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
    ).coerceAtLeast(8192) * 4

    private var recorder:      AudioRecord? = null
    private var recording      = AtomicBoolean(false)
    private var captureThread: Thread?      = null
    private val isListening    = AtomicBoolean(false)
    private val audioBuffer    = ByteArrayOutputStream()
    private var resultCb:      ((String, Boolean) -> Unit)? = null

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS).build()
    private var socket: WebSocket? = null

    fun setResultCallback(cb: (text: String, isFinal: Boolean) -> Unit) { resultCb = cb }

    fun start() {
        if (isListening.get()) return
        isListening.set(true); recording.set(true)
        audioBuffer.reset(); connectWS()
        captureThread = Thread(::captureLoop, "EDITH-Audio")
            .also { it.isDaemon = true; it.start() }
        Log.i(TAG, "Voice recording started")
    }

    fun stop() {
        if (!isListening.get()) return
        isListening.set(false); recording.set(false)
        captureThread?.interrupt()
        recorder?.stop(); recorder?.release(); recorder = null
        val pcm = audioBuffer.toByteArray()
        Log.i(TAG, "Voice stopped — ${pcm.size} bytes")
        if (pcm.size > 3200) transcribe(pcm)
        else resultCb?.invoke("__no_speech__", true)
        onChunk("", true)
    }

    fun toggle() { if (isListening.get()) stop() else start() }
    fun pause()  { stop() }

    private fun captureLoop() {
        try {
            val rec = AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, BUFFER_SIZE)
            if (rec.state != AudioRecord.STATE_INITIALIZED) {
                Log.e(TAG, "AudioRecord failed"); resultCb?.invoke("__error:mic__", true); return
            }
            recorder = rec; rec.startRecording()
            val buf = ShortArray(BUFFER_SIZE / 4)
            while (recording.get()) {
                val n = rec.read(buf, 0, buf.size)
                if (n > 0) {
                    val bytes = ByteArray(n * 2)
                    for (i in 0 until n) {
                        bytes[i*2]   = (buf[i].toInt() and 0xFF).toByte()
                        bytes[i*2+1] = (buf[i].toInt() shr 8).toByte()
                    }
                    synchronized(audioBuffer) { audioBuffer.write(bytes) }
                    val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
                    onChunk(b64, false)
                    socket?.send("""{"type":"audio_chunk","data":"$b64","is_final":false}""")
                }
            }
            rec.stop(); rec.release()
        } catch (e: Exception) {
            Log.e(TAG, "captureLoop: $e"); resultCb?.invoke("__error:${e.message}__", true)
        }
    }

    private fun transcribe(pcm: ByteArray) {
        Thread {
            try {
                val wav   = buildWav(pcm)
                val b64   = Base64.encodeToString(wav, Base64.NO_WRAP)
                val base  = wsUrl.replace("ws://","http://").replace("/ws/edith-main","")
                val body  = """{"audio_b64":"$b64","format":"wav","sample_rate":$SAMPLE_RATE}"""
                    .toRequestBody("application/json".toMediaType())
                val resp  = http.newCall(Request.Builder().url("$base/api/transcribe").post(body).build()).execute()
                if (resp.isSuccessful) {
                    val text = JSONObject(resp.body!!.string()).optString("transcript","").trim()
                    Log.i(TAG, "Transcript: '$text'")
                    resultCb?.invoke(if (text.isNotBlank()) text else "__no_speech__", true)
                } else {
                    Log.e(TAG, "Transcribe ${resp.code}"); resultCb?.invoke("__error:http_${resp.code}__", true)
                }
            } catch (e: Exception) {
                Log.e(TAG, "transcribe: $e"); resultCb?.invoke("__error:${e.message}__", true)
            }
        }.also { it.isDaemon = true; it.start() }
    }

    private fun buildWav(pcm: ByteArray): ByteArray {
        val buf = ByteBuffer.allocate(pcm.size + 44).order(ByteOrder.LITTLE_ENDIAN)
        buf.put("RIFF".toByteArray()); buf.putInt(pcm.size + 36)
        buf.put("WAVEfmt ".toByteArray()); buf.putInt(16)
        buf.putShort(1); buf.putShort(1)
        buf.putInt(SAMPLE_RATE); buf.putInt(SAMPLE_RATE * 2)
        buf.putShort(2); buf.putShort(16)
        buf.put("data".toByteArray()); buf.putInt(pcm.size); buf.put(pcm)
        return buf.array()
    }

    private fun connectWS() {
        try {
            socket = http.newWebSocket(Request.Builder().url(wsUrl).build(),
                object : WebSocketListener() {
                    override fun onOpen(ws: WebSocket, r: Response) { Log.d(TAG,"WS open") }
                    override fun onFailure(ws: WebSocket, t: Throwable, r: Response?) { socket = null }
                })
        } catch (e: Exception) {}
    }
}

// ═══════════════════════════════════════════════════════════════════
// HAND TRACKING  (gesture recognition — emulated when no native SDK)
// ═══════════════════════════════════════════════════════════════════
class HandTrackingService(
    private val context:    Context,
    private val onGesture:  (String) -> Unit,
) {
    private external fun nativeInit(): Long
    private external fun nativeGetJoints(h: Long): FloatArray
    private external fun nativeDestroy(h: Long)

    private var handle  = 0L
    private var running = AtomicBoolean(false)
    private var thread: Thread? = null
    private var lastGesture = ""; private var lastMs = 0L
    companion object { init { try { System.loadLibrary("edith_hand") } catch (_:UnsatisfiedLinkError){} } }

    fun start() {
        running.set(true)
        thread = try { handle = nativeInit(); Thread(::nativePoll,"EDITH-Hand") }
                 catch (_:UnsatisfiedLinkError) { Thread(::emulated,"EDITH-HandEmul") }
        thread?.isDaemon = true; thread?.start()
    }
    private fun nativePoll() { while(running.get()){ try{ classify(nativeGetJoints(handle))?.let{emit(it)}; Thread.sleep(33) }catch(e:Exception){ Thread.sleep(100) } } }
    private fun emulated()   { while(running.get()) Thread.sleep(500) }
    private fun classify(j: FloatArray): String? {
        if (j.size < 78) return null
        fun p(i:Int)=Triple(j[i*3],j[i*3+1],j[i*3+2])
        fun d(a:Triple<Float,Float,Float>,b:Triple<Float,Float,Float>)=sqrt((a.first-b.first).let{it*it}+(a.second-b.second).let{it*it}+(a.third-b.third).let{it*it})
        val ti=d(p(4),p(8))
        return when{ ti<0.022f->"thumbtap"; d(p(8),p(20))>0.13f&&p(8).second>p(0).second+0.05f->"open_palm"; ti<0.045f&&d(p(4),p(12))>0.08f->"pinch"; else->null }
    }
    private fun emit(g:String){ val now=System.currentTimeMillis(); if(g==lastGesture&&now-lastMs<500)return; lastGesture=g;lastMs=now; onGesture(g) }
    fun pause()  { running.set(false) }
    fun resume() { if(!running.get()) start() }
    fun stop()   { running.set(false); thread?.interrupt(); if(handle!=0L)try{nativeDestroy(handle)}catch(_:Exception){} }
}

// ═══════════════════════════════════════════════════════════════════
// SEGMENTED DIMMING
// ═══════════════════════════════════════════════════════════════════
class DimmingService(private val context: Context) {
    private external fun nativeEnable(l:Float)
    private external fun nativeSetLevel(l:Float)
    private external fun nativeDisable()
    companion object { init { try { System.loadLibrary("edith_dimming") } catch (_:UnsatisfiedLinkError){} } }
    fun enableSegmented(l:Float=0.65f) { try{nativeEnable(l)}catch(_:UnsatisfiedLinkError){ Log.i(TAG,"Dimming native N/A") } }
    fun setLevel(l:Float) { try{nativeSetLevel(l.coerceIn(0f,1f))}catch(_:Exception){} }
    fun disable()         { try{nativeDisable()}catch(_:Exception){} }
}
