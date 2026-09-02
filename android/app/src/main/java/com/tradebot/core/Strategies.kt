package com.tradebot.core

/**
 * Toutes les stratégies partagent cette interface, ce qui permet de les passer
 * dans le même backtest et donc de les comparer équitablement.
 */
interface Strategy {
    val name: String
    val description: String
    val warmup: Int
    fun decide(candles: List<Candle>, position: Position?): Decision
}

/** Sorties de protection communes à toutes les stratégies. */
abstract class ProtectedStrategy(
    private val stopLossPct: Double,
    private val trailingStopPct: Double,
) : Strategy {

    protected fun forcedExit(
        price: Double,
        position: Position,
        indicators: Map<String, Double>,
    ): Decision? {
        if (stopLossPct > 0) {
            val floor = position.entryPrice * (1 - stopLossPct / 100)
            if (price <= floor) {
                return Decision(Signal.SELL, "Stop-loss déclenché (-$stopLossPct%)", indicators)
            }
        }
        if (trailingStopPct > 0) {
            val floor = position.peak * (1 - trailingStopPct / 100)
            if (price <= floor) {
                return Decision(Signal.SELL, "Trailing stop déclenché", indicators)
            }
        }
        return null
    }
}

/** Croisement de moyennes mobiles, avec filtre de tendance optionnel.
 * La détection est sans état : recalculée depuis les données, donc un
 * redémarrage de l'app ne fait rien oublier au bot. */
class SmaCrossover(
    private val short: Int = 10,
    private val long: Int = 50,
    private val useTrendFilter: Boolean = false,
    private val trendPeriod: Int = 100,
    stopLossPct: Double = 5.0,
    trailingStopPct: Double = 0.0,
    override val name: String = "Moyennes mobiles",
) : ProtectedStrategy(stopLossPct, trailingStopPct) {

    override val description =
        "Achète quand la moyenne courte passe au-dessus de la longue, vend quand elle repasse dessous."

    override val warmup: Int
        get() = maxOf(long + 1, if (useTrendFilter) trendPeriod else 0)

    override fun decide(candles: List<Candle>, position: Position?): Decision {
        val closes = candles.map { it.close }
        val price = closes.lastOrNull() ?: return Decision(Signal.HOLD, "Pas de données")
        if (candles.size < warmup) {
            return Decision(Signal.HOLD, "Chargement (${candles.size}/$warmup bougies)")
        }

        val nowShort = Indicators.sma(closes, short)!!
        val nowLong = Indicators.sma(closes, long)!!
        val before = closes.dropLast(1)
        val wasShort = Indicators.sma(before, short)
        val wasLong = Indicators.sma(before, long)
        val trend = if (useTrendFilter) Indicators.sma(closes, trendPeriod) else null

        val indicators = buildMap {
            put("price", price)
            put("sma_short", nowShort)
            put("sma_long", nowLong)
            trend?.let { put("trend", it) }
        }

        val crossedUp = wasShort != null && wasLong != null &&
            wasShort <= wasLong && nowShort > nowLong
        val crossedDown = wasShort != null && wasLong != null &&
            wasShort >= wasLong && nowShort < nowLong

        if (position != null) {
            position.updatePeak(price)
            forcedExit(price, position, indicators)?.let { return it }
            if (crossedDown) return Decision(Signal.SELL, "Croisement baissier", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)
        }

        if (!crossedUp) return Decision(Signal.HOLD, "Pas de signal d'entrée", indicators)
        if (trend != null && price < trend) {
            return Decision(Signal.HOLD, "Signal ignoré : sous la tendance de fond", indicators)
        }
        return Decision(Signal.BUY, "Croisement haussier", indicators)
    }
}

