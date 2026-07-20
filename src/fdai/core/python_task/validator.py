"""Static, non-executing validation for generated Python task artifacts."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath

from fdai.shared.providers.vm_task import PythonTaskCapability, PythonTaskSpec

_SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,199}$")
_NETWORK_MODULES = frozenset({"aiohttp", "httpx", "requests", "socket", "urllib"})
_GPU_MODULES = frozenset({"cupy", "jax", "nvidia", "tensorflow", "torch"})
_PROCESS_MODULES = frozenset({"multiprocessing", "subprocess"})
_FILESYSTEM_MODULES = frozenset({"pathlib"})
_FILESYSTEM_WRITE_MODULES = frozenset({"shutil", "tempfile"})
_DYNAMIC_CALLS = frozenset({"compile", "eval", "exec", "__import__"})
_SECRET_MARKERS = ("AccountKey=", "SharedAccessKey=", "-----BEGIN PRIVATE KEY-----")
_PROGRAMMATIC_PIPELINE_MODULES = frozenset(
    {
        "collections",
        "csv",
        "datetime",
        "decimal",
        "functools",
        "hashlib",
        "itertools",
        "json",
        "math",
        "operator",
        "re",
        "statistics",
        "string",
        "fdai_pipeline_client",
    }
)
_PROGRAMMATIC_PIPELINE_FORBIDDEN_CALLS = frozenset(
    {
        "breakpoint",
        "delattr",
        "dir",
        "getattr",
        "globals",
        "hasattr",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)
_PROGRAMMATIC_PIPELINE_RECURSIVE_CALLS = frozenset(
    {
        "client.run_pipeline",
        "client.run_programmatic_pipeline",
        "run_pipeline",
        "run_programmatic_pipeline",
    }
)


@dataclass(frozen=True, slots=True)
class PythonTaskPolicy:
    max_files: int = 32
    max_file_bytes: int = 128 * 1024
    max_total_bytes: int = 64 * 1024


@dataclass(frozen=True, slots=True)
class PythonTaskValidationIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class PythonTaskValidationReport:
    artifact_hash: str
    issues: tuple[PythonTaskValidationIssue, ...]
    detected_capabilities: frozenset[PythonTaskCapability]
    imported_modules: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class ProgrammaticPipelineValidationReport:
    source_digest: str
    issues: tuple[PythonTaskValidationIssue, ...]
    imported_modules: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_programmatic_pipeline_source(
    source: str,
    *,
    path: str = "pipeline.py",
) -> ProgrammaticPipelineValidationReport:
    """Validate reviewed pipeline source without importing or executing it."""

    import hashlib

    issues: list[PythonTaskValidationIssue] = []
    imported: set[str] = set()
    try:
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        issues.append(_issue("syntax_error", path, str(exc)))
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                if any(
                    alias.name.split(".", 1)[0] == "fdai_pipeline_client" for alias in node.names
                ):
                    issues.append(
                        _issue(
                            "forbidden_client_import",
                            path,
                            "import PipelineClient directly from fdai_pipeline_client",
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.level or node.module is None:
                    issues.append(
                        _issue(
                            "forbidden_import",
                            path,
                            "relative imports are not allowed in programmatic pipelines",
                        )
                    )
                else:
                    imported.add(node.module.split(".", 1)[0])
                    if node.module == "fdai_pipeline_client" and (
                        len(node.names) != 1 or node.names[0].name != "PipelineClient"
                    ):
                        issues.append(
                            _issue(
                                "forbidden_client_import",
                                path,
                                "only PipelineClient may be imported from generated client",
                            )
                        )
            elif isinstance(node, ast.Call):
                name = _qualified_call_name(node.func)
                if name in _DYNAMIC_CALLS:
                    issues.append(
                        _issue("dynamic_code", path, f"dynamic code call {name!r} is not allowed")
                    )
                elif name in _PROGRAMMATIC_PIPELINE_FORBIDDEN_CALLS:
                    issues.append(
                        _issue(
                            "forbidden_runtime_access",
                            path,
                            f"runtime access call {name!r} is not allowed",
                        )
                    )
                elif name in _PROGRAMMATIC_PIPELINE_RECURSIVE_CALLS:
                    issues.append(
                        _issue(
                            "recursive_pipeline",
                            path,
                            "programmatic pipelines cannot invoke another pipeline",
                        )
                    )
            elif isinstance(node, ast.Name) and node.id.startswith("__"):
                issues.append(
                    _issue(
                        "forbidden_introspection",
                        path,
                        "dunder names are not allowed in programmatic pipelines",
                    )
                )
            elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                issues.append(
                    _issue(
                        "forbidden_introspection",
                        path,
                        "private attributes are not allowed in programmatic pipelines",
                    )
                )

        for module in sorted(imported - _PROGRAMMATIC_PIPELINE_MODULES):
            issues.append(
                _issue(
                    "forbidden_import",
                    path,
                    f"module {module!r} is not allowed in programmatic pipelines",
                )
            )

    return ProgrammaticPipelineValidationReport(
        source_digest=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        issues=tuple(issues),
        imported_modules=tuple(sorted(imported)),
    )


def validate_python_task(
    task: PythonTaskSpec,
    *,
    policy: PythonTaskPolicy | None = None,
) -> PythonTaskValidationReport:
    """Validate structure and AST without importing or executing task code."""

    resolved_policy = policy or PythonTaskPolicy()
    issues: list[PythonTaskValidationIssue] = []
    detected: set[PythonTaskCapability] = set()
    imported: set[str] = set()
    by_path = {item.path: item for item in task.files}

    if PythonTaskCapability.PROCESS in task.capabilities:
        issues.append(
            _issue(
                "process_capability_forbidden",
                "capabilities",
                "generated Python tasks MUST use a registered command tool instead of process",
            )
        )

    if len(by_path) != len(task.files):
        issues.append(_issue("duplicate_path", "files", "file paths MUST be unique"))
    if len(task.files) > resolved_policy.max_files:
        issues.append(_issue("too_many_files", "files", "task exceeds the file-count limit"))

    total_bytes = 0
    for item in task.files:
        encoded_bytes = len(item.content.encode("utf-8"))
        total_bytes += encoded_bytes
        if not _valid_relative_path(item.path):
            issues.append(
                _issue("invalid_path", item.path, "path MUST be relative and traversal-free")
            )
        if encoded_bytes > resolved_policy.max_file_bytes:
            issues.append(_issue("file_too_large", item.path, "file exceeds the byte limit"))
        if any(marker in item.content for marker in _SECRET_MARKERS):
            issues.append(_issue("embedded_secret", item.path, "source contains a secret marker"))
        if item.path.endswith(".py"):
            _validate_python_file(item.path, item.content, issues, detected, imported)

    if total_bytes > resolved_policy.max_total_bytes:
        issues.append(_issue("artifact_too_large", "files", "task exceeds the total byte limit"))
    if task.entrypoint not in by_path:
        issues.append(_issue("missing_entrypoint", "entrypoint", "entrypoint is not in files"))
    elif not task.entrypoint.endswith(".py"):
        issues.append(_issue("invalid_entrypoint", "entrypoint", "entrypoint MUST be a .py file"))

    missing_capabilities = detected - task.capabilities
    for capability in sorted(missing_capabilities, key=lambda value: value.value):
        issues.append(
            _issue(
                "undeclared_capability",
                "capabilities",
                f"source requires declared capability {capability.value!r}",
            )
        )

    local_module_roots = {
        PurePosixPath(path).parts[0].removesuffix(".py") for path in by_path if path.endswith(".py")
    }
    external_modules = {
        module
        for module in imported
        if module not in sys.stdlib_module_names and module not in local_module_roots
    }
    declared_roots = {module.split(".", 1)[0] for module in task.required_modules}
    for module in sorted(external_modules - declared_roots):
        issues.append(
            _issue(
                "undeclared_module",
                "required_modules",
                f"external module {module!r} is not declared",
            )
        )

    return PythonTaskValidationReport(
        artifact_hash=task.artifact_hash,
        issues=tuple(issues),
        detected_capabilities=frozenset(detected),
        imported_modules=tuple(sorted(imported)),
    )


def _validate_python_file(
    path: str,
    content: str,
    issues: list[PythonTaskValidationIssue],
    detected: set[PythonTaskCapability],
    imported: set[str],
) -> None:
    try:
        tree = ast.parse(content, filename=path)
        compile(tree, path, "exec")
    except (SyntaxError, ValueError) as exc:
        issues.append(_issue("syntax_error", path, str(exc)))
        return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in _DYNAMIC_CALLS:
                issues.append(
                    _issue("dynamic_code", path, f"dynamic code call {name!r} is not allowed")
                )
            if name == "open":
                detected.add(_open_capability(node))
            if name in {"os.system", "os.popen"}:
                detected.add(PythonTaskCapability.PROCESS)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in {
                    "copy",
                    "copy2",
                    "copyfile",
                    "copytree",
                    "makedirs",
                    "mkdir",
                    "move",
                    "remove",
                    "removedirs",
                    "rename",
                    "replace",
                    "rmdir",
                    "rmtree",
                    "unlink",
                    "write_bytes",
                    "write_text",
                }:
                    detected.add(PythonTaskCapability.FILESYSTEM_WRITE)
                elif node.func.attr in {"read_bytes", "read_text"}:
                    detected.add(PythonTaskCapability.FILESYSTEM_READ)

    if imported & _NETWORK_MODULES:
        detected.add(PythonTaskCapability.NETWORK)
    if imported & _GPU_MODULES:
        detected.add(PythonTaskCapability.GPU)
    if imported & _PROCESS_MODULES:
        detected.add(PythonTaskCapability.PROCESS)
    if imported & _FILESYSTEM_MODULES:
        detected.add(PythonTaskCapability.FILESYSTEM_READ)
    if imported & _FILESYSTEM_WRITE_MODULES:
        detected.add(PythonTaskCapability.FILESYSTEM_WRITE)


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    return ""


def _qualified_call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _open_capability(node: ast.Call) -> PythonTaskCapability:
    mode: str | None = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        mode = node.args[1].value if isinstance(node.args[1].value, str) else None
    for keyword in node.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value if isinstance(keyword.value.value, str) else None
    if mode is not None and any(flag in mode for flag in "wax+"):
        return PythonTaskCapability.FILESYSTEM_WRITE
    return PythonTaskCapability.FILESYSTEM_READ


def _valid_relative_path(value: str) -> bool:
    if not _SAFE_PATH.fullmatch(value):
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def _issue(code: str, path: str, message: str) -> PythonTaskValidationIssue:
    return PythonTaskValidationIssue(code=code, path=path, message=message)


__all__ = [
    "ProgrammaticPipelineValidationReport",
    "PythonTaskPolicy",
    "PythonTaskValidationIssue",
    "PythonTaskValidationReport",
    "validate_programmatic_pipeline_source",
    "validate_python_task",
]
