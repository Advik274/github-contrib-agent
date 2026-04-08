import json
import logging
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from agent.config import AgentConfig, ConfigManager
from agent.constants import CONFIG_DIR

logger = logging.getLogger(__name__)


class OnboardingWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("GitHub Agent — Welcome")
        self.root.geometry("520x480")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.root.attributes("-topmost", True)

        self.config_manager = ConfigManager()
        self.step = 0
        self.values = {
            "github_token": "",
            "mistral_api_key": "",
            "github_username": "",
        }

        self._setup_styles()
        self._create_widgets()
        self._center_window()

    def _setup_styles(self):
        self.root.option_add("*Font", "Segoe UI 10")

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (520 // 2)
        y = (self.root.winfo_screenheight() // 2) - (480 // 2)
        self.root.geometry(f"520x480+{x}+{y}")

    def _create_widgets(self):
        self.content_frame = tk.Frame(self.root, bg="#0d1117")
        self.content_frame.pack(fill="both", expand=True, padx=30, pady=20)
        self._show_step_0()

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _show_step_0(self):
        self._clear_content()

        tk.Label(
            self.content_frame,
            text="🤖",
            font=("Segoe UI", 48),
            bg="#0d1117",
            fg="#58a6ff",
        ).pack(pady=(20, 10))

        tk.Label(
            self.content_frame,
            text="GitHub Contribution Agent",
            font=("Segoe UI", 20, "bold"),
            bg="#0d1117",
            fg="#e6edf3",
        ).pack()

        tk.Label(
            self.content_frame,
            text="AI-powered improvements for your repositories",
            font=("Segoe UI", 10),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(pady=(5, 30))

        features = [
            ("🔍", "Scans your repositories"),
            ("🤖", "Uses AI to suggest improvements"),
            ("✅", "You approve before any changes"),
            ("🔄", "Runs automatically every 4 hours"),
        ]

        for icon, text in features:
            tk.Label(
                self.content_frame,
                text=f"{icon}  {text}",
                font=("Segoe UI", 11),
                bg="#0d1117",
                fg="#c9d1d9",
            ).pack(pady=4)

        btn_frame = tk.Frame(self.content_frame, bg="#0d1117")
        btn_frame.pack(pady=30)

        tk.Button(
            btn_frame,
            text="Get Started →",
            font=("Segoe UI", 11, "bold"),
            bg="#238636",
            fg="white",
            relief="flat",
            padx=25,
            pady=10,
            cursor="hand2",
            command=self._show_step_1,
        ).pack()

    def _show_step_1(self):
        self._clear_content()

        self.step = 1

        tk.Label(
            self.content_frame,
            text="Step 1: GitHub Token",
            font=("Segoe UI", 16, "bold"),
            bg="#0d1117",
            fg="#e6edf3",
        ).pack(anchor="w", pady=(0, 5))

        tk.Label(
            self.content_frame,
            text="Create a Personal Access Token with 'repo' scope",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#8b949e",
            wraplength=450,
        ).pack(anchor="w", pady=(0, 15))

        tk.Label(
            self.content_frame,
            text="1. Go to github.com/settings/tokens",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="2. Click 'Generate new token (classic)'",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="3. Check the 'repo' scope",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="4. Copy the generated token",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w", pady=(0, 15))

        tk.Label(
            self.content_frame,
            text="Your GitHub Token:",
            font=("Segoe UI", 9, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w")

        self.token_entry = tk.Entry(
            self.content_frame,
            width=50,
            font=("Consolas", 10),
            bg="#161b22",
            fg="#c9d1d9",
            insertbackground="white",
            relief="flat",
            bd=0,
        )
        self.token_entry.pack(fill="x", pady=(5, 5), ipady=8)

        token_frame = tk.Frame(self.content_frame, bg="#21262d", padx=2, pady=2)
        token_frame.pack(fill="x")
        self.token_entry.config(bg="#161b22")

        tk.Label(
            self.content_frame,
            text="GitHub Username:",
            font=("Segoe UI", 9, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w", pady=(15, 0))

        self.username_entry = tk.Entry(
            self.content_frame,
            width=50,
            font=("Consolas", 10),
            bg="#161b22",
            fg="#c9d1d9",
            insertbackground="white",
            relief="flat",
            bd=0,
        )
        self.username_entry.pack(fill="x", pady=(5, 20), ipady=8)

        self._add_nav_buttons(step=1)

    def _show_step_2(self):
        self._clear_content()

        self.step = 2

        tk.Label(
            self.content_frame,
            text="Step 2: Mistral API Key",
            font=("Segoe UI", 16, "bold"),
            bg="#0d1117",
            fg="#e6edf3",
        ).pack(anchor="w", pady=(0, 5))

        tk.Label(
            self.content_frame,
            text="Get your free API key from Mistral",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#8b949e",
            wraplength=450,
        ).pack(anchor="w", pady=(0, 15))

        tk.Label(
            self.content_frame,
            text="1. Go to console.mistral.ai",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="2. Create an account or sign in",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="3. Go to API Keys section",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w")
        tk.Label(
            self.content_frame,
            text="4. Create a new API key and copy it",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#c9d1d9",
        ).pack(anchor="w", pady=(0, 15))

        tk.Label(
            self.content_frame,
            text="Your Mistral API Key:",
            font=("Segoe UI", 9, "bold"),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w")

        self.mistral_entry = tk.Entry(
            self.content_frame,
            width=50,
            font=("Consolas", 10),
            bg="#161b22",
            fg="#c9d1d9",
            insertbackground="white",
            relief="flat",
            bd=0,
        )
        self.mistral_entry.pack(fill="x", pady=(5, 20), ipady=8)

        self._add_nav_buttons(step=2)

    def _show_step_3(self):
        self._clear_content()

        self.step = 3

        tk.Label(
            self.content_frame,
            text="Step 3: Ready to Go!",
            font=("Segoe UI", 16, "bold"),
            bg="#0d1117",
            fg="#e6edf3",
        ).pack(anchor="w", pady=(0, 5))

        tk.Label(
            self.content_frame,
            text="Review your settings before we start",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#8b949e",
            wraplength=450,
        ).pack(anchor="w", pady=(0, 20))

        review_card = tk.Frame(self.content_frame, bg="#161b22", padx=15, pady=15)
        review_card.pack(fill="both", expand=True)

        self._add_review_row(
            review_card, "GitHub Username:", self.values["github_username"]
        )
        self._add_review_row(
            review_card, "GitHub Token:", self.values["github_token"][:20] + "..."
        )
        self._add_review_row(
            review_card, "Mistral API Key:", self.values["mistral_api_key"][:20] + "..."
        )

        separator = tk.Frame(review_card, height=1, bg="#30363d")
        separator.pack(fill="x", pady=10)

        self._add_review_row(review_card, "Auto-run Interval:", "Every 4 hours")
        self._add_review_row(review_card, "Veto Time:", "5 minutes (auto-push)")

        tk.Label(review_card, text="", bg="#161b22").pack()

        warning_frame = tk.Frame(review_card, bg="#1f1e1c", padx=10, pady=8)
        warning_frame.pack(fill="x")

        tk.Label(
            warning_frame,
            text="⚠️  Important",
            font=("Segoe UI", 9, "bold"),
            bg="#1f1e1c",
            fg="#d29922",
        ).pack(anchor="w")

        tk.Label(
            warning_frame,
            text="Your config.json will be saved locally. Never share your API keys.",
            font=("Segoe UI", 8),
            bg="#1f1e1c",
            fg="#c9d1d9",
            wraplength=420,
        ).pack(anchor="w")

        self._add_nav_buttons(step=3, is_final=True)

    def _add_review_row(self, parent, label, value):
        row = tk.Frame(parent, bg="#161b22")
        row.pack(fill="x", pady=2)

        tk.Label(
            row, text=label, font=("Segoe UI", 9), bg="#161b22", fg="#8b949e"
        ).pack(side="left")

        tk.Label(
            row, text=value, font=("Consolas", 9), bg="#161b22", fg="#79c0ff"
        ).pack(side="right")

    def _add_nav_buttons(self, step, is_final=False):
        btn_frame = tk.Frame(self.content_frame, bg="#0d1117")
        btn_frame.pack(side="bottom", fill="x", pady=10)

        if step > 1:
            tk.Button(
                btn_frame,
                text="← Back",
                font=("Segoe UI", 10),
                bg="#21262d",
                fg="#c9d1d9",
                relief="flat",
                padx=20,
                pady=8,
                cursor="hand2",
                command=lambda: self._go_back(step),
            ).pack(side="left")

        if is_final:
            tk.Button(
                btn_frame,
                text="Start Agent →",
                font=("Segoe UI", 10, "bold"),
                bg="#238636",
                fg="white",
                relief="flat",
                padx=20,
                pady=8,
                cursor="hand2",
                command=self._finish,
            ).pack(side="right")
        else:
            tk.Button(
                btn_frame,
                text="Next →",
                font=("Segoe UI", 10, "bold"),
                bg="#238636",
                fg="white",
                relief="flat",
                padx=20,
                pady=8,
                cursor="hand2",
                command=lambda: self._go_next(step),
            ).pack(side="right")

    def _go_back(self, step):
        if step == 2:
            self._show_step_1()
        elif step == 3:
            self._show_step_2()

    def _go_next(self, step):
        if step == 1:
            github_token = self.token_entry.get().strip()
            github_username = self.username_entry.get().strip()

            if not github_token:
                messagebox.showerror("Error", "Please enter your GitHub token")
                return
            if not github_username:
                messagebox.showerror("Error", "Please enter your GitHub username")
                return

            self.values["github_token"] = github_token
            self.values["github_username"] = github_username
            self._show_step_2()

        elif step == 2:
            mistral_key = self.mistral_entry.get().strip()

            if not mistral_key:
                messagebox.showerror("Error", "Please enter your Mistral API key")
                return

            self.values["mistral_api_key"] = mistral_key
            self._show_step_3()

    def _finish(self):
        try:
            config = AgentConfig(
                github_token=self.values["github_token"],
                mistral_api_key=self.values["mistral_api_key"],
                github_username=self.values["github_username"],
            )

            self.config_manager.save(config)
            logger.info("Onboarding complete - configuration saved")

            self.root.destroy()

            from tray.app import TrayApp
            from agent.config import load_config

            config = load_config()
            app = TrayApp(config)
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
