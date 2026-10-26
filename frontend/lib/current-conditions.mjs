import { RESTORE_ERROR } from './server-conversation.mjs';

function validId(value) {
  if (typeof value !== 'string' || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)) {
    throw new Error(RESTORE_ERROR);
  }
  return value;
}

function validItems(payload) {
  if (!Array.isArray(payload?.items)) throw new Error(RESTORE_ERROR);
  return payload.items.filter((item) => item && typeof item.term_id === 'string'
    && typeof item.label_ko === 'string' && typeof item.role === 'string');
}

export async function readCurrentConditions(sessionId, options = {}) {
  const response = await (options.fetchImpl || globalThis.fetch)(
    `/api/sessions/${validId(sessionId)}/conditions`,
    { credentials: 'include', cache: 'no-store', signal: options.signal },
  );
  if (!response.ok) throw new Error(RESTORE_ERROR);
  return validItems(await response.json());
}

export async function removeCurrentCondition(sessionId, termId, options = {}) {
  if (typeof termId !== 'string' || !termId || termId.length > 200) throw new Error(RESTORE_ERROR);
  const response = await (options.fetchImpl || globalThis.fetch)(
    `/api/sessions/${validId(sessionId)}/conditions/${encodeURIComponent(termId)}`,
    {
      method: 'DELETE', credentials: 'include', cache: 'no-store', signal: options.signal,
      headers: { 'X-Conversation-Action': 'remove-condition' },
    },
  );
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail?.detail || RESTORE_ERROR);
  }
  return validItems(await response.json());
}

export function createConditionRemovalController(apply) {
  let revision = 0;
  let sessionId = null;
  return {
    begin(id) { sessionId = id; return { id, revision: ++revision }; },
    reset(id) { sessionId = id; ++revision; },
    resolve(ticket, items) {
      if (ticket.id === sessionId && ticket.revision === revision) apply(items);
    },
  };
}
