package com.jiffboltp2p.client

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.jiffboltp2p.client.data.CameraStreamManager
import com.jiffboltp2p.client.data.JiffBoltP2PAndroidServer
import com.jiffboltp2p.client.data.JiffBoltP2PSocketClient
import com.jiffboltp2p.client.data.DiscoveryManager
import com.jiffboltp2p.client.data.IncomingFileOffer
import com.jiffboltp2p.client.ui.MainScreen
import com.jiffboltp2p.client.ui.theme.JiffBoltP2PTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID

data class SessionSharedItem(
    val id: String,
    val title: String,
    val subtitle: String,
    val isOutgoing: Boolean,
    val type: String,
    val filePath: String? = null,
    val uriString: String? = null,
    val timestamp: String = java.text.SimpleDateFormat("h:mm a", java.util.Locale.getDefault()).format(java.util.Date())
)

class MainActivity : ComponentActivity() {

    companion object {
        var activeInstance: MainActivity? = null
    }

    private lateinit var socketClient: JiffBoltP2PSocketClient
    private lateinit var cameraStreamManager: CameraStreamManager
    private lateinit var discoveryManager: DiscoveryManager
    private lateinit var androidServer: JiffBoltP2PAndroidServer

    private var hasCameraPermission by mutableStateOf(false)
    private var clipboardContent by mutableStateOf("")
    private var activeHost by mutableStateOf("192.168.1.100")
    private var activePort by mutableIntStateOf(58241)
    private var isConnectedState by mutableStateOf(false)
    private var connectionStatus by mutableStateOf("Ready to connect")
    private var currentIncomingOffer by mutableStateOf<IncomingFileOffer?>(null)
    private val sharedHistory = mutableStateListOf<SessionSharedItem>()

    private var isDownloading by mutableStateOf(false)
    private var downloadProgress by mutableFloatStateOf(0f)
    private var downloadFileName by mutableStateOf("")
    private var downloadStatusText by mutableStateOf("")

