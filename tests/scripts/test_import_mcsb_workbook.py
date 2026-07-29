"""MCSB workbook importer tests using a minimal synthetic XLSX archive."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "catalog" / "import_mcsb_workbook.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("import_mcsb_workbook", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workbook(path: Path, *, duplicate: bool = False) -> None:
    second_id = "NS-1" if duplicate else "IM-1"
    shared = [
        "ID",
        "Recommendation",
        "NS-1",
        "Segment networks",
        second_id,
        "Centralize identity",
    ]
    strings = "".join(f"<si><t>{value}</t></si>" for value in shared)
    rows = "".join(
        (
            '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="G1" t="s"><v>1</v></c></row>',
            '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="G2" t="s"><v>3</v></c></row>',
            '<row r="3"><c r="A3" t="s"><v>4</v></c><c r="G3" t="s"><v>5</v></c></row>',
        )
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{strings}</sst>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Controls" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{rows}</sheetData></worksheet>",
        )


def test_extracts_control_identity_and_title(tmp_path: Path) -> None:
    workbook = tmp_path / "mcsb.xlsx"
    _workbook(workbook)

    controls = _module().extract_controls(workbook)

    assert controls == [
        {"id": "NS-1", "domain": "NS", "title": "Segment networks"},
        {"id": "IM-1", "domain": "IM", "title": "Centralize identity"},
    ]


def test_rejects_duplicate_control_ids(tmp_path: Path) -> None:
    workbook = tmp_path / "mcsb.xlsx"
    _workbook(workbook, duplicate=True)

    with pytest.raises(ValueError, match="duplicate MCSB control id"):
        _module().extract_controls(workbook)
