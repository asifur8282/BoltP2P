package com.jiffboltp2p.client.data

import androidx.annotation.OptIn
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage

class QRCodeScannerAnalyzer(
    private val onQRCodeScanned: (String) -> Unit
) : ImageAnalysis.Analyzer {

    private val scanner = BarcodeScanning.getClient()
    private var isScanning = true

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(imageProxy: ImageProxy) {
        val mediaImage = imageProxy.image
        if (mediaImage != null && isScanning) {
            val image = InputImage.fromMediaImage(mediaImage, imageProxy.imageInfo.rotationDegrees)
            scanner.process(image)
                .addOnSuccessListener { barcodes ->
                    for (barcode in barcodes) {
                        if (barcode.valueType == Barcode.TYPE_TEXT || barcode.valueType == Barcode.TYPE_UNKNOWN) {
                            val raw = barcode.rawValue
                            if (!raw.isNullOrBlank()) {
                                isScanning = false
                                onQRCodeScanned(raw)
                                break
                            }
                        }
                    }
                }
                .addOnCompleteListener {
                    imageProxy.close()
                }
        } else {
            imageProxy.close()
        }
    }

    fun resumeScanning() {
        isScanning = true
    }
}

