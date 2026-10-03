from click.testing import CliRunner
from pytest_mock import MockerFixture

from mpflash import cli_main
from mpflash.custom.add import add_custom_firmware


def test_mpflash_add_accepts_explicit_firmware_metadata(tmp_path, mocker: MockerFixture):
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(b"UF2")
    add_custom_firmware = mocker.patch("mpflash.custom.add_custom_firmware", return_value=0)

    result = CliRunner().invoke(
        cli_main.cli,
        [
            "add",
            "--path",
            str(firmware),
            "--board",
            "PROMICRO_NRF52840",
            "--port",
            "nrf",
            "--version",
            "1.27.0",
        ],
    )

    assert result.exit_code == 0
    add_custom_firmware.assert_called_once_with(
        fw_path=firmware,
        force=False,
        description="",
        board_id="PROMICRO_NRF52840",
        port="nrf",
        version="1.27.0",
    )


def test_add_custom_firmware_registers_explicit_metadata(tmp_path, mocker: MockerFixture):
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(b"UF2")
    mocker.patch(
        "mpflash.custom.add.custom_fw_from_path",
        return_value={
            "board_id": "firmware",
            "custom_id": "firmware",
            "version": "unknown",
            "port": "",
            "firmware_file": "firmware.uf2",
            "source": firmware.as_uri(),
            "custom": True,
            "build": 0,
        },
    )
    add_firmware = mocker.patch("mpflash.custom.add.add_firmware", return_value=True)

    result = add_custom_firmware(
        firmware,
        board_id="PROMICRO_NRF52840",
        port="nrf",
        version="1.27.0",
    )

    assert result == 0
    fw_info = add_firmware.call_args.kwargs["fw_info"]
    assert fw_info["board_id"] == "PROMICRO_NRF52840"
    assert fw_info["custom_id"] == "PROMICRO_NRF52840"
    assert fw_info["port"] == "nrf"
    assert fw_info["version"] == "v1.27.0"
    assert fw_info["firmware_file"] == "nrf/PROMICRO_NRF52840-v1.27.0.uf2"
    assert add_firmware.call_args.kwargs["custom"] is True
