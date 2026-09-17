import { describe, expect, it } from "vitest";
import { sampleAksCommerce } from "./aks-commerce.sample";

describe("AKS commerce sample states", () => {
  it("keeps sample mode explicitly synthetic and authority-free", () => {
    const projection = sampleAksCommerce("order-fulfillment");

    expect(projection.synthetic).toBe(true);
    expect(projection.execution_authority).toBe(false);
    expect(projection.proposed_action?.execution_authority).toBe(false);
  });

  it("keeps the catalog path distinct from order fulfillment", () => {
    const projection = sampleAksCommerce("catalog-browse");

    expect(projection.service_id).toBe("catalog-browse");
    expect(projection.dependency_path).toEqual(["storefront", "product-api"]);
    expect(projection.proposed_action).toBeNull();
  });
});
