import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.schemas.models import InterpretationOutput
from backend.services.llm import LLMConfigurationError
from scripts import run_ollama_eval as runner


def _interpretation():
    return InterpretationOutput(
        interpretation_state="select_terms",
        answer_text="마른 체형의 기준을 확인해 보세요.",
        selections=[{
            "role": "body",
            "term_id": "body_slim",
            "evidence": ["마른"],
            "confidence": 0.9,
        }],
    )


def _personal_response():
    payload = {
        "role": "pose",
        "label_ko": "비틀어 기대기",
        "label_en": "Twisted lean pose",
        "plain_meaning_ko": "몸통을 비틀면서 한쪽으로 기대는 자세입니다.",
        "reference_checkpoints_ko": ["어깨선과 골반선이 반대로 기우는지 확인합니다."],
        "cautions_ko": ["허리만 꺾이지 않게 몸통 전체의 방향을 봅니다."],
        "aliases_ko": ["비틀어 기댄 자세"],
        "query_fragments_en": ["twisted leaning pose reference"],
        "proposal_kind": "descriptive",
        "uncertainty_ko": None,
    }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))],
        usage=None,
    )


class FakeAdapter:
    def __init__(self):
        self.interpret_calls = 0
        self.request_calls = 0

    async def interpret(self, *_args, **_kwargs):
        self.interpret_calls += 1
        return _interpretation()

    async def _request(self, *_args, **_kwargs):
        self.request_calls += 1
        return _personal_response()


def test_fixed_selection_and_dry_run_do_not_construct_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "make_adapter", lambda: pytest.fail("transport created"))
    with pytest.raises(ValueError):
        runner.load_cases(list(runner.CASE_IDS[:-1]))
    with pytest.raises(ValueError):
        runner.load_cases([runner.CASE_IDS[0]] * 30)

    info = asyncio.run(runner.run(tmp_path / "dry", runner.CASE_IDS, "a" * 40))

    assert info["mode"] == "dry_run"
    assert info["requested_model"] == "qwen3.5:4b-q4_K_M"
    assert info["quantization"] == "Q4_K_M"
    assert info["maximum_generations"] == 30
    assert len(info["selected_case_ids"]) == 30
    assert not (tmp_path / "dry" / "results.jsonl").exists()


def test_dry_run_records_approved_9b_model(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "make_adapter", lambda *_args: pytest.fail("transport created"))

    info = asyncio.run(runner.run(
        tmp_path / "dry-9b",
        runner.CASE_IDS,
        "e" * 40,
        model="qwen3.5:9b-q4_K_M",
    ))

    assert info["requested_model"] == "qwen3.5:9b-q4_K_M"
    assert info["quantization"] == "Q4_K_M"


def test_unapproved_eval_model_is_rejected_before_output(tmp_path):
    output = tmp_path / "unapproved"

    with pytest.raises(ValueError, match="approved evaluation model"):
        asyncio.run(runner.run(
            output,
            runner.CASE_IDS,
            "f" * 40,
            model="some-other-model",
        ))

    assert not output.exists()


def test_execute_calls_each_model_backed_case_at_most_once(tmp_path):
    fake = FakeAdapter()

    asyncio.run(runner.run(
        tmp_path / "run", runner.CASE_IDS, "b" * 40,
        execute=True, adapter_factory=lambda: fake,
    ))

    rows = [json.loads(line) for line in (tmp_path / "run" / "results.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()]
    assert len(rows) == 30
    assert fake.interpret_calls == 20
    assert fake.request_calls == 6
    assert sum(row["adapter_attempts"] for row in rows) == 26
    assert all(row["adapter_attempts"] <= 1 for row in rows)
    assert {row["status"] for row in rows} <= {
        "completed", "deterministic_gate", "invalid_or_failed"
    }
    assert (tmp_path / "run" / "review.md").exists()


def test_configuration_failure_stops_later_model_calls_and_sanitizes_output(tmp_path):
    class FailingAdapter(FakeAdapter):
        async def interpret(self, *_args, **_kwargs):
            self.interpret_calls += 1
            raise LLMConfigurationError("SECRET_LOCAL_PATH")

    fake = FailingAdapter()
    asyncio.run(runner.run(
        tmp_path / "failed", runner.CASE_IDS, "c" * 40,
        execute=True, adapter_factory=lambda: fake,
    ))

    result_text = (tmp_path / "failed" / "results.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in result_text.splitlines()]
    assert fake.interpret_calls == 1
    assert fake.request_calls == 0
    assert rows[0]["status"] == "configuration_error"
    assert any(row["status"] == "not_run" for row in rows[1:])
    assert "SECRET_LOCAL_PATH" not in result_text


def test_output_directory_is_never_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    with pytest.raises(FileExistsError):
        asyncio.run(runner.run(output, runner.CASE_IDS, "d" * 40))
