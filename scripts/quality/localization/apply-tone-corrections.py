#!/usr/bin/env python3
"""Apply safe, unambiguous MS-Learn-tone swaps to user-facing markdown docs.

Scope (in):
  README.md, docs/**/*.md, src/**/README.md, console/README.md, infra/README.md,
  rule-catalog/README.md, site/README.md, ui/README.md, mocks/**/README.md,
  tests/**/README.md, tools/**/README.md
Scope (out):
  .github/**/*.md (instructions and skills keep normative RFC 2119 language),
  site/node_modules, .venv

Transformations (only unambiguous phrase-level swaps):
  - "is prohibited"          -> "isn't supported"
  - "is forbidden"           -> "isn't allowed"
  - "are prohibited"         -> "aren't supported"
  - "are forbidden"          -> "aren't allowed"
  - "is a stop-ship"         -> "blocks release"
  - "stop-ship"              -> "release-blocking"
  - "hot-patch"              -> "emergency fix"
  - "Autonomy is never unconditional"
        -> "Autonomy always runs with guardrails"
  - "Fail toward safety"     -> "Choose the safer default when the outcome is uncertain"
  - "This is not an override - it is a definitional gate."
        -> "This is a required check, not an option."

Korean-side transformations (applied to *-ko.md only):
  - "머지 불가"              -> "병합되지 않습니다"
  - "사람 개입"              -> "사람 검토"
  - "실패 -> 안전"           -> "불확실할 때는 안전한 쪽을 선택합니다"
  - "~를 참조합니다."        -> "~를 참조하세요." (only when line-final)
  - "금지"                    -> "지원되지 않음"  (when it stands alone as a state)

Deliberately NOT applied automatically:
  - "MUST" / "MUST NOT" / "SHOULD" - too many are load-bearing operational
    requirements. A blanket softening could weaken safety guarantees.
  - "abstain" - a domain term with a specific control-loop meaning. Kept.
  - Adding jargon gloss on first mention - requires per-doc judgment.

Code fences and inline code are skipped: `re.finditer` over lines and per-line
inline-code split (same approach as `normalize-punctuation.py`).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

EN_SWAPS: list[tuple[str, str]] = [
    ("Autonomy is never unconditional", "Autonomy always runs with guardrails"),
    (
        "This is not an override - it is a definitional gate.",
        "This is a required check, not an option.",
    ),
    ("Fail toward safety", "Choose the safer default when the outcome is uncertain"),
    ("is a stop-ship", "blocks release"),
    ("stop-ship", "release-blocking"),
    ("hot-patch", "emergency fix"),
    ("are prohibited", "aren't supported"),
    ("are forbidden", "aren't allowed"),
    ("is prohibited", "isn't supported"),
    ("is forbidden", "isn't allowed"),
]

# Korean swaps applied to -ko.md only.
KO_SWAPS: list[tuple[str, str]] = [
    ("머지 불가", "병합되지 않습니다"),
    ("사람 개입", "사람 검토"),
    ("실패 -> 안전", "불확실할 때는 안전한 쪽을 선택합니다"),
    ("안전 방향 실패", "불확실할 때는 안전한 쪽을 선택"),
    ("안전 방향으로 실패", "불확실할 때는 안전한 쪽을 선택"),
    ("자율성은 결코 무조건적이지 않습니다", "자율 실행에는 항상 가드레일이 함께 갑니다"),
    ("자율성은 결코 무조건적이지 않다", "자율 실행에는 항상 가드레일이 함께 간다"),
    ("정의상 게이트", "필수 검사"),
    ("를 참조합니다.", "를 참조하세요."),
    ("을 참조합니다.", "을 참조하세요."),
]

INLINE_CODE_RE = re.compile(r"`+[^`\n]*?`+")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")


def apply_to_segment(segment: str, swaps: list[tuple[str, str]]) -> str:
    for old, new in swaps:
        segment = segment.replace(old, new)
    return segment


def process_line(line: str, swaps: list[tuple[str, str]]) -> str:
    out = []
    last = 0
    for m in INLINE_CODE_RE.finditer(line):
        out.append(apply_to_segment(line[last : m.start()], swaps))
        out.append(line[m.start() : m.end()])
        last = m.end()
    out.append(apply_to_segment(line[last:], swaps))
    return "".join(out)


def process_text(text: str, swaps: list[tuple[str, str]]) -> str:
    lines = text.split("\n")
    out = []
    in_fence = False
    fence_char = ""
    for line in lines:
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_char = marker
            elif marker == fence_char:
                in_fence = False
                fence_char = ""
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        out.append(process_line(line, swaps))
    return "\n".join(out)


def in_scope(path: Path) -> bool:
    parts = path.parts
    # Exclude instruction files and skill files. They intentionally keep
    # RFC 2119 normative language.
    if ".github" in parts:
        return False
    # Exclude node_modules, .venv, etc. (git-tracked filter already helps).
    if "node_modules" in parts or ".venv" in parts:
        return False
    # site/src/content/docs/** is auto-mounted from docs/** at build time
    # (see site/scripts/mount-docs.mjs). Editing the mounted copies would be
    # overwritten on the next `npm run mount-docs`; edit the source docs
    # under docs/ instead.
    if len(parts) >= 4 and parts[0] == "site" and parts[1] == "src" and parts[2] == "content":
        return False
    return path.suffix == ".md"


def collect_targets() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(p) for p in result.stdout.splitlines() if p]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="Do not write.")
    args = ap.parse_args()

    changed: list[tuple[Path, list[str]]] = []
    for path in collect_targets():
        if not in_scope(path):
            continue
        original = path.read_text(encoding="utf-8")
        # Choose swap table based on suffix.
        swaps = list(EN_SWAPS)
        if path.name.endswith("-ko.md"):
            swaps += KO_SWAPS
        rewritten = process_text(original, swaps)
        if rewritten != original:
            hits = []
            for old, _new in swaps:
                delta = original.count(old) - rewritten.count(old)
                if delta > 0:
                    hits.append(f"{old!r} x{delta}")
            changed.append((path, hits))
            if not args.check:
                path.write_text(rewritten, encoding="utf-8")

    if args.check:
        for path, hits in changed:
            print(f"WOULD MODIFY {path}  {', '.join(hits)}")
        if changed:
            print(f"\ncheck failed: {len(changed)} file(s) would change.")
            return 1
        print("check ok: no tone gaps in scope.")
        return 0

    for path, hits in changed:
        print(f"rewrote {path}  {', '.join(hits)}")
    print(f"\ntotal: {len(changed)} file(s) rewritten.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
