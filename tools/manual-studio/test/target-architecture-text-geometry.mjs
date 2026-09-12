/** Check painted text, including accessible-hidden labels, against every clipping ancestor. */
export function inspectTextGeometry(root) {
  const rootBox = root.getBoundingClientRect();
  const scale = rootBox.width / root.offsetWidth;
  const tolerance = 1.25 * scale;
  const findings = new Map();
  const runs = [];
  const clippingAncestors = new Set();
  const describe = (element) => element.dataset.taNode || element.id ||
    String(element.className || element.tagName).slice(0, 80);
  const add = (kind, detail) => findings.set(`${kind}:${detail}`, { kind, detail });
  const visible = (element) => {
    for (let current = element; current; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
      if (current === root) break;
    }
    return true;
  };

  for (const element of root.querySelectorAll("*")) {
    if (element.matches("script, style, svg, svg *") || !visible(element)) continue;
    const elementStyle = getComputedStyle(element);
    const clipsWidth = /^(hidden|clip|auto|scroll)$/.test(elementStyle.overflowX);
    const clipsHeight = /^(hidden|clip|auto|scroll)$/.test(elementStyle.overflowY);
    if ((clipsWidth && element.scrollWidth > element.clientWidth + 1) ||
        (clipsHeight && element.scrollHeight > element.clientHeight + 1)) {
      add("clipped-container", `${describe(element)}: content exceeds its clipping box`);
    }
    if (parseFloat(elementStyle.fontSize) === 0) continue;
    for (const node of element.childNodes) {
      if (node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const text = node.textContent.trim().replace(/\s+/g, " ").slice(0, 90);
      for (const rect of range.getClientRects()) {
        if (rect.width === 0 || rect.height === 0) continue;
        runs.push({ element, rect, text });
        for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
          const style = getComputedStyle(ancestor);
          const clipsX = /^(hidden|clip|auto|scroll)$/.test(style.overflowX);
          const clipsY = /^(hidden|clip|auto|scroll)$/.test(style.overflowY);
          if (clipsX || clipsY) {
            clippingAncestors.add(ancestor);
            const bounds = ancestor.getBoundingClientRect();
            const left = bounds.left + parseFloat(style.borderLeftWidth) * scale;
            const right = bounds.right - parseFloat(style.borderRightWidth) * scale;
            const top = bounds.top + parseFloat(style.borderTopWidth) * scale;
            const bottom = bounds.bottom - parseFloat(style.borderBottomWidth) * scale;
            if ((clipsX && (rect.left < left - tolerance || rect.right > right + tolerance)) ||
                (clipsY && (rect.top < top - tolerance || rect.bottom > bottom + tolerance))) {
              add("text-clipped-by-ancestor", `${describe(ancestor)}: ${text}`);
            }
          }
          if (ancestor === root) break;
        }
      }
    }
  }
  if (!runs.length || !(scale > 0)) add("unpainted-slide", "No visible text was measured.");

  for (let first = 0; first < runs.length; first += 1) {
    const a = runs[first];
    if (a.element.closest(".manual-draft-overlay")) continue;
    for (let second = first + 1; second < runs.length; second += 1) {
      const b = runs[second];
      if (a.element.contains(b.element) || b.element.contains(a.element) ||
          b.element.closest(".manual-draft-overlay")) continue;
      const width = Math.min(a.rect.right, b.rect.right) - Math.max(a.rect.left, b.rect.left);
      const height = Math.min(a.rect.bottom, b.rect.bottom) - Math.max(a.rect.top, b.rect.top);
      if (width > tolerance && height > tolerance) add("painted-text-overlap", `${a.text} / ${b.text}`);
    }
  }
  return { checkedTextRuns: runs.length, checkedClipAncestors: clippingAncestors.size, findings: [...findings.values()] };
}

/** Prove the checker rejects clipped nested text and aria-hidden label collisions at three scales. */
export async function verifyTextGeometry(page) {
  await page.setContent(`<!doctype html><html><head><style>
    * { box-sizing: border-box; }
    #fixture { position: relative; width: 640px; height: 400px; transform-origin: top left; font: 20px/24px sans-serif; }
    #nested { width: 300px; height: 34px; overflow: hidden; }
    #nested > div { display: grid; gap: 12px; }
    #horizontal { width: 100px; overflow: hidden; white-space: nowrap; margin-top: 40px; }
    #collision { position: relative; margin-top: 40px; height: 40px; }
    #collision > span { position: absolute; top: 0; left: 0; }
    #hidden { display: none; }
    #fixture.clean #nested { height: 100px; }
    #fixture.clean #horizontal { width: 400px; }
    #fixture.clean #collision > span:last-child { left: 320px; }
  </style></head><body><main id="fixture">
    <section id="nested"><div><span>visible row</span><span>clipped final row</span></div></section>
    <section id="horizontal"><span>a long boundary heading</span></section>
    <section id="collision"><span>node heading</span><span aria-hidden="true">edge label</span></section>
    <section id="hidden"><span>not painted</span><span>not painted</span></section>
  </main></body></html>`);
  const fixture = page.locator("#fixture");
  const results = [];
  for (const scale of [1, .65, .22]) {
    await fixture.evaluate((element, value) => {
      element.className = "";
      element.style.transform = `scale(${value})`;
    }, scale);
    const broken = await fixture.evaluate(inspectTextGeometry);
    const expected = [
      ["clipped-container", "nested: content exceeds its clipping box"],
      ["text-clipped-by-ancestor", "nested: clipped final row"],
      ["text-clipped-by-ancestor", "horizontal: a long boundary heading"],
      ["painted-text-overlap", "node heading / edge label"],
    ];
    for (const [kind, detail] of expected) {
      if (!broken.findings.some((finding) => finding.kind === kind && finding.detail === detail)) {
        throw new Error(`Text geometry missed the ${kind} fixture at scale ${scale}.`);
      }
    }
    await fixture.evaluate((element) => { element.className = "clean"; });
    const clean = await fixture.evaluate(inspectTextGeometry);
    if (clean.findings.length) throw new Error(`Clean text geometry fixture failed: ${JSON.stringify(clean.findings)}`);
    results.push({ scale, detectedFailures: expected.length, cleanFindings: 0 });
  }
  await fixture.evaluate((element) => { element.style.opacity = "0"; });
  const hidden = await fixture.evaluate(inspectTextGeometry);
  if (!hidden.findings.some((finding) => finding.kind === "unpainted-slide")) {
    throw new Error("Text geometry accepted an invisible slide.");
  }
  return results;
}
