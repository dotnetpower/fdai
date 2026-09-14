import { useRef } from "preact/hooks";
import { routeHref } from "../router";
import { t } from "./i18n/ontology";
import type { OntologyView } from "./ontology.types";

const REFERENCE_VIEWS = [
  "map",
  "objects",
  "links",
  "actions",
  "topology",
] as const satisfies readonly OntologyView[];

function ontologyViewLabel(view: (typeof REFERENCE_VIEWS)[number]): string {
  return t(`ontology.common.${view}`);
}

/** Returns the canonical navigation URL for one ontology view. */
export function ontologyViewHref(view: OntologyView): string {
  return view === "instances"
    ? routeHref("ontology")
    : routeHref("ontology", { params: { view } });
}

/**
 * Keeps observed instances primary while exposing schema and topology references
 * through one native, keyboard-operable disclosure.
 */
export function OntologyNavigation({ active }: { readonly active: OntologyView }) {
  const activeReference = active === "instances" ? null : active;
  const referenceNav = useRef<HTMLDetailsElement>(null);
  const closeReferenceNav = (): void => {
    if (referenceNav.current !== null) referenceNav.current.open = false;
  };
  return (
    <nav class="ontology-view-nav" aria-label={t("ontology.navigation.label")}>
      <a
        class={`ontology-view-primary${active === "instances" ? " is-active" : ""}`}
        href={ontologyViewHref("instances")}
        aria-current={active === "instances" ? "page" : undefined}
      >
        {t("ontology.instances.title")}
      </a>
      <details
        ref={referenceNav}
        class={`ontology-reference-nav${activeReference === null ? "" : " is-active"}`}
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !event.currentTarget.open) return;
          event.preventDefault();
          closeReferenceNav();
          event.currentTarget.querySelector<HTMLElement>("summary")?.focus();
        }}
      >
        <summary>
          <span>{t("ontology.navigation.reference")}</span>
          {activeReference === null ? null : <strong>{ontologyViewLabel(activeReference)}</strong>}
          <i aria-hidden="true" />
        </summary>
        <div class="ontology-reference-links">
          {REFERENCE_VIEWS.map((view) => (
            <a
              key={view}
              href={ontologyViewHref(view)}
              class={view === active ? "is-active" : undefined}
              aria-current={view === active ? "page" : undefined}
              onClick={closeReferenceNav}
            >
              {ontologyViewLabel(view)}
            </a>
          ))}
        </div>
      </details>
    </nav>
  );
}
