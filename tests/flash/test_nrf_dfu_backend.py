from pathlib import Path
from types import SimpleNamespace

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.nrf_dfu_backend import NrfDfuBackend
from mpflash.flash.context import FlashContext


def test_nrf_dfu_backend_forwards_explicit_options(mocker, tmp_path: Path):
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(b"uf2")
    mcu = SimpleNamespace()
    profile = object()

    def confirm(message: str) -> bool:
        return True

    mocker.patch("mpflash.flash.builtins.nrf_dfu.profiles.get_profile", return_value=profile)
    migrate = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.migrate_nrf", return_value=mcu)
    ctx = FlashContext(
        mcu=mcu,
        fw_file=firmware,
        options={
            "softdevice_target": "s140-7.3.0",
            "confirm_migration": confirm,
            "nrf_dfu_port": "COM78",
            "force_softdevice_repair": True,
        },
    )

    result = NrfDfuBackend().flash(ctx)

    assert result.success is True
    assert result.mcu is mcu
    assert result.backend == "nrf-dfu"
    migrate.assert_called_once_with(
        mcu,
        firmware,
        profile,
        confirm=confirm,
        bootloader_port="COM78",
        force_repair=True,
    )


@pytest.mark.parametrize(
    "options, message",
    [
        ({}, "explicit --softdevice"),
        ({"softdevice_target": "s140-7.3.0"}, "confirmation policy"),
        (
            {
                "softdevice_target": "s140-7.3.0",
                "confirm_migration": lambda message: True,
                "nrf_dfu_port": 78,
            },
            "invalid bootloader CDC port",
        ),
        (
            {
                "softdevice_target": "s140-7.3.0",
                "confirm_migration": lambda message: True,
                "force_softdevice_repair": "yes",
            },
            "invalid SoftDevice repair policy",
        ),
    ],
)
def test_nrf_dfu_backend_rejects_invalid_options(tmp_path: Path, options: dict, message: str):
    firmware = tmp_path / "firmware.uf2"
    firmware.write_bytes(b"uf2")
    ctx = FlashContext(mcu=SimpleNamespace(), fw_file=firmware, options=options)

    with pytest.raises(MPFlashError, match=message):
        NrfDfuBackend().flash(ctx)
