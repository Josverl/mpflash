"""Unit tests for the OpenOCD (PSOC Edge) flash backend."""

from __future__ import annotations

import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from mpflash.common import PORT_FWTYPES, FlashMethod
from mpflash.errors import MPFlashError
from mpflash.flash.builtins.openocd import download, runner, targets
from mpflash.flash.builtins.openocd import flash as ocd_flash
from mpflash.flash.builtins.openocd_backend import OpenOCDBackend
from mpflash.flash.context import FlashContext, Platform
from mpflash.flash.registry import select_backend

INFINEON_BANNER = "Open On-Chip Debugger 0.12.0+dev-5.16.1.4486 (2026-04-14-19:02)"
STOCK_BANNER = "Open On-Chip Debugger 0.12.0 (2024-01-01)"


@pytest.fixture(autouse=True)
def _clear_version_cache():
    runner._probe_version.cache_clear()
    yield
    runner._probe_version.cache_clear()


@pytest.fixture
def fake_banner(mocker):
    def _set(banner: str):
        mocker.patch.object(
            runner.subprocess,
            "run",
            return_value=SimpleNamespace(stdout="", stderr=banner, returncode=0),
        )

    return _set


@pytest.fixture
def package_zip(tmp_path: Path) -> Path:
    path = tmp_path / "KIT_PSE84_AI-v1.29.0.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("firmware.hex", ":00000001FF\n")
        zf.writestr("PSE84_SMIF.FLM", b"\x7fELF")
        zf.writestr("qspi_config.cfg", "set SMIF_BANKS {}\n")
    return path


def _mcu(**kwargs):
    defaults = dict(
        port="psoc-edge",
        board="KIT_PSE84_AI",
        board_id="KIT_PSE84_AI",
        serialport="/dev/ttyACM0",
        usb_serial_number="181F0D5A01212300",
    )
    return SimpleNamespace(**{**defaults, **kwargs})


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        (INFINEON_BANNER, (5, 16, 1)),
        ("0.12.0+dev-5.8.0.3960", (5, 8, 0)),
        (STOCK_BANNER, None),
    ],
)
def test_parse_version(text, expected):
    assert runner.parse_version(text) == expected


@pytest.mark.parametrize(
    "banner, suitable",
    [
        (INFINEON_BANNER, True),
        ("0.12.0+dev-5.7.0.1000", False),  # older than the minimum
        (STOCK_BANNER, False),
    ],
)
def test_is_suitable(fake_banner, banner, suitable):
    fake_banner(banner)
    assert runner.is_suitable("/x/openocd") is suitable


def test_is_suitable_false_when_not_executable(mocker):
    mocker.patch.object(runner.subprocess, "run", side_effect=FileNotFoundError)
    assert runner.is_suitable("/missing/openocd") is False


def test_find_openocd_prefers_env_var(monkeypatch, fake_banner):
    fake_banner(INFINEON_BANNER)
    monkeypatch.setenv(runner.ENV_VAR, "/opt/custom/openocd")
    assert runner.find_openocd() == Path("/opt/custom/openocd")


def test_find_openocd_rejects_bad_env_var(monkeypatch, fake_banner):
    fake_banner(STOCK_BANNER)
    monkeypatch.setenv(runner.ENV_VAR, "/usr/bin/openocd")
    with pytest.raises(MPFlashError, match="MPFLASH_OPENOCD"):
        runner.find_openocd()


def test_find_openocd_ignores_stock_openocd_on_path(monkeypatch, mocker, fake_banner):
    monkeypatch.delenv(runner.ENV_VAR, raising=False)
    mocker.patch.object(runner.shutil, "which", return_value="/usr/bin/openocd")
    fake_banner(STOCK_BANNER)
    assert runner.find_openocd() is None


def test_run_openocd_reports_failure_output(mocker):
    mocker.patch.object(
        runner.subprocess,
        "run",
        return_value=SimpleNamespace(stdout="", stderr="Error: unable to find a matching CMSIS-DAP device", returncode=1),
    )
    with pytest.raises(MPFlashError, match="CMSIS-DAP"):
        runner.run_openocd(Path("openocd"), ["-c", "init"])


def test_run_openocd_timeout(mocker):
    mocker.patch.object(runner.subprocess, "run", side_effect=runner.subprocess.TimeoutExpired("openocd", 5))
    with pytest.raises(MPFlashError, match="timed out"):
        runner.run_openocd(Path("openocd"), [], timeout=5)