/** Retour à la moyenne : on achète la peur, on vend l'euphorie. */
class RsiReversion(
    private val period: Int = 14,
    private val oversold: Double = 30.0,
    private val overbought: Double = 70.0,
    stopLossPct: Double = 5.0,
    trailingStopPct: Double = 0.0,
) : ProtectedStrategy(stopLossPct, trailingStopPct) {

    override val name = "RSI"
    override val description =
        "Achète quand le marché est survendu (RSI < 30), vend quand il est suracheté (RSI > 70)."
    override val warmup get() = period + 2

    override fun decide(candles: List<Candle>, position: Position?): Decision {
        val closes = candles.map { it.close }
        val price = closes.lastOrNull() ?: return Decision(Signal.HOLD, "Pas de données")
        if (candles.size < warmup) {
            return Decision(Signal.HOLD, "Chargement (${candles.size}/$warmup bougies)")
        }
        val value = Indicators.rsi(closes, period)!!
        val indicators = mapOf("price" to price, "rsi" to value)

        if (position != null) {
            position.updatePeak(price)
            forcedExit(price, position, indicators)?.let { return it }
            if (value >= overbought) {
                return Decision(Signal.SELL, "RSI suracheté (${value.toInt()})", indicators)
            }
            return Decision(Signal.HOLD, "Position conservée", indicators)
        }
        if (value <= oversold) {
            return Decision(Signal.BUY, "RSI survendu (${value.toInt()})", indicators)
        }
        return Decision(Signal.HOLD, "RSI neutre (${value.toInt()})", indicators)
    }
}

/** Suivi de tendance sur le croisement MACD / ligne de signal. */
class MacdCrossover(
    private val fast: Int = 12,
    private val slow: Int = 26,
    private val signalPeriod: Int = 9,
    stopLossPct: Double = 5.0,
    trailingStopPct: Double = 0.0,
) : ProtectedStrategy(stopLossPct, trailingStopPct) {

    override val name = "MACD"
    override val description =
        "Suit la tendance : achète quand la dynamique passe au vert, vend quand elle passe au rouge."
    override val warmup get() = slow + signalPeriod + 2

    override fun decide(candles: List<Candle>, position: Position?): Decision {
        val closes = candles.map { it.close }
        val price = closes.lastOrNull() ?: return Decision(Signal.HOLD, "Pas de données")
        if (candles.size < warmup) {
            return Decision(Signal.HOLD, "Chargement (${candles.size}/$warmup bougies)")
        }
        val (line, signalLine) = Indicators.macd(closes, fast, slow, signalPeriod)
        val (wasLine, wasSignal) = Indicators.macd(closes.dropLast(1), fast, slow, signalPeriod)
        if (line == null || signalLine == null || wasLine == null || wasSignal == null) {
            return Decision(Signal.HOLD, "Chargement")
        }
        val indicators = mapOf("price" to price, "macd" to line, "macd_signal" to signalLine)
        val crossedUp = wasLine <= wasSignal && line > signalLine
        val crossedDown = wasLine >= wasSignal && line < signalLine

        if (position != null) {
            position.updatePeak(price)
            forcedExit(price, position, indicators)?.let { return it }
            if (crossedDown) return Decision(Signal.SELL, "MACD croise vers le bas", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)
        }
        if (crossedUp) return Decision(Signal.BUY, "MACD croise vers le haut", indicators)
        return Decision(Signal.HOLD, "Pas de croisement", indicators)
    }
}

