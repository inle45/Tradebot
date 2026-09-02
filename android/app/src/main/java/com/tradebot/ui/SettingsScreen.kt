package com.tradebot.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradebot.core.StrategyRegistry
import com.tradebot.data.Settings

@Composable
fun SettingsScreen(
    settings: Settings,
    onChanged: () -> Unit,
    modifier: Modifier = Modifier,
) {
    var apiKey by remember { mutableStateOf(settings.apiKey) }
    var privateKey by remember { mutableStateOf(settings.privateKeyPem) }
    var symbol by remember { mutableStateOf(settings.symbol) }
    var capital by remember { mutableStateOf(settings.capitalEur.toInt().toString()) }
    var strategy by remember { mutableStateOf(settings.strategyName) }
    var interval by remember { mutableStateOf(settings.intervalMinutes) }
    var live by remember { mutableStateOf(settings.liveEnabled) }
    var confirmLive by remember { mutableStateOf(false) }

    LazyColumn(
        modifier.fillMaxSize().padding(horizontal = 14.dp),
        verticalArrangement = Arrangement.spacedBy(11.dp),
    ) {
        item {
            Card {
                Label("Marché")
                OutlinedTextField(
                    value = symbol,
                    onValueChange = { symbol = it; settings.symbol = it.trim(); onChanged() },
                    label = { Text("Paire") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                OutlinedTextField(
                    value = capital,
                    onValueChange = {
                        capital = it.filter(Char::isDigit)
                        capital.toDoubleOrNull()?.let { v -> settings.capitalEur = v }
                        onChanged()
                    },
                    label = { Text("Capital / plafond (en ${symbol.substringAfter("/", "EUR")})") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
                Note(
                    "Le plafond borne ce que le bot peut engager, y compris en mode réel.",
                    Modifier.padding(top = 6.dp),
                )
            }
        }

        item {
            Card {
                Label("Intervalle des bougies")
                Row(
                    Modifier.fillMaxWidth().padding(top = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    listOf("60" to "1 h", "240" to "4 h", "1440" to "1 jour").forEach { (value, text) ->
                        FilterChip(
                            selected = interval == value,
                            onClick = { interval = value; settings.intervalMinutes = value; onChanged() },
                            label = { Text(text) },
                        )
                    }
                }
            }
        }

        item {
            Card {
                Label("Stratégie")
                Column(Modifier.padding(top = 8.dp)) {
                    StrategyRegistry.tradable().forEach { candidate ->
                        Row(
                            Modifier.fillMaxWidth().padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            FilterChip(
                                selected = strategy == candidate.name,
                                onClick = {
                                    strategy = candidate.name
                                    settings.strategyName = candidate.name
                                    onChanged()
                                },
                                label = { Text(candidate.name) },
                            )
                        }
                        if (strategy == candidate.name) {
                            Note(candidate.description, Modifier.padding(bottom = 6.dp))
                        }
                    }
                }
            }
        }

        item {
            Card {
                Label("Clés Revolut X")
                Note(
                    "Stockées chiffrées sur l'appareil via le Keystore Android. Elles ne " +
                        "sont envoyées qu'à Revolut, et ne quittent jamais le téléphone " +
                        "autrement.",
                    Modifier.padding(top = 6.dp, bottom = 10.dp),
                )
                OutlinedTextField(
                    value = apiKey,
                    onValueChange = { apiKey = it; settings.apiKey = it.trim(); onChanged() },
                    label = { Text("Clé API") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = privateKey,
                    onValueChange = { privateKey = it; settings.privateKeyPem = it.trim(); onChanged() },
                    label = { Text("Clé privée (contenu de private.pem)") },
                    minLines = 3,
                    maxLines = 5,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                )
            }
        }

        item {
            Card {
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            "Autoriser le mode réel",
                            fontSize = 15.sp,
                            fontWeight = FontWeight.SemiBold,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            if (settings.canGoLive) "Engage de l'argent réel"
                            else "Renseigne d'abord tes clés",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Switch(
                        checked = live,
                        enabled = settings.canGoLive,
                        onCheckedChange = { wanted ->
                            if (wanted) confirmLive = true
                            else { live = false; settings.liveEnabled = false; onChanged() }
                        },
                    )
                }
            }
        }

        item {
            Card {
                Label("Portefeuille de simulation")
                Note(
                    "Remet le portefeuille virtuel à son capital de départ et oublie " +
                        "la position en cours.",
                    Modifier.padding(top = 6.dp, bottom = 10.dp),
                )
                OutlinedButton(
                    onClick = { settings.resetPortfolio(); onChanged() },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Réinitialiser la simulation") }
            }
        }

        item {
            Card {
                Label("Ce que dit la mesure")
                Note(
                    "Les stratégies fournies ont été testées sur des données réelles, " +
                        "sur plusieurs paires et plusieurs périodes. Aucune n'a montré " +
                        "d'avantage fiable face au simple fait de garder ses cryptos — " +
                        "et sur les périodes baissières, rester liquide fait mieux que " +
                        "toutes.\n\n" +
                        "L'onglet Stratégies permet de refaire cette mesure quand tu " +
                        "veux, sur les données du moment.",
                    Modifier.padding(top = 8.dp),
                )
            }
        }
    }

    if (confirmLive) {
        AlertDialog(
            onDismissRequest = { confirmLive = false },
            title = { Text("Activer le mode réel ?") },
            text = {
                Text(
                    "Le bot passera de vrais ordres sur ton compte Revolut X, dans la " +
                        "limite du plafond fixé.\n\n" +
                        "Rappel des mesures effectuées : aucune des stratégies de cette " +
                        "app n'a démontré d'avantage face au fait de ne rien faire. " +
                        "Le risque de perte est réel."
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    live = true; settings.liveEnabled = true; confirmLive = false; onChanged()
                }) { Text("J'ai compris, activer") }
            },
            dismissButton = {
                TextButton(onClick = { confirmLive = false }) { Text("Annuler") }
            },
        )
    }
}
