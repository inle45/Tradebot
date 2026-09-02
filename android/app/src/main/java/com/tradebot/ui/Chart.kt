package com.tradebot.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradebot.core.Candle
import com.tradebot.core.Indicators

/**
 * Graphique de prix avec ses moyennes mobiles, dessiné directement au Canvas.
 * Pas de librairie de graphiques : moins de poids dans l'APK et un rendu
 * exactement maîtrisé.
 */
@Composable
fun PriceChart(
    candles: List<Candle>,
    shortPeriod: Int = 10,
    longPeriod: Int = 50,
    currency: String = "EUR",
    modifier: Modifier = Modifier,
) {
    if (candles.size < 2) {
        Text(
            "Chargement des données de marché…",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontSize = 13.sp,
            modifier = modifier.padding(vertical = 32.dp),
        )
        return
    }

    val closes = candles.map { it.close }
    val shortLine = closes.indices.map { i ->
        Indicators.sma(closes.subList(0, i + 1), shortPeriod)
    }
    val longLine = closes.indices.map { i ->
        Indicators.sma(closes.subList(0, i + 1), longPeriod)
    }

    val everything = closes + shortLine.filterNotNull() + longLine.filterNotNull()
    val low = everything.min()
    val high = everything.max()

    Column(modifier) {
        Canvas(
            Modifier
                .fillMaxWidth()
                .height(180.dp)
        ) {
            fun x(index: Int) = index * size.width / (candles.size - 1).coerceAtLeast(1)
            fun y(value: Double): Float {
                val span = (high - low).takeIf { it > 0 } ?: 1.0
                return (size.height - (value - low) / span * size.height).toFloat()
            }

            // Aplat sous la courbe de prix, pour donner du corps au graphique
            val area = Path().apply {
                moveTo(x(0), size.height)
                closes.forEachIndexed { i, value -> lineTo(x(i), y(value)) }
                lineTo(x(closes.size - 1), size.height)
                close()
            }
            drawPath(
                area,
                Brush.verticalGradient(
                    listOf(Blue.copy(alpha = 0.28f), Color.Transparent),
                ),
            )

            // Ordre de tracé : les moyennes derrière, le prix par-dessus
            drawSeries(longLine, Amber, 2f, ::x, ::y)
            drawSeries(shortLine, Green, 2f, ::x, ::y)
            drawSeries(closes, Blue, 3f, ::x, ::y)
        }

        Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
            Text(
                formatMoney(low, currency),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 11.sp,
                modifier = Modifier.weight(1f),
            )
            Text(
                formatMoney(high, currency),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 11.sp,
            )
        }
    }
}

/** Trace une série, en sautant les points encore indisponibles (moyennes en
 * cours de chauffe). */
private fun DrawScope.drawSeries(
    values: List<Double?>,
    color: Color,
    width: Float,
    x: (Int) -> Float,
    y: (Double) -> Float,
) {
    val path = Path()
    var started = false
    values.forEachIndexed { i, value ->
        if (value == null) return@forEachIndexed
        if (!started) {
            path.moveTo(x(i), y(value)); started = true
        } else {
            path.lineTo(x(i), y(value))
        }
    }
    if (started) drawPath(path, color, style = Stroke(width = width))
}

/** Courbe de capital d'un backtest, avec la ligne du capital de départ. */
@Composable
fun EquityChart(curve: List<Double>, initial: Double, modifier: Modifier = Modifier) {
    if (curve.size < 2) return
    val low = minOf(curve.min(), initial)
    val high = maxOf(curve.max(), initial)
    val positive = curve.last() >= initial

    Canvas(
        modifier
            .fillMaxWidth()
            .height(120.dp)
    ) {
        fun x(index: Int) = index * size.width / (curve.size - 1)
        fun y(value: Double): Float {
            val span = (high - low).takeIf { it > 0 } ?: 1.0
            return (size.height - (value - low) / span * size.height).toFloat()
        }

        // Repère : le capital de départ. Au-dessus on gagne, en dessous on perd.
        drawLine(
            color = Grey.copy(alpha = 0.5f),
            start = Offset(0f, y(initial)),
            end = Offset(size.width, y(initial)),
            strokeWidth = 1.5f,
            pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f)),
        )

        val color = if (positive) Green else Red
        val path = Path().apply {
            moveTo(x(0), y(curve[0]))
            curve.forEachIndexed { i, value -> lineTo(x(i), y(value)) }
        }
        drawPath(path, color, style = Stroke(width = 3f))
    }
}
