/** Measure owned graph edges and briefing sequence connectors on a painted, uniformly scaled slide. */
export function inspectSlideConnectors(root) {
  const scale = root.getBoundingClientRect().width / root.offsetWidth;
  const findings = [];
  let checked = 0;
  let maximumGapPx = 0;
  const box = element => element.getBoundingClientRect();
  const record = (name, gap, aligned = true) => {
    checked += 1;
    maximumGapPx = Math.max(maximumGapPx, gap / scale);
    if (gap / scale > 1 || !aligned) findings.push({ kind: "detached-connector", detail: `${name}: ${(gap / scale).toFixed(3)}px, aligned=${aligned}` });
  };
  const pair = (link, from, to, direction = "right") => {
    if (!from || !to) {
      findings.push({ kind: "connector-node-missing", detail: link.className });
      return;
    }
    const a = box(from), b = box(to), edge = box(link);
    if (!edge.width || !edge.height) return;
    const vertical = direction === "up" || direction === "down";
    const gap = direction === "left" ? Math.max(Math.abs(edge.right - a.left), Math.abs(edge.left - b.right))
      : direction === "down" ? Math.max(Math.abs(edge.top - a.bottom), Math.abs(edge.bottom - b.top))
        : direction === "up" ? Math.max(Math.abs(edge.bottom - a.top), Math.abs(edge.top - b.bottom))
          : Math.max(Math.abs(edge.left - a.right), Math.abs(edge.right - b.left));
    const aligned = vertical
      ? edge.left >= Math.max(a.left, b.left) - scale && edge.right <= Math.min(a.right, b.right) + scale
      : edge.top >= Math.max(a.top, b.top) - scale && edge.bottom <= Math.min(a.bottom, b.bottom) + scale;
    record(link.className, gap, aligned);
  };
  for (const prefix of ["ta", "rm", "vp"]) {
    for (const link of root.querySelectorAll(`[data-${prefix}-link]`)) {
      pair(link,
        root.querySelector(`[data-${prefix}-node="${link.getAttribute(`data-${prefix}-from`)}"]`),
        root.querySelector(`[data-${prefix}-node="${link.getAttribute(`data-${prefix}-to`)}"]`),
        link.getAttribute(`data-${prefix}-direction`) || "right");
    }
  }
  for (const graph of root.querySelectorAll(".rm-path, .rm-graph")) {
    for (const link of graph.querySelectorAll(".rm-link[data-rm-from][data-rm-to]")) {
      const line = link.querySelector("i");
      if (!line) {
        findings.push({ kind: "connector-line-missing", detail: link.className });
        continue;
      }
      pair(line,
        graph.querySelector(`[data-rm-node="${link.dataset.rmFrom}"]`),
        graph.querySelector(`[data-rm-node="${link.dataset.rmTo}"]`),
        link.dataset.rmDirection || "right");
    }
  }
  for (const link of root.querySelectorAll([
    ".identity-flow > i", ".architecture-map > i", ".manual-evidence-chain .journey > i",
    ".manual-timeline > i", ".executive-readiness-tree > i", ".executive-adoption-path > i",
    ".sre-agent-lane > i", ".sre-verification-ledger > i",
  ].join(","))) {
    pair(link, link.previousElementSibling, link.nextElementSibling);
  }
  const bus = root.querySelector(".oe-pubsub-bus");
  if (bus) for (const link of root.querySelectorAll(".oe-bus-connector")) {
    pair(link, link.parentElement, bus, link.closest(".oe-pubsub-top") ? "down" : "up");
  }
  for (const [name, from, to] of [
    ["customer-link", "customer", "service"], ["service-link", "service", "dependency"],
    ["data-link", "dependency", "data"], ["primary-link", "primary", "gate"],
    ["secondary-link", "secondary", "gate"],
  ]) {
    const link = root.querySelector(`.sre-service-map .${name}, .sre-failover-architecture .${name}`);
    if (link) pair(link, root.querySelector(`.${from}`), root.querySelector(`.${to}`));
  }
  for (const region of ["primary", "secondary"]) {
    const link = root.querySelector(`.inbound-${region}`);
    if (link) {
      const edge = box(link), node = box(root.querySelector(`.sre-failover-architecture .${region}`));
      record(`inbound-${region}`, Math.abs(edge.right - node.left), edge.top >= node.top && edge.bottom <= node.bottom);
    }
  }
  return { checkedConnectors: checked, maximumGapPx, findings };
}
