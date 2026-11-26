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


def reported_pod(**status):
    return {
        "spec": {"containers": [{"name": "app", **container("200m", "500Mi")}]},
        "status": status,
    }


def test_kubelet_reported_resources_equal_to_the_declaration_are_accepted() -> None:
    """Newer clusters fill these in for every running Pod; they match when nothing is resizing."""
    plain = pod_resource_requests(reported_pod())
    status = {
        "resources": {"requests": {"cpu": "181m", "memory": "500Mi"}},
        "containerStatuses": [
            {
                "name": "app",
                "allocatedResources": {"cpu": "200m", "memory": "500Mi"},
                "resources": {
                    "limits": {"cpu": "500m", "memory": "1Gi"},
                    "requests": {"cpu": "200m", "memory": "500Mi"},
                },
            }
        ],
    }
    assert (
        pod_resource_requests(reported_pod(**status))
        == plain
        == PodResourceRequests(200, 500 * 1024**2)
    )


@pytest.mark.parametrize(
    "statuses",
    [
        [{"name": "app", "allocatedResources": {"cpu": "400m", "memory": "500Mi"}}],
        [{"name": "app", "allocatedResources": {"cpu": "200m", "memory": "1Gi"}}],
        [{"name": "app", "resources": {"requests": {"cpu": "300m", "memory": "500Mi"}}}],
        [{"name": "app", "allocatedResources": {"cpu": "200m"}}],
        [{"name": "other", "allocatedResources": {"cpu": "200m", "memory": "500Mi"}}],
        [{"allocatedResources": {"cpu": "200m", "memory": "500Mi"}}],
        [{"name": "app", "allocatedResourcesStatus": []}],
        [{"name": "app", "allocatedResources": {"ephemeral-storage": "1Gi"}}],
    ],
)
def test_reported_resources_that_differ_or_cannot_be_matched_are_refused(statuses) -> None:
    with pytest.raises(ValueError):
        pod_resource_requests(reported_pod(containerStatuses=statuses))


def test_init_container_reports_are_matched_by_name_too() -> None:
    pod = {
        "spec": {
            "containers": [{"name": "app", **container("200m", "500Mi")}],
            "initContainers": [{"name": "init", **container("50m", "64Mi")}],
        },
        "status": {
            "initContainerStatuses": [
                {"name": "init", "allocatedResources": {"cpu": "50m", "memory": "64Mi"}}
            ]
        },
    }
    assert pod_resource_requests(pod) == PodResourceRequests(200, 500 * 1024**2)
    pod["status"]["initContainerStatuses"][0]["allocatedResources"]["cpu"] = "60m"
    with pytest.raises(ValueError):
        pod_resource_requests(pod)


def test_pod_level_status_resources_alone_do_not_hide_a_pod_level_declaration() -> None:
    pod = reported_pod(resources={"requests": {"cpu": "1"}})
    pod["spec"]["resources"] = {"requests": {"cpu": "1"}}
    with pytest.raises(ValueError):
        pod_resource_requests(pod)
