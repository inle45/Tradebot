package com.tradebot.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Palette : sombre par défaut, comme la plupart des apps de marché, avec un
// vert/rouge lisibles sans être criards.
val Green = Color(0xFF34D17D)
val Red = Color(0xFFF0616D)
val Amber = Color(0xFFE0A33E)
val Blue = Color(0xFF5AA9F5)
val Grey = Color(0xFF8B98AD)

private val DarkColors = darkColorScheme(
    primary = Blue,
    onPrimary = Color(0xFF06121F),
    background = Color(0xFF0B0F16),
    onBackground = Color(0xFFE8EDF5),
    surface = Color(0xFF141A24),
    onSurface = Color(0xFFE8EDF5),
    surfaceVariant = Color(0xFF1B222E),
    onSurfaceVariant = Grey,
    outline = Color(0xFF232C3B),
    error = Red,
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF1B6FC4),
    background = Color(0xFFF7F9FC),
    onBackground = Color(0xFF141A24),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF141A24),
    surfaceVariant = Color(0xFFEDF1F7),
    onSurfaceVariant = Color(0xFF5B6675),
    outline = Color(0xFFD8DFE9),
    error = Color(0xFFC0303B),
)

@Composable
fun TradebotTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        content = content,
    )
}
