package com.tradebot

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Assessment
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.tradebot.core.BacktestResult
import com.tradebot.core.Backtester
import com.tradebot.core.CashBaseline
import com.tradebot.core.Mode
import com.tradebot.core.RevxClient
import com.tradebot.core.StrategyRegistry
import com.tradebot.data.Settings
import com.tradebot.ui.BacktestScreen
import com.tradebot.ui.LiveScreen
import com.tradebot.ui.SettingsScreen
import com.tradebot.ui.StudyRow
import com.tradebot.ui.StudyScreen
import com.tradebot.ui.TradebotTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Le service en avant-plan a besoin de pouvoir afficher sa notification
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        setContent { TradebotTheme { AppRoot() } }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun AppRoot() {
        val settings = remember { Settings(applicationContext) }
        var settingsVersion by remember { mutableIntStateOf(0) }
        var tab by remember { mutableIntStateOf(0) }
        val scope = rememberCoroutineScope()

        val state by BotService.state.collectAsState()
        val log by BotService.log.collectAsState()
        val running by BotService.running.collectAsState()
        val mode by BotService.mode.collectAsState()

        var backtest by remember { mutableStateOf<BacktestResult?>(null) }
        var backtestRunning by remember { mutableStateOf(false) }
        var backtestError by remember { mutableStateOf<String?>(null) }

        var studyRows by remember { mutableStateOf<List<StudyRow>>(emptyList()) }
        var studyRunning by remember { mutableStateOf(false) }
        var studyProgress by remember { mutableStateOf("") }

        Surface {
            Scaffold(
                topBar = {
                    TopAppBar(
                        title = {
                            Text("Tradebot", fontWeight = FontWeight.Bold, fontSize = 18.sp)
                        },
                        colors = TopAppBarDefaults.topAppBarColors(),
                    )
                },
                bottomBar = {
                    NavigationBar {
                        listOf(
                            Triple(0, "Direct", Icons.Filled.ShowChart),
                            Triple(1, "Stratégies", Icons.Filled.Insights),
                            Triple(2, "Backtest", Icons.Filled.Assessment),
                            Triple(3, "Réglages", Icons.Filled.Settings),
                        ).forEach { (index, label, icon) ->
                            NavigationBarItem(
                                selected = tab == index,
                                onClick = { tab = index },
                                icon = { Icon(icon, contentDescription = label) },
                                label = { Text(label, fontSize = 11.sp) },
                            )
                        }
                    }
                },
            ) { padding ->
                // settingsVersion force la recomposition quand les réglages changent
                @Suppress("UNUSED_EXPRESSION") settingsVersion

                when (tab) {
                    0 -> LiveScreen(
                        state = state,
                        log = log,
                        running = running,
                        mode = mode,
                        settings = settings,
                        onStart = { chosen -> BotService.start(this@MainActivity, chosen) },
                        onStop = { BotService.stop(this@MainActivity) },
                        modifier = Modifier.padding(padding),
                    )

                    1 -> StudyScreen(
                        rows = studyRows,
                        running = studyRunning,
                        progress = studyProgress,
                        onRun = {
                            studyRunning = true
                            scope.launch {
                                studyRows = withContext(Dispatchers.IO) {
                                    runStudy(settings) { studyProgress = it }
                                }
                                studyRunning = false
                            }
                        },
                        modifier = Modifier.padding(padding),
                    )

                    2 -> BacktestScreen(
                        strategyName = settings.strategyName,
                        symbol = settings.symbol,
                        result = backtest,
                        running = backtestRunning,
                        error = backtestError,
                        onRun = {
                            backtestRunning = true
                            backtestError = null
                            scope.launch {
                                runCatching {
                                    withContext(Dispatchers.IO) {
                                        val client = RevxClient()
                                        val candles = client.candles(
                                            settings.symbol, settings.intervalMinutes,
                                        )
                                        Backtester.run(
                                            candles,
                                            StrategyRegistry.byName(settings.strategyName),
                                            settings.capitalEur,
                                        )
                                    }
                                }.onSuccess { backtest = it }
                                    .onFailure { backtestError = it.message }
                                backtestRunning = false
                            }
                        },
                        modifier = Modifier.padding(padding),
                    )

                    else -> SettingsScreen(
                        settings = settings,
                        onChanged = { settingsVersion++ },
                        modifier = Modifier.padding(padding),
                    )
                }
            }
        }
    }

    /**
     * Rejoue toutes les stratégies sur plusieurs paires et les classe.
     * La référence « ne rien faire » est incluse volontairement : si elle
     * arrive en tête, c'est que l'avantage des autres n'était qu'une absence.
     */
    private fun runStudy(settings: Settings, onProgress: (String) -> Unit): List<StudyRow> {
        val client = RevxClient()
        val pairs = runCatching { client.liquidPairs(top = 8) }
            .getOrDefault(listOf(settings.symbol))

        val candlesByPair = mutableMapOf<String, List<com.tradebot.core.Candle>>()
        pairs.forEachIndexed { index, pair ->
            onProgress("Téléchargement ${index + 1}/${pairs.size} — $pair")
            runCatching { client.candles(pair, settings.intervalMinutes) }
                .onSuccess { candlesByPair[pair] = it }
            Thread.sleep(1200)  // budget de l'API publique : ~1 requête/seconde
        }

        val window = if (settings.intervalMinutes == "1440") 60 else 150

        return StrategyRegistry.all().map { strategy ->
            onProgress("Analyse — ${strategy.name}")
            val edges = mutableListOf<Pair<Double, Int>>()
            val returns = mutableListOf<Double>()
            val holds = mutableListOf<Double>()
            val exposures = mutableListOf<Double>()

            candlesByPair.values.forEach { candles ->
                var start = strategy.warmup
                while (start + window <= candles.size) {
                    val leadIn = maxOf(0, start - strategy.warmup)
                    val segment = candles.subList(leadIn, start + window)
                    if (segment.size <= strategy.warmup + 5) break
                    val result = Backtester.run(segment, strategy, settings.capitalEur)
                    edges.add((result.returnPct - result.holdReturnPct) to result.trades.size)
                    returns.add(result.returnPct)
                    holds.add(result.holdReturnPct)
                    exposures.add(result.exposurePct)
                    start += window
                }
            }

            val score = Backtester.score(strategy.name, edges)
            StudyRow(
                name = strategy.name,
                periods = score.periods,
                winRate = score.winRate,
                meanEdge = score.meanEdge,
                ciLow = score.ciLow,
                ciHigh = score.ciHigh,
                significant = score.significant,
                avgReturn = returns.average().takeIf { !it.isNaN() } ?: 0.0,
                avgHoldReturn = holds.average().takeIf { !it.isNaN() } ?: 0.0,
                exposurePct = exposures.average().takeIf { !it.isNaN() } ?: 0.0,
                isCashBaseline = strategy is CashBaseline,
            )
        }.sortedByDescending { it.meanEdge }
    }
}
