/* Synthetic LLM usage exploration only; no provider access or billing inference. */
(() => {
  "use strict";
  const root = document.getElementById("llm-cost-main");
  const byId = (id) => document.getElementById(id);
  const number = new Intl.NumberFormat("en-US");
  const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
  const displayDate = (date) => new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(date);
  const sum = (trend, key) => trend.reduce((total, row) => total + row[key], 0);
  const dayMs = 86400000;
  const sevenDayTrend = [
    { date: "Jul 29, 2026", input: 148000, output: 12000 },
    { date: "Jul 30, 2026", input: 172000, output: 16000 },
    { date: "Jul 31, 2026", input: 184000, output: 17000 },
    { date: "Aug 1, 2026", input: 165000, output: 14000 },
    { date: "Aug 2, 2026", input: 132000, output: 11000 },
    { date: "Aug 3, 2026", input: 156000, output: 13000 },
    { date: "Aug 4, 2026", input: 201000, output: 19000 },
  ];
  const twentyFourHourTrend = [
    { date: "Aug 3, 2026, 18:00 UTC", short: "18:00", input: 20000, output: 1500 },
    { date: "Aug 3, 2026, 22:00 UTC", short: "22:00", input: 24000, output: 2000 },
    { date: "Aug 4, 2026, 02:00 UTC", short: "02:00", input: 31000, output: 2400 },
    { date: "Aug 4, 2026, 06:00 UTC", short: "06:00", input: 27000, output: 2100 },
    { date: "Aug 4, 2026, 10:00 UTC", short: "10:00", input: 33000, output: 2700 },
    { date: "Aug 4, 2026, 14:00 UTC", short: "14:00", input: 33000, output: 3300 },
  ];
  // Preserve the original deterministic layout fixtures, not a historical measurement series.
  const buildDailyTrend = (start, count) => Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.parse(`${start}T00:00:00Z`) + index * dayMs);
    return { date: `${displayDate(date)}, ${date.getUTCFullYear()}`, short: displayDate(date),
      input: 128000 + ((index * 37000) % 78000), output: 10000 + ((index * 7000) % 11000) };
  });
  const presets = {
    "24h": { label: "Aug 3, 15:00 - Aug 4, 15:00, 2026", title: "24-hour token trend", subtitle: "Synthetic input and output tokens by four-hour interval.", totalLabel: "24-hour total", calls: 263, chatShare: .28, from: "2026-08-03", to: "2026-08-04", trend: twentyFourHourTrend },
    "7d": { label: "Jul 29 - Aug 4, 2026", title: "7-day token trend", subtitle: "Daily synthetic input and output tokens.", totalLabel: "7-day total", calls: 1842, chatShare: .27, from: "2026-07-29", to: "2026-08-04", trend: sevenDayTrend },
    "30d": { label: "Jul 6 - Aug 4, 2026", title: "30-day token trend", subtitle: "Daily synthetic input and output tokens.", totalLabel: "30-day total", calls: 7934, chatShare: .27, from: "2026-07-06", to: "2026-08-04", trend: buildDailyTrend("2026-07-06", 30) },
  };
  const defaultState = () => ({ version: 1, range: "7d", from: "", to: "" });
  let committed = defaultState();
  const validDate = (value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
  const validDates = (from, to) => validDate(from) && validDate(to) && from >= "2026-05-07" &&
    to <= "2026-08-04" && from <= to && (Date.parse(to) - Date.parse(from)) / dayMs < 90;
  const validState = (state) => state && typeof state === "object" && !Array.isArray(state) &&
    Object.keys(state).sort().join(",") === "from,range,to,version" && state.version === 1 && typeof state.range === "string" &&
    (state.range === "custom" ? validDates(state.from, state.to) :
      Object.hasOwn(presets, state.range) && state.from === "" && state.to === "");
  const rangeFor = (state) => {
    if (state.range !== "custom") return presets[state.range];
    const start = new Date(`${state.from}T00:00:00Z`);
    const end = new Date(`${state.to}T00:00:00Z`);
    const count = Math.round((end - start) / dayMs) + 1;
    const trend = buildDailyTrend(state.from, count);
    return { label: `${displayDate(start)} - ${displayDate(end)}, ${end.getUTCFullYear()}`, title: `${count}-day token trend`,
      subtitle: "Daily synthetic input and output tokens.", totalLabel: `${count}-day total`,
      calls: Math.max(1, Math.round((sum(trend, "input") + sum(trend, "output")) / 684)), chatShare: .27,
      from: state.from, to: state.to, trend };
  };
  const stateError = (message) => {
    byId("range-state-error").textContent = message;
    byId("range-state-error").hidden = !message;
  };
  const allocate = (total, weights) => {
    const weightTotal = weights.reduce((value, weight) => value + weight, 0);
    let allocated = 0;
    return weights.map((weight, index) => {
      const value = index === weights.length - 1 ? total - allocated : Math.round(total * weight / weightTotal);
      allocated += value;
      return value;
    });
  };
  const rowsFor = (selector) => [...root.querySelectorAll(selector)];
  const modelRows = rowsFor(".lc-model-usage tbody tr");
  const updateModelUsage = (range, input, output) => {
    const chatCalls = Math.round(range.calls * range.chatShare);
    const chatInput = Math.round(input * range.chatShare);
    const chatOutput = Math.round((input + output) * range.chatShare) - chatInput;
    for (const scope of ["control", "chat"]) {
      const rows = modelRows.filter((row) => (row.dataset.modelScope === "chat") === (scope === "chat"));
      const calls = allocate(scope === "chat" ? chatCalls : range.calls - chatCalls, rows.map((row) => Number(row.querySelector(".model-calls").dataset.base)));
      const inputs = allocate(scope === "chat" ? chatInput : input - chatInput, rows.map((row) => Number(row.querySelector(".model-input").dataset.base)));
      const outputs = allocate(scope === "chat" ? chatOutput : output - chatOutput, rows.map((row) => Number(row.querySelector(".model-output").dataset.base)));
      rows.forEach((row, index) => {
        for (const [key, value] of Object.entries({ calls: calls[index], input: inputs[index], output: outputs[index], total: inputs[index] + outputs[index] })) {
          row.querySelector(`.model-${key}`).textContent = number.format(value);
        }
      });
    }
  };
  const updateRollup = (selector, weights, calls, input, output) => {
    const values = { calls: allocate(calls, weights), input: allocate(input, weights), output: allocate(output, weights) };
    rowsFor(selector).forEach((row, index) => {
      for (const key of ["calls", "input", "output", "total"]) {
        row.querySelector(`.${key}`).textContent = number.format(key === "total" ? values.input[index] + values.output[index] : values[key][index]);
      }
    });
  };
  const updateCalendarRollups = (range) => {
    const daily = new Map();
    const counts = allocate(range.calls, range.trend.map((row) => row.input + row.output));
    range.trend.forEach((row, index) => {
      const key = new Date(`${row.date.split(", ").slice(0, 2).join(", ")} 00:00:00 UTC`).toISOString().slice(0, 10);
      const item = daily.get(key) || { calls: 0, input: 0, output: 0 };
      item.calls += counts[index]; item.input += row.input; item.output += row.output;
      daily.set(key, item);
    });
    const monthly = new Map();
    for (const [day, value] of daily) {
      const month = day.slice(0, 7);
      const item = monthly.get(month) || { calls: 0, input: 0, output: 0 };
      item.calls += value.calls; item.input += value.input; item.output += value.output;
      monthly.set(month, item);
    }
    for (const [id, rows] of [["daily-rollup", daily], ["monthly-rollup", monthly]]) {
      byId(id).replaceChildren(...[...rows].map(([key, row]) => {
        const tr = document.createElement("tr");
        for (const value of [key, row.calls, row.input, row.output, row.input + row.output]) {
          const cell = document.createElement("td");
          cell.textContent = typeof value === "number" ? number.format(value) : value;
          if (typeof value === "number") cell.className = "num";
          tr.append(cell);
        }
        return tr;
      }));
    }
  };
  const chart = root.querySelector(".lc-chart");
  const pointsGroup = byId("token-points");
  const tooltip = byId("token-tooltip");
  const guide = byId("token-guide");
  const hideTooltip = () => {
    tooltip.classList.remove("is-visible");
    tooltip.textContent = "Focus or hover a chart point to inspect its exact token values.";
    guide.classList.remove("is-visible");
    pointsGroup.querySelectorAll(".point").forEach((point) => point.classList.remove("is-active"));
  };
  const svgNode = (name, attributes) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  };
  const renderTrend = (trend) => {
    const highest = Math.max(...trend.map((row) => row.input + row.output));
    const rough = highest / 3;
    const power = 10 ** Math.floor(Math.log10(rough));
    const normalized = rough / power;
    const step = (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10) * power;
    const width = Math.max(640, 52 * trend.length + 92);
    const x = (index) => trend.length === 1 ? width / 2 : 46 + index / (trend.length - 1) * (width - 76);
    const y = (value) => 166 - value / (step * 3) * 154;
    chart.setAttribute("viewBox", `0 0 ${width} 218`);
    byId("token-trend").style.minWidth = `${width}px`;
    byId("token-grid").replaceChildren();
    pointsGroup.replaceChildren();
    byId("trend-labels").replaceChildren();
    hideTooltip();
    for (const value of [0, step, step * 2, step * 3]) {
      const line = svgNode("line", { class: "grid", x1: 46, x2: width - 30, y1: y(value), y2: y(value) });
      const label = svgNode("text", { class: "axis-label", x: 38, y: y(value) + 4, "text-anchor": "end" });
      label.textContent = compact.format(value);
      byId("token-grid").append(line, label);
    }
    const coordinates = trend.map((row, index) => [x(index), y(row.input + row.output)]);
    byId("token-line").setAttribute("d", coordinates.map(([px, py], index) => `${index ? "L" : "M"}${px} ${py}`).join(" "));
    byId("token-area").setAttribute("d", `M${x(0)} 166 ${coordinates.map(([px, py]) => `L${px} ${py}`).join(" ")} L${x(trend.length - 1)} 166 Z`);
    const hits = [];
    trend.forEach((row, index) => {
      const total = row.input + row.output;
      const point = svgNode("circle", { class: "point", cx: x(index), cy: y(total), r: 3.5, "aria-hidden": "true" });
      const hit = svgNode("rect", { class: "hit", id: `llm-token-point-${index}`, x: x(index) - 22, y: y(total) - 22, width: 44, height: 44,
        tabindex: index === 0 ? 0 : -1, role: "button",
        "aria-label": `${row.date}${row.date.includes("UTC") ? "" : " UTC"}: ${number.format(row.input)} input, ${number.format(row.output)} output, ${number.format(total)} total tokens`,
        "aria-describedby": "chart-help" });
      const show = () => {
        tooltip.innerHTML = `<strong>${row.date}${row.date.includes("UTC") ? "" : " UTC"}</strong>` +
          [["Input", row.input], ["Output", row.output], ["Total", total]].map(([label, value]) =>
            `<span class="lc-tooltip-row"><span>${label}</span><b>${number.format(value)} tokens</b></span>`).join("");
        tooltip.classList.add("is-visible");
        guide.setAttribute("x1", x(index)); guide.setAttribute("x2", x(index));
        guide.classList.add("is-visible");
        pointsGroup.querySelectorAll(".point").forEach((candidate) => candidate.classList.toggle("is-active", candidate === point));
      };
      hit.addEventListener("mouseenter", show);
      hit.addEventListener("click", show);
      hit.addEventListener("focus", () => {
        hits.forEach((candidate) => candidate.setAttribute("tabindex", candidate === hit ? "0" : "-1"));
        show();
      });
      hit.addEventListener("blur", hideTooltip);
      hit.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { event.preventDefault(); hideTooltip(); return; }
        if (["Enter", " "].includes(event.key)) { event.preventDefault(); show(); return; }
        const target = ({ ArrowRight: index + 1, ArrowDown: index + 1, ArrowLeft: index - 1, ArrowUp: index - 1, Home: 0, End: trend.length - 1 })[event.key];
        if (target !== undefined) {
          event.preventDefault();
          hits[Math.max(0, Math.min(trend.length - 1, target))].focus();
        }
      });
      hits.push(hit); pointsGroup.append(hit, point);
      const label = svgNode("text", { class: "axis-label", x: x(index), y: 206, "text-anchor": "middle" });
      label.textContent = row.short ?? row.date.replace(", 2026", "");
      if (trend.length <= 7 || index % 2 === 0 || index === trend.length - 1) byId("trend-labels").append(label);
    });
  };
  const ledgerRows = rowsFor(".lc-ledger-table tbody tr");
  const visibleLedgerRows = () => ledgerRows.filter((row) => !row.hidden);
  const updateLedger = (range, rangeKey) => {
    // Never move a frozen correlation's timestamp to manufacture an in-range record.
    const from = Date.parse(`${range.from}T${rangeKey === "24h" ? "15:00:00" : "00:00:00"}Z`);
    const until = Date.parse(`${range.to}T${rangeKey === "24h" ? "15:00:00" : "23:59:59.999"}Z`);
    ledgerRows.forEach((row) => {
      const occurred = Date.parse(row.querySelector("time").dateTime);
      row.hidden = occurred < from || occurred > until;
    });
    const visible = visibleLedgerRows();
    byId("ledger-note").textContent = `Showing ${visible.length} of ${number.format(range.calls)} synthetic calls. Truncated subset; CSV exports only these ${visible.length} visible records.`;
    byId("ledger-empty").hidden = visible.length !== 0;
    byId("export-invocations").disabled = visible.length === 0;
    byId("export-status").textContent = "";
    byId("kpi-latest-time").textContent = visible.length ? "14:32 UTC" : "Unavailable";
    byId("kpi-latest-date").textContent = visible.length ? "Aug 4, 2026" : "No ledger examples in range";
    const correlations = new Set(visible.map((row) => row.cells[8].textContent.trim()));
    rowsFor("#conversation-rollup tr").forEach((row) => { row.hidden = !correlations.has(row.cells[0].textContent.trim()); });
    const count = rowsFor("#conversation-rollup tr").filter((row) => !row.hidden).length;
    byId("conversation-note").textContent = count ? "2 illustrative conversation rows. A truncated subset, not the workload total." : "No conversation examples in this range. This is missing detail, not zero chat usage.";
  };
  const renderRange = () => {
    const range = rangeFor(committed);
    const input = sum(range.trend, "input"), output = sum(range.trend, "output"), total = input + output;
    const chatTokens = Math.round(total * range.chatShare);
    const text = { "active-range": range.label, "kpi-calls": number.format(range.calls), "kpi-total": compact.format(total),
      "kpi-chat-share": `${Math.round(range.chatShare * 100)}%`, "kpi-chat-tokens": `${compact.format(chatTokens)} chat tokens`,
      "input-tokens": number.format(input), "output-tokens": number.format(output),
      "input-share": `${(100 * input / total).toFixed(1)}%`, "output-share": `${(100 * output / total).toFixed(1)}%`,
      "trend-title": range.title, "trend-subtitle": range.subtitle, "trend-total-label": range.totalLabel, "trend-total": compact.format(total),
      "usage-evidence": `Source: synthetic-dev / Example scope / Fixed reference 2026-08-04T15:00:00Z / ${number.format(range.calls)} fixture calls / Not a live freshness claim.` };
    for (const [id, value] of Object.entries(text)) byId(id).textContent = value;
    root.querySelector(".lc-token-mix .is-input").style.flex = input;
    root.querySelector(".lc-token-mix .is-output").style.flex = output;
    updateModelUsage(range, input, output);
    updateLedger(range, committed.range);
    updateRollup(".rollup-workload", [1 - range.chatShare, range.chatShare], range.calls, input, output);
    rowsFor(".rollup-workload").forEach((row, index) => {
      const models = modelRows.filter((model) => (model.dataset.modelScope === "chat") === (index === 1));
      for (const key of ["calls", "input", "output", "total"]) {
        row.querySelector(`.${key}`).textContent = number.format(models.reduce((value, model) =>
          value + Number(model.querySelector(`.model-${key}`).textContent.replaceAll(",", "")), 0));
      }
    });
    updateRollup(".rollup-mode", [.91, .09], range.calls, input, output);
    updateRollup(".rollup-chat", [.62, .38], Math.round(range.calls * range.chatShare), Math.round(input * range.chatShare), chatTokens - Math.round(input * range.chatShare));
    renderTrend(range.trend);
    updateCalendarRollups(range);
    rowsFor(".lc-range-option").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.range === committed.range);
      button.setAttribute("aria-pressed", String(button.dataset.range === committed.range));
    });
  };
  const clearErrors = () => {
    byId("range-error").textContent = "";
    for (const id of ["range-start", "range-end"]) byId(id).removeAttribute("aria-invalid");
  };
  const closeCustom = (restoreFocus = false) => {
    byId("custom-range").hidden = true;
    byId("range-custom").setAttribute("aria-expanded", "false");
    clearErrors();
    if (restoreFocus) byId("range-custom").focus();
  };
  const commit = (state) => {
    committed = state;
    stateError("");
    renderRange();
    const url = new URL(location.href);
    for (const key of ["range", "from", "to"]) url.searchParams.delete(key);
    if (state.range === "custom") { url.searchParams.set("from", state.from); url.searchParams.set("to", state.to); }
    else url.searchParams.set("range", state.range);
    history.replaceState(history.state, "", url);
    root.dispatchEvent(new Event("fdai-preview-state-change"));
    window.fdaiPublishMockRoute?.();
  };
  rowsFor(".lc-range-option").forEach((button) => button.addEventListener("click", () => {
    if (button.dataset.range === "custom") {
      const range = rangeFor(committed);
      byId("range-start").value = range.from; byId("range-end").value = range.to;
      clearErrors(); byId("custom-range").hidden = false;
      button.setAttribute("aria-expanded", "true"); byId("range-start").focus();
    } else { closeCustom(); commit({ version: 1, range: button.dataset.range, from: "", to: "" }); }
  }));
  byId("range-cancel").addEventListener("click", () => closeCustom(true));
  byId("custom-range").addEventListener("submit", (event) => {
    event.preventDefault();
    const from = byId("range-start").value, to = byId("range-end").value;
    clearErrors();
    if (!validDates(from, to)) {
      byId("range-error").textContent = "Choose 1 to 90 days within May 7 to August 4, 2026. The end date must not precede the start date.";
      for (const id of ["range-start", "range-end"]) byId(id).setAttribute("aria-invalid", "true");
      byId(!byId("range-start").checkValidity() ? "range-start" : "range-end").focus();
      return;
    }
    closeCustom(true);
    commit({ version: 1, range: "custom", from, to });
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && tooltip.classList.contains("is-visible")) hideTooltip();
    if (event.key === "Escape" && !byId("custom-range").hidden) { event.preventDefault(); closeCustom(true); }
  });
  byId("export-invocations").addEventListener("click", () => {
    const visible = visibleLedgerRows();
    if (!visible.length) { byId("export-status").textContent = "No visible invocation records to export."; return; }
    const header = ["occurred_at", "correlation_id", "capability_id", "model_key", "tier", "mode", "usage_scope", "prompt_tokens", "completion_tokens", "total_tokens"];
    const rows = visible.map((row) => {
      const cells = [...row.cells].map((cell) => cell.textContent.trim());
      const [tier, mode] = cells[4].split("/").map((value) => value.trim());
      return [row.querySelector("time").dateTime, cells[8], cells[3], cells[2], tier, mode,
        cells[1] === "Operator chat" ? "operator_chat" : "control_plane", ...cells.slice(5, 8).map((value) => value.replaceAll(",", ""))];
    });
    const quote = (value) => {
      const raw = String(value);
      return `"${(/^\s*[=+@-]/.test(raw) ? "'" + raw : raw).replaceAll('"', '""')}"`;
    };
    const url = URL.createObjectURL(new Blob([[header, ...rows].map((row) => row.map(quote).join(",")).join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url; link.download = "fdai-synthetic-llm-invocations.csv";
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    byId("export-status").textContent = `CSV download requested for ${visible.length} visible synthetic records. No provider request was made.`;
  });
  const revealSection = () => {
    const target = document.getElementById(location.hash.slice(1));
    const details = target?.closest("details");
    if (details) details.open = true;
  };
  rowsFor('a[href^="#"]').forEach((link) => link.addEventListener("click", () => {
    const target = document.getElementById(link.hash.slice(1));
    const details = target?.closest("details");
    if (details) details.open = true;
  }));
  window.addEventListener("hashchange", revealSection);
  root.fdaiPreviewState = {
    capture: () => ({ ...committed }),
    restore: (payload) => {
      if (!validState(payload)) { stateError("Saved range is incompatible. The current range was retained; choose a preset or apply a valid custom range."); return false; }
      committed = { version: 1, range: payload.range, from: payload.from, to: payload.to };
      closeCustom(); stateError(""); renderRange();
      return true;
    },
  };
  const params = new URL(location.href).searchParams;
  if (["range", "from", "to"].some((key) => params.has(key))) {
    const candidate = { version: 1, range: params.has("from") || params.has("to") ? "custom" : params.get("range"), from: params.get("from") ?? "", to: params.get("to") ?? "" };
    const duplicate = ["range", "from", "to"].some((key) => params.getAll(key).length > 1);
    if (!duplicate && !(params.has("range") && candidate.range === "custom") && validState(candidate)) committed = candidate;
    else stateError("The URL range is invalid. Showing the default 7-day synthetic view; choose a preset or apply dates from May 7 to August 4, 2026.");
  }
  renderRange();
  revealSection();
})();
