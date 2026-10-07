"""FDAI native memory-safety proof harness: run inside the code-build-prove sandbox only.

Standard library only and Python 3.10 compatible. For each C or C++ target it finds the function
that encloses the fix-site line, accepts only a buffer signature it can drive deterministically
(a byte or char pointer with an optional length, or one NUL-terminated string), and builds a small
driver plus the target file with AddressSanitizer and UndefinedBehaviorSanitizer. It then runs the
driver over a fixed set of input lengths. A target is ``proven`` only when a sanitizer report's
first frame in the target file is the fix-site line.

Memory stays bounded without a sandbox address-space limit, which AddressSanitizer can't run
under: the compiler gets an address-space limit, and every run gets ``hard_rss_limit_mb``, a CPU
limit, a wall-clock timeout, and truncated output.

This file is a catalog asset, not an FDAI module: the proof lane copies it into the sandbox.

Usage: python fdai_prove_native.py SOURCE_ROOT TARGETS_JSON COMPILER
"""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import sys
from typing import Any

LENGTHS = (0, 1, 2, 4, 8, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128, 129, 255, 256, 257, 512)
COMPILE_ADDRESS_BYTES = 2 * 1024**3
COMPILE_SECONDS = 60
RUN_SECONDS = 5
MAX_REPORT_BYTES = 65_536
SANITIZER_ENV = {
    "PATH": "/usr/bin:/bin",
    "ASAN_OPTIONS": "detect_leaks=0:hard_rss_limit_mb=512:allocator_may_return_null=1"
    ":halt_on_error=1:symbolize=1",
    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
}
DEFINITION = re.compile(
    r"(?:^|\n)[ \t]*(?:static\s+|inline\s+|extern\s+)*[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)[ \t]*"
    r"\(([^;{}()]*)\)\s*\{"
)
BUFFER = re.compile(r"^(?:const\s+)?(?:unsigned\s+char|char|uint8_t|void)\s*\*\s*\w+$")
LENGTH = re.compile(r"^(?:const\s+)?(?:size_t|int|unsigned(?:\s+int)?|long|unsigned\s+long)\s+\w+$")
KEYWORDS = frozenset({"if", "for", "while", "switch", "return", "sizeof"})


