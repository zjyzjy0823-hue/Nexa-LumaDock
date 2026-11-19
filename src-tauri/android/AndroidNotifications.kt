package com.isidel.studiolo

import android.Manifest
import android.app.Activity
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.Permission
import app.tauri.annotation.PermissionCallback
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
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
}

@TauriPlugin(permissions = [Permission(strings = [Manifest.permission.POST_NOTIFICATIONS], alias = "notifications")])
class AndroidNotifications(private val host: Activity) : Plugin(host) {
    private val manager = host.getSystemService(NotificationManager::class.java)
    private val preferences = host.getSharedPreferences("studiolo.notifications", Context.MODE_PRIVATE)
    private val channelId = "studiolo.chat"

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
        if (!preferences.getBoolean("enabled", false) || !canNotify()) {
            invoke.resolve(JSObject().put("value", false))
            return
        }
        try {
            val data = invoke.parseArgs(FleetNotification::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && manager.getNotificationChannel(channelId) == null) {
                manager.createNotificationChannel(NotificationChannel(
                    channelId, "聊天与任务提醒", NotificationManager.IMPORTANCE_LOW
                ))
            }
            val openApp = host.packageManager.getLaunchIntentForPackage(host.packageName)?.let {
                PendingIntent.getActivity(host, 0, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            }
            val notification = NotificationCompat.Builder(host, channelId)
                .setSmallIcon(R.drawable.studiolo_notification_icon)
                .setContentTitle(data.title.take(80))
                .setContentText(data.body.take(120))
                .setContentIntent(openApp)
                .setAutoCancel(true)
                .setPriority(NotificationCompat.PRIORITY_LOW)
                .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                .build()
            manager.notify(UUID.randomUUID().toString(), 1, notification)
            invoke.resolve(JSObject().put("value", true))
        } catch (_: SecurityException) {
            // Android can revoke notification permission between the check and notify().
            invoke.resolve(JSObject().put("value", false))
        }
    }
}
