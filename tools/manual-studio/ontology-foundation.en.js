import { evidenceLine, sources } from "./ontology-slide-kit.en.js";
import { foundationSlides } from "./ontology-story-foundations.en.js";
import { contractSlides } from "./ontology-story-contracts.en.js";
import { operationSlides } from "./ontology-story-operations.en.js";

/** Preserve the approved title page and compose the 39 teaching slides in order. */
export function buildOntologyFoundationDeck() {
  return [
  {
    eyebrow: "DATA & ONTOLOGY FOUNDATION",
    title: "Ontology",
    lead: "From AI language to operational meaning",
    layout: "ontology-cover",
    content: `
      <svg class="ontology-opening-art" viewBox="0 0 760 864" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="ontology-opening-stone" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#f0ebe1"/>
            <stop offset=".5" stop-color="#ded3bf"/>
            <stop offset="1" stop-color="#ede7da"/>
          </linearGradient>
          <linearGradient id="ontology-opening-light" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stop-color="#c8b99a" stop-opacity=".65"/>
            <stop offset=".5" stop-color="#fffdf8" stop-opacity=".85"/>
            <stop offset="1" stop-color="#baaa8b" stop-opacity=".5"/>
          </linearGradient>
        </defs>
        <path fill="url(#ontology-opening-stone)" d="M104 920V350a276 276 0 0 1 552 0V920H542V350a162 162 0 0 0-324 0V920Z"/>
        <g fill="none" stroke="url(#ontology-opening-light)" stroke-width="1.15">
          ${Array.from({ length: 18 }, (_, index) => {
            const left = 110 + index * 6;
            const radius = 380 - left;
            return `<path d="M${left} 920V350a${radius} ${radius} 0 0 1 ${radius * 2} 0V920"/>`;
          }).join("")}
        </g>
      </svg>
      <small class="ontology-opening-edition">ARCHITECTURE & VALIDATION / L300</small>
      ${evidenceLine([sources.ontology, sources.constitution], "FDAI Operating Ontology")}`,
  },
  ...foundationSlides(),
  ...contractSlides(),
  ...operationSlides(),
  ];
}
