# 🤖 GitHub Contribution Agent

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License">
  <img src="https://img.shields.io/badge/Status-Production%20Ready-brightgreen.svg" alt="Status">
</p>

> An AI-powered background agent that keeps your GitHub contributions streak alive by analyzing your repos and proposing meaningful improvements — all under your control.

**No more empty contribution squares.** This agent runs silently in your system tray, uses Mistral AI to find improvements in your code, and only pushes changes you approve.

---

## ✨ Features

| | |
|---|---|
| 🟢 **System Tray** | Lives quietly in your taskbar, barely noticeable |
| 🔍 **Smart Scanning** | Analyzes Python, Java, C, C++, JS, TS, Markdown files |
| 🤖 **AI-Powered** | Mistral AI generates genuine improvements |
| ✅ **Your Control** | Review & approve every change before push |
| ⏰ **Auto-Schedule** | Runs every 4 hours (configurable) |
| 🔔 **Toast Notifications** | Non-intrusive popups with countdown timer |
| ⚙️ **Settings GUI** | Easy configuration without editing JSON |
| 🔐 **Secure** | Local config, never shares your keys |

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
git clone https://github.com/YOUR_USERNAME/github-contribution-agent.git
cd github-contribution-agent
pip install -r requirements.txt
```

### 2. Run the Agent

```bash
python main.py
```

On first run, a **setup wizard** will guide you:
1. Enter your GitHub Personal Access Token
2. Enter your Mistral API Key  
3. Click "Start Agent"

### 3. That's It!

The agent will:
- Start analyzing your repos
- Show a toast notification when ready
- Auto-push after 5 minutes (or approve/reject immediately)

---

## 📋 API Keys Setup

### GitHub Personal Access Token

> **Important**: Use a **Classic PAT** (not Fine-Grained). Fine-Grained PATs do not support the Contents API required for pushing commits.

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
2. Click **"Generate new token (classic)"** — not "Generate new token"
3. Give it a name (e.g., `contribution-agent`)
4. Check the **`repo`** scope (full control of repositories)
5. Copy and save the token securely

### Mistral API Key

1. Go to [console.mistral.ai](https://console.mistral.ai)
2. Sign up or log in
3. Navigate to **API Keys**
4. Create a new key and copy it

> ⚠️ **Security Note**: Your `config/config.json` contains sensitive keys and is excluded from git via `.gitignore`.

---

## 🖥️ Tray Menu

**Right-click the tray icon** to access:

| Menu Item | Description |
|-----------|-------------|
| ▶ **Run Now** | Manually trigger a contribution scan |
| ⚙️ **Settings** | Open settings GUI |
| 📋 **Open Logs** | View activity log |
| ❌ **Quit** | Stop the agent |

**Tray Icon Colors:**

| Color | Status |
|-------|--------|
| 🟢 Green | Idle — waiting for next run |
| 🟠 Orange | Working — analyzing repos |
| 🔵 Blue | Pushing — committing changes |
| 🔴 Red | Error — check logs |

---

## 🔄 How It Works

```
┌─────────────────────────────────────────────────────────┐
│                     GitHub Agent                         │
├─────────────────────────────────────────────────────────┤
│  1. Fetch your repos (non-forked)                       │
│                      ↓                                   │
│  2. Scan files for improvement opportunities           │
│  (TODOs, docstrings, typos, comments)                  │
│                      ↓                                   │
│  3. Ask Mistral AI to suggest a change                │
│                      ↓                                   │
│  4. Show toast notification with preview               │
│                      ↓                                   │
│  5. You: Approve ✗ | Reject | View Diff               │
│                      ↓                                   │
│  6. (Auto-push after 5 min timeout)                    │
│                      ↓                                   │
│  7. ✅ Green contribution square on GitHub!            │
└─────────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration

### Settings GUI

Click **⚙️ Settings** in the tray menu to:
- Adjust auto-run interval (1-24 hours)
- Change veto countdown (30s - 60min)
- Toggle notifications
- Test API connections

### Manual Config File

Edit `config/config.json`:

```json
{
  "github_token": "ghp_xxxxx",
  "mistral_api_key": "mistral_xxxxx",
  "github_username": "your_username",
  "interval_hours": 4,
  "veto_seconds": 300,
  "show_notifications": true,
  "auto_run_on_startup": true
}
```

### Environment Variables

```bash
export GITHUB_TOKEN=ghp_xxxxx
export MISTRAL_API_KEY=mistral_xxxxx
export GITHUB_USERNAME=your_username
```

---

## 💻 Auto-Start on Windows

1. Press `Win + R`, type `shell:startup`, Enter
2. Right-click → **New → Shortcut**
3. Browse to `start_agent.bat` in this folder
4. Done! Agent starts silently on login

---

## 🧪 Development

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest

# Format code
black .
isort .

# Type check
mypy agent/

# Lint
ruff check .
```

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Make your changes
4. Run tests (`pytest`)
5. Submit a pull request

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Mistral AI](https://mistral.ai) — for the powerful language model
- [pystray](https://pystray.readthedocs.io/) — system tray integration
- [Pillow](https://pillow.readthedocs.io/) — image processing

---

<p align="center">
  Made with ❤️ for developers who want to keep their contribution streak alive
</p>
