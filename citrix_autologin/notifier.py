"""
macOS notification delivery via osascript.

All strings passed to osascript are sanitized to prevent injection.
"""

import subprocess


def _sanitize(text):
    """
    Sanitize a string for safe inclusion in an AppleScript string literal.

    Escapes backslashes first (so we don't double-escape), then double quotes.
    Strips any other control characters that could break the osascript command.
    """
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    # Remove any null bytes or other control chars except newline
    text = "".join(c for c in text if c == "\n" or (ord(c) >= 32))
    return text


def notify(message, title="Citrix Auto-Login"):
    """
    Send a macOS notification via osascript.

    If osascript fails (e.g., in a headless CI environment), logs a warning
    and continues — notifications are never critical path.
    """
    safe_message = _sanitize(message)
    safe_title = _sanitize(title)

    script = f'display notification "{safe_message}" with title "{safe_title}"'

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as e:
        # Notification failure is non-critical — log and continue
        print(f"  (notification failed: {e})")
