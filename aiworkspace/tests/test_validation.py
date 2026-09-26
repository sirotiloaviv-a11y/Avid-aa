import tempfile
import unittest
from pathlib import Path

from aiworkspace.config import load_settings, parse_env_file
from aiworkspace.ratelimit import RateLimiter
from aiworkspace.validation import (
    ValidationError,
    parse_json_object,
    title_from_message,
    validate_id,
    validate_message,
    validate_title,
)


class MessageValidationTest(unittest.TestCase):
    def test_accepts_hebrew_and_strips_whitespace(self):
        self.assertEqual(validate_message("  שלום עולם \n", 100), "שלום עולם")

    def test_rejects_empty_and_whitespace(self):
        for value in ["", "   ", "\n\t", "\x00\x01"]:
            with self.assertRaises(ValidationError):
                validate_message(value, 100)

    def test_rejects_non_strings(self):
        for value in [None, 5, ["x"], {"a": 1}]:
            with self.assertRaises(ValidationError):
                validate_message(value, 100)

    def test_length_limit(self):
        self.assertEqual(len(validate_message("a" * 100, 100)), 100)
        with self.assertRaises(ValidationError):
            validate_message("a" * 101, 100)

    def test_strips_control_characters_but_keeps_newlines_and_tabs(self):
        self.assertEqual(validate_message("a\x00b\x1bc\n\td", 100), "abc\n\td")

    def test_keeps_bidi_marks(self):
        # U+200F RIGHT-TO-LEFT MARK is legitimate in Hebrew text.
        self.assertEqual(validate_message("abc‏שלום", 100), "abc‏שלום")


class TitleValidationTest(unittest.TestCase):
    def test_collapses_whitespace(self):
        self.assertEqual(validate_title("  my   chat \n", 50), "my chat")

    def test_rejects_bad_titles(self):
        for value in ["", "   ", None, 3]:
            with self.assertRaises(ValidationError):
                validate_title(value, 50)
        with self.assertRaises(ValidationError):
            validate_title("x" * 51, 50)

    def test_title_from_message(self):
        self.assertEqual(title_from_message("short"), "short")
        long = title_from_message("word " * 40, 20)
        self.assertLessEqual(len(long), 20)
        self.assertTrue(long.endswith("…"))


class IdAndJsonTest(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(validate_id("a" * 32), "a" * 32)
        for bad in ["", "A" * 32, "a" * 31, "../etc/passwd", "a" * 32 + "\n"]:
            with self.assertRaises(ValidationError):
                validate_id(bad)

    def test_json(self):
        self.assertEqual(parse_json_object(b'{"a": 1}'), {"a": 1})
        for bad in [b"not json", b"[1,2]", b'"s"', b"\xff\xfe"]:
            with self.assertRaises(ValidationError):
                parse_json_object(bad)


class ConfigTest(unittest.TestCase):
    def test_defaults_to_demo_without_key(self):
        s = load_settings({}, env_file=None)
        self.assertEqual(s.resolved_provider, "demo")
        self.assertEqual(s.host, "127.0.0.1")

    def test_auto_selects_anthropic_with_key_and_hides_key(self):
        s = load_settings({"ANTHROPIC_API_KEY": "sk-test-secret"}, env_file=None)
        self.assertEqual(s.resolved_provider, "anthropic")
        self.assertNotIn("sk-test-secret", repr(s))

    def test_model_is_configurable(self):
        s = load_settings({"AIWS_MODEL": "claude-sonnet-5"}, env_file=None)
        self.assertEqual(s.anthropic_model, "claude-sonnet-5")

    def test_refuses_non_loopback_host(self):
        for host in ["0.0.0.0", "192.168.1.5", "example.com"]:
            with self.assertRaises(ValueError):
                load_settings({"AIWS_HOST": host}, env_file=None)

    def test_rejects_bad_values(self):
        bad = [
            {"AIWS_PROVIDER": "openai"},
            {"AIWS_PROVIDER": "anthropic"},  # no key
            {"AIWS_MAX_OUTPUT_TOKENS": "0"},
            {"AIWS_MAX_OUTPUT_TOKENS": "lots"},
            {"AIWS_ANTHROPIC_FALLBACKS": "maybe"},
        ]
        for env in bad:
            with self.assertRaises(ValueError, msg=str(env)):
                load_settings(env, env_file=None)

    def test_env_file_parsing_and_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(
                "# comment\nexport AIWS_MODEL='from-file'\nAIWS_PORT=\"9000\"\nnonsense\n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_env_file(path), {"AIWS_MODEL": "from-file", "AIWS_PORT": "9000"}
            )
            s = load_settings({"AIWS_PORT": "9100"}, env_file=path)
            self.assertEqual(s.anthropic_model, "from-file")
            self.assertEqual(s.port, 9100)  # real environment wins


class RateLimiterTest(unittest.TestCase):
    def test_window(self):
        now = [0.0]
        rl = RateLimiter(2, window_s=60, clock=lambda: now[0])
        self.assertEqual(rl.try_acquire(), 0)
        self.assertEqual(rl.try_acquire(), 0)
        self.assertAlmostEqual(rl.try_acquire(), 60)
        now[0] = 30
        self.assertAlmostEqual(rl.try_acquire(), 30)
        now[0] = 60
        self.assertEqual(rl.try_acquire(), 0)


if __name__ == "__main__":
    unittest.main()
