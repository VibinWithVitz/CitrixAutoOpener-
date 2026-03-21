"""
Playwright-based browser automation for Citrix login and app launching.

Handles:
- Pre-login splash page dismissal ("New Login Instructions")
- Login form fill and submit
- 2FA push notification polling
- Post-login splash screen dismissal (Welcome, Detect Workspace, etc.)
- "All Apps" tab click
- App icon discovery and launch (multiple fallback strategies)
- Auto-minimize browser window (best-effort)
"""

import os
import subprocess
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from . import notifier, logger as logger_mod


# Post-login splash screens: (name, detect_selector, list of dismiss selectors)
SPLASH_SCREENS = [
    {
        "name": "Welcome to Citrix Workspace app",
        "detect": "[class*='WelcomeToReceiver']",
        "dismiss_options": [
            "#protocolhandler-welcome-installButton",
            "#protocolhandler-welcome-useFullVersion",
            "button:has-text('Got it')",
            "a:has-text('Got it')",
            "button:has-text('Continue')",
            "a:has-text('Continue')",
            "button:has-text('OK')",
            "a:has-text('OK')",
            ".welcome-button",
            ".btn-primary",
        ],
    },
    {
        "name": "Detect Citrix Workspace / Receiver",
        "detect": "#protocolhandler-detect-page",
        "dismiss_options": [
            "#protocolhandler-detect-alreadyInstalled",
            "a:has-text('Already installed')",
            "a:has-text('Use web browser')",
            "a:has-text('Use light version')",
        ],
    },
    {
        "name": "Citrix Workspace not detected",
        "detect": "#protocolhandler-notDetected-page",
        "dismiss_options": [
            "#protocolhandler-notDetected-useFullVersion",
            "a:has-text('Already installed')",
            "a:has-text('Use web browser')",
            "a:has-text('Use light version')",
        ],
    },
    {
        "name": "Cookie / privacy consent banner",
        "detect": "[class*='cookie'], [class*='consent']",
        "dismiss_options": [
            "button:has-text('Accept')",
            "a:has-text('Accept')",
            "button:has-text('OK')",
            "button:has-text('Got it')",
        ],
    },
]

# Login URL indicators — if the URL contains any of these, we're still on a login page
LOGIN_INDICATORS = ["login", "auth", "oauth", "signin", "mfa", "verify"]


def _clear_stale_lock(profile_dir):
    """Remove stale Chromium lock files from a previous crashed run."""
    lock_file = os.path.join(profile_dir, "SingletonLock")
    if os.path.exists(lock_file):
        try:
            os.remove(lock_file)
        except OSError:
            pass


