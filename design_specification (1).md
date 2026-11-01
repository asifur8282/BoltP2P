# CrossDrop UI/UX Design System Specification
**Document:** `design.md`  
**Target:** Desktop (Windows 11) & Mobile (Android 14 / Compose)  
**Tone & Persona:** Utilitarian, tactile, engineered, quiet utility

---

## 1. Aesthetic Thesis & Design Standard

### 1.1 What to Avoid (Design Pitfalls)
- **No decorative frosted glass / heavy blur overkill:** Excessive `backdrop-blur-3xl` layered everywhere with noisy shadows.
- **No novelty neon/mesh radial gradients:** No purple-to-cyan or pink-to-orange glow cards that serve no informational hierarchy.
- **No hyperactive physics animations:** Spring bobs, bouncy layout shifts, or pulsing glow borders around static buttons.
- **No pill-shaped everything:** Do not treat every single element like a floating bubblegum pill.

### 1.2 What to Build (Engineered Functional Elegance)
- **High-contrast, deliberate layout hierarchy:** Clear, legible data tables, explicit boundary dividers, and visible border lines (`1px solid`).
- **Tactile feedback:** Mechanical press states, subtle crisp borders, and instantaneous response instead of 400ms easing delays.
- **Native platform citizenship:**
  - **Desktop:** Adheres to Windows 11 Fluent design principles (native caption controls, discreet mica/neutral matte surface, 1px border frames, standard titlebar actions).
  - **Android:** Follows clean Material You / Modern Scandinavian utility (sharp functional cards, predictable bottom sheets, prominent single-tap camera controls).

---

## 2. Typography Specification

### 2.1 Desktop Typography (Windows 11)
- **Primary Typeface:** **Google Sans** (Fallback stack: `Google Sans`, `Segoe UI Variable Text`, `Segoe UI`, `-apple-system`, `sans-serif`)
- **Type Scale:**
  - **Window Title / App Name:** 12pt (16px) / Medium (500) / Tracking: `0.01em`
  - **Headline / Section Header:** 15pt (20px) / SemiBold (600) / Tracking: `-0.01em`
  - **Body / Primary Text:** 10.5pt (14px) / Regular (400) / Line-height: 1.45
  - **Metadata / File Sizes / Timers / IP:** 9.5pt (12.5px) / Monospace variant or Medium (500) / Tabular figures enabled (`tnum`)
  - **Status Badges / Action Caps:** 8.5pt (11px) / SemiBold (600) / Tracking: `0.05em` (Uppercase)

### 2.2 Mobile Typography (Android 14 Jetpack Compose)
- **Primary Typeface:** **Montserrat** or **Google Sans** (Configured as primary font family in `Type.kt`)
  - *Recommendation:* Google Sans for display & headings; Montserrat for clean, geometric UI controls and numeric readouts.
- **Type Scale:**
  - **Display / Top Bar:** `headlineSmall` (22sp) / SemiBold (600)
  - **Section Titles:** `titleMedium` (16sp) / Medium (500)
  - **Primary Body (Transferred Text Preview):** `bodyLarge` (15sp) / Regular (400) / Line-height: 22sp
  - **System Labels / Meta / Badges:** `labelMedium` (12sp) / SemiBold (600)
  - **TTL Countdown Clock:** `labelSmall` (11sp) / Monospace / Bold (700) (Strictly tabular digits for non-jitter countdowns)

---

## 3. Color Palette & Surfaces (High-Utility Neutral)

A monochromatic, content-first base with a surgical signal color for status and data pipelines.

### 3.1 Dark Mode (Primary Palette)
*Both desktop daemon and mobile client default to a cohesive neutral-slate dark theme.*

| Role | Token Name | Hex Value | Purpose |
| :--- | :--- | :--- | :--- |
| **Canvas / Base Surface** | `surface-0` | `#0E1116` | Main background; deep carbon, non-pure black. |
| **Card / Panel Surface** | `surface-1` | `#161B22` | Cards, active transfer rows, input containers. |
| **Elevated Surface** | `surface-2` | `#21262D` | Dialogs, hover states, dropdown menus. |
| **Borders & Dividers** | `border-subtle` | `#30363D` | 1px clean crisp boundaries (replaces blurry drop shadows). |
| **Text: Primary** | `text-primary` | `#F0F6FC` | Headings, transferred text snippets, file labels. |
| **Text: Secondary** | `text-secondary` | `#8B949E` | Timers, file sizes, peer status descriptions. |
| **Primary Accent** | `accent-brand` | `#2F81F7` | Focused inputs, verified connection indicator, transfer buttons. |
| **Success / Pipe Active** | `signal-success`| `#238636` | Active streaming indicator, file hash verified. |
| **Warning / TTL Expiring**| `signal-warning`| `#D29922` | 10-minute timeout ticker under 60 seconds. |
| **Danger / Cancel** | `signal-danger` | `#DA3633` | Reject button, disconnected status, abort action. |

