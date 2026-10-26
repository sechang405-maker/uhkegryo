const PREFIX = 'uhkegryo:live-reference:v1:';
const SESSION_ID = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;

function validTerm(value) {
  return value && typeof value === 'object' && typeof value.term_id === 'string' && value.term_id.length > 0;
}

function normalize(value, sessionId, baseJobId) {
  if (!value || value.version !== 1 || value.sessionId !== sessionId
      || (value.baseJobId ?? null) !== (baseJobId ?? null)
      || !['results', 'term-results'].includes(value.boardView)) return null;
  const termSearch = value.termSearch?.loading === false && !value.termSearch.error
    && validTerm(value.termSearch.term) ? value.termSearch : null;
  const sketchSearches = Object.fromEntries(Object.entries(value.sketchSearches || {}).filter(
    ([termId, search]) => termId && search && !search.loading && !search.error && validTerm(search.term),
  ));
  if (!termSearch && !Object.keys(sketchSearches).length) return null;
  return { boardView: termSearch ? value.boardView : 'results', termSearch, sketchSearches };
}

export function filterLiveTerms(terms, conditions, { loaded = false, historical = false } = {}) {
  if (!loaded || historical) return terms;
  const allowed = new Set((conditions || []).map(item => item?.term_id).filter(Boolean));
  return (terms || []).filter(term => allowed.has(term.term_id));
}

export function readLiveReferenceState(storage, sessionId, baseJobId) {
  if (!storage || !SESSION_ID.test(sessionId || '')) return null;
  try {
    return normalize(JSON.parse(storage.getItem(`${PREFIX}${sessionId}`)), sessionId, baseJobId);
  } catch {
    return null;
  }
}

export function writeLiveReferenceState(storage, sessionId, state) {
  if (!storage || !SESSION_ID.test(sessionId || '')) return false;
  const key = `${PREFIX}${sessionId}`;
  try {
    const value = normalize({ version: 1, sessionId, ...state }, sessionId, state?.baseJobId ?? null);
    if (!value) {
      storage.removeItem(key);
      return false;
    }
    storage.setItem(key, JSON.stringify({
      version: 1, sessionId, baseJobId: state?.baseJobId ?? null, ...value,
    }));
    return true;
  } catch {
    return false;
  }
}

export function clearLiveReferenceState(storage, sessionId) {
  if (!storage || !SESSION_ID.test(sessionId || '')) return;
  try { storage.removeItem(`${PREFIX}${sessionId}`); } catch { /* Best-effort browser state only. */ }
}
