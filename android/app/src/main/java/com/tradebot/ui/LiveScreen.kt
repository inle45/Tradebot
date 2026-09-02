package com.tradebot.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradebot.core.EngineState
import com.tradebot.core.LogEntry
import com.tradebot.core.Mode
import com.tradebot.data.Settings

@Composable
fun LiveScreen(
    state: EngineState,
    log: List<LogEntry>,
    running: Boolean,
    mode: Mode,
    settings: Settings,
    onStart: (Mode) -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier.fillMaxSize().padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        item {
            Card {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Label(settings.symbol)
                    Text(
                        if (running) {
                            if (mode == Mode.LIVE) "● MODE RÉEL" else "● Simulation"
                        } else "○ À l'arrêt",
                        color = if (running) Green else MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 11.5.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                Text(
                    if (state.price > 0) formatMoney(state.price, state.quoteCurrency) else "—",
                    fontSize = 38.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.padding(top = 2.dp, bottom = 10.dp),
                )
                SignalBadge(state.signal)
                Text(
                    state.reason,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontSize = 12.5.sp,
                    modifier = Modifier.padding(top = 9.dp),
                )
            }
        }

        state.error?.let { message ->
            item {
                Card { Text("Erreur : $message", color = Red, fontSize = 12.5.sp) }
            }
        }

        item {
            Card {
                Label("Prix et moyennes mobiles")
                PriceChart(
                    state.candles,
                    currency = state.quoteCurrency,
                    modifier = Modifier.padding(top = 10.dp),
                )
                Row(
                    Modifier.fillMaxWidth().padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    LegendItem(Blue, "prix")
                    LegendItem(Green, "courte")
                    LegendItem(Amber, "longue")
                }
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(11.dp)) {
                Card(Modifier.weight(1f)) {
                    Label("Portefeuille")
                    Text(
                        formatMoney(state.portfolioValue, state.quoteCurrency),
                        fontSize = 21.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    val diff = state.portfolioValue - state.initialEur
                    if (state.portfolioValue > 0 && state.initialEur > 0) {
                        Text(
                            formatMoney(diff, state.quoteCurrency) + " (" +
                                formatPercent(diff / state.initialEur * 100) + ")",
                            color = if (diff >= 0) Green else Red,
                            fontSize = 12.sp,
                        )
                        // Dire depuis quand : un écart sans point de départ
                        // explicite se lit comme une performance du bot.
                        Text(
                            "depuis ${state.referenceLabel}",
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            fontSize = 10.5.sp,
                        )
                    }
                }
                Card(Modifier.weight(1f)) {
                    // En réel on affiche les avoirs réellement détenus sur le
                    // compte, pas seulement ce que le bot a acheté lui-même.
                    val held =
                        if (mode == Mode.LIVE) state.baseBalance else state.positionSize
                    val asset = settings.symbol.substringBefore("/")
                    Label(if (mode == Mode.LIVE) "Avoirs en $asset" else "Position")
                    Text(
                        if (held > 0) String.format("%.4f", held) else "—",
                        fontSize = 21.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        state.entryPrice?.let { "entrée à ${formatMoney(it, state.quoteCurrency)}" }
                            ?: "liquide : ${formatMoney(state.cash, state.quoteCurrency)}",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.sp,
                    )
                }
            }
        }

        item {
            Card {
                Label("Contrôles")
                Column(
                    Modifier.padding(top = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Button(
                        onClick = { onStart(Mode.PAPER) },
                        enabled = !running,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Green),
                    ) { Text("Démarrer en simulation", fontWeight = FontWeight.SemiBold) }

                    Button(
                        onClick = { onStart(Mode.LIVE) },
                        enabled = !running && settings.canGoLive && settings.liveEnabled,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = Amber),
                    ) {
                        Text(
                            when {
                                !settings.canGoLive -> "Mode réel (clés manquantes)"
                                !settings.liveEnabled -> "Mode réel (désactivé)"
                                else -> "Démarrer en mode RÉEL"
                            },
                            fontWeight = FontWeight.SemiBold,
                        )
                    }

                    OutlinedButton(
                        onClick = onStop,
                        enabled = running,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text("Arrêter") }
                }
                Note(
                    "Le bot continue de tourner quand l'app est fermée, grâce à la " +
                        "notification permanente. Le mode simulation n'engage aucun argent réel.",
                    Modifier.padding(top = 10.dp),
                )
            }
        }

        item {
            Card {
                Label("Dernières décisions")
                if (log.isEmpty()) {
                    Text(
                        "Aucune pour l'instant. Le bot n'agit que sur un signal, " +
                            "il peut rester des heures sans rien faire — c'est normal.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontSize = 12.5.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                } else {
                    Column(Modifier.padding(top = 8.dp)) {
                        log.take(12).forEach { entry ->
                            Row(
                                Modifier.fillMaxWidth().padding(vertical = 6.dp),
                                verticalAlignment = Alignment.Top,
                            ) {
                                SignalBadge(entry.signal, small = true)
                                Column(Modifier.padding(start = 10.dp).weight(1f)) {
                                    Text(
                                        "${formatTime(entry.time)} · ${formatMoney(entry.price, state.quoteCurrency)}",
                                        fontSize = 12.5.sp,
                                        color = MaterialTheme.colorScheme.onSurface,
                                    )
                                    Text(
                                        entry.reason,
                                        fontSize = 11.5.sp,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun LegendItem(color: Color, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(Modifier.padding(end = 5.dp).size(width = 14.dp, height = 3.dp)) {
            drawRect(color)
        }
        Text(text, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 11.sp)
    }
}
