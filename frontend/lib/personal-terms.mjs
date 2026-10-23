const ACTION_HEADER = "x-conversation-action";

async function read(response) {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "개인 용어 요청을 처리하지 못했습니다.");
  return body;
}

export function createPersonalTermClient(fetcher = fetch) {
  const request = (url, options = {}) => fetcher(url, { credentials: "include", ...options }).then(read);
  return {
    list: ({ includeDeleted = false } = {}) => request(
      includeDeleted ? "/api/personal-terms?include_deleted=true" : "/api/personal-terms"
    ),
    generate: (sourceInput, idempotencyKey, retryFailed = false) => request("/api/personal-terms/proposals", {
      method: "POST",
      headers: { "Content-Type": "application/json", [ACTION_HEADER]: "personal-term-generate", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ source_input: sourceInput, retry_failed: retryFailed }),
    }),
    update: (termId, values) => request(`/api/personal-terms/${encodeURIComponent(termId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", [ACTION_HEADER]: "personal-term-edit" },
      body: JSON.stringify(values),
    }),
    confirm: (termId) => request(`/api/personal-terms/${encodeURIComponent(termId)}/confirm`, {
      method: "POST", headers: { [ACTION_HEADER]: "personal-term-confirm" },
    }),
    remove: (termId) => request(`/api/personal-terms/${encodeURIComponent(termId)}`, {
      method: "DELETE", headers: { [ACTION_HEADER]: "personal-term-delete" },
    }),
    restore: (termId) => request(`/api/personal-terms/${encodeURIComponent(termId)}/restore`, {
      method: "POST", headers: { [ACTION_HEADER]: "personal-term-restore" },
    }),
  };
}

export function reconcilePersonalTermState(items, selectedIds, focusedId, searchedTermId) {
  const activeIds = new Set(items.filter((item) => item.status === "active").map((item) => item.term_id));
  const unavailable = (id) => typeof id === "string" && id.startsWith("personal_") && !activeIds.has(id);
  return {
    selectedIds: selectedIds.filter((id) => !unavailable(id)),
    focusedId: unavailable(focusedId) ? null : focusedId,
    clearSearch: unavailable(searchedTermId),
  };
}

export function editablePersonalTerm(term) {
  return {
    role: term.role,
    label_ko: term.label_ko || "",
    label_en: term.label_en || "",
    plain_meaning_ko: term.plain_meaning_ko || "",
    reference_checkpoints_ko: term.reference_checkpoints_ko || [],
    cautions_ko: term.cautions_ko || [],
    aliases_ko: term.aliases_ko || [],
    query_fragments_en: term.query_fragments_en || [],
    proposal_kind: term.proposal_kind,
    uncertainty_ko: term.uncertainty_ko || null,
  };
}

export function newPersonalTermRequestId() {
  return globalThis.crypto?.randomUUID?.() || `personal-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