    private val requestCameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
            hasCameraPermission = isGranted
        }

    private val requestNotificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { _ -> }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        activeInstance = this

        // Restore saved PC target
        val prefs = getSharedPreferences("jiffboltp2p_prefs", Context.MODE_PRIVATE)
        activeHost = prefs.getString("pc_host", "192.168.1.100") ?: "192.168.1.100"
        activePort = prefs.getInt("pc_port", 58241)

        socketClient = JiffBoltP2PSocketClient(activeHost, activePort)
        cameraStreamManager = CameraStreamManager(this)
        androidServer = JiffBoltP2PAndroidServer(this, 58242).apply {
            sessionKeySupplier = { socketClient.sessionKey }
            isConnectedSupplier = { isConnectedState }
            onIncomingOffer = { offer ->
                runOnUiThread {
                    currentIncomingOffer = offer
                }
            }
            onTextReceived = { text ->
                runOnUiThread {
                    sharedHistory.add(0, SessionSharedItem(
                        id = java.util.UUID.randomUUID().toString(),
                        title = text.take(60),
                        subtitle = "Received from PC clipboard",
                        isOutgoing = false,
                        type = "TEXT"
                    ))
                }
            }
            onDownloadProgress = { received, total, fname ->
                runOnUiThread {
                    isDownloading = true
                    downloadFileName = fname
                    downloadProgress = if (total > 0) received.toFloat() / total.toFloat() else 0.5f
                    val recStr = if (received > 1024 * 1024) "%.2f MB".format(received / (1024f * 1024f)) else "%.1f KB".format(received / 1024f)
                    val totStr = if (total > 1024 * 1024) "%.2f MB".format(total / (1024f * 1024f)) else "%.1f KB".format(total / 1024f)
                    downloadStatusText = "$recStr / $totStr (${(downloadProgress * 100).toInt()}%)"
                }
            }
            onDownloadComplete = { file, success ->
                runOnUiThread {
                    isDownloading = false
                    downloadProgress = 0f
                    if (success) {
                        val fsize = file.length()
                        val sizeStr = if (fsize > 1024 * 1024) "%.2f MB".format(fsize / (1024f * 1024f)) else "%.1f KB".format(fsize / 1024f)
                        sharedHistory.add(0, SessionSharedItem(
                            id = java.util.UUID.randomUUID().toString(),
                            title = file.name,
                            subtitle = "Download/JiffBoltP2P ($sizeStr) • Tap to Open",
                            isOutgoing = false,
                            type = "FILE",
                            filePath = file.absolutePath
                        ))
                    }
                }
            }
            start()
        }

        // Start background foreground listener
        ForegroundService.start(this)

        checkCameraPermission()
        checkNotificationPermission()

        // Background KeepAlive Heartbeat (Pauses during active transfers)
        lifecycleScope.launch {
            while (isActive) {
                delay(5000L)
                if (isConnectedState && !socketClient.isTransferring) {
                    val ok = socketClient.sendHeartbeat()
                    if (!ok && !socketClient.isTransferring) {
                        androidServer.autoAcceptFiles = false
                        isConnectedState = false
                        connectionStatus = "Disconnected"
                    }
                }
            }
        }

        // Initialize mDNS discovery for desktop daemon
        discoveryManager = DiscoveryManager(this) { name, ip, port ->
            runOnUiThread {
                activeHost = ip
                activePort = port
                socketClient.updateTarget(ip, port)
                prefs.edit().putString("pc_host", ip).putInt("pc_port", port).apply()

                if (!isConnectedState) {
                    lifecycleScope.launch {
                        connectionStatus = "Connecting to $name..."
                        val connected = socketClient.connect(ip, port)
                        if (connected) {
                            isConnectedState = true
                            connectionStatus = "Connected to $name"
                        } else {
                            connectionStatus = "Discovered: $name"
                        }
                    }
                }
            }
        }
        discoveryManager.startDiscovery()

        setContent {
            JiffBoltP2PTheme {
                MainScreen(
                    socketClient = socketClient,
                    cameraStreamManager = cameraStreamManager,
                    clipboardText = clipboardContent,
                    hasCameraPermission = hasCameraPermission,
                    onRequestCameraPermission = {
                        requestCameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    },
                    isConnected = isConnectedState,
                    connectionStatus = connectionStatus,
                    activeHost = activeHost,
                    activePort = activePort,
                    incomingOffer = currentIncomingOffer,
                    sharedHistory = sharedHistory,
                    isDownloading = isDownloading,
                    downloadProgress = downloadProgress,
                    downloadFileName = downloadFileName,
                    downloadStatusText = downloadStatusText,
                    onAcceptOffer = { transferId ->
                        androidServer.acceptOffer(transferId)
                        currentIncomingOffer = null
                    },
                    onAcceptAllOffers = { transferId ->
                        androidServer.autoAcceptFiles = true
                        androidServer.acceptOffer(transferId)
                        currentIncomingOffer = null
                    },
                    onRejectOffer = { transferId ->
                        androidServer.rejectOffer(transferId)
                        currentIncomingOffer = null
                    },
                    onConnect = { host, port, pin ->
                        activeHost = host
                        activePort = port
                        prefs.edit().putString("pc_host", host).putInt("pc_port", port).apply()
                        socketClient.updateTarget(host, port)
                        lifecycleScope.launch {
                            connectionStatus = "Connecting to $host..."
                            val ok = socketClient.connect(host, port, pin)
                            if (ok) {
                                isConnectedState = true
                                connectionStatus = "Connected to ${socketClient.peerDeviceName}"
                            } else {
                                isConnectedState = false
                                connectionStatus = "Failed to connect to $host"
                            }
                        }
                    },
                    onDisconnect = {
                        lifecycleScope.launch {
                            socketClient.disconnect()
                            androidServer.autoAcceptFiles = false
                            isConnectedState = false
                            connectionStatus = "Disconnected"
                        }
                    }
                )
            }
        }

        // Handle file/text shared from another app (Android Share Sheet)
        handleIncomingShareIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingShareIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        checkCameraPermission()
        checkClipboard()
    }

    fun clearIncomingOffer(transferId: String) {
        runOnUiThread {
            if (currentIncomingOffer?.transferId == transferId) {
                currentIncomingOffer = null
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        if (activeInstance == this) activeInstance = null
        discoveryManager.stopDiscovery()
        socketClient.close()
        androidServer.stop()
        ForegroundService.stop(this)
    }

    private fun checkCameraPermission() {
        hasCameraPermission = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun checkNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestNotificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun checkClipboard() {
        try {
            val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
            val item = clipboard?.primaryClip?.getItemAt(0)
            val text = item?.text?.toString() ?: ""
            clipboardContent = text
        } catch (_: Exception) {
            clipboardContent = ""
        }
    }

    private fun handleIncomingShareIntent(intent: Intent?) {
        if (intent == null) return
        val action = intent.action
        val type = intent.type ?: return

        if (Intent.ACTION_SEND == action) {
            if ("text/plain" == type && intent.hasExtra(Intent.EXTRA_TEXT)) {
                val sharedText = intent.getStringExtra(Intent.EXTRA_TEXT) ?: ""
                if (sharedText.isNotBlank()) {
                    shareTextToPc(sharedText)
                }
            } else if (intent.hasExtra(Intent.EXTRA_STREAM)) {
                val uri = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                }
                if (uri != null) {
                    shareUrisToPc(listOf(uri))
                }
            }
        } else if (Intent.ACTION_SEND_MULTIPLE == action) {
            val uris = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
            }
            if (!uris.isNullOrEmpty()) {
                shareUrisToPc(uris)
            }
        }
    }

    private fun shareTextToPc(text: String) {
        lifecycleScope.launch {
            if (!isConnectedState) {
                connectionStatus = "Connecting to PC..."
                val ok = socketClient.connect(activeHost, activePort)
                isConnectedState = ok
            }
            if (isConnectedState) {
                val ok = socketClient.sendInstantText(text)
                if (ok) {
                    sharedHistory.add(0, SessionSharedItem(
                        id = UUID.randomUUID().toString(),
                        title = text.take(60),
                        subtitle = "Shared to PC clipboard",
                        isOutgoing = true,
                        type = "TEXT"
                    ))
                    Toast.makeText(this@MainActivity, "Shared text sent to PC", Toast.LENGTH_SHORT).show()
                } else {
                    Toast.makeText(this@MainActivity, "Failed to send text to PC", Toast.LENGTH_SHORT).show()
                }
            } else {
                Toast.makeText(this@MainActivity, "PC not connected ($activeHost:$activePort)", Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun shareUrisToPc(uris: List<Uri>) {
        lifecycleScope.launch(Dispatchers.IO) {
            if (!isConnectedState) {
                withContext(Dispatchers.Main) { connectionStatus = "Connecting to PC..." }
                val ok = socketClient.connect(activeHost, activePort)
                withContext(Dispatchers.Main) { isConnectedState = ok }
            }
            if (!isConnectedState) {
                withContext(Dispatchers.Main) {
                    Toast.makeText(this@MainActivity, "PC not connected ($activeHost:$activePort)", Toast.LENGTH_LONG).show()
                }
                return@launch
            }

            var successCount = 0
            val totalCount = uris.size

            for ((idx, uri) in uris.withIndex()) {
                var filename = "shared_file_${System.currentTimeMillis()}"
                var size = 0L

                try {
                    contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                        val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                        if (cursor.moveToFirst()) {
                            if (nameIndex != -1) filename = cursor.getString(nameIndex) ?: filename
                            if (sizeIndex != -1) size = cursor.getLong(sizeIndex)
                        }
                    }
                } catch (_: Exception) {}

                val inStream = contentResolver.openInputStream(uri)
                if (inStream != null) {
                    val realSize = if (size > 0) size else inStream.available().toLong()
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@MainActivity, "Streaming [${idx + 1}/$totalCount] $filename to PC...", Toast.LENGTH_SHORT).show()
                    }
                    val ok = socketClient.streamInputStream(filename, realSize, inStream) { _, _ -> }
                    if (ok) {
                        successCount++
                        val sizeStr = if (realSize > 1024 * 1024) "%.2f MB".format(realSize / (1024f * 1024f)) else "%.1f KB".format(realSize / 1024f)
                        withContext(Dispatchers.Main) {
                            sharedHistory.add(0, SessionSharedItem(
                                id = UUID.randomUUID().toString(),
                                title = filename,
                                subtitle = "Shared to PC ($sizeStr)",
                                isOutgoing = true,
                                type = "FILE",
                                uriString = uri.toString()
                            ))
                        }
                    }
                }
            }

            withContext(Dispatchers.Main) {
                if (successCount == totalCount) {
                    Toast.makeText(this@MainActivity, "Shared $totalCount file(s) sent to PC successfully!", Toast.LENGTH_LONG).show()
                } else {
                    Toast.makeText(this@MainActivity, "Sent $successCount of $totalCount files to PC", Toast.LENGTH_LONG).show()
                }
            }
        }
    }
}
