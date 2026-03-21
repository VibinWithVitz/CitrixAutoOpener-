# Citrix Auto-Login v2: How It All Works

## The Big Picture

This automation replaces the tedious daily routine of:
1. Opening Chrome → navigating to the Citrix URL
2. Typing your username and password
3. Waiting for the Authenticator push
4. Going back to Chrome after approving
5. Clicking on each Citrix app to launch it

Instead, you press **one keyboard shortcut**, tap **Approve + Face ID** on your phone, and all your apps launch automatically. You get macOS notifications at each stage — no need to watch a Terminal window.

---

## The Technology Stack

### Python
The scripting language that ties everything together. It's pre-installed on every Mac.

### Playwright
A browser automation library that **controls Chromium programmatically**. Unlike the v1 Selenium approach, Playwright auto-manages its own browser — no more ChromeDriver version mismatches. It uses a persistent browser context so cookies and sessions survive between runs.

### macOS Keychain
Your Mac's built-in encrypted credential vault. Your password is encrypted and protected by your Mac's login credentials — never stored in plain text.

### YAML Config File
A human-readable config file at `~/.citrix-autologin.yaml` that stores your Citrix URL, app list, timing settings, and optional named profiles. No need to edit Python source code.

### macOS Notifications
The script sends native macOS notifications via `osascript` (AppleScript) at key stages — "Check your phone", "All apps launched!", and error messages. No Terminal window needed.

### Automator Quick Action
A built-in macOS feature that connects your keyboard shortcut to running the Python script silently in the background.

---

## Architecture (v2)

```
citrix_autologin/
├── __init__.py       # Package marker
├── __main__.py       # Enables `python3 -m citrix_autologin`
├── main.py           # Entry point: PID lock, arg parsing, orchestration
├── config.py         # YAML config loading, validation, profiles, credentials
├── browser.py        # Playwright browser automation (login + app launching)
├── logger.py         # Dual logging (file + stdout) with rotation
└── notifier.py       # macOS notification wrapper with input sanitization
```

---

## The Flow, Step by Step

```
You press Ctrl+Shift+C (or your chosen shortcut)
        │
        ▼
macOS triggers the Automator Quick Action
        │
        ▼
Automator runs: python3 -m citrix_autologin  (silently, no Terminal)
        │
        ▼
PID lock acquired (prevents double-invocation)
        │
        ▼
Config loaded from ~/.citrix-autologin.yaml
        │
        ▼
Credentials read from macOS Keychain
        │
        ▼
Playwright opens Chromium → navigates to Citrix URL
  (persistent context preserves cookies between runs)
        │
        ▼
IF a "New Login Instructions" splash page appears:
  → Script clicks "Continue" to dismiss it
        │
        ▼
Playwright fills in username (#login) + password (#passwd)
        │
        ▼
Playwright clicks "Log On" (#loginBtn)
  → Microsoft sends push notification to your phone
        │
        ▼
📱 macOS notification: "Check your phone — approve the push notification"
        │
        ▼
Script POLLS: checks browser URL every 2 seconds
  "Still on login page? → wait 2 more seconds"
  "Still on login page? → wait 2 more seconds"
        │
        ▼
YOU tap Approve + Face ID on your phone
        │
        ▼
Browser redirects to the Citrix portal
        │
        ▼
Script detects URL change → handles post-login splash screens
        │
        ▼
Script clicks "All Apps" tab → finds and clicks each app
  (3-second delay between launches)
        │
        ▼
📱 macOS notification: "All apps launched!"
        │
        ▼
Browser minimized, PID lock released. You're ready to work.
```

---

## Key Concepts Explained

### Polling (How We Detect Approval)
The script can't directly "know" when you've tapped Approve. It uses **polling** — checking the browser URL every 2 seconds. Before approval, the URL contains "login" or "auth". After approval, the browser redirects to the portal. The script detects this change instantly.

### Retry Wrapper
Every browser interaction (clicking, filling fields, finding elements) is wrapped in a retry mechanism — 3 attempts with a 3-second delay between each. This handles transient page load timing issues gracefully.

### PID Lock
A lock file at `~/CitrixAutoLogin/.lock` prevents running two instances simultaneously. If you accidentally press the shortcut twice, the second invocation exits immediately. Stale locks from crashed processes are automatically cleaned up.

### Multi-Profile Support
The config file supports named profiles for different app sets:
```yaml
profiles:
  clinic:
    apps: ["Epic Production", "Aria Home"]
  planning:
    apps: ["MIM", "RayStation 2024A SP3"]
```
Launch a specific profile: `python3 -m citrix_autologin --profile clinic`

### Log Rotation
Logs are written to `~/CitrixAutoLogin/logs/` with timestamps. Error screenshots are saved automatically. The 30 most recent log files are kept; older logs and their screenshots are cleaned up automatically.

### Notification Sanitization
All text sent to macOS notifications is sanitized — backslashes and quotes are escaped, control characters are stripped. This prevents AppleScript injection attacks from app names or error messages.

---

## Files In This Package

| File | Purpose |
|------|---------|
| `citrix_autologin/` | Python package — the automation engine |
| `setup.sh` | One-time setup — installs dependencies, stores credentials |
| `tests/` | Automated tests for config, notifications, and logging |
| `HOW_IT_WORKS.md` | This file — explains everything |
| `TODOS.md` | Future enhancement ideas |

---

## What Can and Can't Be Automated

| Step | Automated? | Why? |
|------|-----------|------|
| Open browser to login URL | Yes | Playwright controls Chromium |
| Dismiss splash pages | Yes | Data-driven splash screen handlers |
| Type username + password | Yes | Pulled from Keychain, filled by Playwright |
| Click Log On | Yes | Playwright clicks the button |
| Approve push notification | **No** | Requires your phone + Face ID (by design) |
| Detect approval happened | Yes | Script polls the browser URL for changes |
| Dismiss post-login screens | Yes | Handles up to 3 rounds of splash screens |
| Click "All Apps" tab | Yes | Playwright clicks the tab |
| Launch Citrix apps | Yes | Playwright finds and clicks each app icon |
| Minimize browser | Yes | AppleScript (best-effort) |

---

## Troubleshooting

### "Already running" message
Another instance is running. Wait for it to finish, or delete `~/CitrixAutoLogin/.lock` if it crashed.

### "No credentials found in Keychain"
Re-run `setup.sh` or manually add: `security add-generic-password -a "YOUR_USER" -s "citrix-autologin" -w "YOUR_PASS"`

### Script times out waiting for approval
Default timeout is 120 seconds. Increase `push_approval_timeout` in `~/.citrix-autologin.yaml`.

### Apps not found ("Could not find app: ...")
App names must match **exactly** what's on the portal (case-sensitive). Log in manually and copy the names precisely. Edit `~/.citrix-autologin.yaml` to fix them.

### Only some apps launch
Increase `app_launch_delay` in the config — your Citrix server may need more time between launches.

### No notifications appearing
Check System Settings → Notifications → Script Editor. macOS may be blocking notifications from scripts.

---

## Security Notes

- **Passwords are never stored in plain text** — they live in macOS Keychain (encrypted)
- **The script never sends your credentials anywhere** except to your Citrix login page
- **2FA still requires your physical phone + Face ID** — the script can't bypass this
- **Notification input is sanitized** — prevents injection attacks via osascript
- **PID lock prevents double-invocation** — no accidental parallel logins
