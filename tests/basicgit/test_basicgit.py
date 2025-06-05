from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess
from unittest import mock

import pytest

# test_basicgit.py
from mpflash.basicgit import (
    checkout_commit,
    checkout_tag,
    clone,
    fetch,
    get_git_describe,
    get_local_tag,
    get_local_tags,
    pull,
    switch_branch,
    switch_tag,
)


@pytest.fixture
def mock_subprocess_run():
    with mock.patch("mpflash.basicgit.subprocess.run") as mocked_run:
        yield mocked_run


@pytest.fixture
def mock_subprocess_check_output():
    with mock.patch("mpflash.basicgit.subprocess.check_output") as mocked_check_output:
        yield mocked_check_output


def test_clone_success(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert clone("https://github.com/user1/repo.git", Path("/tmp/repo")) is True


def test_clone_failure(mock_subprocess_run):
    mock_subprocess_run.side_effect = CalledProcessError(returncode=1, cmd="git clone")
    assert clone("https://github.com/user2/repo.git", Path("/tmp/repo")) is False


def test_get_local_tag(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stdout="v1.2.3\n", stderr="")
    assert get_local_tag(Path("/tmp/repo")) == "v1.2.3"


# TODO: FIX TEST
# def test_get_local_tag_none(mock_subprocess_run):
#     mock_subprocess_run.return_value = None
#     assert get_local_tag(Path("/tmp/repo")) is None
# TODO: FIX TEST
# def test_checkout_tag_failure(mock_subprocess_run):
#     mock_subprocess_run.return_value = None
#     assert checkout_tag("v1.2.3", Path("/tmp/repo")) is False


def test_get_local_tags(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stdout="v1.0.0\nv1.2.0\nv1.3.0\n", stderr="")
    assert get_local_tags(Path("/tmp/repo")) == ["v1.0.0", "v1.2.0", "v1.3.0"]


def test_checkout_tag(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    assert checkout_tag("v1.2.3", Path("/tmp/repo")) is True


def test_checkout_commit(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert checkout_commit("abcdef123456", Path("/tmp/repo")) is True


def test_switch_tag(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert switch_tag("v1.2.3", Path("/tmp/repo")) is True


def test_switch_branch(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert switch_branch("develop", Path("/tmp/repo")) is True


def test_fetch(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert fetch(Path("/tmp/repo")) is True


def test_pull(mock_subprocess_run):
    mock_subprocess_run.return_value = CompletedProcess(args=[], returncode=0, stderr="")
    assert pull(Path("/tmp/repo"), branch="main") is True


def test_get_git_describe(mock_subprocess_check_output):
    mock_subprocess_check_output.return_value = "v1.2.3-4-gabcdef"
    assert get_git_describe("/tmp/repo") == "v1.2.3-4-gabcdef"


def test_get_git_describe_no_repo(mock_subprocess_check_output):
    mock_subprocess_check_output.side_effect = CalledProcessError(returncode=128, cmd="git describe")
    assert get_git_describe("/tmp/repo") is None
