"""Operator CLI: ``python -m trading_bot <command>``.

    run                         run the bot: trading loop (if TRADING_ENABLED), dashboard,
                                Telegram, controls
    status                      risk state of every account
    news                        upcoming high-impact events and blackout state
    kill [REASON]               emergency halt on ALL accounts (sets state/KILL)
    resume-all                  clear the kill switch and every manual halt
    halt ACCOUNT REASON         manual halt (flatten) on one account
    resume ACCOUNT              clear one account's manual halt
    pause ACCOUNT [REASON]      block new entries on one account, keep positions
    unpause ACCOUNT             clear a pause
    clear-drawdown ACCOUNT      clear a max-drawdown breach (after a firm reset)
    check-config                validate .env and exit
    telegram-test               send a test message to TELEGRAM_CHAT_IDS

Control commands are safe while the bot runs: they are queued and applied by
the running bot, which owns the account state (see risk_manager/controls.py).
Touching ``state/KILL`` also blocks new entries on every account at once.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from .config import ConfigError, Settings, load_settings
from .risk_manager import (
    ALL_ACCOUNTS,
    ControlAction,
    OperatorControls,
    RiskManager,
    RiskStatus,
    build_news_guard,
    submit_control,
)
from .runtime import kill_switch_path, lock_path
from .telegram_bot import TelegramApiError, TelegramClient
from .utils import ProcessLock, StateStore, StateStoreError, setup_logging


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def _print_status(status: RiskStatus) -> None:
    state = "HALTED" if status.halted else "OK"
    print(f"[{status.account_id}] {state}  day={status.trading_day}  trades={status.trades_today}")
    print(f"  balance={_fmt(status.balance)}  equity={_fmt(status.equity)}  "
          f"day P&L={_fmt(status.daily_pnl)}  realized={_fmt(status.realized_pnl_today)}")
    print(f"  daily floor={_fmt(status.daily_loss_floor)} (room {_fmt(status.daily_room)})  "
          f"DD floor={_fmt(status.drawdown_floor)} (room {_fmt(status.drawdown_room)})  "
          f"HWM={_fmt(status.high_water_mark)}  open risk={_fmt(status.open_risk)}")
    for reason in status.halt_reasons:
        print(f"  ! {reason}")
    if status.halted_until:
        print(f"  halted until {status.halted_until:%Y-%m-%d %H:%M} UTC")


def _telegram_test(settings: Settings) -> int:
    client = TelegramClient(settings.telegram.bot_token, api_base=settings.telegram.api_base)
    ok = True
    for chat_id in settings.telegram.chat_ids:
        try:
            client.send_message(chat_id, "✅ <b>Trading bot</b>: Telegram alerts are working.")
            print(f"sent to {chat_id}")
        except TelegramApiError as exc:
            print(f"FAILED for {chat_id}: {exc}", file=sys.stderr)
            ok = False
    return 0 if ok else 1


def _control(settings: Settings, store: StateStore, action: ControlAction, account: str, argument: str) -> int:
    def build() -> OperatorControls:
        manager = RiskManager.from_settings(settings, store, kill_switch_path=kill_switch_path(settings))
        return OperatorControls(manager, kill_switch_path(settings))

    operator = f"cli:{getpass.getuser()}"
    result = submit_control(store, ProcessLock(lock_path(settings)), build, action, account, argument, operator)
    if result.ok:
        print(f"OK: {result.message}")
        return 0
    print(f"FAILED: {result.message}", file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m trading_bot")
    parser.add_argument("--env-file", default=None, help="path to .env")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "news", "check-config", "telegram-test", "resume-all"):
        sub.add_parser(name)
    sub.add_parser("kill").add_argument("reason", nargs="?", default="kill switch from CLI")
    halt = sub.add_parser("halt")
    halt.add_argument("account")
    halt.add_argument("reason")
    pause = sub.add_parser("pause")
    pause.add_argument("account")
    pause.add_argument("reason", nargs="?", default="paused from CLI")
    for name in ("resume", "unpause", "clear-drawdown"):
        sub.add_parser(name).add_argument("account")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = load_settings(Path(args.env_file)) if args.env_file else load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.command == "check-config":
        print(f"OK: {len(settings.accounts)} account(s), environment={settings.environment.value}, "
              f"telegram={'on' if settings.telegram.enabled else 'off'}, "
              f"dashboard={'on' if settings.dashboard.enabled else 'off'}")
        return 0

    setup_logging(settings.log_dir, settings.log_level, console=args.command == "run")
    if args.command == "telegram-test":
        if not settings.telegram.enabled:
            print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_IDS first.", file=sys.stderr)
            return 2
        return _telegram_test(settings)
    if args.command == "run":
        from .main import run

        return run(settings)

    try:
        store = StateStore(settings.state_db_path)
    except StateStoreError as exc:
        print(exc, file=sys.stderr)
        return 1
    with store:
        if args.command == "status":
            manager = RiskManager.from_settings(settings, store, kill_switch_path=kill_switch_path(settings))
            for status in manager.statuses():
                _print_status(status)
            if kill_switch_path(settings).exists():
                print(f"KILL SWITCH ACTIVE: {kill_switch_path(settings)}")
            return 0
        if args.command == "news":
            news_guard = build_news_guard(settings.news)
            news_guard.refresh(force=True)
            check = news_guard.check()
            print("Entries allowed" if check.allowed else f"BLOCKED: {check.reason}")
            for event in news_guard.upcoming(within=timedelta(days=7)):
                print(f"  {event.time:%a %Y-%m-%d %H:%M} UTC  {event.currency}  {event.title}")
            return 0
        controls: dict[str, tuple[ControlAction, str, str]] = {
            "kill": (ControlAction.EMERGENCY_HALT, ALL_ACCOUNTS, getattr(args, "reason", "")),
            "resume-all": (ControlAction.RESUME_ALL, ALL_ACCOUNTS, ""),
            "halt": (ControlAction.HALT, getattr(args, "account", ""), getattr(args, "reason", "")),
            "resume": (ControlAction.RESUME, getattr(args, "account", ""), ""),
            "pause": (ControlAction.PAUSE, getattr(args, "account", ""), getattr(args, "reason", "")),
            "unpause": (ControlAction.UNPAUSE, getattr(args, "account", ""), ""),
        }
        if args.command == "clear-drawdown":
            answer = input(f"Type {args.account} to confirm the firm has reset this account: ")
            return _control(settings, store, ControlAction.CLEAR_DRAWDOWN, args.account, answer.strip())
        action, account, argument = controls[args.command]
        return _control(settings, store, action, account, argument)


if __name__ == "__main__":
    sys.exit(main())
