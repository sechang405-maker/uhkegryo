export const SESSION_MESSAGE_LIMIT = 20;
export const SESSION_LIMIT_NOTICE = '이 대화의 메시지 20회를 모두 사용했습니다. 새 대화에서 이어가세요.';

// History pages are incomplete; only the server's accepted-job total is usage.
export function sessionUsage(value) {
  if (!Number.isInteger(value?.message_count) || value.message_count < 0) return null;
  const count = value.message_count;
  return { message_count: count, message_limit: SESSION_MESSAGE_LIMIT,
    remaining_messages: Math.max(0, SESSION_MESSAGE_LIMIT - count),
    can_submit: count < SESSION_MESSAGE_LIMIT && value.can_submit !== false };
}

export function quotaError(usage) {
  return { ok: false, error: SESSION_LIMIT_NOTICE, failureCode: 'session_message_limit_reached', retryable: false, usage };
}
