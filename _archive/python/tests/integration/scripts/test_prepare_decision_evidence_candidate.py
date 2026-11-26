"""Bounded deployment evidence candidate packaging tests."""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "deployment"
    / "azure"
    / "prepare_decision_evidence_candidate.py"
)


@pytest.fixture(scope="module")
def packager() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_decision_evidence_candidate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sources(tmp_path: Path) -> dict[str, Path]:
    names = (
        "apply-claim.json",
        "apply-receipt.json",
        "azure-preflight-evidence.json",
        "plan-metadata.json",
        "preflight-evidence.json",
    )
    sources: dict[str, Path] = {}
    for name in names:
        path = tmp_path / f"source-{name}"
        path.write_text("{}\n", encoding="utf-8")
        sources[name] = path
    return sources


def test_prepares_fixed_owner_only_candidate(packager: ModuleType, tmp_path: Path) -> None:
    output = tmp_path / "candidate"

    packager.prepare_candidate(
        sources=_sources(tmp_path),
        container_url="https://example.com/operational-history/",
        output=output,
    )

    assert {path.name for path in output.iterdir()} == {
        "apply-claim.json",
        "apply-receipt.json",
        "azure-preflight-evidence.json",
        "decision-evidence-container-url.txt",
        "plan-metadata.json",
        "preflight-evidence.json",
    }
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in output.iterdir())


def test_rejects_incomplete_candidate(packager: ModuleType, tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    del sources["apply-receipt.json"]

    with pytest.raises(packager.DecisionEvidenceCandidateError, match="incomplete"):
        packager.prepare_candidate(
            sources=sources,
            container_url="https://example.com/operational-history",
            output=tmp_path / "candidate",
        )


def test_rejects_symlinked_input(packager: ModuleType, tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    target = sources["apply-receipt.json"]
    link = tmp_path / "linked-receipt.json"
    link.symlink_to(target)
    sources["apply-receipt.json"] = link

    with pytest.raises(packager.DecisionEvidenceCandidateError, match="regular file"):
        packager.prepare_candidate(
            sources=sources,
            container_url="https://example.com/operational-history",
            output=tmp_path / "candidate",
        )


def test_rejects_oversized_input(packager: ModuleType, tmp_path: Path) -> None:
    sources = _sources(tmp_path)
    sources["apply-receipt.json"].write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(packager.DecisionEvidenceCandidateError, match="regular file"):
        packager.prepare_candidate(
            sources=sources,
            container_url="https://example.com/operational-history",
            output=tmp_path / "candidate",
        )
