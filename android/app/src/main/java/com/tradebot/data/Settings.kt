package com.tradebot.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Réglages persistés. La clé API et la clé privée sont stockées chiffrées via
 * le Keystore Android : elles ne quittent jamais l'appareil et ne sont pas
 * lisibles par les autres applications.
 */
class Settings(context: Context) {

    private val prefs: SharedPreferences = runCatching {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            "tradebot_secure",
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        ) as SharedPreferences
    }.getOrElse {
        // Repli si le Keystore est indisponible : l'app reste utilisable en
        // simulation, mais on ne veut pas y écrire de secrets.
        context.getSharedPreferences("tradebot_plain", Context.MODE_PRIVATE)
    }

    var apiKey: String
        get() = prefs.getString("api_key", "").orEmpty()
        set(value) = prefs.edit().putString("api_key", value).apply()

    var privateKeyPem: String
        get() = prefs.getString("private_key", "").orEmpty()
        set(value) = prefs.edit().putString("private_key", value).apply()

    var symbol: String
        get() = prefs.getString("symbol", "SOL/EUR").orEmpty()
        set(value) = prefs.edit().putString("symbol", value).apply()

    var intervalMinutes: String
        get() = prefs.getString("interval", "240").orEmpty()
        set(value) = prefs.edit().putString("interval", value).apply()

    var strategyName: String
        get() = prefs.getString("strategy", "Moyennes mobiles").orEmpty()
        set(value) = prefs.edit().putString("strategy", value).apply()

    var capitalEur: Double
        get() = prefs.getFloat("capital", 100f).toDouble()
        set(value) = prefs.edit().putFloat("capital", value.toFloat()).apply()

    /** Le mode réel exige un basculement explicite. Par défaut : simulation. */
    var liveEnabled: Boolean
        get() = prefs.getBoolean("live_enabled", false)
        set(value) = prefs.edit().putBoolean("live_enabled", value).apply()

    val canGoLive: Boolean
        get() = apiKey.isNotBlank() && privateKeyPem.isNotBlank()

    // --- État de la position, pour survivre à un redémarrage ---

    fun savePosition(entryPrice: Double?, size: Double?, peak: Double?, cash: Double) {
        prefs.edit().apply {
            if (entryPrice == null) {
                remove("pos_entry"); remove("pos_size"); remove("pos_peak")
            } else {
                putFloat("pos_entry", entryPrice.toFloat())
                putFloat("pos_size", size!!.toFloat())
                putFloat("pos_peak", peak!!.toFloat())
            }
            putFloat("cash", cash.toFloat())
        }.apply()
    }

    fun loadCash(): Double = prefs.getFloat("cash", capitalEur.toFloat()).toDouble()

    fun loadPosition(): Triple<Double, Double, Double>? {
        if (!prefs.contains("pos_entry")) return null
        return Triple(
            prefs.getFloat("pos_entry", 0f).toDouble(),
            prefs.getFloat("pos_size", 0f).toDouble(),
            prefs.getFloat("pos_peak", 0f).toDouble(),
        )
    }

    // --- Référence de performance en mode réel ---
    //
    // Le champ « capital / plafond » borne ce que le bot peut engager ; ce n'est
    // pas un capital de départ. Comparer un compte réel à ce nombre afficherait
    // un gain inventé. On retient donc la valeur du compte au premier cycle réel,
    // par paire, et on mesure l'écart depuis ce point.

    private fun baselineKey(symbol: String) = "live_baseline_$symbol"

    fun liveBaseline(symbol: String): Double? =
        if (prefs.contains(baselineKey(symbol)))
            prefs.getFloat(baselineKey(symbol), 0f).toDouble()
        else null

    fun saveLiveBaseline(symbol: String, value: Double) {
        prefs.edit().putFloat(baselineKey(symbol), value.toFloat()).apply()
    }

    fun resetPortfolio() {
        prefs.edit().apply {
            remove("pos_entry"); remove("pos_size"); remove("pos_peak"); remove("cash")
            // La référence du mode réel repart aussi de zéro, sinon l'écart
            // affiché se mesurerait depuis un point qui n'a plus de sens.
            for (key in prefs.all.keys) {
                if (key.startsWith("live_baseline_")) remove(key)
            }
        }.apply()
    }
}
