"""Verify the mounted scanner input against the controller's retained tree digest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from fdai.delivery.code_security_prepared_source import source_tree_digest


def add_input_verification_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = sub.add_parser("verify-scanner-input", help="check scanner-mounted source bytes")
    parser.add_argument("--path", required=True)
    parser.add_argument("--tree-digest", required=True)


def verify_scanner_input(args: argparse.Namespace) -> dict[str, object]:
    if re.fullmatch(r"[0-9a-f]{64}", args.tree_digest) is None:
        raise ValueError("scanner tree digest must be SHA-256 hex")
    if source_tree_digest(Path(args.path)) != args.tree_digest:
        raise ValueError("scanner-mounted source differs from the controller handoff")
    return {"ok": True, "tree_digest": args.tree_digest}
