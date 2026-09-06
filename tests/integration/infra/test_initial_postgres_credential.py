from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_selected_initial_postgres_credential_reaches_state_store_without_output() -> None:
    main = (ROOT / "infra/main.tf").read_text(encoding="utf-8")
    outputs = (ROOT / "infra/outputs.tf").read_text(encoding="utf-8")

    assert "administrator_password = local.postgres_admin_password" in main
    assert 'output "postgres_admin_password"' not in outputs
