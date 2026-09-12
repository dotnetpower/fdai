#!/usr/bin/env python3
"""Build the allowlisted Manual Studio artifact for the Console site."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

_ROOT_FILES = (
    "app.js",
    "art-of-possible.css",
    "art-of-possible.js",
    "catalog.json",
    "english-layout.css",
    "executive-deck.css",
    "executive-story.css",
    "library.html",
    "localization.js",
    "manual-content.js",
    "manual-decks.css",
    "messages.en.json",
    "messages.ko.json",
    "ontology-foundation.css",
    "ontology-foundation.js",
    "ontology-opening.css",
    "ontology-editorial.css",
    "ontology-slide-kit.js",
    "ontology-story-foundations.js",
    "ontology-story-contracts.js",
    "ontology-story-operations.js",
    "presentation-standard.css",
    "readiness-action-plan.js",
    "readiness-ai.js",
    "readiness-diagrams.css",
    "readiness-diagrams.js",
    "readiness-foundations.js",
    "readiness-maturity-model.js",
    "readiness-maturity.css",
    "readiness-maturity.js",
    "readiness-slide-kit.js",
    "readiness-visuals.css",
    "sre-incident-response.css",
    "sre-incident-response.js",
    "styles.css",
    "target-architecture-decision.js",
    "target-architecture-diagram-kit.js",
    "target-architecture-deployment.css",
    "target-architecture-deployment.js",
    "target-architecture-execution.js",
    "target-architecture-review.js",
    "target-architecture-runtime.js",
    "target-architecture-slide-kit.js",
    "target-architecture-visuals.css",
    "target-architecture.css",
    "target-architecture.js",
    "value-prioritization-action.js",
    "value-prioritization-eligibility.js",
    "value-prioritization-foundations.js",
    "value-prioritization-portfolio.css",
    "value-prioritization-portfolio.js",
    "value-prioritization-slide-kit.js",
    "value-prioritization-value.js",
    "value-prioritization-visuals.css",
    "value-prioritization.css",
    "value-prioritization.js",
)
_ENGLISH_DECK_FILES = (
    "art-of-possible.en.js",
    "executive-briefing.en.js",
    "manual-content.en.js",
    "ontology-foundation.en.js",
    "ontology-slide-kit.en.js",
    "ontology-story-contracts.en.js",
    "ontology-story-foundations.en.js",
    "ontology-story-operations.en.js",
    "readiness-action-plan.en.js",
    "readiness-ai.en.js",
    "readiness-diagrams.en.js",
    "readiness-foundations.en.js",
    "readiness-maturity-model.en.js",
    "readiness-maturity.en.js",
    "readiness-slide-kit.en.js",
    "sre-incident-response.en.js",
    "target-architecture-decision.en.js",
    "target-architecture-deployment.en.js",
    "target-architecture-diagram-kit.en.js",
    "target-architecture-execution.en.js",
    "target-architecture-review.en.js",
    "target-architecture-runtime.en.js",
    "target-architecture-slide-kit.en.js",
    "target-architecture.en.js",
    "value-prioritization-action.en.js",
    "value-prioritization-eligibility.en.js",
    "value-prioritization-foundations.en.js",
    "value-prioritization-portfolio.en.js",
    "value-prioritization-slide-kit.en.js",
    "value-prioritization-value.en.js",
    "value-prioritization.en.js",
)
_ASSET_SUFFIXES = frozenset({".jpeg", ".json", ".png"})


def build_artifact(repo_root: Path, output: Path, *, base_url: str) -> list[Path]:
    """Copy publishable files and generate crawler-readable manual share pages."""
    source_root = (repo_root / "tools" / "manual-studio").resolve()
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")

    source_files = [source_root / name for name in (*_ROOT_FILES, *_ENGLISH_DECK_FILES)]
    assets_root = source_root / "assets"
    source_files.extend(
        path
        for path in sorted(assets_root.rglob("*"))
        if path.is_file() and path.suffix.lower() in _ASSET_SUFFIXES
    )
    generator = source_root / "share-pages.mjs"
    for source in [*source_files, generator]:
        if source.is_symlink():
            raise ValueError(f"symlinks are not allowed in the static artifact: {source}")
        if not source.is_file():
            raise FileNotFoundError(f"Manual Studio source file is unavailable: {source}")

    output.mkdir(parents=True)
    copied: list[Path] = []
    for source in source_files:
        destination = output / source.relative_to(source_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied.append(destination)

    subprocess.run(
        [
            "node",
            str(generator),
            "--template",
            str(source_root / "library.html"),
            "--catalog",
            str(source_root / "catalog.json"),
            "--output",
            str(output),
            "--base-url",
            base_url,
        ],
        check=True,
    )
    catalog = json.loads((source_root / "catalog.json").read_text(encoding="utf-8"))
    copied.extend(output / f"{manual['id']}.html" for manual in catalog["manuals"])
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).parents[3])
    args = parser.parse_args()
    copied = build_artifact(args.repo_root, args.output, base_url=args.base_url)
    print(f"built Manual Studio artifact: {len(copied)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
