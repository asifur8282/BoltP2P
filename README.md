# CrossDrop

<p align="center">
  <img src="CrossDropDemoImg.png" alt="CrossDrop Demo" width="100%" />
</p>

**CrossDrop** is an ultra-lightweight, zero-cloud peer-to-peer (P2P) sync utility operating directly between a Windows 11 PC and an Android 14 (API 34) device on the local network. It's for when you want to get files shared from your pc to phone or vice versa quick and clean! Ok maybe not "quick" for giant files, but clean for sure! No waiting for cloud processing, no popups from unknown third party apps, and no external servers!

---

## 1. Core Philosophy & Invariants

1. **Zero-Cloud / Zero-Relay:** All network traffic terminates strictly across the local Wi-Fi subnet over a direct TCP pipe on port `58241`. No external servers, cloud databases, or third-party relay infrastructure exist.
2. **Zero-Disk Intermediate Footprint:** Neither mobile nor desktop writes `.tmp` files, cache images, or stages media to persistent flash/disk prior to explicit user authorization.
3. **10-Minute Volatile RAM Buffer:** Inbound transfer offers (text payloads or file metadata) reside exclusively in volatile memory. A strict 600-second TTL timer starts on arrival. If unaccepted at $t = 600\text{s}$, the memory reference is zeroed out and purged, the sender is notified of a timeout, and the socket closes cleanly.
4. **Active-Lock Pipeline:** Once the recipient clicks "Accept" or "Download", the TCP socket enters a dedicated transfer lock, streaming 64 KB chunks until transmission finishes and the trailing SHA-256 digest is verified.
5. **Direct-from-Camera Shutter:** CameraX captures raw camera frames directly into an in-memory `ByteBuffer` and streams across the socket without saving photos to mobile storage.

---

## 2. System Architecture & Wire Protocol

```
+---------------------------------------------------------------------------------+
|                                Local Wi-Fi Subnet                               |
|                                                                                 |
|   +--------------------------+                       +----------------------+   |
|   |    Android Client App    | <==== mDNS / NSD ===> |  Windows 11 Daemon   |   |
|   | (Jetpack Compose / Java) |  (_crossdrop._tcp.)   |  (Python 3.14 Async) |   |
|   +--------------------------+                       +----------------------+   |
|                |                                                 |              |
|                +============ Direct TCP Pipe (Port 58241) =======+              |
|                             Custom 18-Byte Binary Framing                       |
+---------------------------------------------------------------------------------+
```

### 18-Byte Big-Endian Frame Header

Every packet transmitted over the socket begins with a fixed 18-byte big-endian header:

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       Magic: "XDRP"                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Msg Type (2B)        |      Meta Length (4B)         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                      Payload Length (8B)                      |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                  JSON Metadata Block (UTF-8)                  |
|                  (Length = Meta Length)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                  Raw Binary Payload Stream                    |
|                  (Length = Payload Length)                    |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### Protocol Message Types

| Value | Identifier | Purpose |
| :--- | :--- | :--- |
| `0x0001` | `PING` / `PONG` | Heartbeat & pipe keep-alive |
| `0x0002` | `OFFER_TEXT` | Push clipboard or text snippet |
| `0x0003` | `OFFER_FILE` | Inbound file or live camera frame offer |
| `0x0004` | `ACCEPT_TRANSFER` | Recipient consent to begin active streaming |
| `0x0005` | `REJECT_TRANSFER` | Recipient declined or 10-minute TTL expired |
| `0x0006` | `DATA_CHUNK` | 64 KB binary stream chunk |
| `0x0007` | `TRANSFER_FIN` | End of stream + trailing SHA-256 digest |
| `0x0008` | `TRANSFER_ACK` | SHA-256 verified; receiver confirms success |

---

## 3. Environment & Prerequisites

- **Host OS:** Windows 11 (x64)
- **Python:** 3.11 or 3.14 (Native 64-bit)
- **Java Runtime:** Eclipse Temurin OpenJDK 21 LTS (`java -version` -> 21)
- **Android SDK:** Configured at `C:\Android`
  - Platform: `android-34`
  - Build-Tools: `34.0.0`
  - Platform-Tools: `adb.exe` v1.0.41+
