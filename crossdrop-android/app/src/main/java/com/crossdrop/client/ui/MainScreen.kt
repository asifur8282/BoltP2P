package com.crossdrop.client.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.view.PreviewView
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.crossdrop.client.data.CameraStreamManager
import com.crossdrop.client.data.CrossDropSocketClient
import com.crossdrop.client.ui.theme.*
import kotlinx.coroutines.launch

@Composable
fun MainScreen(
    socketClient: CrossDropSocketClient,
    cameraStreamManager: CameraStreamManager,
    clipboardText: String,
    hasCameraPermission: Boolean,
    onRequestCameraPermission: () -> Unit,
    onManualConnect: (String, Int) -> Unit,
    activeHost: String,
    activePort: Int,
    connectionStatus: String,
    modifier: Modifier = Modifier
) {
    val coroutineScope = rememberCoroutineScope()
    val context = LocalContext.current
    val haptic = LocalHapticFeedback.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var imageCapture: ImageCapture? by remember { mutableStateOf(null) }
    var transferProgress by remember { mutableFloatStateOf(0f) }
    var isStreaming by remember { mutableStateOf(false) }
    var statusMessage by remember { mutableStateOf("") }
    var showConfigDialog by remember { mutableStateOf(false) }

    // File picker launcher
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            coroutineScope.launch {
                isStreaming = true
                statusMessage = "Streaming file to PC..."
                try {
                    val contentResolver = context.contentResolver
                    val cursor = contentResolver.query(uri, null, null, null, null)
                    val filename = cursor?.use {
                        if (it.moveToFirst()) {
                            val nameIdx = it.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                            if (nameIdx >= 0) it.getString(nameIdx) else "transfer.bin"
                        } else "transfer.bin"
                    } ?: "transfer.bin"

                    val size = cursor?.use {
                        if (it.moveToFirst()) {
                            val sizeIdx = it.getColumnIndex(android.provider.OpenableColumns.SIZE)
                            if (sizeIdx >= 0) it.getLong(sizeIdx) else -1L
                        } else -1L
                    } ?: -1L

                    val inStream = contentResolver.openInputStream(uri)
                    if (inStream != null) {
                        val realSize = if (size > 0) size else inStream.available().toLong()
                        val success = socketClient.streamInputStream(filename, realSize, inStream) { sent, total ->
                            transferProgress = if (total > 0) sent.toFloat() / total.toFloat() else 0.5f
                        }
                        statusMessage = if (success) "File sent & verified!" else "Transfer failed or declined."
                    }
                } catch (e: Exception) {
                    statusMessage = "File error: ${e.message}"
                } finally {
                    isStreaming = false
                    transferProgress = 0f
                }
            }
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CarbonBase)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 16.dp, vertical = 10.dp)
            .verticalScroll(rememberScrollState())
    ) {
        // 1. App Bar with Live Socket Dot
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 4.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = "CrossDrop",
                    style = MaterialTheme.typography.headlineSmall,
                    color = TextPrimary
                )
                Text(
                    text = "Zero-Cloud P2P Sync",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary
                )
            }

            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(4.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.clickable { showConfigDialog = true }
            ) {
                Row(
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .clip(CircleShape)
                            .background(if (socketClient.isConnected) SignalSuccess else SignalWarning)
                    )
                    Text(
                        text = if (socketClient.isConnected) "PC Connected" else connectionStatus,
                        style = MaterialTheme.typography.labelMedium,
                        color = TextPrimary
                    )
                    Icon(
                        imageVector = Icons.Default.Settings,
                        contentDescription = "Config",
                        tint = TextSecondary,
                        modifier = Modifier.size(14.dp)
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // 2. Camera Viewfinder Card (Direct CameraX Viewfinder)
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .height(300.dp),
            shape = RoundedCornerShape(6.dp),
            colors = CardDefaults.cardColors(containerColor = CarbonSurface),
            border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
        ) {
            Box(modifier = Modifier.fillMaxSize()) {
                if (hasCameraPermission) {
                    AndroidView(
                        factory = { ctx ->
                            val previewView = PreviewView(ctx)
                            val cameraProviderFuture = androidx.camera.lifecycle.ProcessCameraProvider.getInstance(ctx)
                            cameraProviderFuture.addListener({
                                val cameraProvider = cameraProviderFuture.get()
                                val preview = Preview.Builder().build().also {
                                    it.setSurfaceProvider(previewView.surfaceProvider)
                                }
                                val capture = ImageCapture.Builder()
                                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                                    .build()
                                imageCapture = capture

                                val cameraSelector = CameraSelector.DEFAULT_BACK_CAMERA
                                try {
                                    cameraProvider.unbindAll()
                                    cameraProvider.bindToLifecycle(lifecycleOwner, cameraSelector, preview, capture)
                                } catch (e: Exception) {
                                    e.printStackTrace()
                                }
                            }, androidx.core.content.ContextCompat.getMainExecutor(ctx))
                            previewView
                        },
                        modifier = Modifier.fillMaxSize()
                    )
                } else {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally
                    ) {
                        Text(
                            text = "Camera Permission Required",
                            style = MaterialTheme.typography.bodyLarge,
                            color = TextPrimary
                        )
                        Text(
                            text = "Enable camera to stream direct in-memory photos to PC.",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary,
                            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp)
                        )
                        Button(
                            onClick = onRequestCameraPermission,
                            colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                            shape = RoundedCornerShape(4.dp)
                        ) {
                            Text("Grant Permission", color = Color.White)
                        }
                    }
                }

                // 2px Slim Linear Progress Bar on Top Edge
                if (isStreaming) {
                    LinearProgressIndicator(
                        progress = { transferProgress },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(3.dp)
                            .align(Alignment.TopCenter),
                        color = BrandAccent,
                        trackColor = CarbonSurface
                    )
                }

                // Shutter Button Overlay at Bottom Center
                if (hasCameraPermission) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .padding(bottom = 14.dp)
                    ) {
                        // Double-ring mechanical shutter button
                        Box(
                            contentAlignment = Alignment.Center,
                            modifier = Modifier
                                .size(64.dp)
                                .clip(CircleShape)
                                .background(CarbonElevated.copy(alpha = 0.8f))
                                .border(3.dp, Color.White, CircleShape)
                                .clickable(enabled = !isStreaming && imageCapture != null) {
                                    haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                    val capture = imageCapture ?: return@clickable
                                    isStreaming = true
                                    statusMessage = "Capturing direct to RAM..."
                                    cameraStreamManager.capturePhotoToMemory(
                                        imageCapture = capture,
                                        onSuccess = { byteBuffer ->
                                            coroutineScope.launch {
                                                statusMessage = "Streaming photo to PC..."
                                                val filename = "IMG_${System.currentTimeMillis()}.jpg"
                                                val success = socketClient.streamMemoryBuffer(
                                                    filename = filename,
                                                    buffer = byteBuffer
                                                ) { sent, total ->
                                                    transferProgress = if (total > 0) sent.toFloat() / total.toFloat() else 0.5f
                                                }
                                                statusMessage = if (success) "Photo sent & verified!" else "Transfer failed or declined."
                                                isStreaming = false
                                                transferProgress = 0f
                                            }
                                        },
                                        onError = { exc ->
                                            statusMessage = "Capture error: ${exc.message}"
                                            isStreaming = false
                                        }
                                    )
                                }
                        ) {
                            Box(
                                modifier = Modifier
                                    .size(46.dp)
                                    .clip(CircleShape)
                                    .background(Color.White)
                            )
                        }
                    }
                }
            }
        }

        if (statusMessage.isNotEmpty()) {
            Spacer(modifier = Modifier.height(8.dp))
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(4.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = statusMessage,
                    style = MaterialTheme.typography.labelMedium,
                    color = BrandAccent,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                )
            }
        }

        Spacer(modifier = Modifier.height(14.dp))

        // 3. Quick Clipboard Push Section
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(6.dp),
            colors = CardDefaults.cardColors(containerColor = CarbonSurface),
            border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(
                    text = "QUICK CLIPBOARD PUSH",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary,
                    fontWeight = FontWeight.SemiBold
                )

                Spacer(modifier = Modifier.height(6.dp))

                Surface(
                    color = CarbonBase,
                    shape = RoundedCornerShape(4.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(8.dp)) {
                        Text(
                            text = if (clipboardText.isNotEmpty()) "Detected in Clipboard:" else "Clipboard is empty",
                            style = MaterialTheme.typography.labelSmall,
                            color = TextSecondary
                        )
                        if (clipboardText.isNotEmpty()) {
                            Text(
                                text = "\"$clipboardText\"",
                                style = MaterialTheme.typography.bodyLarge,
                                maxLines = 2,
                                overflow = TextOverflow.Ellipsis,
                                color = TextPrimary,
                                modifier = Modifier.padding(top = 2.dp)
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(8.dp))

                Button(
                    onClick = {
                        if (clipboardText.isNotEmpty()) {
                            haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                            coroutineScope.launch {
                                statusMessage = "Pushing text to PC..."
                                val ok = socketClient.sendInstantText(clipboardText)
                                statusMessage = if (ok) "Text pushed to PC clipboard!" else "Push failed. Check connection."
                            }
                        }
                    },
                    enabled = clipboardText.isNotEmpty() && !isStreaming,
                    colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                    shape = RoundedCornerShape(4.dp),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Text(
                        text = "Push Clipboard to PC Now",
                        fontWeight = FontWeight.SemiBold,
                        color = Color.White
                    )
                }
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // 4. Secondary Action Tiles (File Transfer & Manual Connect)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(6.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier
                    .weight(1f)
                    .clickable { filePicker.launch("*/*") }
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(
                        imageVector = Icons.Default.Description,
                        contentDescription = "File Transfer",
                        tint = BrandAccent,
                        modifier = Modifier.size(24.dp)
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = "Stream File",
                        style = MaterialTheme.typography.titleMedium,
                        fontSize = 14.sp
                    )
                    Text(
                        text = "Select & send",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextSecondary
                    )
                }
            }

            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(6.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier
                    .weight(1f)
                    .clickable { showConfigDialog = true }
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(
                        imageVector = Icons.Default.Settings,
                        contentDescription = "Connection",
                        tint = TextSecondary,
                        modifier = Modifier.size(24.dp)
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = "PC Target",
                        style = MaterialTheme.typography.titleMedium,
                        fontSize = 14.sp
                    )
                    Text(
                        text = "$activeHost:$activePort",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextSecondary,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }
            }
        }
    }

    // Target IP Configuration Dialog
    if (showConfigDialog) {
        var ipInput by remember { mutableStateOf(activeHost) }
        var portInput by remember { mutableStateOf(activePort.toString()) }

        AlertDialog(
            onDismissRequest = { showConfigDialog = false },
            title = {
                Text("Desktop Daemon Target", style = MaterialTheme.typography.titleMedium)
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "Enter the IP address of your Windows 11 PC on Wi-Fi (or 10.0.2.2 if testing in emulator):",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextSecondary
                    )
                    OutlinedTextField(
                        value = ipInput,
                        onValueChange = { ipInput = it },
                        label = { Text("PC IP Address") },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BrandAccent,
                            unfocusedBorderColor = BorderSubtle
                        )
                    )
                    OutlinedTextField(
                        value = portInput,
                        onValueChange = { portInput = it },
                        label = { Text("Port (default 58241)") },
                        singleLine = true,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BrandAccent,
                            unfocusedBorderColor = BorderSubtle
                        )
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        val port = portInput.toIntOrNull() ?: 58241
                        onManualConnect(ipInput.trim(), port)
                        showConfigDialog = false
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = BrandAccent)
                ) {
                    Text("Save & Connect")
                }
            },
            dismissButton = {
                TextButton(onClick = { showConfigDialog = false }) {
                    Text("Cancel", color = TextSecondary)
                }
            },
            containerColor = CarbonSurface,
            textContentColor = TextPrimary
        )
    }
}
