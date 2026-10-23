from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "lifecycle/Dockerfile.agent"


def test_lifecycle_agent_image_is_pinned_and_non_root() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert len(re.findall(r"^ARG \w+_IMAGE=\S+@sha256:[0-9a-f]{64}$", text, re.MULTILINE)) == 2
    assert "COPY packages/service-contracts packages/service-contracts" in text
    assert "COPY packages/deployment-cli packages/deployment-cli" in text
    assert "COPY lifecycle/agent lifecycle/agent" in text
    assert "COPY . " not in text
    assert "USER 65532:65532" in text
    assert "install -d -m 0700 -o 65532 -g 65532 /config/private" in text
    assert 'ENTRYPOINT ["fdai-lifecycle-agent"]' in text
    assert "--frozen --no-dev --no-editable" in text
