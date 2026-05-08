#!/usr/bin/env python3
"""Desktop GUI for common Tailscale tasks on Linux.

This app wraps the `tailscale` CLI. It requires the Tailscale daemon to be
installed and running.
"""

from __future__ import annotations

import json
import queue
import shlex
import subprocess
import threading
import tkinter as tk
import shutil
import sys
import os
import fcntl
from pathlib import Path
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any

GTK_TRAY_SUPPORTED = False
Gtk = None
GLib = None
AppIndicator3 = None

try:
    import gi

    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    from gi.repository import GLib, Gtk

    GTK_TRAY_SUPPORTED = True
except Exception:
    GTK_TRAY_SUPPORTED = False

try:
    import pystray
    from PIL import Image, ImageDraw

    TRAY_SUPPORTED = True
    TRAY_IMPORT_ERROR = ""
except Exception:
    pystray = None
    Image = None
    ImageDraw = None
    TRAY_SUPPORTED = False
    TRAY_IMPORT_ERROR = "pystray is not installed"


@dataclass
class CommandResult:
    ok: bool
    command: list[str]
    stdout: str
    stderr: str
    returncode: int


class TailscaleCLI:
    """Small helper around the tailscale command."""

    binary = "tailscale"

    @staticmethod
    def _looks_like_permission_error(result: CommandResult) -> bool:
        text = f"{result.stderr}\n{result.stdout}".lower()
        permission_markers = [
            "access denied",
            "checkprefs access denied",
            "permission denied",
            "use 'sudo tailscale",
        ]
        return any(marker in text for marker in permission_markers)

    @staticmethod
    def _needs_privileges(args: list[str]) -> bool:
        if not args:
            return False
        privileged = {"up", "down", "set", "login", "logout", "switch", "funnel", "serve"}
        return args[0] in privileged

    @classmethod
    def run(cls, args: list[str], timeout: int = 30) -> CommandResult:
        cmd = [cls.binary, *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(
                ok=proc.returncode == 0,
                command=cmd,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                returncode=proc.returncode,
            )
        except FileNotFoundError:
            return CommandResult(
                ok=False,
                command=cmd,
                stdout="",
                stderr="tailscale binary not found in PATH.",
                returncode=127,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                ok=False,
                command=cmd,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds.",
                returncode=124,
            )

    @classmethod
    def run_with_privilege_fallback(cls, args: list[str], timeout: int = 30) -> CommandResult:
        result = cls.run(args, timeout=timeout)

        if result.ok:
            return result

        if not cls._needs_privileges(args):
            return result

        if not cls._looks_like_permission_error(result):
            return result

        pkexec_path = shutil.which("pkexec")
        if not pkexec_path:
            return result

        pkexec_cmd = [pkexec_path, cls.binary, *args]
        try:
            proc = subprocess.run(
                pkexec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return CommandResult(
                ok=proc.returncode == 0,
                command=pkexec_cmd,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                ok=False,
                command=pkexec_cmd,
                stdout="",
                stderr=f"Privileged command timed out after {timeout} seconds.",
                returncode=124,
            )

    @classmethod
    def status_json(cls) -> tuple[dict[str, Any] | None, CommandResult]:
        result = cls.run(["status", "--json"])
        if not result.ok:
            return None, result
        try:
            return json.loads(result.stdout), result
        except json.JSONDecodeError as exc:
            parse_error = CommandResult(
                ok=False,
                command=result.command,
                stdout=result.stdout,
                stderr=f"Failed to parse JSON: {exc}",
                returncode=1,
            )
            return None, parse_error


class App(tk.Tk):
    def __init__(self, start_minimized: bool = False) -> None:
        super().__init__()
        self.base_dir = Path(__file__).resolve().parent
        self.title("Tailscale GUI")
        self.geometry("420x560")
        self.minsize(360, 480)

        self._task_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._exit_node_values: dict[str, str] = {}
        self._button_icons: dict[str, tk.BitmapImage] = {}
        self._latest_backend_state = "Unknown"
        self._tray_icon = None
        self._tray_thread: threading.Thread | None = None
        self._gtk_indicator = None
        self._gtk_thread: threading.Thread | None = None
        self._gtk_main_started = False
        self._closing = False
        self._feedback_clear_job: str | None = None

        self._setup_theme()
        self._setup_window_icon()
        self._load_button_icons()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_window_close)
        self._setup_tray_icon()
        if start_minimized and TRAY_SUPPORTED:
            self.after(250, self._hide_window)
        self.after(100, self._process_queue)
        self.after(400, self.refresh_status)

    def _setup_theme(self) -> None:
        self.configure(background="#000000")
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame", background="#000000")
        style.configure("TLabel", background="#000000", foreground="#ffffff")
        style.configure(
            "TButton",
            background="#000000",
            foreground="#ffffff",
            bordercolor="#ffffff",
            lightcolor="#ffffff",
            darkcolor="#ffffff",
            padding=(6, 4),
            focusthickness=1,
            focuscolor="#ffffff",
        )
        style.map(
            "TButton",
            background=[("active", "#ffffff"), ("pressed", "#ffffff")],
            foreground=[("active", "#000000"), ("pressed", "#000000")],
        )

        style.configure(
            "TLabelframe",
            background="#000000",
            bordercolor="#ffffff",
            relief=tk.SOLID,
            borderwidth=1,
            padding=6,
        )
        style.configure("TLabelframe.Label", background="#000000", foreground="#ffffff")

        style.configure("TCheckbutton", background="#000000", foreground="#ffffff")
        style.map(
            "TCheckbutton",
            background=[("active", "#000000")],
            foreground=[("active", "#ffffff")],
        )

        style.configure(
            "TEntry",
            fieldbackground="#000000",
            foreground="#ffffff",
            bordercolor="#ffffff",
            lightcolor="#ffffff",
            darkcolor="#ffffff",
            insertcolor="#ffffff",
        )
        style.configure(
            "TCombobox",
            fieldbackground="#000000",
            foreground="#ffffff",
            background="#000000",
            arrowcolor="#ffffff",
            bordercolor="#ffffff",
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#000000"), ("disabled", "#111111")],
            foreground=[("readonly", "#ffffff"), ("disabled", "#777777")],
            selectbackground=[("readonly", "#000000")],
            selectforeground=[("readonly", "#ffffff")],
            background=[("readonly", "#000000")],
            arrowcolor=[("readonly", "#ffffff"), ("disabled", "#777777")],
        )

        style.configure("TNotebook", background="#000000", borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#121212",
            foreground="#ffffff",
            padding=(8, 4),
            borderwidth=1,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#000000"), ("active", "#1f1f1f")],
            foreground=[("selected", "#ffffff"), ("active", "#ffffff")],
        )

        style.configure(
            "Treeview",
            background="#000000",
            fieldbackground="#000000",
            foreground="#ffffff",
            bordercolor="#ffffff",
            rowheight=20,
        )
        style.map(
            "Treeview",
            background=[("selected", "#ffffff")],
            foreground=[("selected", "#000000")],
        )
        style.configure(
            "Treeview.Heading",
            background="#000000",
            foreground="#ffffff",
            relief=tk.FLAT,
            bordercolor="#ffffff",
            padding=(6, 5),
        )
        style.configure("StatusInfo.TLabel", background="#000000", foreground="#d9d9d9")
        style.configure("StatusSuccess.TLabel", background="#000000", foreground="#6dff6d")
        style.configure("StatusError.TLabel", background="#000000", foreground="#ff7070")

    def _setup_window_icon(self) -> None:
        # Try SVG logo first, fallback to XBM
        icon_path = self.base_dir / "assets" / "icons" / "logo.svg"
        if not icon_path.exists():
            icon_path = self.base_dir / "assets" / "icons" / "app.xbm"
        if icon_path.exists():
            try:
                if str(icon_path).endswith(".svg"):
                    # For SVG, convert to PhotoImage if PIL is available
                    if Image is not None:
                        from PIL import Image as PILImage
                        pil_img = PILImage.open(str(icon_path))
                        pil_img.thumbnail((256, 256), PILImage.Resampling.LANCZOS)
                        # Save as temporary PPM for Tkinter
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp:
                            pil_img.save(tmp.name, "PPM")
                            self.iconphoto(False, tk.PhotoImage(file=tmp.name))
                            import os as _os
                            _os.unlink(tmp.name)
                else:
                    self.iconbitmap(f"@{icon_path}")
            except (tk.TclError, Exception):
                pass

    def _load_button_icons(self) -> None:
        names = {
            "refresh": "refresh.xbm",
            "up": "up.xbm",
            "down": "down.xbm",
            "login": "login.xbm",
            "web": "web.xbm",
            "apply": "apply.xbm",
            "clear": "clear.xbm",
            "run": "run.xbm",
        }

        for key, filename in names.items():
            icon_path = self.base_dir / "assets" / "icons" / filename
            if not icon_path.exists():
                continue
            try:
                icon = tk.BitmapImage(file=f"@{icon_path}", foreground="#ffffff", background="#000000")
                self._button_icons[key] = icon
            except tk.TclError:
                continue

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=4)
        root.pack(fill=tk.BOTH, expand=True)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.dashboard_tab = ttk.Frame(self.notebook, padding=6)
        self.devices_tab = ttk.Frame(self.notebook, padding=6)
        self.commands_tab = ttk.Frame(self.notebook, padding=6)

        self.notebook.add(self.dashboard_tab, text="Dashboard")
        self.notebook.add(self.devices_tab, text="Devices")
        self.notebook.add(self.commands_tab, text="Advanced")

        self._build_dashboard_tab()
        self._build_devices_tab()
        self._build_commands_tab()

        self.feedback_var = tk.StringVar(value="Ready")
        self.feedback_label = ttk.Label(root, textvariable=self.feedback_var, style="StatusInfo.TLabel", anchor=tk.W)
        self.feedback_label.pack(fill=tk.X, pady=(4, 0))

    def _build_dashboard_tab(self) -> None:
        status_frame = ttk.LabelFrame(self.dashboard_tab, text="Current Status", padding=6)
        status_frame.pack(fill=tk.X)
        status_frame.columnconfigure(1, weight=1)

        self.backend_state_var = tk.StringVar(value="Unknown")
        self.self_dns_var = tk.StringVar(value="-")
        self.self_ip_var = tk.StringVar(value="-")
        self.tailnet_var = tk.StringVar(value="-")

        rows = [
            ("Backend state", self.backend_state_var),
            ("Device name", self.self_dns_var),
            ("Tailscale IP", self.self_ip_var),
            ("Tailnet", self.tailnet_var),
        ]

        for row_idx, (label, var) in enumerate(rows):
            ttk.Label(status_frame, text=f"{label}:", width=16).grid(
                row=row_idx,
                column=0,
                sticky=tk.W,
                padx=(0, 8),
                pady=1,
            )
            ttk.Label(status_frame, textvariable=var).grid(
                row=row_idx,
                column=1,
                sticky=tk.EW,
                pady=1,
            )

        action_frame = ttk.Frame(self.dashboard_tab, padding=(0, 5, 0, 5))
        action_frame.pack(fill=tk.X)

        action_top = ttk.Frame(action_frame)
        action_top.pack(fill=tk.X, pady=(0, 6))
        action_bottom = ttk.Frame(action_frame)
        action_bottom.pack(fill=tk.X, pady=(0, 4))
        action_tray = ttk.Frame(action_frame)
        action_tray.pack(fill=tk.X)

        ttk.Button(
            action_top,
            text=" Refresh",
            image=self._button_icons.get("refresh"),
            compound=tk.LEFT,
            command=self.refresh_status,
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            action_top,
            text=" Connect",
            image=self._button_icons.get("up"),
            compound=tk.LEFT,
            command=lambda: self.run_simple(["up"]),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            action_top,
            text=" Disconnect",
            image=self._button_icons.get("down"),
            compound=tk.LEFT,
            command=lambda: self.run_simple(["down"]),
        ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Button(
            action_bottom,
            text=" Login",
            image=self._button_icons.get("login"),
            compound=tk.LEFT,
            command=lambda: self.run_simple(["login"]),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(
            action_bottom,
            text=" Admin Console",
            image=self._button_icons.get("web"),
            compound=tk.LEFT,
            command=lambda: self.run_simple(["web"]),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(action_tray, text="Minimize To Tray", command=self._hide_window).pack(side=tk.LEFT)

        exit_frame = ttk.LabelFrame(self.dashboard_tab, text="Exit Node", padding=6)
        exit_frame.pack(fill=tk.X)
        exit_frame.columnconfigure(1, weight=1)

        self.exit_node_var = tk.StringVar(value="")
        self.allow_lan_var = tk.BooleanVar(value=False)

        ttk.Label(exit_frame, text="Choose exit node:").grid(row=0, column=0, sticky=tk.W)
        self.exit_node_combo = ttk.Combobox(exit_frame, textvariable=self.exit_node_var, state="readonly")
        self.exit_node_combo.grid(row=0, column=1, sticky=tk.EW, padx=8)

        ttk.Checkbutton(
            exit_frame,
            text="Allow LAN access while using exit node",
            variable=self.allow_lan_var,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=8, pady=(8, 6))

        button_row = ttk.Frame(exit_frame)
        button_row.grid(row=2, column=0, columnspan=2, sticky=tk.EW)
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)
        ttk.Button(
            button_row,
            text=" Apply Exit Node",
            image=self._button_icons.get("apply"),
            compound=tk.LEFT,
            command=self.set_selected_exit_node,
        ).grid(row=0, column=0, sticky=tk.EW, padx=(0, 4))
        ttk.Button(
            button_row,
            text=" Disable Exit Node",
            image=self._button_icons.get("clear"),
            compound=tk.LEFT,
            command=self.disable_exit_node,
        ).grid(row=0, column=1, sticky=tk.EW, padx=(4, 0))

    def _build_devices_tab(self) -> None:
        controls = ttk.Frame(self.devices_tab)
        controls.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(
            controls,
            text=" Refresh Device List",
            image=self._button_icons.get("refresh"),
            compound=tk.LEFT,
            command=self.refresh_status,
        ).pack(side=tk.LEFT)

        columns = ("name", "ip", "os", "online", "exit")
        tree_wrap = ttk.Frame(self.devices_tab)
        tree_wrap.pack(fill=tk.BOTH, expand=True)

        self.devices_tree = ttk.Treeview(tree_wrap, columns=columns, show="headings", height=10)
        self.devices_tree.heading("name", text="Name")
        self.devices_tree.heading("ip", text="Tailscale IP")
        self.devices_tree.heading("os", text="OS")
        self.devices_tree.heading("online", text="Online")
        self.devices_tree.heading("exit", text="Exit Node Option")

        self.devices_tree.column("name", width=160)
        self.devices_tree.column("ip", width=110)
        self.devices_tree.column("os", width=70)
        self.devices_tree.column("online", width=60)
        self.devices_tree.column("exit", width=80)

        self.devices_tree.column("name", stretch=True)
        self.devices_tree.column("ip", stretch=True)
        self.devices_tree.column("os", stretch=False)
        self.devices_tree.column("online", stretch=False)
        self.devices_tree.column("exit", stretch=False)

        tree_scroll_y = ttk.Scrollbar(tree_wrap, orient=tk.VERTICAL, command=self.devices_tree.yview)
        tree_scroll_x = ttk.Scrollbar(tree_wrap, orient=tk.HORIZONTAL, command=self.devices_tree.xview)
        self.devices_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        self.devices_tree.grid(row=0, column=0, sticky=tk.NSEW)
        tree_scroll_y.grid(row=0, column=1, sticky=tk.NS)
        tree_scroll_x.grid(row=1, column=0, sticky=tk.EW)
        tree_wrap.columnconfigure(0, weight=1)
        tree_wrap.rowconfigure(0, weight=1)

    def _build_commands_tab(self) -> None:
        helper = ttk.Label(
            self.commands_tab,
            text="Run any tailscale CLI args here (example: set --accept-routes=true).",
        )
        helper.pack(anchor=tk.W, pady=(0, 4))

        entry_row = ttk.Frame(self.commands_tab)
        entry_row.pack(fill=tk.X)

        self.command_var = tk.StringVar(value="status")
        entry = ttk.Entry(entry_row, textvariable=self.command_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        entry.bind("<Return>", lambda _e: self.run_advanced())

        ttk.Button(
            entry_row,
            text=" Run",
            image=self._button_icons.get("run"),
            compound=tk.LEFT,
            command=self.run_advanced,
        ).pack(side=tk.LEFT)

        presets = ttk.Frame(self.commands_tab)
        presets.pack(fill=tk.X, pady=(4, 6))

        ttk.Label(presets, text="Quick commands:").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(presets, text="status", command=lambda: self._set_command("status")).pack(side=tk.LEFT, padx=3)
        ttk.Button(presets, text="status --json", command=lambda: self._set_command("status --json")).pack(
            side=tk.LEFT,
            padx=3,
        )
        ttk.Button(presets, text="netcheck", command=lambda: self._set_command("netcheck")).pack(side=tk.LEFT, padx=3)
        ttk.Button(presets, text="ip", command=lambda: self._set_command("ip")).pack(side=tk.LEFT, padx=3)

        output_frame = ttk.LabelFrame(self.commands_tab, text="Command Output", padding=6)
        output_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(
            output_frame,
            wrap=tk.WORD,
            height=10,
            bg="#000000",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.SOLID,
            borderwidth=1,
            padx=6,
            pady=6,
        )
        text_scroll = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=text_scroll.set)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _set_command(self, value: str) -> None:
        self.command_var.set(value)

    def _set_feedback(self, level: str, message: str, auto_reset: bool = True) -> None:
        if self._feedback_clear_job is not None:
            self.after_cancel(self._feedback_clear_job)
            self._feedback_clear_job = None

        style_name = "StatusInfo.TLabel"
        if level == "success":
            style_name = "StatusSuccess.TLabel"
        elif level == "error":
            style_name = "StatusError.TLabel"

        self.feedback_var.set(message)
        self.feedback_label.configure(style=style_name)

        if auto_reset:
            self._feedback_clear_job = self.after(9000, lambda: self._set_feedback("info", "Ready", auto_reset=False))

    def _format_action_name(self, args: list[str]) -> str:
        if not args:
            return "Command"

        cmd = args[0]
        if cmd == "up":
            return "Connect"
        if cmd == "down":
            return "Disconnect"
        if cmd == "login":
            return "Login"
        if cmd == "web":
            return "Open admin console"
        if cmd == "status":
            return "Refresh status"
        if cmd == "set":
            for arg in args[1:]:
                if arg == "--exit-node=":
                    return "Disable exit node"
                if arg.startswith("--exit-node="):
                    return "Set exit node"
            return "Update settings"
        return f"Run {' '.join(args)}"

    def _show_action_feedback(self, action_name: str, result: CommandResult) -> None:
        if result.ok:
            self._set_feedback("success", f"[OK] {action_name} succeeded")
            return

        details = result.stderr or result.stdout or f"exit code {result.returncode}"
        summary = details.splitlines()[0].strip()
        if len(summary) > 90:
            summary = summary[:87] + "..."
        self._set_feedback("error", f"[ERROR] {action_name} failed: {summary}")

    def _process_queue(self) -> None:
        while True:
            try:
                event, payload = self._task_queue.get_nowait()
            except queue.Empty:
                break

            if event == "command_result":
                if isinstance(payload, tuple):
                    result, action_name = payload
                else:
                    result = payload
                    args = result.command[1:] if len(result.command) > 1 else []
                    action_name = self._format_action_name(args)
                self._print_command_result(result)
                self._show_action_feedback(action_name, result)
            elif event == "status_loaded":
                status_data, command_result = payload
                self._apply_status(status_data)
                self._print_command_result(command_result)
            elif event == "error":
                messagebox.showerror("Tailscale GUI", payload)

        self.after(100, self._process_queue)

    def _run_background(self, callback, *args) -> None:
        def job() -> None:
            try:
                callback(*args)
            except Exception as exc:
                self._task_queue.put(("error", str(exc)))

        threading.Thread(target=job, daemon=True).start()

    def _print_command_result(self, result: CommandResult) -> None:
        self.output_text.delete("1.0", tk.END)
        command_line = " ".join(shlex.quote(c) for c in result.command)

        chunks = [
            f"$ {command_line}",
            f"exit code: {result.returncode}",
            "",
        ]
        if result.stdout:
            chunks.append("stdout:")
            chunks.append(result.stdout)
            chunks.append("")
        if result.stderr:
            chunks.append("stderr:")
            chunks.append(result.stderr)

        self.output_text.insert("1.0", "\n".join(chunks).strip() + "\n")

        if not result.ok and "permission" in result.stderr.lower():
            messagebox.showwarning(
                "Permission issue",
                "Tailscale command failed due to permissions. Run with appropriate privileges.",
            )

    def run_simple(self, args: list[str]) -> None:
        self._run_background(self._run_simple_bg, args)

    def _run_simple_bg(self, args: list[str]) -> None:
        result = TailscaleCLI.run_with_privilege_fallback(args)
        action_name = self._format_action_name(args)
        self._task_queue.put(("command_result", (result, action_name)))
        if result.ok and args and args[0] in {"up", "down", "login", "set"}:
            status_data, status_result = TailscaleCLI.status_json()
            if status_data is not None:
                self._task_queue.put(("status_loaded", (status_data, status_result)))

    def refresh_status(self) -> None:
        self._run_background(self._refresh_status_bg)

    def _refresh_status_bg(self) -> None:
        status_data, command_result = TailscaleCLI.status_json()
        if status_data is None:
            self._task_queue.put(("command_result", command_result))
            return
        self._task_queue.put(("status_loaded", (status_data, command_result)))

    def _apply_status(self, status_data: dict[str, Any]) -> None:
        backend_state = status_data.get("BackendState", "Unknown")
        self._latest_backend_state = backend_state
        self.backend_state_var.set(backend_state)

        self_info = status_data.get("Self", {})
        self.self_dns_var.set(self_info.get("DNSName", "-"))

        self_ips = self_info.get("TailscaleIPs", [])
        self.self_ip_var.set(self_ips[0] if self_ips else "-")

        current_tailnet = status_data.get("CurrentTailnet", {})
        self.tailnet_var.set(current_tailnet.get("Name", "-"))

        self._fill_devices(status_data)
        self._fill_exit_nodes(status_data)
        self._refresh_tray_menu()

    def _fill_devices(self, status_data: dict[str, Any]) -> None:
        for item in self.devices_tree.get_children(""):
            self.devices_tree.delete(item)

        peers = status_data.get("Peer", {})
        for peer in peers.values():
            name = (peer.get("DNSName", "") or "").rstrip(".") or "Unknown"
            ips = peer.get("TailscaleIPs", [])
            ip = ips[0] if ips else "-"
            os_name = peer.get("OS", "-")
            online = "Yes" if peer.get("Online") else "No"
            exit_opt = "Yes" if peer.get("ExitNodeOption") else "No"

            self.devices_tree.insert("", tk.END, values=(name, ip, os_name, online, exit_opt))

    def _fill_exit_nodes(self, status_data: dict[str, Any]) -> None:
        peers = status_data.get("Peer", {})
        candidates: dict[str, str] = {}

        for peer in peers.values():
            if not peer.get("ExitNodeOption"):
                continue
            name = (peer.get("DNSName", "") or "").rstrip(".") or "Unknown"
            ips = peer.get("TailscaleIPs", [])
            if not ips:
                continue
            candidates[f"{name} ({ips[0]})"] = ips[0]

        self._exit_node_values = candidates

        values = list(candidates.keys())
        self.exit_node_combo["values"] = values
        if values and not self.exit_node_var.get():
            self.exit_node_var.set(values[0])
        if not values:
            self.exit_node_var.set("")

    def set_selected_exit_node(self) -> None:
        selection = self.exit_node_var.get().strip()
        if not selection:
            self._set_feedback("error", "[ERROR] Set exit node failed: no exit node selected")
            messagebox.showinfo("Exit node", "No exit node is available in your tailnet.")
            return

        node_ip = self._exit_node_values.get(selection)
        if not node_ip:
            self._set_feedback("error", "[ERROR] Set exit node failed: selected node not found")
            messagebox.showerror("Exit node", "Could not resolve the selected exit node.")
            return

        args = ["set", f"--exit-node={node_ip}"]
        if self.allow_lan_var.get():
            args.append("--exit-node-allow-lan-access=true")

        self.run_simple(args)

    def disable_exit_node(self) -> None:
        self.run_simple(["set", "--exit-node="])

    def run_advanced(self) -> None:
        raw = self.command_var.get().strip()
        if not raw:
            self._set_feedback("error", "[ERROR] Advanced command failed: command is empty")
            return

        try:
            args = shlex.split(raw)
        except ValueError as exc:
            self._set_feedback("error", f"[ERROR] Advanced command parse failed: {exc}")
            messagebox.showerror("Invalid command", str(exc))
            return

        if not args:
            self._set_feedback("error", "[ERROR] Advanced command failed: no arguments")
            return

        self.run_simple(args)

    def _create_tray_image(self):
        if not TRAY_SUPPORTED:
            return None
        try:
            # Try to load logo.svg
            logo_path = self.base_dir / "assets" / "icons" / "logo.svg"
            if logo_path.exists():
                from PIL import Image as PILImage
                image = PILImage.open(str(logo_path)).convert("RGBA")
                image.thumbnail((64, 64), PILImage.Resampling.LANCZOS)
                # Ensure it's RGB for pystray
                rgb_image = PILImage.new("RGB", image.size, "white")
                rgb_image.paste(image, mask=image.split()[3] if len(image.split()) > 3 else None)
                return rgb_image
        except Exception:
            pass
        # Fallback: generate simple dot pattern
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((6, 6, 58, 58), outline="black", width=3)
        dots = [
            (20, 20),
            (32, 20),
            (44, 20),
            (20, 32),
            (32, 32),
            (44, 32),
        ]
        for x, y in dots:
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="black")
        draw.rectangle((18, 42, 46, 50), fill="black")
        return image

    def _setup_tray_icon(self) -> None:
        if GTK_TRAY_SUPPORTED:
            self._setup_gtk_indicator()
            return

        if not TRAY_SUPPORTED:
            return

        image = self._create_tray_image()
        if image is None:
            return

        self._tray_icon = pystray.Icon(
            "tailscale-gui",
            image,
            "Tailscale GUI",
            self._build_tray_menu(),
        )
        self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        self._tray_thread.start()

    def _build_tray_menu(self):
        if not TRAY_SUPPORTED or self._tray_icon is None:
            return None

        state_label = pystray.MenuItem(
            f"State: {self._latest_backend_state}",
            lambda _icon, _item: None,
            enabled=False,
        )

        exit_nodes: list[Any] = []
        for label, ip in sorted(self._exit_node_values.items()):
            exit_nodes.append(
                pystray.MenuItem(
                    label,
                    lambda _icon, _item, node_ip=ip: self.after(0, self.run_simple, ["set", f"--exit-node={node_ip}"]),
                )
            )

        if not exit_nodes:
            exit_nodes.append(
                pystray.MenuItem("No exit nodes available", lambda _icon, _item: None, enabled=False)
            )

        exit_nodes.append(
            pystray.MenuItem(
                "Disable Exit Node",
                lambda _icon, _item: self.after(0, self.disable_exit_node),
            )
        )

        return pystray.Menu(
            state_label,
            pystray.MenuItem(
                "Open Tailscale GUI",
                lambda _icon, _item: self.after(0, self._show_window),
                default=True,
            ),
            pystray.MenuItem("Show Window", lambda _icon, _item: self.after(0, self._show_window)),
            pystray.MenuItem("Hide Window", lambda _icon, _item: self.after(0, self._hide_window)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Connect", lambda _icon, _item: self.after(0, self.run_simple, ["up"])),
            pystray.MenuItem("Disconnect", lambda _icon, _item: self.after(0, self.run_simple, ["down"])),
            pystray.MenuItem("Refresh", lambda _icon, _item: self.after(0, self.refresh_status)),
            pystray.MenuItem("Exit Nodes", pystray.Menu(*exit_nodes)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _icon, _item: self.after(0, self._quit_application)),
        )

    def _refresh_tray_menu(self) -> None:
        if self._gtk_indicator is not None and GTK_TRAY_SUPPORTED:
            self._refresh_gtk_menu()
            return

        if not TRAY_SUPPORTED or self._tray_icon is None:
            return
        self._tray_icon.menu = self._build_tray_menu()
        try:
            self._tray_icon.update_menu()
        except Exception:
            pass

    def _setup_gtk_indicator(self) -> None:
        icon_path = str(self.base_dir / "assets" / "icons" / "logo.svg")

        def gtk_bootstrap() -> None:
            self._gtk_indicator = AppIndicator3.Indicator.new(
                "tailscale-gui",
                icon_path,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self._gtk_indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self._gtk_indicator.set_menu(self._build_gtk_menu())
            self._gtk_main_started = True
            Gtk.main()

        self._gtk_thread = threading.Thread(target=gtk_bootstrap, daemon=True)
        self._gtk_thread.start()

    def _build_gtk_menu(self):
        menu = Gtk.Menu()

        state_item = Gtk.MenuItem(label=f"State: {self._latest_backend_state}")
        state_item.set_sensitive(False)
        menu.append(state_item)

        menu.append(Gtk.SeparatorMenuItem())

        show_item = Gtk.MenuItem(label="Open Tailscale GUI")
        show_item.connect("activate", lambda _w: self.after(0, self._show_window))
        menu.append(show_item)

        hide_item = Gtk.MenuItem(label="Hide Window")
        hide_item.connect("activate", lambda _w: self.after(0, self._hide_window))
        menu.append(hide_item)

        menu.append(Gtk.SeparatorMenuItem())

        connect_item = Gtk.MenuItem(label="Connect")
        connect_item.connect("activate", lambda _w: self.after(0, self.run_simple, ["up"]))
        menu.append(connect_item)

        disconnect_item = Gtk.MenuItem(label="Disconnect")
        disconnect_item.connect("activate", lambda _w: self.after(0, self.run_simple, ["down"]))
        menu.append(disconnect_item)

        refresh_item = Gtk.MenuItem(label="Refresh")
        refresh_item.connect("activate", lambda _w: self.after(0, self.refresh_status))
        menu.append(refresh_item)

        exit_nodes_root = Gtk.MenuItem(label="Exit Nodes")
        exit_nodes_menu = Gtk.Menu()
        for label, ip in sorted(self._exit_node_values.items()):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _w, node_ip=ip: self.after(0, self.run_simple, ["set", f"--exit-node={node_ip}"]))
            exit_nodes_menu.append(item)

        if not self._exit_node_values:
            none_item = Gtk.MenuItem(label="No exit nodes available")
            none_item.set_sensitive(False)
            exit_nodes_menu.append(none_item)

        disable_item = Gtk.MenuItem(label="Disable Exit Node")
        disable_item.connect("activate", lambda _w: self.after(0, self.disable_exit_node))
        exit_nodes_menu.append(disable_item)

        exit_nodes_root.set_submenu(exit_nodes_menu)
        menu.append(exit_nodes_root)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _w: self.after(0, self._quit_application))
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _refresh_gtk_menu(self) -> None:
        if self._gtk_indicator is None or not GTK_TRAY_SUPPORTED:
            return

        GLib.idle_add(lambda: self._gtk_indicator.set_menu(self._build_gtk_menu()))

    def _hide_window(self) -> None:
        self.withdraw()

    def _show_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _on_window_close(self) -> None:
        if self._closing:
            return
        if self._gtk_indicator is not None or (TRAY_SUPPORTED and self._tray_icon is not None):
            self._hide_window()
            return
        self._quit_application()

    def _quit_application(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        if self._gtk_main_started and GTK_TRAY_SUPPORTED:
            try:
                GLib.idle_add(Gtk.main_quit)
            except Exception:
                pass
        self.destroy()


def main() -> None:
    lock_path = "/tmp/tailscale-gui.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Tailscale GUI is already running. Use the existing tray icon/window.")
        return

    start_minimized = "--tray" in sys.argv
    if start_minimized and not TRAY_SUPPORTED:
        print("Tray mode requested, but tray support is unavailable.")
        if TRAY_IMPORT_ERROR:
            print(f"Reason: {TRAY_IMPORT_ERROR}")
        print("Install dependencies and retry. On Debian/Ubuntu: sudo apt install python3-pystray")
    app = App(start_minimized=start_minimized)
    app.mainloop()


if __name__ == "__main__":
    main()
