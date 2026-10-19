import { HOME_TERMS } from './home-catalog.mjs';

export function sessionTitle(session) {
  const terms = Array.isArray(session?.title_terms) ? session.title_terms : [];
  const names = terms.map(term => {
    const id = typeof term === 'string' ? term : term?.term_id;
    const label = typeof term?.label_ko === 'string' ? term.label_ko.trim() : '';
    return label || HOME_TERMS.find(card => card.term_id === id)?.label_ko || '이름 없는 텀카드';
  });
  return [...new Set(names)].join(' · ') || '검색 기록';
}
