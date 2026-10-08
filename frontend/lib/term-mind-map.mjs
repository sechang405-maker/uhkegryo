export const ROLE_ORDER = ["body", "pose", "view", "perspective", "layout"];

const ROLE_LABELS = {
  body: "체형",
  pose: "포즈",
  view: "시점",
  perspective: "투시",
  layout: "구도",
};

function isTermForRole(term, role) {
  return term
    && term.role === role
    && typeof term.term_id === "string"
    && term.term_id.trim()
    && typeof term.label_ko === "string"
    && term.label_ko.trim();
}

export function createMindMapSlots(terms) {
  const termsByRole = new Map();
  for (const term of Array.isArray(terms) ? terms : []) {
    if (ROLE_ORDER.includes(term?.role) && isTermForRole(term, term.role)) {
      termsByRole.set(term.role, [...(termsByRole.get(term.role) || []), term]);
    }
  }

  return ROLE_ORDER.map((role) => ({
    role,
    roleLabel: ROLE_LABELS[role],
    terms: termsByRole.get(role) || [],
    term: termsByRole.get(role)?.[0] || null,
  }));
}

export function firstSelectableTermId(slots) {
  return slots.find((slot) => slot.terms?.length)?.terms[0].term_id || null;
}
