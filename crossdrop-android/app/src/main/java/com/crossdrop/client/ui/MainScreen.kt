package com.crossdrop.client.ui

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.webkit.MimeTypeMap
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import com.crossdrop.client.MainActivity
import com.crossdrop.client.SessionSharedItem
import com.crossdrop.client.data.CameraStreamManager
import com.crossdrop.client.data.CrossDropSocketClient
import com.crossdrop.client.data.IncomingFileOffer
import com.crossdrop.client.data.QRCodeHelper
import com.crossdrop.client.data.QRCodeScannerAnalyzer
import com.crossdrop.client.ui.theme.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.File

fun getLocalWifiIp(): String {
    try {
        val interfaces = java.net.NetworkInterface.getNetworkInterfaces()
        while (interfaces.hasMoreElements()) {
            val intf = interfaces.nextElement()
            val addrs = intf.inetAddresses
            while (addrs.hasMoreElements()) {
                val addr = addrs.nextElement()
                if (!addr.isLoopbackAddress && addr is java.net.Inet4Address) {
                    val ip = addr.hostAddress ?: ""
                    if (ip.isNotEmpty() && !ip.startsWith("127.")) {
                        return ip
                    }
                }
            }
        }
    } catch (_: Exception) {}
    return "127.0.0.1"
}

fun openFileOrContent(context: Context, item: SessionSharedItem) {
    try {
        if (!item.filePath.isNullOrEmpty()) {
            val file = File(item.filePath)
            if (file.exists()) {
                val uri = FileProvider.getUriForFile(
                    context,
                    "${context.packageName}.fileprovider",
                    file
                )
                val ext = file.extension.lowercase()
                val mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "*/*"
                val intent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, mime)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(Intent.createChooser(intent, "Open with..."))
                return
            }
        }
        if (!item.uriString.isNullOrEmpty()) {
            val uri = Uri.parse(item.uriString)
            val mime = context.contentResolver.getType(uri) ?: "*/*"
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, mime)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            context.startActivity(Intent.createChooser(intent, "Open with..."))
            return
        }
        Toast.makeText(context, "File path not available", Toast.LENGTH_SHORT).show()
    } catch (e: Exception) {
        Toast.makeText(context, "Could not open file: ${e.message}", Toast.LENGTH_SHORT).show()
    }
}

