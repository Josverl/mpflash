# others
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_mock import MockerFixture

from mpflash.versions import clean_version

pytestmark = [pytest.mark.mpflash]


@pytest.mark.parametrize(
    "commit, build, expected",
    [
        ("v1.13-103-gb137d064e", True, "v1.13-103"),
        ("v1.13-103-gb137d064e", False, "preview"),  # used to be 'latest'
        ("v1.13", True, "v1.13"),
        ("v1.13", False, "v1.13"),
        ("v1.13-dirty", True, "v1.13"),
        ("v1.13-dirty", False, "preview"),  # used to be 'latest'
        # lets keep all the preview tags simple based on the provided version
        ("v1.23.0-preview", False, "v1.23.0-preview"),
        ("v1.23.0-preview", True, "v1.23.0-preview"),
        ("1.20.0-preview-487", False, "v1.20.0-preview"),
        ("1.20.0-preview-487", True, "v1.20.0-preview"),
        ("v1.23.0-preview-87-g0285cb2bf", False, "v1.23.0-preview"),
    ],
)
def test_clean_version_build(commit, build, expected):
    assert clean_version(commit, build=build) == expected


@pytest.mark.parametrize(
    "input, expected",
    [
        ("", ""),
        ("v1.23.0-preview-87-g0285cb2bf", "v1_23_0_preview"),
    ],
)
def test_clean_version_flat_preview(input: str, expected: str):
    assert clean_version(input, drop_v=False, flat=True) == expected


def test_clean_version_stable():
    # should resolve to the latest stable version
    v = clean_version("stable")
    assert v != "stable"


def test_clean_version_preview():
    # should resolve to the latest preview version
    v = clean_version("preview")
    assert v != "preview"


def test_clean_version_special():
    assert clean_version("v1.13.0-103-gb137d064e") == "preview"
    assert clean_version("v1.13.0-103-gb137d064e", build=True) == "v1.13-103"
    assert clean_version("v1.13.0-103-gb137d064e", build=True, commit=True) == "v1.13-103-gb137d064e"
    # with path
    #    assert clean_version("v1.13.0-103-gb137d064e", patch=True) == "v1.13.0-Latest"
    assert clean_version("v1.13.0-103-gb137d064e", patch=True) == "preview"
    assert clean_version("v1.13.0-103-gb137d064e", patch=True, build=True) == "v1.13.0-103"
    # with commit
    assert clean_version("v1.13.0-103-gb137d064e", patch=True, build=True, commit=True) == "v1.13.0-103-gb137d064e"
    # FLats
    #    assert clean_version("v1.13.0-103-gb137d064e", flat=True) == "v1_13-Latest"
    assert clean_version("v1.13.0-103-gb137d064e", flat=True) == "preview"
    assert clean_version("v1.13.0-103-gb137d064e", build=True, commit=True, flat=True) == "v1_13_103_gb137d064e"

    # all options , no V for version
    assert clean_version("v1.13.0-103-gb137d064e", patch=True, build=True, commit=True, flat=True, drop_v=True) == "1_13_0_103_gb137d064e"


@pytest.mark.parametrize(
    "input, expected",
    [
        ("-", "-"),
        ("0.0", "v0.0"),
        ("1.9.3", "v1.9.3"),
        ("v1.9.3", "v1.9.3"),
        ("v1.10.0", "v1.10"),
        ("v1.13.0", "v1.13"),
        ("1.13.0", "v1.13"),
        ("v1.20.0", "v1.20.0"),
        ("1.20.0", "v1.20.0"),
    ],
)
def test_clean_version(input: str, expected: str):
    assert clean_version(input) == expected
