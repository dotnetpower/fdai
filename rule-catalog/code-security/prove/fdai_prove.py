"""FDAI proof harness: run inside the disposable code-build-prove sandbox only.

Standard library only and Python 3.10 compatible, because it runs on the sandbox's system Python.
For each target it imports the module that holds the fix site, replaces the sinks the target's
weakness class cares about with recording hooks that never perform the real effect, and calls the
enclosing function with a canary in every attacker-controlled input. A target is ``proven`` only
when the canary reaches the dangerous argument of a hooked sink.

Third-party imports that the sandbox can't satisfy resolve to inert stubs, so framework decorators
and models load without network or packages. The harness writes one JSON object per target to
standard output and never writes elsewhere; the sandbox gives it no network and a read-only source.

This file is a catalog asset, not an FDAI module: the proof lane copies it into the sandbox, and
FDAI never imports it.

Usage: python fdai_prove.py SOURCE_ROOT TARGETS_JSON
"""

from __future__ import annotations

import ast
import base64
import builtins
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import os
import signal
import sys
import types
from collections.abc import Callable, Iterator, Sequence
from typing import Any

_MARKER = "FDAICANARYXY"
_PAYLOADS = {
    "command_injection": "x;" + _MARKER,
    "code_injection": _MARKER,
    "sql_injection": "x'" + _MARKER,
    "path_traversal": "../../" + _MARKER,
    "unsafe_deserialization": base64.b64encode(_MARKER.encode("ascii")).decode("ascii"),
}
CANARY = _PAYLOADS["code_injection"]
_PER_TARGET_SECONDS = 10
_STDLIB = set(getattr(sys, "stdlib_module_names", ()))
_SQL_METHODS = frozenset({"execute", "executemany", "executescript", "raw", "text"})
_SQL_RECORDER: list[Recorder] = []


def _stub_attribute(name: str) -> Any:
    if _SQL_RECORDER and name in _SQL_METHODS:
        return _SQL_RECORDER[0].hook(f"*.{name}", Stub)
    return Stub()


class Stub:
    """An inert stand-in for any unavailable third-party object."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _stub_attribute(name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if len(args) == 1 and not kwargs and callable(args[0]) and not isinstance(args[0], Stub):
            return args[0]
        return Stub()

    def __getitem__(self, key: object) -> Stub:
        return Stub()

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __bool__(self) -> bool:
        return True

    def __mro_entries__(self, bases: tuple[Any, ...]) -> tuple[type, ...]:
        return (StubBase,)


class _StubMeta(type):
    def __getattr__(cls, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _stub_attribute(name)


class StubBase(metaclass=_StubMeta):
    """Base for classes that subclass an unavailable framework type, such as an ORM model."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _stub_attribute(name)


class _StubModule(types.ModuleType):
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return Stub()


class _StubLoader(importlib.abc.Loader):
    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType:
        module = _StubModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module: types.ModuleType) -> None:
        return None


class _StubFinder(importlib.abc.MetaPathFinder):
    """Satisfy third-party imports that the real path finder can't."""

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None = None,
        target: types.ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname.split(".")[0] in _STDLIB:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            try:
                spec = finder.find_spec(fullname, path, target)
            except (ImportError, AttributeError, ValueError):
                spec = None
            if spec is not None:
                return None
        return importlib.machinery.ModuleSpec(fullname, _StubLoader(), is_package=True)


class CanaryMap(dict[object, str]):
    """A request collection whose every key holds the canary."""

    def __missing__(self, key: object) -> str:
        return CANARY

    def get(self, key: object, default: object = None) -> str:
        return CANARY

    def getlist(self, key: object, default: object = None) -> list[str]:
        return [CANARY]

    def __contains__(self, key: object) -> bool:
        return True


class FakeUser:
    is_authenticated = True
    is_active = True
    is_superuser = False
    username = "fdai-proof"
    id = 1


class FakeRequest:
    def __init__(self, method: str) -> None:
        self.method = method
        self.user = FakeUser()
        for name in (
            "args",
            "form",
            "values",
            "GET",
            "POST",
            "FILES",
            "COOKIES",
            "cookies",
            "headers",
            "META",
            "query_params",
            "path_params",
            "match_info",
            "params",
            "files",
        ):
            setattr(self, name, CanaryMap())
        self.json = CanaryMap()
        self.data = CANARY.encode("ascii")
        self.body = CANARY.encode("ascii")
        self.query_string = CANARY.encode("ascii")

    def get_json(self, *args: Any, **kwargs: Any) -> CanaryMap:
        return CanaryMap()

    def get_data(self, *args: Any, **kwargs: Any) -> bytes:
        return CANARY.encode("ascii")

    def __getattr__(self, name: str) -> Any:
        return Stub()


