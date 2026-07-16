"""Tests for the pass(1) credential source in lib/env.py.

Covers:
  - missing `pass` binary returns {}
  - successful lookups return parsed key/value pairs at the prefix convention
  - first-line extraction + whitespace stripping
  - subprocess timeout / OSError are swallowed
  - the path prefix is honored (default + LAST30DAYS_PASS_PREFIX override)
  - get_config merges pass below keychain and below explicit env, and labels
    _CONFIG_SOURCE = 'pass' when pass is the effective source
  - lib/env.py KEYCHAIN_KEYS and setup-pass.sh ALL_KEYS stay in lockstep
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from lib import env

SETUP_PASS_SH = Path(__file__).resolve().parents[1] / "skills" / "last30days" / "scripts" / "setup-pass.sh"

# ---------------------------------------------------------------------------
# _load_pass unit tests
# ---------------------------------------------------------------------------


def _run_result(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")






def test_load_pass_takes_first_line_only():
    # pass entries keep the secret on line 1; metadata may follow.
    with mock.patch("shutil.which", return_value="/usr/bin/pass"), \
         mock.patch("subprocess.run", return_value=_run_result(0, "sk-secret\nurl: https://x\nuser: bob\n")):
        assert env._load_pass(["OPENAI_API_KEY"], "last30days/") == {"OPENAI_API_KEY": "sk-secret"}


def test_load_pass_strips_whitespace():
    with mock.patch("shutil.which", return_value="/usr/bin/pass"), \
         mock.patch("subprocess.run", return_value=_run_result(0, "  hello-key  \n")):
        assert env._load_pass(["FOO"], "last30days/") == {"FOO": "hello-key"}












# ---------------------------------------------------------------------------
# get_config integration tests (pass merged below keychain and explicit env)
# ---------------------------------------------------------------------------














def test_get_config_pass_prefix_resolved_from_config_file(clean_env, tmp_path, monkeypatch):
    # LAST30DAYS_PASS_PREFIX set in the .env config layer (not shell-exported)
    # must reach _load_pass — i.e. the prefix is resolved at call time.
    cfg_file = tmp_path / "global.env"
    cfg_file.write_text("LAST30DAYS_PASS_PREFIX=secrets/l30/\n")
    monkeypatch.setattr(env, "CONFIG_FILE", cfg_file)
    seen = {}

    def fake_load_pass(keys, prefix):
        seen["prefix"] = prefix
        return {}

    with mock.patch.object(env, "_load_keychain", return_value={}), \
         mock.patch.object(env, "_load_pass", side_effect=fake_load_pass):
        env.get_config()

    assert seen["prefix"] == "secrets/l30/"


def test_get_config_openai_key_can_come_from_pass(clean_env):
    with mock.patch.object(env, "_load_keychain", return_value={}), \
         mock.patch.object(env, "_load_pass", return_value={"OPENAI_API_KEY": "sk-from-pass"}):
        cfg = env.get_config()
    assert cfg["OPENAI_API_KEY"] == "sk-from-pass"
    assert cfg["OPENAI_AUTH_SOURCE"] == "api_key"


# ---------------------------------------------------------------------------
# Drift guard: lib/env.py KEYCHAIN_KEYS and setup-pass.sh ALL_KEYS must stay in
# lockstep, same as the Keychain helper. A mismatch means a key stored via the
# helper wouldn't be picked up by the loader, or vice versa.
# ---------------------------------------------------------------------------


def _parse_all_keys_from_shell(script: Path) -> list[str]:
    text = script.read_text(encoding="utf-8")
    match = re.search(r"ALL_KEYS=\(\s*(.*?)\s*\)", text, re.DOTALL)
    if not match:
        raise AssertionError(f"ALL_KEYS=( ... ) array not found in {script}")
    body = re.sub(r"#[^\n]*", "", match.group(1))
    return [tok for tok in body.split() if tok]


def test_pass_keys_match_setup_script():
    shell_keys = _parse_all_keys_from_shell(SETUP_PASS_SH)
    python_keys = list(env.KEYCHAIN_KEYS)
    assert shell_keys == python_keys, (
        "lib/env.py::KEYCHAIN_KEYS and scripts/setup-pass.sh::ALL_KEYS have "
        f"drifted.\n  python: {python_keys}\n  shell:  {shell_keys}"
    )
