package com.crossdrop.client.data

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.widget.Toast
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.ServerSocket
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest

class CrossDropAndroidServer(
    private val context: Context,
    val port: Int = 58242
) {
    private var serverSocket: ServerSocket? = null
    private var serverScope: CoroutineScope? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    fun start() {
        if (serverSocket != null) return
        serverScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        serverScope?.launch {
            try {
                serverSocket = ServerSocket(port).apply {
                    reuseAddress = true
                }
                Log.i("CrossDropServer", "Android ServerSocket listening on port $port")

                while (isActive) {
                    val client = try {
                        serverSocket?.accept() ?: break
                    } catch (e: Exception) {
                        break
                    }
                    launch {
                        handleIncomingConnection(client)
                    }
                }
            } catch (e: Exception) {
                Log.e("CrossDropServer", "Server socket exception: ${e.message}")
            }
        }
    }

    private suspend fun handleIncomingConnection(socket: Socket) = withContext(Dispatchers.IO) {
        socket.tcpNoDelay = true
        try {
            val inStream = socket.getInputStream()
            val outStream = socket.getOutputStream()

            val header = readFrameHeader(inStream)
            val metaBytes = if (header.metaLen > 0) readExactBytes(inStream, header.metaLen) else ByteArray(0)
            val metaJson = if (metaBytes.isNotEmpty()) JSONObject(String(metaBytes, Charsets.UTF_8)) else JSONObject()

            when (header.msgType) {
                TYPE_TEXT -> {
                    val payloadBytes = if (header.payloadLen > 0) {
                        readExactBytes(inStream, header.payloadLen.toInt())
                    } else ByteArray(0)
                    val text = String(payloadBytes, Charsets.UTF_8)
                    Log.i("CrossDropServer", "Received text from PC: ${text.take(32)}...")

                    mainHandler.post {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                        if (clipboard != null) {
                            val clip = ClipData.newPlainText("CrossDrop Text", text)
                            clipboard.setPrimaryClip(clip)
                        }
                        Toast.makeText(context, "CrossDrop: Copied text from PC", Toast.LENGTH_SHORT).show()
                    }
                }

                TYPE_FILE -> {
                    val rawFilename = metaJson.optString("filename", "received_${System.currentTimeMillis()}.bin")
                    val filename = File(rawFilename).name
                    val totalSize = metaJson.optLong("size", header.payloadLen)
                    val transferId = metaJson.optString("id", "file_${System.currentTimeMillis()}")

                    Log.i("CrossDropServer", "Incoming file from PC: $filename ($totalSize bytes)")

                    // 1. Automatically accept file transfer from PC
                    val acceptMeta = JSONObject().apply {
                        put("id", transferId)
                        put("status", "ACCEPTED")
                    }.toString().toByteArray(Charsets.UTF_8)
                    writeFrame(outStream, TYPE_ACCEPT, acceptMeta, ByteArray(0))

                    // 2. Stream chunks directly to Downloads
                    val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                    if (!downloadsDir.exists()) downloadsDir.mkdirs()
                    val targetFile = File(downloadsDir, filename)

                    val digest = MessageDigest.getInstance("SHA-256")
                    var bytesReceived = 0L
                    val chunk = ByteArray(65536)

                    FileOutputStream(targetFile).use { fos ->
                        while (bytesReceived < totalSize) {
                            val toRead = minOf(chunk.size.toLong(), totalSize - bytesReceived).toInt()
                            val read = inStream.read(chunk, 0, toRead)
                            if (read == -1) throw IllegalStateException("Stream terminated prematurely")
                            fos.write(chunk, 0, read)
                            digest.update(chunk, 0, read)
                            bytesReceived += read
                        }
                    }

                    // 3. Read FIN frame with SHA-256
                    val finHeader = readFrameHeader(inStream)
                    val finMetaBytes = if (finHeader.metaLen > 0) readExactBytes(inStream, finHeader.metaLen) else ByteArray(0)
                    val finJson = if (finMetaBytes.isNotEmpty()) JSONObject(String(finMetaBytes, Charsets.UTF_8)) else JSONObject()
                    val expectedSha = finJson.optString("sha256", "")
                    val computedSha = digest.digest().joinToString("") { "%02x".format(it) }

                    if (computedSha.equals(expectedSha, ignoreCase = true)) {
                        Log.i("CrossDropServer", "File transfer verified successfully: $filename")
                        val ackMeta = JSONObject().apply {
                            put("id", transferId)
                            put("status", "SUCCESS")
                            put("sha256", computedSha)
                        }.toString().toByteArray(Charsets.UTF_8)
                        writeFrame(outStream, TYPE_ACK, ackMeta, ByteArray(0))

                        mainHandler.post {
                            Toast.makeText(context, "CrossDrop: Saved $filename to Downloads", Toast.LENGTH_LONG).show()
                        }
                    } else {
                        Log.e("CrossDropServer", "SHA-256 mismatch for $filename (expected $expectedSha, got $computedSha)")
                        if (targetFile.exists()) targetFile.delete()
                        val rejectMeta = JSONObject().apply {
                            put("id", transferId)
                            put("status", "INTEGRITY_FAIL")
                        }.toString().toByteArray(Charsets.UTF_8)
                        writeFrame(outStream, TYPE_REJECT, rejectMeta, ByteArray(0))
                    }
                }
                else -> {
                    Log.d("CrossDropServer", "Unhandled frame type: ${header.msgType}")
                }
            }
        } catch (e: Exception) {
            Log.e("CrossDropServer", "Error handling PC connection: ${e.message}")
        } finally {
            try {
                socket.close()
            } catch (_: Exception) {}
        }
    }

    fun stop() {
        serverScope?.cancel()
        serverScope = null
        try {
            serverSocket?.close()
        } catch (_: Exception) {}
        serverSocket = null
    }

    private fun writeFrame(out: OutputStream, type: Short, meta: ByteArray, payload: ByteArray) {
        val header = ByteBuffer.allocate(18)
        header.put("XDRP".toByteArray(Charsets.US_ASCII))
        header.putShort(type)
        header.putInt(meta.size)
        header.putLong(payload.size.toLong())
        out.write(header.array())
        if (meta.isNotEmpty()) out.write(meta)
        if (payload.isNotEmpty()) out.write(payload)
        out.flush()
    }

    private fun readFrameHeader(inStream: InputStream): FrameHeader {
        val headerBytes = readExactBytes(inStream, 18)
        val buffer = ByteBuffer.wrap(headerBytes)
        val magic = ByteArray(4).also { buffer.get(it) }
        val magicStr = String(magic, Charsets.US_ASCII)
        if (magicStr != "XDRP") throw IllegalStateException("Invalid magic frame: $magicStr")
        val type = buffer.short
        val metaLen = buffer.int
        val payloadLen = buffer.long
        return FrameHeader(type, metaLen, payloadLen)
    }

    private fun readExactBytes(inStream: InputStream, count: Int): ByteArray {
        val bytes = ByteArray(count)
        var read = 0
        while (read < count) {
            val r = inStream.read(bytes, read, count - read)
            if (r == -1) throw IllegalStateException("Stream closed unexpectedly")
            read += r
        }
        return bytes
    }

    data class FrameHeader(val msgType: Short, val metaLen: Int, val payloadLen: Long)

    companion object {
        const val TYPE_TEXT: Short = 0x0002
        const val TYPE_FILE: Short = 0x0003
        const val TYPE_ACCEPT: Short = 0x0004
        const val TYPE_REJECT: Short = 0x0005
        const val TYPE_FIN: Short = 0x0007
        const val TYPE_ACK: Short = 0x0008
    }
}
