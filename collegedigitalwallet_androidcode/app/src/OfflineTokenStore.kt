package com.example.collegedigitalwallet

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.example.collegedigitalwallet.model.OfflineTokenItem
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

object OfflineTokenStore {

    private const val PREF_NAME = "collegewallet_offline_tokens_secure"

    private fun prefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        return EncryptedSharedPreferences.create(
            context,
            PREF_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private fun key(username: String): String =
        "tokens_" + username.trim().lowercase()

    private fun parseExpiryMillis(expiresAt: String?): Long {
        if (expiresAt.isNullOrBlank()) return 0L
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US)
            sdf.timeZone = TimeZone.getTimeZone("UTC")
            sdf.parse(expiresAt)?.time ?: 0L
        } catch (_: Exception) {
            0L
        }
    }

    private fun isExpired(token: OfflineTokenItem): Boolean {
        val expiryMillis = parseExpiryMillis(token.expires_at)
        if (expiryMillis <= 0L) return true
        return System.currentTimeMillis() >= expiryMillis
    }

    private fun sortTokens(items: List<OfflineTokenItem>): List<OfflineTokenItem> {
        return items.sortedBy { parseExpiryMillis(it.expires_at) }
    }

    private fun loadMutable(context: Context, username: String): MutableList<OfflineTokenItem> {
        val raw = prefs(context).getString(key(username), "[]") ?: "[]"
        val arr = JSONArray(raw)
        val list = mutableListOf<OfflineTokenItem>()

        for (i in 0 until arr.length()) {
            val o = arr.getJSONObject(i)
            list.add(
                OfflineTokenItem(
                    token_id = o.optString("token_id"),
                    nonce = o.optString("nonce"),
                    expires_at = o.optString("expires_at"),
                    signature = o.optString("signature"),
                    max_amount = o.optDouble("max_amount", 0.0)
                )
            )
        }

        return list
    }

    private fun save(context: Context, username: String, items: List<OfflineTokenItem>) {
        val arr = JSONArray()

        items.forEach { t ->
            arr.put(
                JSONObject()
                    .put("token_id", t.token_id)
                    .put("nonce", t.nonce)
                    .put("expires_at", t.expires_at)
                    .put("signature", t.signature)
                    .put("max_amount", t.max_amount)
            )
        }

        prefs(context).edit().putString(key(username), arr.toString()).apply()
    }

    fun purgeExpiredTokens(context: Context, username: String) {
        val valid = loadMutable(context, username)
            .filterNot { isExpired(it) }

        save(context, username, sortTokens(valid))
    }

    fun availableCount(context: Context, username: String): Int {
        purgeExpiredTokens(context, username)
        return loadMutable(context, username).size
    }

    fun mergeTokens(context: Context, username: String, incoming: List<OfflineTokenItem>) {
        val current = loadMutable(context, username).filterNot { isExpired(it) }
        val freshIncoming = incoming.filterNot { isExpired(it) }

        val map = linkedMapOf<String, OfflineTokenItem>()

        current.forEach { map[it.token_id] = it }
        freshIncoming.forEach { map[it.token_id] = it }

        save(context, username, sortTokens(map.values.toList()))
    }

    fun peekNextToken(context: Context, username: String): OfflineTokenItem? {
        purgeExpiredTokens(context, username)
        return loadMutable(context, username).firstOrNull()
    }

    fun consumeToken(context: Context, username: String, tokenId: String) {
        val remaining = loadMutable(context, username)
            .filterNot { it.token_id == tokenId }
            .filterNot { isExpired(it) }

        save(context, username, sortTokens(remaining))
    }

    fun clearAll(context: Context, username: String) {
        prefs(context).edit().remove(key(username)).apply()
    }
}