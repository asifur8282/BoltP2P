"""
BoltP2P Desktop Daemon Entry Point (Windows 11)
Coordinates async network server, mDNS discovery, Windows 11 notifications,
system tray icon, and the 460x600 quick utility window.
"""

import os
import sys

# Ensure boltp2p-desktop root is always on sys.path for relative submodule resolution
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

# 1. Force Windows to recognize DPI awareness before creating the window
if sys.platform == "win32":
    try:
        import ctypes
        # Set Per-Monitor DPI awareness (V2)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            # Fallback for older Windows systems
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

from typing import Optional, List, Union
import asyncio
import json
import logging
import time
import threading
import pyperclip
from tkinter import filedialog, messagebox

from core.network_server import BoltP2PServer
from core.discovery import DiscoveryManager
from ui.notifier import Notifier
from ui.tray_manager import TrayManager
from ui.quick_window import QuickWindow

def get_base_dir() -> str:
    """Return persistent directory where the executable or main script lives."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_bundle_dir() -> str:
    """Return PyInstaller temp extraction directory (_MEIPASS) or script dir."""
    return getattr(sys, "_MEIPASS", get_base_dir())


BASE_DIR = get_base_dir()
BUNDLE_DIR = get_bundle_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "boltp2p.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8")
    ]
)
logger = logging.getLogger("BoltP2P.Main")


def load_config() -> dict:
    default_config = {
        "device_name": "Windows 11 Workstation",
        "port": 58241,
        "save_dir": os.path.join(BASE_DIR, "Downloads"),
        "auto_accept_text": False,
        "paired_devices": []
    }
    # Check if config exists in base dir or bundle dir
    config_source = CONFIG_PATH if os.path.exists(CONFIG_PATH) else os.path.join(BUNDLE_DIR, "config.json")
    if os.path.exists(config_source):
        try:
            with open(config_source, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                default_config.update(loaded)
        except Exception as e:
            logger.warning("Could not read config.json, using defaults: %s", e)
    return default_config


def register_boltp2p_protocol():
    """Register boltp2p:// URI protocol in HKCU registry so Windows never shows store dialog."""
    try:
        import winreg
        exe_path = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
        proto = "boltp2p"
        key_path = rf"Software\Classes\{proto}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"URL:{proto.capitalize()} Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(key, r"shell\open\command") as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')
    except Exception as e:
        logger.debug("Registry protocol registration notice: %s", e)


