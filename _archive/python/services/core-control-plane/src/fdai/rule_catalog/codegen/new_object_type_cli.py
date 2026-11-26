"""CLI: ``python -m fdai.rule_catalog.codegen.new_object_type_cli``.

Emits a shipped-shape :class:`~fdai.shared.contracts.models.OntologyObjectType`
YAML into ``--out`` (default: stdout). Fork usage::

    python -m fdai.rule_catalog.codegen.new_object_type_cli \\
        --name GovernanceProposal \\
        --key id \\
        --property id:string:required=true:description="Proposal id" \\
        --property status:string:required=true:access-scope=owner \\
        --property submitter:string:purpose-binding=audit-review \\
        --description "A governance proposal awaiting review." \\
        --out fork/vocabulary/object-types/GovernanceProposal.yaml

Property spec grammar:
    ``name:type[:required=true][:description="..."][:access-scope=<role>]``
    ``[:purpose-binding=code1,code2]``

Every field except ``name`` and ``type`` is optional. The renderer
validates the assembled document through the loader before writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fdai.rule_catalog.codegen.new_object_type import (
    ObjectTypeSpec,
    PropertySpec,
    render_object_type_yaml,
)


def _parse_property(raw: str) -> PropertySpec:
    parts = _split_top_level(raw, ":")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError(f"--property {raw!r} MUST be at least 'name:type'")
    name, type_str, *rest = parts
    required = False
    description: str | None = None
    access_scope = "reader"
    purpose_binding: tuple[str, ...] = ()
    for token in rest:
        key, _, value = token.partition("=")
        key = key.strip()
        value = value.strip().strip('"')
        if key == "required":
            required = value.lower() in ("true", "1", "yes")
        elif key == "description":
            description = value
        elif key == "access-scope":
            access_scope = value
        elif key == "purpose-binding":
            purpose_binding = tuple(p.strip() for p in value.split(",") if p.strip())
        else:
            raise argparse.ArgumentTypeError(f"--property {raw!r}: unknown attribute {key!r}")
    return PropertySpec(
        name=name.strip(),
        type=type_str.strip(),
        required=required,
        description=description,
        access_scope=access_scope,
        purpose_binding=purpose_binding,
    )


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split by ``sep`` while respecting double-quoted regions."""
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == sep and not in_quotes:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return parts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fdai.rule_catalog.codegen.new_object_type_cli",
        description="Scaffold a new ontology ObjectType YAML.",
    )
    parser.add_argument("--name", required=True, help="PascalCase ObjectType name.")
    parser.add_argument(
        "--key", required=True, help="Property that uniquely identifies an instance."
    )
    parser.add_argument(
        "--property",
        dest="properties",
        action="append",
        required=True,
        type=_parse_property,
        help="Repeatable. name:type[:required=true][:description=...][:access-scope=<role>][:purpose-binding=a,b]",
    )
    parser.add_argument("--description", default=None, help="One-line ObjectType description.")
    parser.add_argument(
        "--out",
        default=None,
        help="Output file path; when omitted, writes to stdout.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite --out if it already exists.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    spec = ObjectTypeSpec(
        name=args.name,
        key=args.key,
        properties=tuple(args.properties),
        description=args.description,
        header_comment=(
            f"Fork-generated ObjectType {args.name}.",
            "Adjust access_scope / purpose_binding per your access-control policy.",
        ),
    )
    yaml_text = render_object_type_yaml(spec)

    if args.out is None:
        sys.stdout.write(yaml_text)
        return 0
    out_path = Path(args.out)
    if out_path.exists() and not args.overwrite:
        raise SystemExit(f"{out_path} already exists; pass --overwrite to replace.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)
    print(f"wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
