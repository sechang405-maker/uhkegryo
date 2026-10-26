"""Conservative current-turn reference intent, independent of model routing.

Quoted examples and past requests are evidence, never executable instructions.
These guards authorize reference handling; catalog/evidence validation still decides
which cards, if any, can actually be searched.
"""
import re


PERSONAL_TERM_CREATION_GUIDANCE = (
    "새 개인 용어는 ‘새 용어 만들기’를 눌러 설명 입력 → AI 초안 확인·수정 → 명시적 저장 순서로 만들 수 있습니다. "
    "초안만 만든 상태에서는 그래프·검색·대화에 반영되지 않습니다. "
    "명시적으로 저장한 활성 개인 용어는 이 브라우저의 익명 로컬 프로필에 속하며 "
    "그래프·검색·이후 대화에 반영됩니다."
)


def current_action_text(text):
    text = re.sub(r'"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)\'[^\'\n]*\'', ' ', text)
    scoped = re.search(r'\b[1-3]\s*번(?:은|는|을|를)?\s*찾지\s*말고\s*(.+)$', text)
    if scoped and re.search(r'찾아(?:줘|주세요)|검색해', scoped[1]):
        text = text[:scoped.start()] + scoped[1]
    # A later explicit current clause supersedes a narrated past instruction.
    parts = re.split(r'지금은|지금부터|이제는|\b(?:now|this time)\b', text, flags=re.I)
    if len(parts) > 1:
        return parts[-1].strip()
    clauses = re.split(r'[.!?。！？\n]', text)
    return ' '.join(clause for clause in clauses if not re.search(
        r'기억(?:나|해|하|해요)|했었|했지|했더|했는데|했던|했나|했어|했나요|달라고\s*했|'
        r'\b(?:remember|recalled|previously|earlier|yesterday)\b', clause, re.I)).strip()


def requests_personal_term_creation(text):
    """Identify explicit requests to create/register a new term card.

    This is intentionally narrower than ordinary requests to add an existing
    condition to the current search.
    """
    current = current_action_text(text)
    return bool(re.search(
        r'(?:용어|텀\s*카드)(?:에|를|을|로)?[^.!?\n]{0,32}(?:추가|등록|만들|생성)|'
        r'(?:추가|등록|만들|생성)[^.!?\n]{0,24}(?:용어|텀\s*카드)',
        current,
        re.I,
    ))


def search_forbidden(text):
    text = current_action_text(text)
    return bool(re.search(
        r'(?:검색|찾기|레퍼런스|이미지)(?:은|는|을|를|도)?\s*(?:하지\s*마|하지\s*말|안\s*해|금지|필요\s*없)|'
        r'찾(?:아|지)\s*(?:주지\s*마|주지\s*말|마|말)|찾아달라는\s*게\s*아니|'
        r'검색(?:해)?\s*달라는\s*(?:건|게|것은)\s*아니|검색(?:은|을)?\s*원하지\s*않|'
        r'\b(?:do not|don.t|never|no)\s+(?:find|search|references?)\b', text, re.I))


def wants_reference(text):
    text = current_action_text(text)
    if search_forbidden(text):
        return False
    if re.search(r'(?:찾아줘|그리고\s*싶어|검색해)(?:라는|란)\s*(?:말|문장|표현)|번역해', text):
        return False
    explicit = re.search(
        r'찾아(?:줘|주|봐|보|볼|줄)|찾(?:고\s*싶|아야)|검색(?:해|하|을|해줘)|'
        r'(?:레퍼런스|참고\s*(?:자료|이미지)|이미지)(?:를|도|좀)?\s*(?:보여|보고\s*싶|원해)|'
        r'\b(?:find|search|show\s+(?:me\s+)?(?:a\s+)?references?)\b', text, re.I)
    if explicit:
        return True
    if re.search(r'안\s*(?:그리고|그려\s*보고)|그리(?:고|는\s*것을)\s*싶지|'
                 r'\b(?:don.t|do not|never)\s+want\s+to\s+draw\b', text, re.I):
        return False
    if re.search(r'어떻게|그리는\s*(?:법|방법)|잘\s*그리고|연습|배우|걱정|'
                 r'\b(?:how|learn|practice|worr\w*)\b', text, re.I):
        return False
    return bool(re.search(
        r'(?:그리고|그려\s*보고)\s*싶(?:어|어요|다|은데|습니다)|(?:포즈|자세|캐릭터|구도|그런|이런|그런\s*포즈)'
        r'[^.!?]{0,20}보고\s*싶(?:어|어요|다)|\b(?:want|would like)\s+to\s+draw\b', text, re.I))


def explicit_non_search(text):
    """Only unmistakable advice/meta/negative desire; ordinary edits remain open."""
    current = current_action_text(text)
    return not wants_reference(text) and bool(re.search(
        r'어떻게|그리는\s*(?:법|방법)|(?:라는|란)\s*(?:말|문장|표현)|번역해|'
        r'안\s*(?:그리고|그려\s*보고)|(?:그리고|보고)\s*싶지|'
        r'\b(?:how\s+(?:do|can|should|to)|learn\s+how|don.t\s+want|do\s+not\s+want)\b', current, re.I))
