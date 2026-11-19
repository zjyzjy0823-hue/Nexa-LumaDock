package com.isidel.studiolo

import android.app.Activity
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import app.tauri.annotation.Command
import app.tauri.annotation.InvokeArg
import app.tauri.annotation.TauriPlugin
import app.tauri.plugin.Invoke
import app.tauri.plugin.JSObject
import app.tauri.plugin.Plugin
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@InvokeArg
class VaultIdentity {
    lateinit var coreUrl: String
    lateinit var workspaceId: String
    lateinit var kind: String
    lateinit var identityId: String
}

@InvokeArg
class VaultArgs {
    lateinit var key: VaultIdentity
    var secret: String? = null
}

@TauriPlugin
class LocalCorePlugin(private val host: Activity) : Plugin(host) {
    private val alias = "studiolo.local-core.v1"
    private val ivSize = 12
    private val lock = Any()

    private fun key(create: Boolean): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        check(create)
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply {
                init(
                    KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                        .setKeySize(256)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setRandomizedEncryptionRequired(true)
                        .build()
                )
            }.generateKey()
    }

    private fun namespace(identity: VaultIdentity): ByteArray {
        require(identity.kind == "client" || identity.kind == "device")
        return listOf(identity.coreUrl, identity.workspaceId, identity.kind, identity.identityId)
            .joinToString("\u0000").toByteArray(Charsets.UTF_8)
    }

    private fun encryptedFile(namespace: ByteArray): AtomicFile {
        val name = MessageDigest.getInstance("SHA-256").digest(namespace).joinToString("") { "%02x".format(it) }
        val dir = File(host.noBackupFilesDir, "studiolo-vault")
        check(dir.isDirectory || dir.mkdirs())
        return AtomicFile(File(dir, name))
    }

    private fun verify(identity: VaultIdentity, secret: String) {
        val prefix = if (identity.kind == "client") "nc_live_" else "nd_live_"
        require(secret.startsWith(prefix) && secret.removePrefix(prefix).matches(Regex("[A-Za-z0-9_-]{40,}")))
    }

    // Registered only for Rust-to-native calls. The WebView has no vault capability.
    @Command
    fun storage(invoke: Invoke) {
        invoke.resolve(JSObject().put("path", host.noBackupFilesDir.absolutePath))
    }

    @Command
    fun readCredential(invoke: Invoke) = finish(invoke) { args, namespace, file ->
        if (!file.baseFile.exists()) {
            JSObject().put("secret", JSONObject.NULL)
        } else {
            val bytes = file.readFully()
            require(bytes.size > ivSize + 16)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(false), GCMParameterSpec(128, bytes.copyOfRange(0, ivSize)))
            cipher.updateAAD(namespace)
            val decoded = cipher.doFinal(bytes, ivSize, bytes.size - ivSize)
            try {
                val secret = decoded.toString(Charsets.UTF_8)
                verify(args.key, secret)
                JSObject().put("secret", secret)
            } finally {
                decoded.fill(0)
            }
        }
    }

    @Command
    fun writeCredential(invoke: Invoke) = finish(invoke) { args, namespace, file ->
        val secret = requireNotNull(args.secret)
        verify(args.key, secret)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key(true))
        check(cipher.iv.size == ivSize)
        cipher.updateAAD(namespace)
        val plain = secret.toByteArray(Charsets.UTF_8)
        val encrypted = try { cipher.doFinal(plain) } finally { plain.fill(0) }
        val output = file.startWrite()
        try {
            output.write(cipher.iv)
            output.write(encrypted)
            file.finishWrite(output)
        } catch (cause: Exception) {
            file.failWrite(output)
            throw cause
        }
        JSObject()
    }

    @Command
    fun removeCredential(invoke: Invoke) = finish(invoke) { _, _, file ->
        file.delete()
        check(!file.baseFile.exists())
        JSObject()
    }

    private fun finish(invoke: Invoke, action: (VaultArgs, ByteArray, AtomicFile) -> JSObject) {
        try {
            val args = invoke.parseArgs(VaultArgs::class.java)
            val namespace = namespace(args.key)
            val result = synchronized(lock) { action(args, namespace, encryptedFile(namespace)) }
            invoke.resolve(result)
        } catch (_: Exception) {
            invoke.reject("credential_storage")
        }
    }
}
