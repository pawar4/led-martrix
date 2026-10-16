import os
import stat
import subprocess

import pytest

SCRIPT = os.path.abspath("scripts/set-password.sh")
ORIGINAL = "# Read by the service\nMATRIX_TOKEN=oldoldoldold\n#MATRIX_AI_MODEL=claude-haiku-5-5\n"


@pytest.fixture
def env(tmp_path):
    """An env file, and a fake systemctl that records how it was called."""
    env_file = tmp_path / "led-matrix.env"
    env_file.write_text(ORIGINAL)
    env_file.chmod(0o600)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "systemctl.log"
    fake = bin_dir / "systemctl"
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
    fake.chmod(0o755)
    return env_file, log, {**os.environ, "ENV_FILE": str(env_file), "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def run(env, typed):
    env_file, log, environ = env
    return subprocess.run(["bash", SCRIPT], input=typed, capture_output=True, text=True, env=environ)


def test_sets_the_password_keeps_the_rest_and_restarts(env):
    env_file, log, _ = env
    result = run(env, "pizza-night\npizza-night\n")
    assert result.returncode == 0, result.stderr
    assert env_file.read_text() == "# Read by the service\n#MATRIX_AI_MODEL=claude-haiku-5-5\nMATRIX_TOKEN=pizza-night\n"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert log.read_text().strip() == "restart led-matrix-assistant"


def test_adds_the_line_when_there_was_none(env):
    env_file, _, _ = env
    env_file.write_text("#MATRIX_AI_MODEL=x\n")
    assert run(env, "pizza-night\npizza-night\n").returncode == 0
    assert env_file.read_text() == "#MATRIX_AI_MODEL=x\nMATRIX_TOKEN=pizza-night\n"


@pytest.mark.parametrize("typed, message", [
    ("pizza-night\npizza-nite\n", "differ"),
    ("short\nshort\n", "6 to 64"),
    ("has space1\nhas space1\n", "6 to 64"),
    ("quo'te-pass\nquo'te-pass\n", "6 to 64"),
    ("\n\n", "6 to 64"),
])
def test_rejects_a_bad_password_and_changes_nothing(env, typed, message):
    env_file, log, _ = env
    result = run(env, typed)
    assert result.returncode != 0 and message in result.stderr
    assert env_file.read_text() == ORIGINAL
    assert not log.exists()


def test_says_to_use_sudo_when_the_file_is_not_writable(env):
    env_file, log, environ = env
    environ["ENV_FILE"] = str(env_file.parent / "missing.env")
    result = run((env_file, log, environ), "pizza-night\npizza-night\n")
    assert result.returncode != 0 and "run with sudo" in result.stderr
