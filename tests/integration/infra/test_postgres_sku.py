from __future__ import annotations

import re
from pathlib import Path

from fdai_deployment_cli.runtime_profile import DATABASE_SKUS

_ROOT = Path(__file__).resolve().parents[3]


def _block(source: str, header: str) -> str:
    start = source.index(header)
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated block: {header}")


def test_state_store_receives_the_selected_postgres_size() -> None:
    main = (_ROOT / "infra" / "main.tf").read_text(encoding="utf-8")

    block = _block(main, 'module "state_store" {')

    assert re.search(r"^\s*sku_name\s*=\s*var\.postgres_sku_name\s*$", block, re.MULTILINE)


def test_root_allowlist_matches_the_deployment_profile_allowlist() -> None:
    variables = (_ROOT / "infra" / "variables.tf").read_text(encoding="utf-8")

    block = _block(variables, 'variable "postgres_sku_name" {')
    allowed = tuple(re.findall(r'^\s*"([A-Za-z0-9_]+)",\s*$', block, re.MULTILINE))

    assert allowed == DATABASE_SKUS
    assert re.search(r'^\s*default\s*=\s*"B_Standard_B1ms"\s*$', block, re.MULTILINE)