def _retry(fn, logger, max_attempts=3, delay=3, description="operation"):
    """
    Retry a callable up to max_attempts times with a delay between attempts.

    Returns the result of fn() on success.
    Raises the last exception on final failure.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                logger.log(f"  Attempt {attempt}/{max_attempts} failed for {description}: {e}")
                logger.log(f"  Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                logger.log(f"  All {max_attempts} attempts failed for {description}: {e}")
    raise last_error


def run_login(config, apps, log):
    """
    Main browser automation flow.

    Args:
        config: Dict from config.load_config()
        apps: List of app names to launch
        log: DualLogger instance
    """
    profile_dir = os.path.expanduser("~/CitrixAutoLogin/playwright-profile")
    os.makedirs(profile_dir, exist_ok=True)
    _clear_stale_lock(profile_dir)

    headless = config.get("headless", False)

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=headless,
                args=["--start-maximized"],
                no_viewport=True,
            )
        except Exception as e:
            log.log(f"ERROR: Could not launch browser: {e}")
            notifier.notify(f"Citrix login failed: Could not launch browser. {e}")
            return 2

        page = context.pages[0] if context.pages else context.new_page()

        try:
            exit_code = _run_flow(page, config, apps, log, headless)
        except Exception as e:
            log.log(f"ERROR: Unexpected error: {e}")
            log.save_screenshot(page)
            notifier.notify(f"Citrix login failed: {e}. Screenshot saved.")
            exit_code = 2
        finally:
            context.close()

        return exit_code


def _run_flow(page, config, apps, log, headless):
    """Execute the full login flow on the given page."""
    citrix_url = config["citrix_url"]
    timeout = config["push_approval_timeout"]

    # --- Navigate to login page ---
    log.log(f"Opening {citrix_url}...")
    try:
        page.goto(citrix_url, wait_until="networkidle", timeout=30000)
    except PlaywrightTimeout:
        log.log("ERROR: Page load timed out.")
        log.save_screenshot(page)
        notifier.notify("Citrix login failed: Page load timed out.")
        return 2

    # --- Handle pre-login splash page ---
    _handle_pre_login_splash(page, log)

    # --- Check headless compatibility ---
    if headless:
        try:
            page.wait_for_selector("#login", timeout=30000)
        except PlaywrightTimeout:
            log.log("ERROR: Headless mode may be blocked by the portal.")
            log.log("Set headless: false in ~/.citrix-autologin.yaml")
            notifier.notify("Citrix login failed: Headless may be blocked. Set headless: false in config.")
            return 2

    # --- Fill login form ---
    from . import config as config_mod
    username, password = config_mod.get_credentials()
    log.log(f"Logging in as {username}...")

    def fill_and_submit():
        page.wait_for_selector("#login", timeout=10000)
        # Wait for Citrix jQuery/JS framework to finish initializing form handlers.
        # Without this, fill() can fire before event handlers are bound, causing
        # the values to be wiped or the submit to be ignored.
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        page.fill("#login", "")
        page.fill("#login", username)
        page.fill("#passwd", "")
        page.fill("#passwd", password)
        log.log("Submitting login form...")
        page.click("#loginBtn")

    _retry(fill_and_submit, log, description="login form fill")

    # --- Wait for 2FA approval ---
    notifier.notify("Check your phone — approve the Microsoft Authenticator notification")
    log.log("")
    log.log("=" * 50)
    log.log("  CHECK YOUR PHONE!")
    log.log("  Approve the Microsoft Authenticator notification")
    log.log("=" * 50)
    log.log("")

    success = _wait_for_push_approval(page, timeout, log)
    if not success:
        log.save_screenshot(page)
        notifier.notify(f"Login timed out — no approval received in {timeout} seconds")
        return 3

    log.log("Login complete!")
    notifier.notify("Logged in! Launching your apps...")

    # --- Dismiss post-login splash screens ---
    log.log("Checking for post-login splash screens...")
    _dismiss_post_login_screens(page, log)

    # --- Launch apps ---
    launched_count = _launch_apps(page, apps, config, log)

    # --- Auto-minimize browser (best-effort) ---
    if not headless:
        _auto_minimize(log)

    # --- Result ---
    if launched_count == 0 and len(apps) > 0:
        notifier.notify("Citrix login failed: No apps could be found on the portal.")
        return 2

    app_names = ", ".join(apps[:4])
    if len(apps) > 4:
        app_names += f" (+{len(apps) - 4} more)"
    notifier.notify(f"All apps launched: {app_names}")
    return 0


def _handle_pre_login_splash(page, log):
    """
    Handle the "New Login Instructions" splash page if present.

    This page shares #loginBtn with the real Log On button. After clicking
    Continue, we wait for the page to fully navigate and the login form's
    JS framework to initialize before proceeding.
    """
    try:
        log.log("Checking for 'New Login Instructions' splash page...")
        header = page.locator("//*[contains(text(), 'New Login Instructions')]")
        if header.count() > 0 and header.first.is_visible():
            log.log("Found splash page — clicking Continue...")
            page.click("#loginBtn")
            # Wait for navigation to the login form page
            page.wait_for_load_state("networkidle")
            page.wait_for_selector("#login", timeout=15000)
            log.log("Login page loaded.")
    except (PlaywrightTimeout, Exception):
        log.log("No splash page found — proceeding to login.")


def _wait_for_push_approval(page, timeout, log):
    """
    Poll the browser URL every 2 seconds to detect 2FA approval.

    Returns True if login succeeded, False on timeout.
    """
    login_url = page.url
    log.log(f"Current page: {login_url}")
    log.log(f"Waiting up to {timeout} seconds for approval...")

    start_time = time.time()
    poll_interval = 2

    while time.time() - start_time < timeout:
        elapsed = int(time.time() - start_time)
        current_url = page.url

        still_on_login = any(
            indicator in current_url.lower() for indicator in LOGIN_INDICATORS
        )

        if current_url != login_url and not still_on_login:
            log.log(f"\nLogin detected! Redirected to: {current_url}")
            return True

        if elapsed % 10 == 0 and elapsed > 0:
            log.log(f"  Still waiting... ({elapsed}s elapsed)")

        time.sleep(poll_interval)

    log.log(f"\nTimed out after {timeout} seconds waiting for push approval.")
    return False


def _dismiss_post_login_screens(page, log):
    """
    Dismiss Citrix splash screens that appear after login.

    Runs up to 3 passes because dismissing one screen can reveal another.
    This function manages its own retry logic independent of the general retry wrapper.
    """
    for pass_num in range(3):
        found_any = False

        for screen in SPLASH_SCREENS:
            try:
                detector = page.locator(screen["detect"])
                if detector.count() > 0 and detector.first.is_visible():
                    log.log(f"  Found: '{screen['name']}' — dismissing...")
                    found_any = True

                    dismissed = False
                    for dismiss_sel in screen["dismiss_options"]:
                        try:
                            btn = page.locator(dismiss_sel)
                            if btn.count() > 0 and btn.first.is_visible():
                                log.log("  Clicking dismiss button...")
                                btn.first.click()
                                time.sleep(2)
                                dismissed = True
                                break
                        except Exception:
                            continue

                    if not dismissed:
                        log.log(f"  WARNING: Found '{screen['name']}' but no dismiss button.")
            except Exception:
                continue

        if not found_any:
            break

    log.log("  Post-login screens handled.")


def _launch_apps(page, app_names, config, log):
    """
    Find and click each app on the Citrix portal.

    Returns the number of apps successfully launched.
    """
    if not app_names:
        log.log("No apps configured to launch.")
        return 0

    portal_load_wait = config.get("portal_load_wait", 3)
    app_launch_delay = config.get("app_launch_delay", 3)

    log.log(f"\nWaiting {portal_load_wait} seconds for portal to fully load...")
    time.sleep(portal_load_wait)

    # Click "All Apps" tab to show full app list
    try:
        all_apps_btn = page.locator("#allAppsFilterBtn")
        if all_apps_btn.count() > 0 and all_apps_btn.first.is_visible():
            log.log("Clicking 'All Apps' to show the full app list...")
            all_apps_btn.first.click()
            time.sleep(2)
    except Exception:
        log.log("  (No 'All Apps' filter found — portal may already show all apps)")

    launched_count = 0

    for app_name in app_names:
        log.log(f"\nLooking for app: '{app_name}'...")

        def try_launch():
            # Strategy 1: Find img by alt text → click parent <a>
            strategies = [
                page.locator(f'img[alt="{app_name}"]').locator("xpath=ancestor::a[1]"),
                page.locator(f'img[alt="{app_name}"]').locator(".."),
                page.locator(f'a[title="{app_name}"]'),
                page.locator(f'[data-name="{app_name}"]'),
            ]

            for locator in strategies:
                try:
                    if locator.count() > 0 and locator.first.is_visible():
                        log.log(f"  Found '{app_name}' — clicking to launch...")
                        locator.first.click()
                        return True
                except Exception:
                    continue
            raise LookupError(f"App '{app_name}' not found on portal")

        try:
            _retry(try_launch, log, description=f"launching '{app_name}'")
            log.log(f"  '{app_name}' launch initiated!")
            launched_count += 1

            if app_launch_delay > 0 and app_name != app_names[-1]:
                log.log(f"  Waiting {app_launch_delay} seconds before next app...")
                time.sleep(app_launch_delay)
        except LookupError:
            log.log(f"  WARNING: Could not find '{app_name}' on the portal page.")
            log.log("  Make sure the name matches exactly what you see on screen.")

    log.log(f"\nApp launches complete! ({launched_count}/{len(app_names)} launched)")
    return launched_count


def _auto_minimize(log):
    """
    Best-effort: minimize the Playwright Chromium window via AppleScript.

    If this fails for any reason, log a debug warning and continue.
    """
    try:
        subprocess.run(
            [
                "osascript", "-e",
                'tell application "Chromium" to set miniaturized of every window to true',
            ],
            capture_output=True,
            timeout=5,
        )
        log.log("Browser window minimized.")
    except Exception:
        # Try alternative process name
        try:
            subprocess.run(
                [
                    "osascript", "-e",
                    'tell application "Google Chrome for Testing" to set miniaturized of every window to true',
                ],
                capture_output=True,
                timeout=5,
            )
            log.log("Browser window minimized.")
        except Exception:
            log.log("  (auto-minimize failed — browser window may still be visible)")
