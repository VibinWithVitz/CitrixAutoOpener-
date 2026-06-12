#!/usr/bin/env python3
"""
Citrix Auto-Login Script
=========================
This script automates logging into a Citrix web portal, including handling
two-factor authentication (2FA) via Microsoft Authenticator push notifications.

HOW IT WORKS (high-level):
1. Opens Chrome to your Citrix login page using Selenium
2. Fills in your username and password (pulled from macOS Keychain)
3. Submits the form, which triggers a push notification to your phone
4. Waits for you to tap "Approve" + Face ID on your phone
5. Detects that the login succeeded
6. Automatically launches your chosen Citrix applications from the portal

WHAT YOU STILL DO MANUALLY:
- Tap "Approve" on the Microsoft Authenticator push notification
- Confirm with Face ID
That's it — everything else is automated, including launching your apps.

PREREQUISITES (see setup.sh to install these):
- Python 3.9+
- selenium (pip package) — controls Chrome programmatically
- chromedriver — the bridge between Selenium and Chrome
- macOS Keychain entry with your credentials (we'll set this up)
"""

import subprocess
import re
import time
import os
import sys
import signal

# ---------------------------------------------------------------------------
# STEP 1: CONFIGURATION
# ---------------------------------------------------------------------------
# These are the only things you need to change:

CITRIX_URL = "https://gateway.scmc.org/"

# CSS selectors for the login page fields.
# You'll need to inspect your Citrix login page to find these.
# Right-click on each field in Chrome → "Inspect" to see the HTML.
USERNAME_SELECTOR = "#login"                        # The username field (id="login")
PASSWORD_SELECTOR = "#passwd"                       # The password field (id="passwd")
SUBMIT_SELECTOR   = "#loginBtn"                     # The "Log On" button (id="loginBtn")

# How long (in seconds) to wait for you to approve the push notification.
# 120 seconds = 2 minutes. Increase if you need more time.
PUSH_APPROVAL_TIMEOUT = 120

# ---------------------------------------------------------------------------
# CITRIX APPS TO LAUNCH AFTER LOGIN
# ---------------------------------------------------------------------------
# After logging in, the script will click on these apps in the Citrix portal
# to launch them automatically.
#
# HOW TO FIND THE RIGHT APP NAMES:
# 1. Log into your Citrix portal manually
# 2. Look at the names displayed under each app icon
# 3. Type those names EXACTLY as they appear (case-sensitive)
#
# The script finds apps by matching their visible text on the portal page.
# For example, if you see icons labeled "Epic", "Outlook", "Desktop":
#
CITRIX_APPS_TO_LAUNCH = [
    "Epic Production",
    "Aria Home",
    "MIM",
    "RayStation 2024A SP3",
]

# Seconds to wait between launching each app.
# Citrix can be slow — give it time to process each launch before the next.
APP_LAUNCH_DELAY = 2

# ---------------------------------------------------------------------------
# AUTO-SHUTDOWN WHEN IDLE
# ---------------------------------------------------------------------------
# If you stop using your Citrix apps for this long, the script automatically
# closes the Citrix apps, Chrome, AND its own Terminal window — so nothing
# is left running when you walk away.
#
# "Using" means a Citrix window is focused and you've touched the keyboard
# or mouse recently. Working in other apps (email, browser, etc.) counts as
# NOT using Citrix.
#
# Set AUTO_SHUTDOWN_AFTER = 0 to disable this feature entirely.
AUTO_SHUTDOWN_AFTER = 30 * 60   # 30 minutes, in seconds
IDLE_CHECK_INTERVAL = 60        # How often (seconds) to check for activity

# How we detect that login succeeded after you approve the push.
# The script watches the URL — when it changes away from the login page,
# that means you're in. Update this if your Citrix portal has a different
# post-login URL pattern.
#
# OPTION A: Detect by URL change (default)
#   The script waits for the URL to stop containing "login" or "auth".
#   This works for most setups.
#
# OPTION B: Detect by element on the portal page
#   If your portal has a specific element (like a "Launch" button or
#   a welcome message), you can wait for that instead. Uncomment
#   POST_LOGIN_SELECTOR below and set it.
#
# POST_LOGIN_SELECTOR = "#some-element-on-portal"  # Uncomment to use Option B


# ---------------------------------------------------------------------------
# STEP 2: READING CREDENTIALS FROM macOS KEYCHAIN
# ---------------------------------------------------------------------------
"""
WHY KEYCHAIN?
We never want to store passwords in plain text in a script. macOS Keychain
is an encrypted credential store built into your Mac. We store the password
there once, and the script reads it securely each time.

HOW TO STORE YOUR PASSWORD:
Run this command in Terminal (once):
    security add-generic-password -a "YOUR_USERNAME" -s "citrix-autologin" -w "YOUR_PASSWORD"

The script below reads it back with:
    security find-generic-password -s "citrix-autologin" -w
"""

KEYCHAIN_SERVICE = "citrix-autologin"


