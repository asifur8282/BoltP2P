# Detailed Design Document (DDD)
## Project: JiffBoltP2P (Ultra-Lightweight P2P Cross-Device Sync)
**Version:** 1.2.0  
**Target Platform:** Windows 11 & Android 14 (API 34)  

---

## 1. Architectural Overview

JiffBoltP2P establishes a direct, asynchronous TCP connection wrapped in TLS 1.3 across the local Wi-Fi subnet. The architecture consists of an event-driven Python daemon on Windows 11 and a Jetpack Compose single-activity architecture on Android.

```
+---------------------------------------------------------------------------------+
|                                Local Wi-Fi Subnet                               |
|                                                                                 |
|   +--------------------------+                       +----------------------+   |
|   |    Android Client App    | <==== mDNS / NSD ===> |  Windows 11 Daemon   |   |
|   | (Jetpack Compose / Java) |                       |  (Python 3.11 Async) |   |
|   +--------------------------+                       +----------------------+   |
|                |                                                 |              |
|                +============ Secure TCP Pipe (TLS v1.3) =========+              |
|                             Port: 58241 (Custom Framing)                        |
+---------------------------------------------------------------------------------+
```

---

## 2. Wire Framing & Protocol Specification

### 2.1 Fixed Binary Frame Header (18 Bytes)
Every packet transmitted over the socket uses a fixed 18-byte big-endian header:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Magic: "XDRP"                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Msg Type (2B)        |      Meta Length (4B)         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Payload Length (8B)                      |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                  JSON Metadata Block (UTF-8)                  |
|                  (Length = Meta Length)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                  Raw Binary Payload Stream                    |
|                  (Length = Payload Length)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 2.2 Message Types
- `0x0001` (`PING` / `PONG`): Periodic heartbeat.
- `0x0002` (`OFFER_TEXT`): Text/clipboard transfer offer.
- `0x0003` (`OFFER_FILE`): File or live camera frame offer.
- `0x0004` (`ACCEPT_TRANSFER`): Recipient authorization to begin data streaming.
- `0x0005` (`REJECT_TRANSFER`): Transfer rejected or 10-minute TTL expired.
- `0x0006` (`DATA_CHUNK`): 64 KB binary streaming frame.
- `0x0007` (`TRANSFER_FIN`): Transfer termination frame containing overall SHA-256 checksum.
- `0x0008` (`TRANSFER_ACK`): Verification succeeded; receiver confirms data validity.

---

## 3. Ephemeral Buffer & Streaming State Machine

```
                      +-------------------+
                      |   Client Sends    |
                      |    Offer Packet   |
                      +-------------------+
                                |
                                v
               +----------------------------------+
               |  Receiver allocates RAM object;  |
               |  Starts 600s Ephemeral Timer;    |
               |  Displays Native OS Notification |
               +----------------------------------+
                                |
             +------------------+------------------+
             |                                     |
    [Timer > 600s OR Manual Reject]        [User Taps Accept]
             |                                     |
             v                                     v
+--------------------------+         +-------------------------------+
| 1. Clear RAM buffer      |         | 1. Cancel Ephemeral Timer     |
| 2. Send REJECT_TRANSFER  |         | 2. Send ACCEPT_TRANSFER       |
| 3. Close Stream          |         | 3. Lock Active TLS Pipeline   |
+--------------------------+         +-------------------------------+
                                                   |
                                                   v
                                     +-------------------------------+
                                     | Stream 64KB Chunks to Disk    |
                                     | Compute running SHA-256       |
                                     +-------------------------------+
                                                   |
                                                   v
                                     +-------------------------------+
                                     | Compare SHA-256 against FIN   |
                                     | If match: write complete      |
                                     | Return pipe to Idle State     |
                                     +-------------------------------+
```

---

## 4. Desktop Daemon Architecture (Windows 11)

