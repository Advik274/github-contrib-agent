# 🤖 GitHub Contribution Agent

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-35%20passing-brightgreen.svg)](tests/)

> An autonomous agent that keeps your GitHub contribution streak alive by scanning your repos, finding genuine improvements with AI, and only pushing changes **you approve**.

---

## ✨ Features

| | |
|---|---|
| 🟢 **System Tray** | Runs silently in your taskbar |
| 🔍 **Smart Scanning** | Scores files by improvement potential (TODOs, stubs, missing docstrings) |
| 🤖 **Any AI Provider** | Google AI Studio, Groq, OpenRouter, Mistral, OpenAI — your choice |
| ✅ **Your Control** | Review & approve every change before it's pushed |
| ⏰ **Auto-Schedule** | Runs every 4 hours (configurable) |
| 🔔 **Toast Notifications** | Non-intrusive popups with countdown timer |
| ⚙️ **Settings GUI** | Change provider, interval, veto time without editing files |
| 🔐 **Secure** | Keys stored locally, never shared |

---

## 🚀 Quick Start

### Option 1: Standalone Executable (Recommended)

Build a standalone `.exe` that runs without Python:

```bat
install.bat
```

- Choose "Yes" to auto-start with Windows
- The standalone exe will be built in `dist\github_agent\`
- Copy the folder anywhere and run `github_agent.exe`
- **No Python required on target machine**

### Option 2: Python Version

```bat
git clone https://github.com/Advik274/github-contrib-agent.git
cd github-contrib-agent
start_agent.bat
```

### Linux / macOS

```bash
git clone https://github.com/Advik274/github-contrib-agent.git
cd github-contrib-agent
chmod +x install.sh && ./install.sh
python main.py
```

On first run a **setup wizard** guides you through GitHub token + AI provider setup.

---

## 🤖 Supported AI Providers

All providers use the same OpenAI-compatible API — switch anytime from the Settings menu.

| Provider | Free Tier | Best For |
|---|---|---|
| **Google AI Studio** ⭐ | 15 req/min, 1M tokens/day | Best free tier, recommended |
| **Groq** | 6,000 req/day | Fastest inference |
| **OpenRouter** | Many free models | Model variety |
| **Mistral AI** | 1 req/s | Good quality free tier |
| **Together AI** | $25 free credit | Open-source models |
| **OpenAI** | Paid only | GPT-4o-mini |

### Getting a Free API Key

**Google AI Studio (recommended):**
1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with Google → Create API Key → Copy it

**Groq:**
1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Sign up → Create API key → Copy it

---

## 📋 API Keys Required

### GitHub Personal Access Token

> ⚠️ Use a **Classic PAT** (not Fine-Grained). Fine-Grained PATs don't support the Contents API.

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. **Generate new token (classic)** — check `repo` scope
3. Copy and keep it safe

---

## ⚙️ Configuration

Settings are stored in `config/config.json`. Edit via **Settings GUI** (right-click tray icon) or directly:

```json
{
  "github_token": "ghp_xxxxx",
  "ai_provider": "google",
  "ai_api_key": "your_api_key_here",
  "ai_model": "",
  "github_username": "your_username",
  "interval_hours": 4,
  "veto_seconds": 300,
  "show_notifications": true,
  "auto_run_on_startup": true
}
```

**Migrating from the old Mistral-only version?** Your old `config.json` with `mistral_api_key` is automatically migrated — just run the agent and it'll work.

### Environment Variables

```bash
export GITHUB_TOKEN=ghp_xxxxx
export GOOGLE_API_KEY=your_key   # or GROQ_API_KEY, OPENROUTER_API_KEY, etc.
export GITHUB_USERNAME=your_username
```

---

## 🖥️ Tray Menu

Right-click the tray icon to access:

| Item | Action |
|---|---|
| ▶ **Run Now** | Immediately trigger a contribution scan |
| ⚙️ **Settings** | Open the settings GUI |
| 📋 **Open Logs** | View the activity log |
| 🗑️ **Clear History** | Reset processed-files list (re-scan everything) |
| ❌ **Quit** | Stop the agent |

**Icon colours:**
🟢 Idle · 🟠 Analyzing · 🔵 Pushing · 🔵 Review needed · 🔴 Error

---

## 🔄 How It Works

```
1. Fetch your owned (non-forked, non-archived) repos
        ↓
2. Score files by improvement potential
   (TODOs, missing docstrings, stubs, FIXMEs, etc.)
        ↓
3. Pick the highest-scoring unprocessed file
        ↓
4. Ask your chosen AI for ONE small, focused improvement
        ↓
5. Show toast notification — Approve / View Diff / Reject
        ↓
6. Auto-push after veto countdown (default 5 min)
        ↓
7. ✅ Green contribution square on GitHub!
```

---

## 🧪 Development

```bash
pip install -r requirements-dev.txt
pytest              # run 35 tests
black .             # format
isort .
ruff check .
```

---

## 📦 Building Standalone Executable

### Build Separately

```bat
build_exe.bat
```

The standalone exe will be created in `dist\github_agent\github_agent.exe`

### Uninstall

```bat
uninstall.bat
```

Removes:
- Agent from Windows startup
- Optionally removes data files and exe folder

---

## 🖥️ Auto-Start on Windows Boot

### Option 1: During Installation (Recommended)

When you run `install.bat`, it will ask:
```
Do you want the agent to start automatically when Windows boots?
   [Y] Yes - Start with Windows
   [N] No  - Manual start only
```

Select **Y** and the agent will automatically start when Windows boots.

### Option 2: Add After Installation

**Method A: Using uninstall.bat**
```bat
# Run uninstall.bat and select the startup option
# This will add the registry entry for you
```

**Method B: Startup Folder**
1. Press `Win + R`
2. Type `shell:startup` and press Enter
3. Create a shortcut to `github_agent.exe`
4. That's it! Agent will start on Windows boot

**Method C: Registry Editor**
1. Press `Win + R`
2. Type `regedit` and press Enter
3. Navigate to:
   ```
   HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
   ```
4. Right-click → New → String Value
5. Name: `GitHubContributionAgent`
6. Value: `"C:\path\to\github_agent.exe"`
7. Click OK and restart Windows

### Option 3: Python Version Auto-Start

If using the Python version (not the standalone exe):

1. Press `Win + R`
2. Type `shell:startup` and press Enter
3. Create a shortcut to `start_agent.bat`
4. Agent will start on Windows boot

### Removing from Startup

Simply run `uninstall.bat` or:
1. Press `Win + R`
2. Type `regedit`
3. Navigate to `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`
4. Delete the `GitHubContributionAgent` entry

---

## 🤝 Contributing

PRs welcome! Please run `pytest` before submitting.

---

## 📜 License

MIT — see [LICENSE](LICENSE)

---

Made with ❤️ by Arnav
