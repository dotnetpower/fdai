"""Regenerate or check the tracked reference behavior seed artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from fdai.delivery.behavior_knowledge.behavior_seed_generation import (
    MANIFEST,
    check_manifest,
    serialized_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    if args.check:
        result = check_manifest(root)
        print(f"Verified {len(result['seeds'])} reference behavior seeds")
    else:
        (root / MANIFEST).write_text(serialized_manifest(root), encoding="utf-8")
        print("Regenerated reference behavior seed artifact")


if __name__ == "__main__":
    main()
