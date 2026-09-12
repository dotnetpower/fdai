/** Inspect painted slide layout after fonts and animations have settled. */
import { inspectTextGeometry } from "./target-architecture-text-geometry.mjs";

/** Return clipping, collision, and density findings without counting the decorative draft ribbon. */
export function inspectSlideLayout(root) {
  const measured = inspectTextGeometry(root);
  const coverDecoration = root.querySelector('.vp-cover-field[aria-hidden="true"]');
  const clippedCoverDecoration = coverDecoration && !coverDecoration.textContent.trim();
  const findings = measured.findings.filter(finding => !(
    (finding.kind === "text-clipped-by-ancestor" && finding.detail.endsWith(": DRAFT")) ||
    (clippedCoverDecoration && finding.kind === "clipped-container" &&
      finding.detail === "vp-cover-field: content exceeds its clipping box")
  ));
  const scale = root.getBoundingClientRect().width / root.offsetWidth;
  const tolerance = 1.25 * scale;
  const intersect = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left) > tolerance &&
    Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > tolerance;
  const lineCount = element => {
    const tops = new Set();
    if (!element) return 0;
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (!walker.currentNode.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(walker.currentNode);
      for (const rect of range.getClientRects()) {
        if (rect.width && rect.height) tops.add(Math.round(rect.top / scale / 4));
      }
    }
    return tops.size;
  };
  const heading = root.querySelector(".slide-copy h2");
  const lead = root.querySelector(".slide-copy > p");
  const titleLines = lineCount(heading);
  const leadLines = lineCount(lead);
  const onlyExternalConnector = card => {
    const connector = card.querySelector('.oe-bus-connector[aria-hidden="true"]');
    if (!card.matches(".oe-agent-port") || !connector || connector.textContent.trim() ||
        card.scrollWidth > card.clientWidth + 1) return false;
    const bounds = card.getBoundingClientRect();
    const inside = rect => rect.left >= bounds.left - tolerance && rect.right <= bounds.right + tolerance &&
      rect.top >= bounds.top - tolerance && rect.bottom <= bounds.bottom + tolerance;
    return [...card.children].filter(child => !child.matches('.oe-bus-connector[aria-hidden="true"]'))
      .every(child => {
        if (!inside(child.getBoundingClientRect())) return false;
        const walker = document.createTreeWalker(child, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          if (!walker.currentNode.textContent.trim()) continue;
          const range = document.createRange();
          range.selectNodeContents(walker.currentNode);
          if ([...range.getClientRects()].some(rect => rect.width && rect.height && !inside(rect))) return false;
        }
        return true;
      });
  };
  for (const card of root.querySelectorAll("article, .slide-content > section, .rm-visual:not(.rm-cover), .vp-visual, .ta-visual, .oe-visual")) {
    if (card === coverDecoration && clippedCoverDecoration) continue;
    if (!card.getBoundingClientRect().height) continue;
    if ((card.scrollHeight > card.clientHeight + 1 || card.scrollWidth > card.clientWidth + 1) &&
        !onlyExternalConnector(card)) {
      findings.push({ kind: "card-overflow", detail: `${card.className || card.parentElement.className}: ${card.textContent.trim().replace(/\s+/g, " ").slice(0, 110)}` });
    }
  }
  if (titleLines > 2) findings.push({ kind: "title-density", detail: `${titleLines} lines: ${heading.textContent}` });
  if (lead?.querySelector(".aop-cover-subtitle")) {
    for (const part of lead.querySelectorAll(".aop-cover-subtitle, .aop-cover-summary")) {
      if (lineCount(part) > 2) findings.push({ kind: "lead-density", detail: `${lineCount(part)} lines: ${part.textContent.trim()}` });
    }
  } else if (leadLines > 2 && !root.classList.contains("deck-executive-briefing")) {
    findings.push({ kind: "lead-density", detail: `${leadLines} lines: ${lead.textContent}` });
  }
  const copy = root.querySelector(".slide-copy");
  if (copy) {
    const walker = document.createTreeWalker(copy, NodeFilter.SHOW_TEXT);
    const images = [...root.querySelectorAll(".slide-content .cover-photo img")];
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const bounds = copy.getBoundingClientRect();
      for (const rect of range.getClientRects()) {
        if (!rect.width || !rect.height) continue;
        if (rect.right > bounds.right + tolerance || rect.left < bounds.left - tolerance) {
          findings.push({ kind: "copy-width", detail: node.textContent.trim().slice(0, 120) });
        }
        if (images.some(image => intersect(rect, image.getBoundingClientRect()))) {
          findings.push({ kind: "image-occludes-copy", detail: node.textContent.trim().slice(0, 120) });
        }
      }
    }
  }
  if (document.documentElement.scrollWidth > innerWidth + 1) {
    findings.push({ kind: "document-overflow", detail: String(document.documentElement.scrollWidth) });
  }
  return {
    slide: Number(root.dataset.index) + 1,
    title: heading?.textContent.trim(),
    viewport: { width: innerWidth, height: innerHeight },
    titleLines,
    leadLines,
    checkedTextRuns: measured.checkedTextRuns,
    checkedClipAncestors: measured.checkedClipAncestors,
    findings,
  };
}