def get_credentials_from_keychain():
    """
    Reads your Citrix username and password from macOS Keychain.

    The `security` command is a built-in macOS CLI tool for interacting
    with Keychain. The `-s` flag specifies the "service" name (our label),
    and `-w` tells it to return just the password.
    """
    try:
        # Get the password
        password = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            stderr=subprocess.DEVNULL
        ).decode().strip()

        # Get the username (stored as the "account" field)
        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            stderr=subprocess.DEVNULL
        ).decode()

        # Parse the account name from the output
        # The `security` command outputs key-value pairs. We look for "acct"
        # which is where it stores the account/username.
        match = re.search(r'"acct"<blob>="(.+?)"', raw)
        if match:
            username = match.group(1)
        else:
            username = input("Could not read username from Keychain. Enter it: ")

        return username, password

    except subprocess.CalledProcessError:
        print("ERROR: No credentials found in Keychain.")
        print(f'Run: security add-generic-password -a "YOUR_USERNAME" -s "{KEYCHAIN_SERVICE}" -w "YOUR_PASSWORD"')
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# STEP 3: WAITING FOR PUSH NOTIFICATION APPROVAL
# ---------------------------------------------------------------------------
"""
HOW THIS WORKS:
After submitting your username + password, the Citrix/Microsoft login page
triggers a push notification to your Microsoft Authenticator app. You tap
"Approve" and confirm with Face ID on your phone.

THE SCRIPT CAN'T TAP YOUR PHONE FOR YOU — that's the whole point of 2FA.
But it CAN detect when you've approved by watching the browser:

  - Before approval: the browser is stuck on the login/auth page
  - After approval: the browser redirects to the Citrix portal

We "poll" the browser URL every 2 seconds. When the URL changes to
something that doesn't look like a login page, we know you're in.

POLLING vs. WAITING:
Rather than sleeping for a fixed time (which might be too long or too short),
polling checks repeatedly: "Has the page changed yet? No? Check again in
2 seconds." This means the script proceeds the instant you approve.
"""


def is_on_portal(driver):
    """
    Checks if the browser has reached the Citrix app portal (post-login).

    Returns True if the current page looks like the portal rather than
    a login/auth page. We check both the URL and page content.
    """
    current_url = driver.current_url.lower()
    login_indicators = ["login", "logon", "auth", "oauth", "signin", "mfa", "verify"]
    still_on_login = any(indicator in current_url for indicator in login_indicators)

    if still_on_login:
        # Even if URL looks like login, check if portal elements are present.
        # Some Citrix deployments keep a similar URL but change the page content.
        try:
            driver.find_element(By.CSS_SELECTOR, "#allAppsFilterBtn")
            return True
        except Exception:
            pass
        try:
            driver.find_element(By.XPATH, "//img[contains(@class,'storeapp-icon')]")
            return True
        except Exception:
            pass
        return False

    return True  # URL doesn't look like login page — we're through


def wait_for_push_approval(driver, timeout=PUSH_APPROVAL_TIMEOUT):
    """
    Waits for the user to approve the Microsoft Authenticator push notification.

    Monitors the browser to detect when authentication succeeds, either by:
    - URL change: the page redirects away from the login/auth URL
    - Element detection: a known post-login element appears on the page

    Returns True if login succeeded, False if it timed out.
    """
    print("")
    print("=" * 50)
    print("  CHECK YOUR PHONE!")
    print("  Approve the Microsoft Authenticator notification")
    print("  (Face ID will be required)")
    print("=" * 50)
    print("")

    # Remember what URL we're on right now (the login/auth page)
    login_url = driver.current_url
    print(f"Current page: {login_url}")
    print(f"Waiting up to {timeout} seconds for approval...")

    start_time = time.time()
    poll_interval = 2  # Check every 2 seconds
    mfa_in_progress = False

    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)

        # Check if MFA/processing is actively in progress.
        # The Citrix page shows "Your request is being processed" or
        # "Firstfactor" while waiting for MFA approval. If we see these,
        # we know auth is progressing (not stuck), so we stay patient.
        if not mfa_in_progress:
            try:
                page_text = driver.find_element(By.TAG_NAME, "body").text
                if any(phrase in page_text for phrase in [
                    "request is being processed",
                    "Firstfactor",
                    "Approve sign-in request",
                    "approve the notification",
                ]):
                    mfa_in_progress = True
                    print("  MFA in progress — waiting for your approval...")
            except Exception:
                pass

        # Check if we've reached the portal. is_on_portal() inspects both the
        # URL and the page DOM, so we call it once per poll and branch the
        # message on whether the URL also changed.
        current_url = driver.current_url
        if is_on_portal(driver):
            if current_url != login_url:
                print(f"\nLogin detected! Redirected to: {current_url}")
            else:
                print(f"\nLogin detected! Portal elements found on: {current_url}")
            return True

        # Print a status dot every 10 seconds so you know it's still running
        if elapsed % 10 == 0 and elapsed > 0:
            status = " (MFA in progress)" if mfa_in_progress else ""
            print(f"  Still waiting... ({elapsed}s elapsed){status}")

        time.sleep(poll_interval)

    # If we get here, we timed out — but do a final check.
    # The page may have loaded right at the timeout boundary.
    if is_on_portal(driver):
        print(f"\nLogin detected at timeout! Portal loaded on: {driver.current_url}")
        return True

    print(f"\nTimed out after {timeout} seconds waiting for push approval.")
    return False


