"""Tests for config loading, validation, profiles, and credential retrieval."""

import os
import pytest
import tempfile

from citrix_autologin.config import load_config, resolve_apps, DEFAULTS


@pytest.fixture
def config_dir(tmp_path):
    """Create a temporary directory for test config files."""
    return tmp_path


def write_config(path, content):
    """Helper to write a YAML config file."""
    with open(path, "w") as f:
        f.write(content)
    return str(path)


class TestLoadConfig:
    def test_missing_file_exits(self, config_dir):
        """Config file missing → exit code 1."""
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(config_dir / "nonexistent.yaml"))
        assert exc_info.value.code == 1

    def test_empty_file_uses_defaults(self, config_dir):
        """Empty YAML file → all defaults applied."""
        path = write_config(config_dir / "config.yaml", "")
        config = load_config(path)
        assert config["citrix_url"] == DEFAULTS["citrix_url"]
        assert config["push_approval_timeout"] == DEFAULTS["push_approval_timeout"]
        assert config["apps"] == DEFAULTS["apps"]

    def test_partial_config_merges_with_defaults(self, config_dir):
        """Partial config → user values override, rest are defaults."""
        path = write_config(config_dir / "config.yaml", 'citrix_url: "https://example.com/"\n')
        config = load_config(path)
        assert config["citrix_url"] == "https://example.com/"
        assert config["push_approval_timeout"] == DEFAULTS["push_approval_timeout"]

    def test_full_config(self, config_dir):
        """All keys provided → all user values used."""
        path = write_config(config_dir / "config.yaml", """
citrix_url: "https://test.example.com/"
push_approval_timeout: 60
app_launch_delay: 5
portal_load_wait: 10
headless: true
apps:
  - "App One"
  - "App Two"
""")
        config = load_config(path)
        assert config["citrix_url"] == "https://test.example.com/"
        assert config["push_approval_timeout"] == 60
        assert config["app_launch_delay"] == 5
        assert config["portal_load_wait"] == 10
        assert config["headless"] is True
        assert config["apps"] == ["App One", "App Two"]

    def test_malformed_yaml_exits(self, config_dir):
        """Invalid YAML syntax → exit code 1."""
        path = write_config(config_dir / "config.yaml", "{{invalid yaml")
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        assert exc_info.value.code == 1

    def test_wrong_type_exits(self, config_dir):
        """Wrong type for a key → exit code 1."""
        path = write_config(config_dir / "config.yaml", 'push_approval_timeout: "not a number"\n')
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        assert exc_info.value.code == 1

    def test_non_dict_yaml_exits(self, config_dir):
        """YAML that parses to a list instead of dict → exit code 1."""
        path = write_config(config_dir / "config.yaml", "- item1\n- item2\n")
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        assert exc_info.value.code == 1

    def test_apps_wrong_type_exits(self, config_dir):
        """apps as a string instead of list → exit code 1."""
        path = write_config(config_dir / "config.yaml", 'apps: "not a list"\n')
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        assert exc_info.value.code == 1

    def test_headless_wrong_type_exits(self, config_dir):
        """headless as a string instead of bool → exit code 1."""
        path = write_config(config_dir / "config.yaml", 'headless: "yes"\n')
        with pytest.raises(SystemExit) as exc_info:
            load_config(path)
        assert exc_info.value.code == 1

    def test_float_timeout_accepted(self, config_dir):
        """Float values for timeout should be accepted."""
        path = write_config(config_dir / "config.yaml", "push_approval_timeout: 90.5\n")
        config = load_config(path)
        assert config["push_approval_timeout"] == 90.5


class TestResolveApps:
    def test_no_profile_returns_default_apps(self):
        """No --profile flag → use top-level apps list."""
        config = {"apps": ["App A", "App B"]}
        assert resolve_apps(config, None) == ["App A", "App B"]

    def test_no_profile_no_apps_returns_defaults(self):
        """No --profile and no apps in config → use hardcoded defaults."""
        config = {}
        assert resolve_apps(config, None) == DEFAULTS["apps"]

    def test_valid_profile(self):
        """Valid profile name → return profile's app list."""
        config = {
            "apps": ["Default App"],
            "profiles": {
                "clinic": {"apps": ["Epic", "Aria"]},
                "planning": {"apps": ["MIM"]},
            },
        }
        assert resolve_apps(config, "clinic") == ["Epic", "Aria"]
        assert resolve_apps(config, "planning") == ["MIM"]

    def test_unknown_profile_exits(self):
        """Unknown profile name → exit code 1."""
        config = {
            "profiles": {"clinic": {"apps": ["Epic"]}},
        }
        with pytest.raises(SystemExit) as exc_info:
            resolve_apps(config, "nonexistent")
        assert exc_info.value.code == 1

    def test_no_profiles_section_exits(self):
        """--profile flag but no profiles in config → exit code 1."""
        config = {"apps": ["App A"]}
        with pytest.raises(SystemExit) as exc_info:
            resolve_apps(config, "clinic")
        assert exc_info.value.code == 1

    def test_profile_without_apps_key_exits(self):
        """Profile exists but has no 'apps' key → exit code 1."""
        config = {
            "profiles": {"clinic": {"description": "no apps here"}},
        }
        with pytest.raises(SystemExit) as exc_info:
            resolve_apps(config, "clinic")
        assert exc_info.value.code == 1
