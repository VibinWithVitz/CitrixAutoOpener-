"""Tests for notification sanitization and command building."""

from citrix_autologin.notifier import _sanitize


class TestSanitize:
    def test_normal_string(self):
        """Normal strings pass through unchanged."""
        assert _sanitize("Hello world") == "Hello world"

    def test_double_quotes_escaped(self):
        """Double quotes are escaped for AppleScript."""
        assert _sanitize('Say "hello"') == 'Say \\"hello\\"'

    def test_backslash_escaped(self):
        """Backslashes are escaped."""
        assert _sanitize("path\\to\\file") == "path\\\\to\\\\file"

    def test_single_quotes_pass_through(self):
        """Single quotes are safe in double-quoted AppleScript strings."""
        assert _sanitize("it's fine") == "it's fine"

    def test_injection_attempt_neutralized(self):
        """Attempted AppleScript injection is neutralized."""
        malicious = 'Epic"; do shell script "rm -rf ~'
        result = _sanitize(malicious)
        assert '"' not in result.replace('\\"', '')  # No unescaped quotes

    def test_null_bytes_stripped(self):
        """Null bytes and control characters are stripped."""
        assert _sanitize("hello\x00world") == "helloworld"

    def test_newlines_preserved(self):
        """Newlines are allowed (they're valid in notifications)."""
        assert _sanitize("line1\nline2") == "line1\nline2"

    def test_non_string_converted(self):
        """Non-string inputs are converted to strings."""
        assert _sanitize(42) == "42"
        assert _sanitize(None) == "None"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert _sanitize("") == ""

    def test_unicode_preserved(self):
        """Unicode characters pass through."""
        assert _sanitize("✓ Done") == "✓ Done"

    def test_backslash_then_quote(self):
        """Backslash followed by quote: both are escaped correctly."""
        result = _sanitize('test\\"end')
        # Backslash becomes \\, then " becomes \"
        assert result == 'test\\\\\\"end'

    def test_dollar_sign_preserved(self):
        """Dollar signs pass through (not special in AppleScript strings)."""
        assert _sanitize("$100") == "$100"