@Composable
fun MainScreen(
    socketClient: CrossDropSocketClient,
    cameraStreamManager: CameraStreamManager,
    clipboardText: String,
    hasCameraPermission: Boolean,
    onRequestCameraPermission: () -> Unit,
    isConnected: Boolean,
    connectionStatus: String,
    activeHost: String,
    activePort: Int,
    incomingOffer: IncomingFileOffer?,
    sharedHistory: MutableList<SessionSharedItem>,
    isDownloading: Boolean = false,
    downloadProgress: Float = 0f,
    downloadFileName: String = "",
    downloadStatusText: String = "",
    onAcceptOffer: (String) -> Unit,
    onRejectOffer: (String) -> Unit,
    onConnect: (String, Int, String) -> Unit,
    onDisconnect: () -> Unit,
    modifier: Modifier = Modifier
) {
    val coroutineScope = rememberCoroutineScope()
    val context = LocalContext.current
    val haptic = LocalHapticFeedback.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val clipboardManager = LocalClipboardManager.current

    var selectedTab by remember { mutableIntStateOf(0) } // 0: Scan QR, 1: Show My QR, 2: Enter IP / Code
    var manualIp by remember { mutableStateOf(activeHost) }
    var manualPort by remember { mutableStateOf(activePort.toString()) }
    var manualPin by remember { mutableStateOf("") }

    var textInput by remember { mutableStateOf("") }
    LaunchedEffect(clipboardText) {
        if (textInput.isEmpty() && clipboardText.isNotEmpty()) {
            textInput = clipboardText
        }
    }

    var imageCapture: ImageCapture? by remember { mutableStateOf(null) }
    var transferProgress by remember { mutableFloatStateOf(0f) }
    var isStreaming by remember { mutableStateOf(false) }
    var statusMessage by remember { mutableStateOf("") }

    // File picker launcher with Fix 2 (Single synchronous cursor query)
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent()
    ) { uri: Uri? ->
        if (uri != null) {
            coroutineScope.launch {
                isStreaming = true
                statusMessage = "Streaming file to PC..."
                try {
                    val contentResolver = context.contentResolver
                    var filename = "transfer.bin"
                    var size = -1L

                    // Fix 2: Single cursor query block; immediately closed to avoid cursor out-of-bounds crash
                    contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                        if (cursor.moveToFirst()) {
                            val nameIdx = cursor.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                            if (nameIdx >= 0) filename = cursor.getString(nameIdx)
                            val sizeIdx = cursor.getColumnIndex(android.provider.OpenableColumns.SIZE)
                            if (sizeIdx >= 0) size = cursor.getLong(sizeIdx)
                        }
                    }

                    if (size <= 0) {
                        try {
                            contentResolver.openFileDescriptor(uri, "r")?.use { pfd ->
                                size = pfd.statSize
                            }
                        } catch (_: Exception) {}
                    }

                    val inStream = contentResolver.openInputStream(uri)
                    if (inStream != null) {
                        val realSize = if (size > 0) size else inStream.available().toLong()
                        val success = socketClient.streamInputStream(filename, realSize, inStream) { sent, total ->
                            transferProgress = if (total > 0) sent.toFloat() / total.toFloat() else 0.5f
                        }
                        if (success) {
                            val sizeStr = if (realSize > 1024 * 1024) "%.2f MB".format(realSize / (1024f * 1024f)) else "%.1f KB".format(realSize / 1024f)
                            sharedHistory.add(0, SessionSharedItem(
                                id = java.util.UUID.randomUUID().toString(),
                                title = filename,
                                subtitle = "Streamed to PC ($sizeStr) • Tap to View",
                                isOutgoing = true,
                                type = "FILE",
                                uriString = uri.toString()
                            ))
                            statusMessage = "File sent & verified!"
                        } else {
                            statusMessage = "Transfer failed or declined."
                        }
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

    // Fix 3: In-App Incoming Offer Alert Dialog with 10-Minute Countdown
    if (incomingOffer != null) {
        var remainingSeconds by remember(incomingOffer.transferId) { mutableIntStateOf(600) }
        LaunchedEffect(incomingOffer.transferId) {
            while (remainingSeconds > 0) {
                delay(1000L)
                remainingSeconds--
            }
            onRejectOffer(incomingOffer.transferId)
        }
        val mins = remainingSeconds / 60
        val secs = remainingSeconds % 60
        val countdownStr = "%02d:%02d".format(mins, secs)
        val fsize = incomingOffer.size
        val sizeStr = if (fsize > 1024 * 1024) "%.2f MB".format(fsize / (1024f * 1024f)) else "%.1f KB".format(fsize / 1024f)

        AlertDialog(
            onDismissRequest = { onRejectOffer(incomingOffer.transferId) },
            title = {
                Text(
                    text = "Incoming File Offer",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextPrimary
                )
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        text = "Remote peer is offering to send a file:",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextSecondary
                    )
                    Text(
                        text = incomingOffer.filename,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold,
                        color = BrandAccent
                    )
                    Text(
                        text = "File Size: $sizeStr",
                        style = MaterialTheme.typography.bodyMedium,
                        color = TextPrimary
                    )
                    Text(
                        text = "Offer expires in: $countdownStr",
                        style = MaterialTheme.typography.labelMedium,
                        color = SignalWarning,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = { onAcceptOffer(incomingOffer.transferId) },
                    colors = ButtonDefaults.buttonColors(containerColor = SignalSuccess),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text("Accept & Save", color = Color.White)
                }
            },
            dismissButton = {
                Button(
                    onClick = { onRejectOffer(incomingOffer.transferId) },
                    colors = ButtonDefaults.buttonColors(containerColor = CarbonElevated),
                    shape = RoundedCornerShape(4.dp)
                ) {
                    Text("Reject", color = SignalDanger)
                }
            },
            containerColor = CarbonSurface,
            shape = RoundedCornerShape(6.dp)
        )
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(CarbonBase)
            .statusBarsPadding()
            .navigationBarsPadding()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .verticalScroll(rememberScrollState())
    ) {
        // App Title Row
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
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "Zero-Cloud P2P Sync",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary
                )
            }
        }

        Spacer(modifier = Modifier.height(10.dp))

        // Sticky Status Bar (Connected vs Disconnected)
        if (isConnected) {
            // Sticky Connected Status Bar with Explicit Disconnect Button
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(6.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, SignalSuccess.copy(alpha = 0.5f)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(SignalSuccess)
                        )
                        Column {
                            Text(
                                text = "Connected to ${socketClient.peerDeviceName}",
                                style = MaterialTheme.typography.labelLarge,
                                fontWeight = FontWeight.Bold,
                                color = TextPrimary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                            Text(
                                text = "$activeHost:$activePort",
                                style = MaterialTheme.typography.labelSmall,
                                color = TextSecondary,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }

                    Button(
                        onClick = onDisconnect,
                        colors = ButtonDefaults.buttonColors(containerColor = CarbonElevated),
                        border = androidx.compose.foundation.BorderStroke(1.dp, SignalDanger),
                        shape = RoundedCornerShape(4.dp),
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                    ) {
                        Text(
                            text = "Disconnect",
                            style = MaterialTheme.typography.labelMedium,
                            color = SignalDanger,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
        } else {
            // Disconnected Segmented 3-Tab Bar
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(6.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(4.dp),
                    horizontalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    val tabs = listOf("Scan QR", "Show My QR", "Enter IP / Code")
                    tabs.forEachIndexed { index, title ->
                        val isSelected = selectedTab == index
                        Surface(
                            color = if (isSelected) BrandAccent else Color.Transparent,
                            shape = RoundedCornerShape(4.dp),
                            modifier = Modifier
                                .weight(1f)
                                .clickable { selectedTab = index }
                        ) {
                            Text(
                                text = title,
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal,
                                color = if (isSelected) Color.White else TextSecondary,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(vertical = 8.dp)
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // Disconnected Tab Content
            when (selectedTab) {
                0 -> {
                    // TAB 1: Scan QR (CameraX + ML Kit)
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(280.dp),
                        shape = RoundedCornerShape(6.dp),
                        colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                        border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
                    ) {
                        Box(modifier = Modifier.fillMaxSize()) {
                            if (hasCameraPermission) {
                                AndroidView(
                                    factory = { ctx ->
                                        val previewView = PreviewView(ctx)
                                        val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
                                        cameraProviderFuture.addListener({
                                            val cameraProvider = cameraProviderFuture.get()
                                            val preview = Preview.Builder().build().also {
                                                it.setSurfaceProvider(previewView.surfaceProvider)
                                            }
                                            val imageAnalysis = ImageAnalysis.Builder()
                                                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                                                .build()

                                            val analyzer = QRCodeScannerAnalyzer { qrRaw ->
                                                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                                try {
                                                    val json = JSONObject(qrRaw)
                                                    val ip = json.optString("ip", "")
                                                    val port = json.optInt("port", 58241)
                                                    val pin = json.optString("pin", "")
                                                    if (ip.isNotEmpty()) {
                                                        onConnect(ip, port, pin)
                                                    }
                                                } catch (_: Exception) {
                                                    val parts = qrRaw.trim().split(":")
                                                    if (parts.isNotEmpty()) {
                                                        val ip = parts[0]
                                                        val port = parts.getOrNull(1)?.toIntOrNull() ?: 58241
                                                        onConnect(ip, port, "")
                                                    }
                                                }
                                            }
                                            imageAnalysis.setAnalyzer(ContextCompat.getMainExecutor(ctx), analyzer)

                                            try {
                                                cameraProvider.unbindAll()
                                                cameraProvider.bindToLifecycle(
                                                    lifecycleOwner,
                                                    CameraSelector.DEFAULT_BACK_CAMERA,
                                                    preview,
                                                    imageAnalysis
                                                )
                                            } catch (e: Exception) {
                                                e.printStackTrace()
                                            }
                                        }, ContextCompat.getMainExecutor(ctx))
                                        previewView
                                    },
                                    modifier = Modifier.fillMaxSize()
                                )

                                // Overlay Scan Reticle
                                Box(
                                    modifier = Modifier
                                        .size(180.dp)
                                        .align(Alignment.Center)
                                        .border(2.dp, BrandAccent, RoundedCornerShape(8.dp))
                                )
                                Text(
                                    text = "Point camera at desktop or peer QR code",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = Color.White,
                                    modifier = Modifier
                                        .align(Alignment.BottomCenter)
                                        .padding(bottom = 12.dp)
                                        .background(CarbonBase.copy(alpha = 0.7f), RoundedCornerShape(4.dp))
                                        .padding(horizontal = 8.dp, vertical = 4.dp)
                                )
                            } else {
                                Column(
                                    modifier = Modifier
                                        .fillMaxSize()
                                        .padding(20.dp),
                                    verticalArrangement = Arrangement.Center,
                                    horizontalAlignment = Alignment.CenterHorizontally
                                ) {
                                    Text(
                                        text = "Camera Permission Required",
                                        style = MaterialTheme.typography.titleMedium,
                                        color = TextPrimary
                                    )
                                    Spacer(modifier = Modifier.height(6.dp))
                                    Text(
                                        text = "Grant camera permission to scan QR code.",
                                        style = MaterialTheme.typography.labelMedium,
                                        color = TextSecondary,
                                        textAlign = TextAlign.Center
                                    )
                                    Spacer(modifier = Modifier.height(12.dp))
                                    Button(
                                        onClick = onRequestCameraPermission,
                                        colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                                        shape = RoundedCornerShape(4.dp)
                                    ) {
                                        Text("Grant Camera Access", color = Color.White)
                                    }
                                }
                            }
                        }
                    }
                }

                1 -> {
                    // TAB 2: Show My QR
                    val phoneIp = remember { getLocalWifiIp() }
                    val phonePort = 58242
                    val qrBitmap = remember(phoneIp) {
                        val payload = JSONObject().apply {
                            put("ip", phoneIp)
                            put("port", phonePort)
                            put("device", Build.MODEL)
                        }.toString()
                        QRCodeHelper.generateQRCode(payload, 380)
                    }

                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(6.dp),
                        colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                        border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(16.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                text = "SCAN TO CONNECT TO THIS DEVICE",
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                color = TextSecondary
                            )
                            Spacer(modifier = Modifier.height(12.dp))
                            if (qrBitmap != null) {
                                Image(
                                    bitmap = qrBitmap.asImageBitmap(),
                                    contentDescription = "My QR Code",
                                    modifier = Modifier
                                        .size(200.dp)
                                        .clip(RoundedCornerShape(4.dp))
                                        .border(1.dp, BorderSubtle, RoundedCornerShape(4.dp))
                                )
                            }
                            Spacer(modifier = Modifier.height(12.dp))
                            Surface(
                                color = CarbonBase,
                                shape = RoundedCornerShape(4.dp),
                                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Column(
                                    modifier = Modifier.padding(10.dp),
                                    verticalArrangement = Arrangement.spacedBy(4.dp)
                                ) {
                                    Text(
                                        text = "Wi-Fi IP:  $phoneIp",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontFamily = FontFamily.Monospace,
                                        color = TextPrimary
                                    )
                                    Text(
                                        text = "Port:      $phonePort",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontFamily = FontFamily.Monospace,
                                        color = TextSecondary
                                    )
                                    Text(
                                        text = "Device:    ${Build.MODEL}",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontFamily = FontFamily.Monospace,
                                        color = TextSecondary
                                    )
                                }
                            }
                        }
                    }
                }

                2 -> {
                    // TAB 3: Enter IP / Code
                    Card(
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(6.dp),
                        colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                        border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(14.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp)
                        ) {
                            Text(
                                text = "MANUAL SOCKET CONNECTION",
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                color = TextSecondary
                            )

                            OutlinedTextField(
                                value = manualIp,
                                onValueChange = { manualIp = it },
                                label = { Text("Target IP Address") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = BrandAccent,
                                    unfocusedBorderColor = BorderSubtle,
                                    focusedTextColor = TextPrimary,
                                    unfocusedTextColor = TextPrimary
                                )
                            )

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                OutlinedTextField(
                                    value = manualPort,
                                    onValueChange = { manualPort = it },
                                    label = { Text("Port (58241)") },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(1f),
                                    colors = OutlinedTextFieldDefaults.colors(
                                        focusedBorderColor = BrandAccent,
                                        unfocusedBorderColor = BorderSubtle,
                                        focusedTextColor = TextPrimary,
                                        unfocusedTextColor = TextPrimary
                                    )
                                )

                                OutlinedTextField(
                                    value = manualPin,
                                    onValueChange = { manualPin = it },
                                    label = { Text("6-Digit PIN") },
                                    singleLine = true,
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                                    modifier = Modifier.weight(1f),
                                    colors = OutlinedTextFieldDefaults.colors(
                                        focusedBorderColor = BrandAccent,
                                        unfocusedBorderColor = BorderSubtle,
                                        focusedTextColor = TextPrimary,
                                        unfocusedTextColor = TextPrimary
                                    )
                                )
                            }

                            Button(
                                onClick = {
                                    val port = manualPort.toIntOrNull() ?: 58241
                                    onConnect(manualIp.trim(), port, manualPin.trim())
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                                shape = RoundedCornerShape(4.dp),
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(46.dp)
                            ) {
                                Text(
                                    text = "Connect to Device",
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = Color.White
                                )
                            }
                        }
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(14.dp))

        // Transfer Screen (Camera viewfinder + Quick Text Push + File Stream)
        if (isConnected) {
            // Camera Viewfinder Card
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(260.dp),
                shape = RoundedCornerShape(6.dp),
                colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
            ) {
                Box(modifier = Modifier.fillMaxSize()) {
                    if (hasCameraPermission) {
                        AndroidView(
                            factory = { ctx ->
                                val previewView = PreviewView(ctx)
                                val cameraProviderFuture = ProcessCameraProvider.getInstance(ctx)
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
                                }, ContextCompat.getMainExecutor(ctx))
                                previewView
                            },
                            modifier = Modifier.fillMaxSize()
                        )
                    } else {
                        Column(
                            modifier = Modifier
                                .fillMaxSize()
                                .padding(20.dp),
                            verticalArrangement = Arrangement.Center,
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            Text(
                                text = "Camera Permission Required",
                                style = MaterialTheme.typography.bodyLarge,
                                color = TextPrimary
                            )
                            Button(
                                onClick = onRequestCameraPermission,
                                colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                                shape = RoundedCornerShape(4.dp),
                                modifier = Modifier.padding(top = 10.dp)
                            ) {
                                Text("Grant Permission", color = Color.White)
                            }
                        }
                    }

                    // Progress bar
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

                    // Shutter Button Overlay
                    if (hasCameraPermission) {
                        Box(
                            modifier = Modifier
                                .align(Alignment.BottomCenter)
                                .padding(bottom = 12.dp)
                        ) {
                            Box(
                                contentAlignment = Alignment.Center,
                                modifier = Modifier
                                    .size(56.dp)
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
                                                    val bufferSize = byteBuffer.remaining().toLong()
                                                    val savedPath = try {
                                                        val cacheFile = File(context.cacheDir, filename)
                                                        val dup = byteBuffer.duplicate()
                                                        dup.position(0)
                                                        val bytes = ByteArray(dup.remaining())
                                                        dup.get(bytes)
                                                        cacheFile.writeBytes(bytes)
                                                        cacheFile.absolutePath
                                                    } catch (_: Exception) { null }

                                                    val success = socketClient.streamMemoryBuffer(
                                                        filename = filename,
                                                        buffer = byteBuffer
                                                    ) { sent, total ->
                                                        transferProgress = if (total > 0) sent.toFloat() / total.toFloat() else 0.5f
                                                    }
                                                    if (success) {
                                                        val sizeStr = if (bufferSize > 1024 * 1024) "%.2f MB".format(bufferSize / (1024f * 1024f)) else "%.1f KB".format(bufferSize / 1024f)
                                                        sharedHistory.add(0, SessionSharedItem(
                                                            id = filename,
                                                            title = filename,
                                                            subtitle = "Photo streamed to PC ($sizeStr) • Tap to View",
                                                            isOutgoing = true,
                                                            type = "PHOTO",
                                                            filePath = savedPath
                                                        ))
                                                        statusMessage = "Photo sent & verified!"
                                                    } else {
                                                        statusMessage = "Transfer failed or declined."
                                                    }
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
                                        .size(40.dp)
                                        .clip(CircleShape)
                                        .background(Color.White)
                                )
                            }
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // Fix 4: Editable Text Input & "Send Text to Connected Device" Button
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(6.dp),
                colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "SEND TEXT / CLIPBOARD",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary,
                            fontWeight = FontWeight.SemiBold
                        )
                        Surface(
                            color = CarbonElevated,
                            shape = RoundedCornerShape(4.dp),
                            border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                            modifier = Modifier.clickable {
                                val clip = clipboardManager.getText()?.text ?: ""
                                if (clip.isNotEmpty()) {
                                    textInput = clip
                                    haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                }
                            }
                        ) {
                            Text(
                                text = "Paste Clipboard",
                                style = MaterialTheme.typography.labelSmall,
                                color = BrandAccent,
                                modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    OutlinedTextField(
                        value = textInput,
                        onValueChange = { textInput = it },
                        placeholder = { Text("Type or paste text to send to PC...", color = TextSecondary) },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4,
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor = BrandAccent,
                            unfocusedBorderColor = BorderSubtle,
                            focusedTextColor = TextPrimary,
                            unfocusedTextColor = TextPrimary,
                            focusedContainerColor = CarbonBase,
                            unfocusedContainerColor = CarbonBase
                        )
                    )

                    Spacer(modifier = Modifier.height(8.dp))

                    Button(
                        onClick = {
                            if (textInput.isNotEmpty()) {
                                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                val textToSend = textInput
                                coroutineScope.launch {
                                    statusMessage = "Pushing text to PC..."
                                    val ok = socketClient.sendInstantText(textToSend)
                                    if (ok) {
                                        sharedHistory.add(0, SessionSharedItem(
                                            id = java.util.UUID.randomUUID().toString(),
                                            title = textToSend.take(60),
                                            subtitle = "Pushed to PC clipboard",
                                            isOutgoing = true,
                                            type = "TEXT"
                                        ))
                                        statusMessage = "Text pushed to PC clipboard!"
                                    } else {
                                        statusMessage = "Push failed. Check connection."
                                    }
                                }
                            }
                        },
                        enabled = textInput.isNotEmpty() && !isStreaming,
                        colors = ButtonDefaults.buttonColors(containerColor = BrandAccent),
                        shape = RoundedCornerShape(4.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            text = "Send Text to Connected Device",
                            fontWeight = FontWeight.SemiBold,
                            color = Color.White
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // File Transfer Card
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(6.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { filePicker.launch("*/*") }
            ) {
                Row(
                    modifier = Modifier.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Icon(
                        imageVector = Icons.Default.Description,
                        contentDescription = "File Transfer",
                        tint = BrandAccent,
                        modifier = Modifier.size(28.dp)
                    )
                    Column {
                        Text(
                            text = "Stream File to PC",
                            style = MaterialTheme.typography.titleMedium,
                            color = TextPrimary
                        )
                        Text(
                            text = "Select any file from device to stream directly to PC Downloads",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary
                        )
                    }
                }
            }

            // Live Download Progress Card (When receiving file from PC)
            if (isDownloading) {
                Spacer(modifier = Modifier.height(12.dp))
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(6.dp),
                    colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                    border = androidx.compose.foundation.BorderStroke(1.dp, BrandAccent)
                ) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "DOWNLOADING FILE FROM PC",
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.Bold,
                                color = BrandAccent
                            )
                            Text(
                                text = "${(downloadProgress * 100).toInt()}%",
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.Bold,
                                color = TextPrimary
                            )
                        }
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = downloadFileName,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = TextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        LinearProgressIndicator(
                            progress = { downloadProgress },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(6.dp)
                                .clip(RoundedCornerShape(3.dp)),
                            color = BrandAccent,
                            trackColor = CarbonElevated
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        Text(
                            text = downloadStatusText,
                            style = MaterialTheme.typography.labelSmall,
                            color = TextSecondary,
                            fontFamily = FontFamily.Monospace
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // Session Shared History Card
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(6.dp),
                colors = CardDefaults.cardColors(containerColor = CarbonSurface),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "SESSION SHARED HISTORY",
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            color = TextSecondary
                        )
                        if (sharedHistory.isNotEmpty()) {
                            Text(
                                text = "${sharedHistory.size} items",
                                style = MaterialTheme.typography.labelSmall,
                                color = BrandAccent
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))

                    if (sharedHistory.isEmpty()) {
                        Text(
                            text = "No items shared in this session yet. Sent photos, files, and text snippets will appear here.",
                            style = MaterialTheme.typography.labelMedium,
                            color = TextSecondary,
                            modifier = Modifier.padding(vertical = 8.dp)
                        )
                    } else {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            sharedHistory.forEach { item ->
                                Surface(
                                    color = CarbonElevated,
                                    shape = RoundedCornerShape(4.dp),
                                    border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                                            if (item.filePath != null || item.uriString != null) {
                                                openFileOrContent(context, item)
                                            } else if (item.type == "TEXT") {
                                                clipboardManager.setText(AnnotatedString(item.title))
                                                Toast.makeText(context, "Copied text to clipboard!", Toast.LENGTH_SHORT).show()
                                            }
                                        }
                                ) {
                                    Row(
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .padding(10.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                        horizontalArrangement = Arrangement.spacedBy(10.dp)
                                    ) {
                                        // Badge
                                        Surface(
                                            color = if (item.isOutgoing) BrandAccent.copy(alpha = 0.2f) else SignalSuccess.copy(alpha = 0.2f),
                                            shape = RoundedCornerShape(4.dp),
                                            border = androidx.compose.foundation.BorderStroke(
                                                1.dp,
                                                if (item.isOutgoing) BrandAccent else SignalSuccess
                                            )
                                        ) {
                                            Text(
                                                text = if (item.isOutgoing) "↑ SENT" else "↓ RCVD",
                                                style = MaterialTheme.typography.labelSmall,
                                                fontWeight = FontWeight.Bold,
                                                color = if (item.isOutgoing) BrandAccent else SignalSuccess,
                                                modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                                            )
                                        }

                                        Column(modifier = Modifier.weight(1f)) {
                                            Text(
                                                text = item.title,
                                                style = MaterialTheme.typography.bodyMedium,
                                                fontWeight = FontWeight.SemiBold,
                                                color = TextPrimary,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis
                                            )
                                            Text(
                                                text = item.subtitle,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = TextSecondary,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis
                                            )
                                        }

                                        Column(horizontalAlignment = Alignment.End) {
                                            Text(
                                                text = item.timestamp,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = TextSecondary,
                                                fontFamily = FontFamily.Monospace
                                            )
                                            Spacer(modifier = Modifier.height(2.dp))
                                            Surface(
                                                color = CarbonSurface,
                                                shape = RoundedCornerShape(2.dp),
                                                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle)
                                            ) {
                                                Text(
                                                    text = if (item.filePath != null || item.uriString != null) "Open ↗" else "Copy 📋",
                                                    style = MaterialTheme.typography.labelSmall,
                                                    fontSize = 10.sp,
                                                    color = if (item.filePath != null || item.uriString != null) BrandAccent else TextSecondary,
                                                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 1.dp)
                                                )
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        // Live Status Message
        if (statusMessage.isNotEmpty() || connectionStatus.isNotEmpty()) {
            Spacer(modifier = Modifier.height(10.dp))
            Surface(
                color = CarbonSurface,
                shape = RoundedCornerShape(4.dp),
                border = androidx.compose.foundation.BorderStroke(1.dp, BorderSubtle),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = if (statusMessage.isNotEmpty()) statusMessage else connectionStatus,
                    style = MaterialTheme.typography.labelMedium,
                    color = BrandAccent,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
                )
            }
        }
    }
}
