"""Tests for the allowlisted Manual Studio deployment artifact."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_MODULE_PATH = _ROOT / "scripts" / "deployment" / "azure" / "build_manual_studio_artifact.py"
_PUBLISHER_PATH = _ROOT / "scripts" / "deployment" / "azure" / "publish-console.sh"
_SPEC = importlib.util.spec_from_file_location("build_manual_studio_artifact", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_build_artifact_copies_only_publishable_manual_files(tmp_path: Path) -> None:
    output = tmp_path / "manuals"

    copied = _MODULE.build_artifact(_ROOT, output)

    copied_names = {path.relative_to(output).as_posix() for path in copied}
    assert {
        "app.js",
        "catalog.json",
        "executive-deck.css",
        "executive-story.css",
        "library.html",
        "manual-content.js",
        "manual-decks.css",
        "styles.css",
    } <= copied_names
    assert "assets/executive-briefing.jpeg" in copied_names
    assert "assets/provenance.json" in copied_names
    assert "server.mjs" not in copied_names
    assert "package.json" not in copied_names
    assert not any(name.startswith("test/") for name in copied_names)
    assert (output / "catalog.json").read_bytes() == (
        _ROOT / "tools" / "manual-studio" / "catalog.json"
    ).read_bytes()


def test_console_publisher_binds_and_verifies_same_origin_manuals() -> None:
    publisher = _PUBLISHER_PATH.read_text(encoding="utf-8")

    assert 'VITE_MANUAL_STUDIO_URL="https://$hostname/manuals"' in publisher
    assert "build_manual_studio_artifact.py" in publisher
    assert '"https://$hostname/manuals/$manual_file"' in publisher
    assert "sha256sum --check --status" in publisher
