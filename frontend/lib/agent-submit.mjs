const GENERIC_ERROR = "요청을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.";
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

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
        "Idempotency-Key": createId(),
      },
      body: JSON.stringify({ request_text: requestText, ...(options.sessionId ? { session_id: options.sessionId } : {}) }),
    });
    const payload = await response.json();
    if (response.status !== 202) {
      return {
        ok: false,
        error: typeof payload?.user_message === "string" && payload.user_message.trim()
          ? payload.user_message
          : GENERIC_ERROR,
      };
    }
    if (typeof payload?.job_id !== "string" || !payload.job_id) {
      return { ok: false, error: GENERIC_ERROR };
    }
    return { ok: true, jobId: payload.job_id, pollAfterMs: payload.poll_after_ms };
  } catch {
    return { ok: false, error: GENERIC_ERROR };
  }
}

export function createSubmissionController() {
  let pending = false;
  return {
    isPending: () => pending,
    async submit(requestText, options) {
      if (pending) return null;
      pending = true;
      try {
        return await submitAgentRequest(requestText, options);
      } finally {
        pending = false;
      }
    },
  };
}
