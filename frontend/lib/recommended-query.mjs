const PINTEREST_SITE_FILTER = "site:kr.pinterest.com/pin/";

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
