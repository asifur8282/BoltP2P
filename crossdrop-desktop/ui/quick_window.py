"""
CrossDrop Desktop Quick Window
Compact 460px x 600px utilitarian UI adhering strictly to design.md tokens:
- Engineered Dark palette (#0E1116, #161B22, #21262D, #30363D)
- 1px crisp mechanical borders
- Active 10-minute ephemeral RAM buffer list with live countdowns
- Non-blocking thread-safe event queue
- Quick Send controls (Push Clipboard, Stream File, Custom Text)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import queue
import time
import pyperclip
from typing import Optional, Callable

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


class QuickWindow:
    def __init__(
        self,
        server,
        discovery,
        on_send_text: Optional[Callable[[str], None]] = None,
        on_send_file: Optional[Callable[[str], None]] = None
    ):
        self.server = server
        self.discovery = discovery
        self.on_send_text = on_send_text
        self.on_send_file = on_send_file

        self.root: Optional[tk.Tk] = None
        self.status_label: Optional[tk.Label] = None
        self.text_input: Optional[tk.Text] = None
        self.offers_frame: Optional[tk.Frame] = None
        self.auto_accept_var: Optional[tk.BooleanVar] = None
        self.peer_target = "127.0.0.1"
        self.peer_port = 58241
        self.peer_name = "Listening for Mobile..."
        self.peer_connected = False
        self.running = True
        self.event_queue = queue.Queue()
        self.has_empty_placeholder = False

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
        self.root.title("CrossDrop [Desktop Daemon]")
        self.root.geometry("460x640")
        self.root.minsize(460, 600)
        self.root.configure(bg=COLOR_SURFACE_0)

        # Style configurations
        self._build_ui()

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
                text=f"● ONLINE  |  Connected to: {self.peer_name} ({self.peer_target})",
                fg=COLOR_SUCCESS
            )
        else:
            self.status_label.config(
                text=f"○ IDLE  |  LAN Service: {self.discovery.device_name} (Port {self.server.port})",
                fg=COLOR_TEXT_SECONDARY
            )

    def _build_ui(self) -> None:
        # 1. Status Bar Header
        header_frame = tk.Frame(self.root, bg=COLOR_SURFACE_1, height=36, highlightbackground=COLOR_BORDER, highlightthickness=1)
        header_frame.pack(fill="x", padx=10, pady=(10, 6))

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
        self.status_label.pack(fill="x")
        self._render_status()

        # 2. Quick Send Card
        send_card = tk.LabelFrame(
            self.root,
            text=" QUICK SEND ",
            bg=COLOR_SURFACE_1,
            fg=COLOR_TEXT_PRIMARY,
            font=FONT_HEADER,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            bd=0,
            padx=10,
            pady=8
        )
        send_card.pack(fill="x", padx=10, pady=6)

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
        self.text_input.pack(fill="x", pady=(0, 8))
        self.text_input.insert("1.0", "Paste or type text to push to phone...")
        self.text_input.bind("<FocusIn>", self._clear_placeholder)

        btn_row = tk.Frame(send_card, bg=COLOR_SURFACE_1)
        btn_row.pack(fill="x")

        push_btn = tk.Button(
            btn_row,
            text="Push Clipboard",
            bg=COLOR_ACCENT,
            fg="#FFFFFF",
            activebackground="#388BFD",
            activeforeground="#FFFFFF",
            font=FONT_SANS_BOLD,
            relief="flat",
            cursor="hand2",
            padx=10,
            pady=4,
            command=self._handle_push_clipboard
        )
        push_btn.pack(side="left", padx=(0, 6))

        send_text_btn = tk.Button(
            btn_row,
            text="Send Text",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_PRIMARY,
            activebackground=COLOR_BORDER,
            font=FONT_SANS,
            relief="flat",
            cursor="hand2",
            padx=8,
            pady=4,
            command=self._handle_send_custom_text
        )
        send_text_btn.pack(side="left", padx=(0, 6))

        file_btn = tk.Button(
            btn_row,
            text="Select & Stream File",
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
        file_btn.pack(side="right")

        # 3. Active / Recent Transfers (10m Ephemeral RAM Window)
        transfers_card = tk.LabelFrame(
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
        transfers_card.pack(fill="both", expand=True, padx=10, pady=6)

        # Canvas + Scrollbar for Offers List
        canvas = tk.Canvas(transfers_card, bg=COLOR_SURFACE_1, highlightthickness=0)
        scrollbar = ttk.Scrollbar(transfers_card, orient="vertical", command=canvas.yview)
        self.offers_frame = tk.Frame(canvas, bg=COLOR_SURFACE_1)

        self.offers_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.offers_frame, anchor="nw", width=416)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.refresh_offers_ui()

        # 4. Bottom Utility Bar
        bottom_bar = tk.Frame(self.root, bg=COLOR_SURFACE_1, height=36, highlightbackground=COLOR_BORDER, highlightthickness=1)
        bottom_bar.pack(fill="x", padx=10, pady=(6, 10))

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
        chk.pack(side="right", padx=8, pady=4)

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

    def _clear_placeholder(self, event) -> None:
        current = self.text_input.get("1.0", "end-1c").strip()
        if current == "Paste or type text to push to phone...":
            self.text_input.delete("1.0", "end")

    def _toggle_auto_accept(self) -> None:
        self.server.auto_accept_text = self.auto_accept_var.get()

    def _open_downloads_folder(self) -> None:
        import os
        os.startfile(self.server.save_dir)

    def _handle_push_clipboard(self) -> None:
        try:
            content = pyperclip.paste()
            if content and self.on_send_text:
                self.on_send_text(content)
        except Exception as e:
            messagebox.showerror("Clipboard Error", str(e))

    def _handle_send_custom_text(self) -> None:
        text = self.text_input.get("1.0", "end-1c").strip()
        if text and text != "Paste or type text to push to phone...":
            if self.on_send_text:
                self.on_send_text(text)
                self.text_input.delete("1.0", "end")

    def _handle_select_file(self) -> None:
        filename = filedialog.askopenfilename(title="Select File to Stream")
        if filename and self.on_send_file:
            self.on_send_file(filename)

    def refresh_offers_ui(self) -> None:
        """Re-render pending RAM transfer offers with remaining TTL."""
        if not self.offers_frame or not self.root or not self.root.winfo_exists():
            return

        offers = list(self.server.pending_offers.values()) if self.server else []

        if not offers:
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

        # If offers are present, rebuild frame
        self.has_empty_placeholder = False
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

                btn_f = tk.Frame(row, bg=COLOR_SURFACE_0)
                btn_f.pack(fill="x", padx=8, pady=(0, 6))

                tk.Button(
                    btn_f,
                    text="Copy to Clipboard",
                    bg=COLOR_ACCENT,
                    fg="#FFFFFF",
                    font=FONT_SANS,
                    relief="flat",
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
                    padx=6,
                    pady=2,
                    command=lambda tid=offer.transfer_id: self._reject_offer(tid)
                ).pack(side="left")

            else:  # FILE / IMAGE
                fname = offer.metadata.get("filename", "unknown.bin")
                fsize = offer.metadata.get("size", 0)
                size_str = f"{fsize / (1024*1024):.2f} MB" if fsize > 1024*1024 else f"{fsize / 1024:.1f} KB"

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
                    text="Reject",
                    bg=COLOR_SURFACE_2,
                    fg=COLOR_DANGER,
                    font=FONT_SANS,
                    relief="flat",
                    padx=6,
                    pady=2,
                    command=lambda tid=offer.transfer_id: self._reject_offer(tid)
                ).pack(side="left")

    def _copy_text(self, transfer_id: str) -> None:
        self.server.consume_text(transfer_id)
        self.refresh_offers_ui()

    def _accept_file(self, transfer_id: str) -> None:
        self.server.accept_transfer(transfer_id)
        self.refresh_offers_ui()

    def _reject_offer(self, transfer_id: str) -> None:
        self.server.reject_transfer(transfer_id)
        self.refresh_offers_ui()

    def _process_event_queue(self) -> None:
        """Process thread-safe events on main Tkinter thread."""
        if not self.root or not self.root.winfo_exists():
            return
        try:
            while not self.event_queue.empty():
                event_type, _ = self.event_queue.get_nowait()
                if event_type == "render_status":
                    self._render_status()
                elif event_type == "refresh_offers":
                    self.refresh_offers_ui()
                elif event_type == "restore":
                    self._restore()
        except Exception:
            pass
        if self.running and self.root and self.root.winfo_exists():
            self.root.after(50, self._process_event_queue)

    def _on_timer_tick(self) -> None:
        """Tick countdowns without background thread race conditions."""
        if not self.root or not self.root.winfo_exists():
            return
        # Only re-render if active offers exist to avoid unnecessary redraws
        if self.server and self.server.pending_offers:
            self.refresh_offers_ui()
        if self.running and self.root and self.root.winfo_exists():
            self.root.after(1000, self._on_timer_tick)
