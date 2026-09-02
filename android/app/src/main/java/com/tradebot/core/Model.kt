package com.tradebot.core

/** Une bougie de marché : prix d'ouverture, plus haut, plus bas, clôture. */
data class Candle(
    val start: Long,
    val open: Double,
    val high: Double,
    val low: Double,
    val close: Double,
    val volume: Double,
)

enum class Signal { BUY, SELL, HOLD }

/** Position ouverte. `peak` sert au trailing stop. */
data class Position(
    val entryPrice: Double,
    val size: Double,
    var peak: Double = entryPrice,
) {
    fun updatePeak(price: Double) {
        peak = maxOf(peak, price, entryPrice)
    }
}

/** Décision de la stratégie, avec la raison en clair pour l'affichage. */
data class Decision(
    val signal: Signal,
    val reason: String,
    val indicators: Map<String, Double> = emptyMap(),
)

data class Trade(
    val entryPrice: Double,
    val exitPrice: Double,
    val profitPct: Double,
    val reason: String,
    val exitTime: Long,
)

/** Résultat d'un backtest, avec la référence buy & hold systématiquement
 * incluse : c'est elle qui dit si la stratégie sert à quelque chose. */
data class BacktestResult(
    val initialEur: Double,
    val finalValue: Double,
    val returnPct: Double,
    val holdValue: Double,
    val holdReturnPct: Double,
    val beatsHold: Boolean,
    val trades: List<Trade>,
    val winRate: Double,
    val maxDrawdownPct: Double,
    val equityCurve: List<Double>,
    val candlesTested: Int,
    /** Part du temps réellement investi. Une stratégie peu exposée « bat »
     * mécaniquement le buy & hold en marché baissier, sans aucun mérite. */
    val exposurePct: Double = 0.0,
)
