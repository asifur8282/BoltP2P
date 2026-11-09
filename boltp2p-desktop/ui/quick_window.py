"""
BoltP2P Desktop Quick Window
Compact 460px x 600px utilitarian UI adhering strictly to design.md tokens:
- Engineered Dark palette (#0E1116, #161B22, #21262D, #30363D)
- 1px crisp mechanical borders
- Active 10-minute ephemeral RAM buffer list with live countdowns
- Non-blocking thread-safe event queue
- Quick Send controls (Push Clipboard, Stream File, Custom Text)
"""

import sys
import tkinter as tk

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

from tkinter import ttk, filedialog, messagebox
import queue
import time
import os
import json
import pyperclip
import qrcode
import ctypes
from ctypes import wintypes
from PIL import Image, ImageTk, ImageGrab
from typing import Optional, Callable, List, Any
from core.network_server import get_lan_ip

# Win32 Drag-Drop hooks
WM_DROPFILES = 0x0233
GWL_WNDPROC = -4

try:
    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32

    SetWindowLongPtr = user32.SetWindowLongPtrW
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    SetWindowLongPtr.restype = ctypes.c_void_p

    CallWindowProc = user32.CallWindowProcW
    CallWindowProc.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    CallWindowProc.restype = ctypes.c_longlong

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    HAS_WIN32_DND = True
except Exception:
    HAS_WIN32_DND = False

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}

# Design Tokens (design.md)
COLOR_SURFACE_0 = "#0E1116"
COLOR_SURFACE_1 = "#161B22"
COLOR_SURFACE_2 = "#21262D"
COLOR_BORDER = "#30363D"
COLOR_TEXT_PRIMARY = "#F0F6FC"
COLOR_TEXT_SECONDARY = "#8B949E"
COLOR_ACCENT = "#2F81F7"
COLOR_SUCCESS = "#238636"
COLOR_WARNING = "#D29922"
COLOR_DANGER = "#DA3633"

FONT_SANS = ("Segoe UI", 10)
FONT_SANS_BOLD = ("Segoe UI", 10, "bold")
FONT_MONO = ("Consolas", 9)
FONT_HEADER = ("Segoe UI", 11, "bold")


class ToolTip:
    """Hover tooltip for Tkinter widgets."""
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip, add="+")
        self.widget.bind("<Leave>", self.hide_tip, add="+")

    def show_tip(self, event=None):
        if self.tip_window or not self.widget.winfo_exists() or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 10
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tw.configure(bg=COLOR_BORDER)
            lbl = tk.Label(
                tw,
                text=self.text,
                justify="left",
                bg=COLOR_SURFACE_1,
                fg=COLOR_TEXT_PRIMARY,
                relief="flat",
                padx=6,
                pady=3,
                font=FONT_MONO
            )
            lbl.pack(padx=1, pady=1)
        except Exception:
            pass

    def hide_tip(self, event=None):
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


