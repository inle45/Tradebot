package com.tradebot.core

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.UUID
import java.util.concurrent.TimeUnit

class RevxException(message: String) : Exception(message)

/**
 * Client de l'API Revolut X.
 *
 * Les requêtes authentifiées sont signées en Ed25519 : on concatène
 * timestamp + méthode + chemin + query + corps, on signe avec la clé privée,
 * et on envoie la signature en base64. La clé privée ne quitte jamais le
 * téléphone.
 */
class RevxClient(
    private val apiKey: String = "",
    privateKeyPem: String = "",
    private val baseUrl: String = "https://revx.revolut.com/api",
) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val signerKey: Ed25519PrivateKeyParameters? = Signing.parsePem(privateKeyPem)

    val hasCredentials: Boolean get() = apiKey.isNotBlank() && signerKey != null

    private fun sign(message: String): String {
        val key = signerKey ?: throw RevxException("Clé privée absente ou illisible")
        return Signing.sign(key, message)
    }

    private fun request(
        method: String,
        path: String,
        params: Map<String, String> = emptyMap(),
        bodyJson: String? = null,
        authenticated: Boolean = true,
        retries: Int = 4,
    ): String {
        val query = if (params.isEmpty()) "" else "?" + params.toSortedMap()
            .map { "${it.key}=${URLEncoder.encode(it.value, "UTF-8")}" }
            .joinToString("&")

        // Un ordre n'est jamais rejoué automatiquement : en cas de doute, mieux
        // vaut remonter l'erreur que risquer un ordre en double.
        val attempts = if (method == "GET" || method == "DELETE") retries else 1

        var lastError = "inconnue"
        repeat(attempts) { attempt ->
            val builder = Request.Builder().url(baseUrl + path + query)
            if (bodyJson != null) {
                builder.method(method, bodyJson.toRequestBody("application/json".toMediaType()))
            } else if (method != "GET") {
                builder.method(method, ByteArray(0).toRequestBody())
            }

            if (authenticated) {
                val timestamp = System.currentTimeMillis().toString()
                val message = Signing.message(
                    timestamp, method, "/api$path", query, bodyJson ?: "",
                )
                builder.addHeader("X-Revx-API-Key", apiKey)
                builder.addHeader("X-Revx-Timestamp", timestamp)
                builder.addHeader("X-Revx-Signature", sign(message))
            }

            http.newCall(builder.build()).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (response.isSuccessful) return text

                lastError = "HTTP ${response.code}: ${text.take(200)}"
                val retryable = response.code == 429 || response.code >= 500
                if (!retryable || attempt == attempts - 1) {
                    throw RevxException(lastError)
                }
                val waitMs = response.header("Retry-After")?.toLongOrNull() ?: 1000L
                Thread.sleep(maxOf(waitMs, 200L) * (attempt + 1))
            }
        }
        throw RevxException(lastError)
    }

    private fun encodeSymbol(symbol: String) = URLEncoder.encode(symbol, "UTF-8")

    // ---- Données publiques (aucune clé nécessaire) ----

    fun candles(symbol: String, intervalMinutes: String): List<Candle> {
        val raw = request(
            "GET", "/1.0/public/candles/${encodeSymbol(symbol)}",
            params = mapOf("interval" to intervalMinutes),
            authenticated = false,
        )
        val data = JSONObject(raw).getJSONArray("data")
        return (0 until data.length()).map { i ->
            val row = data.getJSONObject(i)
            Candle(
                start = row.getLong("start"),
                open = row.getString("open").toDouble(),
                high = row.getString("high").toDouble(),
                low = row.getString("low").toDouble(),
                close = row.getString("close").toDouble(),
                volume = row.optString("volume", "0").toDoubleOrNull() ?: 0.0,
            )
        }
    }

    /** Paires les plus échangées : les illiquides ont des prix erratiques. */
    fun liquidPairs(quote: String = "EUR", top: Int = 20): List<String> {
        val raw = request("GET", "/1.0/public/tickers", authenticated = false)
        val data = JSONObject(raw).getJSONArray("data")
        val rows = (0 until data.length()).map { data.getJSONObject(it) }
            .filter { it.getString("symbol").endsWith("/$quote") }
            .filterNot { it.getString("symbol").startsWith("USDC") ||
                         it.getString("symbol").startsWith("USDT") }
            .sortedByDescending { it.getString("quote_volume_24h").toDoubleOrNull() ?: 0.0 }
        return rows.map { it.getString("symbol") }.distinct().take(top)
    }

    /** Prix moyen de chaque paire, en un seul appel. */
    fun tickers(): Map<String, Double> {
        val raw = request("GET", "/1.0/public/tickers", authenticated = false)
        val data = JSONObject(raw).getJSONArray("data")
        return buildMap {
            for (i in 0 until data.length()) {
                val row = data.getJSONObject(i)
                val mid = row.optString("mid").toDoubleOrNull() ?: continue
                put(row.getString("symbol"), mid)
            }
        }
    }

    fun price(symbol: String): Double =
        tickers()[symbol] ?: throw RevxException("Paire $symbol introuvable")

    /**
     * Combien vaut une unité de `currency` en euros — pour afficher un compte
     * tenu en USDC dans la monnaie où l'utilisateur compte réellement.
     */
    fun eurRate(currency: String): Double? {
        if (currency == "EUR") return 1.0
        val quotes = tickers()
        quotes["$currency/EUR"]?.let { if (it > 0) return it }
        quotes["EUR/$currency"]?.let { if (it > 0) return 1.0 / it }
        return null
    }

    // ---- Compte et trading (authentifié) ----

    /** Soldes disponibles par devise, en un seul appel. */
    fun balances(): Map<String, Double> = parseBalances(request("GET", "/1.0/balances"))

    fun balance(currency: String): Double = balances()[currency] ?: 0.0

    companion object {
        /**
         * L'endpoint des soldes répond par un tableau nu, mais d'autres routes
         * enveloppent leur contenu dans `{"data": [...]}`. On accepte les deux :
         * la forme exacte n'est pas garantie et une exception ici bloquerait
         * tout le cycle de trading.
         */
        fun parseBalances(raw: String): Map<String, Double> {
            val trimmed = raw.trim()
            val rows = if (trimmed.startsWith("[")) {
                JSONArray(trimmed)
            } else {
                JSONObject(trimmed).optJSONArray("data") ?: JSONArray()
            }
            return buildMap {
                for (i in 0 until rows.length()) {
                    val row = rows.optJSONObject(i) ?: continue
                    val currency = row.optString("currency")
                    if (currency.isNotBlank()) {
                        put(currency, row.optString("available", "0").toDoubleOrNull() ?: 0.0)
                    }
                }
            }
        }
    }

    fun placeMarketOrder(
        symbol: String,
        side: String,
        quoteSize: Double? = null,
        baseSize: Double? = null,
    ): String {
        val market = JSONObject()
        quoteSize?.let { market.put("quote_size", it.toString()) }
        baseSize?.let { market.put("base_size", it.toString()) }
        val body = JSONObject()
            .put("client_order_id", UUID.randomUUID().toString())
            .put("symbol", symbol)
            .put("side", side)
            .put("order_configuration", JSONObject().put("market", market))
        return request("POST", "/1.0/orders", bodyJson = body.toString())
    }
}
