"""The installation anchor that keeps a Trial window from renewing.

Terraform state, not the deployment run, owns the installation identity and its
first-apply time. These pins fail if a change lets a rerun or an upgrade produce a
new identity or a later activation time.
"""

from __future__ import annotations

import re
from pathlib import Path

_INFRA = Path(__file__).resolve().parents[3] / "infra"


def _block(source: str, header: str) -> str:
    start = source.index(header)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start : index + 1]
    raise AssertionError(f"unterminated block: {header}")


def test_the_installation_anchor_is_fixed_at_first_apply() -> None:
    anchor = _block(
        (_INFRA / "main.tf").read_text(encoding="utf-8"),
        'resource "terraform_data" "installation"',
    )

    assert "input = timestamp()" in anchor
    assert re.search(r"ignore_changes\s*=\s*\[input\]", anchor)


def test_the_installation_binding_and_anchor_time_are_outputs() -> None:
    main = (_INFRA / "main.tf").read_text(encoding="utf-8")
    outputs = (_INFRA / "outputs.tf").read_text(encoding="utf-8")

    assert (
        'installation_binding    = sha256("fdai-installation:${terraform_data.installation.id}")'
        in main
    )
    assert "installation_created_at = terraform_data.installation.output" in main
    assert "value       = local.installation_binding" in _block(
        outputs, 'output "installation_binding"'
    )
    assert "value       = local.installation_created_at" in _block(
        outputs, 'output "installation_created_at"'
    )
