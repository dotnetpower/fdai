"""Conservative Python definition/call index without importing application modules."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


def dotted(node: ast.AST) -> str | None:
    """Return names only; never copy literal arguments or source payloads into the graph."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


@dataclass
class Definition:
    identifier: str
    module: str
    path: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    owner_class: str | None


class BodyVisitor(ast.NodeVisitor):
    """Visit a single execution body, not nested functions or classes."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.imports: list[ast.Import | ast.ImportFrom] = []
        self.assigned: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.assigned.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        pass

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass


class SourceIndex:
    """Resolve lexical and declared-type references without guessing runtime implementations."""

    def __init__(self, root: Path, files: list[Path]) -> None:
        self.root = root
        self.functions: dict[str, Definition] = {}
        self.classes: dict[str, tuple[str, list[ast.expr]]] = {}
        self.modules: dict[str, ast.Module] = {}
        self.imports: dict[str, dict[str, str]] = {}
        self.paths: dict[str, str] = {}
        for path in sorted(files):
            parts = path.relative_to(root).parts
            source_offset = parts.index("src") + 1
            module_parts = list(parts[source_offset:])
            module_parts[-1] = Path(module_parts[-1]).stem
            if module_parts[-1] == "__init__":
                module_parts.pop()
            module = ".".join(module_parts)
            if module in self.modules:
                raise ValueError(f"Duplicate source module: {module}")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            self.modules[module] = tree
            self.paths[module] = path.relative_to(root).as_posix()
            imports = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
            self.imports[module] = self.import_map(module, imports)
            self._collect(module, tree.body, module, None)
        self.receivers = self._receivers()

    def _receivers(self) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        for definition in self.functions.values():
            if definition.node.name != "__init__" or definition.owner_class is None:
                continue
            annotations = {
                arg.arg: arg.annotation
                for arg in [
                    *definition.node.args.posonlyargs,
                    *definition.node.args.args,
                    *definition.node.args.kwonlyargs,
                ]
            }
            for statement in definition.node.body:
                if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
                    continue
                target = dotted(statement.targets[0])
                value = statement.value
                if not target or not target.startswith("self.") or target.count(".") != 1:
                    continue
                if isinstance(value, ast.BoolOp) and isinstance(value.op, ast.Or):
                    value = value.values[0]
                annotation = annotations.get(value.id) if isinstance(value, ast.Name) else None
                if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
                    if (
                        isinstance(annotation.right, ast.Constant)
                        and annotation.right.value is None
                    ):
                        annotation = annotation.left
                raw = (
                    dotted(annotation)
                    if annotation
                    else dotted(value.func)
                    if isinstance(value, ast.Call)
                    else None
                )
                if raw:
                    first, _, rest = raw.partition(".")
                    name = self.imports[definition.module].get(
                        first, f"{definition.module}.{first}"
                    )
                    resolved = self.exported(name + (f".{rest}" if rest else ""))
                    if resolved in self.classes:
                        result[(definition.owner_class, target.split(".")[1])] = resolved
        return result

    def import_map(self, module: str, nodes: list[ast.Import | ast.ImportFrom]) -> dict[str, str]:
        result: dict[str, str] = {}
        for node in nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    result[alias.asname or alias.name.split(".")[0]] = (
                        alias.name if alias.asname else alias.name.split(".")[0]
                    )
            else:
                parent = (
                    module
                    if self.paths.get(module, "").endswith("/__init__.py")
                    else module.rpartition(".")[0]
                )
                prefix = node.module or ""
                if node.level:
                    parent_parts = parent.split(".")
                    prefix = ".".join(
                        parent_parts[: len(parent_parts) - node.level + 1]
                        + ([prefix] if prefix else [])
                    )
                for alias in node.names:
                    if alias.name != "*":
                        result[alias.asname or alias.name] = f"{prefix}.{alias.name}"
        return result

    def _collect(self, module: str, body: list[ast.stmt], prefix: str, owner: str | None) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                identifier = f"{prefix}.{node.name}"
                self.classes[identifier] = (module, node.bases)
                self._collect(module, node.body, identifier, identifier)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                identifier = f"{prefix}.{node.name}"
                args = {
                    arg.arg
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                }
                lexical_owner = (
                    None
                    if owner and prefix != owner and args.intersection({"self", "cls"})
                    else owner
                )
                self.functions[identifier] = Definition(
                    identifier, module, self.paths[module], node, lexical_owner
                )
                self._collect(module, node.body, identifier, lexical_owner)
            elif isinstance(node, ast.If | ast.Try):
                self._collect(module, node.body, prefix, owner)
                self._collect(module, node.orelse, prefix, owner)

    def exported(self, name: str, seen: set[str] | None = None) -> str:
        visited = set() if seen is None else seen
        if name in visited:
            return name
        visited.add(name)
        if name in self.functions or name in self.classes:
            return name
        parts = name.split(".")
        for split in range(len(parts) - 1, 0, -1):
            module, local = ".".join(parts[:split]), parts[split]
            imported = self.imports.get(module, {}).get(local)
            if imported:
                binding = f"import:{module}:{local}"
                if binding in visited:
                    return name
                visited.add(binding)
                suffix = ".".join(parts[split + 1 :])
                return self.exported(imported + (f".{suffix}" if suffix else ""), visited)
        return name

    def class_method(self, owner: str, method: str, seen: set[str] | None = None) -> str | None:
        visited = set() if seen is None else seen
        if owner in visited:
            return None
        visited.add(owner)
        candidate = f"{owner}.{method}"
        if candidate in self.functions:
            return candidate
        record = self.classes.get(owner)
        if record is None:
            return None
        module, bases = record
        candidates = set()
        for base in bases:
            raw = dotted(base)
            if raw is None:
                continue
            first, _, rest = raw.partition(".")
            absolute = self.imports[module].get(first, f"{module}.{first}")
            resolved = self.exported(absolute + (f".{rest}" if rest else ""))
            inherited = self.class_method(resolved, method, visited.copy())
            if inherited:
                candidates.add(inherited)
        return next(iter(candidates)) if len(candidates) == 1 else None

    def resolve(self, definition: Definition, call: ast.Call, visitor: BodyVisitor) -> str | None:
        raw = dotted(call.func)
        if raw is None:
            return None
        first, _, rest = raw.partition(".")
        if first in {"self", "cls"}:
            if definition.owner_class and rest and "." not in rest:
                return self.class_method(definition.owner_class, rest)
            if definition.owner_class and rest.count(".") == 1:
                field, method = rest.split(".")
                receiver = self.receivers.get((definition.owner_class, field))
                if receiver:
                    return self.class_method(receiver, method)
            return None
        local_imports = self.import_map(definition.module, visitor.imports)
        args = definition.node.args
        shadowed = {argument.arg for argument in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
        shadowed.update(visitor.assigned)
        if args.vararg:
            shadowed.add(args.vararg.arg)
        if args.kwarg:
            shadowed.add(args.kwarg.arg)
        if first in shadowed and first not in local_imports:
            return None
        aliases = self.imports[definition.module] | local_imports
        if first in aliases:
            candidates = [aliases[first] + (f".{rest}" if rest else "")]
        else:
            candidates = [
                f"{definition.identifier}.{raw}",
                f"{definition.identifier.rpartition('.')[0]}.{raw}",
                f"{definition.module}.{raw}",
            ]
        for candidate in candidates:
            resolved = self.exported(candidate)
            if resolved in self.functions:
                return resolved
            if resolved in self.classes:
                return self.class_method(resolved, "__init__")
        return None

    def calls(self) -> tuple[list[dict], dict[str, list[dict]]]:
        edges: list[dict] = []
        unresolved: dict[str, list[dict]] = {}
        for definition in self.functions.values():
            visitor = BodyVisitor()
            for node in definition.node.body:
                visitor.visit(node)
            for call in visitor.calls:
                target = self.resolve(definition, call, visitor)
                if target:
                    raw = dotted(call.func) or ""
                    edges.append(
                        {
                            "source": definition.identifier,
                            "target": target,
                            "line": call.lineno,
                            "resolution": "declared-receiver"
                            if raw.startswith("self.") and raw.count(".") == 2
                            else "lexical",
                        }
                    )
                else:
                    unresolved.setdefault(definition.identifier, []).append(
                        {
                            "symbol": dotted(call.func) or "<dynamic call>",
                            "line": call.lineno,
                        }
                    )
        return edges, unresolved
