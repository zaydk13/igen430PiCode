import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import serial
import serial.tools.list_ports


# ---------------------------
# HMI theme
# ---------------------------
BG = "#1E1E1E"
PANEL_BG = "#2A2A2A"
FG = "#F5F5F5"

ENTRY_BG = "#F2F2F2"
ENTRY_FG = "#111111"

CONSOLE_BG = "#111111"
CONSOLE_FG = "#F5F5F5"

BTN_NEUTRAL = "#D9D9D9"
BTN_NEUTRAL_FG = "#111111"
BTN_BLUE = "#4EA1FF"
BTN_BLUE_FG = "#111111"
BTN_GREEN = "#5FD16F"
BTN_GREEN_FG = "#111111"
BTN_YELLOW = "#FFD54A"
BTN_YELLOW_FG = "#111111"
BTN_ORANGE = "#FFB347"
BTN_ORANGE_FG = "#111111"
BTN_RED = "#FF6B6B"
BTN_RED_FG = "#111111"

BTN_PRESSED = "#B8B8B8"


# ---------------------------
# Machine commands
# ---------------------------
LIGHT_ON_CMD = "M8"      # coolant on = light on
LIGHT_OFF_CMD = "M9"     # coolant off = light off
SPINDLE_OFF_CMD = "M5"
DEFAULT_SPINDLE_SPEED = "12000"


