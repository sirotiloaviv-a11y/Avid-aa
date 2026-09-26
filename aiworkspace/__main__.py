"""Start the workspace: python -m aiworkspace"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings
from .server import App, make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aiworkspace", description=__doc__)
    parser.add_argument("--port", type=int, help="override AIWS_PORT")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    app = App(settings)
    server = make_server(app, args.port)
    host, port = settings.host, server.server_port
    shown = f"[{host}]" if ":" in host else host
    mode = (
        "DEMO MODE - replies are simulated, not live AI"
        if app.provider.simulated
        else f"live provider: {app.provider.name}, model: {app.provider.model}"
    )
    print(f"AI workspace running at http://{shown}:{port}/  ({mode})", flush=True)
    print(f"Data: {settings.db_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
