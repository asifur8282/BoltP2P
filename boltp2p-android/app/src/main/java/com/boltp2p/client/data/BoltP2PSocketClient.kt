package com.boltp2p.client.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest

/**
 * BoltP2PSocketClient:
 * Handles binary socket streaming to desktop daemon using 18-byte XDRP framing.
 */
class BoltP2PSocketClient(
    private var host: String = "127.0.0.1",
    private var port: Int = 58241
) {

    private var socket: Socket? = null
    private val socketMutex = Mutex()

    @Volatile
    var isTransferring: Boolean = false
        private set

    var sessionKey: ByteArray? = null
        private set
    var peerDeviceName: String = "Desktop Workstation"
        private set

    val isConnected: Boolean
        get() = socket?.isConnected == true && socket?.isClosed == false

    fun updateTarget(newHost: String, newPort: Int = 58241) {
        if (host != newHost || port != newPort) {
            close()
            host = newHost
            port = newPort
        }
    }

    suspend fun connect(targetHost: String = host, targetPort: Int = port, pin: String = ""): Boolean = withContext(Dispatchers.IO) {
        socketMutex.withLock {
            try {
                close()
                host = targetHost
                port = targetPort
                val s = Socket().apply {
                    tcpNoDelay = true
                    keepAlive = true
                    connect(InetSocketAddress(targetHost, targetPort), 5000)
                }
                socket = s

                // Perform Ephemeral X25519 Handshake
                try {
                    val out = s.getOutputStream()
                    val inStream = s.getInputStream()
                    val keyPair = CryptoManager.generateKeyPair()
                    val rawPub = CryptoManager.publicKeyToRawBytes(keyPair.public)

                    val meta = JSONObject().apply {
                        put("client_name", android.os.Build.MODEL)
                        put("pin", pin)
                    }.toString().toByteArray(Charsets.UTF_8)

                    writeFrame(out, TYPE_HANDSHAKE, meta, rawPub)

                    val resp = readFrameHeader(inStream)
                    if (resp.msgType == TYPE_HANDSHAKE_ACK) {
                        val respMetaBytes = if (resp.metaLen > 0) readExactBytes(inStream, resp.metaLen) else ByteArray(0)
                        val serverPubBytes = readExactBytes(inStream, resp.payloadLen.toInt())
                        val sharedSecret = CryptoManager.computeSharedSecret(keyPair.private, serverPubBytes)
                        sessionKey = CryptoManager.deriveSessionKey(sharedSecret, pin)

                        if (respMetaBytes.isNotEmpty()) {
                            val respJson = JSONObject(String(respMetaBytes, Charsets.UTF_8))
                            peerDeviceName = respJson.optString("device", "Desktop Workstation")
                        }
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                }
                true
            } catch (e: Exception) {
                close()
                false
            }
        }
    }

    suspend fun disconnect() = withContext(Dispatchers.IO) {
        socketMutex.withLock {
            try {
                val out = socket?.getOutputStream()
                if (out != null && isConnected) {
                    val meta = JSONObject().apply { put("reason", "USER_DISCONNECT") }.toString().toByteArray(Charsets.UTF_8)
                    writeFrame(out, TYPE_DISCONNECT, meta, ByteArray(0))
                }
            } catch (_: Exception) {}
            close()
        }
    }

    suspend fun sendHeartbeat(): Boolean = withContext(Dispatchers.IO) {
        if (isTransferring) return@withContext true
        if (!socketMutex.tryLock()) return@withContext true
        try {
            if (!isConnected) return@withContext false
            val out = socket?.getOutputStream() ?: return@withContext false
            val inStream = socket?.getInputStream() ?: return@withContext false
            val meta = JSONObject().apply { put("time", System.currentTimeMillis() / 1000.0) }.toString().toByteArray(Charsets.UTF_8)
            writeFrame(out, TYPE_PING, meta, ByteArray(0))
            val header = readFrameHeader(inStream)
            if (header.metaLen > 0) readExactBytes(inStream, header.metaLen)
            if (header.payloadLen > 0) readExactBytes(inStream, header.payloadLen.toInt())
            header.msgType == TYPE_PING
        } catch (e: Exception) {
            close()
            false
        } finally {
            socketMutex.unlock()
        }
    }

    fun close() {
        try {
            socket?.close()
        } catch (_: Exception) {}
        socket = null
        sessionKey = null
        isTransferring = false
    }

    suspend fun sendInstantText(text: String): Boolean = withContext(Dispatchers.IO) {
        socketMutex.withLock {
            try {
                if (!isConnected) {
                    if (!connect()) return@withContext false
                }
                val out = socket?.getOutputStream() ?: return@withContext false
                val meta = JSONObject().apply {
                    put("id", "text_${System.currentTimeMillis()}")
                    put("type", "TEXT")
                    put("preview", text.take(64))
                    put("time", System.currentTimeMillis() / 1000.0)
                }.toString().toByteArray(Charsets.UTF_8)

                val rawBytes = text.toByteArray(Charsets.UTF_8)
                val payload = if (sessionKey != null) {
                    CryptoManager.encryptGcm(sessionKey!!, rawBytes)
                } else {
                    rawBytes
                }
                writeFrame(out, TYPE_TEXT, meta, payload)
                true
            } catch (e: Exception) {
                close()
                false
            }
        }
    }

    suspend fun streamMemoryBuffer(
        filename: String,
        buffer: ByteBuffer,
        onProgress: (bytesSent: Long, totalBytes: Long) -> Unit = { _, _ -> }
    ): Boolean = withContext(Dispatchers.IO) {
        socketMutex.withLock {
            isTransferring = true
            try {
                if (!isConnected) {
                    if (!connect()) return@withContext false
                }
                val out = socket?.getOutputStream() ?: return@withContext false
                val inStream = socket?.getInputStream() ?: return@withContext false
                val totalSize = buffer.remaining().toLong()
                val transferId = "photo_${System.currentTimeMillis()}"

                val meta = JSONObject().apply {
                    put("id", transferId)
                    put("filename", filename)
                    put("size", totalSize)
                    put("mime", "image/jpeg")
                }.toString().toByteArray(Charsets.UTF_8)

                // 1. Send Offer
                writeFrame(out, TYPE_FILE, meta, ByteArray(0))

                // 2. Await Receiver Response (Wait for accept / reject)
                val response = readFrameHeader(inStream)
                if (response.metaLen > 0) {
                    readExactBytes(inStream, response.metaLen)
                }
                if (response.payloadLen > 0) {
                    readExactBytes(inStream, response.payloadLen.toInt())
                }

                if (response.msgType != TYPE_ACCEPT) {
                    return@withContext false
                }

                // 3. Active-Lock Stream with Running SHA-256 Digest
                val digest = MessageDigest.getInstance("SHA-256")
                val chunk = ByteArray(65536)
                var bytesSent = 0L

                while (buffer.hasRemaining()) {
                    val toRead = minOf(buffer.remaining(), chunk.size)
                    buffer.get(chunk, 0, toRead)
                    out.write(chunk, 0, toRead)
                    digest.update(chunk, 0, toRead)
                    bytesSent += toRead
                    onProgress(bytesSent, totalSize)
                }
                out.flush()

                // 4. Send FIN with Checksum
                val hashHex = digest.digest().joinToString("") { "%02x".format(it) }
                val finMeta = JSONObject().apply {
                    put("id", transferId)
                    put("sha256", hashHex)
                }.toString().toByteArray(Charsets.UTF_8)
                writeFrame(out, TYPE_FIN, finMeta, ByteArray(0))

                // 5. Read ACK
                val ackHeader = readFrameHeader(inStream)
                if (ackHeader.metaLen > 0) {
                    readExactBytes(inStream, ackHeader.metaLen)
                }
                if (ackHeader.payloadLen > 0) {
                    readExactBytes(inStream, ackHeader.payloadLen.toInt())
                }
                ackHeader.msgType == TYPE_ACK
            } catch (e: Exception) {
                close()
                false
            } finally {
                isTransferring = false
            }
        }
    }

    suspend fun streamInputStream(
        filename: String,
        totalSize: Long,
        inputStream: InputStream,
        onProgress: (bytesSent: Long, totalBytes: Long) -> Unit = { _, _ -> }
    ): Boolean = withContext(Dispatchers.IO) {
        socketMutex.withLock {
            isTransferring = true
            try {
                if (!isConnected) {
                    if (!connect()) return@withContext false
                }
                val out = socket?.getOutputStream() ?: return@withContext false
                val inStream = socket?.getInputStream() ?: return@withContext false
                val transferId = "file_${System.currentTimeMillis()}"

                val meta = JSONObject().apply {
                    put("id", transferId)
                    put("filename", filename)
                    put("size", totalSize)
                }.toString().toByteArray(Charsets.UTF_8)

                // 1. Send Offer
                writeFrame(out, TYPE_FILE, meta, ByteArray(0))

                // 2. Await Response
                val response = readFrameHeader(inStream)
                if (response.metaLen > 0) {
                    readExactBytes(inStream, response.metaLen)
                }
                if (response.payloadLen > 0) {
                    readExactBytes(inStream, response.payloadLen.toInt())
                }

                if (response.msgType != TYPE_ACCEPT) {
                    return@withContext false
                }

                // 3. Stream 64KB Chunks with SHA-256
                val digest = MessageDigest.getInstance("SHA-256")
                val chunk = ByteArray(65536)
                var bytesSent = 0L

                inputStream.use { stream ->
                    while (bytesSent < totalSize) {
                        val toRead = minOf(chunk.size.toLong(), totalSize - bytesSent).toInt()
                        val read = stream.read(chunk, 0, toRead)
                        if (read == -1) break
                        out.write(chunk, 0, read)
                        digest.update(chunk, 0, read)
                        bytesSent += read
                        onProgress(bytesSent, totalSize)
                    }
                }
                out.flush()

                // 4. Send FIN with Checksum
                val hashHex = digest.digest().joinToString("") { "%02x".format(it) }
                val finMeta = JSONObject().apply {
                    put("id", transferId)
                    put("sha256", hashHex)
                }.toString().toByteArray(Charsets.UTF_8)
                writeFrame(out, TYPE_FIN, finMeta, ByteArray(0))

                // 5. Read ACK
                val ackHeader = readFrameHeader(inStream)
                if (ackHeader.metaLen > 0) {
                    readExactBytes(inStream, ackHeader.metaLen)
                }
                if (ackHeader.payloadLen > 0) {
                    readExactBytes(inStream, ackHeader.payloadLen.toInt())
                }
                ackHeader.msgType == TYPE_ACK
            } catch (e: Exception) {
                close()
                false
            } finally {
                isTransferring = false
            }
        }
    }

    private fun writeFrame(out: OutputStream, type: Short, meta: ByteArray, payload: ByteArray) {
        val header = ByteBuffer.allocate(18)
        header.put("XDRP".toByteArray(Charsets.US_ASCII))
        header.putShort(type)
        header.putInt(meta.size)
        header.putLong(payload.size.toLong())
        out.write(header.array())
        if (meta.isNotEmpty()) {
            out.write(meta)
        }
        if (payload.isNotEmpty()) {
            out.write(payload)
        }
        out.flush()
    }

    private fun readFrameHeader(inStream: InputStream): FrameHeader {
        val headerBytes = readExactBytes(inStream, 18)
        val buffer = ByteBuffer.wrap(headerBytes)
        val magic = ByteArray(4).also { buffer.get(it) }
        val magicStr = String(magic, Charsets.US_ASCII)
        if (magicStr != "XDRP") {
            throw IllegalStateException("Invalid magic frame: $magicStr")
        }
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
        const val TYPE_PING: Short = 0x0001
        const val TYPE_TEXT: Short = 0x0002
        const val TYPE_FILE: Short = 0x0003
        const val TYPE_ACCEPT: Short = 0x0004
        const val TYPE_REJECT: Short = 0x0005
        const val TYPE_CHUNK: Short = 0x0006
        const val TYPE_FIN: Short = 0x0007
        const val TYPE_ACK: Short = 0x0008
        const val TYPE_HANDSHAKE: Short = 0x0009
        const val TYPE_HANDSHAKE_ACK: Short = 0x000A
        const val TYPE_DISCONNECT: Short = 0x000B
    }
}
