"""Tests for log rotation and file naming."""

import os
import pytest

from citrix_autologin.logger import DualLogger, LOG_DIR, MAX_LOG_FILES


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Use a temporary directory for log files."""
    test_log_dir = str(tmp_path / "logs")
    monkeypatch.setattr("citrix_autologin.logger.LOG_DIR", test_log_dir)
    return test_log_dir


class TestLogRotation:
    def test_creates_log_directory(self, log_dir):
        """Log directory is created if it doesn't exist."""
        logger = DualLogger()
        assert os.path.isdir(log_dir)
        logger.close()

    def test_creates_log_file(self, log_dir):
        """A log file is created on init."""
        logger = DualLogger()
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        assert len(log_files) == 1
        logger.close()

    def test_log_file_name_format(self, log_dir):
        """Log file name follows YYYY-MM-DD_HH-MM-SS.log format."""
        logger = DualLogger()
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        name = log_files[0]
        # Should match pattern like 2026-03-21_12-00-00.log
        parts = name.replace(".log", "").split("_")
        assert len(parts) == 2
        assert len(parts[0].split("-")) == 3  # YYYY-MM-DD
        assert len(parts[1].split("-")) == 3  # HH-MM-SS
        logger.close()

    def test_rotation_keeps_max_files(self, log_dir):
        """When more than MAX_LOG_FILES exist, oldest are deleted."""
        os.makedirs(log_dir, exist_ok=True)
        # Create 35 fake log files
        for i in range(35):
            fname = f"2026-01-{i+1:02d}_00-00-00.log"
            with open(os.path.join(log_dir, fname), "w") as f:
                f.write("test")

        assert len(os.listdir(log_dir)) == 35

        # Creating a new logger triggers rotation
        logger = DualLogger()
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        # Should have MAX_LOG_FILES + 1 (the new one)
        assert len(log_files) <= MAX_LOG_FILES + 1
        logger.close()

    def test_rotation_deletes_corresponding_screenshots(self, log_dir):
        """Rotation deletes screenshot PNGs that correspond to deleted logs."""
        os.makedirs(log_dir, exist_ok=True)
        # Create old log + screenshot pairs
        for i in range(35):
            fname = f"2026-01-{i+1:02d}_00-00-00"
            with open(os.path.join(log_dir, f"{fname}.log"), "w") as f:
                f.write("test")
            with open(os.path.join(log_dir, f"{fname}_error.png"), "w") as f:
                f.write("fake png")

        assert len(os.listdir(log_dir)) == 70  # 35 logs + 35 screenshots

        logger = DualLogger()
        remaining_logs = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        remaining_pngs = [f for f in os.listdir(log_dir) if f.endswith(".png")]

        # Screenshots should be cleaned up with their logs
        assert len(remaining_pngs) <= len(remaining_logs)
        logger.close()

    def test_rotation_with_no_old_files(self, log_dir):
        """Rotation with fewer than MAX files does nothing."""
        os.makedirs(log_dir, exist_ok=True)
        for i in range(5):
            with open(os.path.join(log_dir, f"2026-03-{i+1:02d}_00-00-00.log"), "w") as f:
                f.write("test")

        logger = DualLogger()
        log_files = [f for f in os.listdir(log_dir) if f.endswith(".log")]
        assert len(log_files) == 6  # 5 existing + 1 new
        logger.close()


class TestDualLogging:
    def test_log_writes_to_file(self, log_dir):
        """log() writes the message to the log file."""
        logger = DualLogger()
        logger.log("Test message")
        logger.close()

        with open(logger.log_path, "r") as f:
            content = f.read()
        assert "Test message" in content

    def test_log_writes_to_stdout(self, log_dir, capsys):
        """log() also prints to stdout."""
        logger = DualLogger()
        logger.log("Stdout test")
        logger.close()

        captured = capsys.readouterr()
        assert "Stdout test" in captured.out

    def test_screenshot_path_set(self, log_dir):
        """Screenshot path is derived from log file name."""
        logger = DualLogger()
        assert logger.screenshot_path.endswith("_error.png")
        assert logger.screenshot_path.replace("_error.png", ".log") == logger.log_path
        logger.close()
