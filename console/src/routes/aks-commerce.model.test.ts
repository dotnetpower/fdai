import { describe, expect, it } from "vitest";
import { decodeAksCommerceProjection } from "../api-aks-commerce";
import { sampleAksCommerce } from "./aks-commerce.sample";

describe("AKS commerce projection", () => {
  it("decodes the authority-free sample contract", () => {
    const projection = decodeAksCommerceProjection(sampleAksCommerce("order-fulfillment"));

    expect(projection.status).toBe("order_backlog");
    expect(projection.execution_authority).toBe(false);
    expect(projection.owner_agent).toBe("Forseti");
    expect(projection.observer_agent).toBe("Heimdall");
  });

  it("rejects an invented success authority", () => {
    const projection = {
      ...sampleAksCommerce("catalog-browse"),
      execution_authority: true,
    };

    expect(() => decodeAksCommerceProjection(projection)).toThrow(
      "Invalid AKS commerce execution_authority",
    );
  });

  it("preserves unavailable metric values instead of converting them to zero", () => {
    const sample = sampleAksCommerce("order-fulfillment");
    const projection = decodeAksCommerceProjection({
      ...sample,
      metrics: [{
        ...sample.metrics[0],
        current: null,
        previous: null,
        state: "unavailable",
      }],
    });

    expect(projection.metrics[0]?.current).toBeNull();
    expect(projection.metrics[0]?.state).toBe("unavailable");
  });
});
