from __future__ import annotations

import pytest

from fdai.core.read_investigation import classify_read_investigation_intent
from fdai.shared.providers.read_investigation import ReadInvestigationIntent


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("vm-01 is stopped; who stopped it?", ReadInvestigationIntent.CHANGE_ATTRIBUTION),
        ("vm-01을 누가 중지했어?", ReadInvestigationIntent.CHANGE_ATTRIBUTION),
        ("Show the recent Activity Log", ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY),
        ("최근 변경 이력을 보여줘", ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY),
        ("Was this a platform health event?", ReadInvestigationIntent.PLATFORM_HEALTH),
        ("플랫폼 장애나 호스트 장애였어?", ReadInvestigationIntent.PLATFORM_HEALTH),
        ("Find an OS shutdown in the event log", ReadInvestigationIntent.GUEST_SHUTDOWN),
        ("게스트 운영체제 종료 이벤트를 찾아줘", ReadInvestigationIntent.GUEST_SHUTDOWN),
        ("What is the current VM state?", ReadInvestigationIntent.RESOURCE_STATE),
        ("가상 머신 현재 상태는?", ReadInvestigationIntent.RESOURCE_STATE),
        ("Which ports are open on nsg-app?", ReadInvestigationIntent.NETWORK_SECURITY),
        ("nsg-app에서 열린 포트를 보여줘", ReadInvestigationIntent.NETWORK_SECURITY),
        ("How is vnet-hub peered?", ReadInvestigationIntent.NETWORK_PEERING),
        ("vnet-hub의 피어링 연결 상태는?", ReadInvestigationIntent.NETWORK_PEERING),
    ],
)
def test_bilingual_read_intent_routing(question: str, expected: ReadInvestigationIntent) -> None:
    assert classify_read_investigation_intent(question) is expected


def test_unrelated_or_mutating_question_abstains() -> None:
    assert classify_read_investigation_intent("Tell me a joke") is None
    assert classify_read_investigation_intent("Restart vm-01") is None
    assert classify_read_investigation_intent("Open port 22 on nsg-app") is None
    assert classify_read_investigation_intent("vnet-hub 피어링을 연결해줘") is None
