export function resultTerms(job) {
  const result = job?.job_status === "completed" ? job.result : null;
  return ["success", "partial_result"].includes(result?.agent_status)
    ? result.reference_plan?.terms || [] : [];
}

export function renderedResultTerms(job, turns = [], previousReferenceJob = null) {
  const result = job?.job_status === "completed" ? job.result : null;
  const update = result?.reference_update;
  if (!update) return resultTerms(job);

  const currentIndex = turns.findIndex((turn) => turn.job?.job_id === job.job_id);
  const previousJob = currentIndex < 0 ? null : [...turns.slice(0, currentIndex)]
    .reverse()
    .find((turn) => resultTerms(turn.job).length)?.job;
  const previousTerms = resultTerms(previousReferenceJob?.job_id === previousJob?.job_id
    ? previousReferenceJob : previousJob || previousReferenceJob);
  const currentTerms = result?.reference_plan?.terms || [];
  const preservedIds = update.preserved_term_ids || [];
  const replacedIds = update.replaced_term_ids || [];
  if (preservedIds.length || replacedIds.length || update.removed_term_ids?.length) {
    const previousById = new Map(previousTerms.map((term) => [term.term_id, term]));
    const currentById = new Map(currentTerms.map((term) => [term.term_id, term]));
    return [...new Set([...preservedIds, ...replacedIds])].flatMap((id) => {
      const term = replacedIds.includes(id)
        ? currentById.get(id)
        : currentById.get(id) || previousById.get(id);
      return term ? [term] : [];
    });
  }

  // Older saved results express updates by category. Keep all cards in each group.
  const preservedRoles = update.preserved_roles || [];
  const replacedRoles = update.replaced_roles || [];
  return [...new Set([...preservedRoles, ...replacedRoles])].flatMap((role) => {
    const previous = previousTerms.filter((term) => term.role === role);
    const current = currentTerms.filter((term) => term.role === role);
    return replacedRoles.includes(role) ? current : previous.length ? previous : current;
  });
}

export function roleNotice(term) {
  if (term?.reason_codes?.includes("PIN_SEARCH_UNAVAILABLE")) return "검색 결과를 가져오지 못했습니다.";
  if (term?.reason_codes?.includes("PIN_RESULTS_EMPTY")) return "검색 결과가 없습니다.";
  return null;
}

export function showThumbnail(pin) {
  return pin.status === "available" && Boolean(pin.thumbnail_url);
}

export function createGalleryRows(slots) {
  return slots.flatMap((slot) => slot.terms.map((term) => ({
    ...slot, term, pins: (term.pins || []).slice(0, 8),
  })));
}

export function clarificationChoices(result) {
  return Array.isArray(result?.clarification_choices) ? result.clarification_choices : [];
}

export function resultUserMessage(job) {
  if (job?.job_status === "failed") return job.failure?.user_message || "요청을 완료하지 못했습니다. 다시 시도해 주세요.";
  const result = job?.job_status === "completed" ? job.result : null;
  return ["out_of_scope", "unsafe_input", "reference_guidance"].includes(result?.agent_status) ? result.user_message : null;
}


export function pinUnavailableMessage(pin) {
  return pin.status === "deleted" ? "삭제된 핀입니다." : "이미지를 일시적으로 불러오지 못했습니다. 다시 시도해 주세요.";
}
