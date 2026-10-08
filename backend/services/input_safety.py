"""Deterministic, side-effect-free input safety gate."""

from __future__ import annotations

import re
import unicodedata


_SPACE = re.compile(r"\s+")
_KOREAN_OVERRIDE = re.compile(
    r"(?:이전|앞선|앞의|위|상기|기존|시스템|개발자).{0,24}"
    r"(?:지시|명령|규칙|안내|정책|프롬프트|제한).{0,24}"
    r"(?:무시|잊어|덮어|따르지\s*말|바꿔|변경|해제|제거|건너뛰)"
)
_ENGLISH_OVERRIDE = re.compile(
    r"(?:ignore|disregard|override|bypass|forget).{0,48}"
    r"(?:previous|prior|above|earlier|system|developer).{0,24}"
    r"(?:instruction|prompt|rule|guidance|policy)|"
    r"(?:do\s+not|don't)\s+(?:follow|obey).{0,48}"
    r"(?:previous|prior|above|earlier|system|developer).{0,24}"
    r"(?:instruction|prompt|rule|guidance|policy)"
)
_SECRET_VALUE_TARGET = (
    r"api\s*(?:key|키)|"
    r"(?:client|service|server|app(?:lication)?)[_\s-]*secret|"
    r"secret[_\s-]*(?:value|key|token|credential)|"
    r"비밀\s*(?:값|키)|password|암호|token|토큰|credential"
)
_SENSITIVE_TARGET = re.compile(
    r"system\s*(?:prompt|message)|developer\s*(?:message|instruction)|"
    r"시스템\s*(?:프롬프트|지시)|개발자\s*(?:메시지|지시)|"
    rf"(?:{_SECRET_VALUE_TARGET})|"
    r"(?:다른|타인의|other)\s*(?:사용자|user).{0,16}(?:검색\s*기록|history|session|data)"
)
_DISCLOSURE = re.compile(
    r"보여\s*줘|알려\s*줘|공개|출력|나열|제공|reveal|show|give|list|print|expose|return"
)
_LITERAL_SENSITIVE_REFERENCE = re.compile(
    rf"(?:{_SECRET_VALUE_TARGET})"
    r"(?:\s*(?:라는|이라고)\s*)?(?:문구|글자)"
)
_VISUAL_PROP_SUFFIX = re.compile(
    r"(?:을|를|의)?\s*(?:든|들고|쥔|소지한|던지는).{0,24}"
    r"(?:캐릭터|인물|포즈|일러스트|그림|레퍼런스)|"
    r"\s+(?:held|carried|wielded)\s+by\s+(?:a\s+)?"
    r"(?:character|figure|person)"
)
_VISUAL_PROP_PREFIX = re.compile(
    r"(?:character|figure|person).{0,24}(?:holding|carrying|wielding)\s+(?:a|an|the)?\s*$"
)
_REQUEST_SEGMENT_SEPARATOR = re.compile(r"[.!?。！？]+|\s+(?:그리고|and)\s+")
_HARMFUL_TARGET = re.compile(
    r"폭발물|폭탄|사제\s*무기|악성\s*코드|랜섬웨어|피싱|계정\s*탈취|불법\s*침입|"
    r"\bbombs?\b|\bexplosives?\b|\bweapons?\b|\bmalware\b|\bransomware\b|\bphishing\b|"
    r"\bcredential\s*theft\b|\billegal\s*intrusion\b"
)
_EXECUTION_INTENT = re.compile(
    r"제작|제조|만들|작성|실행|방법|절차|코드|조립|설치|탈취|침입|"
    r"how\s+(?:to|do\s+i)|build|make|write|execute|making|building|construction|assembly|"
    r"instructions?|steps?|code"
)
_STRONG_HARMFUL_EXECUTION = re.compile(
    r"(?:제작|제조|조립|설치|탈취|침입)(?:\s*(?:방법|법)|(?:해|하|을|하기))|"
    r"(?:construction|assembly)\s+(?:instructions?|steps?)|"
    r"(?:build|execute)\s+(?:it|that|this)\b"
)
_VISUAL_ACTION_SUBJECT = re.compile(
    r"(?:캐릭터|인물|포즈|일러스트|그림|레퍼런스|character|figure|pose|illustration|drawing|reference)"
    r"(?:을|를|의)?\s*$"
)
_SENSITIVE_COREFERENCE_DISCLOSURE = re.compile(
    r"(?:그|해당)\s*(?:api\s*(?:key|키)|키|비밀\s*값|password|암호|token|토큰|credential|"
    r"secret[_\s-]*(?:value|key|token|credential))(?:을|를)?\s*"
    r"(?:보여\s*줘|알려\s*줘|공개|출력|나열|제공)|"
    r"(?:reveal|give|list|print|expose|return)\s+"
    r"(?:it|that|this|the\s+(?:key|token|credential|secret))\b"
)

