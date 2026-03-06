from collections.abc import Callable

from desktop_app.overlay_event_buffer import OverlayEventBuffer
from desktop_app.overlay_formatting import format_connection_label, format_gear
from desktop_app.overlay_models import OverlaySettings, OverlayState
from desktop_app.overlay_resources import get_overlay_icon_path


class OverlayWindowService:
    """Standalone desktop overlay window with local settings dialog."""

    def __init__(
        self,
        settings: OverlaySettings,
        on_query: Callable[[str], None],
        on_talk_level_changed: Callable[[int], None],
        on_settings_saved: Callable[[OverlaySettings], OverlaySettings],
        on_close_requested: Callable[[], None],
    ):
        self._settings = settings
        self._state = OverlayState()
        self._event_buffer = OverlayEventBuffer(max_queue_size=300)
        self._last_talk_level_sent: int | None = None

        self._on_query = on_query
        self._on_talk_level_changed = on_talk_level_changed
        self._on_settings_saved = on_settings_saved
        self._on_close_requested = on_close_requested

        # Lazy import keeps the rest of the application runnable in non-GUI environments.
        import tkinter as tk

        self._tk = tk
        self._root: object | None = None
        self._status_label = None
        self._drag_origin_x = 0
        self._drag_origin_y = 0

        self._status_var = None
        self._speed_var = None
        self._gear_var = None
        self._lap_var = None
        self._sector_var = None
        self._message_var = None
        self._strategy_var = None
        self._talk_level_var = None
        self._query_var = None

    def enqueue_event(self, topic: str, payload: dict) -> None:
        self._event_buffer.push(topic, payload)

    def run(self) -> None:
        tk = self._tk
        root = tk.Tk()
        self._root = root
        self._status_var = tk.StringVar(master=root, value="CONNECTING...")
        self._speed_var = tk.StringVar(master=root, value="0")
        self._gear_var = tk.StringVar(master=root, value="N")
        self._lap_var = tk.StringVar(master=root, value="LAP 1")
        self._sector_var = tk.StringVar(master=root, value="SECTOR 1")
        self._message_var = tk.StringVar(
            master=root, value=self._state.latest_engineer_message
        )
        self._strategy_var = tk.StringVar(
            master=root, value=self._state.latest_strategy_message
        )
        self._talk_level_var = tk.IntVar(master=root, value=self._settings.default_talk_level)
        self._query_var = tk.StringVar(master=root)
        root.title("Race Engineer Overlay")
        root.configure(bg="#121417")
        root.geometry(
            f"{self._settings.width}x{self._settings.height}+{self._settings.x}+{self._settings.y}"
        )
        icon_path = get_overlay_icon_path()
        if icon_path is not None:
            try:
                root.iconbitmap(default=str(icon_path))
            except Exception:
                pass
        root.overrideredirect(True)
        root.attributes("-topmost", self._settings.always_on_top)
        root.attributes("-alpha", self._settings.opacity)
        root.protocol("WM_DELETE_WINDOW", self._request_close)

        font_small = ("Segoe UI", self._settings.font_size)
        font_big = ("Segoe UI Semibold", self._settings.font_size + 9)

        header = tk.Frame(root, bg="#0F1114", bd=1, relief="flat")
        header.pack(fill="x")
        header.bind("<ButtonPress-1>", self._on_drag_start)
        header.bind("<B1-Motion>", self._on_drag_move)

        tk.Label(
            header,
            text="RACE ENGINEER",
            fg="#E4E6EB",
            bg="#0F1114",
            font=("Segoe UI Bold", self._settings.font_size),
        ).pack(side="left", padx=8, pady=6)
        self._status_label = tk.Label(
            header,
            textvariable=self._status_var,
            fg="#7ED957",
            bg="#0F1114",
            font=("Consolas", self._settings.font_size),
        )
        self._status_label.pack(side="left", padx=8)
        tk.Button(
            header,
            text="SET",
            command=self._open_settings_window,
            fg="#DDE2E8",
            bg="#1D2128",
            activebackground="#2A303A",
            relief="flat",
            width=5,
        ).pack(side="right", padx=4, pady=4)
        tk.Button(
            header,
            text="X",
            command=self._request_close,
            fg="#DDE2E8",
            bg="#502125",
            activebackground="#692A30",
            relief="flat",
            width=3,
        ).pack(side="right", padx=(0, 6), pady=4)

        panel = tk.Frame(root, bg="#121417")
        panel.pack(fill="both", expand=True, padx=8, pady=8)

        metrics = tk.Frame(panel, bg="#121417")
        metrics.pack(fill="x")
        tk.Label(
            metrics,
            textvariable=self._speed_var,
            fg="#FFFFFF",
            bg="#121417",
            font=font_big,
        ).pack(side="left", padx=(0, 10))
        tk.Label(
            metrics,
            text="KM/H",
            fg="#96A0AD",
            bg="#121417",
            font=font_small,
        ).pack(side="left", padx=(0, 16))
        tk.Label(
            metrics,
            textvariable=self._gear_var,
            fg="#8BD3FF",
            bg="#121417",
            font=font_big,
        ).pack(side="left", padx=(0, 16))
        tk.Label(
            metrics,
            textvariable=self._lap_var,
            fg="#EDEFF3",
            bg="#121417",
            font=font_small,
        ).pack(side="left", padx=(0, 12))
        tk.Label(
            metrics,
            textvariable=self._sector_var,
            fg="#EDEFF3",
            bg="#121417",
            font=font_small,
        ).pack(side="left")

        tk.Label(
            panel,
            text="Engineer:",
            fg="#98A2B1",
            bg="#121417",
            font=("Segoe UI Bold", self._settings.font_size),
            anchor="w",
        ).pack(fill="x", pady=(8, 0))
        tk.Label(
            panel,
            textvariable=self._message_var,
            fg="#E6EBF2",
            bg="#121417",
            wraplength=self._settings.width - 30,
            justify="left",
            anchor="w",
            font=font_small,
        ).pack(fill="x", pady=(2, 0))

        tk.Label(
            panel,
            text="Strategy:",
            fg="#98A2B1",
            bg="#121417",
            font=("Segoe UI Bold", self._settings.font_size),
            anchor="w",
        ).pack(fill="x", pady=(8, 0))
        tk.Label(
            panel,
            textvariable=self._strategy_var,
            fg="#C8D2DE",
            bg="#121417",
            wraplength=self._settings.width - 30,
            justify="left",
            anchor="w",
            font=font_small,
        ).pack(fill="x", pady=(2, 0))

        controls = tk.Frame(panel, bg="#121417")
        controls.pack(fill="x", pady=(8, 0))
        query_entry = tk.Entry(
            controls,
            textvariable=self._query_var,
            fg="#E8EDF4",
            bg="#1A1F26",
            insertbackground="#E8EDF4",
            relief="flat",
            font=font_small,
        )
        query_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        query_entry.bind("<Return>", lambda _e: self._submit_query())
        tk.Button(
            controls,
            text="SEND",
            command=self._submit_query,
            fg="#0F1218",
            bg="#61A8FF",
            activebackground="#7AB6FF",
            relief="flat",
            width=7,
        ).pack(side="right")

        talk_frame = tk.Frame(panel, bg="#121417")
        talk_frame.pack(fill="x", pady=(8, 0))
        tk.Label(
            talk_frame,
            text="Talk",
            fg="#98A2B1",
            bg="#121417",
            font=font_small,
        ).pack(side="left")
        tk.Scale(
            talk_frame,
            from_=1,
            to=10,
            orient="horizontal",
            variable=self._talk_level_var,
            command=self._on_talk_level_scale,
            bg="#121417",
            fg="#E8EDF4",
            troughcolor="#202734",
            highlightthickness=0,
            length=max(150, self._settings.width // 2),
        ).pack(side="left", padx=(6, 0))

        self._last_talk_level_sent = self._talk_level_var.get()
        self._on_talk_level_changed(self._talk_level_var.get())
        self._apply_visibility()
        root.after(70, self._process_event_queue)
        root.mainloop()

    def request_close(self) -> None:
        if self._root is None:
            return
        self._root.after(0, self._root.destroy)

    def _process_event_queue(self) -> None:
        if self._root is None:
            return
        for topic, payload in self._event_buffer.pop_batch(limit=40):
            self._handle_event(topic, payload)
        self._root.after(70, self._process_event_queue)

    def _handle_event(self, topic: str, payload: dict) -> None:
        if (
            self._speed_var is None
            or self._gear_var is None
            or self._lap_var is None
            or self._sector_var is None
            or self._message_var is None
            or self._strategy_var is None
            or self._status_var is None
        ):
            return

        if topic == "telemetry_tick":
            self._state.speed = int(payload.get("speed", self._state.speed))
            self._state.gear = format_gear(payload.get("gear", self._state.gear))
            self._state.lap = int(payload.get("lap", self._state.lap))
            self._state.sector = int(payload.get("sector", self._state.sector))
            self._speed_var.set(str(self._state.speed))
            self._gear_var.set(self._state.gear)
            self._lap_var.set(f"LAP {self._state.lap}")
            self._sector_var.set(f"SECTOR {self._state.sector}")
            return

        if topic == "driving_insight":
            message = str(payload.get("message", "")).strip()
            if message:
                self._state.latest_engineer_message = message
                self._message_var.set(message)
            return

        if topic == "agent_status":
            message = str(payload.get("message", "")).strip()
            if message:
                self._state.latest_strategy_message = message
                self._strategy_var.set(message)
            return

        if topic == "telemetry_status":
            mode = str(payload.get("mode", self._state.telemetry_mode))
            status = str(payload.get("status", self._state.telemetry_status))
            self._state.telemetry_mode = mode
            self._state.telemetry_status = status
            self._status_var.set(format_connection_label(mode, status))
            color = "#7ED957" if status == "connected" else ("#FFB347" if status in {"listening", "starting", "running"} else "#FF6B6B")
            self._set_status_color(color)
            self._apply_visibility()
            return

        if topic == "overlay_connection":
            connected = bool(payload.get("connected"))
            if not connected:
                self._status_var.set("SERVER | DISCONNECTED")
                self._set_status_color("#FF6B6B")

    def _submit_query(self) -> None:
        if self._query_var is None:
            return
        text = self._query_var.get().strip()
        if not text:
            return
        self._on_query(text)
        self._query_var.set("")

    def _on_talk_level_scale(self, raw: str) -> None:
        try:
            level = int(float(raw))
        except (TypeError, ValueError):
            return
        if self._last_talk_level_sent == level:
            return
        self._last_talk_level_sent = level
        self._on_talk_level_changed(level)

    def _set_status_color(self, color: str) -> None:
        if self._status_label is None:
            return
        self._status_label.configure(fg=color)

    def _on_drag_start(self, event) -> None:
        self._drag_origin_x = event.x
        self._drag_origin_y = event.y

    def _on_drag_move(self, event) -> None:
        if self._root is None:
            return
        x = self._root.winfo_x() + event.x - self._drag_origin_x
        y = self._root.winfo_y() + event.y - self._drag_origin_y
        self._root.geometry(f"+{x}+{y}")

    def _open_settings_window(self) -> None:
        if self._root is None:
            return

        tk = self._tk
        top = tk.Toplevel(self._root)
        top.title("Overlay Settings")
        top.configure(bg="#171A20")
        top.attributes("-topmost", True)
        top.geometry("360x330")
        top.resizable(False, False)

        host_var = tk.StringVar(value=self._settings.server_host)
        port_var = tk.IntVar(value=self._settings.server_port)
        opacity_var = tk.DoubleVar(value=self._settings.opacity)
        font_var = tk.IntVar(value=self._settings.font_size)
        topmost_var = tk.BooleanVar(value=self._settings.always_on_top)
        connected_only_var = tk.BooleanVar(value=self._settings.show_only_when_connected)
        talk_level = 5 if self._talk_level_var is None else self._talk_level_var.get()
        talk_var = tk.IntVar(value=talk_level)

        def row(label: str, widget) -> None:
            frame = tk.Frame(top, bg="#171A20")
            frame.pack(fill="x", padx=12, pady=6)
            tk.Label(
                frame,
                text=label,
                fg="#D9DEE5",
                bg="#171A20",
                width=17,
                anchor="w",
            ).pack(side="left")
            widget.pack(side="right", fill="x", expand=True)

        row("Server Host", tk.Entry(top, textvariable=host_var))
        row("Server Port", tk.Entry(top, textvariable=port_var))
        row("Opacity", tk.Scale(top, from_=0.35, to=1.0, resolution=0.01, orient="horizontal", variable=opacity_var))
        row("Font Size", tk.Scale(top, from_=9, to=24, resolution=1, orient="horizontal", variable=font_var))
        row("Talk Level", tk.Scale(top, from_=1, to=10, resolution=1, orient="horizontal", variable=talk_var))

        toggles = tk.Frame(top, bg="#171A20")
        toggles.pack(fill="x", padx=12, pady=6)
        tk.Checkbutton(
            toggles,
            text="Always on top",
            variable=topmost_var,
            fg="#D9DEE5",
            bg="#171A20",
            selectcolor="#171A20",
        ).pack(anchor="w")
        tk.Checkbutton(
            toggles,
            text="Show only when telemetry connected",
            variable=connected_only_var,
            fg="#D9DEE5",
            bg="#171A20",
            selectcolor="#171A20",
        ).pack(anchor="w")

        buttons = tk.Frame(top, bg="#171A20")
        buttons.pack(fill="x", padx=12, pady=10)

        def save_and_close() -> None:
            if self._root is None:
                top.destroy()
                return

            updated = OverlaySettings(
                server_host=host_var.get().strip() or self._settings.server_host,
                server_port=port_var.get(),
                width=self._root.winfo_width(),
                height=self._root.winfo_height(),
                x=self._root.winfo_x(),
                y=self._root.winfo_y(),
                opacity=float(opacity_var.get()),
                font_size=int(font_var.get()),
                always_on_top=bool(topmost_var.get()),
                show_only_when_connected=bool(connected_only_var.get()),
                default_talk_level=int(talk_var.get()),
            )
            self._settings = self._on_settings_saved(updated)
            if self._talk_level_var is not None:
                self._talk_level_var.set(self._settings.default_talk_level)
            self._on_talk_level_changed(self._settings.default_talk_level)
            self._root.attributes("-topmost", self._settings.always_on_top)
            self._root.attributes("-alpha", self._settings.opacity)
            self._apply_visibility()
            top.destroy()

        tk.Button(
            buttons,
            text="Save",
            command=save_and_close,
            fg="#10141A",
            bg="#7CC3FF",
            relief="flat",
            width=10,
        ).pack(side="right")
        tk.Button(
            buttons,
            text="Cancel",
            command=top.destroy,
            fg="#E0E5EC",
            bg="#2A303A",
            relief="flat",
            width=10,
        ).pack(side="right", padx=(0, 8))

    def _apply_visibility(self) -> None:
        if self._root is None:
            return
        if (
            self._settings.show_only_when_connected
            and self._state.telemetry_status != "connected"
        ):
            self._root.withdraw()
            return
        self._root.deiconify()

    def _request_close(self) -> None:
        if self._root is not None:
            talk_level = (
                self._settings.default_talk_level
                if self._talk_level_var is None
                else self._talk_level_var.get()
            )
            self._settings = self._on_settings_saved(
                OverlaySettings(
                    server_host=self._settings.server_host,
                    server_port=self._settings.server_port,
                    width=self._root.winfo_width(),
                    height=self._root.winfo_height(),
                    x=self._root.winfo_x(),
                    y=self._root.winfo_y(),
                    opacity=self._settings.opacity,
                    font_size=self._settings.font_size,
                    always_on_top=self._settings.always_on_top,
                    show_only_when_connected=self._settings.show_only_when_connected,
                    default_talk_level=talk_level,
                )
            )
            self._root.destroy()
        self._event_buffer.clear()
        self._on_close_requested()
