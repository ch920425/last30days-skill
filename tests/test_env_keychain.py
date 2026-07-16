"""Tests for macOS Keychain credential source in lib/env.py.

Covers:
  - non-Darwin returns {}
  - missing `security` binary returns {}
  - successful lookups return parsed key/value pairs
  - subprocess timeout / OSError are swallowed
  - get_config merges keychain at lowest priority and labels _CONFIG_SOURCE
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from lib import env

SETUP_KEYCHAIN_SH = Path(__file__).resolve().parents[1] / "skills" / "last30days" / "scripts" / "setup-keychain.sh"

# ---------------------------------------------------------------------------
# _load_keychain unit tests
# ---------------------------------------------------------------------------






def _run_result(returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")






def test_parse_keychain_aliases_warns_on_invalid_json_and_ignores_unknown_keys(capsys):
    assert env._parse_keychain_aliases("not json") == {}
    warning = capsys.readouterr().err
    assert "LAST30DAYS_KEYCHAIN_ALIASES is not valid JSON" in warning
    assert "canonical lookups enabled" in warning

    assert env._parse_keychain_aliases('{"NOT_A_KEY":"secret-service"}') == {}
    assert capsys.readouterr().err == ""








def test_load_keychain_strips_whitespace_and_newlines():
    with mock.patch("platform.system", return_value="Darwin"), \
         mock.patch("shutil.which", return_value="/usr/bin/security"), \
         mock.patch("subprocess.run", return_value=_run_result(0, "  hello-key  \n")):
        result = env._load_keychain(["FOO"])
    assert result == {"FOO": "hello-key"}







# ---------------------------------------------------------------------------
# get_config integration tests
# ---------------------------------------------------------------------------







def test_get_config_reports_env_only_when_keychain_empty(clean_env):
    with mock.patch.object(env, "_load_keychain", return_value={}):
        cfg = env.get_config()
    assert cfg["_CONFIG_SOURCE"] == "env_only"








def test_get_config_openai_key_can_come_from_keychain(clean_env):
    """OPENAI_API_KEY must be visible to get_openai_auth via the keychain
    merge — wiring regression test."""
    with mock.patch.object(env, "_load_keychain", return_value={"OPENAI_API_KEY": "sk-from-kc"}):
        cfg = env.get_config()
    assert cfg["OPENAI_API_KEY"] == "sk-from-kc"
    assert cfg["OPENAI_AUTH_SOURCE"] == "api_key"

# ---------------------------------------------------------------------------
# Drift guard: lib/env.py KEYCHAIN_KEYS and setup-keychain.sh ALL_KEYS must
# stay in lockstep. A mismatch means users storing a key via the helper script
# wouldn't see it picked up by the loader, or vice versa.
# ---------------------------------------------------------------------------


def _parse_all_keys_from_shell(script: Path) -> list[str]:
    text = script.read_text(encoding="utf-8")
    match = re.search(r"ALL_KEYS=\(\s*(.*?)\s*\)", text, re.DOTALL)
    if not match:
        raise AssertionError(f"ALL_KEYS=( ... ) array not found in {script}")
    body = match.group(1)
    # Strip shell comments and split on whitespace
    body = re.sub(r"#[^\n]*", "", body)
    return [tok for tok in body.split() if tok]


def test_keychain_keys_match_setup_script():
    shell_keys = _parse_all_keys_from_shell(SETUP_KEYCHAIN_SH)
    python_keys = list(env.KEYCHAIN_KEYS)
    assert shell_keys == python_keys, (
        "lib/env.py::KEYCHAIN_KEYS and scripts/setup-keychain.sh::ALL_KEYS "
        f"have drifted.\n  python: {python_keys}\n  shell:  {shell_keys}"
    )
