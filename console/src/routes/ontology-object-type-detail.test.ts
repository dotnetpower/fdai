import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import { t } from "./i18n/ontology";
import { lifecycleOwnerSummary } from "./ontology-object-type-detail";

afterEach(() => setLocale("en"));

describe("ObjectType lifecycle presentation", () => {
  it("does not present a lifecycle classification as an owner", () => {
    expect(lifecycleOwnerSummary(undefined)).toBe("No lifecycle owner declared");
    setLocale("ko");
    expect(lifecycleOwnerSummary(undefined)).toBe("선언된 수명주기 소유자 없음");
  });

  it("labels lifecycle metadata as classification in both locales", () => {
    expect(t("ontology.detail.lifecycleClassification")).toBe("Lifecycle classification");
    setLocale("ko");
    expect(t("ontology.detail.lifecycleClassification")).toBe("수명주기 분류");
  });
});
