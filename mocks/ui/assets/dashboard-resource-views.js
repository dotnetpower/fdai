// Bounded DOM views over a synthetic query result; state and query ownership stay in the controller.
(function () {
  "use strict";
  const { definitions, statusKey, typeNames } = window.FdaiDashboardData;
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function badge(lens, key) {
    const [label, tone, symbol] = definitions[lens][key];
    const node = element("span", "dr-status", symbol + " " + label);
    node.dataset.tone = tone;
    return node;
  }
  function create(selectResource, drillDown) {
    const map = document.getElementById("resource-honeycomb");
    const list = document.getElementById("resource-list");
    const body = document.getElementById("resource-list-body");
    const groups = document.getElementById("resource-groups");
    let signature = "";
    function render(result, state, snapshot) {
      const dense = state.effectiveDensity === "dense";
      map.classList.toggle("is-dense", dense);
      map.dataset.columns = String(dense ? state.columns : 4);
      map.hidden = state.view !== "honeycomb" || !result.matchCount;
      list.hidden = state.view !== "list" || !result.matchCount;
      groups.hidden = state.view !== "groups" || !result.matchCount;
      const focusedId = document.activeElement?.dataset.resourceId;
      const nextSignature = `${snapshot.id}:${state.view}:${dense}:${state.columns}:${result.records.map((resource) => resource.id).join(",")}`;
      if (signature !== nextSignature) {
        signature = nextSignature;
        map.replaceChildren();
        body.replaceChildren();
        const clusters = new Map();
        result.records.forEach((resource, index) => {
          if (state.view === "list") {
            const row = element("tr");
            row.dataset.resourceId = resource.id;
            ["Resource", "Type / group", "State", "Last observation"].forEach((label) => {
              const td = element("td");
              td.dataset.label = label;
              row.appendChild(td);
            });
            const button = element("button", "dr-text-link", resource.name);
            button.type = "button";
            button.setAttribute("aria-controls", "resource-inspector");
            button.addEventListener("click", () => selectResource(resource.id));
            row.children[0].appendChild(button);
            row.children[1].append(element("span", "", typeNames[resource.type]), element("small", "", `${resource.subscriptionName} / ${resource.groupName}`));
            row.children[3].textContent = resource.time ? resource.time + " KST" : "Not recorded";
            body.appendChild(row);
            return;
          }
          if (!dense && !clusters.has(resource.group)) {
            const cluster = element("section", "dr-cluster");
            cluster.setAttribute("aria-label", resource.groupName + " resources");
            const heading = element("h3", "", resource.groupName);
            const count = result.records.filter((item) => item.group === resource.group).length;
            heading.appendChild(element("span", "", count + " on page"));
            cluster.append(heading, element("div", "dr-hex-pack"));
            map.appendChild(cluster);
            clusters.set(resource.group, { pack: cluster.lastElementChild, count: 0 });
          }
          const cluster = clusters.get(resource.group);
          const pack = dense ? map : cluster.pack;
          const rowStart = dense ? index % state.columns === 0 : cluster.count++ % 4 === 0;
          if (rowStart) pack.appendChild(element("div", "dr-hex-row"));
          const cell = element("button", "dr-cell");
          cell.type = "button";
          cell.tabIndex = -1;
          cell.dataset.resourceId = resource.id;
          cell.setAttribute("aria-controls", "resource-inspector");
          const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          svg.setAttribute("viewBox", "0 0 54 62");
          svg.setAttribute("aria-hidden", "true");
          const polygon = document.createElementNS(svg.namespaceURI, "polygon");
          polygon.setAttribute("points", "27,2 52,16 52,46 27,60 2,46 2,16");
          svg.appendChild(polygon);
          cell.append(svg, element("span", "dr-cell-symbol"), element("span", "dr-cell-name", resource.short));
          cell.addEventListener("click", () => selectResource(resource.id));
          pack.lastElementChild.appendChild(cell);
        });
      }
      for (const resource of result.records) {
        const key = statusKey(resource, state.lens, snapshot);
        const [label, tone, symbol] = definitions[state.lens][key];
        const container = state.view === "list" ? body : map;
        const node = container.querySelector(`[data-resource-id="${resource.id}"]`);
        const button = state.view === "list" ? node.querySelector("button") : node;
        button.setAttribute("aria-pressed", String(state.selected === resource.id));
        if (state.view === "list") node.children[2].replaceChildren(badge(state.lens, key));
        else {
          node.dataset.state = key;
          node.dataset.tone = tone;
          node.setAttribute("aria-label", `${resource.name}, ${typeNames[resource.type]}, ${resource.groupName}, ${label}`);
          node.querySelector(".dr-cell-symbol").textContent = symbol;
        }
        const cells = [...map.querySelectorAll(".dr-cell")];
        const tabStop = cells.find((cell) => cell.dataset.resourceId === focusedId)
          || cells.find((cell) => cell.dataset.resourceId === state.selected) || cells[0];
        cells.forEach((cell) => { cell.tabIndex = cell === tabStop ? 0 : -1; });
      }
      groups.replaceChildren();
      result.groups.forEach((group) => {
        const item = element("article", "dr-group");
        item.dataset.groupId = group.key;
        item.dataset.count = String(group.count);
        const button = element("button", "dr-group-open", group.name);
        button.type = "button";
        button.addEventListener("click", () => drillDown(result.grouping, group.key));
        button.append(element("span", "", `${group.count.toLocaleString("en-US")} resources`));
        const distribution = element("div", "dr-group-distribution");
        const bar = element("div", "dr-group-bar");
        bar.setAttribute("aria-hidden", "true");
        Object.entries(group.counts).filter(([, count]) => count > 0).forEach(([key, count]) => {
          const segment = element("span");
          segment.dataset.tone = definitions[state.lens][key][1];
          segment.style.width = (100 * count / group.count) + "%";
          bar.appendChild(segment);
          const status = badge(state.lens, key);
          status.append(document.createTextNode(" " + count.toLocaleString("en-US")));
          status.dataset.state = key;
          status.dataset.count = String(count);
          distribution.appendChild(status);
        });
        item.append(button, bar, distribution);
        groups.appendChild(item);
      });
    }
    map.addEventListener("focusin", (event) => {
      if (!event.target.matches(".dr-cell")) return;
      map.querySelectorAll(".dr-cell").forEach((cell) => { cell.tabIndex = cell === event.target ? 0 : -1; });
    });
    map.addEventListener("keydown", (event) => {
      const columns = Number(map.dataset.columns);
      const directions = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns, ArrowUp: -columns, Home: -Infinity, End: Infinity };
      if (!(event.key in directions) || !event.target.matches(".dr-cell")) return;
      event.preventDefault();
      const cells = [...map.querySelectorAll(".dr-cell")];
      const next = Math.max(0, Math.min(cells.length - 1, cells.indexOf(event.target) + directions[event.key]));
      cells[next].focus();
    });
    return { render };
  }
  window.FdaiDashboardViews = Object.freeze({ create, element, badge });
})();
