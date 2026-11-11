package com.jiffboltp2p.client.data

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Log

class DiscoveryManager(
    private val context: Context,
    private val onPeerDiscovered: (name: String, ip: String, port: Int) -> Unit
) {

    private val nsdManager: NsdManager? =
        context.getSystemService(Context.NSD_SERVICE) as? NsdManager

    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private var isDiscovering = false

    fun startDiscovery() {
        if (isDiscovering || nsdManager == null) return

        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(regType: String) {
                isDiscovering = true
                Log.d("BoltP2PNSD", "NSD discovery started: $regType")
            }

            override fun onServiceFound(service: NsdServiceInfo) {
                Log.d("BoltP2PNSD", "Service found: ${service.serviceName}")
                if (service.serviceType.contains("_jiffboltp2p._tcp") || service.serviceType.contains("_boltp2p._tcp")) {
                    resolveService(service)
                }
            }

            override fun onServiceLost(service: NsdServiceInfo) {
                Log.d("BoltP2PNSD", "Service lost: ${service.serviceName}")
            }

            override fun onDiscoveryStopped(serviceType: String) {
                isDiscovering = false
                Log.d("BoltP2PNSD", "Discovery stopped.")
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                isDiscovering = false
                Log.e("BoltP2PNSD", "Start discovery failed: $errorCode")
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e("BoltP2PNSD", "Stop discovery failed: $errorCode")
            }
        }

        try {
            nsdManager.discoverServices("_jiffboltp2p._tcp", NsdManager.PROTOCOL_DNS_SD, discoveryListener)
        } catch (e: Exception) {
            Log.e("BoltP2PNSD", "Failed to start NSD: ${e.message}")
        }
    }

    private fun resolveService(serviceInfo: NsdServiceInfo) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            nsdManager?.registerServiceInfoCallback(
                serviceInfo,
                androidx.core.content.ContextCompat.getMainExecutor(context),
                object : NsdManager.ServiceInfoCallback {
                    override fun onServiceInfoCallbackRegistrationFailed(errorCode: Int) {}
                    override fun onServiceUpdated(service: NsdServiceInfo) {
                        val host = service.hostAddresses.firstOrNull()?.hostAddress ?: return
                        onPeerDiscovered(service.serviceName, host, service.port)
                    }
                    override fun onServiceLost() {}
                    override fun onServiceInfoCallbackUnregistered() {}
                }
            )
        } else {
            @Suppress("DEPRECATION")
            nsdManager?.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    Log.w("BoltP2PNSD", "Resolve failed: $errorCode")
                }

                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    val host = serviceInfo.host?.hostAddress ?: return
                    onPeerDiscovered(serviceInfo.serviceName, host, serviceInfo.port)
                }
            })
        }
    }

    fun stopDiscovery() {
        if (isDiscovering && nsdManager != null && discoveryListener != null) {
            try {
                nsdManager.stopServiceDiscovery(discoveryListener)
            } catch (_: Exception) {}
            isDiscovering = false
            discoveryListener = null
        }
    }
}
