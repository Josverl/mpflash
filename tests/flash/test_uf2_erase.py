import ast

from mpflash.common import BootloaderMethod
from mpflash.flash.builtins.uf2.erase import ERASE_SCRIPT, erase_filesystem
from mpflash.flash.builtins.uf2_backend import UF2Backend
from mpflash.flash.context import FlashContext
from mpflash.mpremoteboard import MPRemoteBoard


def _mcu(port="rp2", serialport="COM7"):
    mcu = MPRemoteBoard(serialport)
    mcu.port = port
    mcu.board = "RPI_PICO"
    mcu.serialport = serialport
    return mcu


def test_erase_bdev_device_script_is_valid_python():
    """The on-device erase script must be valid Python."""
    source = ERASE_SCRIPT.read_text(encoding="utf-8")
    ast.parse(source)
    assert "machine.reset" in source


def test_erase_skips_unsupported_port(mocker):
    mcu = _mcu(port="esp32")
    run = mocker.patch.object(mcu, "run_command")

    assert erase_filesystem(mcu) is False
    run.assert_not_called()


def test_erase_skips_without_serial_port(mocker):
    mcu = _mcu(serialport="auto")
    run = mocker.patch.object(mcu, "run_command")

    assert erase_filesystem(mcu) is False
    run.assert_not_called()


def test_erase_falls_back_when_port_not_live(mocker):
    mcu = _mcu()
    mocker.patch.object(MPRemoteBoard, "connected_comports", return_value=[])
    run = mocker.patch.object(mcu, "run_command")

    # Board is already in the bootloader (port gone) -> cannot erase over serial.
    assert erase_filesystem(mcu) is False
    run.assert_not_called()


def test_erase_runs_script_and_confirms_reconnect(mocker):
    mcu = _mcu()
    mocker.patch.object(MPRemoteBoard, "connected_comports", return_value=["COM7"])
    run = mocker.patch.object(mcu, "run_command", return_value=(0, []))
    mocker.patch.object(mcu, "wait_for_restart", return_value=True)

    assert erase_filesystem(mcu) is True
    # The board-side erase script is executed via `mpremote run`.
    assert run.call_args.args[0][0] == "run"
    assert run.call_args.args[0][1].endswith("erase_bdev.py")


def test_erase_returns_false_when_board_does_not_reconnect(mocker):
    mcu = _mcu()
    mocker.patch.object(MPRemoteBoard, "connected_comports", return_value=["COM7"])
    mocker.patch.object(mcu, "run_command", side_effect=OSError("port reset"))
    mocker.patch.object(mcu, "wait_for_restart", return_value=False)

    assert erase_filesystem(mcu) is False


def test_backend_serial_erase_then_flashes(mocker, tmp_path):
    backend = UF2Backend()
    fw = tmp_path / "RPI_PICO-v1.28.0.uf2"
    fw.write_bytes(b"\x00")

    m_erase = mocker.patch(
        "mpflash.flash.builtins.uf2.erase.erase_filesystem",
        return_value=True,
    )
    m_flash = mocker.patch("mpflash.flash.builtins.uf2.flash_uf2", return_value=_mcu())
    services = mocker.Mock()
    services.enter_bootloader.return_value = True

    ctx = FlashContext(
        mcu=_mcu(),
        fw_file=fw,
        erase=True,
        bootloader=BootloaderMethod.AUTO,
        options={},
        services=services,
    )
    result = backend.flash(ctx)

    assert result.success is True
    m_erase.assert_called_once()
    # Bootloader entry is a separate step and still runs.
    services.enter_bootloader.assert_called_once()
    # flash_uf2 only copies firmware; erase is handled by erase_filesystem.
    assert "erase" not in m_flash.call_args.kwargs


def test_backend_continues_when_serial_erase_fails(mocker, tmp_path):
    backend = UF2Backend()
    fw = tmp_path / "RPI_PICO-v1.28.0.uf2"
    fw.write_bytes(b"\x00")

    mocker.patch(
        "mpflash.flash.builtins.uf2.erase.erase_filesystem",
        return_value=False,
    )
    m_flash = mocker.patch("mpflash.flash.builtins.uf2.flash_uf2", return_value=_mcu())
    m_warn = mocker.patch("mpflash.flash.builtins.uf2_backend.log.warning")
    services = mocker.Mock()
    services.enter_bootloader.return_value = True

    ctx = FlashContext(
        mcu=_mcu(),
        fw_file=fw,
        erase=True,
        bootloader=BootloaderMethod.AUTO,
        options={},
        services=services,
    )
    result = backend.flash(ctx)

    # Erase could not be driven over serial, so warn and continue with the flash.
    assert result.success is True
    m_warn.assert_called_once()
    services.enter_bootloader.assert_called_once()
    m_flash.assert_called_once()
