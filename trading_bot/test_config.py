"""Tests for config: .env loading and ENVIRONMENT. Run from trading_bot/:  python -m unittest -v"""

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config


class TestDotenv(unittest.TestCase):
    def load(self, text, **env):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env, clear=True):
            path = Path(d) / ".env"
            path.write_text(text)
            config._load_dotenv(path)
            return dict(os.environ)

    def test_parses_values_comments_quotes(self):
        env = self.load('# c\nA=1\nexport B="two words"\nC=\'x=y\'\n\nnot a pair\nD=\n')
        self.assertEqual(env, {"A": "1", "B": "two words", "C": "x=y", "D": ""})

    def test_real_env_wins(self):
        self.assertEqual(self.load("A=file\n", A="real")["A"], "real")

    def test_missing_file_is_ignored(self):
        config._load_dotenv(Path("/nonexistent/.env"))


class TestEnvironment(unittest.TestCase):
    def reload(self, value):
        # A real env var beats trading_bot/.env, so this overrides it.
        with mock.patch.dict(os.environ, {"ENVIRONMENT": value}):
            return importlib.reload(config)

    def tearDown(self):
        importlib.reload(config)

    def test_paper_is_dry_run(self):
        self.assertTrue(self.reload("paper").DRY_RUN)
        self.assertTrue(self.reload(" Paper ").DRY_RUN)

    def test_live_trades(self):
        self.assertFalse(self.reload("live").DRY_RUN)

    def test_unknown_value_refuses_to_start(self):
        with self.assertRaises(ValueError):
            self.reload("prod")


if __name__ == "__main__":
    unittest.main()
