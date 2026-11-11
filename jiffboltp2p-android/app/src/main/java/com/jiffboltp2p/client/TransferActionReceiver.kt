package com.jiffboltp2p.client

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class TransferActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        val transferId = intent.getStringExtra(ForegroundService.EXTRA_TRANSFER_ID) ?: return
        Log.i("TransferActionReceiver", "Received notification action $action for transfer $transferId")

        when (action) {
            ForegroundService.ACTION_ACCEPT_TRANSFER -> {
                ForegroundService.cancelIncomingTransferNotification(context, transferId)
                ForegroundService.onAcceptAction?.invoke(transferId)
            }
            ForegroundService.ACTION_REJECT_TRANSFER -> {
                ForegroundService.cancelIncomingTransferNotification(context, transferId)
                ForegroundService.onRejectAction?.invoke(transferId)
            }
        }
    }
}

