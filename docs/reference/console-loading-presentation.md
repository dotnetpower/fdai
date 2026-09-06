# Console Loading Presentation

This reference defines loading geometry and stylesheet continuity for FDAI Console routes.

## Loading states

Every route, panel, and bounded content region renders a skeleton from its first loading frame.
The shared skeleton replaces spinner-only and text-only waits, while a route can provide a shape
that preserves its final layout dimensions.

Dashboard uses a posture block followed by metric, distribution, attention, and vertical
placeholders so loading does not collapse the report. One screen-reader status announces loading;
decorative blocks stay hidden. Shimmer stops under reduced motion while the static skeleton remains
visible.

The shared fallback uses heading, summary-card, and body-panel placeholders. An owned route shape
replaces that fallback only when it preserves a more accurate final layout.

## Stylesheet continuity

The HTML document owns the Console stylesheet as a direct dependency, so authentication, route,
component, and JavaScript hot updates cannot leave a mounted SPA without its layout and theme.
Vite transforms the same document link into the fingerprinted production CSS asset.

During development, the hot-update guard passes CSS changes through Vite's race-safe file reader
before transformation. An editor's temporary empty snapshot cannot replace the complete stylesheet.

## Related docs

| To learn about | Read |
|----------------|------|
| Evidence and recovery behavior | [Console Evidence and Resilience](../roadmap/interfaces/console-evidence-and-resilience.md) |
