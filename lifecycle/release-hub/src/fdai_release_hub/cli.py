"""Local development entry point. Never binds outside loopback or initializes keys on serve."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from fdai_lifecycle_hub.signing import generate_development_key, load_signing_key
from fdai_release_hub.api import create_app
from fdai_release_hub.store import ReleaseStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fdai-release-hub")
    parser.add_argument("command", choices=("dev-init", "serve"))
    parser.add_argument("state", type=Path, help="private state directory outside the checkout")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args(argv)
    state = args.state.resolve()
    checkout = Path(__file__).resolve().parents[4]
    if state.is_relative_to(checkout):
        parser.error("State and development keys must be outside the checkout.")
    if args.command == "dev-init":
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        generate_development_key(state / "development.pem")
        print("Development key initialized. Not a production trust root.")
        return 0
    key = load_signing_key(state / "development.pem", epoch=1)
    store = ReleaseStore(state / "release-hub.sqlite", key)
    import uvicorn

    ui = Path(__file__).resolve().parents[2] / "ui" / "dist"
    uvicorn.run(
        create_app(store, static_dir=ui), host="127.0.0.1", port=args.port, proxy_headers=False
    )
    return 0
