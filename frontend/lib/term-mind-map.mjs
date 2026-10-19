export const ROLE_ORDER = ["body", "pose", "composition", "perspective"];
export const canonicalRole = role => ['view', 'layout'].includes(role) ? 'composition' : role;

const ROLE_LABELS = {
  body: "체형",
  pose: "포즈",
  composition: "구도",
  perspective: "투시",
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
    const role = canonicalRole(term?.role);
    if (ROLE_ORDER.includes(role) && isTermForRole(term, term.role)) {
      termsByRole.set(role, [...(termsByRole.get(role) || []), { ...term, role }]);
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
