from fdai_aks_commerce import (
    load_resource_manifest,
    load_resources,
    load_scenario_profile,
    load_slo_documents,
)


def test_manifest_is_inert_canonical_and_complete() -> None:
    manifest = load_resource_manifest()
    resources = load_resources()

    assert manifest["candidate_state"] == "inert"
    assert [resource.resource_id for resource in resources] == sorted(
        resource.resource_id for resource in resources
    )
    assert {resource.kind for resource in resources} == {"profile", "slo", "workflow"}


def test_profile_declares_reviewed_business_dependency_paths() -> None:
    profile = load_scenario_profile()

    assert {service["id"] for service in profile["services"]} == {
        "catalog-browse",
        "order-fulfillment",
    }
    assert {(link["from_id"], link["link_type"], link["to_id"]) for link in profile["links"]} >= {
        ("storefront", "workload_depends_on", "order-api"),
        ("order-api", "workload_depends_on", "order-queue"),
        ("order-queue", "workload_depends_on", "order-processor"),
        ("order-processor", "workload_depends_on", "order-store"),
    }


def test_packaged_slos_pass_shared_schema() -> None:
    slos = load_slo_documents()

    assert {slo["id"] for slo in slos} == {
        "catalog-browse.availability",
        "order-fulfillment.availability",
        "order-fulfillment.freshness",
    }
