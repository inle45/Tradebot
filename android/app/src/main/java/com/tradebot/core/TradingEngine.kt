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
    /** Avoirs réels dans l'actif tradé, lus sur le compte en mode réel. */
    val baseBalance: Double = 0.0,
    /** Devise avec laquelle on achète : "EUR" pour SOL/EUR, "USDC" pour SOL/USDC. */
    val quoteCurrency: String = "EUR",
    val portfolioValue: Double = 0.0,
    /**
     * Valeur de référence à laquelle comparer le portefeuille. En simulation
     * c'est le capital de départ ; en réel, la valeur du compte au premier
     * cycle — le plafond de Réglages n'est pas un capital investi.
     */
    val initialEur: Double = 100.0,
    /** Ce que mesure l'écart affiché, pour ne pas le faire passer pour autre chose. */
    val referenceLabel: String = "capital de départ",
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

    // "SOL/EUR" : SOL est l'actif tradé, EUR la devise qui sert à l'acheter.
    // Ce sont ces deux soldes qu'on lit sur le compte en mode réel.
    private val baseCurrency = settings.symbol.substringBefore("/")
    private val quoteCurrency = settings.symbol.substringAfter("/", "EUR")

    private var baseBalance: Double = 0.0

    val log = ArrayDeque<LogEntry>()

    fun currentState(): EngineState = EngineState(
        cash = cash,
        positionSize = position?.size ?: 0.0,
        entryPrice = position?.entryPrice,
        baseBalance = baseBalance,
        quoteCurrency = quoteCurrency,
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
            val fetched = runCatching { client.balances() }
            val error = fetched.exceptionOrNull()
            if (error != null) {
                return currentState().copy(
                    error = "Solde Revolut indisponible (${error.message ?: error::class.simpleName}) " +
                        "— le bot n'agit pas ce cycle.",
                )
            }
            val balances = fetched.getOrThrow()
            cash = balances[quoteCurrency] ?: 0.0
            baseBalance = balances[baseCurrency] ?: 0.0
        }

        val candles = client.candles(settings.symbol, settings.intervalMinutes)
        if (candles.isEmpty()) {
            return currentState().copy(error = "Aucune donnée de prix reçue")
        }

        val price = candles.last().close
        val decision = strategy.decide(candles, position)
        var executed = false
        rejection = null

        if (decision.signal == Signal.BUY && position == null) {
            executed = buy(price)
        } else if (decision.signal == Signal.SELL && position != null) {
            executed = sell(price)
        }

        settings.savePosition(position?.entryPrice, position?.size, position?.peak, cash)

        // En réel, la valeur affichée est celle du compte tel qu'il est vraiment :
        // liquide + avoirs, y compris ceux que le bot n'a pas achetés lui-même.
        val value = if (mode == Mode.LIVE) {
            cash + baseBalance * price
        } else {
            cash + (position?.let { it.size * price } ?: 0.0)
        }

        // Point de comparaison honnête : en réel, la valeur du compte au premier
        // cycle. Sans cela l'écart se mesurerait depuis le plafond de Réglages,
        // qui n'a jamais été investi.
        val reference = if (mode == Mode.LIVE) {
            settings.liveBaseline(settings.symbol)
                ?: value.also { settings.saveLiveBaseline(settings.symbol, it) }
        } else {
            settings.capitalEur
        }
        if (decision.signal != Signal.HOLD) {
            log.addFirst(
                LogEntry(System.currentTimeMillis(), decision.signal, price,
                    decision.reason, value, executed)
            )
            while (log.size > 50) log.removeLast()
        }

        // Sans liquide sur le compte, un signal d'achat ne peut pas être exécuté.
        // Mieux vaut le dire que laisser le bot paraître inactif sans raison.
        val blocked = rejection ?: if (mode == Mode.LIVE && cash <= 0.0 && position == null) {
            "Aucun $quoteCurrency disponible sur Revolut X : le bot ne peut rien " +
                "acheter tant que le compte n'est pas approvisionné. " +
                "La paire ${settings.symbol} s'achète en $quoteCurrency."
        } else null

        return EngineState(
            price = price,
            signal = decision.signal,
            reason = decision.reason,
            cash = cash,
            positionSize = position?.size ?: 0.0,
            entryPrice = position?.entryPrice,
            baseBalance = baseBalance,
            quoteCurrency = quoteCurrency,
            portfolioValue = value,
            initialEur = reference,
            referenceLabel = if (mode == Mode.LIVE) "démarrage du bot" else "capital de départ",
            indicators = decision.indicators,
            candles = candles.takeLast(180),
            lastUpdate = System.currentTimeMillis(),
            error = blocked,
        )
    }

    /**
     * Motif du dernier ordre refusé par la plateforme. Un ordre rejeté en
     * silence (montant sous le minimum, fonds insuffisants) laisserait le bot
     * paraître inactif sans qu'on sache pourquoi.
     */
    private var rejection: String? = null

    private fun buy(price: Double): Boolean {
        // Le plafond s'applique dans les deux modes : il borne le risque réel
        // et garde la simulation comparable au réel.
        val budget = minOf(cash, settings.capitalEur)
        if (budget <= 0) return false

        return if (mode == Mode.LIVE) {
            runCatching {
                client.placeMarketOrder(settings.symbol, "buy", quoteSize = budget)
            }.fold(
                onSuccess = {
                    position = Position(price, budget * (1 - Fees.TAKER) / price, price)
                    cash -= budget
                    true
                },
                onFailure = { error ->
                    rejection = "Achat refusé : ${error.message ?: error::class.simpleName}"
                    false
                },
            )
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
            }.fold(
                onSuccess = {
                    cash += held.size * price * (1 - Fees.TAKER)
                    position = null
                    true
                },
                onFailure = { error ->
                    // La position reste ouverte : on n'invente pas une vente
                    // qui n'a pas eu lieu.
                    rejection = "Vente refusée : ${error.message ?: error::class.simpleName}"
                    false
                },
            )
        } else {
            cash += held.size * price * (1 - Fees.TAKER)
            position = null
            true
        }
    }
}
