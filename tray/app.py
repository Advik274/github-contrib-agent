import logging
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw

from agent.config import AgentConfig
from agent.constants import STATUS_COLORS
from agent.core import ContributionJob, GitHubAgent

logger = logging.getLogger(__name__)

DEFAULT_VETO_SECONDS = 300
_MAX_CONSECUTIVE_AI_FAILURES = 3
_AI_FAILURE_BACKOFF_HOURS = 1


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
                "original_content": job.target.content,
            },
            "contribution": {
                "commit_message": job.contribution.commit_message,
                "description": job.contribution.description,
                "improved_code": job.contribution.improved_code,
            },
        }

    def show(self):
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.attributes("-alpha", 0)

        self.root = tk.Toplevel(self._root)
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
        self.root.geometry(f"{w}x{h}+{sw - w - 16}+40")

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

        self.approve_btn = tk.Button(
            buttons,
            text="✅  Approve Now",
            font=("Segoe UI", 9, "bold"),
            bg="#238636",
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._do_approve,
            activebackground="#2ea043",
            bd=0,
        )
        self.approve_btn.pack(side="left")

        self.diff_btn = tk.Button(
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
        )
        self.diff_btn.pack(side="left", padx=(6, 0))

        self.reject_btn = tk.Button(
            buttons,
            text="✕  Reject",
            font=("Segoe UI", 9),
            bg="#b91c1c",
            fg="white",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._do_reject,
            activebackground="#991b1b",
            bd=0,
        )
        self.reject_btn.pack(side="right")

        self.root.update_idletasks()
        self.root.after(1000, self._tick)
        self.root.mainloop()

    def _do_approve(self):
        if self._resolved:
            return
        self._resolved = True
        self.root.destroy()
        self.on_auto_approve(self.job)

    def _do_reject(self):
        if self._resolved:
            return
        self._resolved = True
        self.root.destroy()
        self._root.destroy()
        self.on_reject()

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
        self._root.destroy()
        self.on_auto_approve(self.job)

    def _reject(self):
        if self._resolved:
            return
        self._resolved = True
        self.root.destroy()
        self._root.destroy()
        self.on_reject()

    def _open_diff(self):
        self.remaining = max(self.remaining, 90)
        DiffWindow(self._job_dict, self._auto_push, self._reject)


