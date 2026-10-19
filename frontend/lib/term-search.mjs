import {canonicalRole} from './term-mind-map.mjs';

const cooldowns = new Map();
function failureError(message, status, delay, reason) {
  return Object.assign(new Error(message), {status, retry_after_seconds: delay / 1000,
    search_failure: [401,403].includes(status) ? 'access_restricted' : status === 429 ? 'rate_limited'
      : status >= 500 ? 'temporary' : reason});
}
export function retryDelay(value, now = Date.now()) {
  if (value == null || value === '') return null;
  const numeric = Number(value);
  const delay = Number.isFinite(numeric) ? numeric * 1000 : Date.parse(value) - now;
  return Number.isFinite(delay) ? Math.max(0, delay) : null;
}
const wait = (ms, signal) => new Promise((resolve, reject) => {
  if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
  const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
  const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, ms);
  signal?.addEventListener('abort', abort, {once:true});
});
export function searchFailureMessage(result) {
  if (result?.reason_codes?.includes('PIN_RESULTS_EMPTY')) return '검색 결과가 없습니다.';
  if (result?.search_failure === 'access_restricted') return '검색 서비스 접근이 제한되어 있습니다. 원문 링크를 확인해 주세요.';
  if (result?.search_failure === 'rate_limited') return '요청 한도에 도달했습니다. 안내된 대기 시간 후 다시 시도해 주세요.';
  return '검색 결과를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요.';
}
export async function searchFixedTerm(term, { fetchImpl = fetch, signal, suffix, sleep = wait, now = Date.now, excludePinIds = [], maxRetries = 1 } = {}) {
  const key = term.term_id;
  const remaining = (cooldowns.get(key) || 0) - now();
  if (remaining > 0) throw failureError(`${Math.ceil(remaining / 1000)}초 후 다시 시도해 주세요. 기존 이미지를 유지합니다.`, 429, remaining, 'rate_limited');
  cooldowns.delete(key);
  const exclusions = [...new Set(excludePinIds)].filter(id => typeof id === 'string' && /^(?:[0-9]{1,64}|e1_[A-Za-z0-9_-]{1,200})$/.test(id)).slice(0, 64);
  const retries = maxRetries === 0 ? 0 : 1;
  for (let attempt = 0; attempt <= retries; attempt++) {
  let response;
  try { response = await fetchImpl("/api/term-search", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ term_id: term.term_id, ...(suffix ? { suffix } : {}), ...(exclusions.length ? {exclude_pin_ids: exclusions} : {}) }), signal,
  }); } catch (error) {
    if (signal?.aborted || error.name === 'AbortError') throw error;
    if (attempt < retries && error instanceof TypeError) { await sleep(500, signal); continue; }
    throw error;
  }
  const result = await response.json().catch(() => null);
  const transient = [429, 500, 502, 503, 504].includes(response.status) ||
    (response.ok && result?.retryable === true && !result.pins?.some(p => p.status === 'available' && p.thumbnail_url));
  const delay = retryDelay(response.headers?.get('Retry-After')) ??
    (Number.isFinite(result?.retry_after_seconds) ? result.retry_after_seconds * 1000 : response.status === 429 ? 60000 : 500);
  if (transient || result?.search_failure === 'rate_limited') {
    cooldowns.set(key, now() + delay);
    if (cooldowns.size > 256) cooldowns.delete(cooldowns.keys().next().value);
    if (attempt < retries && transient && delay <= 2000) { await sleep(delay, signal); cooldowns.delete(key); continue; }
  }
  if (response.status === 429) throw failureError(`${Math.ceil(delay / 1000)}초 후 다시 시도해 주세요. 기존 이미지를 유지합니다.`, 429, delay, 'rate_limited');
  if (!response.ok) throw failureError(typeof result?.detail === "string" ? result.detail : "검색 결과를 가져오지 못했습니다.", response.status, delay, result?.search_failure);
  if (result?.term_id !== term.term_id || canonicalRole(result?.role) !== canonicalRole(term.role) || !Array.isArray(result?.pins)) {
    throw new Error("검색 결과가 선택한 텀카드와 일치하지 않습니다.");
  }
  return {...result, role: canonicalRole(result.role)};
  }
}

export function applySketchResult(term, result) {
  if (!result.pins?.some((pin) => pin.status === "available" && pin.thumbnail_url)) {
    throw new Error(`${searchFailureMessage(result)} 기존 이미지를 유지합니다.`);
  }
  const previous = new Map((term.pins || []).map(pin => [pin.pin_id, pin]));
  const pins = result.pins.map(pin => pin.status !== 'available' && previous.get(pin.pin_id)?.thumbnail_url
    && pin.failure_reason !== 'access_restricted' && pin.status !== 'deleted' ? previous.get(pin.pin_id) : pin);
  return { ...term, pins, search_url: result.search_url,
    recommended_search_query: result.recommended_search_query || null, reason_codes: result.reason_codes || [],
    search_failure: result.search_failure, retry_after_seconds: result.retry_after_seconds };
}

export function applyPreviewRecovery(term, result, failedIds = []) {
  const failed = new Set(failedIds);
  const ids = new Set(), images = new Set(), pins = [];
  for (const pin of [...(term.pins || []), ...(result.pins || [])]) {
    if (pin.status !== 'available' || !pin.thumbnail_url || failed.has(pin.pin_id)
        || ids.has(pin.pin_id) || images.has(pin.thumbnail_url)) continue;
    ids.add(pin.pin_id); images.add(pin.thumbnail_url); pins.push(pin);
    if (pins.length === 8) break;
  }
  if (!pins.length) throw new Error(`${searchFailureMessage(result)} 기존 이미지는 유지합니다.`);
  return {...term, pins, search_failure: result.search_failure,
    retry_after_seconds: result.retry_after_seconds, reason_codes: result.reason_codes || []};
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
