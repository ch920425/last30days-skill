import json
import subprocess
from unittest import mock

from lib import xurl_x


def test_is_available_requires_wrapper_and_bearer(monkeypatch):
    monkeypatch.setenv("X_BEARER_TOKEN", "test-token")
    with mock.patch("shutil.which", return_value="/usr/local/bin/xurl"):
        assert xurl_x.is_available() is True


def test_is_available_rejects_missing_bearer(monkeypatch):
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)
    with mock.patch("shutil.which", return_value="/usr/local/bin/xurl"):
        assert xurl_x.is_available() is False


def test_search_uses_get_only_recent_search():
    completed = mock.Mock(returncode=0, stdout=json.dumps({"data": []}), stderr="")
    with mock.patch("subprocess.run", return_value=completed) as run:
        assert xurl_x.search_x("agents", bearer_token="test-token") == {"data": []}
    argv = run.call_args.args[0]
    assert argv[:3] == ["xurl", "/tweets/search/recent", "--get"]
    assert "--data-urlencode" in argv
    assert not any(item in argv for item in ("--post", "--delete", "--header"))
    assert run.call_args.kwargs["env"]["X_BEARER_TOKEN"] == "test-token"


def test_search_surfaces_wrapper_failure():
    completed = mock.Mock(returncode=2, stdout="", stderr="rejected")
    with mock.patch("subprocess.run", return_value=completed):
        result = xurl_x.search_x("agents")
    assert "rejected" in result["error"]


def test_search_surfaces_timeout():
    with mock.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(["xurl"], 30),
    ):
        result = xurl_x.search_x("agents")
    assert "timed out" in result["error"]


def test_parse_response_builds_public_post():
    response = {
        "data": [
            {
                "id": "42",
                "author_id": "7",
                "text": "Agent launch",
                "created_at": "2026-07-16T12:00:00Z",
                "public_metrics": {
                    "like_count": 3,
                    "retweet_count": 2,
                    "reply_count": 1,
                    "quote_count": 0,
                },
            }
        ],
        "includes": {"users": [{"id": "7", "username": "builder"}]},
    }
    item = xurl_x.parse_x_response(response, "agent")[0]
    assert item["url"] == "https://x.com/builder/status/42"
    assert item["engagement"]["likes"] == 3
