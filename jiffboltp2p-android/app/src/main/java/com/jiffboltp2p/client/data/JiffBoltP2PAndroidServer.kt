package com.jiffboltp2p.client.data

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.MediaScannerConnection
import android.net.Uri
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.webkit.MimeTypeMap
import android.widget.Toast
import com.jiffboltp2p.client.ForegroundService
import com.jiffboltp2p.client.MainActivity
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
import java.util.concurrent.ConcurrentHashMap

data class IncomingFileOffer(
    val transferId: String,
    val filename: String,
    val size: Long,
    val acceptDeferred: CompletableDeferred<Boolean> = CompletableDeferred()
)

class JiffBoltP2PAndroidServer(
    private val context: Context,
    val port: Int = 58242
) {
    private var serverSocket: ServerSocket? = null
    private var serverScope: CoroutineScope? = null
    private val mainHandler = Handler(Looper.getMainLooper())
    private val pendingOffers = ConcurrentHashMap<String, IncomingFileOffer>()

    var onIncomingOffer: ((IncomingFileOffer) -> Unit)? = null
    var onTextReceived: ((String) -> Unit)? = null
    var onDownloadProgress: ((received: Long, total: Long, filename: String) -> Unit)? = null
    var onDownloadComplete: ((file: File, success: Boolean) -> Unit)? = null
    var sessionKeySupplier: (() -> ByteArray?)? = null
    var isConnectedSupplier: (() -> Boolean)? = null
    var autoAcceptFiles: Boolean = false

    init {
        ForegroundService.onAcceptAction = { transferId ->
            acceptOffer(transferId)
        }
        ForegroundService.onRejectAction = { transferId ->
            rejectOffer(transferId)
        }
    }

    fun acceptOffer(transferId: String) {
        ForegroundService.cancelIncomingTransferNotification(context, transferId)
        MainActivity.activeInstance?.clearIncomingOffer(transferId)
        Log.i("BoltP2PServer", "acceptOffer called for $transferId")
        pendingOffers[transferId]?.acceptDeferred?.complete(true)
    }

    fun rejectOffer(transferId: String) {
        ForegroundService.cancelIncomingTransferNotification(context, transferId)
        MainActivity.activeInstance?.clearIncomingOffer(transferId)
        Log.i("BoltP2PServer", "rejectOffer called for $transferId")
        pendingOffers[transferId]?.acceptDeferred?.complete(false)
    }

    fun start() {
        if (serverSocket != null) return
        serverScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
        serverScope?.launch {
            try {
                serverSocket = ServerSocket(port).apply {
                    reuseAddress = true
                }
                Log.i("BoltP2PServer", "Android ServerSocket listening on port $port")

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
                Log.e("BoltP2PServer", "Server socket exception: ${e.message}")
            }
        }
    }

    private suspend fun handleIncomingConnection(socket: Socket) = withContext(Dispatchers.IO) {
        socket.tcpNoDelay = true
        try {
            val inStream = socket.getInputStream()
            val outStream = socket.getOutputStream()

            // If phone is marked disconnected in app, reject any unsolicited incoming connections
            if (isConnectedSupplier?.invoke() == false) {
                Log.w("BoltP2PServer", "Rejecting incoming connection from ${socket.inetAddress}: app is disconnected")
                val rejectMeta = JSONObject().apply {
                    put("reason", "DISCONNECTED")
                }.toString().toByteArray(Charsets.UTF_8)
                writeFrame(outStream, TYPE_REJECT, rejectMeta, ByteArray(0))
                return@withContext
            }

            val header = readFrameHeader(inStream)
            val metaBytes = if (header.metaLen > 0) readExactBytes(inStream, header.metaLen) else ByteArray(0)
            val metaJson = if (metaBytes.isNotEmpty()) JSONObject(String(metaBytes, Charsets.UTF_8)) else JSONObject()

            when (header.msgType) {
                TYPE_TEXT -> {
                    val payloadBytes = if (header.payloadLen > 0) {
                        readExactBytes(inStream, header.payloadLen.toInt())
                    } else ByteArray(0)

                    val text = try {
                        val sessionKey = sessionKeySupplier?.invoke()
                        if (sessionKey != null && payloadBytes.size >= 28) {
                            String(CryptoManager.decryptGcm(sessionKey, payloadBytes), Charsets.UTF_8)
                        } else {
                            String(payloadBytes, Charsets.UTF_8)
                        }
                    } catch (e: Exception) {
                        Log.w("BoltP2PServer", "Decryption failed, checking preview: ${e.message}")
                        val fallback = metaJson.optString("preview", "")
                        if (fallback.isNotEmpty()) fallback else String(payloadBytes, Charsets.UTF_8)
                    }
                    Log.i("BoltP2PServer", "Received text from PC: ${text.take(32)}...")

                    mainHandler.post {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                        if (clipboard != null) {
                            val clip = ClipData.newPlainText("JiffBoltP2P Text", text)
                            clipboard.setPrimaryClip(clip)
                        }
                        Toast.makeText(context, "JiffBoltP2P: Copied text from PC", Toast.LENGTH_SHORT).show()
                        onTextReceived?.invoke(text)
                    }
                }

                TYPE_FILE -> {
                    val rawFilename = metaJson.optString("filename", "received_${System.currentTimeMillis()}.bin")
                    val cleanName = File(rawFilename.replace('\\', '/')).name.replace("\u0000", "").trim()
                    val filename = if (cleanName.isEmpty() || cleanName == "." || cleanName == "..") {
                        "received_${System.currentTimeMillis()}.bin"
                    } else {
                        cleanName
                    }
                    val totalSize = metaJson.optLong("size", header.payloadLen)
                    val transferId = metaJson.optString("id", "file_${System.currentTimeMillis()}")

                    Log.i("BoltP2PServer", "Incoming file offer: $filename ($totalSize bytes)")

                    val offer = IncomingFileOffer(transferId, filename, totalSize)
                    pendingOffers[transferId] = offer

                    val accepted = if (autoAcceptFiles) {
                        Log.i("BoltP2PServer", "Auto-accepting incoming file in batch: $filename")
                        pendingOffers.remove(transferId)
                        true
                    } else {
                        val sizeStr = if (totalSize > 1024 * 1024) "%.2f MB".format(totalSize / (1024f * 1024f)) else "%.1f KB".format(totalSize / 1024f)
                        ForegroundService.postIncomingTransferNotification(
                            context,
                            transferId,
                            "Incoming File: $filename",
                            "$sizeStr • Tap to accept or reject"
                        )

                        mainHandler.post {
                            onIncomingOffer?.invoke(offer)
                        }

                        // Await user approval (up to 10 minutes)
                        try {
                            withTimeout(600_000L) {
                                offer.acceptDeferred.await()
                            }
                        } catch (e: Exception) {
                            false
                        } finally {
                            pendingOffers.remove(transferId)
                            ForegroundService.cancelIncomingTransferNotification(context, transferId)
                        }
                    }

                    if (!accepted) {
                        Log.i("BoltP2PServer", "File transfer declined/expired: $transferId")
                        val rejectMeta = JSONObject().apply {
                            put("id", transferId)
                            put("reason", "DECLINED_OR_TIMEOUT")
                        }.toString().toByteArray(Charsets.UTF_8)
                        writeFrame(outStream, TYPE_REJECT, rejectMeta, ByteArray(0))
                        return@withContext
                    }

                    // 1. User accepted: send authorization frame
                    val acceptMeta = JSONObject().apply {
                        put("id", transferId)
                        put("status", "ACCEPTED")
                    }.toString().toByteArray(Charsets.UTF_8)
                    writeFrame(outStream, TYPE_ACCEPT, acceptMeta, ByteArray(0))

                    // 2. Stream chunks directly to public Downloads folder
                    val downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
                    if (!downloadsDir.exists()) downloadsDir.mkdirs()
                    var targetFile = File(downloadsDir, filename)
                    if (!targetFile.canonicalPath.startsWith(downloadsDir.canonicalPath)) {
                        Log.e("JiffBoltP2PServer", "Path traversal blocked: $rawFilename")
                        throw SecurityException("Path traversal outside Downloads directory")
                    }

                    // Avoid overwriting existing files
                    if (targetFile.exists()) {
                        val dotIndex = filename.lastIndexOf('.')
                        val baseName = if (dotIndex > 0) filename.substring(0, dotIndex) else filename
                        val ext = if (dotIndex > 0) filename.substring(dotIndex) else ""
                        var counter = 1
                        while (targetFile.exists()) {
                            targetFile = File(downloadsDir, "$baseName ($counter)$ext")
                            counter++
                        }
                    }

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

                            val curBytes = bytesReceived
                            mainHandler.post {
                                onDownloadProgress?.invoke(curBytes, totalSize, filename)
                            }
                        }
                    }

                    // 3. Read FIN frame with SHA-256
                    val finHeader = readFrameHeader(inStream)
                    val finMetaBytes = if (finHeader.metaLen > 0) readExactBytes(inStream, finHeader.metaLen) else ByteArray(0)
                    val finJson = if (finMetaBytes.isNotEmpty()) JSONObject(String(finMetaBytes, Charsets.UTF_8)) else JSONObject()
                    val expectedSha = finJson.optString("sha256", "")
                    val computedSha = digest.digest().joinToString("") { "%02x".format(it) }

                    if (computedSha.equals(expectedSha, ignoreCase = true)) {
                        Log.i("JiffBoltP2PServer", "File transfer verified successfully: ${targetFile.name}")
                        val ackMeta = JSONObject().apply {
                            put("id", transferId)
                            put("status", "SUCCESS")
                            put("sha256", computedSha)
                        }.toString().toByteArray(Charsets.UTF_8)
                        writeFrame(outStream, TYPE_ACK, ackMeta, ByteArray(0))

                        // Immediately scan into Android MediaStore & Recents so WhatsApp, Instagram, Telegram & Recents see it immediately
                        val ext = targetFile.extension.lowercase()
                        val mimeType = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "*/*"
                        MediaScannerConnection.scanFile(
                            context,
                            arrayOf(targetFile.absolutePath),
                            arrayOf(mimeType)
                        ) { path, uri ->
                            Log.i("JiffBoltP2PServer", "MediaScanner indexed: $path -> $uri")
                        }
                        try {
                            val scanIntent = Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE).apply {
                                data = Uri.fromFile(targetFile)
                            }
                            context.sendBroadcast(scanIntent)
                        } catch (_: Exception) {}

                        mainHandler.post {
                            Toast.makeText(context, "JiffBoltP2P: Saved ${targetFile.name} to Downloads", Toast.LENGTH_LONG).show()
                            ForegroundService.postDownloadCompleteNotification(context, targetFile)
                            onDownloadComplete?.invoke(targetFile, true)
                        }
                    } else {
                        Log.e("JiffBoltP2PServer", "SHA-256 mismatch for ${targetFile.name} (expected $expectedSha, got $computedSha)")
                        if (targetFile.exists()) targetFile.delete()
                        val rejectMeta = JSONObject().apply {
                            put("id", transferId)
                            put("status", "INTEGRITY_FAIL")
                        }.toString().toByteArray(Charsets.UTF_8)
                        writeFrame(outStream, TYPE_REJECT, rejectMeta, ByteArray(0))

                        mainHandler.post {
                            onDownloadComplete?.invoke(targetFile, false)
                        }
                    }
                }
                else -> {
                    Log.d("BoltP2PServer", "Unhandled frame type: ${header.msgType}")
                }
            }
        } catch (e: Exception) {
            Log.e("BoltP2PServer", "Error handling PC connection: ${e.message}")
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
