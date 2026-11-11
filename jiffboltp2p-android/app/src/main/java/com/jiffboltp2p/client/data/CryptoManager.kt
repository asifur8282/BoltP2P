package com.jiffboltp2p.client.data

import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.PrivateKey
import java.security.PublicKey
import java.security.SecureRandom
import java.security.spec.NamedParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

object CryptoManager {

    // Standard ASN.1 SubjectPublicKeyInfo prefix for X25519 (12 bytes)
    private val X25519_ASN1_HEADER = byteArrayOf(
        0x30.toByte(), 0x2a.toByte(), 0x30.toByte(), 0x05.toByte(),
        0x06.toByte(), 0x03.toByte(), 0x2b.toByte(), 0x65.toByte(), 0x6e.toByte(),
        0x03.toByte(), 0x21.toByte(), 0x00.toByte()
    )

    fun generateKeyPair(): KeyPair {
        val kpg = KeyPairGenerator.getInstance("XDH")
        return kpg.generateKeyPair()
    }

    fun rawBytesToPublicKey(rawBytes: ByteArray): PublicKey {
        val fullBytes = X25519_ASN1_HEADER + rawBytes
        val spec = X509EncodedKeySpec(fullBytes)
        val kf = KeyFactory.getInstance("XDH")
        return kf.generatePublic(spec)
    }

    fun publicKeyToRawBytes(publicKey: PublicKey): ByteArray {
        val encoded = publicKey.encoded
        return encoded.takeLast(32).toByteArray()
    }

    fun computeSharedSecret(privateKey: PrivateKey, peerRawPub: ByteArray): ByteArray {
        val peerPublicKey = rawBytesToPublicKey(peerRawPub)
        val ka = KeyAgreement.getInstance("XDH")
        ka.init(privateKey)
        ka.doPhase(peerPublicKey, true)
        return ka.generateSecret()
    }

    fun deriveSessionKey(sharedSecret: ByteArray, pin: String): ByteArray {
        val salt = if (pin.isNotEmpty()) pin.toByteArray(Charsets.UTF_8) else ByteArray(32)
        val info = "jiffboltp2p-x25519-aesgcm".toByteArray(Charsets.UTF_8)

        // HKDF-Extract(salt, sharedSecret) -> PRK
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(salt, "HmacSHA256"))
        val prk = mac.doFinal(sharedSecret)

        // HKDF-Expand(PRK, info, 32) -> OKM
        mac.init(SecretKeySpec(prk, "HmacSHA256"))
        mac.update(info)
        mac.update(0x01.toByte())
        val okm = mac.doFinal()
        return okm.copyOf(32)
    }

    fun encryptGcm(key: ByteArray, plaintext: ByteArray): ByteArray {
        val iv = ByteArray(12).also { SecureRandom().nextBytes(it) }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        val ciphertext = cipher.doFinal(plaintext)
        return iv + ciphertext
    }

    fun decryptGcm(key: ByteArray, data: ByteArray): ByteArray {
        if (data.size < 28) {
            throw IllegalArgumentException("Encrypted data too short for GCM (minimum 28 bytes required)")
        }
        val iv = data.copyOfRange(0, 12)
        val ciphertext = data.copyOfRange(12, data.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext)
    }

    fun generatePairingPin(): String {
        val rnd = SecureRandom()
        return "%06d".format(rnd.nextInt(1_000_000))
    }
}

