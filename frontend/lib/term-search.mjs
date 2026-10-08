export async function searchFixedTerm(term, { fetchImpl = fetch, signal, suffix } = {}) {
  const response = await fetchImpl("/api/term-search", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term_id: term.term_id, ...(suffix ? { suffix } : {}) }), signal,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof result?.detail === "string" ? result.detail : "검색 결과를 가져오지 못했습니다.");
  if (result?.term_id !== term.term_id || result?.role !== term.role || !Array.isArray(result?.pins)) {
    throw new Error("검색 결과가 선택한 텀카드와 일치하지 않습니다.");
  }
  return result;
}

export function applySketchResult(term, result) {
  if (result.reason_codes?.length || !result.pins?.some((pin) => pin.status === "available" && pin.thumbnail_url)) {
    throw new Error("재검색 결과를 가져오지 못했습니다. 기존 이미지를 유지합니다.");
  }
  return { ...term, pins: result.pins, search_url: result.search_url,
    recommended_search_query: result.recommended_search_query || null, reason_codes: [] };
}

export async function searchTermMode(term, suffix, options = {}) {
  const result = await searchFixedTerm(term, { ...options, suffix });
  return applySketchResult(term, result);
}

export function restoreOriginalSearch(searches, termId) {
  const restored = { ...searches };
  delete restored[termId];
  return restored;
}
