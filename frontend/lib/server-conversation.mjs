import { upsertTurn, isTurnPending } from "./conversation.mjs";
import { createJobPoller, STATUS_LABELS } from "./job-polling.mjs";

export const RESTORE_ERROR = "대화를 복원하지 못했습니다. 다시 불러온 뒤 요청해 주세요.";
export const DELETE_CONFIRM = "이 대화를 영구 삭제할까요? 연결된 입력·답변·참고링크가 함께 삭제되며 복구할 수 없습니다. 다른 대화와 외부 Pinterest 원본은 삭제하지 않습니다.";
export async function ensureLocalProfile(options = {}) {
  const response = await (options.fetchImpl || globalThis.fetch)("/api/local/profile", {
    method: "POST", credentials: "include", cache: "no-store", signal: options.signal,
    headers: { "X-Conversation-Action": "profile" },
  });
  if (!response.ok) throw new Error(RESTORE_ERROR);
  return (await response.json()).persistent === true;
}
export async function deleteConversation(id, options = {}) {
  sessionId(id);
  const response = await (options.fetchImpl || globalThis.fetch)(`/api/sessions/${id}`, {
    method: "DELETE", credentials: "include", cache: "no-store", signal: options.signal,
    headers: { "X-Conversation-Action": "delete" },
  });
  if (response.status === 409) throw new Error("답변 처리 중인 대화는 완료 후 삭제할 수 있습니다.");
  if (response.status !== 204) throw new Error("대화를 삭제하지 못했습니다. 기록을 유지했으니 다시 시도해 주세요.");
}
async function read(path, options, method = "GET") {
  const response = await (options.fetchImpl || globalThis.fetch)(path, {
    method, credentials: "include", cache: "no-store", signal: options.signal,
  });
  if (!response.ok) throw new Error(RESTORE_ERROR);
  return response.json();
}
function sessionId(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)) throw new Error(RESTORE_ERROR);
  return value;
}
function validateSessions(items) {
  if (!Array.isArray(items)) throw new Error(RESTORE_ERROR);
  return items.map((item) => {
    sessionId(item?.session_id);
    if (typeof item.created_at !== "string" || Number.isNaN(Date.parse(item.created_at))) throw new Error(RESTORE_ERROR);
    return item;
  });
}
export async function listConversations(options = {}) {
  const sessions = new Map();
  for (let offset = 0; ; offset += 100) {
    const response = await (options.fetchImpl || globalThis.fetch)(`/api/sessions?limit=100&offset=${offset}`, {
      credentials: "include", cache: "no-store", signal: options.signal,
    });
    if (response.status === 401 && offset === 0) return [];
    if (!response.ok) throw new Error(RESTORE_ERROR);
    const items = validateSessions((await response.json())?.items);
    for (const item of items) sessions.set(item.session_id, item);
    if (items.length < 100) return [...sessions.values()];
  }
}
export async function createConversation(options = {}) {
  const created = await read("/api/sessions", options, "POST");
  validateSessions([created]);
  return created;
}
export async function restoreConversation(options = {}) {
  let id = options.sessionId;
  if (id) sessionId(id);
  else {
    const response = await (options.fetchImpl || globalThis.fetch)("/api/sessions?limit=1", {
      credentials: "include", cache: "no-store", signal: options.signal,
    });
    if (response.status === 401) return { sessionId: null, turns: [] };
    if (!response.ok) throw new Error(RESTORE_ERROR);
    const list = await response.json();
    if (!Array.isArray(list?.items)) throw new Error(RESTORE_ERROR);
    if (!list.items.length) return { sessionId: null, turns: [] };
    id = sessionId(list.items[0]?.session_id);
  }
  await read(`/api/sessions/${id}`, options);
  let turns = [];
  for (let offset = 0; ; offset += 100) {
    const page = await read(`/api/sessions/${id}/jobs?limit=100&offset=${offset}`, options);
    if (!Array.isArray(page?.items)) throw new Error(RESTORE_ERROR);
    for (const job of page.items) {
      if (!job.job_id || job.session_id !== id || typeof job.request_text !== "string"
        || !Object.hasOwn(STATUS_LABELS, job.job_status)) throw new Error(RESTORE_ERROR);
      turns = upsertTurn(turns, { id: job.job_id, request: job.request_text, job, demo: false });
    }
    if (page.items.length < 100) break;
  }
  const latest = turns.at(-1);
  if (latest) {
    const job = await read(`/api/jobs/${encodeURIComponent(latest.id)}`, options);
    if (job.job_id !== latest.id || job.session_id !== id
      || !Object.hasOwn(STATUS_LABELS, job.job_status)) throw new Error(RESTORE_ERROR);
    turns = upsertTurn(turns, { ...latest, job });
  }
  return { sessionId: id, turns };
}
export function resumeConversation(turns, options) {
  const pollers = turns.filter(isTurnPending).map((turn) => {
    const poller = createJobPoller(turn.id, {
      ...options,
      onUpdate: (job) => {
        if (job.job_id !== turn.id) return options.onError(turn.id, RESTORE_ERROR);
        options.onUpdate({ ...turn, job });
      },
      onError: (message) => options.onError(turn.id, message),
    });
    poller.start(turn.job?.poll_after_ms);
    return poller;
  });
  return { stop: () => pollers.forEach((poller) => poller.stop()) };
}

export function createHistoryLoader(options) {
  let controller;
  const cancel = () => { controller?.abort(); options.onState({ loading: false, error: "" }); };
  return { cancel, async open(entry) {
    cancel();
    if (entry.demo) { options.onJob(entry.job); return; }
    controller = new AbortController();
    const signal = controller.signal;
    options.onState({ loading: true, error: "" });
    try {
      const job = await read(`/api/jobs/${encodeURIComponent(entry.id)}`, { ...options, signal });
      if (signal.aborted) return;
      if (job.job_id !== entry.id || job.session_id !== entry.job.session_id
        || !["completed", "failed"].includes(job.job_status)) throw new Error("invalid history job");
      options.onJob(job);
      options.onState({ loading: false, error: "" });
    } catch {
      if (!signal.aborted) options.onState({ loading: false, error: "검색 기록을 불러오지 못했습니다. 다시 시도해 주세요." });
    }
  } };
}