/** Retour à la moyenne sur les bandes de Bollinger. */
class BollingerReversion(
    private val period: Int = 20,
    private val deviations: Double = 2.0,
    stopLossPct: Double = 5.0,
    trailingStopPct: Double = 0.0,
) : ProtectedStrategy(stopLossPct, trailingStopPct) {

    override val name = "Bollinger"
    override val description =
        "Achète quand le prix sort anormalement bas, revend quand il revient à sa moyenne."
    override val warmup get() = period + 2

    override fun decide(candles: List<Candle>, position: Position?): Decision {
        val closes = candles.map { it.close }
        val price = closes.lastOrNull() ?: return Decision(Signal.HOLD, "Pas de données")
        if (candles.size < warmup) {
            return Decision(Signal.HOLD, "Chargement (${candles.size}/$warmup bougies)")
        }
        val (lower, middle, upper) = Indicators.bollinger(closes, period, deviations)!!
        val indicators = mapOf(
            "price" to price, "bb_lower" to lower, "bb_mid" to middle, "bb_upper" to upper,
        )

        if (position != null) {
            position.updatePeak(price)
            forcedExit(price, position, indicators)?.let { return it }
            if (price >= middle) {
                return Decision(Signal.SELL, "Retour à la moyenne atteint", indicators)
            }
            return Decision(Signal.HOLD, "Position conservée", indicators)
        }
        if (price <= lower) return Decision(Signal.BUY, "Prix sous la bande basse", indicators)
        return Decision(Signal.HOLD, "Prix dans les bandes", indicators)
    }
}

/** Cassure de canal, la méthode « turtle » historique. */
class DonchianBreakout(
    private val entryPeriod: Int = 20,
    private val exitPeriod: Int = 10,
    stopLossPct: Double = 5.0,
    trailingStopPct: Double = 0.0,
) : ProtectedStrategy(stopLossPct, trailingStopPct) {

    override val name = "Donchian"
    override val description =
        "Achète quand le prix casse son plus haut récent, vend quand il casse son plus bas."
    override val warmup get() = maxOf(entryPeriod, exitPeriod) + 2

    override fun decide(candles: List<Candle>, position: Position?): Decision {
        val price = candles.lastOrNull()?.close ?: return Decision(Signal.HOLD, "Pas de données")
        if (candles.size < warmup) {
            return Decision(Signal.HOLD, "Chargement (${candles.size}/$warmup bougies)")
        }
        val (entryHigh, _) = Indicators.donchian(candles, entryPeriod)!!
        val (_, exitLow) = Indicators.donchian(candles, exitPeriod)!!
        val indicators = mapOf(
            "price" to price, "channel_high" to entryHigh, "channel_low" to exitLow,
        )

        if (position != null) {
            position.updatePeak(price)
            forcedExit(price, position, indicators)?.let { return it }
            if (price < exitLow) return Decision(Signal.SELL, "Cassure du plus bas", indicators)
            return Decision(Signal.HOLD, "Position conservée", indicators)
        }
        if (price > entryHigh) return Decision(Signal.BUY, "Cassure du plus haut", indicators)
        return Decision(Signal.HOLD, "Pas de cassure", indicators)
    }
}

/**
 * Référence de contrôle : n'achète jamais, reste 100% en liquide.
 *
 * Elle démasque un piège classique : en marché baissier, n'importe quelle
 * stratégie peu exposée « bat » le buy & hold sans le moindre mérite. Une
 * stratégie qui ne bat pas celle-ci n'a aucun avantage réel — elle est
 * simplement absente au bon moment.
 */
class CashBaseline : Strategy {
    override val name = "Ne rien faire (liquide)"
    override val description =
        "N'achète jamais. Sert de référence : toute stratégie qui ne la bat pas est inutile."
    override val warmup = 2
    override fun decide(candles: List<Candle>, position: Position?): Decision =
        Decision(Signal.HOLD, "Reste en liquide")
}

object StrategyRegistry {
    fun all(): List<Strategy> = listOf(
        SmaCrossover(),
        SmaCrossover(useTrendFilter = true, name = "Moyennes + filtre tendance"),
        RsiReversion(),
        MacdCrossover(),
        BollingerReversion(),
        DonchianBreakout(),
        CashBaseline(),
    )

    /** Stratégies réellement traçables (sans la référence de contrôle). */
    fun tradable(): List<Strategy> = all().filterNot { it is CashBaseline }

    fun byName(name: String): Strategy = all().firstOrNull { it.name == name } ?: SmaCrossover()
}
