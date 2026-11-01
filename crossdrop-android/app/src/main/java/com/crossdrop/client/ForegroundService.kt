package com.crossdrop.client

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

class ForegroundService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP_SERVICE -> {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_ACCEPT_TRANSFER -> {
                val transferId = intent.getStringExtra(EXTRA_TRANSFER_ID) ?: ""
                cancelIncomingTransferNotification(this, transferId)
                onAcceptAction?.invoke(transferId)
            }
            ACTION_REJECT_TRANSFER -> {
                val transferId = intent.getStringExtra(EXTRA_TRANSFER_ID) ?: ""
                cancelIncomingTransferNotification(this, transferId)
                onRejectAction?.invoke(transferId)
            }
            else -> {
                val notification = buildPersistentNotification()
                startForeground(NOTIFICATION_ID_PERSISTENT, notification)
            }
        }
        return START_STICKY
    }

    private fun buildPersistentNotification(): Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID_PERSISTENT)
            .setContentTitle("CrossDrop Active")
            .setContentText("Zero-Cloud P2P session listening in background")
            .setSmallIcon(android.R.drawable.ic_menu_share)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            val persistentChannel = NotificationChannel(
                CHANNEL_ID_PERSISTENT,
                "CrossDrop Background Status",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps CrossDrop socket alive in background"
            }

            val alertChannel = NotificationChannel(
                CHANNEL_ID_ALERTS,
                "CrossDrop Incoming Transfers",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Actionable alerts for incoming transfers"
                enableVibration(true)
            }

            manager.createNotificationChannel(persistentChannel)
            manager.createNotificationChannel(alertChannel)
        }
    }

    companion object {
        const val CHANNEL_ID_PERSISTENT = "crossdrop_bg_channel"
        const val CHANNEL_ID_ALERTS = "crossdrop_alerts_channel"
        const val NOTIFICATION_ID_PERSISTENT = 1001

        const val ACTION_START_SERVICE = "com.crossdrop.START_SERVICE"
        const val ACTION_STOP_SERVICE = "com.crossdrop.STOP_SERVICE"
        const val ACTION_ACCEPT_TRANSFER = "com.crossdrop.ACCEPT_TRANSFER"
        const val ACTION_REJECT_TRANSFER = "com.crossdrop.REJECT_TRANSFER"
        const val EXTRA_TRANSFER_ID = "extra_transfer_id"

        var onAcceptAction: ((String) -> Unit)? = null
        var onRejectAction: ((String) -> Unit)? = null

        fun cancelIncomingTransferNotification(context: Context, transferId: String) {
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.cancel(transferId.hashCode())
        }

        fun start(context: Context) {
            val intent = Intent(context, ForegroundService::class.java).apply {
                action = ACTION_START_SERVICE
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            val intent = Intent(context, ForegroundService::class.java).apply {
                action = ACTION_STOP_SERVICE
            }
            context.startService(intent)
        }

        fun postIncomingTransferNotification(
            context: Context,
            transferId: String,
            title: String,
            message: String
        ) {
            val acceptIntent = Intent(context, ForegroundService::class.java).apply {
                action = ACTION_ACCEPT_TRANSFER
                putExtra(EXTRA_TRANSFER_ID, transferId)
            }
            val acceptPendingIntent = PendingIntent.getService(
                context,
                transferId.hashCode(),
                acceptIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val rejectIntent = Intent(context, ForegroundService::class.java).apply {
                action = ACTION_REJECT_TRANSFER
                putExtra(EXTRA_TRANSFER_ID, transferId)
            }
            val rejectPendingIntent = PendingIntent.getService(
                context,
                transferId.hashCode() + 1,
                rejectIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
            val contentPendingIntent = PendingIntent.getActivity(
                context,
                0,
                launchIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val notification = NotificationCompat.Builder(context, CHANNEL_ID_ALERTS)
                .setContentTitle(title)
                .setContentText(message)
                .setSmallIcon(android.R.drawable.ic_dialog_info)
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .setContentIntent(contentPendingIntent)
                .addAction(android.R.drawable.ic_menu_save, "Accept", acceptPendingIntent)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Reject", rejectPendingIntent)
                .build()

            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.notify(transferId.hashCode(), notification)
        }
    }
}

