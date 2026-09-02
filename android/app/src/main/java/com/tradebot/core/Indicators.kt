package com.tradebot.core

import kotlin.math.abs
import kotlin.math.sqrt

/** Indicateurs techniques. Portés à l'identique de la version Python pour que
 * les résultats de l'app et ceux de l'étude soient comparables. */
object Indicators {

    fun sma(values: List<Double>, period: Int): Double? {
        if (values.size < period) return null
        return values.takeLast(period).sum() / period
    }

    fun ema(values: List<Double>, period: Int): Double? {
        if (values.size < period) return null
        val multiplier = 2.0 / (period + 1)
        var result = values.take(period).sum() / period
        for (i in period until values.size) {
            result = (values[i] - result) * multiplier + result
        }
        return result
    }

    /** Average True Range : mesure de volatilité. */
    fun atr(candles: List<Candle>, period: Int): Double? {
        if (candles.size < period + 1) return null
        val ranges = mutableListOf<Double>()
        for (i in candles.size - period until candles.size) {
            val current = candles[i]
            val previousClose = candles[i - 1].close
            ranges.add(
                maxOf(
                    current.high - current.low,
                    abs(current.high - previousClose),
                    abs(current.low - previousClose),
                )
            )
        }
        return ranges.average()
    }

    /** RSI : 0-100. Sous 30 = survendu, au-dessus de 70 = suracheté. */
    fun rsi(closes: List<Double>, period: Int = 14): Double? {
        if (closes.size < period + 1) return null
        var gains = 0.0
        var losses = 0.0
        for (i in closes.size - period until closes.size) {
            val change = closes[i] - closes[i - 1]
            if (change > 0) gains += change else losses -= change
        }
        val averageGain = gains / period
        val averageLoss = losses / period
        if (averageLoss == 0.0) return if (averageGain > 0) 100.0 else 50.0
        val strength = averageGain / averageLoss
        return 100 - (100 / (1 + strength))
    }

    /** Retourne (ligne MACD, ligne de signal). */
    fun macd(
        closes: List<Double>,
        fast: Int = 12,
        slow: Int = 26,
        signalPeriod: Int = 9,
    ): Pair<Double?, Double?> {
        if (closes.size < slow + signalPeriod) return null to null
        val series = mutableListOf<Double>()
        for (i in slow..closes.size) {
            val window = closes.subList(0, i)
            val fastEma = ema(window, fast) ?: continue
            val slowEma = ema(window, slow) ?: continue
            series.add(fastEma - slowEma)
        }
        if (series.size < signalPeriod) return null to null
        return series.last() to ema(series, signalPeriod)
    }

    /** Bandes de Bollinger : (basse, moyenne, haute). */
    fun bollinger(
        closes: List<Double>,
        period: Int = 20,
        deviations: Double = 2.0,
    ): Triple<Double, Double, Double>? {
        if (closes.size < period) return null
        val window = closes.takeLast(period)
        val middle = window.average()
        val variance = window.sumOf { (it - middle) * (it - middle) } / period
        val spread = sqrt(variance) * deviations
        return Triple(middle - spread, middle, middle + spread)
    }

    /** Canal de Donchian : (plus haut, plus bas) des N bougies précédentes,
     * la bougie courante exclue pour que le signal ne se déclenche pas seul. */
    fun donchian(candles: List<Candle>, period: Int): Pair<Double, Double>? {
        if (candles.size < period + 1) return null
        val window = candles.subList(candles.size - period - 1, candles.size - 1)
        return window.maxOf { it.high } to window.minOf { it.low }
    }
}
