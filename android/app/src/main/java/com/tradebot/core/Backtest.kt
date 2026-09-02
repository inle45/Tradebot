package com.tradebot.core

import kotlin.math.abs
import kotlin.math.sqrt

/** Frais Revolut X : 0% en maker (ordre limite), 0,09% en taker (ordre marché). */
object Fees {
    const val TAKER = 0.0009
    const val MAKER = 0.0
}

/** Résultat agrégé d'une stratégie évaluée sur plusieurs périodes. */
data class StrategyScore(
    val name: String,
    val periods: Int,
    val winRate: Double,
    val meanEdge: Double,
    val ciLow: Double,
    val ciHigh: Double,
    val tStat: Double,
    val significant: Boolean,
    val avgTrades: Double,
)

object Backtester {

    /**
     * Rejoue une stratégie sur l'historique. Le résultat inclut toujours la
     * référence buy & hold : une stratégie qui ne la bat pas fait perdre de
     * l'argent par rapport à l'inaction.
     */
    fun run(
        candles: List<Candle>,
        strategy: Strategy,
        initialEur: Double = 100.0,
        fee: Double = Fees.TAKER,
    ): BacktestResult {
        val warmup = strategy.warmup
        var cash = initialEur
        var position: Position? = null
        val trades = mutableListOf<Trade>()
        val equity = mutableListOf<Double>()
        var barsInMarket = 0

        for (i in warmup until candles.size) {
            val window = candles.subList(0, i + 1)
            val price = window.last().close
            val decision = strategy.decide(window, position)

            if (decision.signal == Signal.BUY && position == null) {
                val size = (cash * (1 - fee)) / price
                position = Position(entryPrice = price, size = size, peak = price)
                cash = 0.0
            } else if (decision.signal == Signal.SELL && position != null) {
                val proceeds = position.size * price * (1 - fee)
                trades.add(
                    Trade(
                        entryPrice = position.entryPrice,
                        exitPrice = price,
                        profitPct = (price / position.entryPrice - 1) * 100,
                        reason = decision.reason,
                        exitTime = window.last().start,
                    )
                )
                cash = proceeds
                position = null
            }

            if (position != null) barsInMarket++
            equity.add(cash + (position?.let { it.size * price } ?: 0.0))
        }

        if (equity.isEmpty()) {
            return BacktestResult(
                initialEur, initialEur, 0.0, initialEur, 0.0, false,
                emptyList(), 0.0, 0.0, emptyList(), 0, 0.0,
            )
        }

        val finalPrice = candles.last().close
        val finalValue = cash + (position?.let { it.size * finalPrice } ?: 0.0)
        val startPrice = candles[warmup].close
        val holdValue = (initialEur * (1 - fee) / startPrice) * finalPrice
        val wins = trades.count { it.profitPct > 0 }

        return BacktestResult(
            initialEur = initialEur,
            finalValue = finalValue,
            returnPct = (finalValue / initialEur - 1) * 100,
            holdValue = holdValue,
            holdReturnPct = (holdValue / initialEur - 1) * 100,
            beatsHold = finalValue > holdValue,
            trades = trades,
            winRate = if (trades.isEmpty()) 0.0 else wins * 100.0 / trades.size,
            maxDrawdownPct = maxDrawdown(equity),
            equityCurve = equity,
            candlesTested = candles.size - warmup,
            exposurePct = barsInMarket * 100.0 / equity.size,
        )
    }

    /** Pire chute depuis un sommet, en pourcentage. */
    fun maxDrawdown(curve: List<Double>): Double {
        var peak = Double.NEGATIVE_INFINITY
        var worst = 0.0
        for (value in curve) {
            peak = maxOf(peak, value)
            if (peak > 0) worst = minOf(worst, (value - peak) / peak * 100)
        }
        return worst
    }

    /**
     * Découpe l'historique en périodes successives et mesure l'écart face au
     * buy & hold sur chacune. Une seule période ne prouve rien : c'est la
     * régularité sur plusieurs périodes qui compte.
     */
    fun rollingEdges(
        candles: List<Candle>,
        strategy: Strategy,
        window: Int,
        initialEur: Double = 100.0,
        fee: Double = Fees.TAKER,
    ): List<Pair<Double, Int>> {
        val warmup = strategy.warmup
        val edges = mutableListOf<Pair<Double, Int>>()
        var start = warmup

        while (start + window <= candles.size) {
            val leadIn = maxOf(0, start - warmup)
            val segment = candles.subList(leadIn, start + window)
            if (segment.size <= warmup + 5) break
            val result = run(segment, strategy, initialEur, fee)
            edges.add((result.returnPct - result.holdReturnPct) to result.trades.size)
            start += window
        }
        return edges
    }

    /**
     * Un écart moyen positif ne veut rien dire s'il tient dans le bruit.
     * L'intervalle de confiance à 95% tranche : s'il contient zéro, on ne peut
     * pas distinguer la stratégie d'un tirage au sort.
     */
    fun score(name: String, edges: List<Pair<Double, Int>>): StrategyScore {
        val values = edges.map { it.first }
        val n = values.size
        if (n < 2) {
            return StrategyScore(name, n, 0.0, 0.0, 0.0, 0.0, 0.0, false, 0.0)
        }
        val mean = values.average()
        val variance = values.sumOf { (it - mean) * (it - mean) } / (n - 1)
        val standardError = sqrt(variance / n)
        val t = if (standardError == 0.0) 0.0 else mean / standardError

        return StrategyScore(
            name = name,
            periods = n,
            winRate = values.count { it > 0 } * 100.0 / n,
            meanEdge = mean,
            ciLow = mean - 1.96 * standardError,
            ciHigh = mean + 1.96 * standardError,
            tStat = t,
            significant = abs(t) > 1.96,
            avgTrades = edges.map { it.second }.average(),
        )
    }
}
