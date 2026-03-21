"""
Configuration loading, validation, and credential retrieval.

Reads ~/.citrix-autologin.yaml for settings and macOS Keychain for credentials.
All config keys are optional — missing keys fall back to hardcoded defaults.
"""

import os
import re
import subprocess
import sys

import yaml

CONFIG_PATH = os.path.expanduser("~/.citrix-autologin.yaml")
KEYCHAIN_SERVICE = "citrix-autologin"

DEFAULTS = {
    "citrix_url": "https://gateway.scmc.org/",
    "push_approval_timeout": 120,
    "app_launch_delay": 3,
    "portal_load_wait": 3,
    "headless": False,
    "apps": [
        "Epic Production",
        "Aria Home",
        "MIM",
        "RayStation 2024A SP3",
    ],
}

# Type expectations for validation
_TYPE_MAP = {
    "citrix_url": str,
    "push_approval_timeout": (int, float),
    "app_launch_delay": (int, float),
    "portal_load_wait": (int, float),
    "headless": bool,
    "apps": list,
    "profiles": dict,
}


def load_config(config_path=None):
    """
    Load and validate the YAML config file.

    Returns a dict with all keys populated (user values merged over defaults).
    Exits with code 1 if the file is missing, malformed, or has invalid types.
    """
    path = config_path or CONFIG_PATH

    if not os.path.exists(path):
        print(f"ERROR: No config found at {path}")
        print("Run ./setup.sh to create one.")
        sys.exit(1)

    try:
        with open(path, "r") as f:
            user_config = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(f"ERROR: Config file is malformed: {e}")
        print(f"Fix {path} or delete it and re-run setup.sh.")
        sys.exit(1)

    if not isinstance(user_config, dict):
        print(f"ERROR: Config file must be a YAML mapping, got {type(user_config).__name__}.")
        sys.exit(1)

    # Type validation
    for key, expected_type in _TYPE_MAP.items():
        if key in user_config:
            if not isinstance(user_config[key], expected_type):
                print(f"ERROR: Invalid config: '{key}' must be a {_type_name(expected_type)}, "
                      f"got {type(user_config[key]).__name__}.")
                sys.exit(1)

    # Merge with defaults
    config = {**DEFAULTS, **user_config}
    return config


def _type_name(t):
    """Human-readable type name for error messages."""
    if isinstance(t, tuple):
        return " or ".join(cls.__name__ for cls in t)
    return t.__name__


def resolve_apps(config, profile_name=None):
    """
    Resolve the app list based on the optional --profile flag.

    Returns the list of app names to launch.
    Exits with code 1 if the profile is unknown or profiles aren't configured.
    """
    if profile_name is None:
        return config.get("apps", DEFAULTS["apps"])

    profiles = config.get("profiles")
    if not profiles:
        print("ERROR: No profiles configured.")
        print("Add a 'profiles' section to ~/.citrix-autologin.yaml")
        sys.exit(1)

    if profile_name not in profiles:
        available = ", ".join(sorted(profiles.keys()))
        print(f"ERROR: Profile '{profile_name}' not found. Available: {available}")
        sys.exit(1)

    profile = profiles[profile_name]
    if not isinstance(profile, dict) or "apps" not in profile:
        print(f"ERROR: Profile '{profile_name}' must have an 'apps' list.")
        sys.exit(1)

    return profile["apps"]


def get_credentials():
    """
    Read Citrix username and password from macOS Keychain.

    Returns (username, password) tuple.
    Exits with code 1 if the keychain entry is not found.
    Falls back to interactive prompt if username can't be parsed.
    """
    try:
        password = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()

        raw = subprocess.check_output(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
            stderr=subprocess.DEVNULL,
        ).decode()

        match = re.search(r'"acct"<blob>="(.+?)"', raw)
        if match:
            username = match.group(1)
        else:
            username = input("Could not read username from Keychain. Enter it: ")

        return username, password

    except subprocess.CalledProcessError:
        print("ERROR: No credentials found in Keychain.")
        print(f'Run: security add-generic-password -a "YOUR_USERNAME" '
              f'-s "{KEYCHAIN_SERVICE}" -w "YOUR_PASSWORD"')
        print("Or re-run ./setup.sh")
        sys.exit(1)
