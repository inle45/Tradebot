package com.tradebot.ui

import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Currency
import java.util.Date
import java.util.Locale

private val timeFormat = SimpleDateFormat("HH:mm", Locale.FRANCE)

/**
 * Montant dans la devise de cotation de la paire tradée — celle avec laquelle
 * on achète. Afficher « € » alors que le compte est en USDC donnerait une
 * lecture fausse du portefeuille.
 *
 * Les cryptomonnaies stables (USDC…) n'ont pas de code ISO 4217 : dans ce cas
 * on accole simplement le code au montant.
 */
fun formatMoney(value: Double, currency: String): String {
    val iso = runCatching { Currency.getInstance(currency) }.getOrNull()
        ?: return String.format(Locale.FRANCE, "%,.2f %s", value, currency)
    return NumberFormat.getCurrencyInstance(Locale.FRANCE)
        .apply { this.currency = iso }
        .format(value)
}

fun formatEuro(value: Double): String = formatMoney(value, "EUR")

fun formatPercent(value: Double): String =
    (if (value >= 0) "+" else "") + String.format(Locale.FRANCE, "%.2f%%", value)

fun formatPoints(value: Double): String =
    (if (value >= 0) "+" else "") + String.format(Locale.FRANCE, "%.1f", value)

fun formatTime(epochMs: Long): String = timeFormat.format(Date(epochMs))
