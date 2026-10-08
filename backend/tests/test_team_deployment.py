"""Guard background processing settings; a healthy HTTP service can still stall jobs."""
from pathlib import Path

import yaml


def test_api_worker_runs_without_http_and_preserves_observability_target():
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "cloudbuild.yaml").read_text(encoding="utf-8")
    )
    steps = {step["id"]: step for step in config["steps"]}
    api = steps["deploy-api"]["args"][1]
    for flag in (
        "--min=1", "--max=1", "--no-cpu-throttling",
        "--min-instances=default", "--max-instances=default",
    ):
        assert flag in api
    assert "--min-instances=0" not in api
    # Replacing all env vars would discard the configured shared Langfuse URL.
    assert "--set-env-vars=" not in api
    assert "--update-env-vars=" in api
    for setting in (
        "MCP_ENABLED=true", "WORKER_CONCURRENCY=5", "ENVIRONMENT=production", "LLM_MAX_TOKENS=2048",
        "INTERPRETER_PROMPT_PATH=/app/prompts/uhkegryo-interpreter-v4.md",
        "INTERPRETER_PROMPT_VERSION=uhkegryo-interpreter-v4",
        "STRUCTURED_OUTPUT_SKILL_PATH=/app/skills/structured-output/SKILL.md",
        "TERM_CARDS_PATH=/app/term-cards",
    ):
        assert setting in api
    mcp = steps["deploy-mcp"]["args"][1]
    assert "--no-allow-unauthenticated" in mcp
    assert "--no-cpu-throttling" not in mcp


def test_paid_worker_deployment_requires_complete_approval():
    import runpy
    root = Path(__file__).resolve().parents[2]
    validate = runpy.run_path(str(root / "scripts/check-team-operation.py"))["validate"]
    record = {k: "confirmed" for k in ("START", "END", "BUDGET", "BILLING_OWNER", "BILLING_ACCOUNT", "SHUTDOWN_OWNER", "SHUTDOWN_PROCEDURE")}
    record["APPROVED"] = "true"
    validate(record)
    import pytest
    for key in record:
        with pytest.raises(ValueError):
            validate({**record, key: " "})
    config = yaml.safe_load((root / "cloudbuild.yaml").read_text(encoding="utf-8"))
    assert config["steps"][0]["id"] == "check-team-operation"
    assert config["substitutions"]["_TEAM_OPERATION_APPROVED"] == "false"
