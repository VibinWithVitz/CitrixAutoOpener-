# Citrix Auto-Login

One keyboard shortcut to log into Citrix and launch all your radiation oncology apps (Epic Production, Aria Home, MIM, RayStation). You still approve the 2FA push on your phone — everything else is automated.

## What It Does

1. Opens a browser to your Citrix portal
2. Fills in your username and password (from macOS Keychain)
3. Clicks "Log On" and sends you a notification: "Check your phone"
4. Waits for you to approve the push notification
5. Launches all your apps automatically
6. Sends a notification: "All apps launched!"

No Terminal window. No babysitting. Just press the shortcut and approve on your phone.

## Requirements

- macOS
- Python 3 (pre-installed on most Macs — check with `python3 --version`)

## Installation

### 1. Download the project

Download or clone this repo to your Mac:

```bash
git clone https://github.com/VibinWithVitz/CitrixAutoOpener-.git
cd CitrixAutoOpener-
```

Or download the ZIP from GitHub and unzip it.

### 2. Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

The setup script will walk you through everything:

1. **Checks for Python 3** — tells you where to get it if missing
2. **Installs Python packages** — Playwright (browser automation) and PyYAML (config)
3. **Downloads Chromium** — the browser Playwright uses (separate from your Chrome)
4. **Stores your credentials** — username and password go into macOS Keychain (encrypted, not plain text)
5. **Generates your config file** — asks for your Citrix URL and which apps to launch
6. **Creates a keyboard shortcut** — Automator Quick Action you can assign a hotkey to

### 3. Assign a keyboard shortcut

This is the one manual step:

1. Open **System Settings → Keyboard → Keyboard Shortcuts → Services**
2. Find **"Citrix Auto-Login"** in the General section
3. Click **"Add Shortcut"** and press your desired key combo (recommended: **Ctrl+Shift+C**)

## Usage

Press your keyboard shortcut. That's it.

You'll get a notification to check your phone. Approve the push, and your apps launch automatically.

### Command line

You can also run it directly:

```bash
# Default apps
python3 -m citrix_autologin

# Specific profile
python3 -m citrix_autologin --profile clinic
```

### Profiles

If you have different app sets for different workflows, add profiles to `~/.citrix-autologin.yaml`:

```yaml
profiles:
  clinic:
    apps: ["Epic Production", "Aria Home"]
  planning:
    apps: ["MIM", "RayStation 2024A SP3"]
```

Then run with `--profile clinic` or `--profile planning`.

## Configuration

Your config lives at `~/.citrix-autologin.yaml`. The setup script creates it for you, but you can edit it anytime:

```yaml
citrix_url: "https://gateway.scmc.org/"
push_approval_timeout: 120    # seconds to wait for 2FA approval
app_launch_delay: 3           # seconds between launching each app
portal_load_wait: 3           # seconds to wait for portal to load
headless: false               # true = no visible browser window

apps:
  - "Epic Production"
  - "Aria Home"
  - "MIM"
  - "RayStation 2024A SP3"
```

## Updating Your Password

If your password changes, update it in Keychain:

```bash
security delete-generic-password -s "citrix-autologin"
security add-generic-password -a "YOUR_USERNAME" -s "citrix-autologin" -w "YOUR_NEW_PASSWORD"
```

Or just re-run `./setup.sh`.

## Security

- Passwords are stored in **macOS Keychain** (encrypted) — never in plain text
- Credentials are only sent to your Citrix login page — nowhere else
- 2FA still requires your **physical phone + Face ID** — the script can't bypass this
- All notification text is sanitized to prevent injection attacks

## Troubleshooting

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for detailed troubleshooting and a technical explanation of how everything works.
