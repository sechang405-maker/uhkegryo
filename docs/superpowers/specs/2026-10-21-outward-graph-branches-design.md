# Outward Graph Branches Design

## Goal

Keep the graph's immutable 3D world layout and common camera projection while arranging every expanded branch from the graph center toward the outside of its category sector.

## World-space layout

- The graph center is world origin `(0, 0, 0)`.
- A category's sector axis is the normalized vector from the origin to that category node.
- A child inherits its role category's sector and is placed in a bounded 3D cone around that axis.
- A direct child must have a greater origin radius than its one displayed representative parent.
- Siblings split a deterministic fan inside the cone instead of using a full random circle.
- A second-level child continues outward from its parent and cannot return toward the origin.

## Semantic relationships and displayed parents

- Full prerequisite AND/OR relationships remain available as semantic metadata and are not changed by visualization.
- Each displayed term has at most one incoming edge. A base term keeps its category edge; an expanded detail uses the parent that first revealed it; a supporting term without a revealing parent uses its category.
- Expanding another shared parent later never adds another edge or steals ownership. If the representative parent collapses, the next still-expanded parent takes ownership; re-expansion does not steal it back.
- The child radius and outward direction use only the displayed representative parent. Supporting semantic parents stay in the same category sector without an extra line to the child.
- Cycles remain finite; when strict radial ordering is impossible inside a strongly connected relation, deterministic reveal order is used without iterative repositioning.

## Projection and interaction

- World coordinates are computed once when graph structure changes.
- `projectGraph` continues to apply one 3D camera with independent yaw and pitch, perspective, depth, and zoom.
- Dragging never changes individual world coordinates.
- The existing visible-dot anchor remains the shared endpoint for nodes, labels, SVG edges, and expand controls.

## Verification

- Unit tests cover simultaneous category expansion, multi-parent children, and a synthetic two-level branch.
- Browser tests cover shared-child expansion order, ownership transfer on collapse/re-expansion, all currently available expandable roots, continuous 3D drag, independent yaw/pitch, depth changes, and sub-pixel anchor agreement. The reviewed catalog has no expandable second-level term, so the two-level case is covered by the real layout function with a synthetic catalog fixture.
- Existing selection, collapse, search, AND/OR, deduplication, mobile, build, and CI checks remain green.
