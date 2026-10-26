import pytest

from backend.services import reference_intent


@pytest.mark.parametrize("text", [
    "발레 동작을 용어에 추가하고 싶어.",
    "내 전용 텀카드를 만들고 싶어",
    "새로운 포즈를 용어로 등록해줘",
])
def test_personal_term_creation_intent_is_not_reference_search(text):
    assert reference_intent.requests_personal_term_creation(text)


def test_ordinary_reference_addition_is_not_personal_term_creation():
    assert not reference_intent.requests_personal_term_creation("발레 동작 레퍼런스를 검색해줘")


def test_personal_term_creation_guidance_matches_the_available_saved_flow():
    guidance = reference_intent.PERSONAL_TERM_CREATION_GUIDANCE
    assert "새 용어 만들기" in guidance
    assert "AI 초안" in guidance
    assert "확인·수정" in guidance
    assert "명시적 저장" in guidance
    assert "활성 개인 용어" in guidance
    assert "그래프" in guidance
    assert "검색" in guidance
    assert "대화" in guidance
    assert "익명 로컬 프로필" in guidance
    assert "초안만" in guidance
    assert "다음 단계" not in guidance


@pytest.mark.parametrize('text', [
    '이런 캐릭터를 그리고 싶어', '그런 포즈 보고 싶어', '찾아줘',
    '서 있는 캐릭터를 그리고 싶어요', '그 설명대로 레퍼런스 보여줘',
    '전에 "찾아줘"라고 했던 거 기억나? 지금은 정면으로 찾아줘',
    'How do I draw this? Find a reference too.',
    '그려보고 싶어',
])
def test_current_reference_request(text):
    assert reference_intent.wants_reference(text)


@pytest.mark.parametrize('text', [
    '그리고 싶지 않아', '그런 포즈 보고 싶지 않아', '검색하지 말고 설명해줘',
    '"그리고 싶어"라는 말은 검색 요청이 아니야', '전에 찾아줘라고 했었지?',
    '캐릭터를 어떻게 그려야 해?', '그림을 잘 그리고 싶어',
    '서 있는 포즈를 그리고 싶은데 어떻게 그려?', 'I want to learn how to draw',
    'Do not search. Explain the pose.', '"find references" is a quoted example',
    '찾아달라는 게 아니라 설명해줘',
    '찾아줘라는 말은 무슨 뜻이야?', '그리고 싶어라는 문장을 번역해줘',
    '검색해 달라는 건 아니야', '검색은 원하지 않아',
    '안 그리고 싶어', "I don't want to draw this",
])
def test_non_reference_intent(text):
    assert not reference_intent.wants_reference(text)


def test_quoted_prohibition_does_not_cancel_current_search():
    text = '아까 "검색하지 마"라고 했지만 지금은 찾아줘'
    assert not reference_intent.search_forbidden(text)
    assert reference_intent.wants_reference(text)


@pytest.mark.parametrize('text', ['1번 말고 2번으로 찾아줘', '2번은 찾지 말고 1번 찾아줘'])
def test_scoped_candidate_exclusion_keeps_current_positive_search(text):
    assert reference_intent.wants_reference(text)
    assert not reference_intent.search_forbidden(text)


@pytest.mark.parametrize('text', ['2번 찾지 마', '검색하지 말고 1번을 설명해줘'])
def test_prohibition_remains_binding_without_later_scoped_search(text):
    assert reference_intent.search_forbidden(text)
    assert not reference_intent.wants_reference(text)
