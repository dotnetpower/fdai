import { describe, expect, it } from "vitest";
import {
  decodeDeclaredIntentGeneralTopicSummary,
  decodeDeclaredIntentReviewProjection,
  formatDeclaredIntentReviewViewModel,
} from "./declared-intent-review.model";

const DIGEST_1 = `sha256:${"1".repeat(64)}`;
const DIGEST_2 = `sha256:${"2".repeat(64)}`;
const DIGEST_3 = `sha256:${"3".repeat(64)}`;
const DIGEST_4 = `sha256:${"4".repeat(64)}`;
const DIGEST_5 = `sha256:${"5".repeat(64)}`;

const REVIEW_PAYLOAD = {
  type: "declared-intent.review-projection",
  schema_version: "1.0.0",
  read_only: true,
  authority: "none",
  execution_authority: false,
  protected_surface: true,
  general_topic_safe: false,
  action_type: "document.review-intent-diff",
  intent_digest: DIGEST_1,
  resource_id: `document-intent:${"1".repeat(64)}`,
  object_type: "BusinessService",
  operation: "update",
  expected_revision: 2,
  scope_ref: "scope:payments-prod",
  requester_ref: "principal:requester-1",
  reviewer_id: "principal:approver-1",
  independent_reviewer: true,
  source_revision: 3,
  source_digest: DIGEST_2,
  envelope_digest: DIGEST_3,
  acl_digest: DIGEST_4,
  ontology_release: DIGEST_5,
  before_properties: {
    id: "service:payments-core",
    name: "Payments Legacy",
    criticality: "tier-1",
    effective_from: "2026-01-01T00:00:00+00:00",
    effective_to: null,
    source_ref: "doc:00000000-0000-0000-0000-000000000000:00000000-0000-0000-0000-000000000000",
  },
  after_properties: {
    id: "service:payments-core",
    name: "Payments Core",
    criticality: "tier-0",
    effective_from: "2026-11-01T00:00:00+00:00",
    effective_to: "2027-11-01T00:00:00+00:00",
    source_ref: "doc:00000000-0000-0000-0000-000000000000:00000000-0000-0000-0000-000000000000",
  },
  property_changes: [
    {
      field_name: "id",
      before_value: "service:payments-core",
      after_value: "service:payments-core",
      changed: false,
    },
    {
      field_name: "name",
      before_value: "Payments Legacy",
      after_value: "Payments Core",
      changed: true,
    },
    {
      field_name: "criticality",
      before_value: "tier-1",
      after_value: "tier-0",
      changed: true,
    },
    {
      field_name: "effective_from",
      before_value: "2026-01-01T00:00:00+00:00",
      after_value: "2026-11-01T00:00:00+00:00",
      changed: true,
    },
    {
      field_name: "effective_to",
      before_value: null,
      after_value: "2027-11-01T00:00:00+00:00",
      changed: true,
    },
    {
      field_name: "source_ref",
      before_value: "doc:00000000-0000-0000-0000-000000000000:00000000-0000-0000-0000-000000000000",
      after_value: "doc:00000000-0000-0000-0000-000000000000:00000000-0000-0000-0000-000000000000",
      changed: false,
    },
  ],
} as const;

describe("declared-intent-review.model", () => {
  it("decodes protected exact-diff review projection and formats English and Korean view models", () => {
    const decoded = decodeDeclaredIntentReviewProjection(REVIEW_PAYLOAD);
    expect(decoded.read_only).toBe(true);
    expect(decoded.authority).toBe("none");
    expect(decoded.execution_authority).toBe(false);
    expect(decoded.protected_surface).toBe(true);
    expect(decoded.independent_reviewer).toBe(true);

    const enModel = formatDeclaredIntentReviewViewModel(decoded, "en");
    expect(enModel.title).toBe("Protected Declared-Intent Exact-Diff Review");
    expect(enModel.changedFieldCount).toBe(4);
    expect(enModel.unchangedFieldCount).toBe(2);
    expect(enModel.hasChanges).toBe(true);
    expect(enModel.operationLabel).toBe("Update BusinessService (rev 2)");
    expect(enModel.rows[1]?.fieldLabel).toBe("Service Name");
    expect(enModel.rows[1]?.changeBadge).toBe("Changed");
    expect(enModel.rows[4]?.beforeDisplay).toBe("(none)");

    const koModel = formatDeclaredIntentReviewViewModel(decoded, "ko");
    expect(koModel.title).toBe("보호된 선언형 의도 정밀 차분 검토");
    expect(koModel.changedFieldCount).toBe(4);
    expect(koModel.rows[1]?.fieldLabel).toBe("서비스 이름");
    expect(koModel.rows[1]?.changeBadge).toBe("변경됨");
    expect(koModel.rows[4]?.beforeDisplay).toBe("(없음)");
  });

  it("rejects authority elevation or non-protected review projection payloads", () => {
    expect(() =>
      decodeDeclaredIntentReviewProjection({
        ...REVIEW_PAYLOAD,
        authority: "execute",
      }),
    ).toThrow("authority MUST be none");

    expect(() =>
      decodeDeclaredIntentReviewProjection({
        ...REVIEW_PAYLOAD,
        execution_authority: true,
      }),
    ).toThrow("execution_authority MUST be false");

    expect(() =>
      decodeDeclaredIntentReviewProjection({
        ...REVIEW_PAYLOAD,
        property_changes: [
          REVIEW_PAYLOAD.property_changes[0],
          REVIEW_PAYLOAD.property_changes[0],
        ],
      }),
    ).toThrow(/duplicate field_name/);
  });

  it("enforces source-property privacy on general-topic summary payloads", () => {
    const summary = decodeDeclaredIntentGeneralTopicSummary({
      type: "declared-intent.general-topic-summary",
      schema_version: "1.0.0",
      read_only: true,
      authority: "none",
      execution_authority: false,
      protected_surface: false,
      general_topic_safe: true,
      discloses_source_properties: false,
      intent_digest: DIGEST_1,
      resource_id: `document-intent:${"1".repeat(64)}`,
      correlation_id: `document-intent:${"1".repeat(64)}`,
      phase: "candidate",
      producer_principal: "Norns",
      outcome: "pending",
      applied_revision: 0,
    });
    expect(summary.general_topic_safe).toBe(true);
    expect(summary.discloses_source_properties).toBe(false);

    expect(() =>
      decodeDeclaredIntentGeneralTopicSummary({
        type: "declared-intent.general-topic-summary",
        schema_version: "1.0.0",
        read_only: true,
        authority: "none",
        execution_authority: false,
        protected_surface: false,
        general_topic_safe: true,
        discloses_source_properties: false,
        intent_digest: DIGEST_1,
        resource_id: `document-intent:${"1".repeat(64)}`,
        correlation_id: `document-intent:${"1".repeat(64)}`,
        phase: "candidate",
        producer_principal: "Norns",
        outcome: "pending",
        applied_revision: 0,
        properties: { name: "Payments Core" },
      }),
    ).toThrow("MUST NOT disclose source property field properties");
  });
});
