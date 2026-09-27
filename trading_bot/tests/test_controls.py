from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.config import AccountConfig, RiskLimits, SessionConfig, settings_from_env
from trading_bot.risk_manager import (
    ALL_ACCOUNTS,
    ControlAction,
    ControlPoller,
    OperatorControls,
    RiskEngine,
    RiskManager,
    submit_control,
)
from trading_bot.runtime import AlreadyRunning, BotRuntime
from trading_bot.utils import ProcessLock, StateStore

REPO_ROOT = Path(__file__).resolve().parents[2]


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "state.db"
        self.kill = self.dir / "KILL"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def manager(self, store: StateStore) -> RiskManager:
        return RiskManager({
            acc: RiskEngine(AccountConfig(acc, 100_000.0), RiskLimits(), SessionConfig(), store,
                            kill_switch_path=self.kill)
            for acc in ("a1", "a2")
        })


class ProcessLockTests(Fixture):
    def test_exclusive_and_released(self) -> None:
        first, second = ProcessLock(self.dir / "bot.lock"), ProcessLock(self.dir / "bot.lock")
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()


class OperatorControlsTests(Fixture):
    def test_actions(self) -> None:
        with StateStore(self.db) as store:
            manager = self.manager(store)
            for engine in manager:
                engine.update_account(100_000, 100_000)
            controls = OperatorControls(manager, self.kill)
            self.assertTrue(controls.apply(ControlAction.HALT, "a1", "why", "t").ok)
            self.assertFalse(manager["a1"].check_new_trade().allowed)
            self.assertTrue(manager["a2"].check_new_trade().allowed)
            self.assertTrue(controls.apply(ControlAction.RESUME, "a1", "", "t").ok)
            self.assertTrue(manager["a1"].check_new_trade().allowed)
            result = controls.apply(ControlAction.PAUSE, "ghost", "", "t")
            self.assertFalse(result.ok)
            self.assertIn("unknown account", result.message)
            self.assertFalse(controls.apply(ControlAction.CLEAR_DRAWDOWN, "a1", "wrong", "t").ok)

    def test_queued_requests_are_applied_once_and_stale_ones_expire(self) -> None:
        with StateStore(self.db) as store:
            controls = OperatorControls(self.manager(store), self.kill)
            fresh = store.enqueue_control("a1", "pause", "x", "cli")
            bogus = store.enqueue_control("a1", "explode", "", "cli")
            done = controls.process_pending(store)
            self.assertEqual([r.ok for _, r in done], [True, False])
            self.assertEqual(controls.process_pending(store), [])  # claimed exactly once
            request = store.get_control(fresh)
            assert request is not None
            self.assertTrue(request.ok)
            self.assertEqual(store.get_control(bogus).ok, False)  # type: ignore[union-attr]

            old = store.enqueue_control("a2", "pause", "x", "cli")
            later = datetime.now(timezone.utc) + timedelta(minutes=5)
            (_, result), = controls.process_pending(store, now=later)
            self.assertFalse(result.ok)
            self.assertIn("expired", result.message)
            self.assertFalse(controls.manager["a2"].status().paused)
            self.assertIsNotNone(store.get_control(old))


class CliOverrideBugTests(Fixture):
    """Regression: a CLI halt while the bot runs used to be overwritten."""

    def test_submit_while_bot_runs_is_applied_by_the_bot_and_sticks(self) -> None:
        bot_store = StateStore(self.db)
        bot_lock = ProcessLock(self.dir / "bot.lock")
        self.assertTrue(bot_lock.acquire())
        bot_manager = self.manager(bot_store)
        bot_manager["a1"].update_account(100_000, 100_000)
        poller = ControlPoller(OperatorControls(bot_manager, self.kill), bot_store, interval=0.05)
        poller.start()
        try:
            with StateStore(self.db) as cli_store:
                result = submit_control(
                    cli_store, ProcessLock(self.dir / "bot.lock"),
                    lambda: self.fail("CLI must not build its own engines while the bot runs"),
                    ControlAction.HALT, "a1", "from cli", "cli:test", wait_seconds=5, poll=0.02,
                )
            self.assertTrue(result.ok, result.message)
            engine = bot_manager["a1"]
            self.assertFalse(engine.check_new_trade().allowed)
            # The bot keeps saving its in-memory state; the halt must survive it.
            engine.update_account(100_000, 99_900)
            with StateStore(self.db) as check:
                saved = check.load_account("a1")
            assert saved is not None
            self.assertTrue(saved["manual_halt"])
        finally:
            poller.stop()
            bot_store.close()
            bot_lock.release()

    def test_submit_without_bot_applies_directly(self) -> None:
        with StateStore(self.db) as store:
            result = submit_control(
                store, ProcessLock(self.dir / "bot.lock"),
                lambda: OperatorControls(self.manager(store), self.kill),
                ControlAction.EMERGENCY_HALT, ALL_ACCOUNTS, "test", "cli:test",
            )
            self.assertTrue(result.ok)
            self.assertTrue(self.kill.exists())
            saved = store.load_account("a2")
            assert saved is not None
            self.assertTrue(saved["manual_halt"])

    def test_unanswered_request_times_out(self) -> None:
        lock = ProcessLock(self.dir / "bot.lock")
        self.assertTrue(lock.acquire())  # a "bot" that never polls
        try:
            with StateStore(self.db) as store:
                result = submit_control(store, ProcessLock(self.dir / "bot.lock"),
                                        lambda: self.fail("unreachable"), ControlAction.PAUSE,
                                        "a1", "", "cli", wait_seconds=0.1, poll=0.02)
            self.assertFalse(result.ok)
            self.assertIn("queued", result.message)
        finally:
            lock.release()


class RuntimeAndCliTests(Fixture):
    def env(self) -> dict[str, str]:
        return {
            "ACCOUNTS": "a1:100000,a2:50000",
            "NEWS_CALENDAR_SOURCE": "none",
            "STATE_DB_PATH": str(self.db),
            "LOG_DIR": str(self.dir / "logs"),
        }

    def test_only_one_runtime_per_state_directory(self) -> None:
        settings = settings_from_env(self.env())
        runtime = BotRuntime(settings)
        try:
            with self.assertRaises(AlreadyRunning):
                BotRuntime(settings)
        finally:
            runtime.stop()

    def test_cli_halt_reaches_running_bot(self) -> None:
        """End to end: `python -m trading_bot halt` in a separate process."""
        settings = settings_from_env(self.env())
        runtime = BotRuntime(settings, enable_telegram=False, enable_dashboard=False)
        runtime.poller.interval = 0.1
        runtime.start()
        try:
            engine = runtime.manager["a1"]
            engine.update_account(100_000, 100_000)
            env_file = self.dir / "test.env"
            env_file.write_text("".join(f"{k}={v}\n" for k, v in self.env().items()))
            clean_env = {k: v for k, v in os.environ.items() if k not in self.env()}
            proc = subprocess.run(
                [sys.executable, "-m", "trading_bot", "--env-file", str(env_file), "halt", "a1", "cli test"],
                cwd=REPO_ROOT, env=clean_env, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("a1 halted", proc.stdout)
            self.assertFalse(engine.check_new_trade().allowed)
            engine.update_account(100_000, 100_000)  # bot saves; halt must remain
            self.assertTrue(engine.status().manual_halt)
        finally:
            runtime.stop()


if __name__ == "__main__":
    unittest.main()