### 4.1 Component Layout
```text
jiffboltp2p-desktop/
├── main.py              # Application entry point, DPI awareness (V2) & tray runner
├── requirements.txt     # Minimal dependencies
├── config.json          # Persistent paired device public keys / tokens
├── jiffboltp2p.spec     # PyInstaller standalone compilation spec
├── core/
│   ├── network_server.py # Asynchronous TLS socket server & frame parser
│   ├── discovery.py      # Zeroconf / mDNS broadcaster
│   └── crypto.py         # Key pair generation & SHA-256 utilities
└── ui/
    ├── quick_window.py   # Utilitarian quick window (DPI V2, drag & drop, staging, stream monitor)
    ├── tray_manager.py   # Windows notification area tray integration
    └── notifier.py       # Windows 11 native toast notifications
```

### 4.2 Desktop Core Server (`core/network_server.py`)
```python
import asyncio
import json
import struct
import time
import hashlib
from typing import Dict, Optional
import pyperclip
from win11toast import toast

MAGIC = b"XDRP"
TYPE_PING = 1
TYPE_TEXT = 2
TYPE_FILE = 3
TYPE_ACCEPT = 4
TYPE_REJECT = 5
TYPE_CHUNK = 6
TYPE_FIN = 7
TYPE_ACK = 8

class PendingTransfer:
    def __init__(self, transfer_id: str, msg_type: int, metadata: dict, payload_data: Optional[bytes] = None):
        self.transfer_id = transfer_id
        self.msg_type = msg_type
        self.metadata = metadata
        self.payload_data = payload_data
        self.created_at = time.time()
        self.ttl = 600  # 10 minutes strictly
        self.accepted = False
        self.copied = False

class JiffBoltP2PServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 58241, save_dir: str = "./Downloads"):
        self.host = host
        self.port = port
        self.save_dir = save_dir
        self.pending_offers: Dict[str, PendingTransfer] = {}

    def copy_text(self, transfer_id: str) -> Optional[str]:
        """Copy received ephemeral text payload to clipboard and mark copied without purging RAM."""
        if transfer_id in self.pending_offers:
            item = self.pending_offers[transfer_id]
            if item.payload_data:
                text = item.payload_data.decode("utf-8")
                pyperclip.copy(text)
                item.copied = True
                return text
        return None

    def consume_text(self, transfer_id: str) -> Optional[str]:
        """Backwards-compatible text copy."""
        return self.copy_text(transfer_id)

    async def start(self):
        self.server = await asyncio.start_server(self.handle_connection, self.host, self.port)
        print(f"[JiffBoltP2P] Core daemon running on {self.host}:{self.port}")

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        while not writer.is_closing():
            try:
                header = await reader.readexactly(18)
                magic, msg_type, meta_len, payload_len = struct.unpack("!4sHII", header)
                if magic != MAGIC:
                    writer.close()
                    break

                meta_bytes = await reader.readexactly(meta_len)
                metadata = json.loads(meta_bytes.decode('utf-8'))
                transfer_id = metadata.get("id", str(time.time()))

                if msg_type == TYPE_TEXT:
                    text_bytes = await reader.readexactly(payload_len)
                    transfer = PendingTransfer(transfer_id, msg_type, metadata, text_bytes)
                    self.pending_offers[transfer_id] = transfer
                    
                    asyncio.create_task(self._ephemeral_memory_ttl(transfer_id))
                    
                    toast(
                        "JiffBoltP2P: Text Received",
                        metadata.get("preview", "New text snippet received."),
                        buttons=[{"activationType": "protocol", "arguments": f"jiffboltp2p://copy/{transfer_id}", "content": "Copy to Clipboard"}],
                        on_click=lambda args: self.consume_text(transfer_id)
                    )

                elif msg_type == TYPE_FILE:
                    transfer = PendingTransfer(transfer_id, msg_type, metadata)
                    self.pending_offers[transfer_id] = transfer
                    
                    asyncio.create_task(self._ephemeral_memory_ttl(transfer_id, writer))
                    
                    toast(
                        "JiffBoltP2P: Incoming File",
                        f"File: {metadata.get('filename')} ({metadata.get('size')} bytes)",
                        buttons=[
                            {"activationType": "protocol", "arguments": f"jiffboltp2p://accept/{transfer_id}", "content": "Accept"},
                            {"activationType": "protocol", "arguments": f"jiffboltp2p://reject/{transfer_id}", "content": "Reject"}
                        ]
                    )

                    while transfer_id in self.pending_offers and not self.pending_offers[transfer_id].accepted:
                        await asyncio.sleep(0.5)

                    if transfer_id not in self.pending_offers:
                        self._write_frame(writer, TYPE_REJECT, {"id": transfer_id, "reason": "EXPIRED_OR_REJECTED"})
                        continue

                    self._write_frame(writer, TYPE_ACCEPT, {"id": transfer_id})
                    await self._stream_incoming_file(reader, writer, metadata)

            except (asyncio.IncompleteReadError, ConnectionResetError):
                break

    async def _ephemeral_memory_ttl(self, transfer_id: str, writer: Optional[asyncio.StreamWriter] = None):
        await asyncio.sleep(600)
        if transfer_id in self.pending_offers:
            item = self.pending_offers.pop(transfer_id)
            if not item.accepted:
                item.payload_data = None
                print(f"[JiffBoltP2P] TTL expired for {transfer_id}. RAM wiped.")
                if writer and not writer.is_closing():
                    self._write_frame(writer, TYPE_REJECT, {"id": transfer_id, "reason": "TIMEOUT_10M"})

    def consume_text(self, transfer_id: str):
        if transfer_id in self.pending_offers:
            item = self.pending_offers.pop(transfer_id)
            if item.payload_data:
                pyperclip.copy(item.payload_data.decode('utf-8'))
                item.payload_data = None

    async def _stream_incoming_file(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, metadata: dict):
        filename = metadata["filename"]
        target_path = f"{self.save_dir}/{filename}"
        total_size = metadata["size"]
        bytes_received = 0
        hasher = hashlib.sha256()

        with open(target_path, "wb") as f:
            while bytes_received < total_size:
                chunk = await reader.read(min(65536, total_size - bytes_received))
                if not chunk:
                    raise ConnectionError("Stream interrupted.")
                f.write(chunk)
                hasher.update(chunk)
                bytes_received += len(chunk)

        fin_header = await reader.readexactly(18)
        _, _, fin_meta_len, _ = struct.unpack("!4sHII", fin_header)
        fin_meta = json.loads((await reader.readexactly(fin_meta_len)).decode('utf-8'))

        if fin_meta.get("sha256") == hasher.hexdigest():
            self._write_frame(writer, TYPE_ACK, {"status": "SUCCESS"})
        else:
            self._write_frame(writer, TYPE_REJECT, {"status": "INTEGRITY_FAIL"})

    def _write_frame(self, writer: asyncio.StreamWriter, msg_type: int, metadata: dict, payload: bytes = b""):
        meta_bytes = json.dumps(metadata).encode('utf-8')
        header = struct.pack("!4sHII", MAGIC, msg_type, len(meta_bytes), len(payload))
        writer.write(header + meta_bytes + payload)
```

