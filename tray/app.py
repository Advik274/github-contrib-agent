import gc
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

from agent.config import AgentConfig
from agent.constants import STATUS_COLORS
from agent.core import ContributionJob
from agent.optimized import HibernatingAgent, OptimizedScheduler

logger = logging.getLogger(__name__)

DEFAULT_VETO_SECONDS = 300
MEMORY_CLEANUP_INTERVAL = 3600


def create_tray_icon(color: str = "#2ea44f") -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=_hex_to_rgb(color))
    draw.ellipse([22, 22, 42, 42], fill=(255, 255, 255, 255))
    return img


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


class ToastWindow:
    def __init__(
        self, job: ContributionJob, veto_seconds: int, on_auto_approve, on_reject
    ):
        self.job = job
        self.veto_seconds = veto_seconds
        self.remaining = veto_seconds
        self.on_auto_approve = on_auto_approve
        self.on_reject = on_reject
        self._resolved = False
        self.root = None
        self._job_dict = {
            "target": {
                "repo": {
                    "full_name": job.target.repo.full_name,
                    "name": job.target.repo.name,
                },
                "file": {"path": job.target.file.path, "name": job.target.file.name},
            },
            "contribution": {
                "commit_message": job.contribution.commit_message,
                "description": job.contribution.description,
                "improved_code": job.contribution.improved_code,
            },
        }

    def show(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#161b22")

        border = tk.Frame(self.root, bg="#30363d", padx=1, pady=1)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg="#161b22")
        inner.pack(fill="both", expand=True)

        w, h = 390, 140
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{sw - w - 16}+{sh - h - 62}")

        row1 = tk.Frame(inner, bg="#161b22")
        row1.pack(fill="x", padx=12, pady=(10, 0))

        tk.Label(
            row1, text="🤖", font=("Segoe UI", 13), bg="#161b22", fg="#e6edf3"
        ).pack(side="left")
        tk.Label(
            row1,
            text="  Auto-pushing in",
            font=("Segoe UI", 11, "bold"),
            bg="#161b22",
            fg="#e6edf3",
        ).pack(side="left")
        self.timer_label = tk.Label(
            row1,
            text=f"{self.veto_seconds}s",
            font=("Segoe UI", 11, "bold"),
            bg="#161b22",
            fg="#58a6ff",
        )
        self.timer_label.pack(side="right")

        msg = tk.Frame(inner, bg="#161b22")
        msg.pack(fill="x", padx=12)
        tk.Label(
            msg,
            text=f"📁 {self._job_dict['target']['repo']['name']}/{self._job_dict['target']['file']['path']}",
            font=("Segoe UI", 9),
            bg="#161b22",
            fg="#8b949e",
        ).pack(anchor="w")
        tk.Label(
            msg,
            text=f"📝 {self._job_dict['contribution']['commit_message']}",
            font=("Segoe UI", 9),
            bg="#161b22",
            fg="#79c0ff",
            wraplength=350,
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        buttons = tk.Frame(inner, bg="#161b22")
        buttons.pack(fill="x", padx=12, pady=(8, 10))

        def on_approve():
            if not self._resolved:
                self._resolved = True
                self.on_auto_approve(self.job)

        def on_reject():
            if not self._resolved:
                self._resolved = True
                self.on_reject()

        tk.Button(
            buttons,
            text="✅  Approve Now",
            font=("Segoe UI", 9, "bold"),
            bg="#238636",
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=on_approve,
            activebackground="#2ea043",
            bd=0,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="🔍  View Diff",
            font=("Segoe UI", 9),
            bg="#21262d",
            fg="#c9d1d9",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._open_diff,
            activebackground="#30363d",
            bd=0,
        ).pack(side="left", padx=(6, 0))
        tk.Button(
            buttons,
            text="✕  Reject",
            font=("Segoe UI", 9),
            bg="#b91c1c",
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=on_reject,
            activebackground="#991b1b",
            bd=0,
        ).pack(side="right")

        self._tick()
        self.root.mainloop()

    def _tick(self):
        if self._resolved:
            return

        self.remaining -= 1
        self.timer_label.config(text=f"{self.remaining}s")

        if self.remaining <= 0:
            self._auto_push()
        else:
            self.root.after(1000, self._tick)

    def _auto_push(self):
        if self._resolved:
            return
        self._resolved = True
        self.root.destroy()
        self.on_auto_approve(self.job)

    def _reject(self):
        if self._resolved:
            return
        self._resolved = True
        self.root.destroy()
        self.on_reject()

    def _open_diff(self):
        self.remaining = max(self.remaining, 90)
        DiffWindow(self._job_dict, self._auto_push, self._reject)


class DiffWindow:
    def __init__(self, job: dict, on_approve, on_reject):
        import tkinter as tk
        from tkinter import scrolledtext

        contribution = job["contribution"]
        target = job["target"]

        win = tk.Toplevel()
        win.title("GitHub Agent — Review Diff")
        win.geometry("660x520")
        win.attributes("-topmost", True)
        win.configure(bg="#0d1117")

        hdr = tk.Frame(win, bg="#161b22", padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="🤖  Review Contribution",
            font=("Segoe UI", 12, "bold"),
            bg="#161b22",
            fg="#e6edf3",
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text=f"{target['repo']['full_name']}  →  {target['file']['path']}",
            font=("Segoe UI", 9),
            bg="#161b22",
            fg="#8b949e",
        ).pack(anchor="w", pady=(2, 0))

        cf = tk.Frame(win, bg="#0d1117", padx=14, pady=6)
        cf.pack(fill="x")
        tk.Label(
            cf,
            text="Commit message",
            font=("Segoe UI", 8, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w")
        tk.Label(
            cf,
            text=contribution["commit_message"],
            font=("Consolas", 10),
            bg="#161b22",
            fg="#79c0ff",
            padx=8,
            pady=5,
            wraplength=610,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        tk.Label(
            win,
            text=contribution["description"],
            font=("Segoe UI", 10),
            bg="#0d1117",
            fg="#e6edf3",
            wraplength=620,
            anchor="w",
            justify="left",
            padx=14,
            pady=4,
        ).pack(fill="x")

        cdf = tk.Frame(win, bg="#0d1117", padx=14, pady=6)
        cdf.pack(fill="both", expand=True)
        tk.Label(
            cdf,
            text="Improved file preview",
            font=("Segoe UI", 8, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w")
        txt = scrolledtext.ScrolledText(
            cdf,
            font=("Consolas", 9),
            bg="#161b22",
            fg="#e6edf3",
            insertbackground="white",
            height=14,
            wrap="none",
        )
        txt.insert("1.0", contribution["improved_code"][:5000])
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, pady=(3, 0))

        bf = tk.Frame(win, bg="#0d1117", padx=14, pady=10)
        bf.pack(fill="x")
        tk.Button(
            bf,
            text="✅  Approve now",
            font=("Segoe UI", 9, "bold"),
            bg="#238636",
            fg="white",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=lambda: [win.destroy(), on_approve()],
            activebackground="#2ea043",
            bd=0,
        ).pack(side="left")
        tk.Button(
            bf,
            text="✕  Reject",
            font=("Segoe UI", 9),
            bg="#b91c1c",
            fg="white",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=lambda: [win.destroy(), on_reject()],
            activebackground="#991b1b",
            bd=0,
        ).pack(side="left", padx=(8, 0))


class TrayApp:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.icon: Optional[pystray.Icon] = None
        self._status = "idle"
        self._pending_job: Optional[ContributionJob] = None
        self._next_run_time: Optional[float] = None
        self.veto_seconds = getattr(config, "veto_seconds", DEFAULT_VETO_SECONDS)
        self._agent: Optional[HibernatingAgent] = None
        self._scheduler: Optional[OptimizedScheduler] = None
        self._last_cleanup = time.time()

    def _set_status(self, status: str):
        self._status = status
        color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
        if self.icon:
            self.icon.icon = create_tray_icon(color)
            tooltip = self._get_tooltip()
            self.icon.title = tooltip

    def _get_tooltip(self) -> str:
        status_texts = {
            "idle": "GitHub Agent — idle (optimized)",
            "working": "GitHub Agent — analyzing...",
            "pushing": "GitHub Agent — pushing...",
            "pending": "GitHub Agent — review needed!",
            "error": "GitHub Agent — error",
        }
        base = status_texts.get(self._status, "GitHub Agent")
        if self._next_run_time and self._status == "idle":
            next_run = time.strftime("%H:%M", time.localtime(self._next_run_time))
            base += f" | Next: {next_run}"
        return base

    def _get_agent(self) -> HibernatingAgent:
        if self._agent is None:
            self._agent = HibernatingAgent(self.config)
        return self._agent

    def _hibernate_agent(self):
        if self._agent is not None:
            self._agent.hibernate()
        gc.collect()
        logger.debug("Memory cleanup completed")

    def _maybe_cleanup_memory(self):
        now = time.time()
        if now - self._last_cleanup > MEMORY_CLEANUP_INTERVAL:
            self._hibernate_agent()
            self._last_cleanup = now

    def _run_agent(self):
        self._set_status("working")
        logger.info("Agent run started")

        try:
            agent = self._get_agent()
            result = agent.run()

            if result.success and result.job:
                self._pending_job = result.job
                logger.info(
                    f"Contribution ready: {result.job.contribution.commit_message}"
                )
                self._set_status("pending")
                threading.Thread(
                    target=self._show_toast, args=(result.job,), daemon=True
                ).start()
            else:
                self._hibernate_agent()
                self._set_status("idle")

                if result.error:
                    severity = result.error_severity.value.upper()
                    logger.info(f"[{severity}] {result.message}: {result.error}")

                    if (
                        result.error_severity.value == "critical"
                        or result.error_severity.value == "high"
                    ):
                        self._notify("GitHub Agent ⚠️", f"{result.message}")
                    elif result.error_severity.value == "low":
                        logger.debug(f"Nothing to contribute: {result.message}")
                else:
                    logger.info(f"Nothing to contribute: {result.message}")

            self._maybe_cleanup_memory()

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            self._notify("GitHub Agent ❌", f"Error: {str(e)[:50]}")
            self._set_status("error")
            self._hibernate_agent()

    def _show_toast(self, job: ContributionJob):
        toast = ToastWindow(
            job,
            veto_seconds=self.veto_seconds,
            on_auto_approve=self._on_auto_approve,
            on_reject=self._on_reject,
        )
        toast.show()

    def _on_auto_approve(self, job: ContributionJob):
        self._set_status("pushing")
        logger.info("Auto-pushing contribution...")

        try:
            agent = self._get_agent()
            success, error = agent.push_contribution(job.target, job.contribution)

            if success:
                msg = job.contribution.commit_message
                logger.info(f"✅ Pushed: {msg}")
                self._notify("GitHub Agent ✅", f"Pushed: {msg[:70]}")
            else:
                error_msg = str(error) if error else "Unknown error"
                logger.error(f"Push failed: {error_msg}")
                self._notify("GitHub Agent ❌", f"Push failed: {error_msg[:50]}")
                self._notify("GitHub Agent ❌", "Push failed — check logs")
        except Exception as e:
            logger.error(f"Push error: {e}", exc_info=True)
        finally:
            self._hibernate_agent()

        self._pending_job = None
        self._set_status("idle")

    def _on_reject(self):
        logger.info("Contribution rejected - looking for another...")
        self._pending_job = None
        self._notify("GitHub Agent", "Looking for another contribution...")
        self._set_status("working")
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _notify(self, title: str, message: str):
        if self.icon and self.config.show_notifications:
            self.icon.notify(title, message)

    def _menu_run_now(self, icon, item):
        if self._status == "idle":
            threading.Thread(target=self._run_agent, daemon=True).start()

    def _menu_open_logs(self, icon, item):
        log_path = Path(__file__).parent.parent / "logs" / "agent.log"
        os.startfile(str(log_path))

    def _menu_settings(self, icon, item):
        from tray.settings_window import open_settings

        def on_save(new_config):
            self.config = new_config
            self.veto_seconds = new_config.veto_seconds

        open_settings(self.config, on_save)

    def _menu_quit(self, icon, item):
        logger.info("Agent shutting down...")
        self._hibernate_agent()
        if self._scheduler:
            self._scheduler.stop()
        icon.stop()

    def start(self):
        img = create_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("▶  Run Now", self._menu_run_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️  Settings", self._menu_settings),
            pystray.MenuItem("📋  Open Logs", self._menu_open_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌  Quit", self._menu_quit),
        )
        self.icon = pystray.Icon(
            "github_agent", img, "GitHub Agent — idle (optimized)", menu
        )

        interval_hours = getattr(self.config, "interval_hours", 4)
        auto_run = getattr(self.config, "auto_run_on_startup", True)

        self._scheduler = OptimizedScheduler(
            interval_hours=interval_hours,
            on_run=self._run_agent,
            on_status=self._set_status,
        )
        self._scheduler.start(run_on_start=auto_run)

        logger.info(
            f"Started (optimized). Veto: {self.veto_seconds}s. Interval: {interval_hours}h."
        )
        self.icon.run()
