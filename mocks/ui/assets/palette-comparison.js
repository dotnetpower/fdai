// Candidate colors are isolated to this specimen; shared light tokens are read, never overwritten.
(function () {
  "use strict";

  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });

  function channels(color) {
    if (!context || !CSS.supports("color", color)) throw new Error("Cannot measure palette color: " + color);
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = color;
    context.fillRect(0, 0, 1, 1);
    const values = Array.from(context.getImageData(0, 0, 1, 1).data);
    if (values[3] !== 255) throw new Error("Contrast requires an opaque background and text color.");
    return values.slice(0, 3);
  }

  function hex(color) {
    return "#" + channels(color).map((value) => value.toString(16).padStart(2, "0")).join("").toUpperCase();
  }

  function luminance(color) {
    return channels(color).map((value) => value / 255)
      .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
      .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  }

  function contrastRatio(foreground, background) {
    const a = luminance(foreground);
    const b = luminance(background);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  }

  window.FdaiPalette = Object.freeze({ contrastRatio });
  const study = document.getElementById("colors");
  const rootStyles = getComputedStyle(document.documentElement);
  const candidateStyles = getComputedStyle(study.querySelector('[data-palette="fresh"]'));
  const roles = [
    { key: "bg", label: "Page background", token: "--cs-bg" },
    { key: "card", label: "Answer surface", token: "--cs-card" },
    { key: "shade", label: "Supporting surface", token: "--cs-shade" },
    { key: "border", label: "Hairline", token: "--cs-hairline" },
    { key: "text", label: "Primary text", token: "--cs-text" },
    { key: "muted", label: "Secondary text", token: "--cs-text-soft" },
    { key: "blue", label: "Action / selected", token: "--cs-steel" },
    { key: "green", label: "Verified success", token: "--cs-sage" },
    { key: "amber", label: "Attention", token: "--cs-terracotta" },
    { key: "red", label: "Failure", token: "--cs-dusty-red" },
    { key: "purple", label: "Model / category", token: "--cs-plum" },
    { key: "question", label: "Question background", derived: "blue", candidateToken: "--cs-question-bg" },
    { key: "green-wash", label: "Success background", derived: "green", candidateToken: "--cs-success-bg" },
    { key: "amber-wash", label: "Attention background", derived: "amber", candidateToken: "--cs-attention-bg" },
    { key: "red-wash", label: "Failure background", derived: "red", candidateToken: "--cs-failure-bg" },
  ];
  const palettes = { current: {}, fresh: {} };
  for (const role of roles) {
    const value = role.token
      ? rootStyles.getPropertyValue(role.token).trim()
      : `color-mix(in srgb, ${palettes.current[role.derived]} 10%, ${palettes.current.card})`;
    palettes.current[role.key] = hex(value);
    palettes.fresh[role.key] = hex(candidateStyles.getPropertyValue(role.token || role.candidateToken).trim());
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function copyColor(value, label) {
    const button = element("button", "cp-hex", value);
    button.type = "button";
    button.setAttribute("aria-label", `Copy ${label} ${value}`);
    button.addEventListener("click", async () => {
      const feedback = document.getElementById("cp-copy-status");
      try {
        await navigator.clipboard.writeText(value);
        feedback.textContent = `Copied ${label}: ${value}`;
      } catch {
        feedback.textContent = `Clipboard unavailable. Select and copy ${label}: ${value}`;
      }
    });
    return button;
  }

  const template = document.getElementById("cp-sample-template");
  study.querySelectorAll("[data-palette]").forEach((scheme) => {
    const name = scheme.dataset.palette;
    const palette = palettes[name];
    for (const [key, value] of Object.entries(palette)) scheme.style.setProperty("--cp-" + key, value);
    scheme.querySelector(".cp-sample").appendChild(template.content.cloneNode(true));
    const strip = scheme.querySelector(".cp-accent-strip");
    ["blue", "green", "amber", "red", "purple"].forEach((key) => {
      const swatch = element("span", "cp-mini-swatch");
      swatch.style.setProperty("--cp-swatch", palette[key]);
      swatch.setAttribute("aria-label", `${key}: ${palette[key]}`);
      swatch.appendChild(element("i"));
      swatch.appendChild(element("code", "", palette[key]));
      strip.appendChild(swatch);
    });
    scheme.querySelector("[data-show-sample-evidence]").addEventListener("click", () => {
      const details = scheme.querySelector(".cp-evidence");
      details.open = true;
      details.querySelector("summary").focus({ preventScroll: true });
    });
  });

  const tokenRows = document.getElementById("cp-token-rows");
  roles.forEach((role) => {
    const row = document.createElement("tr");
    const title = element("th", "", role.label);
    title.scope = "row";
    title.appendChild(element("code", "", role.token || `${role.derived} tint (sample)`));
    row.appendChild(title);
    ["current", "fresh"].forEach((name) => {
      const cell = element("td");
      cell.dataset.label = name === "current" ? "Current" : "Clear neutral";
      const swatch = element("span", "cp-token-swatch");
      swatch.style.setProperty("--cp-swatch", palettes[name][role.key]);
      swatch.setAttribute("aria-hidden", "true");
      cell.append(swatch, copyColor(palettes[name][role.key], `${name} ${role.label}`));
      row.appendChild(cell);
    });
    tokenRows.appendChild(row);
  });

  const pairs = [
    { label: "Body / answer", text: "text", bg: "card" },
    { label: "Secondary / answer", text: "muted", bg: "card" },
    { label: "Primary button", text: "card", bg: "blue" },
    { label: "Question bubble", text: "text", bg: "question" },
    { label: "Verified badge", text: "green", bg: "green-wash" },
    { label: "Attention badge", text: "amber", bg: "amber-wash" },
    { label: "Failure badge", text: "red", bg: "red-wash" },
  ];
  const contrastRows = document.getElementById("cp-contrast-rows");
  pairs.forEach((pair) => {
    const row = document.createElement("tr");
    const title = element("th", "", pair.label);
    title.scope = "row";
    row.appendChild(title);
    ["current", "fresh"].forEach((name) => {
      const palette = palettes[name];
      const ratio = contrastRatio(palette[pair.text], palette[pair.bg]);
      const cell = element("td");
      cell.dataset.ratio = String(ratio);
      cell.dataset.palettePair = name;
      cell.dataset.label = name === "current" ? "Current" : "Clear neutral";
      cell.appendChild(element("strong", "", `${ratio.toFixed(2)}:1`));
      cell.appendChild(element("span", "", ratio >= 4.5 ? "Meets 4.5:1" : "Below 4.5:1"));
      cell.dataset.result = ratio >= 4.5 ? "pass" : "below";
      row.appendChild(cell);
    });
    contrastRows.appendChild(row);
  });

  study.querySelectorAll("[data-palette-view]").forEach((button) => {
    button.addEventListener("click", () => {
      const selected = button.dataset.paletteView;
      study.querySelectorAll("[data-palette-view]").forEach((control) => {
        control.setAttribute("aria-pressed", String(control === button));
      });
      study.querySelector(".cp-comparison").dataset.paletteLayout = selected;
      study.querySelectorAll("[data-palette]").forEach((scheme) => {
        scheme.hidden = selected !== "compare" && scheme.dataset.palette !== selected;
      });
    });
  });
})();