# ---------------------------------------------------------------------------
# package extraction and command building
# ---------------------------------------------------------------------------


def test_extracted_package_finds_files(package_zip):
    with ocd_flash.extracted_package(package_zip) as package:
        assert package.hex_file.read_text().startswith(":00000001FF")
        assert package.flm_file.name == "PSE84_SMIF.FLM"
        assert (package.cfg_dir / "qspi_config.cfg").is_file()
        extracted = package.cfg_dir
    assert not extracted.exists()


def test_extracted_package_flattens_archive_paths(tmp_path):
    path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("../../evil/firmware.hex", "x")
        zf.writestr("a/b/PSE84_SMIF.FLM", "x")
        zf.writestr("a/qspi_config.cfg", "x")
    with ocd_flash.extracted_package(path) as package:
        assert package.hex_file.parent == package.cfg_dir


@pytest.mark.parametrize("missing", ["firmware.hex", "PSE84_SMIF.FLM", "qspi_config.cfg"])
def test_extracted_package_requires_all_files(tmp_path, missing):
    path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name in ("firmware.hex", "PSE84_SMIF.FLM", "qspi_config.cfg"):
            if name != missing:
                zf.writestr(name, "x")
    with pytest.raises(MPFlashError, match="must contain"):
        with ocd_flash.extracted_package(path):
            pass


def test_extracted_package_rejects_non_zip(tmp_path):
    bad = tmp_path / "pkg.zip"
    bad.write_text("not a zip")
    with pytest.raises(MPFlashError, match="not a valid"):
        with ocd_flash.extracted_package(bad):
            pass


def _args_for(package_zip, **kwargs):
    with ocd_flash.extracted_package(package_zip) as package:
        return ocd_flash.build_args(package, "pse84xgxs2.cfg", **kwargs)


def test_build_args_sequence(package_zip):
    args = _args_for(package_zip, scripts=Path("/opt/openocd/scripts"), serial="ABC123")
    commands = [args[i + 1] for i, a in enumerate(args) if a == "-c"]

    assert args[:2] == ["-s", "/opt/openocd/scripts"]
    assert commands[0].startswith("set QSPI_FLASHLOADER {") and commands[0].endswith("PSE84_SMIF.FLM}")
    assert commands[1] == "source [find interface/kitprog3.cfg]"
    assert commands[2] == "adapter serial ABC123"
    assert "source [find target/infineon/pse84xgxs2.cfg]" in commands
    assert commands.index("init") < commands.index("reset init") < commands.index("adapter speed 12000")
    assert any(c.startswith("flash write_image erase {") for c in commands)
    assert any(c.startswith("verify_image {") for c in commands)
    assert commands[-2:] == ["reset run", "shutdown"]


def test_build_args_without_serial(package_zip):
    args = _args_for(package_zip)
    assert not any(a.startswith("adapter serial") for a in args)


@pytest.mark.parametrize("serial", ["a b", "x;shutdown", "$(id)", "{x}"])
def test_build_args_rejects_unsafe_serial(package_zip, serial):
    with pytest.raises(MPFlashError, match="Invalid probe serial"):
        _args_for(package_zip, serial=serial)


# ---------------------------------------------------------------------------
# flash_openocd
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_flash(mocker):
    mocker.patch.object(ocd_flash, "ensure_openocd", return_value=Path("/opt/openocd/bin/openocd"))
    mocker.patch.object(ocd_flash, "scripts_dir", return_value=None)
    return mocker.patch.object(ocd_flash, "run_openocd", return_value="")


def test_flash_openocd_uses_usb_serial_number(patched_flash, package_zip):
    ocd_flash.flash_openocd(_mcu(), fw_file=package_zip)
    args = patched_flash.call_args.args[1]
    assert "adapter serial 181F0D5A01212300" in args


def test_flash_openocd_probe_id_overrides_serial(patched_flash, package_zip):
    ocd_flash.flash_openocd(_mcu(), fw_file=package_zip, probe_id="OTHER1")
    assert "adapter serial OTHER1" in patched_flash.call_args.args[1]


def test_flash_openocd_unknown_board(patched_flash, package_zip):
    with pytest.raises(MPFlashError, match="No OpenOCD target"):
        ocd_flash.flash_openocd(_mcu(board="OTHER", board_id="OTHER"), fw_file=package_zip)
    patched_flash.assert_not_called()


