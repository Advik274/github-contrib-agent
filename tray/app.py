"""
TrayApp — system-tray frontend for the GitHub Contribution Agent.

Threading model
───────────────
• ONE Tk root (self._root) owns the event loop (mainloop in main.py).
• self._action_queue is the single safe channel from all background threads
  into the Tk main thread. Every state mutation goes through it.
• self._status_lock guards self._status for reads from pystray / scheduler
  threads (those can only READ; writes always go via _set_status on main thread).
• pystray runs in its own daemon thread; menu callbacks must NEVER touch Tk directly.
"""

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
_MAX_CONSECUTIVE_AI_FAILURES = 3   # pause auto-run after this many in a row
_AI_FAILURE_BACKOFF_HOURS = 1      # wait this long before retrying after pause


# ── Icon helper ───────────────────────────────────────────────────────────────

def create_tray_icon(color: str = "#2ea44f") -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=_hex_to_rgb(color))
    draw.ellipse([22, 22, 42, 42], fill=(255, 255, 255, 255))
    return img


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i: i + 2], 16) for i in (0, 2, 4))


# ── Toast notification ────────────────────────────────────────────────────────

class ToastWindow:
    """
    Compact notification shown in the top-right corner when a contribution is ready.
    Must be created and shown on the Tk main thread.
    """

    def __init__(
        self,
        job: ContributionJob,
        veto_seconds: int,
        on_approve,
        on_reject,
        parent_root: tk.Tk,
    ):
        self.job = job
        self.veto_seconds = veto_seconds
        self.remaining = veto_seconds
        self.on_approve = on_approve
        self.on_reject = on_reject
        self._resolved = False
        self._parent_root = parent_root

        # Serialise job so we don't hold cross-thread dataclass references
        self._job_dict = {
            "target": {
                "repo": {
                    "full_name": job.target.repo.full_name,
                    "name": job.target.repo.name,
                },
                "file": {
                    "path": job.target.file.path,
                    "name": job.target.file.name,
                },
                "original_content": job.target.content,
            },
            "contribution": {
                "commit_message": job.contribution.commit_message,
                "description": job.contribution.description,
                "improved_code": job.contribution.improved_code,
            },
        }

    def show(self):
        self.root = tk.Toplevel(self._parent_root)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#161b22")

        border = tk.Frame(self.root, bg="#30363d", padx=1, pady=1)
        border.pack(fill="both", expand=True)
        inner = tk.Frame(border, bg="#161b22")
        inner.pack(fill="both", expand=True)

        w, h = 410, 148
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{w}x{h}+{sw - w - 16}+40")

        # ── Header row ────────────────────────────────────────────────────────
        row1 = tk.Frame(inner, bg="#161b22")
        row1.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(row1, text="🤖", font=("Segoe UI", 13), bg="#161b22", fg="#e6edf3").pack(side="left")
        tk.Label(row1, text="  Auto-pushing in",
                 font=("Segoe UI", 11, "bold"), bg="#161b22", fg="#e6edf3").pack(side="left")
        self.timer_label = tk.Label(
            row1, text=f"{self.veto_seconds}s",
            font=("Segoe UI", 11, "bold"), bg="#161b22", fg="#58a6ff",
        )
        self.timer_label.pack(side="right")

        # ── Info ──────────────────────────────────────────────────────────────
        msg = tk.Frame(inner, bg="#161b22")
        msg.pack(fill="x", padx=12)
        repo_name = self._job_dict["target"]["repo"]["name"]
        file_path = self._job_dict["target"]["file"]["path"]
        commit_msg = self._job_dict["contribution"]["commit_message"]

        tk.Label(msg, text=f"📁 {repo_name}/{file_path}",
                 font=("Segoe UI", 9), bg="#161b22", fg="#8b949e").pack(anchor="w")
        tk.Label(msg, text=f"📝 {commit_msg}",
                 font=("Segoe UI", 9), bg="#161b22", fg="#79c0ff",
                 wraplength=380, anchor="w", justify="left").pack(anchor="w", pady=(2, 0))

        # ── Buttons ───────────────────────────────────────────────────────────
        buttons = tk.Frame(inner, bg="#161b22")
        buttons.pack(fill="x", padx=12, pady=(8, 10))

        self.approve_btn = tk.Button(
            buttons, text="✅  Approve Now",
            font=("Segoe UI", 9, "bold"), bg="#238636", fg="white",
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._do_approve, activebackground="#2ea043", bd=0,
        )
        self.approve_btn.pack(side="left")

        tk.Button(
            buttons, text="🔍  View Diff",
            font=("Segoe UI", 9), bg="#21262d", fg="#c9d1d9",
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._open_diff, activebackground="#30363d", bd=0,
        ).pack(side="left", padx=(6, 0))

        tk.Button(
            buttons, text="✕  Reject",
            font=("Segoe UI", 9), bg="#b91c1c", fg="white",
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._do_reject, activebackground="#991b1b", bd=0,
        ).pack(side="right")

        self.root.after(1000, self._tick)

    def _safe_resolve(self, fn):
        """Execute fn exactly once, regardless of which button fires first."""
        if self._resolved:
            return False
        self._resolved = True
        try:
            self.root.destroy()
        except Exception:
            pass
        fn()
        return True

    def _do_approve(self):
        self._safe_resolve(lambda: self.on_approve(self.job))

    def _do_reject(self):
        self._safe_resolve(self.on_reject)

    def _tick(self):
        if self._resolved:
            return
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        self.remaining -= 1
        self.timer_label.config(text=f"{self.remaining}s")
        if self.remaining <= 0:
            self._do_approve()
        else:
            self.root.after(1000, self._tick)

    def _open_diff(self):
        # Give user extra time while reviewing the diff
        self.remaining = max(self.remaining, 90)
        DiffWindow(self._job_dict, self._do_approve, self._do_reject, self._parent_root)


