"""Generate a binary-bound, explicitly partial Node embedded-component inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

_NPM_COMPONENTS = ("acorn", "amaro", "undici")
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?")
_DIGEST = re.compile(r"[0-9a-f]{64}")


def build_sbom(
    versions: Mapping[str, object], *, binary_digest: str, archive_digest: str
) -> dict[str, object]:
    if len(versions) > 64 or any(
        not isinstance(key, str)
        or re.fullmatch(r"[A-Za-z0-9_]{1,64}", key) is None
        or not isinstance(value, str)
        or len(value) > 128
        or not value.isascii()
        for key, value in versions.items()
    ):
        raise ValueError("Node version observation must be a bounded ASCII string map")
    if _DIGEST.fullmatch(binary_digest) is None or _DIGEST.fullmatch(archive_digest) is None:
        raise ValueError("Node binary and archive provenance require SHA-256 digests")
    observed: dict[str, str] = {}
    for name in ("node", *_NPM_COMPONENTS):
        value = versions.get(name)
        if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
            raise ValueError(f"Node version observation lacks a valid {name} version")
        observed[name] = value
    root = f"node-runtime:sha256:{binary_digest}"
    components = [
        {
            "type": "library",
            "name": name,
            "version": observed[name],
            "purl": f"pkg:npm/{name}@{observed[name]}",
            "bom-ref": f"pkg:npm/{name}@{observed[name]}",
        }
        for name in _NPM_COMPONENTS
    ]
    unassessed = sorted(set(versions) - {"node", *_NPM_COMPONENTS})
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "node-runtime",
                "version": observed["node"],
                "bom-ref": root,
                "purl": f"pkg:generic/nodejs@{observed['node']}",
                "hashes": [{"alg": "SHA-256", "content": binary_digest}],
            },
            "properties": [
                {"name": "fdai:coverage-scope", "value": "embedded-npm-only"},
                {"name": "fdai:source-archive-sha256", "value": archive_digest},
                {"name": "fdai:unassessed-version-fields", "value": json.dumps(unassessed)},
                {
                    "name": "fdai:runtime-reported-versions",
                    "value": json.dumps(dict(versions), sort_keys=True),
                },
            ],
        },
        "components": components,
        "dependencies": [
            {"ref": root, "dependsOn": [component["bom-ref"] for component in components]},
            *[{"ref": component["bom-ref"], "dependsOn": []} for component in components],
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    with arguments.versions.open("rb") as stream:
        raw = stream.read(8193)
    if len(raw) > 8192:
        raise ValueError("Node version observation exceeds 8192 bytes")
    versions = json.loads(raw)
    if not isinstance(versions, dict):
        raise ValueError("Node version observation must be a JSON object")
    with arguments.binary.open("rb") as stream:
        binary_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = build_sbom(
        versions, binary_digest=binary_digest, archive_digest=arguments.archive_sha256
    )
    arguments.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
