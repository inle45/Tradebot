package com.tradebot.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Ligne du classement des stratégies. */
data class StudyRow(
    val name: String,
    val periods: Int,
    val winRate: Double,
    val meanEdge: Double,
    val ciLow: Double,
    val ciHigh: Double,
    val significant: Boolean,
    val avgReturn: Double,
    val avgHoldReturn: Double,
    val exposurePct: Double,
    val isCashBaseline: Boolean,
)

@Composable
fun StudyScreen(
    rows: List<StudyRow>,
    running: Boolean,
    progress: String,
    onRun: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier.fillMaxSize().padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        item {
            Card {
                Label("Comparer les stratégies")
                Note(
                    "Chaque stratégie est rejouée sur l'historique réel de plusieurs " +
                        "paires, découpé en périodes successives, frais inclus. Le " +
                        "classement se fait sur l'écart face au buy & hold.",
                    Modifier.padding(top = 8.dp, bottom = 12.dp),
                )
                OutlinedButton(
                    onClick = onRun,
                    enabled = !running,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(if (running) "Analyse en cours…" else "Lancer l'analyse") }

                if (running) {
                    Row(
                        Modifier.fillMaxWidth().padding(top = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(Modifier.padding(end = 12.dp), strokeWidth = 2.dp)
                        Text(
                            progress,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            fontSize = 12.5.sp,
                        )
                    }
                }
            }
        }

        if (rows.isNotEmpty()) {
            val cash = rows.firstOrNull { it.isCashBaseline }
            val best = rows.filterNot { it.isCashBaseline }.maxByOrNull { it.meanEdge }
            val cashWins = cash != null && best != null && cash.meanEdge >= best.meanEdge

            item {
                Card {
                    Verdict(
                        positive = !cashWins,
                        title = if (cashWins)
                            "Aucune stratégie ne bat le fait de ne rien faire"
                        else
                            "${best?.name} arrive en tête",
                        subtitle = if (cashWins)
                            "Rester 100% liquide fait mieux que toutes les stratégies testées"
                        else
                            "Écart moyen : ${formatPoints(best?.meanEdge ?: 0.0)} points",
                    )
                    if (cashWins) {
                        Note(
                            "Ce n'est pas un bug. Sur la période testée le marché baisse, " +
                                "et une stratégie souvent hors du marché « bat » " +
                                "mécaniquement le buy & hold sans aucun mérite. La " +
                                "référence « ne rien faire » est là pour démasquer ça.",
                            Modifier.padding(top = 12.dp),
                        )
                    }
                }
            }

            items(rows) { row -> StrategyCard(row) }

            item {
                Card {
                    Label("Comment lire ce classement")
                    Note(
                        "• Écart = ce que la stratégie gagne ou perd par rapport à " +
                            "acheter puis ne rien faire.\n" +
                            "• « Significatif » veut dire que l'intervalle de confiance " +
                            "ne contient pas zéro. Sinon, le résultat ne se distingue " +
                            "pas d'un tirage au sort.\n" +
                            "• Exposition = part du temps réellement investie. Une " +
                            "exposition faible en marché baissier gonfle artificiellement " +
                            "le résultat.\n" +
                            "• Un rendement absolu négatif reste une perte, même si " +
                            "l'écart est positif.",
                        Modifier.padding(top = 8.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun StrategyCard(row: StudyRow) {
    Card {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    row.name,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = if (row.isCashBaseline) Grey else MaterialTheme.colorScheme.onSurface,
                )
                if (row.isCashBaseline) {
                    Text(
                        "référence de contrôle",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Text(
                formatPoints(row.meanEdge),
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
                color = if (row.meanEdge >= 0) Green else Red,
            )
        }

        Column(Modifier.padding(top = 10.dp)) {
            KeyValue("Rendement absolu", formatPercent(row.avgReturn),
                if (row.avgReturn >= 0) Green else Red)
            KeyValue("Buy & hold sur la période", formatPercent(row.avgHoldReturn))
            KeyValue("Exposition au marché", "${row.exposurePct.toInt()}%")
            KeyValue("Périodes gagnées", "${row.winRate.toInt()}% sur ${row.periods}")
            KeyValue(
                "Intervalle de confiance",
                "${formatPoints(row.ciLow)} à ${formatPoints(row.ciHigh)}",
            )
            KeyValue(
                "Verdict",
                if (row.significant) "significatif" else "indistinguable du hasard",
                if (row.significant) Green else Grey,
            )
        }
    }
}