# ── Diff viewer ───────────────────────────────────────────────────────────────

class DiffWindow:
    def __init__(self, job: dict, on_approve, on_reject, parent: tk.Tk):
        import difflib

        contribution = job["contribution"]
        target = job["target"]
        original_content = target.get("original_content", "")
        improved_content = contribution["improved_code"]

        win = tk.Toplevel(parent)
        win.title("GitHub Agent — Review Diff")
        win.geometry("940x680")
        win.attributes("-topmost", True)
        win.configure(bg="#0d1117")

        # Header
        hdr = tk.Frame(win, bg="#161b22", padx=14, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🤖  Review Contribution",
                 font=("Segoe UI", 12, "bold"), bg="#161b22", fg="#e6edf3").pack(anchor="w")
        tk.Label(hdr,
                 text=f"{target['repo']['full_name']}  →  {target['file']['path']}",
                 font=("Segoe UI", 9), bg="#161b22", fg="#8b949e").pack(anchor="w", pady=(2, 0))

        # Commit message
        cf = tk.Frame(win, bg="#0d1117", padx=14, pady=6)
        cf.pack(fill="x")
        tk.Label(cf, text="Commit message:", font=("Segoe UI", 8, "bold"),
                 bg="#0d1117", fg="#8b949e").pack(anchor="w")
        tk.Label(cf, text=contribution["commit_message"],
                 font=("Segoe UI", 10), bg="#161b22", fg="#79c0ff",
                 padx=8, pady=4, wraplength=900, anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        # Description
        df = tk.Frame(win, bg="#0d1117", padx=14, pady=4)
        df.pack(fill="x")
        tk.Label(df, text=f"Change: {contribution['description']}",
                 font=("Segoe UI", 9), bg="#0d1117", fg="#7ee787",
                 wraplength=900, anchor="w").pack(fill="x")

        # Diff panels
        diff_frame = tk.Frame(win, bg="#0d1117", padx=14, pady=6)
        diff_frame.pack(fill="both", expand=True)

        hdr_f = tk.Frame(diff_frame, bg="#21262d")
        hdr_f.pack(fill="x")
        tk.Label(hdr_f, text="— Original", font=("Segoe UI", 8, "bold"),
                 bg="#f85149", fg="white", padx=8, pady=2).pack(side="left", padx=(0, 20))
        tk.Label(hdr_f, text="+ Improved", font=("Segoe UI", 8, "bold"),
                 bg="#238636", fg="white", padx=8, pady=2).pack(side="left")

        tf = tk.Frame(diff_frame, bg="#0d1117")
        tf.pack(fill="both", expand=True, pady=(4, 0))

        def make_pane(bg, fg):
            t = __import__("tkinter.scrolledtext", fromlist=["ScrolledText"]).ScrolledText(
                tf, font=("Consolas", 9), bg=bg, fg=fg,
                insertbackground="white", height=22, wrap="none",
                relief="flat", bd=0,
            )
            t.pack(side="left", fill="both", expand=True, padx=(0, 2))
            return t

        orig_w = make_pane("#3d1f1f", "#ffa198")
        impr_w = make_pane("#1f3d1f", "#7ee787")

        for widget, key_del, key_add in [
            (orig_w, "delete", "equal"),
            (impr_w, "equal", "add"),
        ]:
            widget.tag_configure("delete", background="#5c1a1a", foreground="#ffa198")
            widget.tag_configure("add",    background="#1c3a1c", foreground="#7ee787")
            widget.tag_configure("equal",  background="#1e1e1e", foreground="#9cdcfe")

        orig_lines = original_content.splitlines(keepends=True)
        impr_lines = improved_content.splitlines(keepends=True)

        matcher = difflib.SequenceMatcher(None, orig_lines, impr_lines)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for line in orig_lines[i1:i2]:
                    orig_w.insert("end", line, "equal")
                for line in impr_lines[j1:j2]:
                    impr_w.insert("end", line, "equal")
            elif tag in ("replace", "delete"):
                for line in orig_lines[i1:i2]:
                    orig_w.insert("end", line, "delete")
                if tag == "replace":
                    for line in impr_lines[j1:j2]:
                        impr_w.insert("end", line, "add")
            elif tag == "insert":
                for line in impr_lines[j1:j2]:
                    impr_w.insert("end", line, "add")

        orig_w.config(state="disabled")
        impr_w.config(state="disabled")

        # Buttons
        bf = tk.Frame(win, bg="#0d1117", padx=14, pady=10)
        bf.pack(fill="x")
        tk.Button(bf, text="✅  Approve now",
                  font=("Segoe UI", 9, "bold"), bg="#238636", fg="white",
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=lambda: [win.destroy(), on_approve()],
                  activebackground="#2ea043", bd=0).pack(side="left")
        tk.Button(bf, text="✕  Reject",
                  font=("Segoe UI", 9), bg="#b91c1c", fg="white",
                  relief="flat", padx=12, pady=6, cursor="hand2",
                  command=lambda: [win.destroy(), on_reject()],
                  activebackground="#991b1b", bd=0).pack(side="left", padx=(8, 0))


# ── Main tray application ─────────────────────────────────────────────────────

class TrayApp:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.icon: Optional[pystray.Icon] = None

        # ── State (writes: main thread only; reads: guarded by _status_lock) ──
        self._status = "idle"
        self._status_lock = threading.Lock()
        self._pending_job: Optional[ContributionJob] = None
        self._next_run_time: Optional[float] = None
        self._consecutive_ai_failures = 0
        self._ai_paused_until: Optional[float] = None

        self.veto_seconds = getattr(config, "veto_seconds", DEFAULT_VETO_SECONDS)
        self._agent: Optional[GitHubAgent] = None

        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Thread-safe bridge: background threads post callables here;
        # the main thread drains this queue every 100 ms.
        self._action_queue: queue.Queue = queue.Queue()

        # Single Tk root — NEVER create a second one
        self._root = tk.Tk()
        self._root.withdraw()
        self._root.after(100, self._process_actions)

    # ── Thread-safe helpers ───────────────────────────────────────────────────

    def _on_main_thread(self, fn):
        """Schedule fn() to execute on the Tk main thread. Safe from any thread."""
        self._action_queue.put(fn)

    def _process_actions(self):
        """Drain the action queue. Runs every 100 ms on the main thread."""
        try:
            while True:
                action = self._action_queue.get_nowait()
                try:
                    action()
                except Exception as e:
                    logger.error(f"Error in queued action: {e}", exc_info=True)
        except queue.Empty:
            pass
        self._root.after(100, self._process_actions)

    # ── Status management (main thread only for writes) ───────────────────────

    def _set_status(self, status: str):
        """Must be called on main thread. Use _on_main_thread() from background."""
        with self._status_lock:
            self._status = status
        color = STATUS_COLORS.get(status, STATUS_COLORS["idle"])
        if self.icon:
            try:
                self.icon.icon = create_tray_icon(color)
                self.icon.title = self._get_tooltip()
            except Exception:
                pass

    def _read_status(self) -> str:
        """Thread-safe status read for background threads."""
        with self._status_lock:
            return self._status

    def _get_tooltip(self) -> str:
        with self._status_lock:
            status = self._status
        texts = {
            "idle":    "GitHub Agent — idle",
            "working": "GitHub Agent — analyzing...",
            "pushing": "GitHub Agent — pushing...",
            "pending": "GitHub Agent — awaiting review",
            "error":   "GitHub Agent — error (check logs)",
            "paused":  "GitHub Agent — paused (AI errors)",
        }
        base = texts.get(status, "GitHub Agent")
        if self._next_run_time and status in ("idle", "paused"):
            next_run = time.strftime("%H:%M", time.localtime(self._next_run_time))
            base += f" | Next: {next_run}"
        return base

    # ── Agent management ──────────────────────────────────────────────────────

    def _get_agent(self) -> GitHubAgent:
        if self._agent is None:
            self._agent = GitHubAgent(self.config)
        return self._agent

    def _invalidate_agent(self):
        self._agent = None

    # ── Core agent run (background thread) ───────────────────────────────────

    def _run_agent(self):
        # AI back-off: don't hammer a broken API
        if self._ai_paused_until and time.time() < self._ai_paused_until:
            remaining = int(self._ai_paused_until - time.time())
            logger.info(f"AI paused after repeated failures — {remaining}s remaining")
            return

        self._on_main_thread(lambda: self._set_status("working"))
        logger.info("Agent run started")

        try:
            agent = self._get_agent()
            result = agent.run()

            if result.success and result.job:
                self._consecutive_ai_failures = 0
                self._ai_paused_until = None
                self._pending_job = result.job
                logger.info(f"Contribution ready: {result.job.contribution.commit_message}")
                self._on_main_thread(lambda: self._set_status("pending"))
                self._on_main_thread(lambda j=result.job: self._show_toast(j))

            else:
                # Check if history is exhausted → auto-clear and retry
                if result.error and "all files" in result.error.lower():
                    logger.info("All files processed — clearing history for a fresh scan")
                    self._on_main_thread(self._auto_clear_history)
                else:
                    logger.info(f"Nothing to contribute: {result.message}")

                self._on_main_thread(lambda: self._set_status("idle"))

        except Exception as e:
            logger.error(f"Agent error: {e}", exc_info=True)
            self._consecutive_ai_failures += 1
            if self._consecutive_ai_failures >= _MAX_CONSECUTIVE_AI_FAILURES:
                pause = _AI_FAILURE_BACKOFF_HOURS * 3600
                self._ai_paused_until = time.time() + pause
                logger.warning(
                    f"{self._consecutive_ai_failures} consecutive AI failures — "
                    f"pausing for {_AI_FAILURE_BACKOFF_HOURS}h"
                )
                self._on_main_thread(
                    lambda: self._notify(
                        "GitHub Agent ⚠️",
                        f"Pausing AI for {_AI_FAILURE_BACKOFF_HOURS}h after repeated errors",
                    )
                )
                self._on_main_thread(lambda: self._set_status("paused"))
            else:
                err_str = str(e)
                self._on_main_thread(
                    lambda: self._notify("GitHub Agent ❌", f"Error: {err_str[:60]}")
                )
                self._on_main_thread(lambda: self._set_status("error"))

    # ── Toast and approval ────────────────────────────────────────────────────

    def _show_toast(self, job: ContributionJob):
        """Must be called on main thread."""
        toast = ToastWindow(
            job,
            veto_seconds=self.veto_seconds,
            on_approve=self._on_approve,
            on_reject=self._on_reject,
            parent_root=self._root,
        )
        toast.show()

    def _on_approve(self, job: ContributionJob):
        """Called on main thread (from ToastWindow)."""
        if self._read_status() == "pushing":
            logger.warning("Push already in progress — ignoring duplicate approval")
            return
        self._set_status("pushing")
        threading.Thread(target=self._do_push, args=(job,), daemon=True).start()

    def _do_push(self, job: ContributionJob):
        """Background thread — communicates back via _on_main_thread."""
        try:
            agent = self._get_agent()
            success, error = agent.push_contribution(job.target, job.contribution)
            msg = job.contribution.commit_message
            if success:
                logger.info(f"✅ Pushed: {msg}")
                self._on_main_thread(
                    lambda: self._notify("GitHub Agent ✅", f"Pushed: {msg[:60]}")
                )
            else:
                err_str = str(error) if error else "unknown error"
                logger.error(f"Push failed: {err_str}")
                self._on_main_thread(
                    lambda: self._notify("GitHub Agent ❌", "Push failed — check logs")
                )
        except Exception as e:
            logger.error(f"Push exception: {e}", exc_info=True)
        finally:
            self._pending_job = None
            self._on_main_thread(lambda: self._set_status("idle"))

    def _on_reject(self):
        """Called on main thread (from ToastWindow)."""
        logger.info("Contribution rejected — searching for another...")
        if self._pending_job:
            job = self._pending_job
            try:
                self._get_agent()._mark_processed(
                    job.target.repo.full_name, job.target.file.path
                )
            except Exception:
                pass
        self._pending_job = None
        self._notify("GitHub Agent", "Rejected — looking for another contribution...")
        self._set_status("working")
        threading.Thread(target=self._run_agent, daemon=True).start()

    # ── Notifications ─────────────────────────────────────────────────────────

    def _notify(self, title: str, message: str):
        if self.icon and self.config.show_notifications:
            try:
                self.icon.notify(title, message)
            except Exception:
                pass

    # ── History management ────────────────────────────────────────────────────

    def _auto_clear_history(self):
        """Called on main thread when all files are processed."""
        from agent.constants import HISTORY_FILE
        try:
            HISTORY_FILE.write_text('{"processed_files": []}')
            if self._agent:
                self._agent._processed_files = set()
            logger.info("History auto-cleared — all files eligible again")
            self._notify("GitHub Agent 🔄", "All files processed — restarting scan from scratch")
            # Kick off a fresh run after a short delay
            self._root.after(5000, lambda: threading.Thread(
                target=self._run_agent, daemon=True
            ).start())
        except Exception as e:
            logger.error(f"Failed to auto-clear history: {e}")

    # ── Scheduler ─────────────────────────────────────────────────────────────

    def _scheduler_loop(self):
        """
        Background thread. Waits one full interval then fires a run.
        First run (on startup) is handled separately by TrayApp.start().
        Uses _read_status() (thread-safe) to avoid running while busy.
        """
        interval_seconds = getattr(self.config, "interval_hours", 4) * 3600

        while not self._stop_event.is_set():
            self._next_run_time = time.time() + interval_seconds

            # Sleep in 1-second chunks for responsive stop
            for _ in range(int(interval_seconds)):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

            if self._stop_event.is_set():
                return

            status = self._read_status()
            if status == "idle":
                threading.Thread(target=self._run_agent, daemon=True).start()
            else:
                logger.info(f"Scheduled run skipped — status is '{status}'")

    # ── Tray menu handlers ────────────────────────────────────────────────────

    def _menu_run_now(self, icon, item):
        """pystray thread → must go through _on_main_thread for any Tk or state work."""
        if self._read_status() == "idle":
            threading.Thread(target=self._run_agent, daemon=True).start()
        else:
            logger.info(f"Run Now ignored — status is '{self._read_status()}'")

    def _menu_open_logs(self, icon, item):
        log_path = Path(__file__).parent.parent / "logs" / "agent.log"
        if not log_path.exists():
            logger.warning("Log file not found")
            return
        try:
            if os.name == "nt":
                os.startfile(str(log_path))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(log_path)])
        except Exception as e:
            logger.error(f"Could not open log file: {e}")

    def _menu_settings(self, icon, item):
        """
        pystray thread → post the Tk work onto the main thread via _on_main_thread.
        open_settings() creates a Toplevel (NO new mainloop).
        """
        def _open():
            from tray.settings_window import open_settings

            def on_save(new_config: AgentConfig):
                self.config = new_config
                self.veto_seconds = new_config.veto_seconds
                self._invalidate_agent()
                logger.info("Config reloaded from settings")

            open_settings(self.config, on_save, self._root)

        self._on_main_thread(_open)

    def _menu_clear_history(self, icon, item):
        self._on_main_thread(self._do_clear_history)

    def _do_clear_history(self):
        from agent.constants import HISTORY_FILE
        try:
            HISTORY_FILE.write_text('{"processed_files": []}')
            if self._agent:
                self._agent._processed_files = set()
            logger.info("Contribution history manually cleared")
            self._notify("GitHub Agent", "History cleared — all files eligible again")
        except Exception as e:
            logger.error(f"Failed to clear history: {e}")

    def _menu_quit(self, icon, item):
        logger.info("Agent shutting down...")
        self._stop_event.set()
        self._on_main_thread(self._root.quit)
        try:
            icon.stop()
        except Exception:
            pass

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self):
        img = create_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("▶  Run Now", self._menu_run_now),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙️  Settings", self._menu_settings),
            pystray.MenuItem("📋  Open Logs", self._menu_open_logs),
            pystray.MenuItem("🗑️  Clear History", self._menu_clear_history),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌  Quit", self._menu_quit),
        )
        self.icon = pystray.Icon("github_agent", img, "GitHub Agent — idle", menu)

        auto_run = getattr(self.config, "auto_run_on_startup", True)

        # Scheduler: waits one interval before firing (auto_run handles first run)
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, daemon=True
        )
        self._scheduler_thread.start()

        if auto_run:
            threading.Thread(target=self._run_agent, daemon=True).start()

        logger.info(
            f"Tray started | provider={self.config.ai_provider} "
            f"model={self.config.effective_model()} "
            f"veto={self.veto_seconds}s "
            f"interval={getattr(self.config, 'interval_hours', 4)}h"
        )

        # pystray runs in its own daemon thread; Tk mainloop is in main.py
        self._pystray_thread = threading.Thread(target=self.icon.run, daemon=True)
        self._pystray_thread.start()
