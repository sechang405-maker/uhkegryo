"""Guard the deployment command against deleting separately configured env vars."""
from pathlib import Path

import yaml


def test_api_deploy_preserves_existing_langfuse_host():
    config = yaml.safe_load((Path(__file__).resolve().parents[2] / "cloudbuild.yaml").read_text(encoding="utf-8"))
    api = next(step for step in config["steps"] if step["id"] == "deploy-api")["args"][1]
    assert "--update-env-vars=" in api
    assert not any(flag in api for flag in ("--set-env-vars", "--clear-env-vars", "--remove-env-vars"))
    assert "LANGFUSE_HOST=" not in api
