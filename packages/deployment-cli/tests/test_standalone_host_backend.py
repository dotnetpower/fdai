from __future__ import annotations

from pathlib import Path

import pytest

from fdai_deployment_cli import standalone_host


def test_init_recreates_the_backend_after_a_source_snapshot_is_re_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    infra = tmp_path / "source-snapshot/tree/infra"
    infra.mkdir(parents=True)
    (infra / "backend.azurerm.tf.example").write_text('terraform { backend "azurerm" {} }\n')
    observed: list[bool] = []
    monkeypatch.setattr(standalone_host, "_configure_terraform", lambda _context: None)
    monkeypatch.setattr(
        standalone_host, "_run", lambda *_a, **_k: observed.append((infra / "backend.tf").is_file())
    )
    context = {
        "infra": str(infra),
        "state_resource_group": "rg",
        "state_account": "account",
        "state_container": "state",
        "state_key": "fdai-dev.tfstate",
    }

    standalone_host._terraform_init(tmp_path, context)
    (infra / "backend.tf").unlink()
    standalone_host._terraform_init(tmp_path, context)

    assert observed == [True, True]
    assert (infra / "backend.tf").stat().st_mode & 0o777 == 0o600
