import { createElement as h } from 'react';
import { SESSION_LIMIT_NOTICE } from '../lib/session-usage.mjs';

export default function SessionUsageNotice({ usage, busy, onNewSession }) {
  if (!usage) return null;
  return h('div', { className: 'session-usage', role: 'status', 'aria-live': 'polite' },
    h('span', { className: 'session-usage-count' }, `남은 메시지 ${usage.remaining_messages} / ${usage.message_limit}`),
    !usage.can_submit && h('div', { className: 'session-limit-notice' },
      h('p', null, SESSION_LIMIT_NOTICE),
      h('button', { type: 'button', disabled: busy, onClick: onNewSession }, '새 대화 시작')));
}
