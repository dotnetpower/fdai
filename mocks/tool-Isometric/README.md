# Architecture Atlas mock

Architecture Atlas is a standalone Canvas 2D prototype for exploring and editing an
Azure application map. It uses one axonometric baseplate, nested scope and network
regions, low-profile resource nodes, and typed connections instead of stacking every
architecture concept on a separate plate.

## Files

| File | Responsibility |
|------|----------------|
| `index.html` | Canvas-first application shell, resource drawer, layer filters, and inspector |
| `styles.css` | Responsive desktop layout and mobile drawers |
| `model.js` | Resource catalog, nested regions, connections, and JSON serialization |
| `renderer.js` | Axonometric projection, opaque colored-glass nodes, regions, edges, hit testing, and camera |
| `app.js` | Selection, history, drag and drop, snapping, filters, import/export, and controls |

## Running locally

Serve the directory over HTTP because the integrated browser restricts module imports
from `file://` URLs:

```sh
cd mocks/tool-Isometric
python3 -m http.server 8791
```

Open `http://127.0.0.1:8791/index.html`.

## Map model

The mock uses different visual forms for different architecture relationships:

- **Scope boundaries**: the subscription and resource groups appear as nested outlines.
- **Network zones**: the virtual network and subnets appear as tinted nested regions.
- **Resource nodes**: WAF, L4, compute, data, and secret resources float slightly above the baseplate as low 3D blocks with floor reflections.
- **Connections**: ingress, internal, data, and private endpoint paths use distinct line styles.
- **Placement surface**: half-cell snap points guide movement, and each resource casts a
	camera-aligned color reflection across the baseplate.

Dropping or moving a resource recalculates its smallest containing region. This makes the
resource group, virtual network, or subnet relationship part of the scene data instead of
an incidental drawing order.

## Editing

| Action | Input |
|--------|-------|
| Select | click a resource or boundary |
| Add to selection | `Shift` + click |
| Box select | `Ctrl` + drag |
| Move and snap | drag selected resources |
| Push adjacent blocks | drag a block into another block |
| Scale the whole map | select the subscription, then drag its corner handle |
| Pan the map | drag an empty area or boundary |
| Change camera angle | select **Iso**, **Top**, or **Front** |
| Zoom | mouse wheel or zoom controls |
| Copy and paste | `Ctrl+C`, then `Ctrl+V` |
| Undo and redo | `Ctrl+Z`, then `Ctrl+Shift+Z` |
| Delete | `Delete` or the selection toolbar |

Use **Read mode** to disable architecture mutations while keeping camera navigation,
selection, filtering, and inspection available. Use **Iso**, **Top**, and **Front** for
camera presets, or **Fit map** to restore the full scene framing.

Connections attach to directional side ports. Resource abbreviations, names, and status
indicators render above the connection layer so edge paths don't obscure node text.

Resources stay inside their assigned parent boundary. A collision pushes the adjacent
resource to the next free snap position; if the push chain reaches a boundary, the move
stops without leaving overlapping resources.

## Data exchange

**Export JSON** downloads the current regions, resources, connections, and world metadata.
**Import** accepts the same format and validates that the three scene collections are arrays
before replacing the current map.
