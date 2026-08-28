from __future__ import annotations

from pathlib import Path

from scripts.deployment.service.select_changed_images import IMAGE_TARGETS

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "extensions/cost-governance/docker/Dockerfile"


def test_distribution_profile_installs_core_and_cost_governance_wheels() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")

    assert "uv build --wheel --package fdai-core-control-plane" in content
    assert "uv build --wheel --package fdai-cost-governance" in content
    assert "/wheels/fdai_core_control_plane-*.whl" in content
    assert "/wheels/fdai_cost_governance-*.whl" in content
    assert "from fdai_cost_governance import load_package_resources" in content
    assert 'ENTRYPOINT ["fdai-core-control-plane"]' in content
    assert "candidate_state'] == 'inert'" in content


def test_distribution_profile_is_not_a_sixth_runtime_service() -> None:
    target = next(item for item in IMAGE_TARGETS if item.target == "cost-governance")

    assert target.service == "core-control-plane"
    assert target.image == "fdai-cost-governance"
    assert len({item.service for item in IMAGE_TARGETS}) == 5
