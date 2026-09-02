package com.tradebot.ui

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val euroFormat = java.text.NumberFormat.getCurrencyInstance(Locale.FRANCE)
private val timeFormat = SimpleDateFormat("HH:mm", Locale.FRANCE)

fun formatEuro(value: Double): String = euroFormat.format(value)

fun formatPercent(value: Double): String =
    (if (value >= 0) "+" else "") + String.format(Locale.FRANCE, "%.2f%%", value)

fun formatPoints(value: Double): String =
    (if (value >= 0) "+" else "") + String.format(Locale.FRANCE, "%.1f", value)

fun formatTime(epochMs: Long): String = timeFormat.format(Date(epochMs))
