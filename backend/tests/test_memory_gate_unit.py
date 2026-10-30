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
    requests = [
        "남성 캐릭터의 상체가 넓고 허리는 좁은 역삼각형 체형을 그리고 싶어.",
        "한쪽 다리에 체중을 싣고 골반과 어깨가 반대로 기울어진 포즈를 설명해줘.",
        "아래에서 올려다보는 로우 앵글 2점 투시로 건물을 그리고 싶어.",
    ]
    for request_text in requests:
        assert conversation_context.is_clear_new_request(request_text, context)
    assert not conversation_context.is_clear_new_request("좀 더 역동적으로 해줘.", context)
    assert not conversation_context.is_clear_new_request("지난 추천은? 이번에는 서 있는 자세 찾아줘", context)
    for index, request_text in enumerate(requests, 1):
        operation = conversation_context.recall(
            None,
            {
                "request_text": request_text,
                "job_id": f"00000000-0000-0000-0000-{index:012d}",
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


def test_grounded_followups_never_require_model_memory_json():
    context = {
        "state": {"constraints": {"pose_shift": {
            "role": "pose", "term_id": "pose_shift", "evidence": "weight shift",
            "source_job_id": "00000000-0000-4000-8000-000000000001",
        }}},
        "recent": [{"job_id": "00000000-0000-4000-8000-000000000001"}],
        "sources": [],
        "previous_result": {"reference_plan": {"terms": [{"term_id": "pose_shift"}]}},
    }

    recall = conversation_context.grounded_memory_route(
        context, "\ubc29\uae08 \ucd94\ucc9c\ud55c \uc870\uac74\uc744 \ub2e4\uc2dc \ubcf4\uc5ec\uc918."
    )
    mixed = conversation_context.grounded_memory_route(
        context, "\uadf8 \uc790\uc138\uc5d0 \ub85c\uc6b0 \uc575\uae00 \uc2dc\uc810\ub3c4 \uc12e\uc5b4\uc918."
    )
    refresh = conversation_context.grounded_memory_route(
        context, "\uc774\uc804 \uc870\uac74\uc740 \uc720\uc9c0\ud558\uace0 \ucc38\uace0 \uc774\ubbf8\uc9c0\ub9cc \uc0c8\ub85c \uac80\uc0c9\ud574\uc918."
    )

    assert recall.mode == mixed.mode == refresh.mode == "none"
    assert recall.reference_action == mixed.reference_action == "update"
    assert refresh.reference_action == "refresh_all"
