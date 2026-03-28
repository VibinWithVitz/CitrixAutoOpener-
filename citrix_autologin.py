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

# Seconds to wait for the portal page to fully load before looking for apps.
PORTAL_LOAD_WAIT = 3

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

        # Check if we've reached the portal
        current_url = driver.current_url
        if current_url != login_url and is_on_portal(driver):
            print(f"\nLogin detected! Redirected to: {current_url}")
            return True

        # Also check portal elements even if URL hasn't changed much
        if is_on_portal(driver):
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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def cleanup_previous_session():
    """
    Cleans up any leftover Chrome/chromedriver processes from a previous run.

    WHY THIS IS NEEDED:
    The script uses a dedicated Chrome profile folder (~/CitrixAutoLogin/chrome-profile).
    Chrome locks this folder while it's open — if a previous run of this script is
    still running (e.g., sitting at the "Press Enter to close" prompt), the profile
    folder stays locked. A new run can't open Chrome with the same profile and crashes
    with a "DevToolsActivePort file doesn't exist" error.

    Even after killing the old processes, Chrome can leave behind lock files and
    crash state that prevent a clean restart. This function handles all of that.
    """
    print("Checking for leftover sessions from previous runs...")

    script_profile = os.path.expanduser("~/CitrixAutoLogin/chrome-profile")

    # Step 1: Kill any chromedriver processes from a previous run.
    # chromedriver is a separate background process that Selenium spawns.
    # If the previous script didn't exit cleanly, it may still be running.
    subprocess.run(["pkill", "-f", "chromedriver"], capture_output=True)

    # Step 2: Kill any Chrome windows using our specific profile folder.
    # We only target Chrome instances using OUR dedicated profile — not any
    # normal Chrome windows the user might have open.
    #
    # Chrome spawns many child processes (renderers, GPU, utility) that all
    # hold locks on the profile directory. We must wait for ALL of them to
    # exit before launching a new Chrome — otherwise the new instance sees
    # a locked profile and shows "Something went wrong" dialogs.
    #
    # Strategy: SIGTERM first, then poll until all processes are gone.
    # If any linger after 5 seconds, escalate to SIGKILL and poll again.
    subprocess.run(
        ["pkill", "-f", f"--user-data-dir={script_profile}"],
        capture_output=True
    )

    # Poll until all Chrome processes using our profile have exited
    def _profile_processes_alive():
        result = subprocess.run(
            ["pgrep", "-f", f"--user-data-dir={script_profile}"],
            capture_output=True, text=True
        )
        return bool(result.stdout.strip())

    # Wait up to 5 seconds for graceful exit
    for _ in range(10):
        if not _profile_processes_alive():
            break
        time.sleep(0.5)

    # If processes are still alive, force-kill and wait again
    if _profile_processes_alive():
        print("  Chrome didn't exit gracefully — force-killing...")
        subprocess.run(
            ["pkill", "-9", "-f", f"--user-data-dir={script_profile}"],
            capture_output=True
        )
        for _ in range(10):
            if not _profile_processes_alive():
                break
            time.sleep(0.5)

    # Step 3: Remove Chrome's lock files so the profile can be reused.
    # We do NOT delete the entire profile — keeping it means Chrome
    # remembers that Citrix Workspace is installed, so the "Welcome"
    # and "Detect Citrix" splash screens won't appear on every run.
    #
    # On macOS, SingletonLock is a symlink, so we need os.path.islink()
    # to detect it (os.path.exists() follows the symlink and may miss it).
    lock_files = ["SingletonLock", "SingletonSocket", "SingletonCookie"]
    for lock_name in lock_files:
        lock_path = os.path.join(script_profile, lock_name)
        try:
            if os.path.islink(lock_path) or os.path.exists(lock_path):
                os.unlink(lock_path)
                print(f"  Removed leftover lock file: {lock_name}")
        except OSError:
            pass  # Already gone, that's fine

    print("  Ready for new session.")


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

    # Keep Chrome open after the script exits.
    # By default, when the Python process ends, chromedriver shuts down and
    # takes Chrome with it. "detach" tells chromedriver to leave Chrome running.
    chrome_options.add_experimental_option("detach", True)

    # Prevent the "Chrome didn't shut down correctly — Restore pages?" bubble.
    chrome_options.add_argument("--hide-crash-restore-bubble")

    # Disable Chrome's "Save password?" popup.
    # This covers the prompt that appears after login asking to save credentials.
    chrome_options.add_experimental_option("prefs", {
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
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

    driver = webdriver.Chrome(options=chrome_options)
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

    for attempt in range(5):
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

    print(f"\nWaiting {PORTAL_LOAD_WAIT} seconds for portal to fully load...")
    time.sleep(PORTAL_LOAD_WAIT)

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

    for app_name in app_names:
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
        ]

        for method, selector in strategies:
            try:
                elements = driver.find_elements(method, selector)
                # Filter to only visible elements
                clickable = [el for el in elements if el.is_displayed()]

                if clickable:
                    print(f"  Found '{app_name}' — clicking to launch...")
                    clickable[0].click()
                    launched = True
                    break
            except Exception:
                continue

        if launched:
            print(f"  '{app_name}' launch initiated!")
            if delay > 0 and app_name != app_names[-1]:
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
    1. Read credentials from Keychain
    2. Open Chrome and navigate to the login page
    3. Fill in username and password
    4. Submit the form (triggers Authenticator push)
    5. Wait for you to approve on your phone
    6. Launch your configured Citrix apps from the portal
    """
    # --- Clean up any previous session ---
    # This ensures the Chrome profile lock is released before we try to launch
    # a new browser window, so the script works even if you run it again without
    # closing the previous Terminal window or Chrome window.
    cleanup_previous_session()

    # --- Get credentials ---
    print("Reading credentials from Keychain...")
    username, password = get_credentials_from_keychain()
    print(f"Got credentials for: {username}")

    # --- Launch browser ---
    print(f"Opening Chrome to {CITRIX_URL}...")
    driver = create_browser()

    # Clear ALL cookies so the login flow starts completely fresh.
    #
    # Previously we tried to preserve Microsoft's "remember this device"
    # cookies to skip a second MFA push, but stale or partially-expired
    # Microsoft cookies actually cause DOUBLE MFA pushes — the auth flow
    # tries the cached session (push #1), it fails, then falls back to
    # fresh auth (push #2). Clearing everything ensures exactly one push.
    #
    # We load a non-existent path on the Citrix domain first — this gives
    # us access to the domain's cookies without triggering the actual login
    # flow. After clearing, we navigate to the real URL with a clean slate.
    citrix_domain = CITRIX_URL.split("//")[1].split("/")[0]  # e.g. "gateway.scmc.org"
    driver.get(f"https://{citrix_domain}/favicon.ico")
    driver.delete_all_cookies()
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
    try:
        print("Checking for 'New Login Instructions' splash page...")
        instructions_header = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((
                By.XPATH, "//*[contains(text(), 'New Login Instructions')]"
            ))
        )
        if instructions_header.is_displayed():
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

    # Leave Chrome open so the user can go back and launch more apps manually.
    # The cleanup_previous_session() function at the start of the next run
    # will handle any leftover Chrome/chromedriver processes if needed.
    print("\nDone! Chrome will stay open so you can launch more apps if needed.")
    print("Thank you for using the Citrix Auto Opener!")


# ---------------------------------------------------------------------------
# STEP 5: RUN IT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    login_to_citrix()
