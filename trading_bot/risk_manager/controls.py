"""Operator controls, shared by the dashboard, Telegram and the CLI.

There is exactly one writer of account state: the process that owns the
risk engines (the running bot). In-process callers (dashboard, Telegram)
call :class:`OperatorControls` directly. Other processes (the CLI) must not
write account state while the bot runs, or the bot overwrites it from memory
on its next save. They call :func:`submit_control` instead, which queues a
request in SQLite that the bot's :class:`ControlPoller` applies within about
a second. When no bot is running, the CLI takes the process lock and applies
the action itself.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable

from ..utils.logger import get_logger
from ..utils.process_lock import ProcessLock
from ..utils.state_store import ControlRequest, StateStore, StateStoreError
from ..utils.time_utils import utc_now
from .risk_engine import RiskManager

log = get_logger(__name__)

ALL_ACCOUNTS = "*"
# A queued request older than this is expired, not applied: a "resume" typed
# while the bot was down must not take effect hours later.
MAX_REQUEST_AGE = timedelta(minutes=2)


class ControlAction(str, Enum):
    EMERGENCY_HALT = "emergency_halt"  # KILL file + manual halt (flatten) on all
    RESUME_ALL = "resume_all"          # remove KILL + clear manual halts
    HALT = "halt"                      # manual halt (flatten) on one account
    RESUME = "resume"                  # clear one account's manual halt
    PAUSE = "pause"                    # block new entries on one account
    UNPAUSE = "unpause"
    CLEAR_DRAWDOWN = "clear_drawdown"


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    message: str


class OperatorControls:
    def __init__(self, manager: RiskManager, kill_switch_path: Path) -> None:
        self.manager = manager
        self.kill_switch_path = kill_switch_path
        self._lock = threading.Lock()

    @property
    def kill_switch_active(self) -> bool:
        return self.kill_switch_path.exists()

    def apply(self, action: ControlAction, account_id: str, argument: str, operator: str) -> ControlResult:
        """Run one action. Never raises; failures come back as ``ok=False``."""
        with self._lock:
            try:
                return self._apply(action, account_id, argument.strip(), operator)
            except Exception as exc:
                log.exception("Control %s on %s failed", action.value, account_id)
                return ControlResult(False, f"{action.value} failed: {exc}")

    def _apply(self, action: ControlAction, account_id: str, argument: str, operator: str) -> ControlResult:
        if action is ControlAction.EMERGENCY_HALT:
            return self._emergency_halt(argument or "emergency halt", operator)
        if action is ControlAction.RESUME_ALL:
            return self._resume_all(operator)
        try:
            engine = self.manager[account_id]
        except KeyError:
            return ControlResult(False, f"unknown account {account_id!r}")
        by = f"{argument or action.value} ({operator})"
        if action is ControlAction.HALT:
            engine.halt(by)
            return ControlResult(True, f"{account_id} halted")
        if action is ControlAction.RESUME:
            engine.resume_manual_halt()
            return ControlResult(True, f"{account_id} manual halt cleared")
        if action is ControlAction.PAUSE:
            engine.pause(by)
            return ControlResult(True, f"{account_id} paused")
        if action is ControlAction.UNPAUSE:
            engine.unpause()
            return ControlResult(True, f"{account_id} resumed")
        if action is ControlAction.CLEAR_DRAWDOWN:
            engine.clear_max_drawdown_breach(argument)
            return ControlResult(True, f"{account_id} max drawdown breach cleared")
        return ControlResult(False, f"unsupported action {action.value}")

    def _emergency_halt(self, reason: str, operator: str) -> ControlResult:
        # The KILL file comes first: it blocks every process sharing this
        # state directory even if an engine call below fails.
        self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.write_text(f"{utc_now().isoformat()} {operator}: {reason}\n", encoding="utf-8")
        log.critical("EMERGENCY HALT by %s: %s", operator, reason)
        failed: list[str] = []
        for engine in self.manager:
            try:
                engine.halt(f"{reason} ({operator})")
            except Exception:
                log.exception("[%s] Manual halt failed", engine.account.account_id)
                failed.append(engine.account.account_id)
        if failed:
            return ControlResult(False, f"KILL file set; engine halt failed for {', '.join(failed)}")
        return ControlResult(True, f"all {len(self.manager)} accounts halted; kill switch set")

    def _resume_all(self, operator: str) -> ControlResult:
        self.kill_switch_path.unlink(missing_ok=True)
        for engine in self.manager:
            engine.resume_manual_halt()
        log.warning("Kill switch and manual halts cleared by %s", operator)
        still = [s.account_id for s in self.manager.statuses() if s.halted]
        if still:
            return ControlResult(True, f"manual halt cleared; still halted: {', '.join(still)}")
        return ControlResult(True, "manual halt cleared; all accounts may trade")

    # ------------------------------------------------------------ requests
    def process_pending(
        self, store: StateStore, *, now: datetime | None = None
    ) -> list[tuple[ControlRequest, ControlResult]]:
        """Apply control requests queued by other processes."""
        now = now or utc_now()
        done: list[tuple[ControlRequest, ControlResult]] = []
        for request in store.claim_controls():
            result = self._apply_request(request, now)
            try:
                store.complete_control(request.id, result.ok, result.message)
            except StateStoreError as exc:
                log.error("Could not record result of control request %d: %s", request.id, exc)
            done.append((request, result))
        return done

    def _apply_request(self, request: ControlRequest, now: datetime) -> ControlResult:
        try:
            action = ControlAction(request.action)
        except ValueError:
            return ControlResult(False, f"unknown action {request.action!r}")
        if now - request.created_at > MAX_REQUEST_AGE:
            log.warning("Expired queued %s on %s from %s (created %s)", action.value,
                        request.account_id, request.operator, request.created_at)
            return ControlResult(False, "expired before the bot could apply it")
        log.info("Applying queued %s on %s from %s", action.value, request.account_id, request.operator)
        return self.apply(action, request.account_id, request.argument, request.operator)


class ControlPoller:
    """Background thread in the bot process that applies queued requests."""

    def __init__(self, controls: OperatorControls, store: StateStore, *, interval: float = 1.0) -> None:
        self.controls = controls
        self.store = store
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="control-poller", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.controls.process_pending(self.store)
            except Exception:
                log.exception("Control poll failed")


def submit_control(
    store: StateStore,
    lock: ProcessLock,
    build_controls: Callable[[], OperatorControls],
    action: ControlAction,
    account_id: str,
    argument: str,
    operator: str,
    *,
    wait_seconds: float = 15.0,
    poll: float = 0.25,
) -> ControlResult:
    """Apply ``action`` safely from a process that is not the bot.

    If the bot is not running (the process lock is free), take the lock and
    apply the action directly. Otherwise queue it and wait for the bot.
    """
    if lock.acquire():
        try:
            return build_controls().apply(action, account_id, argument, operator)
        finally:
            lock.release()
    request_id = store.enqueue_control(account_id, action.value, argument, operator)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        request = store.get_control(request_id)
        if request is not None and request.completed_at is not None:
            return ControlResult(bool(request.ok), request.result or "")
        time.sleep(poll)
    return ControlResult(False, f"queued as request #{request_id}, but the running bot has not "
                                "applied it yet; check `status` and the bot log")
