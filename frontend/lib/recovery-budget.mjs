// Explicit searches create a fresh generation. Image failures never reset it.
export function createRecoveryBudget(generation) {
  return {generation, cards: {}};
}

export function claimRecovery(budget, {generation, termId, kind = 'auto', now = Date.now()}) {
  const card = budget.cards[termId] || {};
  if (generation !== budget.generation || !['auto', 'manual'].includes(kind)
      || card.busy || card.restricted || card[kind] || (card.retryAt || 0) > now) {
    return {budget, allowed: false};
  }
  return {allowed: true, budget: {...budget, cards: {...budget.cards,
    [termId]: {...card, [kind]: true, busy: true}}}};
}

export function finishRecovery(budget, {generation, termId, retryAfterSeconds = 0, restricted = false, now = Date.now()}) {
  if (generation !== budget.generation || !budget.cards[termId]) return budget;
  const card = budget.cards[termId];
  const delay = Number.isFinite(retryAfterSeconds) ? Math.max(0, retryAfterSeconds) * 1000 : 0;
  return {...budget, cards: {...budget.cards, [termId]: {...card, busy: false,
    restricted: card.restricted || restricted, retryAt: Math.max(card.retryAt || 0, now + delay)}}};
}