class BoltP2PApp:
    def __init__(self):
        self.config = load_config()
        self.loop = asyncio.new_event_loop()
        self.async_thread: Optional[threading.Thread] = None
        self.last_known_peer = {"name": "Android Device", "ip": "127.0.0.1", "port": 58242}

        register_boltp2p_protocol()

        # 1. Notifier
        self.notifier = Notifier(
            on_accept=self.handle_accept_transfer,
            on_reject=self.handle_reject_transfer,
            on_copy=self.handle_consume_text,
            on_open_window=self.open_window
        )

        # 2. Server
        self.server = BoltP2PServer(
            host="0.0.0.0",
            port=self.config["port"],
            save_dir=self.config["save_dir"],
            auto_accept_text=self.config.get("auto_accept_text", False),
            on_notify=self.handle_server_notify,
            on_transfer_progress=self.handle_transfer_progress,
            on_transfer_complete=self.handle_transfer_complete,
            on_connection_change=self.handle_connection_change
        )

        # 3. Discovery
        self.discovery = DiscoveryManager(
            device_name=self.config["device_name"],
            port=self.config["port"],
            on_peer_found=self.handle_peer_discovered
        )

        # 4. Quick UI Window
        self.window = QuickWindow(
            server=self.server,
            discovery=self.discovery,
            on_send_text=self.send_text_to_peer,
            on_send_file=self.send_file_to_peer,
            on_send_files=self.send_files_to_peer,
            on_connect_peer=self.connect_to_peer
        )

        # 5. Tray Manager
        self.tray = TrayManager(
            on_open_window=self.open_window,
            on_push_clipboard=self.push_clipboard,
            on_send_file=self.prompt_send_file,
            on_open_folder=self.open_downloads_folder,
            on_exit=self.shutdown
        )

    def start(self) -> None:
        """Start async server and mDNS discovery, then run tray icon."""
        logger.info("Initializing BoltP2P Desktop Daemon...")

        def run_async():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.server.start())
            self.discovery.start()
            self.loop.run_forever()

        self.async_thread = threading.Thread(target=run_async, daemon=True)
        self.async_thread.start()

        # Start tray in detached background thread
        logger.info("Starting System Tray daemon...")
        self.tray.start()

        # Launch GUI window on main thread so user sees the application immediately
        logger.info("Launching BoltP2P Quick Window...")
        try:
            self.window.show()
        except (KeyboardInterrupt, SystemExit):
            self.shutdown()

    def open_window(self) -> None:
        self.window.show_or_restore()

    def handle_peer_discovered(self, name: str, ip: str, port: int) -> None:
        logger.info("Discovered peer: %s (%s:%d)", name, ip, port)
        self.last_known_peer = {"name": name, "ip": ip, "port": 58242}
        self.window.update_peer_status(name, ip, 58242, connected=True)
        self.tray.set_state("connected")

    def handle_connection_change(self, client_id: str, connected: bool) -> None:
        if connected:
            self.tray.set_state("connected")
            ip = client_id.split(":")[0]
            self.last_known_peer = {"name": "Android Client", "ip": ip, "port": 58242}
            self.window.update_peer_status("Android Client", ip, 58242, connected=True)
        else:
            if not self.server.active_clients:
                self.last_known_peer = {"name": "", "ip": "", "port": 58242}
                self.tray.set_state("listening")
                self.window.update_peer_status("Listening for Mobile...", "", 0, connected=False)

    def handle_server_notify(self, transfer_id: str, offer_type: str, details: str, meta: dict) -> None:
        if offer_type == "TEXT":
            self.notifier.notify_text(transfer_id, details)
        else:
            self.notifier.notify_file(transfer_id, details)
        self.window.trigger_offers_refresh()

    def handle_transfer_progress(self, transfer_id: str, received: int, total: int) -> None:
        self.tray.set_state("streaming")
        self.window.update_progress(transfer_id, received, total)

    def handle_transfer_complete(self, transfer_id: str, path: str, success: bool) -> None:
        self.tray.set_state("connected" if self.server.active_clients else "listening")
        self.window.trigger_offers_refresh()
        if success:
            filename = os.path.basename(path)
            self.notifier.notify_info("BoltP2P: Transfer Complete", f"Saved: {filename}")
        else:
            self.notifier.notify_info("BoltP2P: Transfer Failed", "Integrity check failed or cancelled.")

    def handle_accept_transfer(self, transfer_id: str) -> None:
        self.server.accept_transfer(transfer_id)
        self.window.trigger_offers_refresh()

    def handle_reject_transfer(self, transfer_id: str) -> None:
        self.server.reject_transfer(transfer_id)
        self.window.trigger_offers_refresh()

    def handle_consume_text(self, transfer_id: str) -> None:
        self.server.consume_text(transfer_id)
        self.window.trigger_offers_refresh()

    def push_clipboard(self) -> None:
        try:
            content = pyperclip.paste()
            if content:
                self.send_text_to_peer(content)
        except Exception as e:
            logger.error("Failed to read clipboard: %s", e)

    def prompt_send_file(self) -> None:
        self.open_window()

    def send_text_to_peer(self, text: str) -> None:
        def _worker():
            if not self.server.active_clients:
                self.notifier.notify_info("BoltP2P", "No device connected. Please pair or connect your phone first.")
                return

            ip = list(self.server.active_clients.keys())[0].split(":")[0]
            self.last_known_peer = {"name": "Android Client", "ip": ip, "port": 58242}
            port = 58242
            logger.info("Pushing text to mobile peer %s:%d", ip, port)
            future = asyncio.run_coroutine_threadsafe(
                self.server.push_text_to_peer(ip, port, text),
                self.loop
            )
            try:
                success = future.result(timeout=10.0)
                if success:
                    self.notifier.notify_info("BoltP2P", "Text pushed to mobile peer.")
                else:
                    self.notifier.notify_info("BoltP2P", "Failed to push text to mobile peer.")
            except Exception as e:
                logger.error("Error pushing text: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    def send_file_to_peer(self, filepath: str) -> None:
        self.send_files_to_peer([filepath])

    def send_files_to_peer(self, filepaths: Union[str, List[str]]) -> None:
        if isinstance(filepaths, str):
            filepaths = [filepaths]
        if not filepaths:
            return

        def _worker():
            try:
                if not self.server.active_clients:
                    self.notifier.notify_info("BoltP2P", "No device connected. Please pair or connect your phone first.")
                    return

                ip = list(self.server.active_clients.keys())[0].split(":")[0]
                self.last_known_peer = {"name": "Android Client", "ip": ip, "port": 58242}
                port = 58242
                total_files = len(filepaths)
                success_count = 0

                for idx, filepath in enumerate(filepaths, 1):
                    if not os.path.exists(filepath):
                        continue
                    transfer_id = f"out_{int(time.time()*1000)}_{idx}"
                    fname = os.path.basename(filepath)
                    fsize = os.path.getsize(filepath)
                    display_name = f"[{idx}/{total_files}] {fname}" if total_files > 1 else fname
                    logger.info("Streaming file %d/%d to mobile peer %s:%d: %s (%d bytes)", idx, total_files, ip, port, fname, fsize)

                    # Show outgoing progress bar in QuickWindow
                    self.window.start_outgoing_transfer(transfer_id, display_name, fsize)

                    def on_progress(sent: int, total: int):
                        self.tray.set_state("streaming")
                        self.window.update_outgoing_progress(transfer_id, sent, total)

                    future = asyncio.run_coroutine_threadsafe(
                        self.server.push_file_to_peer(ip, port, filepath, on_progress=on_progress),
                        self.loop
                    )
                    success = future.result(timeout=600.0)
                    self.tray.set_state("connected" if self.server.active_clients else "listening")
                    self.window.complete_outgoing_transfer(transfer_id, display_name, success)
                    if success:
                        success_count += 1
                    else:
                        self.notifier.notify_info("BoltP2P", f"Transfer declined or interrupted for {fname}.")
                        break

                    time.sleep(0.15)  # brief socket settle delay between sequential files

                if total_files > 1:
                    if success_count == total_files:
                        self.notifier.notify_info("BoltP2P", f"All {total_files} files streamed successfully.")
                    else:
                        self.notifier.notify_info("BoltP2P", f"Streamed {success_count} of {total_files} files.")
                elif success_count == 1:
                    self.notifier.notify_info("BoltP2P", f"File streamed successfully: {os.path.basename(filepaths[0])}")

            except Exception as e:
                logger.error("Error streaming file: %s", e, exc_info=True)
                self.tray.set_state("connected" if self.server.active_clients else "listening")
                self.window.complete_outgoing_transfer(f"err_{int(time.time())}", "Batch Transfer", False, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def connect_to_peer(self, host: str, port: int) -> None:
        """Connect or set target peer manually from UI dialog."""
        logger.info("Setting target peer manually to %s:%d", host, port)
        self.last_known_peer = {"name": f"Peer ({host})", "ip": host, "port": port}
        self.window.update_peer_status(f"Peer ({host})", host, port, connected=True)
        self.tray.set_state("connected")
        self.notifier.notify_info("BoltP2P", f"Target peer set to {host}:{port}")

    def open_downloads_folder(self) -> None:
        os.startfile(self.server.save_dir)

    def shutdown(self) -> None:
        logger.info("Shutting down BoltP2P Desktop...")
        self.window.running = False
        if self.window.root:
            try:
                self.window.root.after(0, self.window.root.destroy)
            except Exception:
                pass
        self.discovery.stop()
        if self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.server.stop(), self.loop)
            self.loop.call_soon_threadsafe(self.loop.stop())
        os._exit(0)


if __name__ == "__main__":
    try:
        app = BoltP2PApp()
        app.start()
    except Exception as exc:
        logger.exception("Fatal startup exception: %s", exc)
        sys.exit(1)