def _text(value: object) -> str:
    if isinstance(value, Stub):
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("latin-1")
    if isinstance(value, (io.BytesIO, io.StringIO)):
        return _text(value.getvalue())
    if isinstance(value, (list, tuple)):
        return " ".join(_text(item) for item in value)
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - foreign objects may refuse str()
        return ""


def _shell_injected(text: str) -> bool:
    import shlex

    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    return any(
        token in (";", "&&", "||", "|", "&") and following == _MARKER
        for token, following in zip(tokens, tokens[1:], strict=False)
    )


def _code_injected(text: str) -> bool:
    try:
        tree = ast.parse(text, mode="exec")
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, ast.Name) and node.id == _MARKER for node in ast.walk(tree))


def _sql_injected(text: str) -> bool:
    raw = "x'" + _MARKER
    return raw in text and "x''" + _MARKER not in text and "x\\'" + _MARKER not in text


def _deserialized(text: str) -> bool:
    return CANARY in text or _MARKER in text


_PREDICATES: dict[str, Callable[[str], bool]] = {
    "command_injection": _shell_injected,
    "code_injection": _code_injected,
    "sql_injection": _sql_injected,
    "path_traversal": lambda text: "../../" + _MARKER in text,
    "unsafe_deserialization": _deserialized,
}
_ACTIVE = ["code_injection"]


def tainted(value: object) -> bool:
    """Return whether ``value`` carries the active class's payload in an exploitable form."""
    return _PREDICATES[_ACTIVE[0]](_text(value))


class Recorder:
    def __init__(self) -> None:
        self.hits: list[str] = []

    def hook(
        self, name: str, result: Any, check_arg: int = 0, require_shell: bool = False
    ) -> Callable[..., Any]:
        recorder = self

        def sink(*args: Any, **kwargs: Any) -> Any:
            if require_shell and not kwargs.get("shell"):
                return result() if callable(result) else result
            value = args[check_arg] if len(args) > check_arg else kwargs.get("args", "")
            if tainted(value):
                recorder.hits.append(name)
            return result() if callable(result) else result

        return sink


class _FakeProcess:
    returncode = 0
    stdout = b""
    stderr = b""
    pid = 0

    def communicate(self, *args: Any, **kwargs: Any) -> tuple[bytes, bytes]:
        return b"", b""

    def wait(self, *args: Any, **kwargs: Any) -> int:
        return 0


def _file(*args: Any, **kwargs: Any) -> io.BytesIO | io.StringIO:
    mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
    return io.BytesIO(b"") if "b" in str(mode) else io.StringIO("")


def _sinks(
    recorder: Recorder, weakness_class: str
) -> tuple[dict[tuple[str, str], Any], dict[str, Any]]:
    """Return {(module, attribute): hook} and {builtin name: hook} for one class."""
    hook = recorder.hook
    modules: dict[tuple[str, str], Any] = {}
    names: dict[str, Any] = {}
    if weakness_class == "command_injection":
        for attr in ("system", "popen"):
            modules[("os", attr)] = hook(f"os.{attr}", 0)
        for attr in ("run", "call", "check_call", "check_output", "Popen"):
            modules[("subprocess", attr)] = hook(f"subprocess.{attr}", _FakeProcess, 0, True)
        for attr in ("getoutput", "getstatusoutput"):
            modules[("subprocess", attr)] = hook(f"subprocess.{attr}", "")
    elif weakness_class == "code_injection":
        for name in ("eval", "exec", "compile"):
            names[name] = hook(name, None)
    elif weakness_class == "unsafe_deserialization":
        for module, attr in (
            ("pickle", "loads"),
            ("pickle", "load"),
            ("marshal", "loads"),
            ("dill", "loads"),
            ("jsonpickle", "decode"),
            ("yaml", "load"),
            ("yaml", "unsafe_load"),
        ):
            modules[(module, attr)] = hook(f"{module}.{attr}", Stub)
    elif weakness_class == "sql_injection":
        _SQL_RECORDER[:] = [recorder]

        class _Cursor:
            def __getattr__(self, name: str) -> Any:
                if name in _SQL_METHODS:
                    return hook(f"sqlite3.Cursor.{name}", _Cursor)
                return Stub()

            def fetchall(self) -> list[Any]:
                return []

            def fetchone(self) -> None:
                return None

        class _Connection(_Cursor):
            def cursor(self, *args: Any, **kwargs: Any) -> _Cursor:
                return _Cursor()

            def __enter__(self) -> _Connection:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        modules[("sqlite3", "connect")] = lambda *args, **kwargs: _Connection()
    elif weakness_class == "path_traversal":
        names["open"] = hook("open", _file)
        for module, attr in (
            ("io", "open"),
            ("os", "remove"),
            ("os", "unlink"),
            ("shutil", "rmtree"),
        ):
            modules[(module, attr)] = hook(f"{module}.{attr}", _file if attr == "open" else None)
    return modules, names


