import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from agent.config import AgentConfig, get_config_manager
from agent.constants import MAX_VETO_SECONDS, MIN_VETO_SECONDS, AI_PROVIDERS

logger = logging.getLogger(__name__)

STARTUP_FILENAME = "GitHub Agent.bat"

# ── Startup helpers (Windows only) ────────────────────────────────────────────

def _get_startup_folder() -> Optional[str]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

def _get_agent_bat_path() -> Optional[str]:
    folder = _get_startup_folder()
    return os.path.join(folder, STARTUP_FILENAME) if folder else None

def _is_agent_in_startup() -> bool:
    path = _get_agent_bat_path()
    return bool(path and os.path.exists(path))

def _add_to_startup() -> bool:
    bat_path = _get_agent_bat_path()
    if not bat_path:
        return False
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        batch_content = (
            f'@echo off\n'
            f'cd /d "{script_dir}"\n'
            f'start "" "{sys.executable}" "{os.path.join(script_dir, "main.py")}"\n'
        )
        with open(bat_path, "w") as f:
            f.write(batch_content)
        logger.info(f"Added agent to Windows startup: {bat_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to add to startup: {e}")
        return False

def _remove_from_startup() -> bool:
    bat_path = _get_agent_bat_path()
    if not bat_path:
        return True
    try:
        if os.path.exists(bat_path):
            os.remove(bat_path)
            logger.info("Removed agent from Windows startup")
        return True
    except Exception as e:
        logger.error(f"Failed to remove from startup: {e}")
        return False


# ── Settings window ───────────────────────────────────────────────────────────

