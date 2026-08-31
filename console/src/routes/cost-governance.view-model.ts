import type { CostGovernanceProjection } from "../api-cost-governance";

export interface CostGovernanceRow {
  readonly id: string;
  readonly kind: string;
  readonly label: string;
  readonly service: string;
  readonly amount: number | null;
  readonly amountLabel: string;
  readonly currency: string;
  readonly recordCount: number;
  readonly status: string;
  readonly observedAt: string | null;
  readonly completeness: number | null;
  readonly relativeChange: number | null;
  readonly sourceAuthority: string | null;
  readonly provenanceDigest: string | null;
}

export interface CostGovernanceSummary {
  readonly rows: readonly CostGovernanceRow[];
  readonly knownTotal: number | null;
  readonly currency: string;
  readonly totalsByCurrency: Readonly<Record<string, number>>;
  readonly sourceRecordCount: number;
  readonly largestShare: number | null;
  readonly largestLabel: string | null;
}

export function summarizeCostGovernance(
  projection: CostGovernanceProjection,
): CostGovernanceSummary {
  const rows = projection.items.map((item, index) => decodeRow(item, index));
  const knownRows = rows.filter(
    (row): row is CostGovernanceRow & { readonly amount: number } => row.amount !== null,
  );
  const currencies = [...new Set(rows.map((row) => row.currency).filter(Boolean))];
  const totalsByCurrency = Object.fromEntries(
    currencies.flatMap((currency) => {
      const currencyRows = rows.filter((row) => row.currency === currency);
      if (currencyRows.some((row) => row.amount === null)) return [];
      return [[
        currency,
        currencyRows.reduce((total, row) => total + (row.amount ?? 0), 0),
      ]];
    }),
  );
  const currency = currencies.length === 1 ? currencies[0]! : "";
  const knownTotal = currency ? totalsByCurrency[currency] ?? null : null;
  const sortedRows = [...rows].sort((left, right) => {
    const currencyOrder = left.currency.localeCompare(right.currency);
    return currencyOrder !== 0 ? currencyOrder : (right.amount ?? -1) - (left.amount ?? -1);
  });
  let largestShare: number | null = null;
  let largestLabel: string | null = null;
  for (const row of knownRows) {
    const share = costShare(row, totalsByCurrency);
    if (share === null) continue;
    if (largestShare === null || share > largestShare) {
      largestShare = share;
      largestLabel = row.label;
    }
  }
  return {
    rows: sortedRows,
    knownTotal,
    currency,
    totalsByCurrency,
    sourceRecordCount: rows.reduce((total, row) => total + row.recordCount, 0),
    largestShare,
    largestLabel,
  };
}

export function costShare(
  row: CostGovernanceRow,
  totalsByCurrency: Readonly<Record<string, number>>,
): number | null {
  if (row.amount === null) return null;
  const total = totalsByCurrency[row.currency];
  return total !== undefined && total > 0 ? row.amount / total : null;
}

function decodeRow(
  item: Readonly<Record<string, unknown>>,
  index: number,
): CostGovernanceRow {
  const amountValue = item["amount_exact"] ?? item["amount_rounded"];
  const amount = numericAmount(amountValue);
  const amountLabel = amountValue === undefined
    ? stringValue(item["amount_band"]) ?? (item["suppressed"] ? "suppressed" : "-")
    : String(amountValue);
  const label = stringValue(item["resource"])
    ?? stringValue(item["group_id"])
    ?? stringValue(item["service_id"])
    ?? `record-${index + 1}`;
  return {
    id: stringValue(item["record_id"]) ?? `${label}-${index}`,
    kind: stringValue(item["kind"]) ?? "unknown",
    label,
    service: stringValue(item["service_id"]) ?? label,
    amount,
    amountLabel,
    currency: stringValue(item["currency"]) ?? "",
    recordCount: nonNegativeInteger(item["record_count"]) ?? 1,
    status: stringValue(item["status"]) ?? "observed",
    observedAt: stringValue(item["observed_at"]),
    completeness: numericAmount(item["completeness"]),
    relativeChange: numericAmount(item["relative_change"]),
    sourceAuthority: stringValue(item["source_authority"]),
    provenanceDigest: stringValue(item["provenance_digest"]),
  };
}

function numericAmount(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replaceAll(",", ""));
  return Number.isFinite(parsed) ? parsed : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}