def test_flash_openocd_propagates_openocd_failure(patched_flash, package_zip):
    patched_flash.side_effect = MPFlashError("OpenOCD failed")
    with pytest.raises(MPFlashError, match="OpenOCD failed"):
        ocd_flash.flash_openocd(_mcu(), fw_file=package_zip)


@pytest.fixture
def erase_mock(mocker):
    return mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem", return_value=True)


def test_flash_openocd_erases_right_before_openocd(patched_flash, erase_mock, package_zip):
    order = []
    erase_mock.side_effect = lambda mcu: order.append("erase") or True
    patched_flash.side_effect = lambda *args, **kwargs: order.append("openocd") or ""

    ocd_flash.flash_openocd(_mcu(), fw_file=package_zip, erase=True)

    assert order == ["erase", "openocd"]


def test_flash_openocd_does_not_erase_by_default(patched_flash, erase_mock, package_zip):
    ocd_flash.flash_openocd(_mcu(), fw_file=package_zip)
    erase_mock.assert_not_called()


def test_flash_openocd_continues_when_erase_fails(patched_flash, erase_mock, package_zip):
    erase_mock.return_value = False
    ocd_flash.flash_openocd(_mcu(), fw_file=package_zip, erase=True)
    patched_flash.assert_called_once()


@pytest.mark.parametrize("failure", ["unknown_board", "no_openocd", "bad_zip"])
def test_flash_openocd_never_erases_when_a_check_fails(mocker, patched_flash, erase_mock, package_zip, tmp_path, failure):
    mcu, firmware = _mcu(), package_zip
    if failure == "unknown_board":
        mcu = _mcu(board="OTHER", board_id="OTHER")
    elif failure == "no_openocd":
        mocker.patch.object(ocd_flash, "ensure_openocd", side_effect=MPFlashError("no openocd"))
    else:
        firmware = tmp_path / "bad.zip"
        firmware.write_text("not a zip")

    with pytest.raises(MPFlashError):
        ocd_flash.flash_openocd(mcu, fw_file=firmware, erase=True)

    erase_mock.assert_not_called()
    patched_flash.assert_not_called()


# ---------------------------------------------------------------------------
# board / port targets
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_psoc6_targets(monkeypatch):
    """Pretend a second port exists, with hyphenated board names."""
    monkeypatch.setitem(
        targets.PORT_TARGETS,
        "psoc6",
        {"CY8CPROTO-062-4343W": "cy8c6xx.cfg", "CY8CPROTO-062": "short.cfg"},
    )


@pytest.mark.parametrize(
    "port, board_id, expected",
    [
        ("psoc-edge", "KIT_PSE84_AI", "pse84xgxs2.cfg"),
        ("psoc-edge", "KIT_PSE84_AI-", "pse84xgxs2.cfg"),  # empty variant, as MPRemoteBoard builds it
        ("psoc-edge", "KIT_PSE84_AI-SOMEVARIANT", "pse84xgxs2.cfg"),
        ("psoc-edge", "KIT_PSE84_AI_OTHER", None),
        ("psoc-edge", "OTHER", None),
        ("rp2", "KIT_PSE84_AI", None),
    ],
)
def test_target_for_board(port, board_id, expected):
    assert targets.target_for_board(port, board_id) == expected


@pytest.mark.usefixtures("fake_psoc6_targets")
@pytest.mark.parametrize(
    "board_id, expected",
    [
        ("CY8CPROTO-062-4343W", "cy8c6xx.cfg"),  # hyphens in the board name
        ("CY8CPROTO-062-4343W-VAR", "cy8c6xx.cfg"),  # variant suffix, longest key wins
        ("CY8CPROTO-062", "short.cfg"),
        ("CY8CPROTO-063-BLE", None),
    ],
)
def test_target_for_board_with_hyphenated_names(board_id, expected):
    assert targets.target_for_board("psoc6", board_id) == expected


@pytest.mark.usefixtures("fake_psoc6_targets")
def test_flash_openocd_uses_target_of_another_port(patched_flash, package_zip):
    mcu = _mcu(port="psoc6", board="CY8CPROTO-062-4343W", board_id="CY8CPROTO-062-4343W")
    ocd_flash.flash_openocd(mcu, fw_file=package_zip)
    assert "source [find target/infineon/cy8c6xx.cfg]" in patched_flash.call_args.args[1]


def test_backend_ports_follow_targets_table():
    assert OpenOCDBackend.supported_ports == frozenset(targets.PORT_TARGETS)


# ---------------------------------------------------------------------------
# backend selection and flash()
# ---------------------------------------------------------------------------


