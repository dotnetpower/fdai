"""Canonical Workflow UUID references are not letter-prefixed audience identities."""

import pytest
from fdai.core.detection.alert_noise.outcomes import alert_effect_key
from fdai_service_contracts.alert_noise_base import AlertDispatchRef
from fdai_service_contracts.alert_noise_plan import AlertEffectObservation
from pydantic import TypeAdapter

from .test_outcomes import _fixture_context, _fixture_observation


@pytest.mark.parametrize("leading", list("0123456789abcdef"))
def test_all_canonical_process_uuid_prefixes_roundtrip(leading: str) -> None:
    process_id = leading + "0000000-0000-0000-0000-000000000000"
    dispatch = f"{process_id}:step:update_routing:attempt:1"
    original = _fixture_observation(_fixture_context())
    value = AlertEffectObservation.model_validate(
        {**original.model_dump(), "dispatch_ref": dispatch}
    )
    assert value.dispatch_ref == dispatch
    assert alert_effect_key(plan_digest=original.plan_digest, dispatch_ref=dispatch)


@pytest.mark.parametrize("value", ["", "ref\n", "ref/other", " ref", "ref@other", "r" * 513, 1])
def test_dispatch_identity_remains_bounded_exact_and_uncoerced(value) -> None:
    with pytest.raises(ValueError):
        TypeAdapter(AlertDispatchRef).validate_python(value)
    with pytest.raises(ValueError):
        alert_effect_key(plan_digest="sha256:" + "a" * 64, dispatch_ref=value)
