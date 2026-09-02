package com.tradebot.core

import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import java.util.Base64

/**
 * Signature Ed25519 des requêtes Revolut X.
 *
 * Isolé du client HTTP et sans dépendance Android (java.util.Base64 est
 * disponible depuis l'API 26, notre minSdk), afin de pouvoir être vérifié par
 * des tests unitaires : une signature fausse ferait échouer tous les ordres
 * réels, silencieusement.
 */
object Signing {

    /** Lit une clé privée Ed25519 au format PEM produit par openssl. */
    fun parsePem(pem: String): Ed25519PrivateKeyParameters? {
        if (pem.isBlank()) return null
        return try {
            val body = pem
                .replace("-----BEGIN PRIVATE KEY-----", "")
                .replace("-----END PRIVATE KEY-----", "")
                .replace(Regex("\\s"), "")
            val der = Base64.getDecoder().decode(body)
            // La clé brute occupe les 32 derniers octets de l'enveloppe PKCS#8
            if (der.size < 32) null
            else Ed25519PrivateKeyParameters(der, der.size - 32)
        } catch (e: Exception) {
            null
        }
    }

    /** Signe un message et retourne la signature encodée en base64. */
    fun sign(key: Ed25519PrivateKeyParameters, message: String): String {
        val bytes = message.toByteArray(Charsets.UTF_8)
        val signer = Ed25519Signer().apply {
            init(true, key)
            update(bytes, 0, bytes.size)
        }
        return Base64.getEncoder().encodeToString(signer.generateSignature())
    }

    /**
     * Message à signer, tel que l'attend Revolut X : timestamp, méthode HTTP,
     * chemin, query string puis corps, concaténés sans séparateur.
     */
    fun message(
        timestampMs: String,
        method: String,
        path: String,
        query: String,
        body: String,
    ): String = timestampMs + method + path + query + body
}
