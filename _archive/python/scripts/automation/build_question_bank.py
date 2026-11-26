#!/usr/bin/env python3
"""Materialize the FDAI question-bank JSON and human review catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.question_bank import (
    build_question_bank,
    compress_question_bank_bundle,
    render_review_catalog,
)


def _render_question_bank_json(payload: dict[str, Any]) -> str:
    head = {key: value for key, value in payload.items() if key != "questions"}
    head_json = json.dumps(head, ensure_ascii=False, indent=2)
    rows = [
        "  " + json.dumps(question, ensure_ascii=False, separators=(",", ":"))
        for question in payload["questions"]
    ]
    return head_json[:-2] + ',\n  "questions": [\n' + ",\n".join(rows) + "\n  ]\n}\n"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("eval/golden-dataset/question-bank/question-bank.source.yaml"),
    )
    parser.add_argument(
        "--zstd-output",
        type=Path,
        default=None,
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    source_path = (
        args.source.resolve() if args.source.is_absolute() else (repo_root / args.source).resolve()
    )
    payload = build_question_bank(repo_root=repo_root, source_path=source_path)
    output_root = source_path.parent
    artifacts = {
        output_root / "question-bank.json": _render_question_bank_json(payload),
        output_root / "review-catalog.md": render_review_catalog(payload),
    }
    zstd_path = (
        (
            args.zstd_output.resolve()
            if args.zstd_output.is_absolute()
            else (repo_root / args.zstd_output).resolve()
        )
        if args.zstd_output is not None
        else None
    )
    zstd_bytes = compress_question_bank_bundle(payload) if zstd_path is not None else None
    if args.check:
        stale = [
            path
            for path, expected in artifacts.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        if zstd_path is not None and zstd_bytes is not None:
            if not zstd_path.is_file() or zstd_path.read_bytes() != zstd_bytes:
                stale.append(zstd_path)
        for path in stale:
            print(f"question-bank: stale generated artifact: {path.name}", file=sys.stderr)
        if stale:
            return 1
        print("question-bank: OK (generated JSON and review catalog match all sources)")
        return 0
    for path, content in artifacts.items():
        _write_text(path, content)
    if zstd_path is not None and zstd_bytes is not None:
        _write_bytes(zstd_path, zstd_bytes)
    print(
        "question-bank: rendered "
        f"{payload['summary']['question_count']} logical questions "
        f"from {len(payload['source_files'])} source files"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