class DiffWindow:
    def __init__(self, job: dict, on_approve, on_reject):
        import difflib
        import tkinter as tk
        from tkinter import scrolledtext

        contribution = job["contribution"]
        target = job["target"]
        original_content = job["target"].get("original_content", "")
        improved_content = contribution["improved_code"]

        win = tk.Toplevel()
        win.title("GitHub Agent — Review Diff")
        win.geometry("900x650")
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
            text="Commit message:",
            font=("Segoe UI", 8, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w")
        tk.Label(
            cf,
            text=contribution["commit_message"],
            font=("Segoe UI", 10),
            bg="#161b22",
            fg="#79c0ff",
            padx=8,
            pady=4,
            wraplength=860,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        desc_frame = tk.Frame(win, bg="#0d1117", padx=14, pady=4)
        desc_frame.pack(fill="x")
        tk.Label(
            desc_frame,
            text=f"Change: {contribution['description']}",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#7ee787",
            wraplength=860,
            anchor="w",
        ).pack(fill="x")

        diff_frame = tk.Frame(win, bg="#0d1117", padx=14, pady=6)
        diff_frame.pack(fill="both", expand=True)

        header_frame = tk.Frame(diff_frame, bg="#21262d")
        header_frame.pack(fill="x")

        tk.Label(
            header_frame,
            text="- Original",
            font=("Segoe UI", 8, "bold"),
            bg="#f85149",
            fg="white",
            padx=8,
            pady=2,
        ).pack(side="left", padx=(0, 20))

        tk.Label(
            header_frame,
            text="+ Improved",
            font=("Segoe UI", 8, "bold"),
            bg="#238636",
            fg="white",
            padx=8,
            pady=2,
        ).pack(side="left")

        text_frame = tk.Frame(diff_frame, bg="#0d1117")
        text_frame.pack(fill="both", expand=True, pady=(4, 0))

        original_text = scrolledtext.ScrolledText(
            text_frame,
            font=("Consolas", 9),
            bg="#3d1f1f",
            fg="#ffa198",
            insertbackground="white",
            height=20,
            wrap="none",
            relief="flat",
            bd=0,
        )
        original_text.pack(side="left", fill="both", expand=True)

        improved_text = scrolledtext.ScrolledText(
            text_frame,
            font=("Consolas", 9),
            bg="#1f3d1f",
            fg="#7ee787",
            insertbackground="white",
            height=20,
            wrap="none",
            relief="flat",
            bd=0,
        )
        improved_text.pack(side="left", fill="both", expand=True, padx=(4, 0))

        original_lines = original_content.splitlines(keepends=True)
        improved_lines = improved_content.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, original_lines, improved_lines)

        original_display = []
        improved_display = []
        original_tags = []
        improved_tags = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for line in original_lines[i1:i2]:
                    original_display.append(line)
                    original_tags.append("equal")
                for line in improved_lines[j1:j2]:
                    improved_display.append(line)
                    improved_tags.append("equal")
            elif tag == "replace":
                for line in original_lines[i1:i2]:
                    original_display.append(line)
                    original_tags.append("delete")
                for line in improved_lines[j1:j2]:
                    improved_display.append(line)
                    improved_tags.append("add")
            elif tag == "delete":
                for line in original_lines[i1:i2]:
                    original_display.append(line)
                    original_tags.append("delete")
            elif tag == "insert":
                for line in improved_lines[j1:j2]:
                    improved_display.append(line)
                    improved_tags.append("add")

        def tag_text(text_widget, lines, tags):
            for i, line in enumerate(lines[:100]):
                tag = tags[i] if i < len(tags) else "equal"
                if tag == "delete":
                    text_widget.insert("end", line, ("delete", f"line_{i}"))
                elif tag == "add":
                    text_widget.insert("end", line, ("add", f"line_{i}"))
                else:
                    text_widget.insert("end", line, ("equal", f"line_{i}"))

        text_widget_original = original_text
        text_widget_improved = improved_text

        text_widget_original.tag_configure(
            "delete", background="#5c1a1a", foreground="#ffa198"
        )
        text_widget_original.tag_configure(
            "add", background="#3d1f1f", foreground="#ffa198"
        )
        text_widget_original.tag_configure(
            "equal", background="#1e1e1e", foreground="#9cdcfe"
        )

        text_widget_improved.tag_configure(
            "delete", background="#3d1f1f", foreground="#7ee787"
        )
        text_widget_improved.tag_configure(
            "add", background="#1c3a1c", foreground="#7ee787"
        )
        text_widget_improved.tag_configure(
            "equal", background="#1e1e1e", foreground="#9cdcfe"
        )

        text_widget_original.delete("1.0", "end")
        text_widget_improved.delete("1.0", "end")

        tag_text(text_widget_original, original_display, original_tags)
        tag_text(text_widget_improved, improved_display, improved_tags)

        text_widget_original.config(state="disabled")
        text_widget_improved.config(state="disabled")

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
        self._agent: Optional[GitHubAgent] = None
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._action_queue: queue.Queue = queue.Queue()
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.after(100, self._process_actions)

    def _set_status(self, status: str):
        self._status = status
        color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
        if self.icon:
            self.icon.icon = create_tray_icon(color)
            tooltip = self._get_tooltip()
            self.icon.title = tooltip

    def _process_actions(self):
        try:
            while True:
                action = self._action_queue.get_nowait()
                action()
        except queue.Empty:
            pass
        self._root.after(100, self._process_actions)

    def _get_tooltip(self) -> str:
        status_texts = {
            "idle": "GitHub Agent — idle",
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

    def _get_agent(self) -> GitHubAgent:
        if self._agent is None:
            self._agent = GitHubAgent(self.config)
        return self._agent

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
                self._show_toast(result.job)
            else:
                self._set_status("idle")
                if result.error:
                    logger.info(f"{result.message}: {result.error}")
                else:
                    logger.info(f"Nothing to contribute: {result.message}")

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            self._notify("GitHub Agent ❌", f"Error: {str(e)[:50]}")
            self._set_status("error")

    def _show_toast(self, job: ContributionJob):
        toast = ToastWindow(
            job,
            veto_seconds=self.veto_seconds,
            on_auto_approve=self._on_auto_approve,
            on_reject=self._on_reject,
        )
        toast.show()

    def _on_auto_approve(self, job: ContributionJob):
        if self._status == "pushing":
            logger.warning("Push already in progress, ignoring duplicate call")
            return

        self._set_status("pushing")
        logger.info("Auto-pushing contribution...")

        try:
            agent = self._get_agent()
            success, error = agent.push_contribution(job.target, job.contribution)

            if success:
                msg = job.contribution.commit_message
                logger.info(f"✅ Pushed: {msg}")
                self._notify("GitHub Agent ✅", f"Pushed: {msg[:50]}...")
            else:
                error_msg = str(error) if error else "Unknown error"
                logger.error(f"Push failed: {error_msg}")
                self._notify("GitHub Agent ❌", "Push failed - check logs")
        except Exception as e:
            logger.error(f"Push error: {e}", exc_info=True)

        self._pending_job = None
        self._set_status("idle")

    def _on_reject(self):
        logger.info("Contribution rejected - looking for another...")

        if self._pending_job:
            job = self._pending_job
            agent = self._get_agent()
            agent._mark_processed(job.target.repo.full_name, job.target.file.path)

        self._pending_job = None
        self._notify("GitHub Agent", "Looking for another contribution...")
        self._set_status("working")
        threading.Thread(target=self._run_agent, daemon=True).start()

    def _notify(self, title: str, message: str):
        if self.icon and self.config.show_notifications:
            self.icon.notify(title, message)

    def _scheduler_loop(self):
        interval_seconds = getattr(self.config, "interval_hours", 4) * 3600

        while not self._stop_event.is_set():
            if self._status == "idle":
                self._run_agent()
                self._next_run_time = time.time() + interval_seconds

            remaining = int(self._next_run_time - time.time()) if self._next_run_time else 0
            sleep_seconds = max(0, min(remaining, interval_seconds))

            for _ in range(sleep_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _menu_run_now(self, icon, item):
        if self._status == "idle":
            threading.Thread(target=self._run_agent, daemon=True).start()

    def _menu_open_logs(self, icon, item):
        log_path = Path(__file__).parent.parent / "logs" / "agent.log"
        os.startfile(str(log_path))

    def _menu_settings(self, icon, item):
        def open_settings_action():
            from tray.settings_window import open_settings

            def on_save(new_config):
                self.config = new_config
                self.veto_seconds = new_config.veto_seconds

            open_settings(self.config, on_save, self._root)

        self._root.after(0, open_settings_action)

    def _menu_quit(self, icon, item):
        logger.info("Agent shutting down...")
        self._stop_event.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=2)
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
        self.icon = pystray.Icon("github_agent", img, "GitHub Agent — idle", menu)

        auto_run = getattr(self.config, "auto_run_on_startup", True)

        if auto_run:
            threading.Thread(target=self._run_agent, daemon=True).start()

        logger.info(
            f"Started. Veto: {self.veto_seconds}s. Interval: {getattr(self.config, 'interval_hours', 4)}h."
        )
        self._pystray_thread = threading.Thread(target=self.icon.run, daemon=True)
        self._pystray_thread.start()
