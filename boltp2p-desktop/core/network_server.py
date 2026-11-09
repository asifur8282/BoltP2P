"""
BoltP2P Core Network Server (Windows 11)
Implements 18-byte big-endian framing, 10-minute ephemeral RAM buffer,
active-lock socket streaming, and on-the-fly SHA-256 integrity verification.
"""

import asyncio
import hashlib
import json
import logging
import os
import socket
import struct
import time
from typing import Dict, Optional, Callable, Any
import pyperclip
from .crypto import (
    zero_memory,
    generate_pairing_pin,
    generate_pairing_token,
    generate_x25519_keypair,
    derive_shared_secret,
    derive_session_key,
    encrypt_gcm,
    decrypt_gcm
)

def get_lan_ip() -> str:
    """Detect active local network IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

logger = logging.getLogger("BoltP2P.Server")

MAGIC = b"XDRP"

# Message Types
TYPE_PING = 0x0001
TYPE_TEXT = 0x0002
TYPE_FILE = 0x0003
TYPE_ACCEPT = 0x0004
TYPE_REJECT = 0x0005
TYPE_CHUNK = 0x0006
TYPE_FIN = 0x0007
TYPE_ACK = 0x0008
TYPE_HANDSHAKE = 0x0009
TYPE_HANDSHAKE_ACK = 0x000A
TYPE_DISCONNECT = 0x000B

HEADER_STRUCT = "!4sHIQ"
HEADER_SIZE = 18  # 4 + 2 + 4 + 8 = 18 bytes


class PendingTransfer:
    def __init__(self, transfer_id: str, msg_type: int, metadata: dict, payload_data: Optional[bytearray] = None):
        self.transfer_id = transfer_id
        self.msg_type = msg_type
        self.metadata = metadata
        self.payload_data = payload_data
        self.created_at = time.time()
        self.ttl = 600  # 10 minutes strictly
        self.accepted = False
        self.rejected = False
        self.accept_event = asyncio.Event()
        self.state = "PENDING"  # PENDING, DOWNLOADING, COMPLETED, REJECTED
        self.progress = 0.0
        self.bytes_transferred = 0
        self.total_bytes = metadata.get("size", 0)
        self.timer_stopped = False
        self.copied = False

    def remaining_ttl(self) -> int:
        if self.timer_stopped or self.state in ("DOWNLOADING", "COMPLETED", "REJECTED"):
            return 0
        elapsed = time.time() - self.created_at
        return max(0, int(self.ttl - elapsed))

    def purge_memory(self) -> None:
        if self.payload_data is not None:
            zero_memory(self.payload_data)
            self.payload_data = None


class BoltP2PServer:
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 58241,
        save_dir: str = "./Downloads",
        auto_accept_text: bool = False,
        auto_accept_files: bool = False,
        on_notify: Optional[Callable[[str, str, str, dict], None]] = None,
        on_transfer_progress: Optional[Callable[[str, int, int], None]] = None,
        on_transfer_complete: Optional[Callable[[str, str, bool], None]] = None,
        on_connection_change: Optional[Callable[[str, bool], None]] = None
    ):
        self.host = host
        self.port = port
        self.save_dir = os.path.abspath(save_dir)
        os.makedirs(self.save_dir, exist_ok=True)
        self.auto_accept_text = auto_accept_text
        self.auto_accept_files = auto_accept_files
        self.on_notify = on_notify
        self.on_transfer_progress = on_transfer_progress
        self.on_transfer_complete = on_transfer_complete
        self.on_connection_change = on_connection_change

        self.pending_offers: Dict[str, PendingTransfer] = {}
        self.server: Optional[asyncio.Server] = None
        self.active_clients: Dict[str, asyncio.StreamWriter] = {}
        self.client_sessions: Dict[str, bytes] = {}
        self.client_names: Dict[str, str] = {}
        self.pairing_pin: str = generate_pairing_pin()
        self.pairing_psk: str = generate_pairing_token()
        self.private_key, self.public_key_bytes = generate_x25519_keypair()
        self.device_name: str = "Windows 11 Workstation"
        self.running = False
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """Start the asynchronous TCP socket server."""
        self.running = True
        self.loop = asyncio.get_running_loop()
        self.server = await asyncio.start_server(
            self.handle_connection,
            self.host,
            self.port,
            reuse_address=True
        )
        logger.info("BoltP2P core network server listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop server and terminate open connections."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        # Cleanly purge any pending ephemeral RAM
        for transfer in list(self.pending_offers.values()):
            transfer.purge_memory()
        self.pending_offers.clear()
        for writer in list(self.active_clients.values()):
            if not writer.is_closing():
                writer.close()
        self.active_clients.clear()
        logger.info("BoltP2P server shut down.")

    def pack_frame(self, msg_type: int, metadata: dict, payload: bytes = b"") -> bytes:
        meta_bytes = json.dumps(metadata).encode("utf-8")
        header = struct.pack(HEADER_STRUCT, MAGIC, msg_type, len(meta_bytes), len(payload))
        return header + meta_bytes + payload

    def send_frame(self, writer: asyncio.StreamWriter, msg_type: int, metadata: dict, payload: bytes = b"") -> None:
        if not writer.is_closing():
            writer.write(self.pack_frame(msg_type, metadata, payload))

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_addr = writer.get_extra_info("peername")
        client_id = f"{peer_addr[0]}:{peer_addr[1]}" if peer_addr else "unknown"
        self.active_clients[client_id] = writer
        logger.info("Accepted connection from %s", client_id)

        if self.on_connection_change:
            self.on_connection_change(client_id, True)

        try:
            while self.running and not writer.is_closing():
                header = await reader.readexactly(HEADER_SIZE)
                magic, msg_type, meta_len, payload_len = struct.unpack(HEADER_STRUCT, header)

                if magic != MAGIC:
                    logger.warning("Invalid magic token received from %s; closing.", client_id)
                    writer.close()
                    break

                # Memory DoS prevention: enforce strict boundary on metadata and payload lengths
                if meta_len > 1_048_576 or meta_len < 0:
                    logger.warning("Metadata length exceeds 1MB limit (%d bytes) from %s; dropping.", meta_len, client_id)
                    writer.close()
                    break

                if msg_type == TYPE_TEXT and (payload_len > 52_428_800 or payload_len < 0):
                    logger.warning("Text payload length exceeds 50MB limit (%d bytes) from %s; dropping.", payload_len, client_id)
                    writer.close()
                    break

                meta_bytes = await reader.readexactly(meta_len)
                metadata = json.loads(meta_bytes.decode("utf-8"))
                transfer_id = metadata.get("id", str(time.time()))

                if msg_type == TYPE_PING:
                    self.send_frame(writer, TYPE_PING, {"status": "PONG", "time": time.time()})
                    await writer.drain()

                elif msg_type == TYPE_HANDSHAKE:
                    payload = await reader.readexactly(payload_len)
                    if len(payload) == 32:
                        client_pub = bytes(payload)
                        shared_secret = derive_shared_secret(self.private_key, client_pub)
                        pin = str(metadata.get("pin", ""))
                        session_key = derive_session_key(shared_secret, pin)
                        self.client_sessions[client_id] = session_key
                        if peer_addr:
                            self.client_sessions[peer_addr[0]] = session_key
                        client_name = metadata.get("client_name", "Android Device")
                        self.client_names[client_id] = client_name
                        logger.info("X25519 Handshake complete with %s (%s). Session key established.", client_id, client_name)
                        # Reply with server's 32-byte raw public key
                        self.send_frame(writer, TYPE_HANDSHAKE_ACK, {
                            "status": "OK",
                            "device": self.device_name
                        }, self.public_key_bytes)
                        await writer.drain()
                        if self.on_connection_change:
                            self.on_connection_change(client_id, True)
                    else:
                        logger.warning("Invalid handshake payload length (%d bytes) from %s", len(payload), client_id)

                elif msg_type == TYPE_DISCONNECT:
                    logger.info("Peer %s requested disconnect.", client_id)
                    break

                elif msg_type == TYPE_TEXT:
                    payload = await reader.readexactly(payload_len)
                    # Attempt AES-256-GCM decryption if session established
                    if client_id in self.client_sessions and len(payload) >= 28:
                        try:
                            payload = decrypt_gcm(self.client_sessions[client_id], bytes(payload))
                        except Exception as e:
                            logger.debug("Decryption fallback (plain payload?): %s", e)
                    mutable_buf = bytearray(payload)
                    transfer = PendingTransfer(transfer_id, msg_type, metadata, mutable_buf)
                    self.pending_offers[transfer_id] = transfer

                    # Start 600-second volatile memory TTL watcher
                    asyncio.create_task(self._ephemeral_memory_ttl(transfer_id, writer))

                    preview = metadata.get("preview", mutable_buf.decode("utf-8", errors="replace")[:64])
                    logger.info("Text offer received [%s]: %s", transfer_id, preview)

                    if self.auto_accept_text:
                        self.consume_text(transfer_id)
                        self.send_frame(writer, TYPE_ACK, {"id": transfer_id, "status": "COPIED"})
                        await writer.drain()
                    else:
                        if self.on_notify:
                            self.on_notify(transfer_id, "TEXT", preview, metadata)

                elif msg_type == TYPE_FILE:
                    transfer = PendingTransfer(transfer_id, msg_type, metadata)
                    self.pending_offers[transfer_id] = transfer

                    asyncio.create_task(self._ephemeral_memory_ttl(transfer_id, writer))

                    filename = metadata.get("filename", "unknown.bin")
                    size = metadata.get("size", payload_len)
                    logger.info("Incoming file offer [%s]: %s (%d bytes)", transfer_id, filename, size)

                    if self.on_notify:
                        self.on_notify(transfer_id, "FILE", f"{filename} ({size} bytes)", metadata)

                    if self.auto_accept_files:
                        transfer.accepted = True
                        transfer.accept_event.set()
                    else:
                        # Await user consent or TTL expiry
                        try:
                            await asyncio.wait_for(transfer.accept_event.wait(), timeout=600.0)
                        except asyncio.TimeoutError:
                            transfer.rejected = True

                    if transfer_id not in self.pending_offers or transfer.rejected:
                        self.send_frame(writer, TYPE_REJECT, {"id": transfer_id, "reason": "REJECTED_OR_EXPIRED"})
                        await writer.drain()
                        continue

                    # Active-Lock Pipeline: User accepted; authorization sent
                    self.send_frame(writer, TYPE_ACCEPT, {"id": transfer_id})
                    await writer.drain()

                    # Stream binary chunks to disk with on-the-fly SHA-256 calculation
                    await self._stream_incoming_file(reader, writer, metadata, transfer_id)

                elif msg_type == TYPE_ACCEPT:
                    logger.info("Peer accepted transfer offer: %s", transfer_id)
                    if transfer_id in self.pending_offers:
                        self.pending_offers[transfer_id].accepted = True
                        self.pending_offers[transfer_id].accept_event.set()

                elif msg_type == TYPE_REJECT:
                    logger.info("Peer rejected transfer: %s", transfer_id)
                    if transfer_id in self.pending_offers:
                        self.pending_offers[transfer_id].rejected = True
                        self.pending_offers[transfer_id].accept_event.set()

                elif msg_type == TYPE_ACK:
                    logger.info("Transfer acknowledged by peer: %s", metadata)

        except (asyncio.IncompleteReadError, ConnectionResetError, ConnectionAbortedError):
            logger.info("Client disconnected: %s", client_id)
        except Exception as e:
            logger.error("Error handling client %s: %s", client_id, e)
        finally:
            self.active_clients.pop(client_id, None)
            if not writer.is_closing():
                writer.close()
            if self.on_connection_change:
                self.on_connection_change(client_id, False)

    async def _ephemeral_memory_ttl(self, transfer_id: str, writer: Optional[asyncio.StreamWriter] = None) -> None:
        """Strict 600-second volatile RAM holding timer."""
        await asyncio.sleep(600)
        if transfer_id in self.pending_offers:
            item = self.pending_offers.pop(transfer_id)
            if not item.accepted:
                item.purge_memory()
                logger.info("TTL (600s) expired for %s. Volatile memory purged.", transfer_id)
                if writer and not writer.is_closing():
                    try:
                        self.send_frame(writer, TYPE_REJECT, {"id": transfer_id, "reason": "TIMEOUT_10M"})
                        await writer.drain()
                    except Exception:
                        pass

    def accept_transfer(self, transfer_id: str) -> bool:
        """Manually approve pending file offer from UI/Toast."""
        if transfer_id in self.pending_offers:
            item = self.pending_offers[transfer_id]
            item.accepted = True
            item.timer_stopped = True
            item.state = "DOWNLOADING"
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(item.accept_event.set)
            else:
                item.accept_event.set()
            return True
        return False

    def reject_transfer(self, transfer_id: str) -> bool:
        """Manually decline pending offer from UI/Toast."""
        if transfer_id in self.pending_offers:
            item = self.pending_offers[transfer_id]
            item.rejected = True
            item.timer_stopped = True
            item.state = "REJECTED"
            item.purge_memory()
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(item.accept_event.set)
            else:
                item.accept_event.set()
            return True
        return False

    def copy_text(self, transfer_id: str) -> Optional[str]:
        """Copy received ephemeral text payload to clipboard and mark as copied without removing from RAM buffer."""
        if transfer_id in self.pending_offers:
            item = self.pending_offers[transfer_id]
            if item.payload_data:
                try:
                    text = item.payload_data.decode("utf-8")
                    pyperclip.copy(text)
                    item.copied = True
                    logger.info("Text copied to clipboard (retained in 10m RAM buffer): %s", transfer_id)
                    return text
                except Exception as e:
                    logger.error("Failed to copy text to clipboard: %s", e)
        return None

    def consume_text(self, transfer_id: str) -> Optional[str]:
        """Copy received ephemeral text payload to clipboard and retain in 10m RAM buffer."""
        return self.copy_text(transfer_id)

    async def _stream_incoming_file(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        metadata: dict,
        transfer_id: str
    ) -> None:
        raw_name = metadata.get("filename", f"transfer_{int(time.time())}.bin")
        # Strict filename sanitization: strip directory separators, null bytes, and path traversal sequences
        safe_name = os.path.basename(raw_name.replace("\\", "/")).replace("\x00", "").strip()
        if not safe_name or safe_name in (".", ".."):
            safe_name = f"transfer_{int(time.time())}.bin"

        target_path = os.path.abspath(os.path.join(self.save_dir, safe_name))
        save_dir_abs = os.path.abspath(self.save_dir)

        # Path traversal guard: ensure target file remains inside save_dir
        if not target_path.startswith(save_dir_abs):
            logger.error("Path traversal attempt detected from %s for filename: %s", transfer_id, raw_name)
            raise PermissionError("Path traversal outside save directory rejected.")
        total_size = metadata.get("size", 0)
        bytes_received = 0
        hasher = hashlib.sha256()

        logger.info("Starting active-lock stream for %s (%d bytes)", safe_name, total_size)

        try:
            with open(target_path, "wb") as f:
                while bytes_received < total_size:
                    to_read = min(65536, total_size - bytes_received)
                    chunk = await reader.read(to_read)
                    if not chunk:
                        raise ConnectionError("Active stream interrupted prematurely.")
                    f.write(chunk)
                    hasher.update(chunk)
                    bytes_received += len(chunk)
                    if transfer_id in self.pending_offers:
                        item = self.pending_offers[transfer_id]
                        item.bytes_transferred = bytes_received
                        item.progress = (bytes_received / total_size) if total_size > 0 else 0.0
                    if self.on_transfer_progress:
                        self.on_transfer_progress(transfer_id, bytes_received, total_size)

            # Await trailing TRANSFER_FIN frame with checksum
            fin_header = await reader.readexactly(HEADER_SIZE)
            _, fin_type, fin_meta_len, _ = struct.unpack(HEADER_STRUCT, fin_header)
            fin_meta = json.loads((await reader.readexactly(fin_meta_len)).decode("utf-8"))

            computed_sha = hasher.hexdigest()
            expected_sha = fin_meta.get("sha256", "")

            if computed_sha.lower() == expected_sha.lower():
                logger.info("SHA-256 match (%s). Transfer complete.", computed_sha)
                if transfer_id in self.pending_offers:
                    self.pending_offers[transfer_id].state = "COMPLETED"
                    self.pending_offers[transfer_id].progress = 1.0
                self.send_frame(writer, TYPE_ACK, {"id": transfer_id, "status": "SUCCESS", "sha256": computed_sha})
                await writer.drain()
                if self.on_transfer_complete:
                    self.on_transfer_complete(transfer_id, target_path, True)
            else:
                logger.error("SHA-256 mismatch! Received: %s, Computed: %s", expected_sha, computed_sha)
                if transfer_id in self.pending_offers:
                    self.pending_offers[transfer_id].state = "REJECTED"
                if os.path.exists(target_path):
                    os.remove(target_path)
                self.send_frame(writer, TYPE_REJECT, {"id": transfer_id, "status": "INTEGRITY_FAIL"})
                await writer.drain()
                if self.on_transfer_complete:
                    self.on_transfer_complete(transfer_id, target_path, False)

        except Exception as e:
            logger.error("File stream failed: %s", e)
            if transfer_id in self.pending_offers:
                self.pending_offers[transfer_id].state = "REJECTED"
            if os.path.exists(target_path):
                os.remove(target_path)
            self.send_frame(writer, TYPE_REJECT, {"id": transfer_id, "reason": str(e)})
            await writer.drain()
            if self.on_transfer_complete:
                self.on_transfer_complete(transfer_id, target_path, False)

    def disconnect_peer(self) -> None:
        """Gracefully disconnect all active peers."""
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._disconnect_all(), self.loop)

    async def _disconnect_all(self) -> None:
        for cid, writer in list(self.active_clients.items()):
            try:
                if not writer.is_closing():
                    self.send_frame(writer, TYPE_DISCONNECT, {"reason": "USER_DISCONNECT"})
                    await writer.drain()
                    writer.close()
            except Exception:
                pass
        self.active_clients.clear()
        self.client_sessions.clear()
        self.client_names.clear()
        if self.on_connection_change:
            self.on_connection_change("", False)

    async def push_text_to_peer(self, host: str, port: int, text: str) -> bool:
        """Push a text snippet to a remote BoltP2P peer (default mobile port 58242)."""
        if not host or host in ("127.0.0.1", "0.0.0.0", "localhost"):
            logger.warning("No mobile peer target available to push text.")
            return False
        # If target port is the PC's own server port (58241), redirect to mobile server port (58242)
        target_port = 58242 if port == self.port else port
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, target_port),
                timeout=5.0
            )
            # Encrypt with session key if paired
            session_key = self.client_sessions.get(host)
            if not session_key:
                for cid, sk in self.client_sessions.items():
                    if host in cid:
                        session_key = sk
                        break

            payload = text.encode("utf-8")
            if session_key:
                try:
                    payload = encrypt_gcm(session_key, payload)
                except Exception as e:
                    logger.debug("Encryption exception, using plain payload: %s", e)

            meta = {
                "id": f"text_{int(time.time()*1000)}",
                "type": "TEXT",
                "preview": text[:64],
                "time": time.time(),
                "encrypted": session_key is not None,
            }

            self.send_frame(writer, TYPE_TEXT, meta, payload)
            await writer.drain()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("Successfully pushed text to %s:%d", host, target_port)
            return True
        except Exception as e:
            logger.error("Failed to push text to peer %s:%d: %s", host, target_port, e)
            return False

    async def push_file_to_peer(
        self,
        host: str,
        port: int,
        filepath: str,
        on_progress: Optional[Callable[[int, int], None]] = None
    ) -> bool:
        """Send a local file to a remote BoltP2P peer."""
        if not host or host in ("127.0.0.1", "0.0.0.0", "localhost"):
            logger.warning("No mobile peer target available to push file.")
            return False
        if not os.path.exists(filepath):
            logger.error("File does not exist: %s", filepath)
            return False
        target_port = 58242 if port == self.port else port
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, target_port),
                timeout=6.0
            )
            filename = os.path.basename(filepath)
            total_size = os.path.getsize(filepath)
            transfer_id = f"file_{int(time.time()*1000)}"

            meta = {
                "id": transfer_id,
                "filename": filename,
                "size": total_size,
            }
            # 1. Send Offer
            self.send_frame(writer, TYPE_FILE, meta)
            await writer.drain()

            # 2. Await Peer Acceptance (give user up to 5 minutes to accept on mobile)
            header = await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=300.0)
            _, msg_type, meta_len, _ = struct.unpack(HEADER_STRUCT, header)
            if meta_len > 0:
                await reader.readexactly(meta_len)

            if msg_type != TYPE_ACCEPT:
                logger.info("Remote peer declined file offer (type=%d).", msg_type)
                writer.close()
                return False

            # 3. Stream 64KB chunks with SHA-256
            hasher = hashlib.sha256()
            sent = 0
            with open(filepath, "rb") as f:
                while sent < total_size:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    writer.write(chunk)
                    hasher.update(chunk)
                    sent += len(chunk)
                    if on_progress:
                        on_progress(sent, total_size)
                    await writer.drain()

            # 4. Send FIN with checksum
            fin_meta = {"id": transfer_id, "sha256": hasher.hexdigest()}
            self.send_frame(writer, TYPE_FIN, fin_meta)
            await writer.drain()

            # 5. Await ACK
            ack_header = await asyncio.wait_for(reader.readexactly(HEADER_SIZE), timeout=20.0)
            _, ack_type, ack_meta_len, _ = struct.unpack(HEADER_STRUCT, ack_header)
            if ack_meta_len > 0:
                await reader.readexactly(ack_meta_len)

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info("Successfully pushed file %s to %s:%d", filename, host, target_port)
            return ack_type == TYPE_ACK
        except Exception as e:
            logger.error("Failed to push file to peer %s:%d: %s", host, target_port, e)
            return False
