#!/usr/bin/env python3
"""Materialize the FDAI question-bank JSON and human review catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.question_bank import build_question_bank, render_review_catalog


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("eval/golden-dataset/question-bank/question-bank.source.yaml"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    source_path = (
        args.source.resolve() if args.source.is_absolute() else (repo_root / args.source).resolve()
    )
    payload = build_question_bank(repo_root=repo_root, source_path=source_path)
    output_root = source_path.parent
    _write_text(
        output_root / "question-bank.json",
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    _write_text(output_root / "review-catalog.md", render_review_catalog(payload))
    print(
        "question-bank: rendered "
        f"{payload['summary']['question_count']} logical questions "
        f"from {len(payload['source_files'])} source files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