def test_registry_selects_openocd_for_psoc_edge_zip(mocker, package_zip):
    mocker.patch.object(OpenOCDBackend, "is_available", return_value=True)
    assert select_backend(_mcu(), package_zip).name == "openocd"


def test_openocd_rejects_other_ports_and_formats(mocker, tmp_path):
    mocker.patch.object(OpenOCDBackend, "is_available", return_value=True)
    backend = OpenOCDBackend()
    assert backend.supports(_mcu(port="rp2"), tmp_path / "fw.zip", Platform.LINUX).kind == "port"
    assert backend.supports(_mcu(), tmp_path / "fw.hex", Platform.LINUX).kind == "format"
    assert backend.supports(_mcu(), tmp_path / "fw.zip", Platform.LINUX) is None


def test_openocd_available_when_download_possible(mocker, monkeypatch):
    monkeypatch.delenv(runner.ENV_VAR, raising=False)
    mocker.patch.object(download, "download_supported", return_value=True)
    assert OpenOCDBackend().is_available() is True


def test_openocd_unavailable_without_tool_or_download(mocker, monkeypatch):
    monkeypatch.delenv(runner.ENV_VAR, raising=False)
    mocker.patch.object(download, "download_supported", return_value=False)
    mocker.patch.object(runner, "find_openocd", return_value=None)
    assert OpenOCDBackend().is_available() is False


def test_flash_passes_erase_through_and_waits(mocker, package_zip):
    erase = mocker.patch("mpflash.flash.builtins.uf2.erase.erase_filesystem")
    flash = mocker.patch.object(ocd_flash, "flash_openocd")
    services = SimpleNamespace(wait_for_restart=mocker.Mock())
    mcu = _mcu()
    ctx = FlashContext(mcu=mcu, fw_file=package_zip, erase=True, options={"probe_id": "P1", "assume_yes": True}, services=services)

    result = OpenOCDBackend().flash(ctx)

    erase.assert_not_called()  # the erase happens inside flash_openocd, after its checks
    flash.assert_called_once_with(mcu, fw_file=package_zip, probe_id="P1", assume_yes=True, erase=True)
    services.wait_for_restart.assert_called_once_with(mcu)
    assert result.success and result.mcu is mcu


def test_flash_without_erase_passes_erase_false(mocker, package_zip):
    flash = mocker.patch.object(ocd_flash, "flash_openocd")
    services = SimpleNamespace(wait_for_restart=mocker.Mock())

    OpenOCDBackend().flash(FlashContext(mcu=_mcu(), fw_file=package_zip, erase=False, services=services))

    assert flash.call_args.kwargs["erase"] is False


# ---------------------------------------------------------------------------
# serial filesystem erase timeout
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("port, expected", [("psoc-edge", 600), ("rp2", 60)])
def test_erase_timeout_is_per_port(mocker, port, expected):
    from mpflash.flash.builtins.uf2 import erase
    from mpflash.mpremoteboard import MPRemoteBoard

    mcu = _mcu(port=port)
    mocker.patch.object(MPRemoteBoard, "connected_comports", return_value=[mcu.serialport])
    run = mocker.patch.object(mcu, "run_command", create=True, return_value=(0, []))
    mcu.wait_for_restart = mocker.Mock(return_value=True)

    assert erase.erase_filesystem(mcu) is True
    assert run.call_args.kwargs["timeout"] == expected


def test_erase_timeout_can_be_overridden(mocker):
    from mpflash.flash.builtins.uf2 import erase
    from mpflash.mpremoteboard import MPRemoteBoard

    mcu = _mcu()
    mocker.patch.object(MPRemoteBoard, "connected_comports", return_value=[mcu.serialport])
    run = mocker.patch.object(mcu, "run_command", create=True, return_value=(0, []))
    mcu.wait_for_restart = mocker.Mock(return_value=True)

    erase.erase_filesystem(mcu, timeout=5)
    assert run.call_args.kwargs["timeout"] == 5


# ---------------------------------------------------------------------------
# download / install
# ---------------------------------------------------------------------------


