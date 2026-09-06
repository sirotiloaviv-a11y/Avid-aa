"""Command line entry point.

    python -m fitness_platform serve      # development server (wsgiref)
    python -m fitness_platform seed       # demo content and users
    python -m fitness_platform createadmin --email … --password …
    python -m fitness_platform routes     # print the routing table

In production the app is served by a real WSGI server against
``fitness_platform.wsgi:application``; ``serve`` is explicitly the development
runner and says so when it starts.
"""

from __future__ import annotations

import argparse
import sys
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .config import get_settings
from .db.connection import get_connection
from .domain.roles import Role


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        sys.stderr.write("%s %s\n" % (self.address_string(), format % args))


def cmd_serve(args: argparse.Namespace) -> int:
    from .wsgi import create_app

    settings = get_settings()
    app = create_app()
    get_connection()  # create the schema before the first request
    host = args.host or settings.host
    port = args.port or settings.port
    print(f"{settings.brand_name} — development server")
    print(f"  mode      : {settings.mode}")
    print(f"  database  : {settings.database_path}")
    print(f"  listening : http://{host}:{port}")
    print("  (production: gunicorn 'fitness_platform.wsgi:application')")
    with make_server(host, port, app, handler_class=_QuietHandler) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from .db.seed import seed

    counts = seed(with_demo_users=not args.no_users, verbose=True)
    print("seeded:", ", ".join(f"{key}={value}" for key, value in counts.items()))
    if not args.no_users:
        print("demo logins (password Aa123456): admin@example.com, noa@example.com, daniel@example.com")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    from .services.auth import register

    user = register(args.email, args.password, args.name, None, role=Role.ADMIN)
    print(f"admin created: {user.email} (id={user.id})")
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    from .wsgi import build_router

    for route in build_router().routes:
        methods = ",".join(sorted(route.methods - {"HEAD"}))
        print(f"{methods:<12} {route.pattern:<48} {route.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fitness_platform")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the development server")
    serve.add_argument("--host", default="")
    serve.add_argument("--port", type=int, default=0)
    serve.set_defaults(func=cmd_serve)

    seed_parser = sub.add_parser("seed", help="load demo content")
    seed_parser.add_argument("--no-users", action="store_true", help="content only")
    seed_parser.set_defaults(func=cmd_seed)

    admin = sub.add_parser("createadmin", help="create an admin account")
    admin.add_argument("--email", required=True)
    admin.add_argument("--password", required=True)
    admin.add_argument("--name", default="Admin")
    admin.set_defaults(func=cmd_create_admin)

    routes = sub.add_parser("routes", help="print the routing table")
    routes.set_defaults(func=cmd_routes)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
