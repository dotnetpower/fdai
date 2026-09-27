"""Container entry point for isolated Azure inventory network certification."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from .inventory_network_certification import (
    run_inventory_network_campaign,
    verify_inventory_network_campaign,
)


async def _run(command: str) -> dict[str, object]:
    if command == "run":
        return await run_inventory_network_campaign(os.environ)
    return await verify_inventory_network_campaign(os.environ)


def main() -> None:
    parser = argparse.ArgumentParser(prog="fdai-inventory-network-certification")
    parser.add_argument("command", choices=("run", "verify"))
    arguments = parser.parse_args()
    result = asyncio.run(_run(arguments.command))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
