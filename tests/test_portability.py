import os
import subprocess
import sys
import tomllib


def test_controller_root_override(tmp_path):
    env = dict(os.environ, HARDLINE_HOME=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-c", "from hardline.runtime import ROOT; print(ROOT)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str(tmp_path)


def test_generated_launcher_uses_controller_root(tmp_path, monkeypatch):
    from hardline import mcp

    root = tmp_path / "controller with spaces"
    root.mkdir()
    agent = tmp_path / "agent"
    agent.mkdir()
    monkeypatch.setattr(mcp, "ROOT", root)
    mcp.install_mcp_config("helper", agent)
    cfg = tomllib.loads((agent / ".codex/config.toml").read_text())
    assert cfg["mcp_servers"]["hardline"]["command"] == str(root / ".venv/bin/hardline")


def test_worker_home_denials_follow_current_user():
    from pathlib import Path

    from hardline.runtime import worker_config

    paths = worker_config()["permissions.hardline-worker"]["filesystem"]
    assert paths[str(Path.home() / ".ssh")] == "deny"
