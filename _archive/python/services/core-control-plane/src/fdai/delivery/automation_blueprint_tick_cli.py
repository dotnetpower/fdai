"""One-shot automation-blueprint suggestion and review binding."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from fdai.delivery.automation_blueprint_binding import build_postgres_automation_blueprint_binding

DSN_ENV = "FDAI_AUTOMATION_BLUEPRINT_DSN"
FALLBACK_DSN_ENV = "FDAI_SCHEDULE_STORE_DSN"


@dataclass(frozen=True, slots=True)
class AutomationBlueprintTickSettings:
    dsn: str | None

    @property
    def configured(self) -> bool:
        return self.dsn is not None

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> AutomationBlueprintTickSettings:
        dsn = environ.get(DSN_ENV, "").strip() or environ.get(FALLBACK_DSN_ENV, "").strip()
        return cls(dsn=dsn.replace("postgresql+psycopg://", "postgresql://", 1) or None)


async def run_once(environ: Mapping[str, str] | None = None) -> dict[str, object]:
    source = os.environ if environ is None else environ
    settings = AutomationBlueprintTickSettings.from_environ(source)
    if not settings.configured or settings.dsn is None:
        return {"configured": False, "proposed": 0, "applied": 0, "rejected": 0}
    binding = build_postgres_automation_blueprint_binding(dsn=settings.dsn)
    summary = await binding.run_once(now=datetime.now(UTC))
    return {"configured": True, **summary}


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if arguments:
        print(json.dumps({"status": "invalid_arguments"}, sort_keys=True))
        return 2
    try:
        summary = asyncio.run(run_once())
    except (psycopg.Error, ValueError) as exc:
        print(json.dumps({"status": "retry_required", "error_kind": type(exc).__name__}))
        return 1
    print(json.dumps({"status": "completed", **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
