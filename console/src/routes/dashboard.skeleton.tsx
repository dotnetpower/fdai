import { t } from "../i18n";

export function DashboardSkeleton() {
  return (
    <div class="overview-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span class="sr-only">{t("shared.loadingResource", { resource: "overview" })}</span>
      <div class="overview-skeleton-content" aria-hidden="true">
        <SkeletonSection layout="attention" blocks={3} />
        <SkeletonSection layout="distributions" blocks={2} />
        <SkeletonSection layout="metrics" blocks={4} />
      </div>
    </div>
  );
}

function SkeletonSection({
  layout,
  blocks,
}: {
  readonly layout: "metrics" | "distributions" | "attention" | "verticals";
  readonly blocks: number;
}) {
  return (
    <section class="overview-skeleton-section">
      <div class="overview-skeleton-section-head">
        <span>
          <span class="skeleton-shimmer overview-skeleton-section-heading" />
          <span class="skeleton-shimmer overview-skeleton-section-copy" />
        </span>
      </div>
      <div class={`overview-skeleton-grid is-${layout}`}>
        {Array.from({ length: blocks }, (_, index) => (
          <span key={index} class="skeleton-shimmer overview-skeleton-card" />
        ))}
      </div>
    </section>
  );
}
