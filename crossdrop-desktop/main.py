"""
CrossDrop Desktop Daemon Entry Point (Windows 11)
Coordinates async network server, mDNS discovery, Windows 11 notifications,
system tray icon, and the 460x600 quick utility window.
"""

from typing import Optional
import asyncio
import json
import logging
import os
import sys
import threading
import pyperclip
from tkinter import filedialog, messagebox

from core.network_server import CrossDropServer
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
LOG_PATH = os.path.join(BASE_DIR, "crossdrop.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_PATH, encoding="utf-8")
    ]
)
logger = logging.getLogger("CrossDrop.Main")


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


def register_crossdrop_protocol():
    """Register crossdrop:// URI protocol in HKCU registry so Windows never shows store dialog."""
    try:
        import winreg
        exe_path = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else sys.argv[0])
        key_path = r"Software\Classes\crossdrop"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:CrossDrop Protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(key, r"shell\open\command") as cmd_key:
                winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')
    except Exception as e:
        logger.debug("Registry protocol registration notice: %s", e)


class CrossDropApp:
    def __init__(self):
        self.config = load_config()
        self.loop = asyncio.new_event_loop()
        self.async_thread: Optional[threading.Thread] = None
        self.last_known_peer = {"name": "Android Device", "ip": "127.0.0.1", "port": 58242}

        register_crossdrop_protocol()

        # 1. Notifier
        self.notifier = Notifier(
            on_accept=self.handle_accept_transfer,
            on_reject=self.handle_reject_transfer,
            on_copy=self.handle_consume_text,
            on_open_window=self.open_window
        )

        # 2. Server
        self.server = CrossDropServer(
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
            on_send_file=self.send_file_to_peer
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
        logger.info("Initializing CrossDrop Desktop Daemon...")

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
        logger.info("Launching CrossDrop Quick Window...")
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

    def handle_transfer_complete(self, transfer_id: str, path: str, success: bool) -> None:
        self.tray.set_state("connected" if self.server.active_clients else "listening")
        self.window.trigger_offers_refresh()
        if success:
            filename = os.path.basename(path)
            self.notifier.notify_info("CrossDrop: Transfer Complete", f"Saved: {filename}")
        else:
            self.notifier.notify_info("CrossDrop: Transfer Failed", "Integrity check failed or cancelled.")

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
            # Dynamically resolve active phone IP if connected
            ip = self.last_known_peer["ip"]
            if self.server.active_clients:
                ip = list(self.server.active_clients.keys())[0].split(":")[0]
                self.last_known_peer["ip"] = ip

            if not ip or ip in ("127.0.0.1", "0.0.0.0"):
                self.notifier.notify_info("CrossDrop", "No Android peer connected yet. Open CrossDrop on your phone.")
                return

            port = 58242
            logger.info("Pushing text to mobile peer %s:%d", ip, port)
            future = asyncio.run_coroutine_threadsafe(
                self.server.push_text_to_peer(ip, port, text),
                self.loop
            )
            try:
                success = future.result(timeout=10.0)
                if success:
                    self.notifier.notify_info("CrossDrop", "Text pushed to mobile peer.")
                else:
                    self.notifier.notify_info("CrossDrop", "Failed to push text to mobile peer.")
            except Exception as e:
                logger.error("Error pushing text: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    def send_file_to_peer(self, filepath: str) -> None:
        def _worker():
            ip = self.last_known_peer["ip"]
            if self.server.active_clients:
                ip = list(self.server.active_clients.keys())[0].split(":")[0]
                self.last_known_peer["ip"] = ip

            if not ip or ip in ("127.0.0.1", "0.0.0.0"):
                self.notifier.notify_info("CrossDrop", "No Android peer connected yet. Open CrossDrop on your phone.")
                return

            port = 58242
            logger.info("Streaming file to mobile peer %s:%d: %s", ip, port, filepath)
            future = asyncio.run_coroutine_threadsafe(
                self.server.push_file_to_peer(ip, port, filepath),
                self.loop
            )
            try:
                success = future.result(timeout=600.0)
                if success:
                    self.notifier.notify_info("CrossDrop", f"File streamed successfully: {os.path.basename(filepath)}")
                else:
                    self.notifier.notify_info("CrossDrop", "Transfer declined or interrupted.")
            except Exception as e:
                logger.error("Error streaming file: %s", e)

        threading.Thread(target=_worker, daemon=True).start()

    def open_downloads_folder(self) -> None:
        os.startfile(self.server.save_dir)

    def shutdown(self) -> None:
        logger.info("Shutting down CrossDrop Desktop...")
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
        app = CrossDropApp()
        app.start()
    except Exception as exc:
        logger.exception("Fatal startup exception: %s", exc)
        sys.exit(1)
