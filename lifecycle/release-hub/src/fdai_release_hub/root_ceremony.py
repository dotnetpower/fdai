"""Offline root ceremony for the signed catalog roles. No network, no database, no Hub state.

The ceremony runs on an offline workstation. Each key holder generates a key and keeps the private
file; only public keys and signed records move between people. The Release Hub receives the signed
root through its installation command and never sees a root private key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fdai_deployment_cli.lifecycle_catalog_integrity import CatalogRootRecord
from fdai_deployment_cli.lifecycle_catalog_roles import (
    CatalogRootChainError,
    root_from_wire,
    root_to_wire,
    verify_root_chain,
)

from fdai_lifecycle_hub.catalog_trust import key_id_of, raw_public_key, role_verifier, sign_role
from fdai_lifecycle_hub.signing import generate_development_key, load_private_key, load_public_key

MAX_RECORD_BYTES = 64 * 1024


def _write_new(path: Path, data: bytes) -> None:
    """Create a file that must not already exist, readable by its owner only."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _read_record(path: Path) -> CatalogRootRecord:
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError(f"{path.name} is too large to be a root record")
    return root_from_wire(json.loads(path.read_bytes()))


def _encode(root: CatalogRootRecord) -> bytes:
    return json.dumps(root_to_wire(root), sort_keys=True, indent=2).encode() + b"\n"


def _public(paths: Sequence[Path]) -> dict[str, bytes]:
    return {key_id_of(key): raw_public_key(key) for key in map(load_public_key, paths)}


def _keygen(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    for index in range(1, args.count + 1):
        private = args.out_dir / f"{args.name}-{index}.pem"
        public = generate_development_key(private)
        print(json.dumps({"key_id": key_id_of(load_public_key(public)), "public": str(public)}))
    return 0


def _build(args: argparse.Namespace) -> int:
    roots, snapshots = _public(args.root_public), _public(args.snapshot_public)
    timestamps, exports = _public(args.timestamp_public), _public(args.export_public)
    signed_at = datetime.now(UTC)
    record = CatalogRootRecord(
        version=args.version,
        threshold=args.threshold,
        root_key_ids=frozenset(roots),
        snapshot_key_ids=frozenset(snapshots),
        timestamp_key_ids=frozenset(timestamps),
        export_key_ids=frozenset(exports),
        public_keys={**roots, **snapshots, **timestamps, **exports},
        signed_at=signed_at,
        expires_at=signed_at + timedelta(days=args.valid_days),
    )
    if args.threshold > len(roots):
        raise ValueError("The threshold exceeds the number of root keys.")
    _write_new(args.out, _encode(record))
    print(json.dumps({"version": record.version, "unsigned": True}))
    return 0


def _sign(args: argparse.Namespace) -> int:
    record = _read_record(args.record)
    allowed = set(record.root_key_ids)
    for previous in args.previous:
        allowed |= _read_record(previous).root_key_ids
    signatures = dict(record.signatures)
    for key_path in args.key:
        private_key = load_private_key(key_path)
        key_id = key_id_of(private_key.public_key())
        if key_id not in allowed:
            raise ValueError("A signing key is not named by this root or the previous root.")
        signatures[key_id] = sign_role(private_key, record.canonical_payload())
    signed = CatalogRootRecord(
        version=record.version,
        threshold=record.threshold,
        root_key_ids=record.root_key_ids,
        snapshot_key_ids=record.snapshot_key_ids,
        timestamp_key_ids=record.timestamp_key_ids,
        export_key_ids=record.export_key_ids,
        public_keys=record.public_keys,
        signed_at=record.signed_at,
        expires_at=record.expires_at,
        signatures=signatures,
    )
    target = args.out or args.record
    target.write_bytes(_encode(signed))
    print(json.dumps({"version": signed.version, "signatures": len(signatures)}))
    return 0


def _verify(args: argparse.Namespace) -> int:
    chain = [_read_record(path) for path in [*args.previous, args.record]]
    try:
        verified = verify_root_chain(
            chain,
            pinned_root_key_ids=chain[0].root_key_ids,
            pinned_threshold=chain[0].threshold,
            make_verifier=role_verifier,
        )
    except CatalogRootChainError as error:
        print(json.dumps({"verified": False, "reason": error.reason_code}))
        return 1
    print(json.dumps({"verified": True, "version": verified.version}))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-release-hub root")
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen", help="generate private keys with mode 0600")
    keygen.add_argument("--out-dir", type=Path, required=True)
    keygen.add_argument("--name", default="root-key")
    keygen.add_argument("--count", type=int, default=1)
    keygen.set_defaults(handler=_keygen)
    build = commands.add_parser("build", help="write an unsigned root record")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--version", type=int, required=True)
    build.add_argument("--threshold", type=int, required=True)
    build.add_argument("--root-public", type=Path, nargs="+", required=True)
    build.add_argument("--snapshot-public", type=Path, nargs="+", required=True)
    build.add_argument("--timestamp-public", type=Path, nargs="+", required=True)
    build.add_argument("--export-public", type=Path, nargs="+", required=True)
    build.add_argument("--valid-days", type=int, default=365)
    build.set_defaults(handler=_build)
    sign = commands.add_parser("sign", help="add signatures from private key files")
    sign.add_argument("--record", type=Path, required=True)
    sign.add_argument("--key", type=Path, nargs="+", required=True)
    sign.add_argument("--out", type=Path)
    sign.add_argument(
        "--previous",
        type=Path,
        nargs="*",
        default=(),
        help="previous root records whose key holders may also sign a rotation",
    )
    sign.set_defaults(handler=_sign)
    verify = commands.add_parser("verify", help="verify a root and the chain before it")
    verify.add_argument("--record", type=Path, required=True)
    verify.add_argument("--previous", type=Path, nargs="*", default=())
    verify.set_defaults(handler=_verify)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    checkout = Path(__file__).resolve().parents[4]
    for path in (getattr(args, "out_dir", None), getattr(args, "out", None)):
        if path is not None and path.resolve().is_relative_to(checkout):
            print("Ceremony output must be outside the checkout.", file=sys.stderr)
            return 2
    try:
        return int(args.handler(args))
    except (OSError, ValueError, PermissionError) as error:
        print(f"Root ceremony stopped: {error}", file=sys.stderr)
        return 1
