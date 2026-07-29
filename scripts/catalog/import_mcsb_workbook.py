#!/usr/bin/env python3
"""Import a Microsoft Cloud Security Benchmark workbook as versioned controls."""

from __future__ import annotations

import argparse
import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"m": _MAIN_NS, "r": _REL_NS, "p": _PACKAGE_REL_NS}
_CONTROL_ID = re.compile(r"^(NS|IM|PA|DP|AM|LT|IR|PV|ES|BR|DS|GS|AI)-[1-9][0-9]*$")
_MAX_XML_BYTES = 16 * 1024 * 1024


def _xml_root(archive: zipfile.ZipFile, name: str) -> ET.Element:
    info = archive.getinfo(name)
    if info.file_size > _MAX_XML_BYTES:
        raise ValueError(f"workbook XML entry {name!r} exceeds {_MAX_XML_BYTES} bytes")
    payload = archive.read(info)
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError(f"workbook XML entry {name!r} contains a forbidden declaration")
    return ET.fromstring(payload)  # noqa: S314 - bounded input with DTD/entity rejection


def _cell_column(reference: str) -> str:
    return "".join(character for character in reference if character.isalpha())


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        root = _xml_root(archive, "xl/sharedStrings.xml")
    except KeyError:
        return ()
    return tuple(
        "".join(node.text or "" for node in item.iterfind(".//m:t", _NS))
        for item in root.findall("m:si", _NS)
    )


def _sheet_paths(archive: zipfile.ZipFile) -> Iterator[tuple[str, str]]:
    workbook = _xml_root(archive, "xl/workbook.xml")
    relationships = _xml_root(archive, "xl/_rels/workbook.xml.rels")
    targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall("p:Relationship", _NS)
    }
    sheets = workbook.find("m:sheets", _NS)
    if sheets is None:
        raise ValueError("workbook has no sheets")
    for sheet in sheets:
        relationship_id = sheet.attrib[f"{{{_REL_NS}}}id"]
        target = PurePosixPath(targets[relationship_id])
        if target.is_absolute():
            path = target.as_posix().lstrip("/")
        else:
            path = (PurePosixPath("xl") / target).as_posix()
        yield sheet.attrib["name"], path


def _cell_value(cell: ET.Element, shared: tuple[str, ...]) -> str:
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iterfind(".//m:t", _NS)).strip()
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return shared[int(value.text)].strip()
    return value.text.strip()


def extract_controls(workbook_path: Path) -> list[dict[str, str]]:
    """Extract unique control IDs, domains, and recommendation titles."""

    controls: list[dict[str, str]] = []
    seen: set[str] = set()
    with zipfile.ZipFile(workbook_path) as archive:
        shared = _shared_strings(archive)
        for sheet_name, sheet_path in _sheet_paths(archive):
            if sheet_name.casefold() == "readme":
                continue
            worksheet = _xml_root(archive, sheet_path)
            rows = worksheet.findall(".//m:sheetData/m:row", _NS)
            for row in rows[1:]:
                values = {
                    _cell_column(cell.attrib["r"]): _cell_value(cell, shared)
                    for cell in row.findall("m:c", _NS)
                }
                control_id = values.get("A", "")
                if not control_id:
                    continue
                match = _CONTROL_ID.fullmatch(control_id)
                if match is None:
                    raise ValueError(f"invalid MCSB control id {control_id!r} in {sheet_name}")
                if control_id in seen:
                    raise ValueError(f"duplicate MCSB control id {control_id!r}")
                title = values.get("G", "")
                if not title:
                    raise ValueError(f"MCSB control {control_id!r} has no recommendation title")
                seen.add(control_id)
                controls.append({"id": control_id, "domain": match.group(1), "title": title})
    return controls


def build_manifest(
    workbook_path: Path,
    *,
    benchmark_version: str,
    title: str,
    source_url: str,
    artifact_url: str,
    resolved_ref: str,
    retrieved_at: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    return {
        "schema_version": "1.0.0",
        "kind": "mcsb-controls",
        "benchmark": "mcsb",
        "benchmark_version": benchmark_version,
        "status": "stable",
        "control_import_status": "complete",
        "title": title,
        "source": {
            "source_url": source_url,
            "artifact_url": artifact_url,
            "resolved_ref": resolved_ref,
            "content_hash": f"sha256:{digest}",
            "license": "CC-BY-4.0",
            "redistribution": "embeddable",
            "retrieved_at": retrieved_at,
        },
        "controls": extract_controls(workbook_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark-version", default="v1")
    parser.add_argument("--title", default="Microsoft Cloud Security Benchmark v1")
    parser.add_argument(
        "--source-url",
        default="https://learn.microsoft.com/security/benchmark/azure/overview-mcsb-v1",
    )
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--resolved-ref", required=True)
    parser.add_argument("--retrieved-at", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = build_manifest(
        args.input,
        benchmark_version=args.benchmark_version,
        title=args.title,
        source_url=args.source_url,
        artifact_url=args.artifact_url,
        resolved_ref=args.resolved_ref,
        retrieved_at=args.retrieved_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "# Generated by scripts/catalog/import_mcsb_workbook.py. Do not edit manually.\n"
        + yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )
    print(f"imported {len(manifest['controls'])} controls into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
