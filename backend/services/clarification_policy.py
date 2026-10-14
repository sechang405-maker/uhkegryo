"""Bounded public wording and a no-extra-model-call repetition guard."""
import re
from difflib import SequenceMatcher

from backend.services.input_safety import normalize_input_text

CATALOG_FALLBACK = '현재 제공하는 레퍼런스로 이 조건을 정확히 표현하기 어렵습니다. 홈의 용어 목록에서 가까운 자세를 골라 볼 수 있어요.'
REPEATED_FALLBACK = '같은 확인을 반복하지 않겠습니다. 기존 조건은 유지하며, 홈의 용어 목록에서 참고할 자세를 직접 고를 수 있어요.'
_INTERNAL = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|'
    r'\b(?:body|pose|view|perspective|layout|composition)_[a-z0-9_]+|'
    r'prompt|system|developer|api[_\s-]*key|password|secret|token|'
    r'term[_\s-]*id|active_cards|schema|confidence|mcp|'
    r'시스템|프롬프트|내부\s*(?:ID|아이디|식별자|정책)|개발자\s*(?:메시지|지시)|비밀|인증키|토큰', re.I)


def public_wording(text, fallback):
    if not isinstance(text, str):
        return fallback
    value = text.strip()
    normalized = normalize_input_text(value)
    if (not value or len(value) > 500 or _INTERNAL.search(normalized)
            or re.search(r'https?://|www\.|[<>`\[\]{}]|[\x00-\x08\x0b-\x1f]', normalized)):
        return fallback
    return value


def repeated_question(question, context):
    pending = (context or {}).get('state', {}).get('pending_question')
    context = context or {}
    def key(text):
        return re.sub(r'[^\w]', '', normalize_input_text(text))
    proposed = key(question)
    previous = ([pending] if pending else []) + [item.get('question') for item in context.get('recent', []) if item.get('question')]
    return any(SequenceMatcher(None, proposed, key(old)).ratio() >= 0.85 for old in previous)
