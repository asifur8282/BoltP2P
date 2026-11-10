# Software Requirements Specification (SRS)
## Project: BoltP2P (Ultra-Lightweight P2P Cross-Device Sync)
**Version:** 1.0  
**Target Environment:** Windows 11 & Android 14 (API 34)  
**Development Toolchain:** Android CLI + JDK 21 / Python 3.11+  

---

## 1. Introduction

### 1.1 Purpose
This document specifies the software requirements for **BoltP2P**, a zero-cloud, peer-to-peer (P2P) local synchronization utility operating directly between an Android smartphone and a Windows 11 PC on the same Local Area Network (LAN). The solution addresses the need for instantaneous file, image, and text transfer without intermediate transit platforms (WhatsApp, email, cloud drives).

### 1.2 Scope
BoltP2P provides:
- One-time initial device pairing via QR code or numeric PIN.
- Persistent LAN device discovery and connection maintenance without repeated pairing steps.
- Direct-from-camera photo capture and transfer with zero device-side intermediate caching.
- Bi-directional text and clipboard dispatch with native OS toast alerts and one-tap copy actions.
- Arbitrary binary file transfer featuring pre-transfer consent, in-memory ephemeral hold windows, and active-stream locking.

### 1.3 Definitions, Acronyms, and Abbreviations
- **P2P:** Peer-to-Peer
- **LAN:** Local Area Network
- **mDNS / NSD:** Multicast Domain Name System / Network Service Discovery
- **TTL:** Time-To-Live
- **E2EE:** End-to-End Encryption
- **PSK:** Pre-Shared Key
- **RAM:** Random Access Memory

---

## 2. Overall Description

### 2.1 Product Perspective
BoltP2P operates as a lightweight distributed application composed of two endpoints:
1. **Desktop Daemon:** A low-overhead Python background process (system tray + native notification hooks) on Windows 11.
2. **Mobile Client:** A lean Kotlin application built with Jetpack Compose using the modern Android CLI and target platform API 34.

### 2.2 User Characteristics
The user requires fast, ad-hoc, and private cross-device data movement across their workstation and mobile device, operating under strict storage and resource constraints.

### 2.3 General Constraints
- **Zero Cloud / Zero Relays:** All communication must terminate solely on the local network.
- **Development Footprint Constraint:** Total toolchain and IDE overhead must remain under 1.5 GB. No heavyweight IDE installations (e.g., standard 15 GB+ Android Studio) are utilized.
- **Runtime Footprint Constraint:** Desktop daemon idle RAM < 40 MB; Android APK size < 15 MB.

---

## 3. Specific Requirements

### 3.1 Functional Requirements (FR)

| ID | Description | Priority |
| :--- | :--- | :--- |
| **FR-01** | **One-Time Pairing:** Mobile client must securely pair with the PC by scanning a desktop-generated QR code or entering a 6-digit PIN. Pairing keys must persist across device reboots. | High |
| **FR-02** | **LAN Device Auto-Discovery:** Paired devices must automatically detect each other upon connecting to the same Wi-Fi network via mDNS without manual IP entry. | High |
| **FR-03** | **Persistent Pipe & Keep-Alive:** The transport pipe must maintain an authenticated, idle state to enable immediate transfers without renegotiation overhead. | High |
| **FR-04** | **Instant Camera Transfer:** Mobile app must feature a one-tap camera shutter that immediately sends the captured frame to the PC without writing an image file to mobile flash storage. | High |
| **FR-05** | **Bidirectional Text/Clipboard Push:** Pasting or typing text on either device must instantly push to the peer, triggering an OS toast notification with a direct "Copy to Clipboard" action. Inbound text offers are retained in the 10-minute RAM buffer with a dynamic "Copy Again" state until dismissed or timed out. | High |
| **FR-06** | **Arbitrary File Transfer:** Both endpoints must support selecting and streaming binary files of arbitrary size with transfer progress indicators. | High |
| **FR-07** | **Interactive Recipient Approval:** Inbound file and image transfers must prompt the recipient for approval before binary data is written to disk. | High |
| **FR-08** | **Active Pipeline Hold-Open:** Once the receiver clicks "Accept" or "Download", the underlying network socket must remain held open in an active transfer lock until transmission and SHA-256 integrity verification are completed. | High |
| **FR-09** | **Universal Desktop Input & Staging:** Desktop client must support native Win32 drag-and-drop file ingestion, clipboard image pasting (`Ctrl+V`) with live thumbnails, document badges with double-click launch, and manual transmission trigger via "Send to Connected Device". | High |

---

### 3.2 Non-Functional Requirements (NFR)

#### 3.2.1 Data Ephemerality & Zero Retention
- **NFR-01 (Zero Disk Caching):** Neither endpoint shall write incoming stream bytes to temporary files (`.tmp`), disk caches, or intermediate flash blocks prior to user confirmation.
- **NFR-02 (10-Minute Volatile RAM Window):** Incoming offers (text payloads or file metadata) reside strictly in volatile RAM. A 600-second (10-minute) TTL timer starts upon receipt. If the user does not accept or copy within 10 minutes:
  - The RAM reference is purged and zeroed out.
  - The peer receives a transfer timeout notification.
  - The pending transfer session terminates cleanly.

#### 3.2.2 Security & Integrity
- **NFR-03 (Encrypted Wire Protocol):** All traffic across the LAN must be encrypted using TLS 1.3 with certificates or PSK exchanged during initial QR pairing.
- **NFR-04 (Integrity Verification):** Every completed payload transfer must validate a trailing SHA-256 digest against the stream checksum calculated on the fly. Mismatched transfers are discarded immediately.

#### 3.2.3 Performance & Resource Constraints
- **NFR-05 (Low Memory Footprint):** The Windows desktop process must consume under 40 MB of RAM while idling in the system tray.
- **NFR-06 (Mobile Storage Footprint):** Compiled Android APK release build must not exceed 15 MB in size.
- **NFR-07 (Per-Monitor High-DPI Fidelity):** Desktop application must register Windows Per-Monitor DPI awareness (V2) prior to window initialization to guarantee razor-sharp text, mechanical borders, and proper scaling on high-resolution displays.