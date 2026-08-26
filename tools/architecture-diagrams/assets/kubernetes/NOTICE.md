# Kubernetes Icons

This directory contains an allowlisted subset of the official Kubernetes Icons
Set published by the Kubernetes community. The files are embedded without
cropping, rotation, recoloring, or shape changes.

The Kubernetes Icons Set is licensed under either the Apache License 2.0 or
CC-BY-4.0, at your option. Review the current terms on the
[Kubernetes Icons Set](https://github.com/kubernetes/community/tree/master/icons)
page before updating this subset.

`icons.lock.json` records the pinned upstream commit URL and SHA-256 digest for
every included file. Builds run without downloading icon assets from the
network.

The subset uses the unlabeled variant because the console renders these glyphs
at 22 px, where the labeled abbreviation is unreadable.

Two console resource types reuse a related glyph because the upstream set
publishes no dedicated icon for them:

- `kubernetes.endpoint-slice` reuses `ep.svg`, the Endpoints glyph.
- `kubernetes.ingress-class` reuses `ing.svg`, the Ingress glyph.
