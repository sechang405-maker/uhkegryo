# Outward Graph Branches Design

## Goal

Keep the graph's immutable 3D world layout and common camera projection while arranging every expanded branch from the graph center toward the outside of its category sector.

## World-space layout

- The graph center is world origin `(0, 0, 0)`.
- A category's sector axis is the normalized vector from the origin to that category node.
- A child's local branch axis is the normalized vector from the graph origin to its displayed parent. Its position continues from the parent into that outward half-space.
- Visible parent axes within the same role divide the category cone into deterministic angular territories. A sibling fan is bounded by half the nearest parent-axis separation, so it cannot spill into an adjacent parent's territory.
- A direct child must have a greater origin radius than its one displayed representative parent.
- Siblings split a deterministic, narrow 3D fan around the parent axis instead of using a full random circle.
- A second-level child continues outward from its parent and cannot return toward the origin.
- Expanding an unrelated parent never recomputes existing world coordinates. Collapse and re-expansion reproduce the same coordinates from stable term and parent identifiers.

## Semantic relationships and displayed parents

- Full prerequisite AND/OR relationships remain available as semantic metadata and are not changed by visualization.
- Each displayed term has at most one incoming edge. A base term keeps its category edge; an expanded detail uses the parent that first revealed it; a supporting term without a revealing parent uses its category.
- Expanding another shared parent later never adds another edge or steals ownership. If the representative parent collapses, the next still-expanded parent takes ownership; re-expansion does not steal it back.
- The child radius and outward direction use only the displayed representative parent. Supporting semantic parents stay in the same category sector without an extra line to the child.
- Cycles remain finite; when strict radial ordering is impossible inside a strongly connected relation, deterministic reveal order is used without iterative repositioning.

## Projection and interaction

- World coordinates are computed once when graph structure changes.
- `projectGraph` continues to apply one 3D camera with independent yaw and pitch, perspective, depth, and zoom.
- Category centers use a more compact world-z span so their projected sectors remain readable; the former `>250` category-z-distance assertion was a fixture-shape check, not a 3D contract. The replacement contract checks substantial full-graph world-z depth, camera-depth separation, independent yaw/pitch response, and immutable world anchors.
- Dragging never changes individual world coordinates.
- Every term is a centered circular node. Its wrapped label and, when applicable, its small expand/collapse region stay inside that same circle; there is no detached dot, card, or floating control.
- The circle center is the shared endpoint for the node, label, SVG edge, and integrated expand control.
- Pointer gestures that start on a node or its integrated control never rotate the scene. Selection, focus, hover, and keyboard focus do not change node dimensions or world/screen anchors.

## Verification

- Unit tests cover simultaneous category expansion, multi-parent children, and a synthetic two-level branch.
- Browser tests cover shared-child expansion order, ownership transfer on collapse/re-expansion, all currently available expandable roots, parent-axis territory, existing-coordinate stability across unrelated expansion, selection with pointer jitter, circular containment, continuous 3D drag, independent yaw/pitch, depth changes, and sub-pixel center-anchor agreement. The reviewed catalog has no expandable second-level term, so the two-level case is covered by the real layout function with a synthetic catalog fixture.
- Perspective can still make two separate 3D territories partially overlap at an extreme camera angle. The initial camera rejects stacked centers and keeps anchors near the frame; rotation is not allowed to mutate world coordinates to chase screen-space overlap.
- Existing selection, collapse, search, AND/OR, deduplication, mobile, build, and CI checks remain green.
