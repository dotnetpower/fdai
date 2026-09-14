"""Exact alert boundary scalars; normalization never repairs an authority claim."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BeforeValidator, ConfigDict

from fdai_service_contracts.executor_models import ContractBase


class AlertContractBase(ContractBase):
    """Frozen closed records revalidated even when a caller supplies an existing instance."""

    model_config = ConfigDict(str_strip_whitespace=False, revalidate_instances="always")


def _false(value: object) -> Literal[False]:
    if value is not False:
        raise ValueError("execution authority MUST be the JSON boolean false")
    return False


def _time(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})",
            value,
        )
        is None
        or value.endswith("-00:00")
    ):
        raise ValueError("alert time MUST be an exact aware RFC 3339 timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


FalseOnly = Annotated[Literal[False], BeforeValidator(_false)]
AlertTime = Annotated[AwareDatetime, BeforeValidator(_time)]
