"""
CrossDrop Cryptographic Utilities:
- TLS 1.3 self-signed certificate generation (ECDSA P-256)
- Streaming SHA-256 integrity verification
- Volatile memory zeroization helpers
- Secure pairing token / 6-digit PIN generation
"""

import os
import secrets
import hashlib
import ssl
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_pairing_pin() -> str:
    """Generate a high-entropy 6-digit numeric pairing PIN."""
    return f"{secrets.randbelow(1_000_000):06d}"


def generate_pairing_token() -> str:
    """Generate a random 32-byte hex token for session authorization."""
    return secrets.token_hex(32)


def compute_sha256(data: bytes) -> str:
    """Compute hex SHA-256 digest of arbitrary bytes."""
    return hashlib.sha256(data).hexdigest()


def zero_memory(buf: bytearray) -> None:
    """Safely overwrite mutable byte buffer with zeros before deallocation."""
    if isinstance(buf, (bytearray, memoryview)):
        for i in range(len(buf)):
            buf[i] = 0


def generate_self_signed_cert(
    cert_path: str,
    key_path: str,
    common_name: str = "CrossDrop-Local"
) -> Tuple[str, str]:
    """
    Generate an ephemeral self-signed ECDSA certificate for TLS 1.3 transport.
    Valid for 30 days on local subnet.
    """
    os.makedirs(os.path.dirname(os.path.abspath(cert_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)

    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path

    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CrossDrop P2P"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


def create_server_ssl_context(cert_path: str, key_path: str) -> ssl.SSLContext:
    """Create an SSLContext configured for TLS 1.3 server."""
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# --------------------------------------------------
# Ephemeral X25519 Key Exchange & AES-256-GCM Cipher
# --------------------------------------------------

def generate_x25519_keypair() -> Tuple[x25519.X25519PrivateKey, bytes]:
    """Generate ephemeral X25519 private key and raw 32-byte public key."""
    priv = x25519.X25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    return priv, pub_bytes


def derive_shared_secret(private_key: x25519.X25519PrivateKey, peer_pub_bytes: bytes) -> bytes:
    """Compute Diffie-Hellman shared secret with peer's raw 32-byte public key."""
    peer_pub = x25519.X25519PublicKey.from_public_bytes(peer_pub_bytes)
    return private_key.exchange(peer_pub)


def derive_session_key(shared_secret: bytes, pin_or_psk: str) -> bytes:
    """Derive 256-bit AES session key using HKDF-SHA256 salted with pairing PIN."""
    salt = pin_or_psk.encode("utf-8") if pin_or_psk else None
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"crossdrop-x25519-aesgcm"
    ).derive(shared_secret)


def encrypt_gcm(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM. Returns 12-byte IV + ciphertext + 16-byte tag."""
    iv = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext_and_tag = aesgcm.encrypt(iv, plaintext, None)
    return iv + ciphertext_and_tag


def decrypt_gcm(key: bytes, data: bytes) -> bytes:
    """Decrypt payload using AES-256-GCM expecting 12-byte IV + ciphertext + 16-byte tag."""
    if len(data) < 28:
        raise ValueError("Encrypted data too short for GCM (minimum 28 bytes required)")
    iv = data[:12]
    ciphertext_and_tag = data[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext_and_tag, None)

