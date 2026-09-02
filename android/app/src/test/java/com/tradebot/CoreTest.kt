package com.tradebot

import com.tradebot.core.Backtester
import com.tradebot.core.BollingerReversion
import com.tradebot.core.Candle
import com.tradebot.core.DonchianBreakout
import com.tradebot.core.Indicators
import com.tradebot.core.MacdCrossover
import com.tradebot.core.Position
import com.tradebot.core.RsiReversion
import com.tradebot.core.Signal
import com.tradebot.core.SmaCrossover
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreTest {

    private fun candles(prices: List<Double>): List<Candle> =
        prices.mapIndexed { i, p ->
            Candle(i * 3_600_000L, p, p * 1.01, p * 0.99, p, 1.0)
        }

    // ---------- Indicateurs ----------

    @Test
    fun smaComputesAverage() {
        assertEquals(2.0, Indicators.sma(listOf(1.0, 2.0, 3.0), 3)!!, 1e-9)
        assertNull(Indicators.sma(listOf(1.0, 2.0), 3))
    }

    @Test
    fun emaReactsFasterThanSmaToARecentJump() {
        // Sur une rampe linéaire, EMA et SMA sont identiques : ce n'est pas là
        // que les deux se distinguent. La différence apparaît sur un saut récent,
        // que l'EMA prend davantage en compte.
        val jump = List(15) { 10.0 } + listOf(20.0)
        val emaValue = Indicators.ema(jump, 10)!!
        val smaValue = Indicators.sma(jump, 10)!!
        assertTrue(
            "l'EMA doit réagir plus vite au saut (ema=$emaValue, sma=$smaValue)",
            emaValue > smaValue,
        )

        val linear = (1..20).map { it.toDouble() }
        assertEquals(
            "sur une rampe linéaire les deux coïncident",
            Indicators.sma(linear, 10)!!, Indicators.ema(linear, 10)!!, 1e-9,
        )
    }

    @Test
    fun rsiIsHighWhenPricesOnlyRise() {
        val value = Indicators.rsi((1..30).map { it.toDouble() }, 14)!!
        assertTrue("hausse continue -> RSI proche de 100, obtenu $value", value > 95)
    }

    @Test
    fun rsiIsLowWhenPricesOnlyFall() {
        val value = Indicators.rsi((1..30).map { (60 - it).toDouble() }, 14)!!
        assertTrue("baisse continue -> RSI proche de 0, obtenu $value", value < 5)
    }

    @Test
    fun bollingerBandsSurroundTheAverage() {
        val (lower, middle, upper) = Indicators.bollinger(
            listOf(10.0, 12.0, 11.0, 13.0, 9.0, 11.0, 12.0, 10.0, 11.0, 12.0,
                   10.0, 11.0, 13.0, 12.0, 11.0, 10.0, 12.0, 11.0, 13.0, 11.0),
            20, 2.0,
        )!!
        assertTrue(lower < middle && middle < upper)
    }

    @Test
    fun donchianExcludesCurrentCandle() {
        // La dernière bougie est un sommet : il ne doit pas apparaître dans le canal,
        // sinon la cassure se déclencherait sur elle-même.
        val list = candles(listOf(10.0, 11.0, 12.0, 11.0, 10.0, 50.0))
        val (high, _) = Indicators.donchian(list, 5)!!
        assertTrue("le plus haut du canal ne doit pas inclure la bougie courante", high < 50)
    }

    @Test
    fun atrIsPositive() {
        assertTrue(Indicators.atr(candles(listOf(10.0, 11.0, 12.0, 13.0)), 2)!! > 0)
    }

    // ---------- Stratégies ----------

    @Test
    fun smaBuysOnUpwardCrossover() {
        val strategy = SmaCrossover(short = 3, long = 5, stopLossPct = 0.0)
        val decision = strategy.decide(candles(List(5) { 10.0 } + listOf(11.0)), null)
        assertEquals(Signal.BUY, decision.signal)
    }

    @Test
    fun smaCrossoverIsStateless() {
        // Deux instances distinctes doivent décider pareil sur les mêmes données.
        val prices = List(5) { 10.0 } + listOf(11.0, 12.0, 11.0, 10.0, 12.0)
        val data = candles(prices)
        val progressive = SmaCrossover(short = 3, long = 5, stopLossPct = 0.0)
        for (i in 6..prices.size) progressive.decide(data.subList(0, i), null)
        val fresh = SmaCrossover(short = 3, long = 5, stopLossPct = 0.0)
        assertEquals(fresh.decide(data, null).signal, progressive.decide(data, null).signal)
    }

    @Test
    fun stopLossFiresBeforeAnyOtherSignal() {
        val strategy = SmaCrossover(short = 3, long = 5, stopLossPct = 5.0)
        val position = Position(entryPrice = 100.0, size = 1.0, peak = 100.0)
        val decision = strategy.decide(candles(List(5) { 100.0 } + listOf(94.0)), position)
        assertEquals(Signal.SELL, decision.signal)
        assertTrue(decision.reason.contains("Stop-loss"))
    }

    @Test
    fun trailingStopFiresAfterAPeak() {
        val strategy = SmaCrossover(short = 3, long = 5, stopLossPct = 0.0, trailingStopPct = 10.0)
        val position = Position(entryPrice = 100.0, size = 1.0, peak = 120.0)
        val decision = strategy.decide(candles(List(5) { 100.0 } + listOf(105.0)), position)
        assertEquals(Signal.SELL, decision.signal)
        assertTrue(decision.reason.contains("Trailing"))
    }

    @Test
    fun trendFilterBlocksBuyBelowTheTrend() {
        val strategy = SmaCrossover(
            short = 3, long = 5, useTrendFilter = true, trendPeriod = 15, stopLossPct = 0.0,
        )
        val prices = listOf(100.0, 95.0, 90.0, 85.0, 80.0, 75.0, 70.0, 65.0, 60.0,
                            55.0, 50.0, 45.0, 40.0, 35.0, 30.0, 33.0, 38.0, 44.0)
        // Sans filtre le croisement déclenche bien un achat...
        val unfiltered = SmaCrossover(short = 3, long = 5, stopLossPct = 0.0)
        assertEquals(Signal.BUY, unfiltered.decide(candles(prices), null).signal)
        // ...mais le filtre de tendance doit le bloquer.
        val decision = strategy.decide(candles(prices), null)
        assertEquals(Signal.HOLD, decision.signal)
        assertTrue(decision.reason.contains("tendance"))
    }

    @Test
    fun rsiBuysOversoldAndSellsOverbought() {
        val falling = candles((1..30).map { (60 - it).toDouble() })
        assertEquals(Signal.BUY, RsiReversion(stopLossPct = 0.0).decide(falling, null).signal)

        val rising = candles((1..30).map { it.toDouble() })
        val position = Position(entryPrice = 1.0, size = 1.0, peak = 30.0)
        assertEquals(Signal.SELL, RsiReversion(stopLossPct = 0.0).decide(rising, position).signal)
    }

    @Test
    fun donchianBuysOnBreakout() {
        val prices = List(25) { 10.0 } + listOf(20.0)
        val decision = DonchianBreakout(stopLossPct = 0.0).decide(candles(prices), null)
        assertEquals(Signal.BUY, decision.signal)
    }

    @Test
    fun strategiesReportEnoughWarmup() {
        for (strategy in com.tradebot.core.StrategyRegistry.all()) {
            val short = candles(List(3) { 10.0 })
            assertEquals(
                "${strategy.name} doit attendre d'avoir assez de données",
                Signal.HOLD, strategy.decide(short, null).signal,
            )
        }
    }

    @Test
    fun macdProducesBothLines() {
        val prices = (1..60).map { 100.0 + it * 0.5 }
        val (line, signal) = Indicators.macd(prices)
        assertNotNull(line)
        assertNotNull(signal)
    }

    @Test
    fun macdStrategyRunsWithoutCrashing() {
        val prices = (1..80).map { 100.0 + kotlin.math.sin(it / 5.0) * 10 }
        val decision = MacdCrossover(stopLossPct = 0.0).decide(candles(prices), null)
        assertNotNull(decision.signal)
    }

    @Test
    fun bollingerBuysBelowLowerBand() {
        val prices = List(25) { 100.0 } + listOf(80.0)
        val decision = BollingerReversion(stopLossPct = 0.0).decide(candles(prices), null)
        assertEquals(Signal.BUY, decision.signal)
    }

    // ---------- Backtest ----------

    @Test
    fun backtestAlwaysReportsTheHoldBenchmark() {
        val prices = List(10) { 10.0 } + listOf(11.0, 12.0, 13.0, 12.0, 11.0, 12.0, 14.0)
        val result = Backtester.run(candles(prices), SmaCrossover(3, 5, stopLossPct = 0.0))
        assertTrue(result.holdValue > 0)
        assertEquals(result.finalValue > result.holdValue, result.beatsHold)
    }

    @Test
    fun feesReduceTheResult() {
        val prices = List(10) { 10.0 } +
            listOf(11.0, 12.0, 11.0, 10.0, 11.0, 12.0, 13.0, 12.0, 11.0, 12.0, 13.0)
        val strategy = SmaCrossover(3, 5, stopLossPct = 0.0)
        val free = Backtester.run(candles(prices), strategy, 100.0, 0.0)
        val costly = Backtester.run(candles(prices), strategy, 100.0, 0.01)
        if (free.trades.isNotEmpty()) {
            assertTrue("les frais doivent réduire le résultat",
                costly.finalValue < free.finalValue)
        }
    }

    @Test
    fun maxDrawdownMeasuresTheWorstFall() {
        // De 100 à 50 = -50%
        assertEquals(-50.0, Backtester.maxDrawdown(listOf(100.0, 80.0, 50.0, 90.0)), 1e-9)
        assertEquals(0.0, Backtester.maxDrawdown(listOf(10.0, 20.0, 30.0)), 1e-9)
    }

    @Test
    fun scoreFlagsNoiseAsNotSignificant() {
        // Écarts symétriques autour de zéro : aucun avantage réel
        val noise = listOf(5.0 to 1, -5.0 to 1, 4.0 to 1, -4.0 to 1, 3.0 to 1, -3.0 to 1)
        assertTrue(!Backtester.score("bruit", noise).significant)
    }

    @Test
    fun scoreFlagsAConsistentEdgeAsSignificant() {
        // Avantage régulier et net : doit ressortir comme significatif
        val consistent = List(20) { 5.0 + (it % 3) * 0.1 to 1 }
        val score = Backtester.score("avantage", consistent)
        assertTrue("un avantage régulier doit être détecté", score.significant)
        assertTrue(score.ciLow > 0)
    }
}
