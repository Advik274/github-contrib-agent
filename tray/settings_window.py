import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from agent.config import AgentConfig, get_config_manager
from agent.constants import MAX_VETO_SECONDS, MIN_VETO_SECONDS

logger = logging.getLogger(__name__)

STARTUP_FILENAME = "GitHub Agent Agent.bat"
STARTUP_FOLDER = os.path.join(
    os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
)


def _get_agent_bat_path() -> str:
    return os.path.join(STARTUP_FOLDER, STARTUP_FILENAME)


def _is_agent_in_startup() -> bool:
    return os.path.exists(_get_agent_bat_path())


def _add_to_startup():
    try:
        bat_path = _get_agent_bat_path()
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        python_exe = sys.executable
        main_py = os.path.join(script_dir, "main.py")
        batch_content = (
            f'@echo off\ncd /d "{script_dir}"\nstart "" "{python_exe}" "{main_py}"\n'
        )

        with open(bat_path, "w") as f:
            f.write(batch_content)

        logger.info(f"Added agent to Windows startup: {bat_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to add to startup: {e}")
        return False


def _remove_from_startup():
    try:
        bat_path = _get_agent_bat_path()
        if os.path.exists(bat_path):
            os.remove(bat_path)
            logger.info("Removed agent from Windows startup")
        return True
    except Exception as e:
        logger.error(f"Failed to remove from startup: {e}")
        return False


