import shutil, subprocess, sys
from pathlib import Path

import pytest, yaml

from scripts.cloud_run_mcp_ingress import configure_mcp_service, ingress_name

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(("service", "expected"), [
    (None, "mcp"),
    ({"spec": {"template": {"spec": {"containers": [{"name": "legacy", "ports": [8000]}]}}}}, "legacy"),
    ({"spec": {"template": {"spec": {"containers": [{"ports": [8000]}]}}}}, "__default__"),
])
def test_ingress_target(service, expected):
    assert ingress_name(service) == expected


def test_unnamed_ingress_becomes_mcp_with_searxng_sidecar():
    service = {"apiVersion": "serving.knative.dev/v1", "kind": "Service", "metadata": {"name": "mcp"}, "spec": {"template": {"spec": {"containers": [{"image": "old", "ports": [{"containerPort": 8000}], "env": [{"name": "KEEP", "value": "yes"}]}]}}}}
    configured = configure_mcp_service(service, "mcp-image", "searxng-image")
    containers = configured["spec"]["template"]["spec"]["containers"]
    assert [(c["name"], c["image"], c.get("ports")) for c in containers] == [("mcp", "mcp-image", [{"containerPort": 8000}]), ("searxng", "searxng-image", None)]
    assert containers[0]["env"][0] == {"name": "KEEP", "value": "yes"}
    assert containers[0].get("dependsOn") is None
    annotations = configured["spec"]["template"]["metadata"]["annotations"]
    assert annotations["run.googleapis.com/container-dependencies"] == '{"mcp":["searxng"]}'
    assert containers[1]["env"][0]["valueFrom"]["secretKeyRef"] == {"name": "SEARXNG_SECRET", "key": "latest"}


def test_cloudbuild_bash_blocks_are_valid():
    config = yaml.safe_load((ROOT / "cloudbuild.yaml").read_text(encoding="utf-8"))
    deploy = next(step for step in config["steps"] if step["id"] == "deploy-mcp")["args"][1]
    assert "services replace /workspace/mcp-deploy.json --region=\"${_REGION}\" --project=\"${PROJECT_ID}\" --dry-run" in deploy
    git = shutil.which("git")
    bash = str(Path(git).parent.parent / "usr" / "bin" / "bash.exe") if git and sys.platform == "win32" else shutil.which("bash")
    for step in config["steps"]:
        if step.get("entrypoint") == "bash":
            result = subprocess.run([bash, "-n"], input=step["args"][1], capture_output=True, text=True)
            assert result.returncode == 0, f"{step['id']}: {result.stderr}"
