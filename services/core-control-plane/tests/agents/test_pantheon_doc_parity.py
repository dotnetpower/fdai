"""Regression: pin pantheon names, layers, and ownership to the docs.

The machine-readable source of truth for the 15-agent pantheon is
``PANTHEON_SPECS`` in ``services/core-control-plane/src/fdai/agents/_framework/pantheon.py``. Two
human-readable docs paraphrase it:

- ``.github/instructions/agent-pantheon.instructions.md``
- ``docs/roadmap/agents/agent-pantheon.md``

If those docs drift from the code (a rename, an accidental omission, a
duplicated entry), this test catches it. It scans each doc for the 15
canonical names and asserts each one appears at least once.
"""

from __future__ import annotations

from pathlib import Path

from fdai.agents import PANTHEON_NAMES, PANTHEON_SPECS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DOC_PATHS = (
    _REPO_ROOT / ".github" / "instructions" / "agent-pantheon.instructions.md",
    _REPO_ROOT / "docs" / "roadmap" / "agents" / "agent-pantheon.md",
    _REPO_ROOT / "docs" / "roadmap" / "agents" / "agent-pantheon-ko.md",
)
_CATALOG_DOC_PATHS = _DOC_PATHS[1:]
_LAYER_BY_NUMBER = {"1": "domain", "2": "pipeline", "3": "governance"}


def _mentions(text: str, name: str) -> int:
    """Return the number of times ``name`` appears as a token in ``text``."""
    # Simple substring count is enough: the 15 names are unique tokens
    # that do not appear as prefixes of other English words in these
    # docs. Case-sensitive so 'thor' in inline URLs cannot mask a
    # missing capitalized 'Thor'.
    return text.count(name)


def test_all_pantheon_names_appear_in_each_doc() -> None:
    """Every canonical agent name MUST appear in every pantheon doc."""

    for doc_path in _DOC_PATHS:
        assert doc_path.is_file(), f"missing pantheon doc: {doc_path}"
        text = doc_path.read_text(encoding="utf-8")
        missing = [name for name in PANTHEON_NAMES if _mentions(text, name) == 0]
        assert not missing, (
            f"{doc_path.relative_to(_REPO_ROOT)} is missing pantheon "
            f"member(s): {sorted(missing)}. The machine-readable source is "
            "PANTHEON_SPECS in the Core service's "
            "fdai/agents/_framework/pantheon.py; the "
            f"docs paraphrase it. If a name changed in code, update the "
            f"doc to match."
        )


def test_pantheon_size_is_fifteen() -> None:
    """Sanity check the constant this test depends on."""
    assert len(PANTHEON_NAMES) == 15


def _catalog_rows(text: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    section = text.split("## 4.", 1)[1].split("### 4.1", 1)[0]
    rows: dict[str, tuple[str, tuple[str, ...]]] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] not in PANTHEON_NAMES:
            continue
        owns = tuple(item.strip().strip("`") for item in cells[3].split(",") if item.strip())
        rows[cells[0]] = (_LAYER_BY_NUMBER[cells[2]], owns)
    return rows


def test_agent_catalog_layer_and_ownership_match_specs_in_both_locales() -> None:
    expected = {spec.name: (spec.layer.value, spec.owns) for spec in PANTHEON_SPECS}

    for doc_path in _CATALOG_DOC_PATHS:
        rows = _catalog_rows(doc_path.read_text(encoding="utf-8"))
        assert rows == expected, doc_path.relative_to(_REPO_ROOT)
