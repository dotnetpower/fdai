#!/usr/bin/env python3
"""Give every tracked Python file a modification time derived from its content.

CPython and pytest validate cached bytecode by the source's modification time and size. A fresh
CI checkout stamps every file with the checkout time, so no cached bytecode from an earlier run
is ever valid and every job recompiles (and, for test modules, re-runs pytest's assertion
rewriting) the whole suite: about 55 s of a 70 s cold collection.

The mtime here is the first 32 bits of the file's Git blob id. An unchanged file always gets the
same stamp, so bytecode restored from a cache stays valid; any content change changes the blob id
and therefore the stamp, so stale bytecode is rejected, with the size check as a second guard.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_STAMP_BITS = 32


def stamps(index_listing: str) -> dict[str, int]:
    """Map each regular file in ``git ls-files -s`` output to its content-derived mtime."""
    result: dict[str, int] = {}
    for line in index_listing.splitlines():
        metadata, _, path = line.partition("\t")
        fields = metadata.split()
        if len(fields) != 3 or fields[0] not in {"100644", "100755"}:
            continue
        # Stay inside the 32-bit range pyc headers store, and above zero.
        result[path] = (int(fields[1][: _STAMP_BITS // 4], 16) & 0x7FFFFFFF) or 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    listing = subprocess.run(  # noqa: S603 - fixed Git plumbing command
        ["git", "ls-files", "-s", "--", "*.py"],
        cwd=arguments.root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    stamped = 0
    for relative, mtime in stamps(listing).items():
        path = arguments.root / relative
        if path.is_file() and not path.is_symlink():
            os.utime(path, (mtime, mtime))
            stamped += 1
    print(f"stamped {stamped} Python files from their content")
    return 0


if __name__ == "__main__":
    sys.exit(main())
