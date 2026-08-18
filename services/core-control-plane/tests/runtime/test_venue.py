"""The core control plane re-exports the shared venue contract without forking it.

The contract itself is tested in `packages/service-contracts/tests/test_venue.py`. What this
file protects is the re-export: a core binding that imported a stale or partial copy would
resolve the venue outside the one table, which is exactly what FDAI-CONST-001 needs to
prevent.
"""

from __future__ import annotations

from fdai.runtime import venue as core
from fdai_service_contracts import venue as shared


def test_the_core_module_re_exports_every_shared_name() -> None:
    assert core.__all__ == shared.__all__
    for name in shared.__all__:
        assert getattr(core, name) is getattr(shared, name), name


def test_the_core_module_declares_no_binding_of_its_own() -> None:
    """A value or table defined here would be a second source of venue truth."""

    exported = set(shared.__all__)
    local_definitions = {
        name
        for name, value in vars(core).items()
        if not name.startswith("__") and name not in exported and name != "annotations"
    }

    assert local_definitions == set()
