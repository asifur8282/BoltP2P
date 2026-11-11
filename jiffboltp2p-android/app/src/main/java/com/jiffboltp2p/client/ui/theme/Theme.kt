package com.jiffboltp2p.client.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val DarkColorScheme = darkColorScheme(
    primary = BrandAccent,
    secondary = BorderSubtle,
    background = CarbonBase,
    surface = CarbonSurface,
    onPrimary = TextPrimary,
    onSecondary = TextSecondary,
    onBackground = TextPrimary,
    onSurface = TextPrimary
)

@Composable
fun JiffBoltP2PTheme(
    content: @Composable () -> Unit
) {
    val colorScheme = DarkColorScheme
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = CarbonBase.toArgb()
            window.navigationBarColor = CarbonBase.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
            WindowCompat.getInsetsController(window, view).isAppearanceLightNavigationBars = false
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = JiffBoltP2PTypography,
        content = content
    )
}