class QuickWindow:
    def __init__(
        self,
        server,
        discovery,
        on_send_text: Optional[Callable[[str], None]] = None,
        on_send_file: Optional[Callable[[str], None]] = None,
        on_send_files: Optional[Callable[[List[str]], None]] = None,
        on_connect_peer: Optional[Callable[[str, int], None]] = None
    ):
        self.server = server
        self.discovery = discovery
        self.on_send_text = on_send_text
        self.on_send_files = on_send_files or (lambda fl: [on_send_file(f) for f in fl] if on_send_file else None)
        self.on_send_file = on_send_file
        self.on_connect_peer = on_connect_peer

        self.root: Optional[tk.Tk] = None
        self.status_label: Optional[tk.Label] = None
        self.disconnect_btn: Optional[tk.Button] = None
        self.pairing_card: Optional[tk.LabelFrame] = None
        self.text_input: Optional[tk.Text] = None
        self.offers_frame: Optional[tk.Frame] = None
        self.auto_accept_var: Optional[tk.BooleanVar] = None
        self.auto_accept_files_var: Optional[tk.BooleanVar] = None
        self.peer_target = "127.0.0.1"
        self.peer_port = 58241
        self.peer_name = "Listening for Mobile..."
        self.peer_connected = False
        self.running = True
        self.event_queue = queue.Queue()
        self.has_empty_placeholder = False
        self.qr_photo = None
        self.canvas: Optional[tk.Canvas] = None
        self.offer_timer_labels: dict = {}
        self.offer_progress_bars: dict = {}
        self.offer_progress_labels: dict = {}
        self.outgoing_frame: Optional[tk.LabelFrame] = None
        self.transfers_card: Optional[tk.LabelFrame] = None
        self.outgoing_progress_bars: dict = {}
        self.outgoing_progress_labels: dict = {}
        self.last_offers_signature: str = ""

        # Staging Area state for general input
        self.staged_files: List[str] = []
        self.staged_thumbnails: dict = {}
        self.staged_container: Optional[tk.Frame] = None
        self.staged_items_inner: Optional[tk.Frame] = None
        self.staged_canvas: Optional[tk.Canvas] = None
        self.staged_count_lbl: Optional[tk.Label] = None
        self.send_btn: Optional[tk.Button] = None
        self.btn_row: Optional[tk.Frame] = None
        self._old_wndprocs: dict = {}
        self._wndproc_refs: list = []

    def show_or_restore(self) -> None:
        """Thread-safe request to bring window to front or initialize."""
        if self.root and self.root.winfo_exists():
            self.event_queue.put(("restore", None))
        else:
            self.show()

    def _restore(self) -> None:
        if self.root and self.root.winfo_exists():
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()

    def show(self) -> None:
        if self.root and self.root.winfo_exists():
            self._restore()
            return

        self.root = tk.Tk()
        self.root.title("BoltP2P [Desktop Daemon]")
        self.root.geometry("460x700")
        self.root.minsize(460, 480)
        self.root.configure(bg=COLOR_SURFACE_0)

        # Style configurations for ttk
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Custom.Horizontal.TProgressbar",
            foreground=COLOR_ACCENT,
            background=COLOR_ACCENT,
            troughcolor=COLOR_SURFACE_0,
            bordercolor=COLOR_BORDER,
            lightcolor=COLOR_ACCENT,
            darkcolor=COLOR_ACCENT
        )
        self._build_ui()
        self._setup_drag_and_drop()

        # Handle window close as hide to tray
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        # Native non-blocking event loop hooks (zero background thread interference)
        self.root.after(50, self._process_event_queue)
        self.root.after(1000, self._on_timer_tick)

        self.root.mainloop()

    def hide(self) -> None:
        if self.root and self.root.winfo_exists():
            self.root.withdraw()

    def update_peer_status(self, name: str, ip: str, port: int, connected: bool) -> None:
        """Thread-safe update from network server or discovery."""
        self.peer_name = name
        self.peer_target = ip
        self.peer_port = port
        self.peer_connected = connected
        self.event_queue.put(("render_status", None))

    def trigger_offers_refresh(self) -> None:
        """Thread-safe request to re-render incoming offers."""
        self.event_queue.put(("refresh_offers", None))

    def _render_status(self) -> None:
        if not self.status_label:
            return
        if self.peer_connected:
            self.status_label.config(
                text=f"● ONLINE  |  Connected: {self.peer_name} ({self.peer_target})",
                fg=COLOR_SUCCESS
            )
            if self.disconnect_btn:
                self.disconnect_btn.pack(side="right", padx=6, pady=2)
        else:
            self.status_label.config(
                text=f"○ IDLE  |  LAN Service: {self.discovery.device_name} (Port {self.server.port})",
                fg=COLOR_TEXT_SECONDARY
            )
            if self.disconnect_btn:
                self.disconnect_btn.pack_forget()

    def _build_ui(self) -> None:
        # 1. Status Bar Header
        header_frame = tk.Frame(self.root, bg=COLOR_SURFACE_1, height=36, highlightbackground=COLOR_BORDER, highlightthickness=1)
        header_frame.pack(fill="x", padx=10, pady=(10, 4))

        self.status_label = tk.Label(
            header_frame,
            text="",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_SECONDARY,
            font=FONT_SANS_BOLD,
            anchor="w",
            padx=8,
            pady=6
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        self.disconnect_btn = tk.Button(
            header_frame,
            text="Disconnect",
            bg=COLOR_SURFACE_2,
            fg=COLOR_DANGER,
            activebackground=COLOR_BORDER,
            font=FONT_SANS_BOLD,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=2,
            command=self._handle_disconnect
        )
        self._render_status()

        # 2. Pairing & Connection Card (Always visible on startup)
        lan_ip = get_lan_ip()
        pairing_card = tk.LabelFrame(
            self.root,
            text=" PAIRING & CONNECTION ",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_PRIMARY,
            font=FONT_HEADER,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8
        )
        pairing_card.pack(fill="x", padx=10, pady=4)
        self.pairing_card = pairing_card

        pair_row = tk.Frame(pairing_card, bg=COLOR_SURFACE_1)
        pair_row.pack(fill="x")

        # QR Code Generation
        try:
            qr_payload = json.dumps({
                "ip": lan_ip,
                "port": self.server.port,
                "pin": self.server.pairing_pin,
                "psk": self.server.pairing_psk,
                "device": self.server.device_name
            })
            qr = qrcode.QRCode(box_size=3, border=1)
            qr.add_data(qr_payload)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="#F0F6FC", back_color="#0E1116")
            self.qr_photo = ImageTk.PhotoImage(qr_img)

            qr_lbl = tk.Label(pair_row, image=self.qr_photo, bg=COLOR_SURFACE_0, bd=1, relief="solid")
            qr_lbl.pack(side="left", padx=(0, 10))
        except Exception as e:
            pass

        info_col = tk.Frame(pair_row, bg=COLOR_SURFACE_1)
        info_col.pack(side="left", fill="both", expand=True)

        tk.Label(info_col, text=f"Local IP:  {lan_ip}", font=FONT_MONO, bg=COLOR_SURFACE_1, fg=COLOR_TEXT_PRIMARY, anchor="w").pack(fill="x", pady=1)
        tk.Label(info_col, text=f"Port:      {self.server.port}", font=FONT_MONO, bg=COLOR_SURFACE_1, fg=COLOR_TEXT_SECONDARY, anchor="w").pack(fill="x", pady=1)
        tk.Label(info_col, text=f"PIN Code:  {self.server.pairing_pin}", font=("Consolas", 12, "bold"), bg=COLOR_SURFACE_1, fg=COLOR_ACCENT, anchor="w").pack(fill="x", pady=(2, 6))

        connect_remote_btn = tk.Button(
            info_col,
            text="Connect to Remote Device (IP/QR)",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_PRIMARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=3,
            command=self._prompt_connect_peer
        )
        connect_remote_btn.pack(fill="x")

        # 3. General Input & Staged Send Card
        send_card = tk.LabelFrame(
            self.root,
            text=" GENERAL INPUT & QUICK SEND ",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_PRIMARY,
            font=FONT_HEADER,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=6
        )
        send_card.pack(fill="x", padx=10, pady=4)

        self.text_input = tk.Text(
            send_card,
            height=3,
            bg=COLOR_SURFACE_0,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_TEXT_PRIMARY,
            font=FONT_SANS,
            relief="flat",
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=6,
            pady=6
        )
        self.text_input.pack(fill="x", pady=(0, 6))
        self.text_input.insert("1.0", "Type message, or drop files / paste image (Ctrl+V) here...")
        self.text_input.bind("<FocusIn>", self._clear_placeholder)
        self.text_input.bind("<Control-v>", self._handle_paste_event)
        self.text_input.bind("<Control-V>", self._handle_paste_event)
        self.text_input.bind("<Control-Return>", lambda e: self._handle_send_staged())
        self.root.bind("<Control-v>", self._handle_paste_event)
        self.root.bind("<Control-V>", self._handle_paste_event)
        self.root.bind("<Control-Return>", lambda e: self._handle_send_staged())

        # Staged Attachments Container (Hidden until files/images are staged)
        self.staged_container = tk.Frame(send_card, bg=COLOR_SURFACE_1)

        staged_header = tk.Frame(self.staged_container, bg=COLOR_SURFACE_1)
        staged_header.pack(fill="x", pady=(0, 4))

        self.staged_count_lbl = tk.Label(
            staged_header,
            text="STAGED ATTACHMENTS (Ready to send)",
            bg=COLOR_SURFACE_1,
            fg=COLOR_ACCENT,
            font=FONT_MONO
        )
        self.staged_count_lbl.pack(side="left")

        clear_all_btn = tk.Button(
            staged_header,
            text="Clear All",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_SECONDARY,
            activeforeground=COLOR_DANGER,
            activebackground=COLOR_SURFACE_1,
            font=("Segoe UI", 8),
            relief="flat",
            cursor="hand2",
            command=self.clear_staged_files
        )
        clear_all_btn.pack(side="right")

        # Scrollable container for thumbnail cards
        staged_scroll_frame = tk.Frame(self.staged_container, bg=COLOR_SURFACE_1)
        staged_scroll_frame.pack(fill="x", pady=(0, 2))

        self.staged_canvas = tk.Canvas(staged_scroll_frame, bg=COLOR_SURFACE_1, height=92, highlightthickness=0)
        self.staged_items_inner = tk.Frame(self.staged_canvas, bg=COLOR_SURFACE_1)

        self.staged_items_inner.bind(
            "<Configure>",
            lambda e: self.staged_canvas.configure(scrollregion=self.staged_canvas.bbox("all"))
        )
        self.staged_canvas.create_window((0, 0), window=self.staged_items_inner, anchor="nw")
        self.staged_canvas.pack(side="top", fill="x", expand=True)

        def _on_h_mousewheel(event):
            if self.staged_canvas and self.staged_canvas.winfo_exists():
                self.staged_canvas.xview_scroll(int(-1 * (event.delta / 120)), "units")

        self.staged_canvas.bind("<MouseWheel>", _on_h_mousewheel)
        self.staged_items_inner.bind("<MouseWheel>", _on_h_mousewheel)

        btn_row = tk.Frame(send_card, bg=COLOR_SURFACE_1)
        btn_row.pack(fill="x")
        self.btn_row = btn_row

        self.send_btn = tk.Button(
            btn_row,
            text="Send to Connected Device",
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            activebackground="#388BFD",
            activeforeground="#FFFFFF",
            font=FONT_SANS_BOLD,
            relief="flat",
            cursor="hand2",
            padx=12,
            pady=4,
            command=self._handle_send_staged
        )
        self.send_btn.pack(side="left", padx=(0, 6))

        attach_btn = tk.Button(
            btn_row,
            text="📎 Attach Files",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_PRIMARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self._handle_select_file
        )
        attach_btn.pack(side="left", padx=(0, 6))

        push_btn = tk.Button(
            btn_row,
            text="📋 Push Clipboard",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_SECONDARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self._handle_push_clipboard
        )
        push_btn.pack(side="right")

        # Outgoing Stream Card (hidden until file streaming is active)
        self.outgoing_frame = tk.LabelFrame(
            self.root,
            text=" OUTGOING STREAM ",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_PRIMARY,
            font=FONT_HEADER,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=4
        )
        # Not packed initially; packed on start_outgoing_transfer

        # 4. Bottom Utility Bar (docked permanently to bottom of window)
        bottom_bar = tk.Frame(self.root, bg=COLOR_SURFACE_1, height=36, highlightbackground=COLOR_BORDER, highlightthickness=1)
        bottom_bar.pack(side="bottom", fill="x", padx=10, pady=(4, 10))

        self.auto_accept_files_var = tk.BooleanVar(value=getattr(self.server, "auto_accept_files", False))
        chk_files = tk.Checkbutton(
            bottom_bar,
            text="Auto-Accept Files",
            variable=self.auto_accept_files_var,
            command=self._toggle_auto_accept_files,
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_SECONDARY,
            selectcolor=COLOR_SURFACE_0,
            activebackground=COLOR_SURFACE_1,
            activeforeground=COLOR_TEXT_PRIMARY,
            font=FONT_SANS
        )
        chk_files.pack(side="right", padx=(4, 8), pady=4)

        self.auto_accept_var = tk.BooleanVar(value=self.server.auto_accept_text)
        chk = tk.Checkbutton(
            bottom_bar,
            text="Auto-Accept Text",
            variable=self.auto_accept_var,
            command=self._toggle_auto_accept,
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_SECONDARY,
            selectcolor=COLOR_SURFACE_0,
            activebackground=COLOR_SURFACE_1,
            activeforeground=COLOR_TEXT_PRIMARY,
            font=FONT_SANS
        )
        chk.pack(side="right", padx=4, pady=4)

        open_folder_btn = tk.Button(
            bottom_bar,
            text="Open Downloads",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_SECONDARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            padx=8,
            pady=2,
            command=self._open_downloads_folder
        )
        open_folder_btn.pack(side="left", padx=8, pady=4)

        # 3. Active / Recent Transfers (10m Ephemeral RAM Window)
        self.transfers_card = tk.LabelFrame(
            self.root,
            text=" ACTIVE / RECENT OFFERS (10m Ephemeral RAM Window) ",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_PRIMARY,
            font=FONT_HEADER,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8
        )
        self.transfers_card.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # Canvas + Scrollbar for Offers List
        canvas = tk.Canvas(self.transfers_card, bg=COLOR_SURFACE_1, highlightthickness=0)
        self.canvas = canvas
        scrollbar = ttk.Scrollbar(self.transfers_card, orient="vertical", command=canvas.yview)
        self.offers_frame = tk.Frame(canvas, bg=COLOR_SURFACE_1)

        self.offers_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.offers_frame, anchor="nw", width=416)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            if self.canvas and self.canvas.winfo_exists():
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        self.offers_frame.bind("<MouseWheel>", _on_mousewheel)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.refresh_offers_ui()

    def _toggle_auto_accept(self) -> None:
        if self.server and self.auto_accept_var:
            self.server.auto_accept_text = self.auto_accept_var.get()

    def _toggle_auto_accept_files(self) -> None:
        if self.server and self.auto_accept_files_var:
            self.server.auto_accept_files = self.auto_accept_files_var.get()

    def _open_downloads_folder(self) -> None:
        import os
        os.startfile(self.server.save_dir)

    def _safe_open_file(self, filepath: str) -> None:
        """Safely open received file; warn if executable or script to prevent user-assisted RCE."""
        ext = os.path.splitext(filepath)[1].lower()
        dangerous_extensions = {
            ".exe", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
            ".ps1", ".ps1xml", ".ps2", ".ps2xml", ".psc1", ".psc2", ".msh", ".msh1",
            ".msh2", ".mshxml", ".msh1xml", ".msh2xml", ".scf", ".lnk", ".inf",
            ".reg", ".dll", ".com", ".scr", ".hta", ".cpl", ".jar", ".pif", ".msi", ".msp"
        }
        if ext in dangerous_extensions:
            fname = os.path.basename(filepath)
            confirmed = messagebox.askyesno(
                "Security Warning",
                f"'{fname}' is an executable program or script ({ext}).\n\n"
                "Executing untrusted files received over the network may harm your computer.\n\n"
                "Are you sure you want to run this file?",
                icon="warning"
            )
            if not confirmed:
                return
        try:
            os.startfile(filepath)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file: {e}")

    def _clear_placeholder(self, event=None) -> None:
        if not self.text_input:
            return
        current = self.text_input.get("1.0", "end-1c").strip()
        if current in [
            "Paste or type text to push to phone...",
            "Type message, or drop files / paste image (Ctrl+V) here..."
        ]:
            self.text_input.delete("1.0", "end")

    def _setup_drag_and_drop(self) -> None:
        """Register native Win32 WM_DROPFILES on window and input widgets."""
        if not HAS_WIN32_DND or not self.root:
            return
        try:
            self.root.update_idletasks()
            targets = [self.root]
            if self.text_input:
                targets.append(self.text_input)

            def make_wndproc(hwnd):
                def proc(h, msg, wp, lp):
                    if msg == WM_DROPFILES:
                        hdrop = wp
                        count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                        dropped = []
                        for i in range(count):
                            length = shell32.DragQueryFileW(hdrop, i, None, 0)
                            buf = ctypes.create_unicode_buffer(length + 1)
                            shell32.DragQueryFileW(hdrop, i, buf, length + 1)
                            dropped.append(buf.value)
                        shell32.DragFinish(hdrop)
                        if dropped:
                            self.event_queue.put(("files_dropped", dropped))
                        return 0
                    old_p = self._old_wndprocs.get(h)
                    if old_p:
                        return CallWindowProc(old_p, h, msg, wp, lp)
                    return 0
                return WNDPROC(proc)

            for target in targets:
                try:
                    hid = target.winfo_id()
                    shell32.DragAcceptFiles(hid, True)
                    wp = make_wndproc(hid)
                    self._wndproc_refs.append(wp)
                    old_p = SetWindowLongPtr(hid, GWL_WNDPROC, ctypes.cast(wp, ctypes.c_void_p))
                    self._old_wndprocs[hid] = old_p
                except Exception:
                    pass
        except Exception:
            pass

    def _handle_paste_event(self, event=None):
        """Handle Ctrl+V: stage image or files from clipboard without auto-sending; allow text to paste."""
        # 1. Check if an image or list of files is in the clipboard
        try:
            from PIL import ImageGrab
            data = ImageGrab.grabclipboard()
            if data is not None:
                if isinstance(data, list):
                    # List of file paths copied in Windows Explorer
                    self.stage_files(data)
                    return "break"
                elif hasattr(data, "save"):
                    # PIL Image object from Snipping Tool or Browser
                    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cache")
                    os.makedirs(cache_dir, exist_ok=True)
                    timestamp = int(time.time() * 1000)
                    img_path = os.path.join(cache_dir, f"pasted_image_{timestamp}.png")
                    data.save(img_path, "PNG")
                    self.stage_files([img_path])
                    return "break"
        except Exception:
            pass

        # 2. Check win32clipboard for copied files (CF_HDROP)
        try:
            import win32clipboard
            win32clipboard.OpenClipboard(self.root.winfo_id() if self.root else 0)
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP):
                    files = win32clipboard.GetClipboardData(win32clipboard.CF_HDROP)
                    if files:
                        self.stage_files(list(files))
                        return "break"
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            pass

        # 3. For text paste: clear placeholder if present, let standard Tkinter paste continue
        if self.text_input:
            current = self.text_input.get("1.0", "end-1c").strip()
            if current in [
                "Paste or type text to push to phone...",
                "Type message, or drop files / paste image (Ctrl+V) here..."
            ]:
                self.text_input.delete("1.0", "end")
        return None

    def stage_files(self, filepaths: List[str]) -> None:
        """Stage files or images into the general input without sending immediately."""
        changed = False
        for path in filepaths:
            if path and os.path.exists(path) and path not in self.staged_files:
                self.staged_files.append(path)
                changed = True
        if changed:
            self._render_staged_items()

    def unstage_file(self, filepath: str) -> None:
        """Remove a staged file before sending."""
        if filepath in self.staged_files:
            self.staged_files.remove(filepath)
            self._render_staged_items()

    def clear_staged_files(self) -> None:
        """Remove all staged files."""
        self.staged_files.clear()
        self._render_staged_items()

    def _render_staged_items(self) -> None:
        """Render square/rounded thumbnails for staged images and document badges."""
        if not self.staged_container or not self.root or not self.root.winfo_exists():
            return

        for child in self.staged_items_inner.winfo_children():
            child.destroy()
        self.staged_thumbnails.clear()

        if not self.staged_files:
            self.staged_container.pack_forget()
            if self.send_btn:
                self.send_btn.config(text="Send to Connected Device")
            self.root.update_idletasks()
            return

        self.staged_container.pack(fill="x", pady=(0, 8), before=self.btn_row)
        count = len(self.staged_files)
        self.staged_count_lbl.config(
            text=f"STAGED ATTACHMENTS ({count} item{'s' if count != 1 else ''} ready to send)"
        )
        if self.send_btn:
            self.send_btn.config(text=f"Send to Connected Device ({count})")

        for filepath in self.staged_files:
            ext = os.path.splitext(filepath)[1].lower()
            fname = os.path.basename(filepath)
            fsize = os.path.getsize(filepath) if os.path.exists(filepath) else 0
            size_str = f"{fsize/(1024*1024):.1f} MB" if fsize > 1024*1024 else f"{fsize/1024:.0f} KB"
            is_image = ext in IMAGE_EXTENSIONS

            card = tk.Frame(
                self.staged_items_inner,
                bg=COLOR_SURFACE_2,
                highlightbackground=COLOR_BORDER,
                highlightthickness=1,
                padx=4,
                pady=4,
                width=78,
                height=88
            )
            card.pack_propagate(False)
            card.pack(side="left", padx=(0, 6), pady=2)

            # Top bar with close button
            top_bar = tk.Frame(card, bg=COLOR_SURFACE_2)
            top_bar.pack(fill="x")

            del_btn = tk.Label(
                top_bar,
                text="✕",
                bg=COLOR_SURFACE_2,
                fg=COLOR_TEXT_SECONDARY,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2"
            )
            del_btn.pack(side="right")
            del_btn.bind("<Enter>", lambda e, b=del_btn: b.config(fg=COLOR_DANGER))
            del_btn.bind("<Leave>", lambda e, b=del_btn: b.config(fg=COLOR_TEXT_SECONDARY))
            del_btn.bind("<Button-1>", lambda e, p=filepath: self.unstage_file(p))

            if is_image:
                thumb_photo = None
                try:
                    with Image.open(filepath) as img:
                        img_thumb = img.copy()
                        img_thumb.thumbnail((50, 44), Image.Resampling.LANCZOS)
                        thumb_photo = ImageTk.PhotoImage(img_thumb)
                        self.staged_thumbnails[filepath] = thumb_photo
                except Exception:
                    pass

                if thumb_photo:
                    thumb_lbl = tk.Label(card, image=thumb_photo, bg=COLOR_SURFACE_2, cursor="hand2")
                    thumb_lbl.pack(pady=(1, 2))
                    thumb_lbl.bind("<Button-1>", lambda e, p=filepath: self._show_image_preview(p))
                else:
                    thumb_lbl = tk.Label(card, text="🖼️", font=("Segoe UI", 16), bg=COLOR_SURFACE_2, fg=COLOR_ACCENT, cursor="hand2")
                    thumb_lbl.pack(pady=(2, 2))
                    thumb_lbl.bind("<Button-1>", lambda e, p=filepath: self._show_image_preview(p))

                ToolTip(card, f"Image: {fname}\nSize: {size_str}\nClick to view full preview")
                card.bind("<Button-1>", lambda e, p=filepath: self._show_image_preview(p))

            else:
                # Document / Non-Image Badge
                badge_text = ext.replace(".", "").upper()[:4] or "FILE"
                badge_fg = COLOR_ACCENT
                if ext in {".pdf"}:
                    badge_fg = "#F85149"
                elif ext in {".doc", ".docx", ".txt", ".md"}:
                    badge_fg = "#58A6FF"
                elif ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
                    badge_fg = "#D29922"
                elif ext in {".mp3", ".wav", ".flac", ".m4a"}:
                    badge_fg = "#BC8CFF"
                elif ext in {".mp4", ".mkv", ".avi", ".mov"}:
                    badge_fg = "#7EE787"

                badge_lbl = tk.Label(
                    card,
                    text=badge_text,
                    bg=COLOR_SURFACE_0,
                    fg=badge_fg,
                    font=FONT_MONO,
                    padx=4,
                    pady=6,
                    relief="flat",
                    cursor="hand2"
                )
                badge_lbl.pack(fill="x", padx=4, pady=(2, 2))
                badge_lbl.bind("<Double-Button-1>", lambda e, p=filepath: self._safe_open_file(p))
                card.bind("<Double-Button-1>", lambda e, p=filepath: self._safe_open_file(p))

                ToolTip(card, f"File: {fname}\nSize: {size_str}\nPath: {filepath}\nDouble-click to open file")

            # Filename label below thumbnail (truncated)
            display_name = fname if len(fname) <= 10 else fname[:7] + "..." + (ext if len(ext) <= 4 else "")
            name_lbl = tk.Label(
                card,
                text=display_name,
                bg=COLOR_SURFACE_2,
                fg=COLOR_TEXT_PRIMARY,
                font=("Segoe UI", 7),
                anchor="center"
            )
            name_lbl.pack(fill="x")

        self.root.update_idletasks()

    def _show_image_preview(self, filepath: str) -> None:
        """Popup viewer to preview staged image."""
        if not os.path.exists(filepath):
            messagebox.showerror("File Not Found", f"Cannot preview: '{filepath}' does not exist.")
            return

        preview_top = tk.Toplevel(self.root)
        preview_top.title(f"Image Preview - {os.path.basename(filepath)}")
        preview_top.geometry("520x560")
        preview_top.configure(bg=COLOR_SURFACE_0)
        preview_top.transient(self.root)

        try:
            with Image.open(filepath) as orig:
                orig_w, orig_h = orig.size
                fsize = os.path.getsize(filepath)
                size_str = f"{fsize/(1024*1024):.2f} MB" if fsize > 1024*1024 else f"{fsize/1024:.1f} KB"

                info_frame = tk.Frame(preview_top, bg=COLOR_SURFACE_1, highlightbackground=COLOR_BORDER, highlightthickness=1)
                info_frame.pack(fill="x", padx=12, pady=(12, 6))

                tk.Label(
                    info_frame,
                    text=os.path.basename(filepath),
                    bg=COLOR_SURFACE_1,
                    fg=COLOR_TEXT_PRIMARY,
                    font=FONT_SANS_BOLD,
                    anchor="w"
                ).pack(fill="x", padx=10, pady=(6, 2))

                tk.Label(
                    info_frame,
                    text=f"Resolution: {orig_w} × {orig_h} px  •  Size: {size_str}",
                    bg=COLOR_SURFACE_1,
                    fg=COLOR_TEXT_SECONDARY,
                    font=FONT_MONO,
                    anchor="w"
                ).pack(fill="x", padx=10, pady=(0, 6))

                display_img = orig.copy()
                display_img.thumbnail((480, 400), Image.Resampling.LANCZOS)
                preview_photo = ImageTk.PhotoImage(display_img)

                img_lbl = tk.Label(
                    preview_top,
                    image=preview_photo,
                    bg=COLOR_SURFACE_1,
                    relief="solid",
                    bd=1
                )
                img_lbl.image = preview_photo
                img_lbl.pack(padx=12, pady=6, expand=True)

                action_row = tk.Frame(preview_top, bg=COLOR_SURFACE_0)
                action_row.pack(fill="x", padx=12, pady=10)

                tk.Button(
                    action_row,
                    text="Open in Default App",
                    bg=COLOR_SURFACE_2,
                    fg=COLOR_TEXT_PRIMARY,
                    font=FONT_SANS,
                    relief="flat",
                    cursor="hand2",
                    padx=10,
                    pady=4,
                    command=lambda: os.startfile(filepath)
                ).pack(side="left")

                tk.Button(
                    action_row,
                    text="Close",
                    bg=COLOR_ACCENT,
                    fg="#FFFFFF",
                    font=FONT_SANS_BOLD,
                    relief="flat",
                    cursor="hand2",
                    padx=14,
                    pady=4,
                    command=preview_top.destroy
                ).pack(side="right")

        except Exception as e:
            messagebox.showerror("Preview Error", f"Failed to load image preview: {e}")
            preview_top.destroy()

    def _handle_send_staged(self) -> None:
        """Send all staged files and/or custom text to the connected device upon explicit click."""
        text = self.text_input.get("1.0", "end-1c").strip() if self.text_input else ""
        placeholder_texts = [
            "Paste or type text to push to phone...",
            "Type message, or drop files / paste image (Ctrl+V) here..."
        ]
        is_valid_text = bool(text and text not in placeholder_texts)
        has_files = bool(self.staged_files)

        if not has_files and not is_valid_text:
            messagebox.showinfo(
                "Nothing to Send",
                "Please type a text message, drag & drop files, or paste an image (Ctrl+V) first."
            )
            return

        # 1. Send staged files if any
        if has_files:
            files_to_send = list(self.staged_files)
            self.clear_staged_files()
            if self.on_send_files:
                self.on_send_files(files_to_send)
            elif self.on_send_file:
                for f in files_to_send:
                    self.on_send_file(f)

        # 2. Send custom text if typed
        if is_valid_text:
            if self.on_send_text:
                self.on_send_text(text)
            if self.text_input:
                self.text_input.delete("1.0", "end")

    def _handle_push_clipboard(self) -> None:
        try:
            content = pyperclip.paste()
            if content and self.on_send_text:
                self.on_send_text(content)
        except Exception as e:
            messagebox.showerror("Clipboard Error", str(e))

    def _handle_send_custom_text(self) -> None:
        self._handle_send_staged()

    def _handle_select_file(self) -> None:
        """Open file dialog and stage selected files without sending immediately."""
        filenames = filedialog.askopenfilenames(title="Select File(s) to Attach")
        if filenames:
            self.stage_files(list(filenames))

    def refresh_offers_ui(self) -> None:
        """Re-render pending RAM transfer offers with remaining TTL."""
        if not self.offers_frame or not self.root or not self.root.winfo_exists():
            return

        offers = list(self.server.pending_offers.values()) if self.server else []
        # Sort so latest incoming is ON TOP!
        offers.sort(key=lambda x: x.created_at, reverse=True)
        self.last_offers_signature = "|".join(f"{t.transfer_id}:{t.state}" for t in offers)

        if not offers:
            self.offer_timer_labels.clear()
            self.offer_progress_bars.clear()
            self.offer_progress_labels.clear()
            if not self.has_empty_placeholder:
                for child in self.offers_frame.winfo_children():
                    child.destroy()
                lbl = tk.Label(
                    self.offers_frame,
                    text="No pending ephemeral offers in RAM.\nTransfers received will appear here with a 10m TTL.",
                    bg=COLOR_SURFACE_1,
                    fg=COLOR_TEXT_SECONDARY,
                    font=FONT_SANS,
                    pady=40
                )
                lbl.pack(fill="x")
                self.has_empty_placeholder = True
            return

        # Save previous scroll position
        prev_yview = self.canvas.yview() if self.canvas else None

        # If offers are present, rebuild frame
        self.has_empty_placeholder = False
        self.offer_timer_labels.clear()
        self.offer_progress_bars.clear()
        self.offer_progress_labels.clear()
        for child in self.offers_frame.winfo_children():
            child.destroy()

        for offer in offers:
            row = tk.Frame(self.offers_frame, bg=COLOR_SURFACE_0, highlightbackground=COLOR_BORDER, highlightthickness=1)
            row.pack(fill="x", pady=4, padx=2)

            ttl_left = offer.remaining_ttl()
            mins, secs = divmod(ttl_left, 60)
            ttl_str = f"{mins:02d}:{secs:02d}"
            timer_color = COLOR_WARNING if ttl_left < 60 else COLOR_TEXT_SECONDARY

            if offer.msg_type == 2:  # TEXT
                preview = offer.metadata.get("preview", "Text offer")
                lbl_top = tk.Label(
                    row,
                    text=f"📋 Text: \"{preview}\"",
                    bg=COLOR_SURFACE_0,
                    fg=COLOR_TEXT_PRIMARY,
                    font=FONT_SANS_BOLD,
                    anchor="w"
                )
                lbl_top.pack(fill="x", padx=8, pady=(6, 2))

                lbl_sub = tk.Label(
                    row,
                    text=f"Expires in: {ttl_str}",
                    bg=COLOR_SURFACE_0,
                    fg=timer_color,
                    font=FONT_MONO,
                    anchor="w"
                )
                lbl_sub.pack(fill="x", padx=8, pady=(0, 4))
                self.offer_timer_labels[offer.transfer_id] = lbl_sub

                btn_f = tk.Frame(row, bg=COLOR_SURFACE_0)
                btn_f.pack(fill="x", padx=8, pady=(0, 6))

                is_copied = getattr(offer, "copied", False)
                btn_copy_text = "Copy Again" if is_copied else "Copy to Clipboard"
                btn_copy_bg = COLOR_SURFACE_2 if is_copied else COLOR_ACCENT
                btn_copy_fg = COLOR_TEXT_PRIMARY if is_copied else "#FFFFFF"

                tk.Button(
                    btn_f,
                    text=btn_copy_text,
                    bg=btn_copy_bg,
                    fg=btn_copy_fg,
                    font=FONT_SANS,
                    relief="flat",
                    cursor="hand2",
                    padx=6,
                    pady=2,
                    command=lambda tid=offer.transfer_id: self._copy_text(tid)
                ).pack(side="left", padx=(0, 4))

                tk.Button(
                    btn_f,
                    text="Dismiss",
                    bg=COLOR_SURFACE_2,
                    fg=COLOR_TEXT_SECONDARY,
                    font=FONT_SANS,
                    relief="flat",
                    cursor="hand2",
                    padx=6,
                    pady=2,
                    command=lambda tid=offer.transfer_id: self._reject_offer(tid)
                ).pack(side="left")

            else:  # FILE / IMAGE
                fname = offer.metadata.get("filename", "unknown.bin")
                fsize = offer.metadata.get("size", 0)
                size_str = f"{fsize / (1024*1024):.2f} MB" if fsize > 1024*1024 else f"{fsize / 1024:.1f} KB"

                if offer.state == "DOWNLOADING":
                    pct = int(offer.progress * 100)
                    rec = offer.bytes_transferred
                    rec_str = f"{rec / (1024*1024):.2f} MB" if rec > 1024*1024 else f"{rec / 1024:.1f} KB"
                    lbl_top = tk.Label(
                        row,
                        text=f"⬇️ Downloading: {fname} - {rec_str} / {size_str} ({pct}%)",
                        bg=COLOR_SURFACE_0,
                        fg=COLOR_ACCENT,
                        font=FONT_SANS_BOLD,
                        anchor="w"
                    )
                    lbl_top.fname = fname
                    lbl_top.pack(fill="x", padx=8, pady=(6, 2))
                    self.offer_progress_labels[offer.transfer_id] = lbl_top

                    pbar = ttk.Progressbar(
                        row,
                        style="Custom.Horizontal.TProgressbar",
                        orient="horizontal",
                        mode="determinate",
                        maximum=100,
                        value=pct
                    )
                    pbar.pack(fill="x", padx=8, pady=(4, 8))
                    self.offer_progress_bars[offer.transfer_id] = pbar

                elif offer.state == "COMPLETED":
                    lbl_top = tk.Label(
                        row,
                        text=f"✅ {fname} - Completed (SHA-256 Verified)",
                        bg=COLOR_SURFACE_0,
                        fg=COLOR_SUCCESS,
                        font=FONT_SANS_BOLD,
                        anchor="w"
                    )
                    lbl_top.pack(fill="x", padx=8, pady=(6, 2))

                    btn_f = tk.Frame(row, bg=COLOR_SURFACE_0)
                    btn_f.pack(fill="x", padx=8, pady=(0, 6))

                    target_path = os.path.join(self.server.save_dir, fname)
                    if os.path.exists(target_path):
                        tk.Button(
                            btn_f,
                            text="Open File",
                            bg=COLOR_SUCCESS,
                            fg="#FFFFFF",
                            font=FONT_SANS,
                            relief="flat",
                            padx=6,
                            pady=2,
                            command=lambda p=target_path: self._safe_open_file(p)
                        ).pack(side="left", padx=(0, 4))

                    tk.Button(
                        btn_f,
                        text="Dismiss",
                        bg=COLOR_SURFACE_2,
                        fg=COLOR_TEXT_SECONDARY,
                        font=FONT_SANS,
                        relief="flat",
                        padx=6,
                        pady=2,
                        command=lambda tid=offer.transfer_id: self._dismiss_offer(tid)
                    ).pack(side="left")

                elif offer.state == "REJECTED":
                    lbl_top = tk.Label(
                        row,
                        text=f"❌ {fname} - Declined or Expired",
                        bg=COLOR_SURFACE_0,
                        fg=COLOR_DANGER,
                        font=FONT_SANS,
                        anchor="w"
                    )
                    lbl_top.pack(fill="x", padx=8, pady=(6, 2))
                    tk.Button(
                        row,
                        text="Dismiss",
                        bg=COLOR_SURFACE_2,
                        fg=COLOR_TEXT_SECONDARY,
                        font=FONT_SANS,
                        relief="flat",
                        padx=6,
                        pady=2,
                        command=lambda tid=offer.transfer_id: self._dismiss_offer(tid)
                    ).pack(padx=8, pady=(0, 6), anchor="w")

                else:  # PENDING
                    lbl_top = tk.Label(
                        row,
                        text=f"📷 {fname} ({size_str})",
                        bg=COLOR_SURFACE_0,
                        fg=COLOR_TEXT_PRIMARY,
                        font=FONT_SANS_BOLD,
                        anchor="w"
                    )
                    lbl_top.pack(fill="x", padx=8, pady=(6, 2))

                    lbl_sub = tk.Label(
                        row,
                        text=f"Direct Stream  •  Expires in: {ttl_str}",
                        bg=COLOR_SURFACE_0,
                        fg=timer_color,
                        font=FONT_MONO,
                        anchor="w"
                    )
                    lbl_sub.pack(fill="x", padx=8, pady=(0, 4))
                    self.offer_timer_labels[offer.transfer_id] = lbl_sub

                    btn_f = tk.Frame(row, bg=COLOR_SURFACE_0)
                    btn_f.pack(fill="x", padx=8, pady=(0, 6))

                    tk.Button(
                        btn_f,
                        text="Accept & Save",
                        bg=COLOR_SUCCESS,
                        fg="#FFFFFF",
                        font=FONT_SANS,
                        relief="flat",
                        padx=6,
                        pady=2,
                        command=lambda tid=offer.transfer_id: self._accept_file(tid)
                    ).pack(side="left", padx=(0, 4))

                    tk.Button(
                        btn_f,
                        text="Accept All",
                        bg=COLOR_SURFACE_2,
                        fg=COLOR_ACCENT,
                        font=FONT_SANS,
                        relief="flat",
                        padx=6,
                        pady=2,
                        command=lambda tid=offer.transfer_id: self._accept_all_files(tid)
                    ).pack(side="left", padx=(0, 4))

                    tk.Button(
                        btn_f,
                        text="Reject",
                        bg=COLOR_SURFACE_2,
                        fg=COLOR_DANGER,
                        font=FONT_SANS,
                        relief="flat",
                        padx=6,
                        pady=2,
                        command=lambda tid=offer.transfer_id: self._reject_offer(tid)
                    ).pack(side="left")

        # Restore scroll position if previously scrolled down
        if self.canvas and prev_yview and prev_yview[0] > 0.0:
            self.root.update_idletasks()
            self.canvas.yview_moveto(prev_yview[0])

    def _copy_text(self, transfer_id: str) -> None:
        self.server.copy_text(transfer_id)
        self.refresh_offers_ui()

    def _accept_file(self, transfer_id: str) -> None:
        self.server.accept_transfer(transfer_id)
        self.refresh_offers_ui()

    def _accept_all_files(self, transfer_id: str) -> None:
        if self.server:
            self.server.auto_accept_files = True
        if self.auto_accept_files_var:
            self.auto_accept_files_var.set(True)
        self._accept_file(transfer_id)

    def _reject_offer(self, transfer_id: str) -> None:
        self.server.reject_transfer(transfer_id)
        self.refresh_offers_ui()

    def _dismiss_offer(self, transfer_id: str) -> None:
        self.server.pending_offers.pop(transfer_id, None)
        self.refresh_offers_ui()

    def _handle_disconnect(self) -> None:
        self.server.disconnect_peer()
        self.update_peer_status("Listening for Mobile...", "", 0, False)

    def _prompt_connect_peer(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Connect to Remote Device")
        dialog.geometry("340x220")
        dialog.configure(bg=COLOR_SURFACE_1)
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="Target Device IP Address:", bg=COLOR_SURFACE_1, fg=COLOR_TEXT_PRIMARY, font=FONT_SANS).pack(padx=16, pady=(16, 4), anchor="w")
        ip_entry = tk.Entry(dialog, bg=COLOR_SURFACE_0, fg=COLOR_TEXT_PRIMARY, insertbackground=COLOR_TEXT_PRIMARY, relief="flat", highlightbackground=COLOR_BORDER, highlightthickness=1, font=FONT_SANS)
        ip_entry.insert(0, self.peer_target if self.peer_target != "127.0.0.1" else "")
        ip_entry.pack(fill="x", padx=16, pady=(0, 8))

        tk.Label(dialog, text="Target Port (Mobile default: 58242):", bg=COLOR_SURFACE_1, fg=COLOR_TEXT_PRIMARY, font=FONT_SANS).pack(padx=16, pady=(0, 4), anchor="w")
        port_entry = tk.Entry(dialog, bg=COLOR_SURFACE_0, fg=COLOR_TEXT_PRIMARY, insertbackground=COLOR_TEXT_PRIMARY, relief="flat", highlightbackground=COLOR_BORDER, highlightthickness=1, font=FONT_SANS)
        port_entry.insert(0, "58242")
        port_entry.pack(fill="x", padx=16, pady=(0, 16))

        def on_connect_click():
            ip = ip_entry.get().strip()
            port = int(port_entry.get().strip()) if port_entry.get().strip().isdigit() else 58242
            if ip and self.on_connect_peer:
                self.on_connect_peer(ip, port)
            dialog.destroy()

        btn_row = tk.Frame(dialog, bg=COLOR_SURFACE_1)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))
        tk.Button(btn_row, text="Connect", bg=COLOR_ACCENT, fg="#FFFFFF", font=FONT_SANS_BOLD, relief="flat", padx=12, pady=4, command=on_connect_click).pack(side="right")
        tk.Button(btn_row, text="Cancel", bg=COLOR_SURFACE_2, fg=COLOR_TEXT_SECONDARY, font=FONT_SANS, relief="flat", padx=8, pady=4, command=dialog.destroy).pack(side="right", padx=(0, 8))

    def _process_event_queue(self) -> None:
        """Process thread-safe events on main Tkinter thread."""
        if not self.root or not self.root.winfo_exists():
            return
        try:
            while not self.event_queue.empty():
                event_type, data = self.event_queue.get_nowait()
                if event_type == "render_status":
                    self._render_status()
                elif event_type == "refresh_offers":
                    self.refresh_offers_ui()
                elif event_type == "restore":
                    self._restore()
                elif event_type == "progress":
                    transfer_id, received, total = data
                    self._apply_progress(transfer_id, received, total)
                elif event_type == "start_outgoing":
                    transfer_id, fname, fsize = data
                    self._ui_start_outgoing(transfer_id, fname, fsize)
                elif event_type == "files_dropped":
                    self.stage_files(data)
                elif event_type == "complete_outgoing":
                    transfer_id, fname, success, error = data
                    self._ui_complete_outgoing(transfer_id, fname, success, error)
        except Exception:
            pass
        if self.running and self.root and self.root.winfo_exists():
            self.root.after(30, self._process_event_queue)

    def update_progress(self, transfer_id: str, received: int, total: int) -> None:
        """Thread-safe queue dispatch for transfer progress."""
        self.event_queue.put(("progress", (transfer_id, received, total)))

    def start_outgoing_transfer(self, transfer_id: str, fname: str, fsize: int) -> None:
        """Thread-safe request to show outgoing stream progress bar."""
        self.event_queue.put(("start_outgoing", (transfer_id, fname, fsize)))

    def update_outgoing_progress(self, transfer_id: str, sent: int, total: int) -> None:
        """Thread-safe request to update outgoing progress bar."""
        self.event_queue.put(("progress", (transfer_id, sent, total)))

    def complete_outgoing_transfer(self, transfer_id: str, fname: str, success: bool, error: str = "") -> None:
        """Thread-safe request to mark outgoing stream complete or failed."""
        self.event_queue.put(("complete_outgoing", (transfer_id, fname, success, error)))

    def _ui_start_outgoing(self, transfer_id: str, fname: str, fsize: int) -> None:
        if not self.outgoing_frame or not self.root or not self.root.winfo_exists():
            return
        if self.transfers_card and self.transfers_card.winfo_exists():
            self.outgoing_frame.pack(before=self.transfers_card, fill="x", padx=10, pady=(0, 6))
        else:
            self.outgoing_frame.pack(fill="x", padx=10, pady=(0, 6))

        for child in self.outgoing_frame.winfo_children():
            child.destroy()

        header_row = tk.Frame(self.outgoing_frame, bg=COLOR_SURFACE_1)
        header_row.pack(fill="x", padx=8, pady=(4, 2))

        lbl = tk.Label(
            header_row,
            text=f"⬆️ Streaming to Phone: {fname} (0%)",
            bg=COLOR_SURFACE_1,
            fg=COLOR_ACCENT,
            font=FONT_SANS_BOLD,
            anchor="w"
        )
        lbl.fname = fname
        lbl.pack(side="left", fill="x", expand=True)
        self.outgoing_progress_labels[transfer_id] = lbl

        dismiss_mini = tk.Button(
            header_row,
            text="✕",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_SECONDARY,
            activebackground=COLOR_SURFACE_2,
            activeforeground="#FFFFFF",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            bd=0,
            cursor="hand2",
            padx=4,
            pady=0,
            command=self._dismiss_outgoing
        )
        dismiss_mini.pack(side="right")

        pbar = ttk.Progressbar(
            self.outgoing_frame,
            style="Custom.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100,
            value=0
        )
        pbar.pack(fill="x", padx=8, pady=(2, 6))
        self.outgoing_progress_bars[transfer_id] = pbar
        self.root.update_idletasks()

    def _ui_complete_outgoing(self, transfer_id: str, fname: str, success: bool, error: str = "") -> None:
        if not self.outgoing_frame or not self.root or not self.root.winfo_exists():
            return
        if self.transfers_card and self.transfers_card.winfo_exists():
            self.outgoing_frame.pack(before=self.transfers_card, fill="x", padx=10, pady=(0, 6))
        else:
            self.outgoing_frame.pack(fill="x", padx=10, pady=(0, 6))

        for child in self.outgoing_frame.winfo_children():
            child.destroy()

        header_row = tk.Frame(self.outgoing_frame, bg=COLOR_SURFACE_1)
        header_row.pack(fill="x", padx=8, pady=(4, 2))

        if success:
            lbl = tk.Label(
                header_row,
                text=f"✅ Sent to Phone: {fname} (SHA-256 Verified)",
                bg=COLOR_SURFACE_1,
                fg=COLOR_SUCCESS,
                font=FONT_SANS_BOLD,
                anchor="w"
            )
            lbl.pack(side="left", fill="x", expand=True)
        else:
            err_msg = f": {error}" if error else ""
            lbl = tk.Label(
                header_row,
                text=f"❌ Failed to stream {fname}{err_msg}",
                bg=COLOR_SURFACE_1,
                fg=COLOR_DANGER,
                font=FONT_SANS_BOLD,
                anchor="w"
            )
            lbl.pack(side="left", fill="x", expand=True)

        btn = tk.Button(
            header_row,
            text="✕ Dismiss",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_SECONDARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            cursor="hand2",
            padx=6,
            pady=1,
            command=self._dismiss_outgoing
        )
        btn.pack(side="right", padx=(4, 0))

        self.outgoing_progress_bars.pop(transfer_id, None)
        self.outgoing_progress_labels.pop(transfer_id, None)
        self.root.update_idletasks()

    def _dismiss_outgoing(self) -> None:
        if self.outgoing_frame and self.outgoing_frame.winfo_exists():
            for child in self.outgoing_frame.winfo_children():
                child.destroy()
            self.outgoing_frame.pack_forget()

    def _apply_progress(self, transfer_id: str, received: int, total: int) -> None:
        pct = int((received / total * 100)) if total > 0 else 0
        rec_mb = received / (1024 * 1024)
        tot_mb = total / (1024 * 1024)
        size_text = f"{rec_mb:.2f} / {tot_mb:.2f} MB ({pct}%)" if total > 1024*1024 else f"{received/1024:.1f} / {total/1024:.1f} KB ({pct}%)"

        # 1. Incoming transfer progress
        pbar = self.offer_progress_bars.get(transfer_id)
        if pbar and pbar.winfo_exists():
            pbar["value"] = pct
        lbl = self.offer_progress_labels.get(transfer_id)
        if lbl and lbl.winfo_exists():
            fname = getattr(lbl, "fname", "file")
            lbl.config(text=f"⬇️ Downloading: {fname} - {size_text}")

        # 2. Outgoing transfer progress
        out_pbar = self.outgoing_progress_bars.get(transfer_id)
        if out_pbar and out_pbar.winfo_exists():
            out_pbar["value"] = pct
        out_lbl = self.outgoing_progress_labels.get(transfer_id)
        if out_lbl and out_lbl.winfo_exists():
            fname = getattr(out_lbl, "fname", "file")
            out_lbl.config(text=f"⬆️ Streaming to Phone: {fname} - {size_text}")

        if self.root and self.root.winfo_exists():
            self.root.update_idletasks()

    def _on_timer_tick(self) -> None:
        """Tick countdowns without destroying frames and jumping scrollbar."""
        if not self.root or not self.root.winfo_exists():
            return
        if self.server and self.server.pending_offers:
            current_signature = "|".join(f"{t.transfer_id}:{t.state}:{getattr(t, 'copied', False)}" for t in self.server.pending_offers.values())
            if current_signature != self.last_offers_signature:
                self.last_offers_signature = current_signature
                self.refresh_offers_ui()
            else:
                # Update countdown labels in-place without rebuilding frames or jumping scrollbar!
                for tid, lbl in list(self.offer_timer_labels.items()):
                    if tid in self.server.pending_offers:
                        offer = self.server.pending_offers[tid]
                        ttl_left = offer.remaining_ttl()
                        mins, secs = divmod(ttl_left, 60)
                        ttl_str = f"{mins:02d}:{secs:02d}"
                        timer_color = COLOR_WARNING if ttl_left < 60 else COLOR_TEXT_SECONDARY
                        prefix = "Direct Stream  •  " if offer.msg_type != 2 else ""
                        try:
                            lbl.config(text=f"{prefix}Expires in: {ttl_str}", fg=timer_color)
                        except Exception:
                            pass

                # In-place fallback update for downloading progress bars
                for tid, pbar in list(self.offer_progress_bars.items()):
                    if tid in self.server.pending_offers:
                        offer = self.server.pending_offers[tid]
                        pct = int(offer.progress * 100)
                        try:
                            if pbar.winfo_exists():
                                pbar["value"] = pct
                            lbl = self.offer_progress_labels.get(tid)
                            if lbl and lbl.winfo_exists():
                                fname = getattr(lbl, "fname", "file")
                                rec_mb = offer.bytes_transferred / (1024 * 1024)
                                tot = offer.metadata.get("size", 0)
                                tot_mb = tot / (1024 * 1024)
                                size_text = f"{rec_mb:.2f} / {tot_mb:.2f} MB ({pct}%)" if tot > 1024*1024 else f"{offer.bytes_transferred/1024:.1f} / {tot/1024:.1f} KB ({pct}%)"
                                lbl.config(text=f"⬇️ Downloading: {fname} - {size_text}")
                        except Exception:
                            pass
        else:
            if self.last_offers_signature != "":
                self.last_offers_signature = ""
                self.refresh_offers_ui()

        if self.running and self.root and self.root.winfo_exists():
            self.root.after(1000, self._on_timer_tick)