class SettingsWindow:
    def __init__(self, config: AgentConfig, on_save: Optional[callable] = None):
        self.config = config
        self.config_manager = get_config_manager()
        self.on_save = on_save
        self.root = tk.Tk()
        self.root.title("GitHub Agent — Settings")
        self.root.geometry("480x420")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d1117")
        self.root.attributes("-topmost", True)

        self._setup_styles()
        self._create_widgets()
        self._load_values()
        self._center_window()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background="#0d1117")
        style.configure("Card.TFrame", background="#161b22", relief="flat")

        style.configure(
            "Header.TLabel",
            background="#0d1117",
            foreground="#e6edf3",
            font=("Segoe UI", 14, "bold"),
        )

        style.configure(
            "SubHeader.TLabel",
            background="#0d1117",
            foreground="#8b949e",
            font=("Segoe UI", 9),
        )

        style.configure(
            "Field.TLabel",
            background="#161b22",
            foreground="#c9d1d9",
            font=("Segoe UI", 10),
        )

        style.configure(
            "Value.TLabel",
            background="#161b22",
            foreground="#79c0ff",
            font=("Consolas", 10),
        )

        style.configure(
            "Primary.TButton",
            background="#238636",
            foreground="white",
            font=("Segoe UI", 10, "bold"),
            padding=(20, 8),
        )

        style.configure(
            "Secondary.TButton",
            background="#21262d",
            foreground="#c9d1d9",
            font=("Segoe UI", 10),
            padding=(20, 8),
        )

        style.configure("TScale", background="#161b22")

    def _create_widgets(self):
        main_frame = tk.Frame(self.root, bg="#0d1117", padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        tk.Label(
            main_frame,
            text="⚙️  Settings",
            font=("Segoe UI", 16, "bold"),
            bg="#0d1117",
            fg="#e6edf3",
        ).pack(anchor="w", pady=(0, 5))

        tk.Label(
            main_frame,
            text="Configure your GitHub Contribution Agent",
            font=("Segoe UI", 9),
            bg="#0d1117",
            fg="#8b949e",
        ).pack(anchor="w", pady=(0, 15))

        settings_card = tk.Frame(main_frame, bg="#161b22", padx=15, pady=15)
        settings_card.pack(fill="both", expand=True)

        row = 0

        tk.Label(
            settings_card,
            text="GitHub Username",
            font=("Segoe UI", 9, "bold"),
            bg="#161b22",
            fg="#8b949e",
        ).grid(row=row, column=0, sticky="w", pady=(0, 5))
        self.username_var = tk.StringVar()
        username_label = tk.Label(
            settings_card,
            textvariable=self.username_var,
            font=("Consolas", 10),
            bg="#161b22",
            fg="#79c0ff",
        )
        username_label.grid(row=row, column=1, sticky="e", pady=(0, 5))
        row += 1

        separator = tk.Frame(settings_card, height=1, bg="#30363d")
        separator.grid(row=row, columnspan=2, sticky="ew", pady=10)
        row += 1

        tk.Label(
            settings_card,
            text="Auto-Run Interval",
            font=("Segoe UI", 9, "bold"),
            bg="#161b22",
            fg="#8b949e",
        ).grid(row=row, column=0, sticky="w", pady=(0, 5))
        self.interval_var = tk.IntVar()
        self.interval_value_label = tk.Label(
            settings_card,
            text="4 hours",
            font=("Segoe UI", 9),
            bg="#161b22",
            fg="#f0883e",
        )
        self.interval_value_label.grid(row=row, column=1, sticky="e", pady=(0, 5))
        row += 1

        self.interval_slider = ttk.Scale(
            settings_card,
            from_=1,
            to=24,
            orient="horizontal",
            length=300,
            variable=self.interval_var,
            command=self._on_interval_change,
        )
        self.interval_slider.grid(row=row, columnspan=2, sticky="ew", pady=(0, 15))
        row += 1

        tk.Label(
            settings_card,
            text="Auto-Push Veto Time",
            font=("Segoe UI", 9, "bold"),
            bg="#161b22",
            fg="#8b949e",
        ).grid(row=row, column=0, sticky="w", pady=(0, 5))
        self.veto_var = tk.IntVar()
        self.veto_value_label = tk.Label(
            settings_card, text="5:00", font=("Segoe UI", 9), bg="#161b22", fg="#f0883e"
        )
        self.veto_value_label.grid(row=row, column=1, sticky="e", pady=(0, 5))
        row += 1

        self.veto_slider = ttk.Scale(
            settings_card,
            from_=MIN_VETO_SECONDS,
            to=MAX_VETO_SECONDS,
            orient="horizontal",
            length=300,
            variable=self.veto_var,
            command=self._on_veto_change,
        )
        self.veto_slider.grid(row=row, columnspan=2, sticky="ew", pady=(0, 15))
        row += 1

        separator2 = tk.Frame(settings_card, height=1, bg="#30363d")
        separator2.grid(row=row, columnspan=2, sticky="ew", pady=10)
        row += 1

        self.notifications_var = tk.BooleanVar()
        notifications_check = tk.Checkbutton(
            settings_card,
            text="Show desktop notifications",
            variable=self.notifications_var,
            font=("Segoe UI", 10),
            bg="#161b22",
            fg="#c9d1d9",
            selectcolor="#21262d",
            activebackground="#161b22",
            activeforeground="#c9d1d9",
        )
        notifications_check.grid(row=row, columnspan=2, sticky="w", pady=(0, 5))
        row += 1

        self.startup_var = tk.BooleanVar()
        startup_check = tk.Checkbutton(
            settings_card,
            text="Run agent on Windows startup",
            variable=self.startup_var,
            font=("Segoe UI", 10),
            bg="#161b22",
            fg="#c9d1d9",
            selectcolor="#21262d",
            activebackground="#161b22",
            activeforeground="#c9d1d9",
        )
        startup_check.grid(row=row, columnspan=2, sticky="w", pady=(0, 5))
        row += 1

        separator3 = tk.Frame(settings_card, height=1, bg="#30363d")
        separator3.grid(row=row, columnspan=2, sticky="ew", pady=10)
        row += 1

        self.test_github_btn = tk.Button(
            settings_card,
            text="🔗  Test GitHub Connection",
            font=("Segoe UI", 9),
            bg="#21262d",
            fg="#c9d1d9",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._test_github,
        )
        self.test_github_btn.grid(row=row, column=0, sticky="w", pady=(0, 5))

        self.test_mistral_btn = tk.Button(
            settings_card,
            text="🤖  Test Mistral API",
            font=("Segoe UI", 9),
            bg="#21262d",
            fg="#c9d1d9",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._test_mistral,
        )
        self.test_mistral_btn.grid(row=row, column=1, sticky="e", pady=(0, 5))

        button_frame = tk.Frame(main_frame, bg="#0d1117")
        button_frame.pack(fill="x", pady=(15, 0))

        tk.Button(
            button_frame,
            text="Cancel",
            font=("Segoe UI", 10),
            bg="#21262d",
            fg="#c9d1d9",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.root.destroy,
        ).pack(side="left")

        tk.Button(
            button_frame,
            text="Save Settings",
            font=("Segoe UI", 10, "bold"),
            bg="#238636",
            fg="white",
            relief="flat",
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._save,
        ).pack(side="right")

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (480 // 2)
        y = (self.root.winfo_screenheight() // 2) - (420 // 2)
        self.root.geometry(f"480x420+{x}+{y}")

    def _load_values(self):
        self.username_var.set(self.config.github_username)
        self.interval_var.set(self.config.interval_hours)
        self.veto_var.set(self.config.veto_seconds)
        self.notifications_var.set(self.config.show_notifications)
        self.startup_var.set(_is_agent_in_startup())
        self._on_interval_change(None)
        self._on_veto_change(None)

    def _on_interval_change(self, _):
        hours = int(self.interval_var.get())
        self.interval_value_label.config(
            text=f"{hours} hour{'s' if hours != 1 else ''}"
        )

    def _on_veto_change(self, _):
        seconds = int(self.veto_var.get())
        minutes, secs = divmod(seconds, 60)
        self.veto_value_label.config(text=f"{minutes}:{secs:02d}")

    def _test_github(self):
        self.test_github_btn.config(state="disabled", text="Testing...")
        self.root.update()

        try:
            from agent.core import GitHubAgent

            agent = GitHubAgent(self.config)
            success, message = agent.validate_credentials()

            if success:
                messagebox.showinfo("Connection Test", f"✅ GitHub: {message}")
            else:
                messagebox.showerror("Connection Test", f"❌ GitHub: {message}")
        except Exception as e:
            messagebox.showerror("Connection Test", f"❌ Error: {e}")
        finally:
            self.test_github_btn.config(
                state="normal", text="🔗  Test GitHub Connection"
            )

    def _test_mistral(self):
        self.test_mistral_btn.config(state="disabled", text="Testing...")
        self.root.update()

        try:
            from mistralai import Mistral

            client = Mistral(api_key=self.config.mistral_api_key)
            client.chat.complete(
                model="mistral-small",
                messages=[{"role": "user", "content": "Hi"}],
            )
            messagebox.showinfo(
                "Connection Test", "✅ Mistral API: Connection successful!"
            )
        except Exception as e:
            messagebox.showerror("Connection Test", f"❌ Mistral API: {e}")
        finally:
            self.test_mistral_btn.config(state="normal", text="🤖  Test Mistral API")

    def _save(self):
        new_config = AgentConfig(
            github_token=self.config.github_token,
            mistral_api_key=self.config.mistral_api_key,
            github_username=self.config.github_username,
            interval_hours=int(self.interval_var.get()),
            veto_seconds=int(self.veto_var.get()),
            show_notifications=self.notifications_var.get(),
            auto_run_on_startup=self.startup_var.get(),
            log_level=self.config.log_level,
            max_api_calls=self.config.max_api_calls,
        )

        try:
            startup_wanted = self.startup_var.get()
            startup_current = _is_agent_in_startup()

            if startup_wanted and not startup_current:
                if not _add_to_startup():
                    messagebox.showerror(
                        "Startup Error", "Failed to add agent to Windows startup"
                    )
                    return
            elif not startup_wanted and startup_current:
                _remove_from_startup()

            self.config_manager.save(new_config)
            logger.info("Settings saved successfully")

            if self.on_save:
                self.on_save(new_config)

            messagebox.showinfo("Settings", "✅ Settings saved successfully!")
            self.root.destroy()
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def _on_close(self):
        self.root.destroy()

    def show(self):
        self.root.mainloop()


def open_settings(config: AgentConfig, on_save: Optional[callable] = None):
    settings = SettingsWindow(config, on_save)
    settings.show()