def _function(tree: ast.AST, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    best: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= line <= end and (best is None or node.lineno >= best.lineno):
                best = node
    return best


def _module_name(root: str, path: str) -> str:
    relative = os.path.relpath(path, root)
    parts = relative[:-3].split(os.sep)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _alarm(signum: int, frame: object) -> None:
    raise TimeoutError("proof target timed out")


def prove(root: str, target: dict[str, Any]) -> dict[str, Any]:
    path = os.path.join(root, target["path"])
    with open(path, "rb") as handle:
        tree = ast.parse(handle.read())
    function = _function(tree, int(target["line"]))
    if function is None:
        return {"issue_id": target["issue_id"], "outcome": "not_proven", "reason": "no_function"}
    parent = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and function in node.body
        ),
        None,
    )
    if parent is not None:
        return {"issue_id": target["issue_id"], "outcome": "not_proven", "reason": "method_target"}
    try:
        module = importlib.import_module(_module_name(root, path))
    except BaseException as exc:  # noqa: BLE001 - any import failure leaves the issue unproven
        return {
            "issue_id": target["issue_id"],
            "outcome": "not_proven",
            "reason": "import_failed",
            "detail": type(exc).__name__,
        }
    callable_target = getattr(module, function.name, None)
    if not callable(callable_target):
        return {"issue_id": target["issue_id"], "outcome": "not_proven", "reason": "not_callable"}
    global CANARY
    _ACTIVE[0] = target["weakness_class"]
    CANARY = _PAYLOADS[target["weakness_class"]]
    recorder = Recorder()
    module_hooks, name_hooks = _sinks(recorder, target["weakness_class"])
    originals: list[tuple[Any, str, Any]] = []
    for (module_name, attr), hook in module_hooks.items():
        owner = sys.modules.get(module_name)
        if owner is None:
            continue
        original = getattr(owner, attr, None)
        originals.append((owner, attr, original))
        setattr(owner, attr, hook)
        for key, value in list(vars(module).items()):
            if original is not None and value is original:
                originals.append((module, key, value))
                setattr(module, key, hook)
    for name, hook in name_hooks.items():
        originals.append((module, name, vars(module).get(name, getattr(builtins, name))))
        setattr(module, name, hook)
    previous_request = vars(module).get("request")
    params = [
        a.arg for a in function.args.posonlyargs + function.args.args + function.args.kwonlyargs
    ]
    try:
        for method in ("POST", "GET"):
            request = FakeRequest(method)
            if "request" in vars(module):
                setattr(module, "request", request)  # noqa: B010 - dynamic module attribute
            arguments: dict[str, Any] = {}
            for name in params:
                arguments[name] = request if name in ("request", "req") else CANARY
            signal.signal(signal.SIGALRM, _alarm)
            signal.alarm(_PER_TARGET_SECONDS)
            try:
                result = callable_target(**arguments)
                if hasattr(result, "__await__"):
                    import asyncio

                    asyncio.run(result)
            except BaseException:  # noqa: BLE001, S110 - the target may fail after the sink
                pass
            finally:
                signal.alarm(0)
            if recorder.hits:
                break
    finally:
        _SQL_RECORDER[:] = []
        for owner, attr, value in reversed(originals):
            setattr(owner, attr, value)
        if previous_request is not None:
            setattr(module, "request", previous_request)  # noqa: B010 - dynamic module attribute
    if recorder.hits:
        return {
            "issue_id": target["issue_id"],
            "outcome": "proven",
            "reason": "canary_reached_sink",
            "sink": recorder.hits[0],
        }
    return {
        "issue_id": target["issue_id"],
        "outcome": "not_proven",
        "reason": "canary_not_observed",
    }


def main(argv: Sequence[str]) -> int:
    root, targets_path = argv[1], argv[2]
    with open(targets_path, encoding="utf-8") as handle:
        targets = json.load(handle)
    sys.path.insert(0, root)
    sys.meta_path.append(_StubFinder())
    sys.dont_write_bytecode = True
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    for target in targets:
        try:
            result = prove(root, target)
        except BaseException as exc:  # noqa: BLE001 - report and continue with the next target
            result = {
                "issue_id": target.get("issue_id"),
                "outcome": "not_proven",
                "reason": "harness_error",
                "detail": type(exc).__name__,
            }
        sys.stdout = io.StringIO()
        out = sys.__stdout__
        if out is not None:
            out.write(json.dumps(result) + "\n")
            out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
