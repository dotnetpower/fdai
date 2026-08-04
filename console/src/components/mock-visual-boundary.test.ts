import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const MOCK_ROOT = fileURLToPath(new URL("../../../mocks/ui/", import.meta.url));
const REPOSITORY_ROOT = fileURLToPath(new URL("../../../", import.meta.url));

function mockSources(): readonly { readonly file: string; readonly source: string }[] {
  return readdirSync(MOCK_ROOT, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && (
      entry.name.endsWith(".html") || entry.name.endsWith(".css") || entry.name.endsWith(".md")
    ))
    .map((entry) => {
      const relative = `${entry.parentPath.slice(MOCK_ROOT.length)}/${entry.name}`.replace(/^\//, "");
      return { file: relative, source: readFileSync(`${entry.parentPath}/${entry.name}`, "utf8") };
    });
}

describe("mock console visual boundary", () => {
  test("prohibits top and left edge accents on content containers", () => {
    const forbidden = [
      /cs-kpi-accent/,
      /cs-hcard-rail/,
      /in-severity-rail/,
      /fc-turn-bar/,
      /vx-card-d/,
      /border-top:\s*[2-9]px\s+solid/,
      /border-left:\s*[2-9]px\s+solid/,
      /box-shadow:\s*inset\s+[1-9][0-9]*px\s+0/,
      /\.cs-tile::before/,
    ];
    const violations = mockSources().flatMap(({ file, source }) =>
      forbidden.flatMap((pattern) => pattern.test(source) ? [`${file}: ${pattern.source}`] : []),
    );
    expect(violations).toEqual([]);
  });

  test("cache-busts iframe previews so removed variants do not persist", () => {
    const landing = readFileSync(`${MOCK_ROOT}/index.html`, "utf8");
    expect(landing).toMatch(/const previewUrl = page \+ '\?shell=left-v5&preview=' \+ Date\.now\(\);/);
    expect(landing).toContain("frame.src = previewUrl");
  });

  test("registers the synthetic Service Map under Visualization", () => {
    const landing = readFileSync(`${MOCK_ROOT}/index.html`, "utf8");
    const masterLanding = readFileSync(`${REPOSITORY_ROOT}/index.html`, "utf8");
    const navigation = readFileSync(`${MOCK_ROOT}/assets/calm-slate.js`, "utf8");
    const serviceMap = readFileSync(`${MOCK_ROOT}/service-map.html`, "utf8");

    expect(landing).toContain("<h3>Visualization</h3>");
    expect(landing).toContain('data-page="service-map.html"');
    expect(masterLanding).toContain("<h3>Visualization</h3>");
    expect(masterLanding).toContain('data-page="mocks/ui/service-map.html"');
    expect(masterLanding).toContain('<span class="count">41 pages</span>');
    expect(navigation).toContain('["Visualization", [');
    expect(navigation).toContain('["service-map.html", "Service map", "is-steel"]');
    expect(serviceMap).toContain("Design preview · Synthetic telemetry");
    expect(serviceMap).toContain('data-sm-mode="live"');
    expect(serviceMap).toContain('data-sm-mode="performance"');
    expect(serviceMap).toContain('data-sm-mode="incident"');
    expect(serviceMap).toContain('data-sm-mode="security"');
    expect(serviceMap).toContain("grid-template-columns: repeat(2, 1fr)");
    expect(serviceMap).toContain('port: 5432, tls: "TLS 1.3", auth: "mTLS"');
    expect(serviceMap).toContain('port: 8080, tls: "Plaintext"');
    expect(serviceMap).toContain("Ports are destination listeners. Security values are synthetic.");
    expect(serviceMap).toContain("renderEdgeInspector");
    expect(serviceMap).toContain("sm-road-outline");
    expect(serviceMap).toContain("sm-road-surface");
    expect(serviceMap).toContain("sm-road-divider");
    expect(serviceMap).toContain("sm-traffic-vehicle");
    expect(serviceMap).toContain("animation.beginElement()");
    expect(serviceMap).toContain("sm-speed-sign");
    expect(serviceMap).toContain("function rateSignUnit(");
    expect(serviceMap).toContain("sm-road-tooltip");
    expect(serviceMap).toContain("plateHalfWidth = 35");
    expect(serviceMap).not.toContain("marker-end=");
    expect(serviceMap).toContain('id="sm-map-grid"');
    expect(serviceMap).toContain('data-sm-zoom-in');
    expect(serviceMap).toContain('data-sm-zoom-out');
    expect(serviceMap).toContain('data-sm-zoom-fit');
    expect(serviceMap).toContain("function zoomAt(");
    expect(serviceMap).toContain("function fitDrawing(");
    expect(serviceMap).toContain("function formatCoordinate(");
    expect(serviceMap).toContain('scrollSurface.addEventListener("keydown"');
    expect(serviceMap).toContain("sm-map-plate");
    expect(serviceMap).not.toContain("sm-iso-floor-top");
    expect(serviceMap).toContain("sm-iso-object");
    expect(serviceMap).toContain("sm-iso-label");
    expect(serviceMap).toContain('<rect width="104" height="32" rx="3"/>');
    expect(serviceMap).toContain("sm-sign-post");
    expect(serviceMap).not.toContain("sm-cad-dimensions");
    expect(serviceMap).not.toContain('<text x="95" y="41">190</text>');
    expect(serviceMap).toContain('class="sm-node kind-');
    expect(serviceMap).toContain('inspector.className = "sm-inspector kind-"');
    expect(serviceMap).not.toContain("sm-edge-particles");
  });
});
