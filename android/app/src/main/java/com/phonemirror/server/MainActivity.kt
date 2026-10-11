package com.phonemirror.server

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.view.Surface
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean

/**
 * PhoneMirror Server  -  standalone screen streaming (no scrcpy, no adb).
 *
 * Phone par yeh app screen capture karti hai (MediaProjection), H.264 me encode
 * karti hai (MediaCodec, hardware), aur raw stream TCP socket par bhejti hai.
 * PC par PhoneMirrorReceiver.py isse connect karke ffplay se dikhata hai.
 *
 * Yeh ek prototype hai: sirf video, ek client, app foreground me rehni chahiye.
 */
class MainActivity : Activity() {

    companion object {
        private const val PORT = 27183
        private const val REQ_CAPTURE = 1001
        private const val MAX_DIM = 1280
        private const val BITRATE = 8_000_000
        private const val FPS = 30
    }

    private var projection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var encoder: MediaCodec? = null
    private var server: ServerSocket? = null
    private var client: Socket? = null
    private val running = AtomicBoolean(false)

    private var width = 720
    private var height = 1280
    private var dpi = 320

    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val dm = resources.displayMetrics
        var w = dm.widthPixels
        var h = dm.heightPixels
        dpi = dm.densityDpi
        // Bahut bade resolutions encode load badhaate hain -> long side 1280 tak cap
        if (maxOf(w, h) > MAX_DIM) {
            val s = MAX_DIM.toFloat() / maxOf(w, h)
            w = (w * s).toInt()
            h = (h * s).toInt()
        }
        width = w and -2   // last bit clear -> even (0xFFFFFFFE Int me fit nahi hota)
        height = h and -2

        val layout = LinearLayout(this)
        layout.orientation = LinearLayout.VERTICAL
        layout.setPadding(48, 80, 48, 48)

        val title = TextView(this)
        title.text = "PhoneMirror Server"
        title.textSize = 22f
        layout.addView(title)

        status = TextView(this)
        status.textSize = 15f
        status.setPadding(0, 32, 0, 32)
        status.text = "Ready.\n\n1) 'Start server' dabao\n2) Screen capture ki permission do\n" +
            "3) PC par receiver me yeh IP daalo (screen par dikhega)\n\n" +
            "Resolution: ${width}x$height  @ $FPS fps, ${BITRATE / 1_000_000} Mbps"
        layout.addView(status)

        val btnStart = Button(this)
        btnStart.text = "Start server"
        btnStart.setOnClickListener { requestCapture() }
        layout.addView(btnStart)

        val btnStop = Button(this)
        btnStop.text = "Stop"
        btnStop.setOnClickListener { stopAll() }
        layout.addView(btnStop)

