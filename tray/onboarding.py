import logging
import tkinter as tk
from tkinter import messagebox, ttk

from agent.config import AgentConfig, ConfigManager
from agent.constants import CONFIG_DIR, AI_PROVIDERS

logger = logging.getLogger(__name__)


class OnboardingWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GitHub Agent — Setup")
        self.root.geometry("520x520")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.root.attributes("-topmost", True)

        # Don't load config here — it doesn't exist yet on first run.
        # ConfigManager is only used in _finish() when we're ready to save.
        self.step = 0
        self.values = {
            "github_token": "",
            "ai_provider": "google",
            "ai_api_key": "",
            "github_username": "",
        }

        self._provider_keys = list(AI_PROVIDERS.keys())
        self._provider_display = {k: v[0] for k, v in AI_PROVIDERS.items()}

        self._create_widgets()
        self._center_window()

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (520 // 2)
        y = (self.root.winfo_screenheight() // 2) - (520 // 2)
        self.root.geometry(f"520x520+{x}+{y}")

    def _create_widgets(self):
        self.content_frame = tk.Frame(self.root, bg="#0d1117")
        self.content_frame.pack(fill="both", expand=True, padx=30, pady=20)
        self._show_step_0()

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _label(self, parent, text, size=10, bold=False, color="#c9d1d9", **kwargs):
        font = ("Segoe UI", size, "bold") if bold else ("Segoe UI", size)
        return tk.Label(parent, text=text, font=font, bg="#0d1117", fg=color, **kwargs)

    # ── Step 0: Welcome ──────────────────────────────────────────────────────
    def _show_step_0(self):
        self._clear_content()
        tk.Label(self.content_frame, text="🤖", font=("Segoe UI", 48),
                 bg="#0d1117", fg="#58a6ff").pack(pady=(10, 8))
        tk.Label(self.content_frame, text="GitHub Contribution Agent",
                 font=("Segoe UI", 20, "bold"), bg="#0d1117", fg="#e6edf3").pack()
        tk.Label(self.content_frame, text="AI-powered improvements for your repositories",
                 font=("Segoe UI", 10), bg="#0d1117", fg="#8b949e").pack(pady=(4, 20))

        for icon, text in [
            ("🔍", "Scans your repositories for improvement opportunities"),
            ("🤖", "Uses free AI APIs to suggest genuine code improvements"),
            ("✅", "You approve every change before it's pushed"),
            ("🔄", "Runs automatically on a schedule you control"),
        ]:
            tk.Label(self.content_frame, text=f"{icon}  {text}",
                     font=("Segoe UI", 10), bg="#0d1117", fg="#c9d1d9").pack(pady=3)

        tk.Button(self.content_frame, text="Get Started →",
                  font=("Segoe UI", 11, "bold"), bg="#238636", fg="white",
                  relief="flat", padx=25, pady=10, cursor="hand2",
                  command=self._show_step_1).pack(pady=25)

    # ── Step 1: GitHub token + username ─────────────────────────────────────
    def _show_step_1(self):
        self._clear_content()
        tk.Label(self.content_frame, text="Step 1 of 2: GitHub Token",
                 font=("Segoe UI", 16, "bold"), bg="#0d1117", fg="#e6edf3").pack(anchor="w")
        tk.Label(self.content_frame, text="Create a Classic Personal Access Token with 'repo' scope",
                 font=("Segoe UI", 9), bg="#0d1117", fg="#8b949e", wraplength=450).pack(anchor="w", pady=(4, 12))

        steps_frame = tk.Frame(self.content_frame, bg="#161b22", padx=12, pady=10)
        steps_frame.pack(fill="x", pady=(0, 12))
        for step in [
            "1.  Go to  github.com/settings/tokens",
            "2.  Click 'Generate new token (classic)' — NOT fine-grained",
            "3.  Give it a name, check the 'repo' scope",
            "4.  Copy the generated token below",
        ]:
            tk.Label(steps_frame, text=step, font=("Segoe UI", 9), bg="#161b22", fg="#c9d1d9",
                     anchor="w").pack(fill="x", pady=1)

        tk.Label(self.content_frame, text="GitHub Token (ghp_...):",
                 font=("Segoe UI", 9, "bold"), bg="#0d1117", fg="#8b949e").pack(anchor="w")
        self.token_entry = tk.Entry(self.content_frame, width=55, font=("Consolas", 10),
                                    bg="#161b22", fg="#c9d1d9", insertbackground="white",
                                    relief="flat", bd=0, show="•")
        self.token_entry.pack(fill="x", pady=(4, 2), ipady=8)

        show_var = tk.BooleanVar()
        def toggle_show():
            self.token_entry.config(show="" if show_var.get() else "•")
        tk.Checkbutton(self.content_frame, text="Show token", variable=show_var,
                       command=toggle_show, font=("Segoe UI", 8),
                       bg="#0d1117", fg="#8b949e", selectcolor="#0d1117",
                       activebackground="#0d1117").pack(anchor="w", pady=(0, 10))

        tk.Label(self.content_frame, text="GitHub Username:",
                 font=("Segoe UI", 9, "bold"), bg="#0d1117", fg="#8b949e").pack(anchor="w")
        self.username_entry = tk.Entry(self.content_frame, width=55, font=("Consolas", 10),
                                       bg="#161b22", fg="#c9d1d9", insertbackground="white",
                                       relief="flat", bd=0)
        self.username_entry.pack(fill="x", pady=(4, 16), ipady=8)

        # Restore values
        if self.values["github_token"]:
            self.token_entry.insert(0, self.values["github_token"])
        if self.values["github_username"]:
            self.username_entry.insert(0, self.values["github_username"])

        self._nav(step=1)

    # ── Step 2: AI Provider ──────────────────────────────────────────────────
    def _show_step_2(self):
        self._clear_content()
        tk.Label(self.content_frame, text="Step 2 of 2: Choose AI Provider",
                 font=("Segoe UI", 16, "bold"), bg="#0d1117", fg="#e6edf3").pack(anchor="w")
        tk.Label(self.content_frame,
                 text="Choose a provider and paste your API key. All options below have a free tier.",
                 font=("Segoe UI", 9), bg="#0d1117", fg="#8b949e", wraplength=450).pack(anchor="w", pady=(4, 12))

        # Provider selector
        provider_frame = tk.Frame(self.content_frame, bg="#0d1117")
        provider_frame.pack(fill="x", pady=(0, 4))
        tk.Label(provider_frame, text="Provider:", font=("Segoe UI", 9, "bold"),
                 bg="#0d1117", fg="#8b949e").pack(side="left")

        self._onboard_provider_var = tk.StringVar(value=self._provider_display.get(self.values["ai_provider"], "Google AI Studio (Gemini)"))
        combo = ttk.Combobox(provider_frame, textvariable=self._onboard_provider_var,
                             values=[self._provider_display[k] for k in self._provider_keys],
                             state="readonly", width=34)
        combo.pack(side="right")
        combo.bind("<<ComboboxSelected>>", self._on_onboard_provider_change)

        self._provider_note_label = tk.Label(self.content_frame, text="",
                                              font=("Segoe UI", 8), bg="#0d1117", fg="#7ee787",
                                              wraplength=450, anchor="w")
        self._provider_note_label.pack(fill="x", pady=(2, 8))

        # Instructions card
        self._instructions_frame = tk.Frame(self.content_frame, bg="#161b22", padx=12, pady=10)
        self._instructions_frame.pack(fill="x", pady=(0, 10))

        tk.Label(self.content_frame, text="API Key:",
                 font=("Segoe UI", 9, "bold"), bg="#0d1117", fg="#8b949e").pack(anchor="w")
        self.ai_key_entry = tk.Entry(self.content_frame, width=55, font=("Consolas", 10),
                                     bg="#161b22", fg="#c9d1d9", insertbackground="white",
                                     relief="flat", bd=0, show="•")
        self.ai_key_entry.pack(fill="x", pady=(4, 2), ipady=8)

        show_var = tk.BooleanVar()
        def toggle_show():
            self.ai_key_entry.config(show="" if show_var.get() else "•")
        tk.Checkbutton(self.content_frame, text="Show key", variable=show_var,
                       command=toggle_show, font=("Segoe UI", 8),
                       bg="#0d1117", fg="#8b949e", selectcolor="#0d1117",
                       activebackground="#0d1117").pack(anchor="w", pady=(0, 8))

        if self.values["ai_api_key"]:
            self.ai_key_entry.insert(0, self.values["ai_api_key"])

        self._update_onboard_instructions(self.values["ai_provider"])
        self._nav(step=2, is_final=True)

    def _on_onboard_provider_change(self, _=None):
        display = self._onboard_provider_var.get()
        key = next((k for k, v in self._provider_display.items() if v == display), "google")
        self.values["ai_provider"] = key
        self._update_onboard_instructions(key)

    def _update_onboard_instructions(self, key: str):
        info = AI_PROVIDERS.get(key)
        if not info:
            return
        _, _, default_model, _, note = info
        self._provider_note_label.config(text=f"ℹ️  {note}  |  Default model: {default_model}")

        for w in self._instructions_frame.winfo_children():
            w.destroy()

        instructions = {
            "google":     ["1. Go to  aistudio.google.com/apikey", "2. Sign in with Google", "3. Click 'Create API Key'", "4. Copy and paste it below"],
            "openrouter": ["1. Go to  openrouter.ai/keys", "2. Create an account", "3. Click 'Create Key'", "4. Copy and paste it below — many free models!"],
            "mistral":    ["1. Go to  console.mistral.ai/api-keys", "2. Sign up or sign in", "3. Create a new API key", "4. Copy and paste it below"],
            "groq":       ["1. Go to  console.groq.com/keys", "2. Sign up with Google or email", "3. Create an API key", "4. Copy and paste it below — very fast!"],
            "together":   ["1. Go to  api.together.xyz/settings/api-keys", "2. Sign up for free $25 credit", "3. Copy your API key", "4. Paste it below"],
            "openai":     ["1. Go to  platform.openai.com/api-keys", "2. Sign in and add billing", "3. Create an API key", "4. Paste it below"],
        }

        for step in instructions.get(key, []):
            tk.Label(self._instructions_frame, text=step, font=("Segoe UI", 9),
                     bg="#161b22", fg="#c9d1d9", anchor="w").pack(fill="x", pady=1)

    # ── Shared nav ───────────────────────────────────────────────────────────
    def _nav(self, step: int, is_final: bool = False):
        btn_frame = tk.Frame(self.content_frame, bg="#0d1117")
        btn_frame.pack(side="bottom", fill="x", pady=(8, 0))

        if step > 1:
            tk.Button(btn_frame, text="← Back", font=("Segoe UI", 10),
                      bg="#21262d", fg="#c9d1d9", relief="flat", padx=20, pady=8,
                      cursor="hand2", command=lambda: self._go_back(step)).pack(side="left")

        label = "Start Agent →" if is_final else "Next →"
        cmd = self._finish if is_final else lambda: self._go_next(step)
        tk.Button(btn_frame, text=label, font=("Segoe UI", 10, "bold"),
                  bg="#238636", fg="white", relief="flat", padx=20, pady=8,
                  cursor="hand2", command=cmd).pack(side="right")

    def _go_back(self, step: int):
        if step == 2:
            self._show_step_1()

    def _go_next(self, step: int):
        if step == 1:
            token = self.token_entry.get().strip()
            username = self.username_entry.get().strip()
            if not token:
                messagebox.showerror("Error", "Please enter your GitHub token")
                return
            if not username:
                messagebox.showerror("Error", "Please enter your GitHub username")
                return
            self.values["github_token"] = token
            self.values["github_username"] = username
            self._show_step_2()

    def _finish(self):
        display = self._onboard_provider_var.get()
        provider_key = next((k for k, v in self._provider_display.items() if v == display), "google")
        api_key = self.ai_key_entry.get().strip()

        if not api_key:
            messagebox.showerror("Error", "Please enter your API key")
            return

        self.values["ai_provider"] = provider_key
        self.values["ai_api_key"] = api_key

        try:
            config = AgentConfig(
                github_token=self.values["github_token"],
                ai_provider=self.values["ai_provider"],
                ai_api_key=self.values["ai_api_key"],
                github_username=self.values["github_username"],
            )
            config_manager = ConfigManager()
            config_manager.save(config)
            logger.info("Onboarding complete - configuration saved")
            self.root.destroy()

            from agent.config import load_config
            from tray.app import TrayApp
            app = TrayApp(load_config())
            app.start()

        except Exception as e:
            logger.error(f"Onboarding failed: {e}")
            messagebox.showerror("Error", f"Failed to save configuration: {e}")

    def show(self):
        self.root.mainloop()


def check_and_show_onboarding() -> bool:
    config_path = CONFIG_DIR / "config.json"
    if not config_path.exists():
        OnboardingWizard().show()
        return True
    return False