class GrblHALController:
    def __init__(self):
        self.ser = None
        self.read_thread = None
        self.read_running = False
        self.rx_queue = queue.Queue()
        self.lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def connect(self, port: str, baudrate: int = 115200, timeout: float = 0.05) -> None:
        self.disconnect()
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.0)
        self.read_running = True
        self.read_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self.read_thread.start()

        self.write_raw("\r\n\r\n")
        time.sleep(0.2)
        self.flush_input()

    def disconnect(self) -> None:
        self.read_running = False
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=0.5)
        self.read_thread = None

        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None

    def flush_input(self) -> None:
        if self.is_connected:
            with self.lock:
                self.ser.reset_input_buffer()

    def write_line(self, line: str) -> None:
        if not self.is_connected:
            return
        if not line.endswith("\n"):
            line += "\n"
        with self.lock:
            self.ser.write(line.encode("ascii", errors="ignore"))

    def write_raw(self, text: str) -> None:
        if not self.is_connected:
            return
        with self.lock:
            self.ser.write(text.encode("ascii", errors="ignore"))

    def send_realtime(self, cmd: bytes) -> None:
        if not self.is_connected:
            return
        with self.lock:
            self.ser.write(cmd)

    def get_rx_lines(self) -> list[str]:
        lines = []
        while True:
            try:
                lines.append(self.rx_queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def _reader_loop(self) -> None:
        while self.read_running and self.is_connected:
            try:
                line = self.ser.readline()
                if line:
                    text = line.decode(errors="replace").strip()
                    if text:
                        self.rx_queue.put(text)
            except Exception as exc:
                self.rx_queue.put(f"[ERROR] Serial read failed: {exc}")
                break


class TouchUI(tk.Tk):
    POLL_MS = 200
    RX_PROCESS_MS = 50
    JOG_REPEAT_S = 0.12
    GCODE_ACK_TIMEOUT_S = 8.0

    def __init__(self):
        super().__init__()
        self.title("grblHAL Touch UI")
        self.geometry("1780x1080")
        self.minsize(1500, 920)
        self.configure(bg=BG)

        self.ctrl = GrblHALController()

        self.machine_state = "Disconnected"
        self.last_status = ""
        self.polling = False
        self.homed = False
        self.in_alarm = False

        self.waiting_for_ack = False
        self.last_controller_reply = None

        self.jogging = False
        self.jog_thread = None

        self.gcode_lines = []
        self.current_line_index = 0
        self.job_running = False
        self.job_paused = False
        self.job_stopping = False
        self.job_thread = None

        self.status_text = tk.StringVar(value="Disconnected")
        self.state_text = tk.StringVar(value="State: --")
        self.machine_pos_text = tk.StringVar(value="MPos: --")
        self.work_pos_text = tk.StringVar(value="WPos: --")
        self.job_progress_text = tk.StringVar(value="Job: idle")
        self.file_text = tk.StringVar(value="No file loaded")
        self.last_status_text = tk.StringVar(value="Last status: --")

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")

        self.jog_step_var = tk.StringVar(value="1.0")
        self.jog_feed_var = tk.StringVar(value="1000")

        self.a_rot_step_var = tk.StringVar(value="5.0")
        self.a_rot_feed_var = tk.StringVar(value="300")
        self.b_rot_step_var = tk.StringVar(value="5.0")
        self.b_rot_feed_var = tk.StringVar(value="300")
        self.c_rot_step_var = tk.StringVar(value="5.0")
        self.c_rot_feed_var = tk.StringVar(value="300")

        self.mdi_var = tk.StringVar()
        self.spindle_speed_var = tk.StringVar(value=DEFAULT_SPINDLE_SPEED)

        self._build_ui()
        self._refresh_ports()
        self.after(self.RX_PROCESS_MS, self._process_rx)
        self.after(self.POLL_MS, self._status_poll_loop)

    # ---------------------------
    # UI BUILD
    # ---------------------------
    def _build_ui(self) -> None:
        default_font = ("Arial", 14, "bold")

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel", font=default_font, background=BG, foreground=FG)
        style.configure("TButton", font=default_font, padding=10)
        style.configure("TEntry", font=default_font, fieldbackground=ENTRY_BG, foreground=ENTRY_FG)
        style.configure("TCombobox", font=default_font, fieldbackground=ENTRY_BG, background=ENTRY_BG, foreground=ENTRY_FG)

        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 8), font=default_font)
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL_BG), ("!selected", BTN_NEUTRAL)],
            foreground=[("selected", FG), ("!selected", "#111111")]
        )

        # Shared top controls
        self._build_header()

        # Notebook / tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.manual_tab = tk.Frame(self.notebook, bg=BG)
        self.run_tab = tk.Frame(self.notebook, bg=BG)
        self.setup_tab = tk.Frame(self.notebook, bg=BG)
        self.diagnostics_tab = tk.Frame(self.notebook, bg=BG)

        self.notebook.add(self.manual_tab, text="Manual")
        self.notebook.add(self.run_tab, text="Run")
        self.notebook.add(self.setup_tab, text="Setup")
        self.notebook.add(self.diagnostics_tab, text="Diagnostics")

        self._build_manual_tab(self.manual_tab)
        self._build_run_tab(self.run_tab)
        self._build_setup_tab(self.setup_tab)
        self._build_diagnostics_tab(self.diagnostics_tab)

    def _build_header(self) -> None:
        default_font = ("Arial", 14, "bold")
        big_font = ("Arial", 24, "bold")

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=10, pady=10)

        tk.Label(top, text="Port", bg=BG, fg=FG, font=default_font).pack(side="left", padx=5)
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=20, state="readonly")
        self.port_combo.pack(side="left", padx=5)

        tk.Button(
            top, text="Refresh", command=self._refresh_ports,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=8, bd=3, relief="raised"
        ).pack(side="left", padx=5)

        tk.Label(top, text="Baud", bg=BG, fg=FG, font=default_font).pack(side="left", padx=5)
        ttk.Entry(top, textvariable=self.baud_var, width=9).pack(side="left", padx=5)

        tk.Button(
            top, text="Connect", command=self._connect,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=8, bd=3, relief="raised"
        ).pack(side="left", padx=5)

        tk.Button(
            top, text="Disconnect", command=self._disconnect,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font, width=9, bd=3, relief="raised"
        ).pack(side="left", padx=5)

        status_frame = tk.Frame(self, bg=BG)
        status_frame.pack(fill="x", padx=10, pady=(0, 6))

        tk.Label(status_frame, textvariable=self.status_text, bg=BG, fg=FG,
                 font=big_font).pack(anchor="w")
        tk.Label(status_frame, textvariable=self.state_text, bg=BG, fg=FG,
                 font=default_font).pack(anchor="w")
        tk.Label(status_frame, textvariable=self.machine_pos_text, bg=BG, fg=FG,
                 font=default_font).pack(anchor="w")
        tk.Label(status_frame, textvariable=self.work_pos_text, bg=BG, fg=FG,
                 font=default_font).pack(anchor="w")
        tk.Label(status_frame, textvariable=self.job_progress_text, bg=BG, fg=BTN_GREEN,
                 font=default_font).pack(anchor="w", pady=(3, 0))

    def _build_manual_tab(self, parent) -> None:
        default_font = ("Arial", 14, "bold")
        button_font = ("Arial", 18, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(main, bg=BG, width=340)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        center = tk.Frame(main, bg=BG)
        center.pack(side="left", fill="both", expand=True)
        center.pack_propagate(False)

        # Left
        settings_box = tk.LabelFrame(left, text="Jog Settings XYZ", bg=PANEL_BG, fg=FG,
                                     font=default_font, padx=10, pady=8, bd=3, relief="solid")
        settings_box.pack(fill="x", pady=(0, 6))

        tk.Label(settings_box, text="Step (mm)", bg=PANEL_BG, fg=FG, font=default_font).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(settings_box, textvariable=self.jog_step_var, width=8).grid(row=0, column=1, pady=4, padx=(8, 0))
        tk.Label(settings_box, text="Feed (mm/min)", bg=PANEL_BG, fg=FG, font=default_font).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(settings_box, textvariable=self.jog_feed_var, width=8).grid(row=1, column=1, pady=4, padx=(8, 0))

        rotary_box = tk.LabelFrame(left, text="Jog Settings A/B/C", bg=PANEL_BG, fg=FG,
                                   font=default_font, padx=10, pady=8, bd=3, relief="solid")
        rotary_box.pack(fill="x", pady=(0, 6))

        tk.Label(rotary_box, text="A Step (deg)", bg=PANEL_BG, fg=FG, font=default_font).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.a_rot_step_var, width=8).grid(row=0, column=1, pady=4, padx=(8, 0))
        tk.Label(rotary_box, text="A Feed", bg=PANEL_BG, fg=FG, font=default_font).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.a_rot_feed_var, width=8).grid(row=1, column=1, pady=4, padx=(8, 0))

        tk.Label(rotary_box, text="B Step (deg)", bg=PANEL_BG, fg=FG, font=default_font).grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.b_rot_step_var, width=8).grid(row=2, column=1, pady=4, padx=(8, 0))
        tk.Label(rotary_box, text="B Feed", bg=PANEL_BG, fg=FG, font=default_font).grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.b_rot_feed_var, width=8).grid(row=3, column=1, pady=4, padx=(8, 0))

        tk.Label(rotary_box, text="C Step (deg)", bg=PANEL_BG, fg=FG, font=default_font).grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.c_rot_step_var, width=8).grid(row=4, column=1, pady=4, padx=(8, 0))
        tk.Label(rotary_box, text="C Feed", bg=PANEL_BG, fg=FG, font=default_font).grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(rotary_box, textvariable=self.c_rot_feed_var, width=8).grid(row=5, column=1, pady=4, padx=(8, 0))

        # Center
        jog_box = tk.LabelFrame(center, text="Jog", bg=PANEL_BG, fg=FG,
                                font=default_font, padx=10, pady=8, bd=3, relief="solid")
        jog_box.pack(anchor="n", fill="x", expand=False)

        self.jog_buttons = []

        def make_jog_button(parent_widget, text, axis_moves, row, col):
            btn = tk.Button(
                parent_widget,
                text=text,
                font=button_font,
                width=3,
                height=2,
                bg=BTN_NEUTRAL,
                fg=BTN_NEUTRAL_FG,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                bd=4,
                relief="raised"
            )
            btn.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            btn.bind("<ButtonPress-1>", lambda _e, a=axis_moves, b=btn: self._on_jog_press(a, b))
            btn.bind("<ButtonRelease-1>", lambda _e, b=btn: self._on_jog_release(b))
            self.jog_buttons.append(btn)
            return btn

        for c in range(7):
            jog_box.grid_columnconfigure(c, weight=1, minsize=78)
        for r in range(3):
            jog_box.grid_rowconfigure(r, weight=0, minsize=78)

        make_jog_button(jog_box, "Y+", {"Y": 1}, 0, 1)
        make_jog_button(jog_box, "X-", {"X": -1}, 1, 0)
        make_jog_button(jog_box, "X+", {"X": 1}, 1, 2)
        make_jog_button(jog_box, "Y-", {"Y": -1}, 2, 1)

        make_jog_button(jog_box, "Z+", {"Z": 1}, 0, 3)
        make_jog_button(jog_box, "Z-", {"Z": -1}, 1, 3)

        make_jog_button(jog_box, "A+", {"A": 1}, 0, 4)
        make_jog_button(jog_box, "A-", {"A": -1}, 1, 4)

        make_jog_button(jog_box, "B+", {"B": 1}, 0, 5)
        make_jog_button(jog_box, "B-", {"B": -1}, 1, 5)

        make_jog_button(jog_box, "C+", {"C": 1}, 0, 6)
        make_jog_button(jog_box, "C-", {"C": -1}, 1, 6)

        outputs_box = tk.LabelFrame(center, text="Outputs", bg=PANEL_BG, fg=BTN_YELLOW,
                                    font=default_font, padx=10, pady=8, bd=3, relief="solid")
        outputs_box.pack(anchor="n", fill="x", pady=(10, 0))

        outputs_box.grid_columnconfigure(0, weight=1)
        outputs_box.grid_columnconfigure(1, weight=1)

        tk.Button(
            outputs_box, text="Light ON", command=self._light_on,
            bg=BTN_YELLOW, fg=BTN_YELLOW_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        tk.Button(
            outputs_box, text="Light OFF", command=self._light_off,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=0, column=1, padx=4, pady=4, sticky="ew")

        tk.Label(outputs_box, text="Spindle RPM", bg=PANEL_BG, fg=FG, font=default_font).grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        ttk.Entry(outputs_box, textvariable=self.spindle_speed_var, width=10).grid(
            row=1, column=1, padx=4, pady=4, sticky="ew"
        )

        tk.Button(
            outputs_box, text="Spindle ON", command=self._spindle_on,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=2, column=0, padx=4, pady=4, sticky="ew")

        tk.Button(
            outputs_box, text="Spindle OFF", command=self._spindle_off,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED,
            activeforeground="#000000", font=default_font,
            width=10, height=1, bd=3, relief="raised"
        ).grid(row=2, column=1, padx=4, pady=4, sticky="ew")

    def _build_run_tab(self, parent) -> None:
        default_font = ("Arial", 14, "bold")
        small_font = ("Courier", 12)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        job_box = tk.LabelFrame(main, text="G-code Job", bg=PANEL_BG, fg=FG,
                                font=default_font, padx=10, pady=8, bd=3, relief="solid")
        job_box.pack(fill="x", pady=(0, 8))

        tk.Label(job_box, textvariable=self.file_text, bg=PANEL_BG, fg=FG,
                 font=default_font, anchor="w", justify="left", wraplength=800).pack(fill="x", pady=(0, 6))

        job_btns = tk.Frame(job_box, bg=PANEL_BG)
        job_btns.pack(fill="x")

        tk.Button(
            job_btns, text="Load File", command=self._load_gcode_file,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=default_font, width=10,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=0, padx=4, pady=4)

        tk.Button(
            job_btns, text="Run", command=self._start_gcode_job,
            bg=BTN_GREEN, fg=BTN_GREEN_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=1, padx=4, pady=4)

        tk.Button(
            job_btns, text="Pause", command=self._pause_gcode_job,
            bg=BTN_ORANGE, fg=BTN_ORANGE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=2, padx=4, pady=4)

        tk.Button(
            job_btns, text="Resume", command=self._resume_gcode_job,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=3, padx=4, pady=4)

        tk.Button(
            job_btns, text="Stop", command=self._stop_gcode_job,
            bg=BTN_RED, fg=BTN_RED_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).grid(row=0, column=4, padx=4, pady=4)

        mdi_box = tk.LabelFrame(main, text="MDI / Console", bg=PANEL_BG, fg=FG,
                                font=default_font, padx=10, pady=8, bd=3, relief="solid")
        mdi_box.pack(fill="both", expand=True)

        mdi_top = tk.Frame(mdi_box, bg=PANEL_BG)
        mdi_top.pack(fill="x", pady=(0, 8))

        ttk.Entry(mdi_top, textvariable=self.mdi_var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(
            mdi_top, text="Send", command=self._send_mdi,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, font=default_font, width=8,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).pack(side="left")

        self.console = tk.Text(
            mdi_box,
            font=small_font,
            bg=CONSOLE_BG,
            fg=CONSOLE_FG,
            insertbackground=FG,
            wrap="word",
            bd=3,
            relief="solid"
        )
        self.console.pack(fill="both", expand=True)

        tk.Button(
            mdi_box, text="Clear Console", command=self._clear_console,
            bg=BTN_NEUTRAL, fg=BTN_NEUTRAL_FG, font=default_font, width=12,
            activebackground=BTN_PRESSED, activeforeground="#000000", bd=3, relief="raised"
        ).pack(anchor="w", pady=(8, 0))

    def _build_setup_tab(self, parent) -> None:
        default_font = ("Arial", 14, "bold")

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        left = tk.Frame(main, bg=BG)
        left.pack(side="left", fill="y", padx=(0, 10))

        right = tk.Frame(main, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        ctrl_box = tk.LabelFrame(left, text="Machine Control", bg=PANEL_BG, fg=FG,
                                 font=default_font, padx=10, pady=8, bd=3, relief="solid")
        ctrl_box.pack(fill="x", pady=(0, 8))

        machine_buttons = [
            ("Home", self._home, BTN_BLUE, BTN_BLUE_FG),
            ("Unlock", self._unlock, BTN_YELLOW, BTN_YELLOW_FG),
            ("Hold", self._hold, BTN_ORANGE, BTN_ORANGE_FG),
            ("Resume", self._resume, BTN_GREEN, BTN_GREEN_FG),
            ("Reset", self._reset, BTN_RED, BTN_RED_FG),
        ]
        for i, (label, fn, color, fgcolor) in enumerate(machine_buttons):
            tk.Button(
                ctrl_box,
                text=label,
                command=fn,
                bg=color,
                fg=fgcolor,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                font=default_font,
                width=14,
                height=1,
                bd=3,
                relief="raised"
            ).grid(row=i, column=0, pady=2, sticky="ew")

        zero_box = tk.LabelFrame(right, text="Set Zero", bg=PANEL_BG, fg=FG,
                                 font=default_font, padx=10, pady=8, bd=3, relief="solid")
        zero_box.pack(fill="x", pady=(0, 8))

        zero_buttons = [
            ("Zero X", "G10 L20 P1 X0"),
            ("Zero Y", "G10 L20 P1 Y0"),
            ("Zero Z", "G10 L20 P1 Z0"),
            ("Zero A", "G10 L20 P1 A0"),
            ("Zero B", "G10 L20 P1 B0"),
            ("Zero C", "G10 L20 P1 C0"),
            ("Zero XYZ", "G10 L20 P1 X0 Y0 Z0"),
        ]
        for i, (label, cmd) in enumerate(zero_buttons):
            tk.Button(
                zero_box,
                text=label,
                command=lambda c=cmd: self._send_line(c),
                bg=BTN_NEUTRAL,
                fg=BTN_NEUTRAL_FG,
                activebackground=BTN_PRESSED,
                activeforeground="#000000",
                font=default_font,
                width=12,
                height=1,
                bd=3,
                relief="raised"
            ).grid(row=i // 2, column=i % 2, padx=4, pady=4, sticky="ew")

    def _build_diagnostics_tab(self, parent) -> None:
        default_font = ("Arial", 14, "bold")
        mono_font = ("Courier", 12)

        main = tk.Frame(parent, bg=BG)
        main.pack(fill="both", expand=True, padx=10, pady=8)

        info_box = tk.LabelFrame(main, text="Controller Status", bg=PANEL_BG, fg=FG,
                                 font=default_font, padx=10, pady=8, bd=3, relief="solid")
        info_box.pack(fill="x", pady=(0, 8))

        tk.Label(info_box, textvariable=self.state_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.machine_pos_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.work_pos_text, bg=PANEL_BG, fg=FG, font=default_font).pack(anchor="w", pady=2)
        tk.Label(info_box, textvariable=self.last_status_text, bg=PANEL_BG, fg=FG, font=mono_font, justify="left", wraplength=1400).pack(anchor="w", pady=4)

        btns = tk.Frame(info_box, bg=PANEL_BG)
        btns.pack(anchor="w", pady=(6, 0))

        tk.Button(
            btns, text="Poll Status", command=lambda: self.ctrl.send_realtime(b"?") if self.ctrl.is_connected else None,
            bg=BTN_BLUE, fg=BTN_BLUE_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            btns, text="Soft Reset", command=self._reset,
            bg=BTN_RED, fg=BTN_RED_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            btns, text="Unlock", command=self._unlock,
            bg=BTN_YELLOW, fg=BTN_YELLOW_FG, activebackground=BTN_PRESSED, activeforeground="#000000",
            font=default_font, width=10, bd=3, relief="raised"
        ).pack(side="left")

    # ---------------------------
    # UI helpers
    # ---------------------------
    def _append_console(self, text: str) -> None:
        self.console.insert("end", text + "\n")
        self.console.see("end")

    def _clear_console(self) -> None:
        self.console.delete("1.0", "end")

    # ---------------------------
    # Machine / serial actions
    # ---------------------------
    def _refresh_ports(self) -> None:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _connect(self) -> None:
        port = self.port_var.get().strip()
        baud = self.baud_var.get().strip()

        if not port:
            messagebox.showerror("Error", "Select a serial port.")
            return

        try:
            baud_int = int(baud)
        except ValueError:
            messagebox.showerror("Error", "Invalid baud rate.")
            return

        try:
            self.ctrl.connect(port, baud_int)
            self.polling = True
            self.in_alarm = False
            self.machine_state = "Unknown"
            self.status_text.set(f"Connected: {port} @ {baud_int}")
            self._append_console(f"> Connected to {port} @ {baud_int}")
            self.configure(bg=BG)
        except Exception as exc:
            messagebox.showerror("Connection Error", str(exc))

    def _disconnect(self) -> None:
        self._stop_all_motion_and_jobs()
        self.polling = False
        self.ctrl.disconnect()
        self.machine_state = "Disconnected"
        self.status_text.set("Disconnected")
        self.state_text.set("State: --")
        self.machine_pos_text.set("MPos: --")
        self.work_pos_text.set("WPos: --")
        self.job_progress_text.set("Job: idle")
        self.last_status_text.set("Last status: --")
        self._append_console("> Disconnected")
        self.configure(bg=BG)

    def _send_line(self, line: str) -> None:
        if not self.ctrl.is_connected:
            return
        self.ctrl.write_line(line)
        self._append_console(f">> {line}")

    def _send_mdi(self) -> None:
        line = self.mdi_var.get().strip()
        if not line:
            return
        if self.job_running:
            messagebox.showwarning("Busy", "Cannot send MDI while a job is running.")
            return
        self._send_line(line)
        self.mdi_var.set("")

    def _hold(self) -> None:
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"!")
            self._append_console(">> [HOLD] !")

    def _resume(self) -> None:
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"~")
            self._append_console(">> [RESUME] ~")

    def _reset(self) -> None:
        if self.ctrl.is_connected:
            self._stop_all_motion_and_jobs()
            self.ctrl.send_realtime(b"\x18")
            self._append_console(">> [RESET] Ctrl-X")

    def _home(self) -> None:
        if self.job_running:
            return
        self._send_line("$H")

    def _unlock(self) -> None:
        if self.job_running:
            return
        self._send_line("$X")
        self.in_alarm = False
        self.configure(bg=BG)

    def _light_on(self) -> None:
        if self.job_running:
            return
        self._send_line(LIGHT_ON_CMD)

    def _light_off(self) -> None:
        if self.job_running:
            return
        self._send_line(LIGHT_OFF_CMD)

    def _spindle_on(self) -> None:
        if self.job_running:
            return
        try:
            speed = int(float(self.spindle_speed_var.get()))
            if speed <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Spindle Error", "Enter a spindle speed > 0.")
            return
        self._send_line(f"M3 S{speed}")

    def _spindle_off(self) -> None:
        if self.job_running:
            return
        self._send_line(SPINDLE_OFF_CMD)

    # ---------------------------
    # Jog logic
    # ---------------------------
    def _safe_to_jog(self) -> bool:
        if not self.ctrl.is_connected:
            return False
        if self.job_running:
            return False
        if self.in_alarm:
            return False
        return self.machine_state in ("Idle", "Jog")

    def _get_jog_settings(self, axis_moves: dict[str, int]) -> tuple[float, float]:
        axes = set(axis_moves.keys())

        if axes == {"A"}:
            return float(self.a_rot_step_var.get()), float(self.a_rot_feed_var.get())
        if axes == {"B"}:
            return float(self.b_rot_step_var.get()), float(self.b_rot_feed_var.get())
        if axes == {"C"}:
            return float(self.c_rot_step_var.get()), float(self.c_rot_feed_var.get())

        return float(self.jog_step_var.get()), float(self.jog_feed_var.get())

    def _on_jog_press(self, axis_moves: dict[str, int], btn: tk.Button) -> None:
        btn.config(bg=BTN_PRESSED)
        self._start_continuous_jog(axis_moves)

    def _on_jog_release(self, btn: tk.Button) -> None:
        btn.config(bg=BTN_NEUTRAL)
        self._cancel_jog()

    def _start_continuous_jog(self, axis_moves: dict[str, int]) -> None:
        if not self._safe_to_jog():
            return
        if self.jogging:
            return

        try:
            step, feed = self._get_jog_settings(axis_moves)
        except ValueError:
            messagebox.showerror("Jog Error", "Invalid jog step or feed.")
            return

        if step <= 0 or feed <= 0:
            messagebox.showerror("Jog Error", "Jog step and feed must be > 0.")
            return

        self.jogging = True

        def jog_loop() -> None:
            while self.jogging and self.ctrl.is_connected:
                if not self._safe_to_jog():
                    break

                parts = []
                for axis, direction in axis_moves.items():
                    parts.append(f"{axis}{step * direction:.3f}")

                cmd = f"$J=G91 {' '.join(parts)} F{feed:.1f}"
                self.ctrl.write_line(cmd)
                time.sleep(self.JOG_REPEAT_S)

        self.jog_thread = threading.Thread(target=jog_loop, daemon=True)
        self.jog_thread.start()

    def _cancel_jog(self) -> None:
        if not self.jogging:
            return
        self.jogging = False
        if self.ctrl.is_connected:
            self.ctrl.send_realtime(b"\x85")
            self._append_console(">> [JOG CANCEL] 0x85")

    # ---------------------------
    # G-code job logic
    # ---------------------------
    def _load_gcode_file(self) -> None:
        if self.job_running:
            return

        path = filedialog.askopenfilename(
            title="Open G-code File",
            filetypes=[
                ("G-code files", "*.nc *.gcode *.tap *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw_lines = f.readlines()

            cleaned = []
            for line in raw_lines:
                s = line.strip()
                if not s:
                    continue
                if ";" in s:
                    s = s.split(";", 1)[0].strip()
                if s.startswith("(") and s.endswith(")"):
                    continue
                if s:
                    cleaned.append(s)

            self.gcode_lines = cleaned
            self.current_line_index = 0
            self.file_text.set(os.path.basename(path))
            self.job_progress_text.set(f"Job: ready ({len(cleaned)} lines)")
            self._append_console(f"> Loaded G-code file: {path}")
            self._append_console(f"> {len(cleaned)} executable lines")
        except Exception as exc:
            messagebox.showerror("File Error", str(exc))

    def _can_run_job(self) -> bool:
        if not self.ctrl.is_connected:
            return False
        if self.job_running or self.jogging:
            return False
        if self.in_alarm:
            return False
        return self.machine_state == "Idle"

    def _start_gcode_job(self) -> None:
        if not self._can_run_job():
            messagebox.showerror("Run Error", "Machine must be connected, idle, and not in alarm.")
            return
        if not self.gcode_lines:
            messagebox.showerror("Run Error", "No G-code file loaded.")
            return

        self.job_running = True
        self.job_paused = False
        self.job_stopping = False
        self.waiting_for_ack = False
        self.last_controller_reply = None

        self.job_thread = threading.Thread(target=self._gcode_job_loop, daemon=True)
        self.job_thread.start()
        self._append_console("> Starting G-code job")

    def _pause_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = True
        self.ctrl.send_realtime(b"!")
        self._append_console(">> [JOB HOLD] !")

    def _resume_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_paused = False
        self.ctrl.send_realtime(b"~")
        self._append_console(">> [JOB RESUME] ~")

    def _stop_gcode_job(self) -> None:
        if not self.job_running:
            return
        self.job_stopping = True
        self.job_paused = False
        self.ctrl.send_realtime(b"\x18")
        self._append_console(">> [JOB STOP] Ctrl-X")

    def _gcode_job_loop(self) -> None:
        try:
            total = len(self.gcode_lines)

            while self.current_line_index < total:
                if self.job_stopping:
                    self.job_progress_text.set("Job: stopped")
                    break

                if self.job_paused:
                    self.job_progress_text.set(f"Job: paused at line {self.current_line_index + 1}/{total}")
                    time.sleep(0.05)
                    continue

                line = self.gcode_lines[self.current_line_index].strip()
                if not line:
                    self.current_line_index += 1
                    continue

                pct = int(((self.current_line_index + 1) / total) * 100)
                self.job_progress_text.set(f"Job: line {self.current_line_index + 1}/{total} ({pct}%)")
                self.last_controller_reply = None
                self.waiting_for_ack = True

                self.ctrl.write_line(line)
                self._append_console(f">> [RUN {self.current_line_index + 1}/{total}] {line}")

                start = time.time()
                while self.waiting_for_ack:
                    if self.job_stopping:
                        break
                    if time.time() - start > self.GCODE_ACK_TIMEOUT_S:
                        self._append_console("[ERROR] Timed out waiting for controller reply")
                        self.job_stopping = True
                        break
                    time.sleep(0.01)

                if self.job_stopping:
                    self.job_progress_text.set("Job: stopped")
                    break

                if self.last_controller_reply == "ok":
                    self.current_line_index += 1
                    continue

                if isinstance(self.last_controller_reply, str):
                    if self.last_controller_reply.startswith("error:") or self.last_controller_reply.startswith("ALARM:"):
                        self._append_console(f"[JOB ABORTED] {self.last_controller_reply}")
                        self.job_progress_text.set("Job: aborted")
                        break

            if self.current_line_index >= total and not self.job_stopping:
                self.job_progress_text.set("Job: complete")
                self._append_console("> Job complete")

        finally:
            self.job_running = False
            self.job_paused = False
            self.job_stopping = False
            self.waiting_for_ack = False

    # ---------------------------
    # RX / status
    # ---------------------------
    def _status_poll_loop(self) -> None:
        if self.polling and self.ctrl.is_connected:
            try:
                self.ctrl.send_realtime(b"?")
            except Exception as exc:
                self._append_console(f"[ERROR] Status poll failed: {exc}")
        self.after(self.POLL_MS, self._status_poll_loop)

    def _process_rx(self) -> None:
        for line in self.ctrl.get_rx_lines():
            self._append_console(line)

            if line == "ok":
                self.last_controller_reply = "ok"
                self.waiting_for_ack = False

            elif line.startswith("error:"):
                self.last_controller_reply = line
                self.waiting_for_ack = False

            elif line.startswith("ALARM:"):
                self.last_controller_reply = line
                self.waiting_for_ack = False
                self.in_alarm = True
                self.machine_state = "Alarm"
                self.status_text.set("!!! ALARM !!!")
                self.state_text.set(f"State: {line}")
                self.job_progress_text.set("Job: alarm")

            elif line.startswith("<") and line.endswith(">"):
                self._parse_status(line)

            elif line.startswith("[ERROR]"):
                self.status_text.set("Connection error")

        self.after(self.RX_PROCESS_MS, self._process_rx)

    def _parse_status(self, line: str) -> None:
        self.last_status = line
        self.last_status_text.set(f"Last status: {line}")

        inner = line[1:-1]
        parts = inner.split("|")
        if not parts:
            return

        state = parts[0]
        self.machine_state = state
        self.state_text.set(f"State: {state}")

        if state.startswith("Alarm"):
            self.in_alarm = True
            self.status_text.set("!!! ALARM !!!")
        elif self.ctrl.is_connected:
            self.status_text.set("Connected")

        for part in parts[1:]:
            if ":" not in part:
                continue
            key, val = part.split(":", 1)
            if key == "MPos":
                self.machine_pos_text.set(f"MPos: {val}")
            elif key == "WPos":
                self.work_pos_text.set(f"WPos: {val}")

    def _stop_all_motion_and_jobs(self) -> None:
        self._cancel_jog()
        self.job_stopping = True
        self.job_paused = False

    def on_close(self) -> None:
        self._disconnect()
        self.destroy()


if __name__ == "__main__":
    app = TouchUI()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()