        setContentView(layout)
    }

    // ---- permission ----
    private fun requestCapture() {
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        @Suppress("DEPRECATION")
        startActivityForResult(mpm.createScreenCaptureIntent(), REQ_CAPTURE)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_CAPTURE && resultCode == RESULT_OK && data != null) {
            startServer(data)
        } else {
            status.text = "Screen capture permission nahi mili."
        }
    }

    // ---- server ----
    private fun startServer(data: Intent) {
        if (running.get()) {
            status.text = "Pehle se chal raha hai."
            return
        }
        running.set(true)
        status.text = "Server start ho raha hai...\nPhone IP: ${phoneIp()}  Port: $PORT"

        Thread {
            try {
                val ss = ServerSocket(PORT)
                server = ss
                ui("Waiting for PC...\nPhone IP: ${phoneIp()}   Port: $PORT\n" +
                    "Receiver me yeh IP daal ke Start dabao.")
                val sock = ss.accept()
                client = sock
                ui("PC juda: ${sock.inetAddress.hostAddress}\nStream shuru ho raha hai...")
                setupAndStream(data, sock)
            } catch (e: Exception) {
                ui("Error: ${e.message}")
                stopAll()
            }
        }.start()
    }

    private fun setupAndStream(data: Intent, sock: Socket) {
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val proj = mpm.getMediaProjection(Activity.RESULT_OK, data)
        projection = proj

        val fmt = MediaFormat.createVideoFormat("video/avc", width, height)
        fmt.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
        fmt.setInteger(MediaFormat.KEY_BIT_RATE, BITRATE)
        fmt.setInteger(MediaFormat.KEY_FRAME_RATE, FPS)
        fmt.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
        try {
            fmt.setInteger(
                MediaFormat.KEY_BITRATE_MODE,
                MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR
            )
        } catch (_: Exception) {
            // kuch encoders CBR support nahi karte - VBR default chalega
        }

        val enc = MediaCodec.createEncoderByType("video/avc")
        enc.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        val inputSurface: Surface = enc.createInputSurface()
        enc.start()
        encoder = enc

        val vd = proj.createVirtualDisplay(
            "PhoneMirror", width, height, dpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            inputSurface, null, null
        )
        virtualDisplay = vd

        val out = BufferedOutputStream(sock.getOutputStream(), 1 shl 16)
        val info = MediaCodec.BufferInfo()

        while (running.get()) {
            val idx = enc.dequeueOutputBuffer(info, 10000)
            when {
                idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    val nf = enc.outputFormat
                    nf.getByteBuffer("csd-0")?.let { out.write(withStartCode(it)) }
                    nf.getByteBuffer("csd-1")?.let { out.write(withStartCode(it)) }
                    out.flush()
                }
                idx >= 0 -> {
                    val bb: ByteBuffer = enc.getOutputBuffer(idx)!!
                    if (info.size > 0) {
                        bb.position(info.offset)
                        bb.limit(info.offset + info.size)
                        val chunk = ByteArray(info.size)
                        bb.get(chunk)
                        out.write(toAnnexB(chunk))
                        out.flush()
                    }
                    enc.releaseOutputBuffer(idx, false)
                }
                // INFO_TRY_AGAIN_LATER -> loop
            }
        }

        try { out.flush() } catch (_: Exception) {}
        ui("Stream band ho gaya.")
        stopAll()
    }

    // ---- bitstream helpers ----
    private fun withStartCode(src: ByteBuffer): ByteArray {
        val n = src.remaining()
        val b = ByteArray(n + 4)
        b[0] = 0; b[1] = 0; b[2] = 0; b[3] = 1
        src.get(b, 4, n)
        return b
    }

    /** MediaCodec output AVCC (length-prefixed) hota hai; ffplay ko Annex-B chahiye. */
    private fun toAnnexB(data: ByteArray): ByteArray {
        // already Annex-B? (00 00 00 01 ya 00 00 01)
        if (data.size >= 4 && data[0] == 0.toByte() && data[1] == 0.toByte() &&
            data[2] == 0.toByte() && data[3] == 1.toByte()
        ) return data
        if (data.size >= 3 && data[0] == 0.toByte() && data[1] == 0.toByte() &&
            data[2] == 1.toByte()
        ) return data

        val out = ByteArrayOutputStream(data.size + 16)
        var i = 0
        while (i + 4 <= data.size) {
            val len = ((data[i].toInt() and 0xFF) shl 24) or
                ((data[i + 1].toInt() and 0xFF) shl 16) or
                ((data[i + 2].toInt() and 0xFF) shl 8) or
                (data[i + 3].toInt() and 0xFF)
            i += 4
            if (len <= 0 || i + len > data.size) break
            out.write(0); out.write(0); out.write(0); out.write(1)
            out.write(data, i, len)
            i += len
        }
        return out.toByteArray()
    }

    // ---- helpers ----
    private fun phoneIp(): String {
        try {
            for (nif in Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (addr in Collections.list(nif.inetAddresses)) {
                    if (!addr.isLoopbackAddress && addr is Inet4Address) {
                        return addr.hostAddress ?: "?"
                    }
                }
            }
        } catch (_: Exception) {
        }
        return "?"
    }

    private fun ui(msg: String) {
        runOnUiThread { status.text = msg }
    }

    private fun stopAll() {
        running.set(false)
        try { client?.close() } catch (_: Exception) {}
        try { server?.close() } catch (_: Exception) {}
        try { virtualDisplay?.release() } catch (_: Exception) {}
        try { projection?.stop() } catch (_: Exception) {}
        try { encoder?.stop() } catch (_: Exception) {}
        try { encoder?.release() } catch (_: Exception) {}
        client = null; server = null; virtualDisplay = null; projection = null; encoder = null
        ui("Stopped.\n\n'Start server' dabao dobara chalane ke liye.")
    }

    override fun onDestroy() {
        stopAll()
        super.onDestroy()
    }
}