class SettingsWindow:
    """
    Settings GUI.

    Layout notes
    ────────────
    • Window is tall enough (680px) so the Save/Cancel buttons are never clipped.
    • The card area uses a Canvas + Scrollbar so content can scroll if the
      screen is small.
    • Changing the AI provider reveals an API key entry so the user can enter
      the key for the new provider without re-opening onboarding.
    • Test AI builds a temporary config from the *current UI values*, not the
      saved config, so it tests whatever is currently entered.
    """

    # ── Construction ──────────────────────────────────────────────────────────

    def __init__(
        self,
        config: AgentConfig,
        on_save: Optional[callable] = None,
        parent: Optional[tk.Tk] = None,
    ):
        self.config = config
        self.config_manager = get_config_manager()
        self.on_save = on_save
        self._api_key_changed = False   # track whether user entered a new key

        if parent:
            self.root = tk.Toplevel(parent)
            self._owns_mainloop = False
        else:
            self.root = tk.Tk()
            self._owns_mainloop = True

        self.root.title("GitHub Agent — Settings")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.focus_force()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._setup_styles()
        self._create_widgets()
        self._load_values()
        self._center_window()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame",    background="#0d1117")
        style.configure("TScale",    background="#161b22")
        style.configure("TCombobox",
            fieldbackground="#21262d",
            background="#21262d",
            foreground="#c9d1d9",
            selectbackground="#30363d",
            selectforeground="#e6edf3",
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", "#21262d")],
            foreground=[("readonly", "#c9d1d9")],
        )

    # ── Widget creation ───────────────────────────────────────────────────────

    def _create_widgets(self):
        BG       = "#0d1117"
        CARD_BG  = "#161b22"
        DIM      = "#8b949e"
        BRIGHT   = "#e6edf3"
        ACCENT   = "#58a6ff"
        MUTED    = "#c9d1d9"
        SEP      = "#30363d"
        INPUT_BG = "#21262d"
        GREEN    = "#7ee787"
        ORANGE   = "#f0883e"

        # ── Outer frame ───────────────────────────────────────────────────────
        outer = tk.Frame(self.root, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)

        # Title
        tk.Label(outer, text="⚙️  Settings",
                 font=("Segoe UI", 15, "bold"), bg=BG, fg=BRIGHT).pack(anchor="w")
        tk.Label(outer, text="Configure your GitHub Contribution Agent",
                 font=("Segoe UI", 9), bg=BG, fg=DIM).pack(anchor="w", pady=(2, 10))

        # ── Scrollable card ───────────────────────────────────────────────────
        canvas_frame = tk.Frame(outer, bg=BG)
        canvas_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(canvas_frame, bg=CARD_BG, bd=0,
                                  highlightthickness=0, relief="flat")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical",
                                   command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        card = tk.Frame(self._canvas, bg=CARD_BG, padx=14, pady=12)
        self._card_window = self._canvas.create_window((0, 0), window=card, anchor="nw")

        card.bind("<Configure>", self._on_card_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        # Mouse-wheel scrolling
        self._canvas.bind_all("<MouseWheel>",  self._on_mousewheel)
        self._canvas.bind_all("<Button-4>",    lambda e: self._canvas.yview_scroll(-1, "units"))
        self._canvas.bind_all("<Button-5>",    lambda e: self._canvas.yview_scroll(1,  "units"))

        card.columnconfigure(0, weight=0, minsize=160)
        card.columnconfigure(1, weight=1)

        def sep(row):
            tk.Frame(card, height=1, bg=SEP).grid(
                row=row, columnspan=2, sticky="ew", pady=7)

        def label(row, text, col=0, colspan=1, **kw):
            tk.Label(card, text=text, font=("Segoe UI", 9, "bold"),
                     bg=CARD_BG, fg=DIM, **kw).grid(
                row=row, column=col, columnspan=colspan,
                sticky="w", pady=(4, 2), padx=(0, 8))

        r = 0

        # ── GitHub Username ───────────────────────────────────────────────────
        label(r, "GitHub Username")
        self.username_var = tk.StringVar()
        tk.Label(card, textvariable=self.username_var,
                 font=("Consolas", 10), bg=CARD_BG, fg=ACCENT).grid(
            row=r, column=1, sticky="e", pady=(4, 2))
        r += 1
        sep(r)
        r += 1

        # ── AI Provider ───────────────────────────────────────────────────────
        label(r, "AI Provider")
        self.provider_var = tk.StringVar()
        self._provider_names = {k: v[0] for k, v in AI_PROVIDERS.items()}
        self._provider_keys  = {v: k for k, v in self._provider_names.items()}

        self._provider_combo = ttk.Combobox(
            card, textvariable=self.provider_var,
            values=list(self._provider_names.values()),
            state="readonly", width=29,
        )
        self._provider_combo.grid(row=r, column=1, sticky="e", pady=(4, 2))
        self._provider_combo.bind("<<ComboboxSelected>>", self._on_provider_change)
        r += 1

        # Free-tier note
        self.provider_note_var = tk.StringVar()
        tk.Label(card, textvariable=self.provider_note_var,
                 font=("Segoe UI", 8), bg=CARD_BG, fg=GREEN,
                 wraplength=260, justify="right").grid(
            row=r, column=1, sticky="e", pady=(0, 4))
        r += 1

        # ── API Key (shown / editable when provider changes) ──────────────────
        label(r, "API Key")
        self._api_key_frame = tk.Frame(card, bg=CARD_BG)
        self._api_key_frame.grid(row=r, column=1, sticky="ew", pady=(4, 2))
        self._api_key_frame.columnconfigure(0, weight=1)

        self.api_key_var = tk.StringVar()
        self._api_key_entry = tk.Entry(
            self._api_key_frame, textvariable=self.api_key_var,
            font=("Consolas", 9), bg=INPUT_BG, fg=MUTED,
            insertbackground="white", relief="flat", bd=0,
            show="•", width=28,
        )
        self._api_key_entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self._api_key_entry.bind("<FocusIn>",  self._on_key_focus_in)
        self._api_key_entry.bind("<KeyRelease>", lambda e: setattr(self, "_api_key_changed", True))

        # Show/hide toggle
        self._show_key_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self._api_key_frame, text="Show", variable=self._show_key_var,
            command=self._toggle_key_visibility,
            font=("Segoe UI", 8), bg=CARD_BG, fg=DIM,
            selectcolor=INPUT_BG, activebackground=CARD_BG,
            relief="flat", bd=0,
        ).grid(row=0, column=1, padx=(6, 0))

        # "Key saved" badge shown when key is unchanged
        self._key_saved_label = tk.Label(
            card, text="🔒 key saved", font=("Segoe UI", 8),
            bg=CARD_BG, fg=DIM,
        )
        r += 1

        # ── Model override ────────────────────────────────────────────────────
        label(r, "Model override")
        self._model_hint_var = tk.StringVar()
        tk.Label(card, textvariable=self._model_hint_var,
                 font=("Segoe UI", 8), bg=CARD_BG, fg=DIM).grid(
            row=r, column=1, sticky="e", pady=(4, 0))
        r += 1

        self.model_var = tk.StringVar()
        self._model_entry = tk.Entry(
            card, textvariable=self.model_var,
            font=("Consolas", 9), bg=INPUT_BG, fg=MUTED,
            insertbackground="white", relief="flat", bd=0, width=32,
        )
        self._model_entry.grid(row=r, column=0, columnspan=2,
                                sticky="ew", pady=(2, 6), ipady=5)
        r += 1
        sep(r)
        r += 1

        # ── Interval slider ───────────────────────────────────────────────────
        label(r, "Auto-Run Interval")
        self.interval_var = tk.IntVar()
        self._interval_lbl = tk.Label(card, text="4 hours",
                                       font=("Segoe UI", 9), bg=CARD_BG, fg=ORANGE)
        self._interval_lbl.grid(row=r, column=1, sticky="e", pady=(4, 2))
        r += 1
        ttk.Scale(card, from_=1, to=24, orient="horizontal",
                  variable=self.interval_var,
                  command=self._on_interval_change).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        r += 1

        # ── Veto slider ───────────────────────────────────────────────────────
        label(r, "Veto Countdown")
        self.veto_var = tk.IntVar()
        self._veto_lbl = tk.Label(card, text="5:00",
                                   font=("Segoe UI", 9), bg=CARD_BG, fg=ORANGE)
        self._veto_lbl.grid(row=r, column=1, sticky="e", pady=(4, 2))
        r += 1
        ttk.Scale(card, from_=MIN_VETO_SECONDS, to=MAX_VETO_SECONDS,
                  orient="horizontal", variable=self.veto_var,
                  command=self._on_veto_change).grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        r += 1
        sep(r)
        r += 1

        # ── Checkboxes ────────────────────────────────────────────────────────
        self.notifications_var = tk.BooleanVar()
        tk.Checkbutton(card, text="Show desktop notifications",
                       variable=self.notifications_var,
                       font=("Segoe UI", 10), bg=CARD_BG, fg=MUTED,
                       selectcolor=INPUT_BG, activebackground=CARD_BG,
                       activeforeground=MUTED).grid(
            row=r, columnspan=2, sticky="w", pady=(0, 4))
        r += 1

        self.startup_var = tk.BooleanVar()
        sc = tk.Checkbutton(card, text="Run agent on Windows startup",
                             variable=self.startup_var,
                             font=("Segoe UI", 10), bg=CARD_BG, fg=MUTED,
                             selectcolor=INPUT_BG, activebackground=CARD_BG,
                             activeforeground=MUTED)
        sc.grid(row=r, columnspan=2, sticky="w", pady=(0, 4))
        if os.name != "nt":
            sc.config(state="disabled")
        r += 1
        sep(r)
        r += 1

        # ── Test buttons ──────────────────────────────────────────────────────
        test_frame = tk.Frame(card, bg=CARD_BG)
        test_frame.grid(row=r, columnspan=2, sticky="ew", pady=(2, 4))

        self.test_github_btn = tk.Button(
            test_frame, text="🔗  Test GitHub",
            font=("Segoe UI", 9), bg=INPUT_BG, fg=MUTED,
            relief="flat", padx=10, pady=5, cursor="hand2",
            activebackground=SEP, bd=0, command=self._test_github,
        )
        self.test_github_btn.pack(side="left")

        self.test_ai_btn = tk.Button(
            test_frame, text="🤖  Test AI API",
            font=("Segoe UI", 9), bg=INPUT_BG, fg=MUTED,
            relief="flat", padx=10, pady=5, cursor="hand2",
            activebackground=SEP, bd=0, command=self._test_ai,
        )
        self.test_ai_btn.pack(side="right")

        # ── Bottom bar: Cancel + Save (always visible, outside scroll) ────────
        bottom = tk.Frame(outer, bg=BG, pady=10)
        bottom.pack(fill="x", side="bottom")

        tk.Button(
            bottom, text="Cancel",
            font=("Segoe UI", 10), bg="#21262d", fg=MUTED,
            relief="flat", padx=22, pady=9, cursor="hand2",
            activebackground=SEP, bd=0,
            command=self.root.destroy,
        ).pack(side="left")

        tk.Button(
            bottom, text="💾  Save Settings",
            font=("Segoe UI", 10, "bold"), bg="#238636", fg="white",
            relief="flat", padx=22, pady=9, cursor="hand2",
            activebackground="#2ea043", bd=0,
            command=self._save,
        ).pack(side="right")

        # Separator above bottom bar
        tk.Frame(outer, height=1, bg=SEP).pack(fill="x", side="bottom")

    # ── Scroll helpers ────────────────────────────────────────────────────────

    def _on_card_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._card_window, width=event.width)

    def _on_mousewheel(self, event):
        # Guard: the scroll event can fire after the canvas widget is destroyed
        # (user scrolls while closing the window). Swallow the TclError silently.
        try:
            if self._canvas.winfo_exists():
                self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    # ── Center window ─────────────────────────────────────────────────────────

    def _center_window(self):
        self.root.update_idletasks()
        W, H = 540, 660
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Cap height to 90% of screen
        H = min(H, int(sh * 0.90))
        x = (sw // 2) - (W // 2)
        y = (sh // 2) - (H // 2)
        self.root.geometry(f"{W}x{H}+{x}+{y}")

    # ── Load saved values into UI ─────────────────────────────────────────────

    def _load_values(self):
        self.username_var.set(self.config.github_username)
        self.interval_var.set(self.config.interval_hours)
        self.veto_var.set(self.config.veto_seconds)
        self.notifications_var.set(self.config.show_notifications)
        self.startup_var.set(_is_agent_in_startup())

        # Provider
        display = self._provider_names.get(
            self.config.ai_provider,
            list(self._provider_names.values())[0],
        )
        self.provider_var.set(display)
        self._update_provider_ui(self.config.ai_provider)

        # API key — show placeholder, not the real key
        self._set_key_placeholder()

        # Model
        self.model_var.set(self.config.ai_model or "")

        self._on_interval_change(None)
        self._on_veto_change(None)

    # ── API key helpers ───────────────────────────────────────────────────────

    def _set_key_placeholder(self):
        """Show a masked placeholder representing the saved key."""
        saved = self.config.ai_api_key or ""
        if saved:
            visible = saved[:4] + "••••••••" + saved[-4:] if len(saved) > 8 else "••••••••"
        else:
            visible = ""
        self.api_key_var.set(visible)
        self._api_key_changed = False
        # Show "key saved" badge, hide entry show-toggle
        self._api_key_entry.config(fg="#8b949e")

    def _on_key_focus_in(self, event):
        """Clear the placeholder when user clicks into the key field."""
        if not self._api_key_changed:
            self.api_key_var.set("")
            self._api_key_entry.config(fg="#c9d1d9", show="•")
            self._api_key_changed = False  # reset; actual typing sets it True

    def _toggle_key_visibility(self):
        self._api_key_entry.config(
            show="" if self._show_key_var.get() else "•"
        )

    def _get_effective_api_key(self) -> str:
        """Return the key to save: new entry if changed, else keep existing."""
        if self._api_key_changed:
            return self.api_key_var.get().strip()
        return self.config.ai_api_key

    # ── Provider change ───────────────────────────────────────────────────────

    def _on_provider_change(self, _event=None):
        display = self.provider_var.get()
        key = self._provider_keys.get(display, "google")
        self._update_provider_ui(key)

        # Prompt user to enter key for the newly selected provider
        self.api_key_var.set("")
        self._api_key_entry.config(fg="#c9d1d9", show="•")
        self._api_key_changed = False  # not changed yet — user must type
        self._api_key_entry.focus_set()

        # Show a hint about what key is needed
        _, _, _, env_var, _ = AI_PROVIDERS[key]
        self._api_key_entry.config(
            # light placeholder styling until user types
        )
        messagebox.showinfo(
            "API Key Required",
            f"You switched to {self._provider_names[key]}.\n\n"
            f"Please enter your API key for this provider.\n"
            f"(Env var: {env_var})",
            parent=self.root,
        )

    def _update_provider_ui(self, key: str):
        """Update note and model hint for the given provider key."""
        if key not in AI_PROVIDERS:
            return
        _, _, default_model, _, note = AI_PROVIDERS[key]
        self.provider_note_var.set(f"ℹ️ {note}")
        self._model_hint_var.set(f"default: {default_model}")

    # ── Slider callbacks ──────────────────────────────────────────────────────

    def _on_interval_change(self, _):
        h = int(self.interval_var.get())
        self._interval_lbl.config(text=f"{h} hour{'s' if h != 1 else ''}")

    def _on_veto_change(self, _):
        s = int(self.veto_var.get())
        m, sec = divmod(s, 60)
        self._veto_lbl.config(text=f"{m}:{sec:02d}")

    # ── Connection tests ──────────────────────────────────────────────────────

    def _build_current_config(self) -> Optional[AgentConfig]:
        """Build an AgentConfig from *current UI values* for testing."""
        display = self.provider_var.get()
        provider_key = self._provider_keys.get(display, "google")
        api_key = self._get_effective_api_key()
        if not api_key:
            messagebox.showerror(
                "Missing API Key",
                "Please enter an API key before testing.",
                parent=self.root,
            )
            return None
        try:
            return AgentConfig(
                github_token=self.config.github_token,
                ai_provider=provider_key,
                ai_api_key=api_key,
                ai_model=self.model_var.get().strip(),
                github_username=self.config.github_username,
                interval_hours=int(self.interval_var.get()),
                veto_seconds=int(self.veto_var.get()),
                show_notifications=self.notifications_var.get(),
                auto_run_on_startup=self.startup_var.get(),
                log_level=self.config.log_level,
                max_api_calls=self.config.max_api_calls,
            )
        except Exception as e:
            messagebox.showerror("Config Error", str(e), parent=self.root)
            return None

    def _test_github(self):
        self.test_github_btn.config(state="disabled", text="Testing…")
        self.root.update()
        try:
            from agent.core import GitHubAgent
            agent = GitHubAgent(self.config)
            success, message = agent.validate_credentials()
            if success:
                messagebox.showinfo("GitHub Test", f"✅ {message}", parent=self.root)
            else:
                messagebox.showerror("GitHub Test", f"❌ {message}", parent=self.root)
        except Exception as e:
            messagebox.showerror("GitHub Test", f"❌ Error: {e}", parent=self.root)
        finally:
            self.test_github_btn.config(state="normal", text="🔗  Test GitHub")

    def _test_ai(self):
        """Test with the current UI values — not the stale saved config."""
        cfg = self._build_current_config()
        if cfg is None:
            return
        self.test_ai_btn.config(state="disabled", text="Testing…")
        self.root.update()
        try:
            from agent.core import AIClient
            client = AIClient(cfg)
            success, message = client.test_connection()
            if success:
                messagebox.showinfo("AI API Test", f"✅ {message}", parent=self.root)
            else:
                messagebox.showerror("AI API Test", f"❌ {message}", parent=self.root)
        except Exception as e:
            messagebox.showerror("AI API Test", f"❌ Error: {e}", parent=self.root)
        finally:
            self.test_ai_btn.config(state="normal", text="🤖  Test AI API")

    # ── Save ──────────────────────────────────────────────────────────────────

    def _save(self):
        display = self.provider_var.get()
        provider_key = self._provider_keys.get(display, "google")
        api_key = self._get_effective_api_key()

        if not api_key:
            messagebox.showerror(
                "Missing API Key",
                "Please enter an API key for the selected provider.",
                parent=self.root,
            )
            self._api_key_entry.focus_set()
            return

        try:
            new_config = AgentConfig(
                github_token=self.config.github_token,
                ai_provider=provider_key,
                ai_api_key=api_key,
                ai_model=self.model_var.get().strip(),
                github_username=self.config.github_username,
                interval_hours=int(self.interval_var.get()),
                veto_seconds=int(self.veto_var.get()),
                show_notifications=self.notifications_var.get(),
                auto_run_on_startup=self.startup_var.get(),
                log_level=self.config.log_level,
                max_api_calls=self.config.max_api_calls,
            )
        except Exception as e:
            messagebox.showerror("Validation Error", str(e), parent=self.root)
            return

        try:
            if os.name == "nt":
                want = self.startup_var.get()
                current = _is_agent_in_startup()
                if want and not current:
                    if not _add_to_startup():
                        messagebox.showerror(
                            "Startup Error",
                            "Failed to add agent to Windows startup.",
                            parent=self.root,
                        )
                        return
                elif not want and current:
                    _remove_from_startup()

            self.config_manager.save(new_config)
            logger.info("Settings saved")

            if self.on_save:
                self.on_save(new_config)

            messagebox.showinfo("Settings", "✅ Settings saved!", parent=self.root)
            try:
                self.root.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self.root.destroy()

        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            messagebox.showerror("Error", f"Failed to save settings:\n{e}", parent=self.root)

    # ── Close ─────────────────────────────────────────────────────────────────

    def _on_close(self):
        # Unbind the global mousewheel handler BEFORE destroying the window.
        # Without this, scroll events that are already queued keep firing and
        # try to call yview_scroll on the destroyed canvas → TclError spam.
        try:
            self.root.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.root.destroy()

    def show(self):
        if self._owns_mainloop:
            self.root.mainloop()


# ── Public entry point ────────────────────────────────────────────────────────

def open_settings(
    config: AgentConfig,
    on_save: Optional[callable] = None,
    parent: Optional[tk.Tk] = None,
):
    """Open the settings window as a child Toplevel — no new mainloop."""
    SettingsWindow(config, on_save, parent)