def _openocd_tarball(extra: tuple[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        entries = [("openocd/bin/openocd", b"#!/bin/sh\n")] + ([extra] if extra else [])
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_download(mocker, tmp_path, monkeypatch):
    """Route ensure_openocd to a fake host/asset/cache and a stubbed HTTP download."""

    def _setup(payload: bytes, sha256: str | None = None):
        asset = download._Asset("openocd-test-linux.tar.gz", sha256 or hashlib.sha256(payload).hexdigest())
        monkeypatch.setattr(download, "_ASSETS", {("linux", "x64"): asset})
        monkeypatch.setattr(download, "_EXE_NAME", "openocd")
        monkeypatch.setattr(download.sys, "platform", "linux")
        monkeypatch.delenv(runner.ENV_VAR, raising=False)
        mocker.patch.object(download, "_host_key", return_value=("linux", "x64"))
        mocker.patch.object(download, "install_dir", return_value=tmp_path / "cache" / "5.16.1.4486")
        mocker.patch.object(download, "find_openocd", return_value=None)
        mocker.patch.object(download, "is_suitable", return_value=True)
        response = mocker.MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [payload]
        get = mocker.patch("requests.get", return_value=response)
        return asset, get

    return _setup


def test_ensure_openocd_uses_existing_install(mocker):
    mocker.patch.object(download, "find_openocd", return_value=Path("/opt/openocd/bin/openocd"))
    get = mocker.patch("requests.get")
    assert download.ensure_openocd() == Path("/opt/openocd/bin/openocd")
    get.assert_not_called()


def test_ensure_openocd_downloads_and_installs(fake_download):
    asset, get = fake_download(_openocd_tarball())

    exe = download.ensure_openocd(assume_yes=True)

    assert exe.name == "openocd" and exe.is_file()
    assert get.call_args.args[0].endswith(f"/{asset.name}")


def test_ensure_openocd_reuses_cached_download(fake_download):
    _, get = fake_download(_openocd_tarball())
    first = download.ensure_openocd(assume_yes=True)
    second = download.ensure_openocd(assume_yes=True)

    assert first == second
    assert get.call_count == 1


def test_ensure_openocd_checksum_mismatch(fake_download):
    fake_download(_openocd_tarball(), sha256="0" * 64)
    with pytest.raises(MPFlashError, match="Checksum mismatch"):
        download.ensure_openocd(assume_yes=True)


def test_ensure_openocd_rejects_path_traversal(fake_download):
    fake_download(_openocd_tarball(extra=("../escape.txt", b"x")))
    with pytest.raises(MPFlashError, match="Unsafe path"):
        download.ensure_openocd(assume_yes=True)


def test_ensure_openocd_declined_prompt(fake_download, mocker):
    _, get = fake_download(_openocd_tarball())
    mocker.patch.object(download, "_confirm_download", return_value=False)
    with pytest.raises(MPFlashError, match="MPFLASH_OPENOCD"):
        download.ensure_openocd()
    get.assert_not_called()


def test_ensure_openocd_unsupported_host(fake_download, mocker):
    fake_download(_openocd_tarball())
    mocker.patch.object(download, "_host_key", return_value=("linux", "riscv64"))
    with pytest.raises(MPFlashError, match="No Infineon OpenOCD package"):
        download.ensure_openocd(assume_yes=True)


def test_confirm_download_skips_prompt_when_non_interactive(mocker):
    mocker.patch.object(download.sys.stdin, "isatty", return_value=False)
    assert download._confirm_download(download._Asset("x", "y"), assume_yes=False) is True


# ---------------------------------------------------------------------------
# firmware discovery plumbing
# ---------------------------------------------------------------------------


def test_psoc_edge_registered_as_zip_port():
    assert PORT_FWTYPES["psoc-edge"] == [".zip"]
    assert FlashMethod("openocd") is FlashMethod.OPENOCD


def test_worklist_prefers_zip_for_psoc_edge():
    from mpflash.flash.worklist import _is_port_compatible_firmware

    assert _is_port_compatible_firmware("psoc-edge", "psoc-edge/KIT_PSE84_AI-v1.29.0.zip")
    assert not _is_port_compatible_firmware("psoc-edge", "psoc-edge/KIT_PSE84_AI-v1.29.0.hex")


def test_download_page_zip_links_are_found(mocker):
    from mpflash.download import from_web

    html = '<a href="/resources/firmware/KIT_PSE84_AI-20260824-v1.29.0.zip">v1.29.0</a>'
    mocker.patch.object(from_web, "get_page", return_value=html)
    urls = from_web.board_firmware_urls("https://micropython.org/download/KIT_PSE84_AI", "https://micropython.org/", ".zip")
    assert urls == ["https://micropython.org/resources/firmware/KIT_PSE84_AI-20260824-v1.29.0.zip"]
