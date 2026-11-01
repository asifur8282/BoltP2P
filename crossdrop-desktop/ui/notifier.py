"""
Windows 11 Native Actionable Toast Notifier
Dispatches native Windows 11 notifications safely without blocking threads or triggering OS protocol dialogs.
"""

import logging
import threading
from typing import Callable, Optional
from win11toast import toast

logger = logging.getLogger("CrossDrop.Notifier")


class Notifier:
    def __init__(
        self,
        on_accept: Optional[Callable[[str], None]] = None,
        on_reject: Optional[Callable[[str], None]] = None,
        on_copy: Optional[Callable[[str], None]] = None,
        on_open_window: Optional[Callable[[], None]] = None
    ):
        self.on_accept = on_accept
        self.on_reject = on_reject
        self.on_copy = on_copy
        self.on_open_window = on_open_window

    def _async_toast(self, title: str, message: str, on_click: Optional[Callable] = None) -> None:
        def _worker():
            try:
                if on_click:
                    toast(title, message, on_click=on_click)
                else:
                    toast(title, message)
            except Exception as e:
                logger.debug("Native toast notice: %s (%s)", title, e)

        threading.Thread(target=_worker, daemon=True).start()

    def notify_text(self, transfer_id: str, preview: str) -> None:
        """Show toast for incoming text; clicking brings Quick Window to front or copies."""
        def _handle_click(args):
            if self.on_copy:
                self.on_copy(transfer_id)
            elif self.on_open_window:
                self.on_open_window()

        self._async_toast(
            "CrossDrop: Text Received",
            f"\"{preview}\"\nClick to open CrossDrop & review.",
            on_click=_handle_click
        )

    def notify_file(self, transfer_id: str, details: str) -> None:
        """Show toast for incoming file; clicking opens CrossDrop Quick Window with Accept/Reject controls."""
        def _handle_click(args):
            if self.on_open_window:
                self.on_open_window()

        self._async_toast(
            "CrossDrop: Incoming File Offer",
            f"{details}\nClick to review & accept in CrossDrop.",
            on_click=_handle_click
        )

    def notify_info(self, title: str, message: str) -> None:
        """Standard informational toast."""
        self._async_toast(title, message)
