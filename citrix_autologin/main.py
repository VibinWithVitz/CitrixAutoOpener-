"""
Entry point for CitrixAutoOpener v2.

Orchestrates: PID lock → config load → credential retrieval → browser login → app launch.
"""

import argparse
import os
import sys
import signal

from . import config as config_mod
from . import browser
from .logger import DualLogger
from .notifier import notify


LOCK_FILE = os.path.expanduser("~/CitrixAutoLogin/.lock")


def _acquire_lock():
    """
    Acquire a PID lock to prevent double-invocation.

    If another instance is running, print a message and exit.
    If a stale lock exists (process no longer alive), clear it and proceed.
    """
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)

    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Check if the process is still alive
            os.kill(old_pid, 0)
            # Process is alive — another instance is running
            print(f"Already running (PID {old_pid}). Exiting.")
            sys.exit(0)
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            # PID is invalid or process is dead — stale lock
            pass

    # Write our PID
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_lock():
    """Remove the PID lock file."""
    try:
        os.remove(LOCK_FILE)
    except OSError:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Citrix Auto-Login — automated Citrix portal login and app launching"
    )
    parser.add_argument(
        "--profile",
        help="Named profile from config (e.g., 'clinic', 'planning')",
        default=None,
    )
    parser.add_argument(
        "--config",
        help="Path to config file (default: ~/.citrix-autologin.yaml)",
        default=None,
    )
    args = parser.parse_args()

    # --- PID lock ---
    _acquire_lock()

    # Ensure lock is released on exit or signal
    def cleanup(*_):
        _release_lock()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        # --- Logger ---
        log = DualLogger()

        log.log("=" * 50)
        log.log("  Citrix Auto-Login v2")
        log.log("=" * 50)

        # --- Config ---
        log.log("Loading config...")
        config = config_mod.load_config(args.config)

        # --- Resolve app list ---
        apps = config_mod.resolve_apps(config, args.profile)
        if args.profile:
            log.log(f"Using profile: {args.profile} ({len(apps)} apps)")
        else:
            log.log(f"Using default app list ({len(apps)} apps)")

        # --- Run browser automation ---
        exit_code = browser.run_login(config, apps, log)

        log.close()
        sys.exit(exit_code)

    finally:
        _release_lock()


if __name__ == "__main__":
    main()
