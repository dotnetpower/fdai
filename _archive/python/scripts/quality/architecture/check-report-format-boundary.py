#!/usr/bin/env python3
"""Keep report format additions behind FormatEncoder and composition registration.

Every module under `core/reporting/formats/` must contribute exactly one
`FormatEncoder` implementation, expose it from the package, and either register
it in `defaults.py` or be documented as an explicit opt-in encoder. Format
modules may not reach outside `core/` for a delivery dependency: an encoder that
needs one belongs in a delivery or service module bound at the composition root
(`docs/roadmap/interfaces/reporting-subsystem.md`).

Exit codes: 0 on clean, 1 on any violation.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

FORMATS_ROOT = Path("services/core-control-plane/src/fdai/core/reporting/formats")
PACKAGE_INIT = FORMATS_ROOT / "__init__.py"
DEFAULTS_MODULE = FORMATS_ROOT / "defaults.py"
INFRASTRUCTURE_MODULES = frozenset({"__init__.py", "defaults.py"})

# Encoders upstream ships but deliberately does not register by default. A new
# encoder must either be registered in `defaults.py` or added here in a reviewed
# change; prose in a docstring is not a registration.
OPT_IN_ENCODERS = frozenset({"PrometheusFormatEncoder"})

ALLOWED_IMPORT_PREFIXES = (
    "fdai.core.reporting",
    "fdai.shared.contracts",
)
STANDARD_LIBRARY_ROOTS = frozenset(sys.stdlib_module_names)


def _module_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def _has_relative_import(tree: ast.AST) -> bool:
    """A relative import can reach outside the package without naming it."""
    return any(isinstance(node, ast.ImportFrom) and node.level > 0 for node in ast.walk(tree))


def _imported_names(source: str) -> set[str]:
    """Return the names a module actually imports, ignoring prose mentions."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _exported_names(source: str) -> set[str]:
    """Return the names listed in a module's ``__all__``."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
        if "__all__" not in targets or not isinstance(node.value, ast.List | ast.Tuple):
            continue
        return {
            element.value
            for element in node.value.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
    return set()


def _encoder_class_names(tree: ast.AST) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name.endswith("FormatEncoder")
    ]


def _is_allowed_import(name: str) -> bool:
    if name.split(".", 1)[0] in STANDARD_LIBRARY_ROOTS:
        return True
    return any(
        name == prefix or name.startswith(f"{prefix}.") for prefix in ALLOWED_IMPORT_PREFIXES
    )


def validate(root: Path) -> list[str]:
    """Return every boundary violation found under the formats package."""
    formats_root = root / FORMATS_ROOT
    if not formats_root.is_dir():
        return [f"{FORMATS_ROOT}: directory is missing"]

    errors: list[str] = []
    package_source = (root / PACKAGE_INIT).read_text(encoding="utf-8")
    defaults_source = (root / DEFAULTS_MODULE).read_text(encoding="utf-8")
    exported = _imported_names(package_source) | _exported_names(package_source)
    registered = _imported_names(defaults_source)

    # The package is a flat set of encoder modules. A subdirectory would carry
    # encoders the per-file checks below never see.
    for child in sorted(formats_root.iterdir()):
        if child.is_dir() and child.name != "__pycache__":
            errors.append(
                f"{child.relative_to(root).as_posix()}: the formats package is flat; "
                "an encoder MUST be a module directly under it"
            )

    # Infrastructure modules collect encoders; they never define one, because a
    # class defined there would skip every check below.
    for name in sorted(INFRASTRUCTURE_MODULES):
        path = formats_root / name
        if not path.exists():
            continue
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        defined = _encoder_class_names(tree)
        if defined:
            errors.append(f"{relative}: MUST NOT define an encoder class, found {defined}")
        errors.extend(_import_errors(tree, relative))

    for path in sorted(formats_root.glob("*.py")):
        if path.name in INFRASTRUCTURE_MODULES:
            continue
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)

        encoders = _encoder_class_names(tree)
        if len(encoders) != 1:
            errors.append(
                f"{relative}: expected exactly one *FormatEncoder class, found {len(encoders)}"
            )
            continue
        encoder = encoders[0]

        if encoder not in exported:
            errors.append(f"{relative}: {encoder} is not exported from {PACKAGE_INIT.as_posix()}")
        if encoder not in registered and encoder not in OPT_IN_ENCODERS:
            errors.append(
                f"{relative}: {encoder} is neither registered in "
                f"{DEFAULTS_MODULE.as_posix()} nor listed as a reviewed opt-in encoder"
            )

        errors.extend(_import_errors(tree, relative))
    return errors


def _import_errors(tree: ast.AST, relative: str) -> list[str]:
    errors: list[str] = []
    if _has_relative_import(tree):
        errors.append(
            f"{relative}: relative imports are not allowed; a format module MUST name "
            "every dependency so this gate can see it"
        )
    for name in sorted(_module_names(tree)):
        if not _is_allowed_import(name):
            errors.append(
                f"{relative}: forbidden import {name!r}; an encoder needing a delivery "
                "dependency belongs outside core/ and is registered at the composition root"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="repository root")
    arguments = parser.parse_args()

    errors = validate(Path(arguments.root).resolve())
    for error in errors:
        print(f"check-report-format-boundary: {error}")
    if errors:
        print(f"check-report-format-boundary: FAILED with {len(errors)} issue(s).")
        return 1
    print("check-report-format-boundary: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