# ---------------------------------------------------------------------------
# STEP 4: BROWSER AUTOMATION WITH SELENIUM
# ---------------------------------------------------------------------------
"""
WHAT IS SELENIUM?
Selenium is a tool that controls a web browser programmatically. It can:
- Open URLs
- Find elements on a page (buttons, text fields, etc.)
- Type text, click buttons, wait for pages to load

It works by communicating with a "driver" program (chromedriver for Chrome)
that translates Python commands into browser actions.

CSS SELECTORS:
We use CSS selectors to identify page elements. These are the same selectors
used in web design. For example:
  - "input[name='username']" finds an <input> tag with name="username"
  - "#loginBtn" finds an element with id="loginBtn"
  - ".submit-button" finds elements with class="submit-button"

To find the right selectors for YOUR Citrix page:
1. Open the login page in Chrome
2. Right-click on the username field → "Inspect"
3. Look at the HTML. If you see <input name="login" id="user"...>
   you could use "input[name='login']" or "#user"
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager


# ---------------------------------------------------------------------------
# PID FILE MANAGEMENT
# ---------------------------------------------------------------------------
# Instead of trying to hunt down and kill orphan Chrome processes by name,
# we take a simpler approach: the script manages its OWN lifecycle.
#
# - On startup, check if a previous instance is still running (via PID file)
# - If so, send it SIGTERM → its signal handler calls driver.quit() → Chrome
#   shuts down cleanly → no orphan processes, no stale lock files
# - The new instance then starts fresh with a clean profile
#
# This means pressing the hotkey (Ctrl+Shift+C) again will:
#   1. Kill the previous script + its Chrome cleanly
#   2. Start a brand new login session

PID_FILE = os.path.expanduser("~/CitrixAutoLogin/.pid")


def terminate_processes(pattern):
    """
    Gracefully terminate every process whose command line matches `pattern`
    (the same matching `pgrep -f` / `pkill -f` use), escalating to SIGKILL
    for any that survive ~5 seconds.

    Returns True if at least one matching process was found, False otherwise.
    """
    if not subprocess.run(
        ["pgrep", "-f", pattern], capture_output=True, text=True
    ).stdout.strip():
        return False

    # SIGTERM first (graceful)
    subprocess.run(["pkill", "-f", pattern], capture_output=True)

    # Wait up to 5 seconds for them to exit, then force-kill stragglers
    for _ in range(10):
        if not subprocess.run(
            ["pgrep", "-f", pattern], capture_output=True, text=True
        ).stdout.strip():
            break
        time.sleep(0.5)
    else:
        subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
        time.sleep(1)

    return True


def close_citrix_apps():
    """
    Close any running Citrix virtual app sessions.

    Citrix apps launched from the portal run inside "Citrix Viewer" processes
    on macOS. Killing these before a fresh login prevents stale sessions from
    lingering and ensures a clean start.
    """
    if terminate_processes("Citrix Viewer"):
        print("Closed existing Citrix app sessions.")
    else:
        print("No existing Citrix app sessions found.")


def kill_previous_instance():
    """
    If a previous instance of this script is still running, send it SIGTERM
    so it can shut down Chrome cleanly via its signal handler.

    Returns True if a previous instance was found and killed.
    """
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, "r") as f:
            old_pid = int(f.read().strip())
    except (ValueError, OSError):
        # Corrupt or unreadable PID file — remove it and move on
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        return False

    # Check if the process is actually still running
    try:
        os.kill(old_pid, 0)  # Signal 0 = just check if process exists
    except ProcessLookupError:
        # Process is already gone — clean up stale PID file
        try:
            os.unlink(PID_FILE)
        except OSError:
            pass
        return False
    except PermissionError:
        # Process exists but we can't signal it — shouldn't happen for our own process
        return False

    # Process is alive — send SIGTERM so it shuts down Chrome cleanly
    print(f"Found previous instance (PID {old_pid}) — sending shutdown signal...")
    try:
        os.kill(old_pid, signal.SIGTERM)
    except OSError:
        pass

    # Wait for it to exit (up to 10 seconds)
    for _ in range(20):
        try:
            os.kill(old_pid, 0)
            time.sleep(0.5)
        except ProcessLookupError:
            print("  Previous instance shut down cleanly.")
            break
    else:
        # Still alive after 10 seconds — force kill
        print("  Previous instance didn't exit — force killing...")
        try:
            os.kill(old_pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(1)

    # Clean up the old PID file
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass

    return True


def write_pid_file():
    """Write our PID to the PID file so future runs can find and stop us."""
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_pid_file():
    """Remove the PID file on exit."""
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# IDLE DETECTION (for auto-shutdown)
# ---------------------------------------------------------------------------
# To know whether you're "using" Citrix, we combine two macOS signals:
#
# 1. SYSTEM IDLE TIME — how long since the keyboard or mouse was touched,
#    anywhere on the Mac. We read this from `ioreg`, which exposes the
#    HIDIdleTime counter (in nanoseconds) from the input-device driver.
#
# 2. FRONTMOST APP — which application currently has focus. We ask
#    System Events via AppleScript. If a Citrix window is focused AND
#    you've been active recently, you're using Citrix.
#
# NOTE: The first time the frontmost-app check runs, macOS will show a
# one-time permission prompt ("Terminal wants to control System Events").
# Click OK. If the check is denied or fails, we fall back to system idle
# time alone — so the feature degrades safely instead of closing your
# apps while you're still working.


def get_system_idle_seconds():
    """
    Returns seconds since the last keyboard/mouse input, system-wide.
    Returns 0.0 if the value can't be read (treated as "active" — safe).
    """
    try:
        out = subprocess.check_output(["ioreg", "-c", "IOHIDSystem"], text=True)
        match = re.search(r'"HIDIdleTime" = (\d+)', out)
        if match:
            return int(match.group(1)) / 1_000_000_000  # nanoseconds → seconds
    except Exception:
        pass
    return 0.0


def get_frontmost_app():
    """
    Returns the name of the currently focused application (e.g. "Citrix
    Viewer", "Safari"), or None if it can't be determined (e.g. the
    Automation permission was denied).
    """
    try:
        return subprocess.check_output(
            ["osascript", "-e",
             'tell application "System Events" to get name of first '
             'application process whose frontmost is true'],
            stderr=subprocess.DEVNULL, text=True, timeout=10,
        ).strip() or None
    except Exception:
        return None


def is_citrix_in_use():
    """
    Returns True if the user appears to be actively using Citrix right now:
    recent keyboard/mouse input AND a Citrix window in focus.

    If we can't tell which app is focused (permission denied), we fall back
    to counting ANY recent input as activity — conservative, so we never
    close apps out from under someone who's at their desk.
    """
    # No recent input anywhere on the Mac → definitely not in use.
    if get_system_idle_seconds() > IDLE_CHECK_INTERVAL * 2:
        return False

    front = get_frontmost_app()
    if front is None:
        return True  # Can't tell what's focused — assume in use (safe)

    return front in ("Citrix Viewer", "Citrix Workspace")


def close_terminal_window():
    """
    Closes the Terminal window this script is running in.

    We find our window by its tty (the terminal device this process is
    attached to), then close it via AppleScript. The osascript runs as a
    DETACHED process with a 2-second delay: by the time it fires, this
    script has already exited, so Terminal shows "[Process completed]"
    and closes the window without a "process still running" warning.
    """
    try:
        tty = os.ttyname(sys.stdin.fileno())
    except (OSError, ValueError):
        return  # Not attached to a terminal (e.g. launched by a daemon)

    applescript = f'''
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is "{tty}" then
                    close w saving no
                    return
                end if
            end repeat
        end repeat
    end tell
    '''
    subprocess.Popen(
        ["/bin/bash", "-c", f"sleep 2; osascript -e '{applescript}'"],
        start_new_session=True,  # Survives this script's exit
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def cleanup_orphan_chrome():
    """
    Safety net: kill any Chrome processes using our profile that outlived
    the previous script.

    This handles the case where the script crashed, was force-killed, or
    was running the old version with detach=True — leaving Chrome alive
    with no script to manage it. Without this, the profile stays locked
    and the new Chrome can't start.

    This only targets Chrome instances using OUR dedicated profile folder,
    never the user's normal Chrome windows.
    """
    script_profile = os.path.expanduser("~/CitrixAutoLogin/chrome-profile")

    if not terminate_processes(f"--user-data-dir={script_profile}"):
        return  # No orphan Chrome processes — nothing to do

    print("Found orphan Chrome processes from a previous run — cleaning up...")

    # Clean up lock files so the profile can be reused
    for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_path = os.path.join(script_profile, lock_name)
        try:
            if os.path.islink(lock_path) or os.path.exists(lock_path):
                os.unlink(lock_path)
        except OSError:
            pass

    print("  Orphan processes cleaned up.")


def create_browser():
    """
    Creates a Chrome browser instance controlled by Selenium.

    IMPORTANT: We use a SEPARATE Chrome profile (stored in ~/CitrixAutoLogin)
    instead of your normal Chrome profile. This solves a common problem:
    if Chrome is already open, Selenium can't share the same profile and
    you'd get a "DevToolsActivePort file doesn't exist" error.

    With a dedicated profile, the script works whether Chrome is open or not.
    The trade-off is that this Chrome window won't have your bookmarks or
    extensions — but since it's only used for Citrix login, that's fine.
    """
    chrome_options = Options()

    # Use a dedicated profile folder so the script never conflicts with
    # your normal Chrome window. This folder is created automatically
    # the first time the script runs.
    script_profile = os.path.expanduser("~/CitrixAutoLogin/chrome-profile")
    os.makedirs(script_profile, exist_ok=True)
    chrome_options.add_argument(f"--user-data-dir={script_profile}")

    # Quality-of-life options
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])

    # NOTE: We intentionally do NOT use detach=True here. The script keeps
    # running and owns Chrome's lifecycle. When the script exits (via hotkey,
    # Ctrl+C, or closing Terminal), it calls driver.quit() for a clean shutdown.
    # This eliminates orphan Chrome processes and stale profile lock files.

    # Prevent the "Chrome didn't shut down correctly — Restore pages?" bubble.
    chrome_options.add_argument("--hide-crash-restore-bubble")

    # Disable Chrome's "Save password?" popup.
    # This covers the prompt that appears after login asking to save credentials.
    chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
        # Allow the Citrix portal to download multiple .ica files without
        # Chrome showing "This site wants to download multiple files. Allow?"
        # Each app launch triggers an .ica file download. Without this,
        # Chrome blocks every download after the first one — which is why
        # only Epic was opening. Value 1 = allow automatic downloads.
        "profile.default_content_setting_values.automatic_downloads": 1,
    })

    # Block the "Open Citrix Workspace Launcher?" dialog.
    # After login, the Citrix portal tries to launch a custom URL scheme
    # (receiver://) which triggers a Chrome dialog asking "Open external app?"
    # Selenium CANNOT click browser-level dialogs — they block everything.
    # This flag tells Chrome to silently deny all external protocol requests,
    # preventing the dialog from appearing in the first place.
    # This is fine because we don't need the native launcher — the script
    # clicks the app icons directly on the web portal page instead.
    chrome_options.add_argument("--disable-external-intent-requests")

    # Use webdriver-manager to automatically download the correct ChromeDriver
    # version that matches the installed Chrome browser. This avoids the
    # "This version of ChromeDriver only supports Chrome version X" error
    # that happens when Chrome auto-updates but chromedriver doesn't.
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def dismiss_post_login_screens(driver):
    """
    Handles the various splash screens and prompts Citrix shows after login.

    Citrix StoreFront / Workspace has several screens that can appear between
    logging in and actually seeing your apps. These vary by deployment, but
    the common ones are:

    1. "Welcome to Citrix Workspace app" — an intro splash screen
    2. "Detect Citrix Workspace" — asks if you have the Citrix client installed
    3. "Citrix Workspace app is not detected" — offers to download or use browser
    4. Cookie consent or privacy banners

    The script checks for each one and clicks the appropriate dismiss button.
    We loop through multiple times because dismissing one screen sometimes
    reveals another one behind it.
    """
    # Each entry is: (description, how to detect it, how to dismiss it)
    # We check by looking for a visible element, then clicking the dismiss button.
    # Instead of trying to detect and click through each individual splash
    # screen (Welcome → Detect → Not Detected), we take a simpler approach:
    #
    # Look for "Already installed" — this link appears on every version of
    # the Citrix detection/welcome flow and skips straight to the app portal.
    # We also look for "Detect again" since that appears alongside it.
    #
    # We loop because:
    #   - The first screen (Welcome) may not have "Already installed" yet —
    #     we click "Detect Citrix Workspace app" to advance to the next screen
    #   - The second screen (Detecting...) shows "Already installed" after
    #     a brief detection attempt
    #   - There may be additional screens after that

    def any_visible(by, selector):
        """True if at least one element matching the selector is VISIBLE.
        Citrix renders the app list in the DOM behind the splash overlay,
        so merely existing in the DOM is not enough — we must check
        is_displayed() or we'd skip dismissing a splash that's on screen."""
        try:
            return any(el.is_displayed() for el in driver.find_elements(by, selector))
        except Exception:
            return False

    for attempt in range(5):
        # If the app portal is actually visible on screen AND no detection
        # splash is covering it, there's nothing to dismiss — skip the
        # settle delay entirely. This saves up to 15 seconds on deployments
        # that go straight to the app list after login.
        splash_showing = any_visible(
            By.XPATH,
            "//*[contains(text(), 'Detect Citrix Workspace')"
            " or contains(text(), 'Already installed')"
            " or contains(text(), 'Welcome to Citrix Workspace')]",
        )
        portal_showing = (
            any_visible(By.CSS_SELECTOR, "#allAppsFilterBtn")
            or any_visible(By.XPATH, "//img[contains(@class,'storeapp-icon')]")
        )
        if portal_showing and not splash_showing:
            break

        time.sleep(3)  # Let the page settle between attempts

        # Priority 1: Click "Already installed" if it's visible.
        # This is the fastest way past ALL detection screens.
        try:
            already_installed = driver.find_element(
                By.XPATH, "//*[contains(text(), 'Already installed')]"
            )
            if already_installed.is_displayed():
                print("  Found 'Already installed' — clicking to skip detection...")
                driver.execute_script("arguments[0].click();", already_installed)
                time.sleep(3)
                continue  # Check if there's another screen after this
        except Exception:
            pass

        # Priority 2: Click "Detect Citrix Workspace app" button.
        # This is the big teal button on the Welcome screen. Clicking it
        # advances to the detection screen, which then shows "Already installed".
        #
        # We use //* instead of //button because Citrix renders this as
        # different element types depending on the version (<span>, <div>,
        # <a>, or <button>). We also use JavaScript click because Selenium's
        # normal .click() can fail if another element is overlapping it.
        try:
            detect_btn = driver.find_element(
                By.XPATH, "//*[contains(text(), 'Detect Citrix Workspace')]"
            )
            if detect_btn.is_displayed():
                print("  Found 'Detect Citrix Workspace app' — clicking to advance...")
                driver.execute_script("arguments[0].click();", detect_btn)
                time.sleep(5)
                continue
        except Exception:
            pass

        # Priority 3: Click "Use light version" or "Use web browser" links.
        # Some Citrix deployments offer these as alternatives.
        for link_text in ["Use light version", "Use web browser"]:
            try:
                link = driver.find_element(
                    By.XPATH, f"//*[contains(text(), '{link_text}')]"
                )
                if link.is_displayed():
                    print(f"  Found '{link_text}' — clicking...")
                    driver.execute_script("arguments[0].click();", link)
                    time.sleep(3)
                    break
            except Exception:
                continue
        else:
            # No splash screen elements found — we're through!
            break

    print("  Post-login screens handled.")


def launch_citrix_apps(driver, app_names, delay=APP_LAUNCH_DELAY):
    """
    Launches specific applications from the Citrix portal after login.

    HOW THIS WORKS:
    Citrix portals (both Citrix Workspace and StoreFront) display applications
    as clickable cards/icons on a web page. Each app has its name displayed
    as visible text. We use Selenium to find elements containing that text
    and click them, just as you would manually.

    WHY MULTIPLE STRATEGIES:
    Different Citrix deployments render their app lists differently:
    - Some use <span> tags with the app name
    - Some use data attributes like data-name="AppName"
    - Some use image alt text
    - Some use buttons or links with the app name as text

    We try several approaches to maximize compatibility. The script tries
    the most common patterns first and falls back to broader searches.

    DELAY BETWEEN LAUNCHES:
    Citrix needs time to process each app launch (it downloads and starts
    a virtual application). Clicking too fast can cause launches to fail.
    We wait a few seconds between each click.
    """
    if not app_names:
        print("No apps configured to launch. Edit CITRIX_APPS_TO_LAUNCH in the script.")
        return

    # Poll for the app list instead of sleeping a fixed amount — we proceed
    # the moment the portal renders, and wait up to 15 seconds if it's slow.
    print("\nWaiting for the portal app list to load...")
    try:
        WebDriverWait(driver, 15).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#allAppsFilterBtn")
            or d.find_elements(By.XPATH, "//img[contains(@class,'storeapp-icon')]")
        )
    except Exception:
        print("  (App list didn't appear within 15 seconds — trying anyway)")

    # Click the "All Apps" tab to make sure every app is visible.
    # By default, the portal may only show a subset of apps (e.g., favorites).
    # The "All Apps" tab has a known id="allAppsFilterBtn", so we click it first.
    try:
        all_apps_btn = driver.find_element(By.CSS_SELECTOR, "#allAppsFilterBtn")
        if all_apps_btn.is_displayed():
            print("Clicking 'All Apps' to show the full app list...")
            all_apps_btn.click()
            time.sleep(2)  # Give the app list a moment to refresh
    except Exception:
        print("  (No 'All Apps' filter found — portal may already show all apps)")

    # Dump all visible app names so we can diagnose name mismatches
    print("\n--- Apps visible on portal ---")
    for source, method, selector in [
        ("img alt",   By.XPATH,        "//img[contains(@class,'storeapp-icon')]"),
        ("storeapp-name", By.XPATH,    "//p[contains(@class,'storeapp-name')]"),
        ("a[title]",  By.CSS_SELECTOR, "a[title]"),
    ]:
        try:
            els = driver.find_elements(method, selector)
            visible = [el for el in els if el.is_displayed()]
            if visible:
                for el in visible:
                    name = el.get_attribute("alt") or el.get_attribute("title") or el.text
                    if name and name.strip():
                        print(f"  [{source}] {name.strip()!r}")
        except Exception:
            pass
    print("--- End of app list ---\n")

    for i, app_name in enumerate(app_names):
        print(f"\nLooking for app: '{app_name}'...")
        launched = False

        # Strategy 1: Find by visible text using XPath
        # XPath is another way to locate elements on a page (like CSS selectors,
        # but more powerful for text matching). This searches the ENTIRE page
        # for any element whose text content contains the app name.
        #
        # The expression: //*[contains(text(), 'AppName')]
        #   //*           = any element anywhere in the page
        #   contains()    = partial text match (in case the name has extra spaces)
        #   text()        = the visible text content of the element
        # We know from inspecting the portal that apps are structured like:
        #   <a href="#">                   ← this is the clickable element
        #     <img class="storeapp-icon" alt="Epic Production">
        #     <div class="storeapp-action-link-sprite"></div>  ← NOT this
        #   </a>
        #
        # The correct approach: find the <img> by its alt text, then
        # navigate UP to the parent <a> link and click that instead.
        # In XPath, "ancestor::a[1]" means "walk up the tree and find
        # the nearest <a> element above this one."

        strategies = [
            # Strategy 1 (BEST): Find img by alt text → click parent <a>
            # This is the most precise approach given the known HTML structure.
            (By.XPATH, f"//img[@alt='{app_name}']/ancestor::a[1]"),

            # Strategy 2: Find img by alt text → click immediate parent
            # Fallback if the parent isn't an <a> but some other element.
            (By.XPATH, f"//img[@alt='{app_name}']/parent::*"),

            # Strategy 3: Find img by alt text on storeapp-icon class specifically
            # Narrows to Citrix's specific icon class to avoid false matches.
            (By.XPATH, f"//img[contains(@class,'storeapp-icon') and @alt='{app_name}']/ancestor::a[1]"),

            # Strategy 4: Any link whose title matches the app name
            (By.CSS_SELECTOR, f"a[title='{app_name}']"),

            # Strategy 5: Data attribute match
            (By.CSS_SELECTOR, f"[data-name='{app_name}']"),

            # Strategy 6: Find by storeapp-name paragraph text → click ancestor <a>
            # Matches portal structure: <p class="storeapp-name">App Name</p>
            # Used as last resort since the <a> ancestor may not be the launch trigger.
            (By.XPATH, f"//p[contains(@class,'storeapp-name') and contains(text(),'{app_name}')]/ancestor::a[1]"),
        ]

        for method, selector in strategies:
            try:
                elements = driver.find_elements(method, selector)
                # Filter to only visible elements
                clickable = [el for el in elements if el.is_displayed()]

                if clickable:
                    el = clickable[0]
                    print(f"  Found '{app_name}' — clicking to launch...")
                    # Use ActionChains for a realistic mouse interaction.
                    # Citrix's JS listens for the full mousedown → mouseup →
                    # click event sequence. A synthetic JS click() only fires
                    # the click event, which is why only the first app was
                    # launching — subsequent clicks were "heard" by the DOM
                    # but ignored by Citrix's event handlers.
                    #
                    # ActionChains moves the mouse to the element center and
                    # performs a real click, producing the full event chain.
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", el)
                    time.sleep(0.5)
                    ActionChains(driver).move_to_element(el).pause(0.3).click().perform()
                    launched = True
                    break
            except Exception:
                continue

        if launched:
            print(f"  '{app_name}' launch initiated!")

            # Clicking an app can open a new browser tab. Switch back to the
            # portal tab so the next app lookup searches the right page.
            if len(driver.window_handles) > 1:
                driver.switch_to.window(driver.window_handles[0])

            if delay > 0 and i < len(app_names) - 1:
                print(f"  Waiting {delay} seconds before next app...")
                time.sleep(delay)
        else:
            print(f"  WARNING: Could not find '{app_name}' on the portal page.")
            print(f"  Make sure the name matches exactly what you see on screen.")
            print(f"  Tip: Right-click the app icon → Inspect to see its text.")

    print("\nAll app launches complete!")


def login_to_citrix():
    """
    Main function that orchestrates the entire login flow.

    The flow is:
    1. Kill any previous instance of this script (and its Chrome) cleanly
    2. Read credentials from Keychain
    3. Open Chrome and navigate to the login page
    4. Fill in username and password
    5. Submit the form (triggers Authenticator push)
    6. Wait for you to approve on your phone
    7. Launch your configured Citrix apps from the portal
    8. Stay alive until the user presses the hotkey again (or Ctrl+C)
    """
    # --- Close any existing Citrix app sessions ---
    close_citrix_apps()

    # --- Kill any previous instance ---
    # If the user pressed the hotkey while a previous run is still going,
    # send it SIGTERM so it shuts down Chrome cleanly, then proceed.
    kill_previous_instance()

    # --- Safety net: clean up orphan Chrome processes ---
    # If the previous script crashed or was the old version with detach=True,
    # Chrome may still be alive with no script managing it. Kill those too.
    cleanup_orphan_chrome()

    # --- Write our PID so future runs can find and stop us ---
    write_pid_file()

    # --- Get credentials ---
    print("Reading credentials from Keychain...")
    username, password = get_credentials_from_keychain()
    print(f"Got credentials for: {username}")

    # --- Launch browser ---
    print(f"Opening Chrome to {CITRIX_URL}...")
    driver = create_browser()

    # --- Register signal handlers for clean shutdown ---
    # When the user presses the hotkey again (or Ctrl+C, or closes Terminal),
    # these handlers ensure driver.quit() is called so Chrome shuts down
    # properly — no orphan processes, no stale lock files.
    def handle_shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        print(f"\n{sig_name} received — shutting down Chrome cleanly...")
        try:
            driver.quit()
        except Exception:
            pass
        remove_pid_file()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGHUP, handle_shutdown)  # Terminal window closed

    # Clear ALL browser data so the login flow starts completely fresh.
    #
    # Cookies alone aren't enough — Microsoft's auth also stores session
    # state in localStorage, sessionStorage, IndexedDB, and cache. If any
    # of that survives, the auth flow detects a "remembered" session and
    # sends an automatic MFA push before we even submit credentials,
    # causing DOUBLE MFA pushes.
    #
    # Using Chrome DevTools Protocol (CDP) to wipe everything ensures
    # a truly clean slate — exactly one push notification per login.
    driver.execute_cdp_cmd("Storage.clearDataForOrigin", {
        "origin": CITRIX_URL.rstrip("/"),
        "storageTypes": "all",
    })
    # Also clear Microsoft's auth domain — this is where SSO session
    # state lives that can trigger an automatic push.
    driver.execute_cdp_cmd("Storage.clearDataForOrigin", {
        "origin": "https://login.microsoftonline.com",
        "storageTypes": "all",
    })
    driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
    driver.get(CITRIX_URL)

    # --- Wait for the page to load ---
    # WebDriverWait polls the page until the element appears (up to 30 sec).
    # This is better than time.sleep() because it proceeds as soon as ready.
    wait = WebDriverWait(driver, 30)

    # --- Handle the "New Login Instructions" splash page (if present) ---
    # The Citrix site sometimes shows an informational page before the actual
    # login form. If it appears, we need to click the "Continue" button to
    # get past it.
    #
    # The tricky part: the Continue button and the Log On button share the
    # same id (#loginBtn). So after clicking Continue, we wait for the
    # username field to appear — that tells us we've reached the real login page.
    #
    # We use WebDriverWait here (instead of find_element) so the script
    # gives the page enough time to load before deciding the splash page
    # isn't there.
    # We wait for EITHER the splash header OR the username field, whichever
    # shows up first. The old approach waited a full 10 seconds for the splash
    # before giving up — which added 10 seconds to every login that didn't
    # have one. This way the script moves on the instant the page is ready.
    splash_xpath = "//*[contains(text(), 'New Login Instructions')]"
    try:
        print("Checking for 'New Login Instructions' splash page...")
        wait.until(
            lambda d: d.find_elements(By.XPATH, splash_xpath)
            or d.find_elements(By.CSS_SELECTOR, USERNAME_SELECTOR)
        )
        splash = driver.find_elements(By.XPATH, splash_xpath)
        if splash and splash[0].is_displayed():
            print("Found splash page — waiting for Continue button...")
            continue_btn = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#loginBtn"))
            )
            print("Clicking Continue...")
            continue_btn.click()
            # Wait for the login form to appear (proves we got past the splash)
            print("Waiting for login page to load...")
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, USERNAME_SELECTOR))
            )
            print("Login page loaded.")
        else:
            print("No splash page found — proceeding to login.")
    except Exception:
        print("No splash page found — proceeding to login.")

    # --- Fill in username ---
    print("Entering username...")
    username_field = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, USERNAME_SELECTOR))
    )
    username_field.clear()
    username_field.send_keys(username)

    # --- Fill in password ---
    print("Entering password...")
    password_field = wait.until(
        EC.presence_of_element_located((By.CSS_SELECTOR, PASSWORD_SELECTOR))
    )
    password_field.clear()
    password_field.send_keys(password)

    # --- Submit the login form ---
    # This triggers the Microsoft Authenticator push notification.
    print("Submitting login form (this sends the push notification)...")
    submit_btn = driver.find_element(By.CSS_SELECTOR, SUBMIT_SELECTOR)
    submit_btn.click()

    # --- Wait for push approval ---
    # This is where the script pauses and waits for YOU to tap Approve
    # on your phone's Microsoft Authenticator notification + Face ID.
    success = wait_for_push_approval(driver)

    if success:
        print("")
        print("Login complete!")
    else:
        print("")
        print("Push approval timed out, but checking if the page loaded anyway...")
        # Give it a few more seconds — the redirect may be in progress
        time.sleep(5)
        if is_on_portal(driver):
            print("Portal loaded! Continuing with app launches.")
            success = True
        else:
            print("Login may not have completed. The browser is still open —")
            print("you can finish logging in manually if needed.")

    if success:
        # --- Dismiss any post-login splash screens ---
        # Citrix often shows "Welcome to Workspace", "Detect Receiver",
        # or similar screens before letting you see your apps. This
        # function handles all the common ones automatically.
        print("\nChecking for post-login splash screens...")
        dismiss_post_login_screens(driver)

        # --- Launch Citrix apps ---
        # Now that we're past all splash screens, find and click on each app.
        launch_citrix_apps(driver, CITRIX_APPS_TO_LAUNCH)

    # --- Stay alive so Chrome stays open (and watch for idleness) ---
    # The script keeps running in the background. Chrome stays open for the
    # user to work with their Citrix apps. The script will exit cleanly when:
    #   - The user presses the hotkey again (Ctrl+Shift+C) → new instance
    #     sends SIGTERM → signal handler calls driver.quit()
    #   - The user presses Ctrl+C in Terminal → SIGINT → same clean shutdown
    #   - The user closes the Terminal window → SIGHUP → same clean shutdown
    #   - AUTO-SHUTDOWN: the user hasn't used Citrix for AUTO_SHUTDOWN_AFTER
    #     seconds → close Citrix apps, Chrome, and this Terminal window
    print("\nDone! Chrome will stay open so you can use your Citrix apps.")
    print("Press Ctrl+Shift+C again (or Ctrl+C) to close Chrome and exit.")
    if AUTO_SHUTDOWN_AFTER > 0:
        print(f"Auto-shutdown: everything closes after "
              f"{AUTO_SHUTDOWN_AFTER // 60} minutes of inactivity.")
    print("Thank you for using the Citrix Auto Opener!")

    idle_shutdown = False
    try:
        # Watch for activity in a loop — the signal handlers will interrupt
        # the sleep when it's time to shut down for other reasons.
        #
        # The idle clock (last_active) resets every time we see the user
        # actively using Citrix. If it runs past AUTO_SHUTDOWN_AFTER without
        # a reset, we tear everything down.
        last_active = time.time()
        while True:
            time.sleep(IDLE_CHECK_INTERVAL if AUTO_SHUTDOWN_AFTER > 0 else 1)
            if AUTO_SHUTDOWN_AFTER <= 0:
                continue  # Feature disabled — just stay alive

            if is_citrix_in_use():
                last_active = time.time()
            elif time.time() - last_active >= AUTO_SHUTDOWN_AFTER:
                idle_minutes = int((time.time() - last_active) / 60)
                print(f"\nNo Citrix activity for {idle_minutes} minutes — "
                      "shutting everything down...")
                idle_shutdown = True
                break
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Belt-and-suspenders: if we somehow get here without the signal
        # handler running, still clean up.
        try:
            driver.quit()
        except Exception:
            pass
        remove_pid_file()
        if idle_shutdown:
            # Close the Citrix app sessions and our own Terminal window.
            # (Only on idle shutdown — a hotkey restart or Ctrl+C keeps the
            # window open so you can see what happened.)
            close_citrix_apps()
            close_terminal_window()


# ---------------------------------------------------------------------------
# STEP 5: RUN IT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    login_to_citrix()
