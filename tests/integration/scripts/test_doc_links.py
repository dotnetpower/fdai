from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECK_LINKS = REPO_ROOT / "scripts/quality/repository/check-doc-links.sh"


def test_doc_link_gate_scans_untracked_markdown(tmp_path: Path) -> None:
    git = shutil.which("git")
    bash = shutil.which("bash")
    assert git is not None and bash is not None
    subprocess.run(  # noqa: S603 - fixed executable and test-controlled arguments
        [git, "init", "--quiet"], cwd=tmp_path, check=True
    )
    document = tmp_path / "docs" / "new.md"
    document.parent.mkdir(parents=True)
    document.write_text("# New\n\n[Missing](missing.md)\n", encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - fixed executable and repository-owned script
        [bash, str(CHECK_LINKS)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "docs/new.md -> missing.md" in result.stderr