- **Physical Device:** Android smartphone running Android 8.0+ (API 26 to 34), connected via USB with "USB Debugging" enabled under Developer Options.

### Environment Variables Verification

Ensure the following variables are present in your session:

```powershell
$env:ANDROID_HOME = "C:\Android"
$env:PATH = "C:\Android\platform-tools;C:\Android\cmdline-tools\latest\bin;$env:PATH"
```

---

## 4. Quick Start & Execution Guide

### 4.1 Running the Windows 11 Desktop Daemon

1. Navigate to the desktop directory:
   ```powershell
   cd D:\Crossdrop\crossdrop-desktop
   ```

2. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

3. Launch the daemon:
   ```powershell
   python main.py
   ```
   - The daemon will minimize to the system tray with a geometric status icon.
   - Right-click the tray icon to **"Open CrossDrop"** (bringing up the 460x600 quick window), **"Push Clipboard to Phone"**, or **"Send File..."**.
   - Native Windows 11 actionable notifications will automatically trigger when text or files arrive.

---

### 4.2 Building & Deploying the Android Mobile Client

1. Verify physical phone is connected via ADB:
   ```powershell
   adb devices
   ```
   *(Ensure device shows up as `device`, not `unauthorized`)*

2. Navigate to the android client directory:
   ```powershell
   cd D:\Crossdrop\crossdrop-android
   ```

3. Compile the debug APK using the headless Gradle wrapper:
   ```powershell
   .\gradlew.bat assembleDebug
   ```

4. Install the application onto the connected phone:
   ```powershell
   adb install -r app\build\outputs\apk\debug\app-debug.apk
   ```

5. Launch the client directly via ADB:
   ```powershell
   adb shell am start -n com.crossdrop.client.debug/com.crossdrop.client.MainActivity
   ```

---

### 4.3 Compiling Standalone Windows 11 Executable (`CrossDrop.exe`)

To build the windowless, standalone `.exe`:

1. Navigate to the desktop directory:
   ```powershell
   cd D:\Crossdrop\crossdrop-desktop
   ```

2. Run the packaging script:
   ```powershell
   python build_exe.py
   # Or run: .\build_exe.bat
   ```

3. The standalone binary is produced at:
   ```
   D:\Crossdrop\crossdrop-desktop\dist\CrossDrop.exe
   ```

4. Launch the binary in the background:
   ```powershell
   Start-Process .\dist\CrossDrop.exe
   ```

---

## 5. Mobile Client Usage

- **Camera Direct Shutter:** Tap the shutter button in the center viewfinder. The camera captures the JPEG into a memory `ByteBuffer` and immediately streams it to your PC. A slim 2px progress bar on top tracks transmission.
- **Quick Clipboard Push:** When you copy text anywhere on Android and open CrossDrop, the clipboard snippet is automatically detected. Tap **"Push Clipboard to PC Now"** to instantly dispatch it to Windows.
- **Arbitrary File Transfer:** Tap **"Stream File"** to pick any document, video, or archive and send it to your PC.
- **PC Target:** The app automatically discovers your PC via mDNS (`_crossdrop._tcp.local.`). You can also tap the status pill or **"PC Target"** tile to manually set the PC IP address and port.

---

## 6. Troubleshooting & Diagnostics

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **"Connection refused" or red dot on phone** | Windows Firewall blocking port 58241 | Run in elevated PowerShell: `New-NetFirewallRule -DisplayName "CrossDrop" -Direction Inbound -LocalPort 58241 -Protocol TCP -Action Allow` |
| **mDNS Auto-Discovery fails** | Wi-Fi router AP Isolation enabled | Router blocks multicast between devices. Manually enter PC's IP address (from `ipconfig`) in CrossDrop Mobile Target Settings. |
| **Toast notifications do not show** | Windows Focus Assist / Do Not Disturb | Check Windows 11 Settings > System > Notifications and ensure notifications are enabled for Python/Terminal. |
| **ADB device unauthorized** | Phone screen locked or RSA key unaccepted | Unlock phone screen and tap "Always allow from this computer" on the USB Debugging prompt. |
| **Transfer SHA-256 Mismatch** | Network packet loss or stream truncated | CrossDrop automatically deletes corrupted partial writes on integrity failure. Retry transfer on stable Wi-Fi. |
