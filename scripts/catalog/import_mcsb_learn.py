#!/usr/bin/env python3
"""Import MCSB v2 preview controls from pinned Microsoft Learn domain pages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Final
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import yaml

_BASE_URL: Final[str] = "https://learn.microsoft.com/en-us/security/benchmark/azure/"
_OVERVIEW_URL: Final[str] = _BASE_URL + "overview"
_MAX_PAGE_BYTES: Final[int] = 20 * 1024 * 1024
_CONTROL_ID = re.compile(r"^(NS|IM|PA|DP|AM|LT|IR|PV|ES|BR|DS|AI)-[1-9][0-9]*$")

_DOMAINS: Final[tuple[tuple[str, str, int], ...]] = (
    ("NS", "network-security", 10),
    ("IM", "identity-management", 8),
    ("PA", "privileged-access", 8),
    ("DP", "data-protection", 8),
    ("AM", "asset-management", 5),
    ("LT", "logging-threat-detection", 7),
    ("IR", "incident-response", 7),
    ("PV", "posture-vulnerability-management", 7),
    ("ES", "endpoint-security", 3),
    ("BR", "backup-recovery", 4),
    ("DS", "devops-security", 7),
    ("AI", "artificial-intelligence-security", 7),
)


@dataclass(frozen=True, slots=True)
class DomainSnapshot:
    domain: str
    source_url: str
    resolved_ref: str
    content_hash: str
    controls: tuple[dict[str, str], ...]


class _LearnPageParser(HTMLParser):
    def __init__(self, domain: str) -> None:
        super().__init__(convert_charrefs=True)
        self.domain = domain
        self.commit: str | None = None
        self.controls: list[dict[str, str]] = []
        self._control_id: str | None = None
        self._heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "meta" and attributes.get("name") == "git_commit_id":
            self.commit = attributes.get("content")
        if tag != "h2":
            return
        heading_id = (attributes.get("id") or "").upper()
        if _CONTROL_ID.fullmatch(heading_id) and heading_id.startswith(f"{self.domain}-"):
            self._control_id = heading_id
            self._heading_text = []

    def handle_data(self, data: str) -> None:
        if self._control_id is not None:
            self._heading_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "h2" or self._control_id is None:
            return
        title = " ".join("".join(self._heading_text).split())
        prefix = f"{self._control_id}:"
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
        if not title:
            raise ValueError(f"MCSB control {self._control_id!r} has no title")
        self.controls.append({"id": self._control_id, "domain": self.domain, "title": title})
        self._control_id = None
        self._heading_text = []


def _fetch(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "learn.microsoft.com":
        raise ValueError(f"MCSB source is outside the Microsoft Learn allowlist: {url}")
    request = Request(  # noqa: S310 - URL validated against the HTTPS host allowlist above
        url,
        headers={"User-Agent": "fdai-catalog-import/1.0"},
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed HTTPS allowlist
        final_url = urlparse(response.geturl())
        if final_url.scheme != "https" or final_url.hostname != "learn.microsoft.com":
            raise ValueError(f"MCSB source redirected outside Microsoft Learn: {response.geturl()}")
        size = response.headers.get("Content-Length")
        if size is not None and int(size) > _MAX_PAGE_BYTES:
            raise ValueError(f"MCSB source exceeds {_MAX_PAGE_BYTES} bytes: {url}")
        payload: bytes = response.read(_MAX_PAGE_BYTES + 1)
    if len(payload) > _MAX_PAGE_BYTES:
        raise ValueError(f"MCSB source exceeds {_MAX_PAGE_BYTES} bytes: {url}")
    return payload


def parse_domain_page(domain: str, source_url: str, payload: bytes) -> DomainSnapshot:
    parser = _LearnPageParser(domain)
    parser.feed(payload.decode("utf-8"))
    if parser.commit is None or re.fullmatch(r"[0-9a-f]{40}", parser.commit) is None:
        raise ValueError(f"MCSB {domain} page has no immutable git commit")
    ids = [control["id"] for control in parser.controls]
    if len(ids) != len(set(ids)):
        raise ValueError(f"MCSB {domain} page contains duplicate control ids")
    normalized = json.dumps(
        parser.controls,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return DomainSnapshot(
        domain=domain,
        source_url=source_url,
        resolved_ref=parser.commit,
        content_hash="sha256:" + hashlib.sha256(normalized).hexdigest(),
        controls=tuple(parser.controls),
    )


def collect_snapshots() -> tuple[DomainSnapshot, ...]:
    snapshots: list[DomainSnapshot] = []
    for domain, slug, expected_count in _DOMAINS:
        source_url = f"{_BASE_URL}mcsb-v2-{slug}"
        snapshot = parse_domain_page(domain, source_url, _fetch(source_url))
        if len(snapshot.controls) != expected_count:
            raise ValueError(
                f"MCSB {domain} expected {expected_count} controls, found {len(snapshot.controls)}"
            )
        snapshots.append(snapshot)
    controls = [control for snapshot in snapshots for control in snapshot.controls]
    if len(controls) != 81:
        raise ValueError(f"MCSB v2 expected 81 controls, found {len(controls)}")
    return tuple(snapshots)


def build_manifest(
    snapshots: tuple[DomainSnapshot, ...],
    *,
    retrieved_at: str,
) -> dict[str, object]:
    controls = [control for snapshot in snapshots for control in snapshot.controls]
    revisions = "\n".join(
        f"{snapshot.domain}:{snapshot.resolved_ref}" for snapshot in snapshots
    ).encode()
    normalized = json.dumps(controls, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "1.0.0",
        "kind": "mcsb-controls",
        "benchmark": "mcsb",
        "benchmark_version": "v2-preview",
        "status": "preview",
        "control_import_status": "complete",
        "title": "Microsoft Cloud Security Benchmark v2 preview",
        "source_documents": [
            {
                "domain": snapshot.domain,
                "source_url": snapshot.source_url,
                "resolved_ref": snapshot.resolved_ref,
                "content_hash": snapshot.content_hash,
            }
            for snapshot in snapshots
        ],
        "source": {
            "source_url": _OVERVIEW_URL,
            "artifact_url": None,
            "resolved_ref": "sha256:" + hashlib.sha256(revisions).hexdigest(),
            "content_hash": "sha256:" + hashlib.sha256(normalized).hexdigest(),
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": retrieved_at,
        },
        "controls": controls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retrieved-at", required=True)
    args = parser.parse_args()
    manifest = build_manifest(collect_snapshots(), retrieved_at=args.retrieved_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "# Generated by scripts/catalog/import_mcsb_learn.py. Do not edit manually.\n"
        + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    controls = manifest["controls"]
    if not isinstance(controls, list):
        raise TypeError("generated MCSB controls MUST be a list")
    print(f"imported {len(controls)} controls into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