def enclosing_function(source: str, line: int) -> tuple[str, list[str]] | None:
    """Return the name and parameters of the function whose body contains ``line``."""
    for match in DEFINITION.finditer(source):
        name = match.group(1)
        if name in KEYWORDS:
            continue
        start = match.end() - 1
        depth = 0
        end = None
        for index in range(start, len(source)):
            char = source[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end is None:
            continue
        first = source.count("\n", 0, start) + 1
        last = source.count("\n", 0, end) + 1
        if first <= line <= last:
            params = [p.strip() for p in match.group(2).split(",") if p.strip()]
            return name, [] if params == ["void"] else params
    return None


def driver(path: str, name: str, params: list[str]) -> str | None:
    """Return driver source for a supported buffer signature, or ``None``."""
    if len(params) == 1 and BUFFER.match(params[0]):
        call = f"{name}((void *)buffer)"
    elif len(params) == 2 and BUFFER.match(params[0]) and LENGTH.match(params[1]):
        call = f"{name}((void *)buffer, length)"
    else:
        return None
    return (
        "#include <stdlib.h>\n#include <string.h>\n"
        f'#include "{path}"\n'
        "int fdai_driver(int argc, char **argv) {\n"
        "  size_t length = (size_t)strtoul(argv[1], 0, 10);\n"
        "  char *buffer = malloc(length + 1);\n"
        "  if (!buffer) return 2;\n"
        "  memset(buffer, 'A', length);\n"
        "  buffer[length] = 0;\n"
        f"  {call};\n"
        "  free(buffer);\n"
        "  return 0;\n"
        "}\n"
    )


def _limit_compile() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (COMPILE_ADDRESS_BYTES, COMPILE_ADDRESS_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (COMPILE_SECONDS, COMPILE_SECONDS))


def _limit_run() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (RUN_SECONDS, RUN_SECONDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def report_site(report: str, path: str) -> tuple[str, int] | None:
    """Return the sanitizer kind and the first target-file line of a sanitizer report."""
    asan = re.search(r"ERROR: AddressSanitizer: ([\w-]+)", report)
    if asan:
        for frame in re.finditer(r"#\d+ 0x[0-9a-f]+ in \S+ (\S+?):(\d+)", report):
            if frame.group(1) == path:
                return "asan:" + asan.group(1), int(frame.group(2))
        return None
    ubsan = re.search(re.escape(path) + r":(\d+):\d+: runtime error", report)
    if ubsan:
        return "ubsan", int(ubsan.group(1))
    return None


ENTRY = (
    "int fdai_driver(int argc, char **argv);\nint main(int argc, char **argv) {\n"
    "  return fdai_driver(argc, argv);\n}\n"
)


def _compile(compiler: str, scratch: str, driver_source: str, cplusplus: bool) -> str | None:
    driver_path = os.path.join(scratch, "driver.cc" if cplusplus else "driver.c")
    entry_path = os.path.join(scratch, "entry.c")
    with open(driver_path, "w", encoding="utf-8") as handle:
        handle.write(driver_source)
    with open(entry_path, "w", encoding="utf-8") as handle:
        handle.write(ENTRY)
    binary = os.path.join(scratch, "proof")
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g", "-O0", "-w"]
    steps = [
        [compiler, *flags, "-Dmain=fdai_target_main", "-c", driver_path, "-o", binary + ".d.o"],
        [compiler, *flags, "-c", entry_path, "-o", binary + ".e.o"],
        [compiler, *flags, binary + ".d.o", binary + ".e.o", "-o", binary]
        + (["-lstdc++"] if cplusplus else []),
    ]
    for argv in steps:
        try:
            done = subprocess.run(  # noqa: S603 - fixed compiler argv inside the sandbox
                argv,
                capture_output=True,
                timeout=COMPILE_SECONDS,
                env={"PATH": "/usr/bin:/bin"},
                preexec_fn=_limit_compile,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None
        if done.returncode != 0:
            return None
    return binary


def prove(root: str, target: dict[str, Any], compiler: str, scratch: str) -> dict[str, Any]:
    issue_id = target["issue_id"]
    relative = str(target["path"])
    path = os.path.realpath(os.path.join(root, relative))
    if not path.startswith(os.path.realpath(root) + os.sep) or not os.path.isfile(path):
        return {"issue_id": issue_id, "outcome": "not_proven", "reason": "outside_source"}
    with open(path, encoding="utf-8", errors="replace") as handle:
        found = enclosing_function(handle.read(), int(target["line"]))
    if found is None:
        return {"issue_id": issue_id, "outcome": "not_proven", "reason": "no_function"}
    source = driver(path, *found)
    if source is None:
        return {"issue_id": issue_id, "outcome": "not_proven", "reason": "unsupported_signature"}
    binary = _compile(compiler, scratch, source, relative.endswith((".cc", ".cpp", ".cxx")))
    if binary is None:
        return {"issue_id": issue_id, "outcome": "not_proven", "reason": "build_failed"}
    for length in LENGTHS:
        try:
            done = subprocess.run(  # noqa: S603 - the proof binary built above
                [binary, str(length)],
                capture_output=True,
                timeout=RUN_SECONDS,
                env=SANITIZER_ENV,
                preexec_fn=_limit_run,
                check=False,
            )
        except subprocess.TimeoutExpired:
            continue
        report = done.stderr[:MAX_REPORT_BYTES].decode("utf-8", "replace")
        site = report_site(report, path)
        if site is not None and site[1] == int(target["line"]):
            return {
                "issue_id": issue_id,
                "outcome": "proven",
                "reason": "sanitizer_report_at_fix_site",
                "sink": f"{site[0]}:len={length}",
            }
    return {"issue_id": issue_id, "outcome": "not_proven", "reason": "no_report_at_fix_site"}


def main(argv: list[str]) -> int:
    root, targets_path, compiler = argv[1], argv[2], argv[3]
    with open(targets_path, encoding="utf-8") as handle:
        targets = json.load(handle)
    scratch = os.environ.get("TMPDIR", "/tmp")  # noqa: S108 - the sandbox's private tmpfs
    for index, target in enumerate(targets):
        work = os.path.join(scratch, f"native-{index}")
        os.makedirs(work, mode=0o700, exist_ok=True)
        try:
            result = prove(root, target, compiler, work)
        except Exception as exc:  # noqa: BLE001 - report and continue with the next target
            result = {
                "issue_id": target.get("issue_id"),
                "outcome": "not_proven",
                "reason": "harness_error",
                "detail": type(exc).__name__,
            }
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
