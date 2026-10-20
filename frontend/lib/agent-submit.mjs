const GENERIC_ERROR = "요청을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.";
import { sessionUsage, quotaError } from './session-usage.mjs';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

export function shouldSubmitOnEnter(event, composing = false) {
  return event.key === "Enter" && !event.shiftKey && !event.repeat && !composing
    && !event.isComposing && !event.nativeEvent?.isComposing
    && event.keyCode !== 229 && event.nativeEvent?.keyCode !== 229;
}

export function countCharacters(value) {
  return Array.from(value).length;
}

export function validateRequestText(value) {
  if (typeof value !== "string" || !value.trim()) {
    return "그릴 캐릭터를 한 글자 이상 설명해 주세요.";
  }
  if (countCharacters(value) > 500) {
    return "설명은 500자 이하로 입력해 주세요.";
  }
  return null;
}

export async function submitAgentRequest(requestText, options = {}) {
  const validationError = validateRequestText(requestText);
  if (validationError) return { ok: false, error: validationError };
  if (API_BASE_URL !== "/api") return { ok: false, error: GENERIC_ERROR };

  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const createId = options.createId || (() => globalThis.crypto.randomUUID());
  try {
    const response = await fetchImpl(`${API_BASE_URL}/agent`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": options.idempotencyKey || createId(),
      },
      body: JSON.stringify({ request_text: requestText, ...(options.sessionId ? { session_id: options.sessionId } : {}) }),
      signal: options.signal,
    });
    const payload = await response.json();
    const usage = sessionUsage(payload);
    if (response.status !== 202) {
      return {
        ok: false,
        ...(usage ? { usage } : {}),
        ...(payload?.failure_code ? { failureCode: payload.failure_code } : {}),
        ...(typeof payload?.retryable === 'boolean' ? { retryable: payload.retryable } : {}),
        ...(response.status >= 500 ? { uncertain: true } : {}),
        error: typeof payload?.user_message === "string" && payload.user_message.trim()
          ? payload.user_message
          : GENERIC_ERROR,
      };
    }
    if (typeof payload?.job_id !== "string" || !payload.job_id) {
      return { ok: false, error: GENERIC_ERROR, uncertain: true };
    }
    return { ok: true, jobId: payload.job_id, pollAfterMs: payload.poll_after_ms, ...(usage ? { usage } : {}) };
  } catch {
    return { ok: false, error: GENERIC_ERROR, uncertain: true };
  }
}

export function createSubmissionController() {
  let pending = false;
  const memory = new Map();
  const attempts = new Map();
  function storageFor(options) {
    if (options.storage) return options.storage;
    if (typeof window !== 'undefined') return window.localStorage;
    return { getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key) };
  }
  function attemptStorageFor(options) {
    if (options.attemptStorage) return options.attemptStorage;
    if (typeof window !== 'undefined') return window.sessionStorage;
    return { getItem: key => attempts.get(key), setItem: (key, value) => attempts.set(key, value), removeItem: key => attempts.delete(key) };
  }
  async function tokenFor(text, options) {
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${options.sessionId || ''}\n${text}`));
    const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    return `uh-pending-request-v1:${options.sessionId || 'new'}:${hash}`;
  }
  return {
    isPending: () => pending,
    async canRetry(requestText, options = {}) {
      try {
        const token = await tokenFor(requestText, options);
        return Boolean(attempts.get(token) || attemptStorageFor(options).getItem(token) || storageFor(options).getItem(token));
      }
      catch { return false; }
    },
    async submit(requestText, options = {}) {
      if (pending) return null;
      pending = true;
      try {
        const invalid = validateRequestText(requestText);
        if (invalid) return { ok: false, error: invalid };
        const storage = storageFor(options);
        const attemptStorage = attemptStorageFor(options);
        const token = await tokenFor(requestText, options);
        let key = attempts.get(token) || attemptStorage.getItem(token) || storage.getItem(token);
        if (options.usage?.can_submit === false && !key) return quotaError(options.usage);
        if (!key) {
          key = (options.createId || (() => globalThis.crypto.randomUUID()))();
          // Persist before sending: a reload after an ambiguous receipt must reuse this key.
          storage.setItem(token, key);
        }
        // Keep this tab's ambiguous receipt through another tab's acknowledgement and reload.
        attemptStorage.setItem(token, key);
        attempts.set(token, key);
        const result = await submitAgentRequest(requestText, { ...options, idempotencyKey: key });
        if (!result.uncertain) {
          attempts.delete(token);
          try {
            if (attemptStorage.getItem(token) === key) attemptStorage.removeItem(token);
            if (storage.getItem(token) === key) storage.removeItem(token);
          } catch { /* Keep an acknowledged response usable. */ }
        }
        return result;
      } catch {
        return { ok: false, error: '요청을 안전하게 저장하지 못했습니다. 브라우저 저장 공간을 확인한 뒤 다시 시도해 주세요.' };
      } finally {
        pending = false;
      }
    },
  };
}
