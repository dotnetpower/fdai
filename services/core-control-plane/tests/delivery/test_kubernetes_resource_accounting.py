"""Conservative resource sums consume the shared quantity boundary."""

from copy import deepcopy
from decimal import localcontext

import pytest
from fdai.delivery.kubernetes_quantity import MAX_RESOURCE_QUANTITY
from fdai.delivery.kubernetes_resource_accounting import PodResourceRequests, pod_resource_requests


def container(cpu="100m", memory="128Mi"):
    return {"resources": {"requests": {"cpu": cpu, "memory": memory}}}


def test_init_maximum_is_per_resource_and_overhead_is_added_once() -> None:
    pod = {
        "spec": {
            "containers": [container(), container()],
            "initContainers": [container("500m", "64Mi"), container("1m", "512Mi")],
            "overhead": {"cpu": "25m", "memory": "16Mi"},
        }
    }
    original = deepcopy(pod)
    with localcontext() as active:
        active.prec = 2
        result = pod_resource_requests(pod)
    assert result == PodResourceRequests(525, 528 * 1024**2)
    assert pod == original


def test_app_sum_can_exceed_each_init_request() -> None:
    pod = {"spec": {"containers": [container(), container()], "initContainers": [container()]}}
    assert pod_resource_requests(pod) == PodResourceRequests(200, 256 * 1024**2)


def test_limits_default_only_absent_requests_never_explicit_zero() -> None:
    pod = {
        "spec": {
            "containers": [
                {
                    "resources": {
                        "requests": {"cpu": "0"},
                        "limits": {"cpu": "1", "memory": "256Mi"},
                    }
                },
                {},
            ]
        }
    }
    assert pod_resource_requests(pod) == PodResourceRequests(0, 256 * 1024**2)


def test_fractional_units_round_up_conservatively() -> None:
    assert pod_resource_requests(
        {"spec": {"containers": [container("1n", "400m")]}}
    ) == PodResourceRequests(1, 1)


@pytest.mark.parametrize(
    "spec",
    [
        None,
        {},
        {"containers": []},
        {"containers": None},
        {"containers": [None]},
        {"containers": [{}] * 513},
        {"containers": [{}], "initContainers": "invalid"},
        {"containers": [{}], "resources": {}},
        {"containers": [{"resources": None}]},
        {"containers": [{"resources": {"requests": {"cpu": None}}}]},
        {"containers": [{"resources": {"limits": {"memory": "Infinity"}}}]},
        {"containers": [{"resources": {"requests": {"cpu": "bad"}, "limits": {"cpu": "1"}}}]},
        {"containers": [{"resources": {"requests": {"example.com/device": "1"}}}]},
        {"containers": [{"resources": {"claims": []}}]},
        {"containers": [{"resizePolicy": []}]},
        {"containers": [{}], "initContainers": [{"restartPolicy": "Always"}]},
        {"containers": [{}], "overhead": {"memory": "-1"}},
        {"containers": [{}], "overhead": {"ephemeral-storage": "1Gi"}},
        {"containers": [container(memory=MAX_RESOURCE_QUANTITY), container()]},
    ],
)
def test_unsupported_or_malformed_input_is_not_silently_omitted(spec) -> None:
    with pytest.raises(ValueError):
        pod_resource_requests({"spec": spec})


@pytest.mark.parametrize(
    "status",
    [
        None,
        {"resize": "InProgress"},
        {"resources": {}},
        {"containerStatuses": [{"allocatedResources": {"cpu": "2"}}]},
        {"initContainerStatuses": [{"resources": {}}]},
        {"containerStatuses": [{"allocatedResourcesStatus": []}]},
        {"containerStatuses": [None]},
        {"conditions": "invalid"},
        {"conditions": [{"type": []}]},
        {"conditions": [{}]},
        {"conditions": [{"type": "PodResizePending", "status": "True"}]},
        {"conditions": [{"type": "PodResizeInProgress", "status": "True"}]},
    ],
)
def test_resize_or_malformed_status_withholds_accounting(status) -> None:
    with pytest.raises(ValueError):
        pod_resource_requests({"spec": {"containers": [container()]}, "status": status})
