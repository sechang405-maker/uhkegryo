# Term Graph Motion Design

## Goal

Make the fixed-world 3D term graph feel alive and responsive without changing its
layout contract. Expanding a term reveals its direct children from the parent;
collapsing returns removed children to that parent. Idle motion is visual only.

## Design

- Keep logical expansion state immediate for semantics and accessibility.
- Reconcile logical nodes with a short-lived display graph. Removed nodes retain
  their last world-coordinate snapshot until their exit completes.
- Drive all node, label, integrated control, and edge endpoints from one projected
  point map. Presence only interpolates between the projected parent and the
  projected fixed world point, so camera rotation and zoom remain common to the
  whole graph.
- Animate presence for 180 ms with a smoothstep curve. Reversing an in-flight
  toggle starts from its current amount. Exiting nodes are inert and hidden from
  accessibility immediately.
- Use one requestAnimationFrame clock only while presence transitions exist.
  Pause its clock while the document is hidden, and clean up frame, visibility,
  and media-query listeners on list mode or unmount.
- Respect `prefers-reduced-motion` by settling presence immediately. The idle
  effect is a low-amplitude synchronized glow on circles, never node movement.
- Preserve direct-child expansion, one visual parent, fixed world coordinates,
  3D yaw/pitch/perspective, 14 px labels, wheel zoom, and the no-scroll canvas.

## Interaction details

- Background drag keeps direct, lag-free camera updates and pointer capture.
- Pointer cancel/lost capture share cleanup; node controls never leak into camera
  drag.
- Hover, pressed, and keyboard focus use color/glow feedback without changing
  node geometry.
- Entering nodes remain non-interactive until mostly visible; exiting nodes never
  intercept input.

## Verification

- Pure state tests cover enter, exit, rapid reversal, immediate reduced motion,
  display graph cleanup, edge ownership, and unaffected point identity.
- Browser checks cover idle, expand/collapse/repeat, rotation during expansion,
  continuous wheel input, list/unmount cleanup, mobile, reduced motion, shared
  node ownership, and frame-by-frame edge-anchor agreement.

