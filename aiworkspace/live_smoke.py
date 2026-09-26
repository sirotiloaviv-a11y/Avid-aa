"""Opt-in live smoke test against the configured Anthropic model.

    python -m aiworkspace.live_smoke                      # dry run: shows the plan
    python -m aiworkspace.live_smoke --confirm-paid-request

Sends exactly two short requests through the same ChatService the app uses:
a Hebrew question, then a follow-up that can only be answered from the
conversation context. Nothing is retried beyond the configured bounded
retries for rejected requests. A throwaway database is used; your history is
not touched. The API key is never printed.

Exit codes: 0 passed, 1 failed, 3 BLOCKED (no key), 4 not confirmed.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

from .chat import ChatService
from .config import load_settings
from .providers import AnthropicProvider
from .store import Store

TURNS = [
    ("שלום! ענה במשפט אחד בעברית: מהי עיר הבירה של צרפת?", None),
    # Answerable only from the previous turn.
    (
        "על איזו מדינה שאלתי בהודעה הקודמת? ענה במילה אחת.",
        re.compile(r"צרפת|France", re.IGNORECASE),
    ),
]
HEBREW = re.compile(r"[֐-׿]")
# Published list prices (USD per million tokens) from the Anthropic reference
# bundled with the claude-api skill (cached 2026-06-24). Used only for the
# worst-case estimate printed before a paid run; check current pricing.
PRICES = {"claude-opus-5": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aiworkspace.live_smoke")
    parser.add_argument(
        "--confirm-paid-request",
        action="store_true",
        help="actually send the two billable requests",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2048,
        help="max_tokens per request, including thinking (default 2048)",
    )
    args = parser.parse_args(argv)
    if not 16 <= args.max_tokens <= 16_000:
        parser.error("--max-tokens must be between 16 and 16000")

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1
    if not settings.anthropic_api_key:
        print(
            "BLOCKED: ANTHROPIC_API_KEY is not configured "
            "(set it in aiworkspace/.env or the environment)."
        )
        return 3

    model = settings.anthropic_model
    print(f"Model requested : {model}")
    print("API key         : configured (value not shown)")
    print(f"Fallbacks beta  : {settings.anthropic_fallbacks}")
    print(f"Requests        : {len(TURNS)} (max_tokens={args.max_tokens} each)")
    print(
        f"Retries         : up to {settings.max_retries} per request, only if rejected"
    )
    if model in PRICES:
        _, out_price = PRICES[model]
        worst = len(TURNS) * args.max_tokens * out_price / 1e6
        print(f"Worst-case output cost ≈ ${worst:.3f} (+ a few hundred input tokens)")
    else:
        print("Cost estimate   : unknown for this model; check current pricing")

    if not args.confirm_paid_request:
        print("\nNOT RUN: re-run with --confirm-paid-request to send the requests.")
        return 4

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "smoke.sqlite3")
        provider = AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=model,
            base_url=settings.anthropic_base_url,
            fallbacks=settings.anthropic_fallbacks,
            max_retries=settings.max_retries,
        )
        chat = ChatService(
            store,
            provider,
            max_output_tokens=args.max_tokens,
            max_context_chars=settings.max_context_chars,
            request_timeout_s=settings.request_timeout_s,
        )
        cid = store.create_conversation("live smoke test").id
        ok = True
        for i, (prompt, expect) in enumerate(TURNS, 1):
            events: list[tuple[str, dict[str, object]]] = []
            chat.reply(cid, prompt, lambda e, d: events.append((e, d)), lambda: None)
            name, data = events[-1]
            msg = data.get("assistant_message") or {}
            assert isinstance(msg, dict)
            text = str(msg.get("content") or "")
            checks = {
                "completed": msg.get("status") == "complete",
                "hebrew": bool(HEBREW.search(text)),
            }
            if expect is not None:
                checks["uses context"] = bool(expect.search(text))
            print(f"\n--- turn {i} ---")
            print(f"event           : {name}")
            print(f"returned model  : {msg.get('response_model')}")
            print(
                f"status          : {msg.get('status')} (stop_reason={msg.get('stop_reason')})"
            )
            print(
                f"usage           : input={msg.get('input_tokens')} output={msg.get('output_tokens')}"
            )
            if name == "error":
                print(f"error           : {data.get('message')}")
            print(f"reply           : {text[:300]!r}")
            for label, passed in checks.items():
                print(f"check {label:<10}: {'PASS' if passed else 'FAIL'}")
            ok = ok and all(checks.values())
            if name == "error":
                break
        print("\nLIVE SMOKE TEST:", "PASSED" if ok else "FAILED")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
