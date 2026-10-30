from contextlib import nullcontext

from backend.services import conversation_context


class _ForbiddenAdapter:
    async def memory(self, *args, **kwargs):
        raise AssertionError("empty session has no memory to classify")


class _Trace:
    def stage(self, _name):
        return nullcontext()


def test_drawing_inflection_skips_memory_classification_for_new_request():
    context = {
        "state": {"memory_version": 1, "constraints": {}},
        "recent": [],
        "sources": [],
        "previous_result": {},
    }
    request_text = "남성 캐릭터의 상체가 넓고 허리는 좁은 역삼각형 체형을 그리고 싶어."
    assert conversation_context.is_clear_new_request(request_text, context)
    assert not conversation_context.is_clear_new_request("좀 더 역동적으로 해줘.", context)
    assert not conversation_context.is_clear_new_request("지난 추천은? 이번에는 서 있는 자세 찾아줘", context)
    operation = conversation_context.recall(
        None,
        {
            "request_text": request_text,
            "job_id": "00000000-0000-0000-0000-000000000001",
            "session_id": "00000000-0000-0000-0000-000000000002",
            "attempt": 1,
            "max_attempts": 3,
        },
        context,
        _ForbiddenAdapter(),
        _Trace(),
    )
    try:
        operation.send(None)
    except StopIteration as completed:
        result = completed.value
    else:
        raise AssertionError("recall unexpectedly suspended")
    assert result == (None, False)
