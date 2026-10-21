const PINTEREST_SITE_FILTER = "site:kr.pinterest.com/pin/";

export function combineRecommendedSearchQueries(terms) {
  const queries = [...new Set(terms.map(getRecommendedSearchQuery).filter(Boolean))];
  if (!queries.length) return null;
  if (queries.length === 1) return queries[0];
  const phrases = [...new Set(queries.map(query => query.replace(/(?:\s+(?:reference|drawing))+$/i, "").trim()).filter(Boolean))];
  return `${phrases.join(" ")} reference drawing`;
}

export function getRecommendedSearchQuery(term) {
  if (term?.recommended_search_query) return term.recommended_search_query;
  if (!term?.search_url) return null;

  try {
    const query = new URL(term.search_url).searchParams.get("q")?.trim();
    return query?.startsWith(PINTEREST_SITE_FILTER)
      ? query.slice(PINTEREST_SITE_FILTER.length).trim()
      : query || null;
  } catch {
    return null;
  }
}

export function createGraphSearchScope(terms, selectedIds, focusedId) {
  const selected = new Set(selectedIds);
  const selectedTerms = terms.filter(term => selected.has(term.term_id));
  return {
    focusedTerm: terms.find(term => term.term_id === focusedId) || null,
    selectedTerms,
    selectedQuery: combineRecommendedSearchQueries(selectedTerms),
  };
}