### 3.2 Light Mode (Workstation Mode)
| Role | Token Name | Hex Value |
| :--- | :--- | :--- |
| **Canvas / Base Surface** | `surface-0` | `#F6F8FA` |
| **Card / Panel Surface** | `surface-1` | `#FFFFFF` |
| **Borders & Dividers** | `border-subtle` | `#D0D7DE` |
| **Text: Primary** | `text-primary` | `#1F2328` |
| **Text: Secondary** | `text-secondary` | `#656D76` |
| **Primary Accent** | `accent-brand` | `#0969DA` |

---

## 4. Desktop Interface Layout (Windows 11)

### 4.1 Window Blueprint (Compact Utility Window: `460px × 600px`)
The desktop client is not an expansive website wrapped in an electron frame. It behaves like a native, precision tool (e.g., Process Hacker, PuTTY, or Obsidian's settings drawer).

```
+-------------------------------------------------------------+
| CrossDrop [Desktop Daemon]             [ - ] [ # ] [ X ]    |  <- 32px Native Titlebar
+-------------------------------------------------------------+
| [● ONLINE] Connected to: Pixel 8 Pro (192.168.1.42)         |  <- 36px Status Header
+-------------------------------------------------------------+
| QUICK SEND                                                  |
| +---------------------------------------------------------+ |
| | [ Paste or type text to push to phone...              ] | |  <- Monospace/Sans input
| +---------------------------------------------------------+ |
| [ Push Clipboard ]               [ Select & Stream File ]   |  <- Crisp 1px bordered btns
+-------------------------------------------------------------+
| ACTIVE / RECENT TRANSFERS (10m Ephemeral RAM Window)        |
| +---------------------------------------------------------+ |
| | 📷 IMG_20261101_0341.jpg (3.2 MB)                       | |
| | From: Phone  •  Expires in: 08:42                       | |
| | [ Accept & Save ]                      [ Reject ]       | |  <- Direct action row
| +---------------------------------------------------------+ |
| | 📋 "https://github.com/torvalds/linux"                  | |
| | Text  •  Expires in: 04:19                              | |
| | [ Copy to Clipboard ]                  [ Dismiss ]      | |
| +---------------------------------------------------------+ |
+-------------------------------------------------------------+
| [Settings] [Show Pairing QR]           Auto-Accept Text [x] |  <- Bottom status bar
+-------------------------------------------------------------+
```

### 4.2 Interactive Components & State Behaviors
- **Action Buttons:** Flat surfaces with explicit `1px solid #30363D` borders. On hover: surface brightness shifts +5%. On click: instant `-1px` translate down or border darkening (mechanical feel).
- **TTL Countdown Display:** Displayed as `mm:ss` in a fixed-width monospace font (`Google Sans` tabular or native `Consolas`). Color stays `text-secondary` until `< 60s`, where it turns `signal-warning`.
- **System Tray Icon:**
  - Dim outline: Offline/Listening.
  - Solid blue dot: Paired and idle keep-alive maintained.
  - Active clockwise rotating segment: Data actively streaming across the pipe.

---

## 5. Mobile Interface Layout (Android 14 / Jetpack Compose)

### 5.1 Screen Hierarchy (Single Screen with Bottom Sheet Drawers)

```
+-----------------------------------+
| CrossDrop              [● PC Paired] |  <- App Bar with live socket dot
+-----------------------------------+
|                                   |
|   +---------------------------+   |
|   |                           |   |
|   |     CAMERA VIEWFINDER     |   |  <- Direct viewfinder preview
|   |     (Tap Shutter to Send) |   |     (CameraX minimal footprint)
|   |                           |   |
|   +---------------------------+   |
|                ( O )              |  <- Large mechanical shutter button
|                                   |
+-----------------------------------+
| QUICK CLIPBOARD PUSH              |
| +-------------------------------+ |
| | Detected in Clipboard:        | |  <- Automatically detects clipboard
| | "Meeting Room 402 Code: 9912" | |
| +-------------------------------+ |
| [ Push Clipboard to PC Now ]      |  <- Full-width primary button
+-----------------------------------+
| [ File Transfer ] [ Scan Desktop ]|  <- Secondary action tiles
+-----------------------------------+
```

### 5.2 Micro-Interactions (Purposeful Only)
1. **Camera Tap-and-Send:**
   - Shutter button has a concentric double ring (`border: 3px`).
   - Tapping provides an immediate single haptic click (`HapticFeedbackType.TextHandleMove`).
   - A slim, 2px linear progress bar emerges at the very top edge of the viewfinder to track outbound stream progress—no full-screen blocking modals.
2. **Clipboard Auto-Detection:**
   - When the user switches to the app, the interface inspects the clipboard. If non-empty, a preview chip appears with a **"Push to Desktop"** button, reducing the action to one tap.
3. **Pending Incoming Notifications:**
   - Standard Android Heads-Up Notification (Notification Channel: `Transfers`, Priority: `HIGH`).
   - Notification Actions: `[ Accept ]` and `[ Reject ]`. No need to keep the app in foreground.

---

## 6. Implementation Tokens for Codebases

### 6.1 Jetpack Compose Color & Style Theme (`ui/theme/Theme.kt`)
```kotlin
package com.crossdrop.client.ui.theme

import androidx.compose.material3.*
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Functional Palette (Engineered Dark)
val CarbonBase = Color(0xFF0E1116)
val CarbonSurface = Color(0xFF161B22)
val CarbonElevated = Color(0xFF21262D)
val BorderSubtle = Color(0xFF30363D)
val TextPrimary = Color(0xFFF0F6FC)
val TextSecondary = Color(0xFF8B949E)
val BrandAccent = Color(0xFF2F81F7)
val SignalSuccess = Color(0xFF238636)
val SignalWarning = Color(0xFFD29922)

// Typography Config (Google Sans or Montserrat)
val AppFontFamily = FontFamily.Default // Replaced with Font(R.font.googlesans_regular)

val CrossDropTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = AppFontFamily,
        fontWeight = FontWeight.SemiBold,
        fontSize = 20.sp,
        color = TextPrimary
    ),
    bodyLarge = TextStyle(
        fontFamily = AppFontFamily,
        fontWeight = FontWeight.Normal,
        fontSize = 15.sp,
        color = TextPrimary
    ),
    labelMedium = TextStyle(
        fontFamily = AppFontFamily,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        color = TextSecondary
    )
)
```

### 6.2 Desktop GUI Style Specification (`ui/tray_manager.py` / Tk / PyQt CSS)
```css
/* Minimalist, Clean Desktop Theme */
QMainWindow, QDialog {
    background-color: #0E1116;
    color: #F0F6FC;
    font-family: "Google Sans", "Segoe UI Variable Text", sans-serif;
}

QFrame.Card {
    background-color: #161B22;
    border: 1px solid #30363D;
    border-radius: 6px;
    padding: 10px;
}

QPushButton {
    background-color: #21262D;
    color: #F0F6FC;
    border: 1px solid #30363D;
    border-radius: 4px;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #30363D;
    border-color: #8B949E;
}

QPushButton:pressed {
    background-color: #161B22;
}

QPushButton.Primary {
    background-color: #2F81F7;
    border: 1px solid #2F81F7;
    color: #FFFFFF;
}

QPushButton.Primary:hover {
    background-color: #388BFD;
}

QLabel.Timer {
    font-family: "Consolas", monospace;
    font-size: 12px;
    color: #8B949E;
}
```

---

## 7. Review Checklist: Design Verification

- [x] **No gratuitous glassmorphism:** Surfaces are solid `#0E1116` / `#161B22` with clear borders instead of noisy blurs.
- [x] **Information-dense hierarchy:** Every element on screen communicates either device connectivity, incoming payload size, or remaining TTL.
- [x] **Mechanical feedback:** Fast, sharp state transitions without sluggish floating animations.
- [x] **Zero clutter camera view:** Mobile camera interface shows strictly the viewfinder, a shutter button, and a minimal transmission rail.