import struct
from pathlib import Path

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.uf2 import nrf


def test_build_nrf_reset_uf2_targets_invalid_uicr_bootloader_update():
    block = nrf.build_nrf_reset_uf2()

    assert len(block) == 512
    assert struct.unpack_from("<8I", block) == (
        0x0A324655,
        0x9E5D5157,
        0x00002000,
        0x10001000,
        256,
        0,
        1,
        0xD663823C,
    )
    assert block[32 + 0x14 : 32 + 0x1C] == bytes(8)
    assert struct.unpack_from("<I", block, 508) == (0x0AB16F30,)


def test_reset_nrf_to_application_writes_reset_block(tmp_path: Path, mocker):
    (tmp_path / "INFO_UF2.TXT").write_text("Board-ID: nRF52840-test\n")
    mounted = mocker.patch(
        "mpflash.flash.builtins.uf2.nrf._volume_is_mounted",
        side_effect=[True, False],
    )
    fsync = mocker.patch("mpflash.flash.builtins.uf2.nrf.os.fsync")

    nrf.reset_nrf_to_application(tmp_path)

    assert (tmp_path / "MPFLASH.UF2").read_bytes() == nrf.build_nrf_reset_uf2()
    assert mounted.call_count == 2
    fsync.assert_called_once()


def test_reset_nrf_to_application_requires_mounted_volume(tmp_path: Path):
    with pytest.raises(MPFlashError, match="no longer mounted"):
        nrf.reset_nrf_to_application(tmp_path)


def test_probe_nrf_softdevice_round_trip(mocker):
    mcu = mocker.Mock()
    mcu.family = "micropython"
    mcu.serialport = "COM7"
    mcu.run_command.return_value = (1, [])
    mcu.wait_for_restart.return_value = True
    existing = {Path("D:/")}
    new_volume = Path("E:/")
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value=existing,
    )
    wait_for_new = mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.wait_for_new_volume",
        return_value=new_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_board_id",
        return_value="nRF52840-test",
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_softdevice",
        return_value="S140 7.3.0",
    )
    reset = mocker.patch("mpflash.flash.builtins.uf2.nrf.reset_nrf_to_application")

    assert nrf.probe_nrf_softdevice(mcu, timeout=4) == "S140 7.3.0"

    command = mcu.run_command.call_args.args[0]
    assert command[:2] == ["exec", "--no-follow"]
    assert "machine.mem32[0x4000051c]=0x57" in command[2]
    wait_for_new.assert_called_once_with(existing, timeout=4)
    reset.assert_called_once_with(new_volume)
    mcu.wait_for_restart.assert_called_once_with(timeout=4)


def test_probe_nrf_softdevice_uses_circuitpython_uf2_reset(mocker):
    mcu = mocker.Mock()
    mcu.family = "circuitpython"
    mcu.serialport = "COM8"
    mcu.run_command.return_value = (1, [])
    mcu.wait_for_restart.return_value = True
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value=set(),
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.wait_for_new_volume",
        return_value=Path("F:/"),
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_board_id",
        return_value="nRF52840-test",
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_softdevice",
        return_value=None,
    )
    mocker.patch("mpflash.flash.builtins.uf2.nrf.reset_nrf_to_application")

    assert nrf.probe_nrf_softdevice(mcu) is None

    command = mcu.run_command.call_args.args[0][2]
    assert "microcontroller.RunMode.UF2" in command


def test_probe_nrf_softdevice_reports_missing_volume(mocker):
    mcu = mocker.Mock()
    mcu.family = "micropython"
    mcu.serialport = "COM7"
    mcu.run_command.return_value = (1, [])
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value=set(),
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.wait_for_new_volume",
        return_value=None,
    )

    with pytest.raises(MPFlashError, match="did not expose a new UF2 volume"):
        nrf.probe_nrf_softdevice(mcu)


def test_probe_nrf_softdevice_reports_reconnect_failure(mocker):
    mcu = mocker.Mock()
    mcu.family = "micropython"
    mcu.serialport = "COM7"
    mcu.run_command.return_value = (1, [])
    mcu.wait_for_restart.return_value = False
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value=set(),
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.wait_for_new_volume",
        return_value=Path("E:/"),
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_board_id",
        return_value="nRF52840-test",
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_softdevice",
        return_value="S140 7.3.0",
    )
    mocker.patch("mpflash.flash.builtins.uf2.nrf.reset_nrf_to_application")

    with pytest.raises(MPFlashError, match="press its reset button"):
        nrf.probe_nrf_softdevice(mcu)


def test_probe_nrf_softdevice_rejects_unknown_firmware(mocker):
    mcu = mocker.Mock()
    mcu.family = "unknown"

    with pytest.raises(MPFlashError, match="unknown firmware"):
        nrf.probe_nrf_softdevice(mcu)


def test_enrich_mounted_nrf_bootloader(mocker):
    mcu = mocker.Mock()
    mcu.family = "unknown"
    mcu.port = ""
    mcu.sys_platform = ""
    mcu.board_id = ""
    mcu.description = ""
    mcu.softdevice = ""
    volume = Path("D:/")
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value={volume},
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_board_id",
        return_value="nRF52840-nicenano",
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_softdevice",
        return_value="S140 version 6.1.1",
    )

    nrf.enrich_mounted_nrf_bootloader([mcu])

    assert mcu.port == "nrf"
    assert mcu.sys_platform == "nrf"
    assert mcu.board_id == "nRF52840-nicenano"
    assert mcu.description == f"UF2 bootloader at {volume}"
    assert mcu.softdevice == "S140 version 6.1.1"


def test_enrich_mounted_nrf_bootloader_does_not_guess(mocker):
    first = mocker.Mock(family="unknown")
    second = mocker.Mock(family="unknown")
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.mounted_uf2_volumes",
        return_value={Path("D:/")},
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_board_id",
        return_value="nRF52840-nicenano",
    )
    mocker.patch(
        "mpflash.flash.builtins.uf2.nrf.get_softdevice",
        return_value="S140 version 6.1.1",
    )

    nrf.enrich_mounted_nrf_bootloader([first, second])

    assert "port" not in first.__dict__
    assert "port" not in second.__dict__
