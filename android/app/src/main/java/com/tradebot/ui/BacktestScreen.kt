package com.tradebot.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradebot.core.BacktestResult

@Composable
fun BacktestScreen(
    strategyName: String,
    symbol: String,
    result: BacktestResult?,
    running: Boolean,
    error: String?,
    onRun: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier.fillMaxSize().padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        item {
            Card {
                Label("Tester sur l'historique")
                Text(
                    "$strategyName · $symbol",
                    fontSize = 15.sp,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Note(
                    "Rejoue la stratégie sur les données réelles passées, frais compris, " +
                        "et compare le résultat au fait d'acheter puis de ne rien faire.",
                    Modifier.padding(top = 8.dp, bottom = 12.dp),
                )
                OutlinedButton(
                    onClick = onRun,
                    enabled = !running,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (running) "Calcul en cours…" else "Lancer le backtest") }
            }
        }

        error?.let {
            item { Card { Text("Erreur : $it", color = Red, fontSize = 12.5.sp) } }
        }

        result?.let { r ->
            item {
                Card {
                    Verdict(
                        positive = r.beatsHold,
                        title = if (r.beatsHold)
                            "La stratégie bat le buy & hold"
                        else
                            "La stratégie fait MOINS BIEN que ne rien faire",
                        subtitle = "écart : ${formatPoints(r.returnPct - r.holdReturnPct)} points",
                    )

                    Column(Modifier.padding(top = 14.dp)) {
                        Label("Évolution du capital")
                        EquityChart(
                            r.equityCurve, r.initialEur,
                            Modifier.padding(top = 8.dp),
                        )
                    }
                }
            }

            item {
                Card {
                    KeyValue("Capital de départ", formatEuro(r.initialEur))
                    KeyValue(
                        "Résultat de la stratégie",
                        "${formatEuro(r.finalValue)}  (${formatPercent(r.returnPct)})",
                        if (r.returnPct >= 0) Green else Red,
                    )
                    KeyValue(
                        "Acheter et ne rien faire",
                        "${formatEuro(r.holdValue)}  (${formatPercent(r.holdReturnPct)})",
                    )
                    KeyValue("Exposition au marché", "${r.exposurePct.toInt()}%")
                    KeyValue("Nombre de trades", "${r.trades.size}")
                    KeyValue("Trades gagnants", "${r.winRate.toInt()}%")
                    KeyValue("Pire chute", String.format("%.2f%%", r.maxDrawdownPct))
                    KeyValue("Bougies testées", "${r.candlesTested}")

                    if (r.exposurePct < 50 && r.holdReturnPct < 0) {
                        Note(
                            "Attention : sur cette période le marché baisse et la " +
                                "stratégie est restée hors du marché la plupart du temps. " +
                                "Son avantage vient surtout de son absence, pas de la " +
                                "qualité de ses décisions.",
                            Modifier.padding(top = 12.dp),
                        )
                    }
                }
            }

            if (r.trades.isNotEmpty()) {
                item {
                    Card {
                        Label("Derniers trades")
                        Column(Modifier.padding(top = 8.dp)) {
                            r.trades.takeLast(10).reversed().forEach { trade ->
                                KeyValue(
                                    "${formatEuro(trade.entryPrice)} → ${formatEuro(trade.exitPrice)}",
                                    formatPercent(trade.profitPct),
                                    if (trade.profitPct >= 0) Green else Red,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
