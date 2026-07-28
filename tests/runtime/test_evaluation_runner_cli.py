"""Evaluation runner CLI configuration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.rca import RcaTier, RootCauseHypothesis
from fdai.runtime.evaluation_runner_cli import (
    _kubernetes_config,
    _probe_rca,
    _requires_llm_binding,
    main,
)
from fdai.shared.config.models import LlmMode


def test_kubernetes_config_requires_complete_exact_scope(tmp_path: Path) -> None:
    kubeconfig = tmp_path / "config"
    kubeconfig.write_text("synthetic", encoding="utf-8")
    config = _kubernetes_config(
        {
            "FDAI_EVALUATION_KUBECONFIG": str(kubeconfig),
            "FDAI_EVALUATION_KUBERNETES_CONTEXT": "example-context",
            "FDAI_EVALUATION_KUBERNETES_CLUSTER": "example-cluster",
            "FDAI_EVALUATION_KUBERNETES_NAMESPACES": "app-a, app-b",
        }
    )
    assert config.allowed_namespaces == frozenset({"app-a", "app-b"})

    with pytest.raises(ValueError, match="are required"):
        _kubernetes_config({})


def test_cli_rejects_unknown_adapter_before_runtime_start() -> None:
    with pytest.raises(SystemExit):
        main(("check", "--adapter", "unknown"))


def test_azure_mode_matches_deserialized_string_value() -> None:
    assert _requires_llm_binding("azure") is True
    assert _requires_llm_binding(LlmMode.AZURE) is True
    assert _requires_llm_binding("disabled") is False


async def test_rca_probe_requires_grounded_live_hypothesis() -> None:
    class _Reasoner:
        async def reason(self, *, incident_summary, candidate_citations):  # type: ignore[no-untyped-def]
            assert "Synthetic readiness probe" in incident_summary
            return RootCauseHypothesis(
                tier=RcaTier.T2,
                cause="No operational diagnosis was requested.",
                confidence=1.0,
                citations=(candidate_citations[0],),
            )

    class _AbstainingReasoner:
        async def reason(self, *, incident_summary, candidate_citations):  # type: ignore[no-untyped-def]
            del incident_summary, candidate_citations
            return None

    assert await _probe_rca(_Reasoner()) is True
    assert await _probe_rca(_AbstainingReasoner()) is False
    assert await _probe_rca(None) is False
