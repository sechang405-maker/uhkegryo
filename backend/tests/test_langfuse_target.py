"""Environment precedence shared by worker and LLM tracing clients."""
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.shared.config import Settings


@pytest.mark.parametrize("host,base,expected", [
    (None, None, "http://localhost:3000"),
    ("https://shared.example", None, "https://shared.example"),
    ("http://localhost:3000", "https://shared.example", "https://shared.example"),
])
def test_langfuse_target(monkeypatch, host, base, expected):
    for name, value in (("LANGFUSE_HOST", host), ("LANGFUSE_BASE_URL", base)):
        monkeypatch.delenv(name, raising=False)
        if value is not None:
            monkeypatch.setenv(name, value)
    assert Settings(_env_file=None, database_url="postgresql://test").langfuse_host == expected


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell required")
def test_switch_restores_local_keys_and_preserves_other_settings(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "set-langfuse-target.ps1"
    shutil.copyfile(Path(__file__).resolve().parents[2] / "scripts" / script.name, script)
    env = tmp_path / ".env"
    env.write_text("OTHER=keep\nLANGFUSE_PUBLIC_KEY=pk-local\nLANGFUSE_SECRET_KEY=sk-local\n")
    (tmp_path / ".env.langfuse-gcp").write_text(
        "LANGFUSE_APP_URL=https://shared.example\nLANGFUSE_PUBLIC_KEY=pk-shared\nLANGFUSE_SECRET_KEY=sk-shared\n")
    for target in ("shared", "shared", "local"):
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script), "-Target", target], check=True, capture_output=True)
        content = env.read_text()
        assert "OTHER=keep" in content
        assert content.count("LANGFUSE_SECRET_KEY=") == 1
        assert f"LANGFUSE_SECRET_KEY=sk-{target}" in content
    assert "LANGFUSE_APP_URL=\n" in env.read_text()
    assert "LANGFUSE_BASE_URL=http://localhost:3000" in env.read_text()
