from contextlib import nullcontext

from backend.services import conversation_context


class _ForbiddenAdapter:
    async def memory(self, *args, **kwargs):
        raise AssertionError("empty session has no memory to classify")


class _Trace:
    def stage(self, _name):
        return nullcontext()


def test_empty_session_skips_memory_classification_for_new_drawing_request():
    context = {
        "state": {"memory_version": 1, "constraints": {}},
        "recent": [],
        "sources": [],
        "previous_result": {},
    }
    operation = conversation_context.recall(
        None,
        {
            "request_text": "남성 캐릭터의 상체가 넓고 허리는 좁은 역삼각형 체형을 그리고 싶어.",
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
