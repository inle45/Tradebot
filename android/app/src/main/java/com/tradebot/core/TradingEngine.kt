package com.tradebot.core

import com.tradebot.data.Settings

enum class Mode { PAPER, LIVE }

/** Une décision passée, pour l'historique affiché dans l'app. */
data class LogEntry(
    val time: Long,
    val signal: Signal,
    val price: Double,
    val reason: String,
    val portfolioValue: Double,
    val executed: Boolean,
)

data class EngineState(
    val price: Double = 0.0,
    val signal: Signal = Signal.HOLD,
    val reason: String = "En attente du premier cycle",
    val cash: Double = 0.0,
    val positionSize: Double = 0.0,
    val entryPrice: Double? = null,
    val portfolioValue: Double = 0.0,
    val initialEur: Double = 100.0,
    val indicators: Map<String, Double> = emptyMap(),
    val candles: List<Candle> = emptyList(),
    val lastUpdate: Long = 0L,
    val error: String? = null,
)

/**
 * Moteur de trading, commun à la simulation et au réel.
 *
 * En simulation, aucun ordre n'est envoyé : le portefeuille est virtuel mais
 * les prix et les frais sont réels. En mode réel, les ordres partent vraiment,
 * et un plafond limite ce qui peut être engagé.
 */
class TradingEngine(
    private val settings: Settings,
    private val client: RevxClient,
    private val mode: Mode,
) {
    val strategy: Strategy = StrategyRegistry.byName(settings.strategyName)

    private var cash: Double = settings.loadCash()
    private var position: Position? = settings.loadPosition()?.let { (entry, size, peak) ->
        Position(entry, size, peak)
    }

    // Devise de cotation ("EUR" dans "SOL/EUR") : c'est elle qu'on interroge
    // pour connaître le vrai solde disponible en mode réel.
    private val quoteCurrency = settings.symbol.substringAfter("/", "EUR")

    val log = ArrayDeque<LogEntry>()

    fun currentState(): EngineState = EngineState(
        cash = cash,
        positionSize = position?.size ?: 0.0,
        entryPrice = position?.entryPrice,
        initialEur = settings.capitalEur,
    )

    /** Un cycle : récupère les prix, décide, agit, sauvegarde. */
    fun step(): EngineState {
        // En mode réel, la trésorerie affichée et utilisée pour dimensionner
        // les ordres vient toujours du vrai solde Revolut, jamais du compteur
        // virtuel de la simulation : sinon l'app pourrait engager plus (ou
        // moins) que ce qui est réellement disponible sur le compte. Si cet
        // appel échoue, on l'affiche clairement au lieu de continuer avec un
        // chiffre local périmé — mieux vaut un cycle sans rien faire qu'un
        // ordre dimensionné sur un solde qu'on ne connaît plus.
        if (mode == Mode.LIVE) {
            val fetched = runCatching { client.balance(quoteCurrency) }
            val error = fetched.exceptionOrNull()
            if (error != null) {
                return currentState().copy(
                    error = "Solde Revolut indisponible (${error.message ?: error::class.simpleName}) " +
                        "— le bot n'agit pas ce cycle.",
                )
            }
            cash = fetched.getOrThrow()
        }

        val candles = client.candles(settings.symbol, settings.intervalMinutes)
        if (candles.isEmpty()) {
            return currentState().copy(error = "Aucune donnée de prix reçue")
        }

        val price = candles.last().close
        val decision = strategy.decide(candles, position)
        var executed = false

        if (decision.signal == Signal.BUY && position == null) {
            executed = buy(price)
        } else if (decision.signal == Signal.SELL && position != null) {
            executed = sell(price)
        }

        settings.savePosition(position?.entryPrice, position?.size, position?.peak, cash)

        val value = cash + (position?.let { it.size * price } ?: 0.0)
        if (decision.signal != Signal.HOLD) {
            log.addFirst(
                LogEntry(System.currentTimeMillis(), decision.signal, price,
                    decision.reason, value, executed)
            )
            while (log.size > 50) log.removeLast()
        }

        return EngineState(
            price = price,
            signal = decision.signal,
            reason = decision.reason,
            cash = cash,
            positionSize = position?.size ?: 0.0,
            entryPrice = position?.entryPrice,
            portfolioValue = value,
            initialEur = settings.capitalEur,
            indicators = decision.indicators,
            candles = candles.takeLast(180),
            lastUpdate = System.currentTimeMillis(),
        )
    }

    private fun buy(price: Double): Boolean {
        // Le plafond s'applique dans les deux modes : il borne le risque réel
        // et garde la simulation comparable au réel.
        val budget = minOf(cash, settings.capitalEur)
        if (budget <= 0) return false

        return if (mode == Mode.LIVE) {
            runCatching {
                client.placeMarketOrder(settings.symbol, "buy", quoteSize = budget)
            }.map {
                position = Position(price, budget * (1 - Fees.TAKER) / price, price)
                cash -= budget
                true
            }.getOrDefault(false)
        } else {
            position = Position(price, budget * (1 - Fees.TAKER) / price, price)
            cash -= budget
            true
        }
    }

    private fun sell(price: Double): Boolean {
        val held = position ?: return false
        return if (mode == Mode.LIVE) {
            runCatching {
                client.placeMarketOrder(settings.symbol, "sell", baseSize = held.size)
            }.map {
                cash += held.size * price * (1 - Fees.TAKER)
                position = null
                true
            }.getOrDefault(false)
        } else {
            cash += held.size * price * (1 - Fees.TAKER)
            position = null
            true
        }
    }
}
