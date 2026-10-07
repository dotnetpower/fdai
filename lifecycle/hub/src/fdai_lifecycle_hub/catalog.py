"""The Release catalog the Hub plans from, and how to load it.

Lifecycle I0 trusts a local development catalog directory. Verifying vendor signatures on
Releases, channel membership, and recall notices is Lifecycle I2 work.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path

from fdai_deployment_cli.runtime_release import (
    RecallRecord,
    RuntimeRelease,
    compare_release_ids,
    parse_runtime_release_manifest,
)
from pydantic import TypeAdapter

_MAX_FILE_BYTES = 1024 * 1024
_CHANNELS = TypeAdapter(dict[str, frozenset[str]])
_RECALLS = TypeAdapter(tuple[RecallRecord, ...])


@dataclass(frozen=True, slots=True)
class ReleaseCatalog:
    """Releases by SemVer id, channel membership, and recall records."""

    releases: Mapping[str, RuntimeRelease]
    channels: Mapping[str, frozenset[str]]
    recalls: tuple[RecallRecord, ...] = ()

    def __post_init__(self) -> None:
        unknown = {
            release_id
            for members in self.channels.values()
            for release_id in members
            if release_id not in self.releases
        }
        if unknown:
            raise ValueError(f"channels name unknown Releases: {sorted(unknown)}")

    def newer_than(self, channel: str, release_id: str) -> Iterator[tuple[str, RuntimeRelease]]:
        """Yield the channel's Releases newer than `release_id`, newest first."""

        newer = (
            candidate
            for candidate in self.channels.get(channel, frozenset())
            if compare_release_ids(candidate, release_id) > 0
        )
        for candidate in sorted(newer, key=cmp_to_key(compare_release_ids), reverse=True):
            yield candidate, self.releases[candidate]


def load_catalog(root: Path) -> ReleaseCatalog:
    """Load `releases/<id>.json`, `channels.json`, and an optional `recalls.json`."""

    paths = {path.stem: path for path in (root / "releases").glob("*.json")}
    # Sorting by SemVer precedence also rejects every non-canonical Release id.
    ordered = sorted(paths, key=cmp_to_key(compare_release_ids))
    recalls_path = root / "recalls.json"
    return ReleaseCatalog(
        releases={
            release_id: parse_runtime_release_manifest(_read(paths[release_id]))
            for release_id in ordered
        },
        channels=_CHANNELS.validate_json(_read(root / "channels.json")),
        recalls=_RECALLS.validate_json(_read(recalls_path)) if recalls_path.exists() else (),
    )


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"catalog entry is not a regular file: {path.name}")
    raw = path.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        raise ValueError(f"catalog entry is too large: {path.name}")
    return raw
