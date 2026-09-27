"""Operator CLI: ``python -m trading_bot <command>``.

    status                      risk state of every account
    news                        upcoming high-impact events and blackout state
    halt ACCOUNT REASON         kill switch for one account (persists)
    resume ACCOUNT              clear a manual halt
    clear-drawdown ACCOUNT      clear a max-drawdown breach (after a firm reset)
    check-config                validate .env and exit

Touching ``state/KILL`` blocks new entries on every account without a restart.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from .config import ConfigError, Settings, load_settings
from .risk_manager import RiskManager, RiskStatus, build_news_guard
from .utils import StateStore, StateStoreError, setup_logging


def _kill_switch(settings: Settings) -> Path:
    return settings.state_db_path.parent / "KILL"


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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m trading_bot")
    parser.add_argument("--env-file", type=Path, default=None, help="path to .env")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("news")
    sub.add_parser("check-config")
    halt = sub.add_parser("halt")
    halt.add_argument("account")
    halt.add_argument("reason")
    sub.add_parser("resume").add_argument("account")
    sub.add_parser("clear-drawdown").add_argument("account")
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.env_file) if args.env_file else load_settings()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.command == "check-config":
        print(f"OK: {len(settings.accounts)} account(s), environment={settings.environment.value}")
        return 0

    setup_logging(settings.log_dir, settings.log_level, console=False)
    try:
        store = StateStore(settings.state_db_path)
    except StateStoreError as exc:
        print(exc, file=sys.stderr)
        return 1

    with store:
        news_guard = build_news_guard(settings.news)
        manager = RiskManager.from_settings(
            settings, store, news_guard=news_guard, kill_switch_path=_kill_switch(settings)
        )
        if args.command == "status":
            for status in manager.statuses():
                _print_status(status)
            if _kill_switch(settings).exists():
                print(f"KILL SWITCH ACTIVE: {_kill_switch(settings)}")
        elif args.command == "news":
            news_guard.refresh(force=True)
            check = news_guard.check()
            print("Entries allowed" if check.allowed else f"BLOCKED: {check.reason}")
            for event in news_guard.upcoming(within=timedelta(days=7)):
                print(f"  {event.time:%a %Y-%m-%d %H:%M} UTC  {event.currency}  {event.title}")
        else:
            try:
                engine = manager[args.account]
            except KeyError:
                print(f"unknown account {args.account!r}", file=sys.stderr)
                return 2
            if args.command == "halt":
                engine.halt(args.reason)
            elif args.command == "resume":
                engine.resume_manual_halt()
            elif args.command == "clear-drawdown":
                answer = input(f"Type {args.account} to confirm the firm has reset this account: ")
                engine.clear_max_drawdown_breach(answer.strip())
            _print_status(engine.status())
    return 0


if __name__ == "__main__":
    sys.exit(main())
