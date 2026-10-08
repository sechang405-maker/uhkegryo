"""Compose prompt pair defaults and startup validation."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path,version,ok", [("", "", True), ("v0", "", False), ("", "v4", False), ("v0", "v0", True), ("v4", "v4", True), (None, None, True)])
def test_compose_prompt_pair(tmp_path, path, version, ok):
    cli = shutil.which("docker")
    if not cli:
        pytest.skip("Docker CLI required for Compose interpolation")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(compose, encoding="utf-8")
    prompt_path = f"./prompts/uhkegryo-interpreter-{path}.md" if path else ""
    prompt_version = f"uhkegryo-interpreter-{version}" if version else ""
    (tmp_path / ".env").write_text(
        f"INTERPRETER_PROMPT_PATH={prompt_path}\nINTERPRETER_PROMPT_VERSION={prompt_version}\n" if path is not None else "",
        encoding="utf-8",
    )
    env = {k: v for k, v in os.environ.items() if k not in ("INTERPRETER_PROMPT_PATH", "INTERPRETER_PROMPT_VERSION")}
    env.update({key: "test-value" for key in re.findall(r"\$\{([A-Z_]+):\?", compose)})
    result = subprocess.run([cli, "compose", "config", "--format", "json"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    api = json.loads(result.stdout)["services"]["api"]
    assert api["environment"]["INTERPRETER_PROMPT_PATH"] == (prompt_path or "/app/prompts/uhkegryo-interpreter-v4.md")
    assert api["environment"]["INTERPRETER_PROMPT_VERSION"] == (prompt_version or "uhkegryo-interpreter-v4")
    assert api["command"][:2] == ["python", "-c"]
    with patch.dict(os.environ, api["environment"], clear=True), patch("os.execvp") as launch:
        if ok:
            exec(api["command"][2], {})
            launch.assert_called_once_with("uvicorn", ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"])
        else:
            with pytest.raises(SystemExit, match="Set both INTERPRETER_PROMPT_PATH and INTERPRETER_PROMPT_VERSION"):
                exec(api["command"][2], {})
            launch.assert_not_called()
