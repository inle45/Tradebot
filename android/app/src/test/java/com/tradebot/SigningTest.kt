package com.tradebot

import com.tradebot.core.Signing
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Vérifie que la signature Ed25519 produite par l'app est identique à celle
 * de la bibliothèque de référence (`cryptography` en Python), sur une clé et
 * un message fixés.
 *
 * C'est le test le plus important du projet : une signature incorrecte ferait
 * rejeter tous les ordres réels par Revolut, sans erreur explicite côté app.
 */
class SigningTest {

    // Clé de test générée avec `openssl genpkey -algorithm ed25519`.
    // Elle ne protège rien : elle n'existe que pour ce test.
    private val testPem = """
        -----BEGIN PRIVATE KEY-----
        MC4CAQAwBQYDK2VwBCIEIJFQLdND+m47gIXMwkQY+ovx1lUAg0Ifn/tiyQF2Dhq/
        -----END PRIVATE KEY-----
    """.trimIndent()

    private val message = "1788260430547GET/api/1.0/balances"

    // Signature calculée indépendamment par Python (cryptography)
    private val expected =
        "vAjG/o0Dol7KR9gaWC4aAHEojUlHJEplECZdL0sCqVg+23gvG0F2HGgP9nKveO6+yHrVuNuWSLMgWCGhRgjJCQ=="

    @Test
    fun signatureMatchesTheReferenceImplementation() {
        val key = Signing.parsePem(testPem)
        assertNotNull("la clé PEM doit être lisible", key)
        assertEquals(expected, Signing.sign(key!!, message))
    }

    @Test
    fun messageFollowsRevolutConcatenationOrder() {
        // timestamp + méthode + chemin + query + corps, sans séparateur
        assertEquals(
            "123GET/api/1.0/orders?symbol=SOL%2FEUR{\"a\":1}",
            Signing.message("123", "GET", "/api/1.0/orders", "?symbol=SOL%2FEUR", "{\"a\":1}"),
        )
    }

    @Test
    fun signatureChangesWithTheMessage() {
        val key = Signing.parsePem(testPem)!!
        // Un timestamp différent doit produire une signature différente, sinon
        // une requête rejouée resterait valide.
        assertEquals(false, Signing.sign(key, message) == Signing.sign(key, message + "x"))
    }

    @Test
    fun parsePemToleratesWhitespaceAndRejectsGarbage() {
        assertNotNull(Signing.parsePem(testPem.replace("\n", "\r\n")))
        assertNotNull(Signing.parsePem("  $testPem  "))
        assertNull(Signing.parsePem(""))
        assertNull(Signing.parsePem("pas une clé"))
    }
}