---

## 5. Android Mobile Architecture (API 34 / Jetpack Compose)

### 5.1 Zero-Disk In-Memory Camera Pipeline
The mobile client directly intercepts raw camera byte buffers via CameraX and pipes them into the active socket without hitting the local filesystem:

```kotlin
package com.jiffboltp2p.client.data

import android.content.Context
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.core.content.ContextCompat
import java.nio.ByteBuffer

class CameraStreamManager(private val context: Context) {

    fun capturePhotoToMemory(
        imageCapture: ImageCapture,
        onSuccess: (ByteBuffer) -> Unit,
        onError: (ImageCaptureException) -> Unit
    ) {
        imageCapture.takePicture(
            ContextCompat.getMainExecutor(context),
            object : ImageCapture.OnImageCapturedCallback() {
                override fun onCaptureSuccess(image: ImageProxy) {
                    val plane = image.planes[0]
                    val buffer = plane.buffer
                    val duplicate = ByteBuffer.allocate(buffer.remaining())
                    duplicate.put(buffer)
                    duplicate.flip()
                    image.close()
                    onSuccess(duplicate)
                }

                override fun onError(exception: ImageCaptureException) {
                    onError(exception)
                }
            }
        )
    }
}
```

### 5.2 Direct Socket Client & Active Lock Streamer
```kotlin
package com.jiffboltp2p.client.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.InputStream
import java.io.OutputStream
import java.net.Socket
import java.nio.ByteBuffer
import java.security.MessageDigest

class JiffBoltP2PSocketClient(private val host: String, private val port: Int = 58241) {

    private var socket: Socket? = null

    suspend fun connect() = withContext(Dispatchers.IO) {
        socket = Socket(host, port).apply {
            tcpNoDelay = true
            keepAlive = true
        }
    }

    suspend fun sendInstantText(text: String) = withContext(Dispatchers.IO) {
        val out = socket?.getOutputStream() ?: return@withContext
        val meta = JSONObject().apply {
            put("type", "TEXT")
            put("preview", text.take(64))
        }.toString().toByteArray()

        val payload = text.toByteArray()
        writeFrame(out, 0x0002.toShort(), meta, payload)
    }

    suspend fun streamMemoryBuffer(filename: String, buffer: ByteBuffer) = withContext(Dispatchers.IO) {
        val out = socket?.getOutputStream() ?: return@withContext
        val inStream = socket?.getInputStream() ?: return@withContext
        val totalSize = buffer.remaining()

        val meta = JSONObject().apply {
            put("filename", filename)
            put("size", totalSize)
            put("mime", "image/jpeg")
        }.toString().toByteArray()

        // 1. Send Offer
        writeFrame(out, 0x0003.toShort(), meta, ByteArray(0))

        // 2. Await Receiver Response (10-minute wait loop)
        val response = readFrameHeader(inStream)
        if (response.msgType == 0x0004.toShort()) { // ACCEPTED
            val digest = MessageDigest.getInstance("SHA-256")
            val chunk = ByteArray(65536)
            
            while (buffer.hasRemaining()) {
                val toRead = minOf(buffer.remaining(), chunk.size)
                buffer.get(chunk, 0, toRead)
                out.write(chunk, 0, toRead)
                digest.update(chunk, 0, toRead)
            }
            out.flush()

            // 3. Send FIN with Checksum
            val finMeta = JSONObject().apply {
                put("sha256", digest.digest().joinToString("") { "%02x".format(it) })
            }.toString().toByteArray()
            writeFrame(out, 0x0007.toShort(), finMeta, ByteArray(0))
        }
    }

    private fun writeFrame(out: OutputStream, type: Short, meta: ByteArray, payload: ByteArray) {
        val header = ByteBuffer.allocate(18)
        header.put("XDRP".toByteArray())
        header.putShort(type)
        header.putInt(meta.size)
        header.putInt(payload.size)
        out.write(header.array())
        out.write(meta)
        if (payload.isNotEmpty()) {
            out.write(payload)
        }
        out.flush()
    }

    private fun readFrameHeader(inStream: InputStream): FrameHeader {
        val headerBytes = ByteArray(18)
        var read = 0
        while (read < 18) {
            val r = inStream.read(headerBytes, read, 18 - read)
            if (r == -1) throw Exception("Stream closed")
            read += r
        }
        val buffer = ByteBuffer.wrap(headerBytes)
        val magic = ByteArray(4).also { buffer.get(it) }
        val type = buffer.short
        val metaLen = buffer.int
        val payloadLen = buffer.int
        return FrameHeader(type, metaLen, payloadLen)
    }

    data class FrameHeader(val msgType: Short, val metaLen: Int, val payloadLen: Int)
}
```