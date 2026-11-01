package com.crossdrop.client

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
import com.crossdrop.client.data.CameraStreamManager
import com.crossdrop.client.data.CrossDropAndroidServer
import com.crossdrop.client.data.CrossDropSocketClient
import com.crossdrop.client.data.DiscoveryManager
import com.crossdrop.client.ui.MainScreen
import com.crossdrop.client.ui.theme.CrossDropTheme
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private lateinit var socketClient: CrossDropSocketClient
    private lateinit var cameraStreamManager: CameraStreamManager
    private lateinit var discoveryManager: DiscoveryManager
    private lateinit var androidServer: CrossDropAndroidServer

    private var hasCameraPermission by mutableStateOf(false)
    private var clipboardContent by mutableStateOf("")
    private var activeHost by mutableStateOf("192.168.1.100")
    private var activePort by mutableIntStateOf(58241)
    private var connectionStatus by mutableStateOf("Searching LAN...")

    private val requestCameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
            hasCameraPermission = isGranted
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Restore saved PC target
        val prefs = getSharedPreferences("crossdrop_prefs", Context.MODE_PRIVATE)
        activeHost = prefs.getString("pc_host", "192.168.1.100") ?: "192.168.1.100"
        activePort = prefs.getInt("pc_port", 58241)

        socketClient = CrossDropSocketClient(activeHost, activePort)
        cameraStreamManager = CameraStreamManager(this)
        androidServer = CrossDropAndroidServer(this, 58242).apply { start() }

        checkCameraPermission()

        // Initialize mDNS discovery for desktop daemon
        discoveryManager = DiscoveryManager(this) { name, ip, port ->
            runOnUiThread {
                activeHost = ip
                activePort = port
                socketClient.updateTarget(ip, port)
                connectionStatus = "Discovered: $name"
                prefs.edit().putString("pc_host", ip).putInt("pc_port", port).apply()

                // Attempt auto-connect
                lifecycleScope.launch {
                    val connected = socketClient.connect(ip, port)
                    if (connected) {
                        connectionStatus = "Connected to $name"
                    }
                }
            }
        }
        discoveryManager.startDiscovery()

        setContent {
            CrossDropTheme {
                MainScreen(
                    socketClient = socketClient,
                    cameraStreamManager = cameraStreamManager,
                    clipboardText = clipboardContent,
                    hasCameraPermission = hasCameraPermission,
                    onRequestCameraPermission = {
                        requestCameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    },
                    onManualConnect = { host, port ->
                        activeHost = host
                        activePort = port
                        prefs.edit().putString("pc_host", host).putInt("pc_port", port).apply()
                        socketClient.updateTarget(host, port)
                        lifecycleScope.launch {
                            connectionStatus = "Connecting..."
                            val ok = socketClient.connect(host, port)
                            connectionStatus = if (ok) "Connected to $host" else "Failed to connect"
                        }
                    },
                    activeHost = activeHost,
                    activePort = activePort,
                    connectionStatus = connectionStatus
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
    }

    private fun checkCameraPermission() {
        hasCameraPermission = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
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
