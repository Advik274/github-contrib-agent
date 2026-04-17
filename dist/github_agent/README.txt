GitHub Contribution Agent
=========================

Standalone executable - no Python installation required!

First Run:
----------
1. Double-click github_agent.exe
2. The setup wizard will guide you through:
   - GitHub Personal Access Token
   - AI Provider setup
3. Agent starts in system tray

Auto-Start on Windows:
---------------------
The agent can auto-start when Windows boots.
Run uninstall.bat and select "Yes" to add/remove startup.

Tray Menu (right-click):
------------------------
- Run Now: Trigger a contribution scan
- Settings: Configure AI provider, interval, veto time
- Open Logs: View activity log
- Clear History: Re-scan all files
- Quit: Stop the agent

Files:
------
github_agent.exe - Main executable
config/         - Configuration (created on first run)
logs/           - Activity logs (created on first run)
data/           - Processed file history (created on first run)

Support:
--------
https://github.com/Advik274/github-contrib-agent
