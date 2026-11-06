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
import os
import json
import pyperclip
import qrcode
from PIL import Image, ImageTk
from typing import Optional, Callable, List, Any
from core.network_server import get_lan_ip

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
        self.outgoing_progress_bars: dict = {}
        self.outgoing_progress_labels: dict = {}
        self.last_offers_signature: str = ""

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
        self.root.geometry("460x720")
        self.root.minsize(460, 640)
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

        # 3. Quick Send Card
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
            text="Select & Stream Files",
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
        self.canvas = canvas
        scrollbar = ttk.Scrollbar(transfers_card, orient="vertical", command=canvas.yview)
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

        # 4. Bottom Utility Bar
        bottom_bar = tk.Frame(self.root, bg=COLOR_SURFACE_1, height=36, highlightbackground=COLOR_BORDER, highlightthickness=1)
        bottom_bar.pack(fill="x", padx=10, pady=(6, 10))

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

    def _clear_placeholder(self, event) -> None:
        current = self.text_input.get("1.0", "end-1c").strip()
        if current == "Paste or type text to push to phone...":
            self.text_input.delete("1.0", "end")

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
        filenames = filedialog.askopenfilenames(title="Select File(s) to Stream")
        if filenames:
            file_list = list(filenames)
            if self.on_send_files:
                self.on_send_files(file_list)
            elif self.on_send_file:
                for f in file_list:
                    self.on_send_file(f)

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
        self.server.consume_text(transfer_id)
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
        self.outgoing_frame.pack(fill="x", padx=10, pady=4)
        for child in self.outgoing_frame.winfo_children():
            child.destroy()

        size_str = f"{fsize / (1024*1024):.2f} MB" if fsize > 1024*1024 else f"{fsize / 1024:.1f} KB"
        lbl = tk.Label(
            self.outgoing_frame,
            text=f"⬆️ Streaming to Phone: {fname} (0%)",
            bg=COLOR_SURFACE_1,
            fg=COLOR_ACCENT,
            font=FONT_SANS_BOLD,
            anchor="w"
        )
        lbl.fname = fname
        lbl.pack(fill="x", padx=8, pady=(6, 2))
        self.outgoing_progress_labels[transfer_id] = lbl

        pbar = ttk.Progressbar(
            self.outgoing_frame,
            style="Custom.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate",
            maximum=100,
            value=0
        )
        pbar.pack(fill="x", padx=8, pady=(4, 8))
        self.outgoing_progress_bars[transfer_id] = pbar
        self.root.update_idletasks()

    def _ui_complete_outgoing(self, transfer_id: str, fname: str, success: bool, error: str = "") -> None:
        if not self.outgoing_frame or not self.root or not self.root.winfo_exists():
            return
        for child in self.outgoing_frame.winfo_children():
            child.destroy()

        if success:
            lbl = tk.Label(
                self.outgoing_frame,
                text=f"✅ Sent to Phone: {fname} (SHA-256 Verified)",
                bg=COLOR_SURFACE_1,
                fg=COLOR_SUCCESS,
                font=FONT_SANS_BOLD,
                anchor="w"
            )
            lbl.pack(fill="x", padx=8, pady=(6, 2))
        else:
            err_msg = f": {error}" if error else ""
            lbl = tk.Label(
                self.outgoing_frame,
                text=f"❌ Failed to stream {fname}{err_msg}",
                bg=COLOR_SURFACE_1,
                fg=COLOR_DANGER,
                font=FONT_SANS_BOLD,
                anchor="w"
            )
            lbl.pack(fill="x", padx=8, pady=(6, 2))

        btn = tk.Button(
            self.outgoing_frame,
            text="Dismiss",
            bg=COLOR_SURFACE_2,
            fg=COLOR_TEXT_SECONDARY,
            font=FONT_SANS,
            relief="flat",
            padx=6,
            pady=2,
            command=self._dismiss_outgoing
        )
        btn.pack(padx=8, pady=(2, 6), anchor="w")
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
            current_signature = "|".join(f"{t.transfer_id}:{t.state}" for t in self.server.pending_offers.values())
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
