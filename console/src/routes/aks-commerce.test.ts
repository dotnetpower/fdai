import { describe, expect, it } from "vitest";
import { getLocale, setLocale } from "../i18n";
import {
  aksCommerceServiceFromSearch,
  aksCommerceServiceHref,
} from "./aks-commerce";
import { sampleAksCommerce } from "./aks-commerce.sample";
import { t } from "./i18n/aks-commerce";

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

  it("round-trips service selection in URL search params and localizes signal header", () => {
    expect(aksCommerceServiceFromSearch(new URLSearchParams())).toBe("order-fulfillment");
    expect(aksCommerceServiceFromSearch(new URLSearchParams("service=catalog-browse")))
      .toBe("catalog-browse");
    expect(aksCommerceServiceFromSearch(new URLSearchParams("service=invalid")))
      .toBe("order-fulfillment");
    expect(
      aksCommerceServiceHref("catalog-browse", new URLSearchParams("data=sample")),
    ).toBe("/aks-commerce?data=sample&service=catalog-browse");
    expect(
      aksCommerceServiceHref(
        "order-fulfillment",
        new URLSearchParams("data=sample&service=catalog-browse"),
      ),
    ).toBe("/aks-commerce?data=sample");

    const previousLocale = getLocale();
    try {
      setLocale("en");
      expect(t("aksCommerce.signal")).toBe("Signal");
      setLocale("ko");
      expect(t("aksCommerce.signal")).toBe("신호");
    } finally {
      setLocale(previousLocale);
    }
  });
});
