package com.boltp2p.client

import android.Manifest
import android.content.ClipboardManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.boltp2p.client.data.CameraStreamManager
import com.boltp2p.client.data.BoltP2PAndroidServer
import com.boltp2p.client.data.BoltP2PSocketClient
import com.boltp2p.client.data.DiscoveryManager
import com.boltp2p.client.data.IncomingFileOffer
import com.boltp2p.client.ui.MainScreen
import com.boltp2p.client.ui.theme.BoltP2PTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

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

    private lateinit var socketClient: BoltP2PSocketClient
    private lateinit var cameraStreamManager: CameraStreamManager
    private lateinit var discoveryManager: DiscoveryManager
    private lateinit var androidServer: BoltP2PAndroidServer

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

        // Restore saved PC target
        val prefs = getSharedPreferences("boltp2p_prefs", Context.MODE_PRIVATE)
        activeHost = prefs.getString("pc_host", "192.168.1.100") ?: "192.168.1.100"
        activePort = prefs.getInt("pc_port", 58241)

        socketClient = BoltP2PSocketClient(activeHost, activePort)
        cameraStreamManager = CameraStreamManager(this)
        androidServer = BoltP2PAndroidServer(this, 58242).apply {
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
                            subtitle = "Downloads/BoltP2P ($sizeStr) • Tap to Open",
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
            BoltP2PTheme {
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
    }

    override fun onResume() {
        super.onResume()
        checkCameraPermission()
        checkClipboard()
    }

    override fun onDestroy() {
        super.onDestroy()
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
}
