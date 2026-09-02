package com.tradebot

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.tradebot.core.EngineState
import com.tradebot.core.LogEntry
import com.tradebot.core.Mode
import com.tradebot.core.RevxClient
import com.tradebot.core.TradingEngine
import com.tradebot.data.Settings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.text.NumberFormat
import java.util.Currency
import java.util.Locale

/**
 * Service en avant-plan : la façon propre, sur Android, de faire tourner le bot
 * en continu. Sans lui, le système suspend l'app dès qu'elle passe en arrière-plan
 * et le bot cesse de surveiller le marché.
 */
class BotService : LifecycleService() {

    companion object {
        const val CHANNEL_ID = "tradebot_running"
        const val NOTIFICATION_ID = 1
        const val EXTRA_MODE = "mode"

        private val _state = MutableStateFlow(EngineState())
        val state: StateFlow<EngineState> = _state

        private val _log = MutableStateFlow<List<LogEntry>>(emptyList())
        val log: StateFlow<List<LogEntry>> = _log

        private val _running = MutableStateFlow(false)
        val running: StateFlow<Boolean> = _running

        private val _mode = MutableStateFlow(Mode.PAPER)
        val mode: StateFlow<Mode> = _mode

        fun start(context: Context, mode: Mode) {
            val intent = Intent(context, BotService::class.java)
                .putExtra(EXTRA_MODE, mode.name)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, BotService::class.java))
        }
    }

    /** Montant dans la devise de la paire tradée (EUR, USDC…). */
    private fun money(value: Double, currency: String): String {
        val iso = runCatching { Currency.getInstance(currency) }.getOrNull()
            ?: return String.format(Locale.FRANCE, "%,.2f %s", value, currency)
        return NumberFormat.getCurrencyInstance(Locale.FRANCE)
            .apply { this.currency = iso }
            .format(value)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)

        val selectedMode = intent?.getStringExtra(EXTRA_MODE)
            ?.let { runCatching { Mode.valueOf(it) }.getOrDefault(Mode.PAPER) }
            ?: Mode.PAPER

        createChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Démarrage…"))

        _mode.value = selectedMode
        _running.value = true

        lifecycleScope.launch(Dispatchers.IO) {
            val settings = Settings(applicationContext)
            val client = RevxClient(settings.apiKey, settings.privateKeyPem)
            val engine = TradingEngine(settings, client, selectedMode)

            while (isActive && _running.value) {
                try {
                    val state = engine.step()
                    _state.value = state
                    _log.value = engine.log.toList()
                    notify(
                        "${state.signal} · ${money(state.price, state.quoteCurrency)} · " +
                            money(state.portfolioValue, state.quoteCurrency)
                    )
                } catch (e: Exception) {
                    _state.value = _state.value.copy(error = e.message ?: "Erreur inconnue")
                    notify("Erreur : ${e.message?.take(60)}")
                }
                // Un cycle complet par minute : suffisant pour des bougies de
                // 4h, et respectueux du quota de l'API.
                delay(60_000)
            }
        }

        // Le prix affiché à l'écran se rafraîchit plus souvent que le cycle de
        // décision : juste un ticker public, léger, pour que l'écran Direct
        // se sente vraiment en direct entre deux cycles de trading.
        lifecycleScope.launch(Dispatchers.IO) {
            val settings = Settings(applicationContext)
            val client = RevxClient(settings.apiKey, settings.privateKeyPem)
            while (isActive && _running.value) {
                runCatching { client.price(settings.symbol) }
                    .onSuccess { fresh -> _state.value = _state.value.copy(price = fresh) }
                delay(10_000)
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        _running.value = false
        super.onDestroy()
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            CHANNEL_ID, "Bot en marche", NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "Affiche l'état du bot pendant qu'il tourne" }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val title = if (_mode.value == Mode.LIVE) "Tradebot — MODE RÉEL" else "Tradebot — simulation"
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_sort_by_size)
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun notify(text: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, buildNotification(text))
    }
}