_OUT_OF_SCOPE_INPUT = re.compile(
    r"이미지.{0,12}(?:생성|그려|편집)|(?:생성|그려|편집).{0,12}이미지|"
    r"(?:올린|첨부한|업로드한).{0,16}(?:그림|이미지).{0,18}(?:분석|판정|읽어)|"
    r"(?:그림|이미지).{0,16}(?:분석|판정|읽어).{0,18}(?:올린|첨부|업로드)|"
    r"(?:현존|특정).{0,16}(?:일러스트레이터|작가|화가).{0,18}(?:화풍|스타일)|"
    r"(?:화풍|스타일).{0,18}(?:그대로|복제|따라).{0,16}(?:그려|생성)|"
    r"pinterest.{0,40}(?:100개|모아서|크롤링|내려받|다운로드|저장)|"
    r"(?:핀|이미지).{0,24}(?:대량으로|100개).{0,24}(?:다운로드|내려받|저장)"
)
_SCOPE_CLAUSE_SEPARATOR = re.compile(r"[.!?。！？,;]+")
_NEGATED_SCOPE_ACTION = re.compile(
    r"^\s*(?:(?:은|는|을|를|이|가)\s*)?(?:하지\s*(?:말고|않고|마|않)|"
    r"안\s*(?:해도|하고|할|하는|함)|지\s*(?:말고|않고|않)|필요\s*없|원하지\s*않|(?:말고|없이)(?=\s|$))"
)


def normalize_input_text(request_text: str) -> str:
    """Normalize user text for deterministic safety and evidence checks."""
    normalized = unicodedata.normalize("NFKC", request_text).casefold()
    without_format_controls = "".join(
        char for char in normalized if unicodedata.category(char) != "Cf"
    )
    return _SPACE.sub(" ", without_format_controls).strip()


def _requests_sensitive_disclosure(text: str) -> bool:
    non_literal_text = _LITERAL_SENSITIVE_REFERENCE.sub("", text)
    matches = list(_SENSITIVE_TARGET.finditer(non_literal_text))
    if not matches or not _DISCLOSURE.search(text):
        return False
    if _SENSITIVE_COREFERENCE_DISCLOSURE.search(non_literal_text):
        return True
    return any(
        not _is_visual_prop_reference(non_literal_text, match) for match in matches
    )


def _is_visual_prop_reference(text: str, match: re.Match[str]) -> bool:
    suffix = text[match.end() :]
    prefix = text[max(0, match.start() - 48) : match.start()]
    return bool(
        _VISUAL_PROP_SUFFIX.match(suffix) or _VISUAL_PROP_PREFIX.search(prefix)
    )


def _requests_harmful_execution(text: str) -> bool:
    harmful_target_seen = False
    for segment in _REQUEST_SEGMENT_SEPARATOR.split(text):
        matches = list(_HARMFUL_TARGET.finditer(segment))
        harmful_target_seen = harmful_target_seen or bool(matches)
        if harmful_target_seen and _has_strong_harmful_execution(segment):
            return True
        if not _EXECUTION_INTENT.search(segment):
            continue
        if any(
            not _is_visual_prop_reference(segment, match)
            for match in matches
        ):
            return True
    return False


def _has_strong_harmful_execution(segment: str) -> bool:
    for match in _STRONG_HARMFUL_EXECUTION.finditer(segment):
        prefix = segment[max(0, match.start() - 24) : match.start()]
        if not _VISUAL_ACTION_SUBJECT.search(prefix):
            return True
    return False


def is_unsafe_input(request_text: str) -> bool:
    """Return whether a request matches the deterministic unsafe-input policy."""
    text = normalize_input_text(request_text)
    return bool(
        _KOREAN_OVERRIDE.search(text)
        or _ENGLISH_OVERRIDE.search(text)
        or _requests_sensitive_disclosure(text)
        or _requests_harmful_execution(text)
    )


def is_out_of_scope_input(request_text: str) -> bool:
    """Return whether a request asks for a deterministic unsupported operation."""
    clauses = _SCOPE_CLAUSE_SEPARATOR.split(normalize_input_text(request_text))
    return any(
        not _NEGATED_SCOPE_ACTION.match(clause[match.end():])
        for clause in clauses for match in _OUT_OF_SCOPE_INPUT.finditer(clause)
    )
