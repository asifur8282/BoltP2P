"""
BoltP2P Windows 11 System Tray Integration
Uses pystray and dynamic Pillow icons representing daemon states:
- Dim outline: Offline / Listening
- Solid blue: Connected / Idle keep-alive maintained
- Signal green: Data actively streaming
"""

import threading
from typing import Callable, Optional
from PIL import Image, ImageDraw
import pystray


def create_tray_icon_image(state: str = "listening") -> Image.Image:
    """Generate in-memory 64x64 RGBA system tray icon with crisp geometric states."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Base boundary circle
    draw.ellipse((8, 8, 56, 56), outline="#30363D", width=3)

    if state == "listening":
        # Dim outline / inner carbon dot
        draw.ellipse((24, 24, 40, 40), fill="#8B949E")
    elif state == "connected":
        # Solid blue dot (design.md accent #2F81F7)
        draw.ellipse((20, 20, 44, 44), fill="#2F81F7")
    elif state == "streaming":
        # Active streaming indicator (#238636)
        draw.ellipse((18, 18, 46, 46), fill="#238636")
        draw.arc((4, 4, 60, 60), start=0, end=180, fill="#2F81F7", width=4)

    return img


class TrayManager:
    def __init__(
        self,
        on_open_window: Callable[[], None],
        on_push_clipboard: Callable[[], None],
        on_send_file: Callable[[], None],
        on_open_folder: Callable[[], None],
        on_exit: Callable[[], None]
    ):
        self.on_open_window = on_open_window
        self.on_push_clipboard = on_push_clipboard
        self.on_send_file = on_send_file
        self.on_open_folder = on_open_folder
        self.on_exit = on_exit

        self.icon: Optional[pystray.Icon] = None
        self.state = "listening"

    def build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open JiffBoltP2P", lambda: self.on_open_window(), default=True),
            pystray.MenuItem("Push Clipboard to Phone", lambda: self.on_push_clipboard()),
            pystray.MenuItem("Send File to Phone...", lambda: self.on_send_file()),
            pystray.MenuItem("Open Downloads Folder", lambda: self.on_open_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit JiffBoltP2P", lambda: self.stop())
        )

    def start(self) -> None:
        """Start the system tray icon in detached background thread."""
        initial_image = create_tray_icon_image("listening")
        self.icon = pystray.Icon(
            name="JiffBoltP2P",
            icon=initial_image,
            title="JiffBoltP2P P2P Daemon",
            menu=self.build_menu()
        )
        self.icon.run_detached()

    def set_state(self, state: str) -> None:
        """Update system tray icon state: 'listening' | 'connected' | 'streaming'."""
        self.state = state
        if self.icon:
            self.icon.icon = create_tray_icon_image(state)

    def stop(self) -> None:
        """Cleanly remove tray icon and signal exit callback."""
        if self.icon:
            self.icon.stop()
        if self.on_exit:
            self.on_exit()
