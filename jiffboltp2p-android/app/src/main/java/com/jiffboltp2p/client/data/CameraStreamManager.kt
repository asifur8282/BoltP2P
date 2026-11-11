package com.jiffboltp2p.client.data

import android.content.Context
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.core.content.ContextCompat
import java.nio.ByteBuffer

/**
 * CameraStreamManager:
 * Intercepts raw camera frame buffers via CameraX and pipes them directly into
 * an in-memory ByteBuffer, strictly bypassing flash storage / disk caching.
 */
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
                    try {
                        val plane = image.planes[0]
                        val buffer = plane.buffer
                        val duplicate = ByteBuffer.allocate(buffer.remaining())
                        duplicate.put(buffer)
                        duplicate.flip()
                        onSuccess(duplicate)
                    } catch (e: Exception) {
                        onError(ImageCaptureException(ImageCapture.ERROR_UNKNOWN, "Buffer extraction failed", e))
                    } finally {
                        image.close()
                    }
                }

                override fun onError(exception: ImageCaptureException) {
                    onError(exception)
                }
            }
        )
    }
}
