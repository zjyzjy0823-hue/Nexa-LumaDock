package com.isidel.studiolo

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.Permission
import app.tauri.annotation.PermissionCallback
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.Channel
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import java.util.UUID

@InvokeArg
class NotificationPreference {
    var enabled = false
}

@InvokeArg
class FleetNotification {
    lateinit var title: String
    lateinit var body: String
    var sessionKey: String? = null
    var ongoing = false
    var clear = false
}

@InvokeArg
class FleetApprovalNotice {
    var count = 0
    var callId: String? = null
}

@InvokeArg
class FleetApprovalListener {
    lateinit var channel: Channel
}

@TauriPlugin(permissions = [Permission(strings = [Manifest.permission.POST_NOTIFICATIONS], alias = "notifications")])
class AndroidNotifications(private val host: Activity) : Plugin(host) {
    private val manager = host.getSystemService(NotificationManager::class.java)
    private val preferences = host.getSharedPreferences("studiolo.notifications", Context.MODE_PRIVATE)
    private val channelId = "studiolo.chat"
    private val approvalChannel = "studiolo.chat.approval"
    private val approvalNotificationId = 2
    private val activityNotificationId = 3
    private val approvalIntents = mutableMapOf<String, Pair<String, String?>>()
    private var approvalListener: Channel? = null

    @Command
    fun listenApproval(invoke: Invoke) {
        approvalListener = invoke.parseArgs(FleetApprovalListener::class.java).channel
        invoke.resolve(JSObject().put("value", true))
        openSessionIntent(host.intent)
    }

    override fun onNewIntent(intent: Intent) {
        if (openSessionIntent(intent)) return
        if (intent.action != "${host.packageName}.FLEET_APPROVAL") return
        val token = intent.getStringExtra("studiolo.approval.token") ?: return
        val response = synchronized(approvalIntents) {
            approvalIntents[token]?.also { approvalIntents.clear() }
        } ?: return
        intent.removeExtra("studiolo.approval.token")
        manager.cancel(approvalNotificationId)
        approvalListener?.send(JSObject().put("action", response.first).put("callId", response.second))
    }

    private fun openSessionIntent(intent: Intent?): Boolean {
        if (intent == null || intent.action != "${host.packageName}.FLEET_SESSION") return false
        val listener = approvalListener ?: return true
        val key = intent.getStringExtra("studiolo.session.key")
        intent.removeExtra("studiolo.session.key")
        intent.action = null
        listener.send(JSObject().put("action", "open").put("sessionKey", key))
        return true
    }

    private fun approvalIntent(action: String, callId: String?): PendingIntent {
        val token = UUID.randomUUID().toString()
        synchronized(approvalIntents) { approvalIntents[token] = action to callId }
        val intent = Intent(host, host.javaClass)
            .setAction("${host.packageName}.FLEET_APPROVAL")
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("studiolo.approval.token", token)
        return PendingIntent.getActivity(host, token.hashCode(), intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_ONE_SHOT)
    }

    @Command
    fun showApproval(invoke: Invoke) {
        val data = invoke.parseArgs(FleetApprovalNotice::class.java)
        synchronized(approvalIntents) { approvalIntents.clear() }
        if (data.count <= 0 || !preferences.getBoolean("enabled", false) || !canNotify()) {
            manager.cancel(approvalNotificationId)
            invoke.resolve(JSObject().put("value", false))
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(NotificationChannel(approvalChannel, "待审批请求", NotificationManager.IMPORTANCE_DEFAULT))
        }
        val callId = data.callId?.takeIf { data.count == 1 && it.isNotBlank() }
        val notification = NotificationCompat.Builder(host, approvalChannel)
            .setSmallIcon(R.drawable.studiolo_notification_icon)
            .setContentTitle("Studiolo")
            .setContentText("${data.count} 个待审批请求")
            .setNumber(data.count)
            .setContentIntent(approvalIntent("open", callId))
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        if (callId != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            for ((action, label) in listOf("allow_once" to "批准一次", "deny" to "拒绝")) {
                notification.addAction(NotificationCompat.Action.Builder(0, label, approvalIntent(action, callId))
                    .setAuthenticationRequired(true).build())
            }
        }
        try {
            manager.notify(approvalNotificationId, notification.build())
            invoke.resolve(JSObject().put("value", true))
        } catch (_: SecurityException) {
            invoke.resolve(JSObject().put("value", false))
        }
    }

    private fun hasPermission(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            host.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun canNotify(): Boolean =
        hasPermission() && manager.areNotificationsEnabled() &&
            (Build.VERSION.SDK_INT < Build.VERSION_CODES.O ||
                manager.getNotificationChannel(channelId)?.importance != NotificationManager.IMPORTANCE_NONE)

    @Command
    fun enabled(invoke: Invoke) {
        invoke.resolve(JSObject().put("value", preferences.getBoolean("enabled", false) && canNotify()))
    }

    @Command
    fun setEnabled(invoke: Invoke) {
        val enabled = invoke.parseArgs(NotificationPreference::class.java).enabled
        if (enabled && !hasPermission()) {
            requestPermissionForAlias("notifications", invoke, "notificationPermissionResult")
        } else {
            savePreference(invoke, enabled && canNotify())
        }
    }

    @PermissionCallback
    fun notificationPermissionResult(invoke: Invoke) = savePreference(invoke, canNotify())

    private fun savePreference(invoke: Invoke, enabled: Boolean) {
        preferences.edit().putBoolean("enabled", enabled).apply()
        invoke.resolve(JSObject().put("value", enabled))
    }

    @Command
    fun show(invoke: Invoke) {
        val data = invoke.parseArgs(FleetNotification::class.java)
        if (data.clear) {
            manager.cancel(activityNotificationId)
            invoke.resolve(JSObject().put("value", true))
            return
        }
        if (!preferences.getBoolean("enabled", false) || !canNotify()) {
            invoke.resolve(JSObject().put("value", false))
            return
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager.getNotificationChannel(channelId) == null) {
                manager.createNotificationChannel(NotificationChannel(
                    channelId, "聊天与任务提醒", NotificationManager.IMPORTANCE_LOW
                ))
            }
            val intent = Intent(host, host.javaClass)
                .setAction("${host.packageName}.FLEET_SESSION")
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra("studiolo.session.key", data.sessionKey)
            val openApp = PendingIntent.getActivity(host, if (data.ongoing) activityNotificationId else UUID.randomUUID().hashCode(),
                intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val notification = NotificationCompat.Builder(host, channelId)
                .setSmallIcon(R.drawable.studiolo_notification_icon)
                .setContentTitle(data.title.take(80))
                .setContentText(data.body.take(120))
                .setContentIntent(openApp)
                .setAutoCancel(!data.ongoing)
                .setOngoing(data.ongoing)
                .setOnlyAlertOnce(data.ongoing)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setVisibility(if (data.ongoing) NotificationCompat.VISIBILITY_PUBLIC else NotificationCompat.VISIBILITY_PRIVATE)
                .build()
            if (data.ongoing) manager.notify(activityNotificationId, notification)
            else manager.notify(UUID.randomUUID().toString(), 1, notification)
            invoke.resolve(JSObject().put("value", true))
        } catch (_: SecurityException) {
            // Android can revoke notification permission between the check and notify().
            invoke.resolve(JSObject().put("value", false))
        }
    }
}
