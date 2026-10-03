import subprocess
from pathlib import Path

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.nrf_dfu import transport


def test_flash_serial_dfu_invokes_one_explicit_port(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    run = mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.transport.subprocess.run",
        return_value=subprocess.CompletedProcess([], 0, "ok", ""),
    )

    result = transport.flash_serial_dfu(package, "COM76", command=("nrfutil", "dfu"))

    assert result.stdout == "ok"
    run.assert_called_once_with(
        ("nrfutil", "dfu"),
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_flash_serial_dfu_reports_timeout(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.transport.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["nrfutil"], 5),
    )

    with pytest.raises(MPFlashError, match="still be in its bootloader"):
        transport.flash_serial_dfu(package, "COM76", timeout=5, command=("nrfutil",))


def test_flash_serial_dfu_reports_process_error(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.transport.subprocess.run",
        return_value=subprocess.CompletedProcess([], 2, "", "Failed to connect"),
    )

    with pytest.raises(MPFlashError, match="Failed to connect"):
        transport.flash_serial_dfu(package, "COM76", command=("nrfutil",))


def test_flash_serial_dfu_requires_optional_dependency(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.transport.is_nrfutil_available", return_value=False)

    with pytest.raises(MPFlashError, match="uv sync --extra nrf"):
        transport.flash_serial_dfu(package, "COM76")


def test_flash_serial_dfu_requires_explicit_port(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    run = mocker.patch("mpflash.flash.builtins.nrf_dfu.transport.subprocess.run")

    with pytest.raises(MPFlashError, match="explicitly matched"):
        transport.flash_serial_dfu(package, "", command=("nrfutil",))

    run.assert_not_called()


def test_flash_serial_dfu_requires_existing_package(tmp_path: Path, mocker):
    run = mocker.patch("mpflash.flash.builtins.nrf_dfu.transport.subprocess.run")

    with pytest.raises(MPFlashError, match="does not exist"):
        transport.flash_serial_dfu(tmp_path / "missing.zip", "COM76", command=("nrfutil",))

    run.assert_not_called()


def test_flash_serial_dfu_reports_startup_error(tmp_path: Path, mocker):
    package = tmp_path / "package.zip"
    package.write_bytes(b"package")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.transport.subprocess.run",
        side_effect=OSError("cannot execute"),
    )

    with pytest.raises(MPFlashError, match="Could not start.*cannot execute"):
        transport.flash_serial_dfu(package, "COM76", command=("nrfutil",))
