"""
Dual logging (stdout + file) with log rotation and screenshot support.

Log files are stored in ~/CitrixAutoLogin/logs/ with timestamps.
Keeps the 30 most recent .log files and their corresponding screenshots.
"""

import os
import sys
from datetime import datetime


LOG_DIR = os.path.expanduser("~/CitrixAutoLogin/logs")
MAX_LOG_FILES = 30


class DualLogger:
    """Writes to both stdout and a log file simultaneously."""

    def __init__(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self._rotate_logs()

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_path = os.path.join(LOG_DIR, f"{timestamp}.log")
        self.screenshot_path = os.path.join(LOG_DIR, f"{timestamp}_error.png")

        try:
            self._log_file = open(self.log_path, "w")
        except IOError as e:
            print(f"  (warning: could not create log file: {e})")
            self._log_file = None

    def log(self, message):
        """Write a message to both stdout and the log file."""
        print(message)
        if self._log_file:
            try:
                self._log_file.write(message + "\n")
                self._log_file.flush()
            except IOError:
                pass  # Log write failure is non-critical

    def save_screenshot(self, page):
        """Take a screenshot of the current browser page and save it."""
        try:
            page.screenshot(path=self.screenshot_path)
            self.log(f"Screenshot saved: {self.screenshot_path}")
        except Exception as e:
            self.log(f"  (screenshot failed: {e})")

    def close(self):
        """Close the log file."""
        if self._log_file:
            try:
                self._log_file.close()
            except IOError:
                pass

    def _rotate_logs(self):
        """Delete old log files, keeping only the most recent MAX_LOG_FILES."""
        try:
            log_files = sorted(
                [f for f in os.listdir(LOG_DIR) if f.endswith(".log")],
                reverse=True,
            )

            for old_log in log_files[MAX_LOG_FILES:]:
                log_path = os.path.join(LOG_DIR, old_log)
                # Delete the log file
                try:
                    os.remove(log_path)
                except OSError:
                    pass

                # Delete corresponding screenshot if it exists
                screenshot_name = old_log.replace(".log", "_error.png")
                screenshot_path = os.path.join(LOG_DIR, screenshot_name)
                if os.path.exists(screenshot_path):
                    try:
                        os.remove(screenshot_path)
                    except OSError:
                        pass
        except OSError:
            pass  # Log rotation failure is non-critical
