"""Local development entry point. Never binds outside loopback or initializes keys on serve."""

from __future__ import annotations

import argparse
import stat
from collections.abc import Sequence
from pathlib import Path

from fdai_lifecycle_hub.signing import generate_development_key, load_signing_key
from fdai_release_hub.api import create_app
from fdai_release_hub.store import ReleaseStore


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fdai-release-hub")
    parser.add_argument("command", choices=("dev-init", "serve"))
    parser.add_argument("state", type=Path, help="private state directory outside the checkout")
    parser.add_argument("--port", type=_port, default=8091)
    parser.add_argument("--ui", type=Path, help="built UI directory; container images use /app/ui")
    args = parser.parse_args(argv)
    state = args.state.resolve()
    checkout = Path(__file__).resolve().parents[4]
    if state.is_relative_to(checkout):
        parser.error("State and development keys must be outside the checkout.")
    if state.exists():
        if not state.is_dir():
            parser.error("State path must be a directory.")
        if stat.S_IMODE(state.stat().st_mode) & 0o077:
            parser.error("State directory must not be accessible by group or other users.")
    elif args.command == "serve":
        parser.error("State directory does not exist. Run dev-init first.")
    private_key = state / "development.pem"
    if args.command == "dev-init":
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        if private_key.exists():
            parser.error("Development key already exists.")
        generate_development_key(private_key)
        print("Development key initialized. Not a production trust root.")
        return 0
    if not private_key.is_file():
        parser.error("Development key is missing. Run dev-init first.")
    key = load_signing_key(private_key, epoch=1)
    store = ReleaseStore(state / "release-hub.sqlite", key)
    import uvicorn

    ui = args.ui or Path(__file__).resolve().parents[2] / "ui" / "dist"
    uvicorn.run(
        create_app(store, static_dir=ui), host="127.0.0.1", port=args.port, proxy_headers=False
    )
    return 0
