from pathlib import Path
from types import SimpleNamespace

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.builtins.nrf_dfu.migration import (
    BootloaderPort,
    _validate_explicit_bootloader_pair,
    migrate_nrf,
    wait_for_bootloader_port,
    wait_for_profile_volume,
    wait_for_runtime_port,
)
from mpflash.flash.builtins.nrf_dfu.profiles import get_profile
from mpflash.flash.builtins.uf2.boardid import Uf2BoardInfo


def _mcu():
    mcu = SimpleNamespace(
        serialport="COM77",
        path=None,
        family="unknown",
        softdevice="S140 6.1.1",
        wait_for_restart=lambda timeout: True,
    )
    mcu.get_mcu_info = lambda: setattr(mcu, "family", "micropython")
    return mcu


def _prepare_destructive_migration(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    source_volume = Path("E:/")
    target_volume = Path("F:/")
    source_port = BootloaderPort("COM76", 0x239A, 0x00B3, "source", "1-1")
    target_port = BootloaderPort("COM79", 0x1209, 0x5284, "target", "1-1")
    source_info = Uf2BoardInfo(
        board_id="nRF52840-nicenano",
        bootloader_version="0.6.0",
        softdevice="S140 6.1.1",
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes",
        side_effect=[set(), {source_volume}],
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader",
        return_value=source_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=source_info,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        side_effect=[source_port, target_port],
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration._volume_fingerprints",
        return_value={str(source_volume).casefold(): source_info},
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_profile_volume",
        return_value=target_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port",
        return_value=BootloaderPort("COM81", 0x239A, 0x8052, "runtime", "1-1"),
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_dfu_package")
    return mcu, application


def test_wait_for_runtime_port_prefers_bootloader_usb_location(mocker):
    bootloader = BootloaderPort("COM80", 0x1209, 0x5284, "bootloader", "1-1")
    expected = BootloaderPort("COM81", 0x239A, 0x8052, "runtime", "1-1")
    unrelated = BootloaderPort("COM82", 0x239A, 0x8052, "other", "2-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com81": expected, "com82": unrelated},
    )

    assert wait_for_runtime_port({}, bootloader, timeout=0.1, poll_interval=0) == expected


def test_wait_for_runtime_port_rejects_ambiguous_candidates(mocker):
    bootloader = BootloaderPort("COM80", 0x1209, 0x5284, "bootloader", None)
    first = BootloaderPort("COM81", 0x239A, 0x8052, "first", "1-1")
    second = BootloaderPort("COM82", 0x239A, 0x8052, "second", "2-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com81": first, "com82": second},
    )

    with pytest.raises(MPFlashError, match="Multiple new runtime CDC ports"):
        wait_for_runtime_port({}, bootloader, timeout=0.1, poll_interval=0)


def test_wait_for_runtime_port_reports_timeout(mocker):
    bootloader = BootloaderPort("COM80", 0x1209, 0x5284, "bootloader", "1-1")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})

    with pytest.raises(MPFlashError, match="No unambiguous runtime CDC port"):
        wait_for_runtime_port({}, bootloader, timeout=0.01, poll_interval=0)


def test_wait_for_runtime_port_rejects_only_candidate_at_wrong_location(mocker):
    bootloader = BootloaderPort("COM80", 0x1209, 0x5284, "bootloader", "1-1")
    unrelated = BootloaderPort("COM81", 0x239A, 0x8052, "runtime", "2-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com81": unrelated},
    )

    with pytest.raises(MPFlashError, match="No unambiguous runtime CDC port"):
        wait_for_runtime_port({}, bootloader, timeout=0.01, poll_interval=0)


def test_wait_for_profile_volume_returns_one_changed_target(mocker):
    profile = get_profile("s140-7.3.0")
    volume = Path("E:/")
    target_info = Uf2BoardInfo(
        board_id=profile.board_id,
        bootloader_version=profile.bootloader_version,
        softdevice=profile.softdevice,
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes", return_value={volume})
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info", return_value=target_info)

    assert wait_for_profile_volume(profile, {}, timeout=0.1, poll_interval=0) == volume


def test_wait_for_profile_volume_rejects_multiple_targets(mocker):
    profile = get_profile("s140-7.3.0")
    target_info = Uf2BoardInfo(
        board_id=profile.board_id,
        bootloader_version=profile.bootloader_version,
        softdevice=profile.softdevice,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes",
        return_value={Path("E:/"), Path("F:/")},
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info", return_value=target_info)

    with pytest.raises(MPFlashError, match="Multiple target nRF UF2 volumes"):
        wait_for_profile_volume(profile, {}, timeout=0.1, poll_interval=0)


def test_wait_for_profile_volume_ignores_unchanged_target(mocker):
    profile = get_profile("s140-7.3.0")
    volume = Path("E:/")
    target_info = Uf2BoardInfo(
        board_id=profile.board_id,
        bootloader_version=profile.bootloader_version,
        softdevice=profile.softdevice,
    )
    previous = {str(volume).casefold(): target_info}
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes", return_value={volume})
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info", return_value=target_info)

    with pytest.raises(MPFlashError, match="target bootloader did not appear"):
        wait_for_profile_volume(profile, previous, timeout=0.01, poll_interval=0)


def test_explicit_bootloader_pair_accepts_one_volume_and_port(mocker):
    profile = get_profile("s140-6.1.1")
    volume = Path("D:/")
    port = BootloaderPort("COM78", profile.usb_vid, profile.usb_pid, "source", "1-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=Uf2BoardInfo(
            board_id=profile.board_id,
            bootloader_version="0.6.0",
            softdevice=profile.softdevice,
        ),
    )

    _validate_explicit_bootloader_pair(volume, "COM78", {volume}, {"com78": port})


def test_explicit_bootloader_pair_rejects_multiple_cdc_candidates(mocker):
    profile = get_profile("s140-6.1.1")
    volume = Path("D:/")
    first = BootloaderPort("COM78", profile.usb_vid, profile.usb_pid, "first", "1-1")
    second = BootloaderPort("COM79", profile.usb_vid, profile.usb_pid, "second", "2-1")

    with pytest.raises(MPFlashError, match="Cannot safely pair.*CDC"):
        _validate_explicit_bootloader_pair(
            volume,
            "COM78",
            {volume, Path("E:/")},
            {"com78": first, "com79": second},
        )


def test_explicit_bootloader_pair_rejects_multiple_allowlisted_volumes(mocker):
    profile = get_profile("s140-6.1.1")
    selected = Path("D:/")
    port = BootloaderPort("COM78", profile.usb_vid, profile.usb_pid, "source", "1-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=Uf2BoardInfo(
            board_id=profile.board_id,
            bootloader_version="0.6.0",
            softdevice=profile.softdevice,
        ),
    )

    with pytest.raises(MPFlashError, match="Cannot safely pair.*volume"):
        _validate_explicit_bootloader_pair(
            selected,
            "COM78",
            {selected, Path("E:/")},
            {"com78": port},
        )


def test_wait_for_bootloader_port_rejects_unchanged_implicit_candidate(mocker):
    existing = BootloaderPort("COM78", 0x239A, 0x00B3, "existing", "2-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com78": existing},
    )

    with pytest.raises(MPFlashError, match="No new or explicitly selected"):
        wait_for_bootloader_port({"com78": existing}, timeout=0.01, poll_interval=0)


def test_wait_for_bootloader_port_accepts_explicit_unchanged_candidate(mocker):
    existing = BootloaderPort("COM78", 0x239A, 0x00B3, "existing", "2-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com78": existing},
    )

    assert wait_for_bootloader_port({"com78": existing}, preferred_port="COM78", timeout=0.1) == existing


def test_wait_for_bootloader_port_ignores_stale_preferred_source_identity(mocker):
    source = BootloaderPort("COM78", 0x239A, 0x00B3, "source", "1-1")
    target = BootloaderPort("COM78", 0x1209, 0x5284, "target", "1-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        side_effect=[{"com78": source}, {"com78": target}],
    )

    assert (
        wait_for_bootloader_port(
            {"com78": source},
            preferred_port="COM78",
            expected_usb_id=(0x1209, 0x5284),
            timeout=0.1,
            poll_interval=0,
        )
        == target
    )


def test_wait_for_bootloader_port_requires_matching_physical_location(mocker):
    wrong = BootloaderPort("COM78", 0x239A, 0x00B3, "wrong", "2-1")
    expected = BootloaderPort("COM79", 0x239A, 0x00B3, "expected", "1-1")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        return_value={"com78": wrong, "com79": expected},
    )

    assert (
        wait_for_bootloader_port(
            {},
            expected_location="1-1",
            timeout=0.1,
            poll_interval=0,
        )
        == expected
    )


def test_source_profile_rejects_unlisted_bootloader_version():
    from mpflash.flash.builtins.nrf_dfu.migration import _source_profile

    info = Uf2BoardInfo(
        board_id="nRF52840-nicenano",
        bootloader_version="custom",
        softdevice="S140 6.1.1",
    )
    port = BootloaderPort("COM78", 0x239A, 0x00B3, "source", "1-1")

    with pytest.raises(MPFlashError, match="not an allowlisted"):
        _source_profile(info, port)


def test_migrate_nrf_runs_serial_dfu_then_application(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    source_volume = Path("E:/")
    target_volume = Path("F:/")
    source_port = BootloaderPort("COM76", 0x239A, 0x00B3, "source", "1-1")
    target_port = BootloaderPort("COM79", 0x1209, 0x5284, "target", "1-1")
    runtime_port = BootloaderPort("COM81", 0x239A, 0x8052, "runtime", "1-1")
    runtime_port_before = BootloaderPort("COM77", 0x239A, 0x8052, "runtime", "1-1")
    source_info = Uf2BoardInfo(
        board_id="nRF52840-nicenano",
        bootloader_version="0.6.0",
        model="nice!nano",
        softdevice="S140 6.1.1",
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes",
        side_effect=[set(), {source_volume}],
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports",
        side_effect=[{"com77": runtime_port_before}, {}, {}],
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader",
        return_value=source_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=source_info,
    )
    wait_bootloader = mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        side_effect=[source_port, target_port],
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration._volume_fingerprints",
        return_value={str(source_volume).casefold(): source_info},
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_profile_volume",
        return_value=target_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port",
        return_value=runtime_port,
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_dfu_package")
    serial_dfu = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")

    result = migrate_nrf(
        mcu,
        application,
        get_profile("s140-7.3.0"),
        confirm=lambda message: "erases" in message,
    )

    assert result is mcu
    assert mcu.family == "micropython"
    assert mcu.serialport == "COM81"
    assert mcu.serial_number == "runtime"
    assert mcu.softdevice == "S140 7.3.0"
    assert serial_dfu.call_args.args[1] == "COM76"
    assert wait_bootloader.call_args_list[0].kwargs["expected_location"] == "1-1"
    assert wait_bootloader.call_args_list[1].kwargs["preferred_port"] == "COM76"
    assert wait_bootloader.call_args_list[1].kwargs["expected_usb_id"] == (0x1209, 0x5284)
    copy.assert_called_once_with(application, target_volume)


def test_migrate_nrf_cancellation_performs_no_writes(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    source_volume = Path("E:/")
    source_port = BootloaderPort("COM76", 0x239A, 0x00B3, "source", "1-1")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes", return_value=set())
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader",
        return_value=source_volume,
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=Uf2BoardInfo(
            board_id="nRF52840-nicenano",
            bootloader_version="0.6.0",
            softdevice="S140 6.1.1",
        ),
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        return_value=source_port,
    )
    serial_dfu = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port",
        return_value=BootloaderPort("COM77", 0x239A, 0x8052, "runtime", "1-1"),
    )

    with pytest.raises(MPFlashError, match="cancelled before any writes"):
        migrate_nrf(
            mcu,
            application,
            get_profile("s140-7.3.0"),
            confirm=lambda message: False,
        )

    serial_dfu.assert_not_called()
    copy.assert_not_called()


def test_migrate_nrf_reports_serial_dfu_failure_stage(mocker, tmp_path: Path):
    mcu, application = _prepare_destructive_migration(mocker, tmp_path)
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu",
        side_effect=MPFlashError("transfer failed"),
    )
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")

    with pytest.raises(MPFlashError, match=r"during SoftDevice\+bootloader Serial DFU: transfer failed"):
        migrate_nrf(mcu, application, get_profile("s140-7.3.0"), confirm=lambda message: True)

    copy.assert_not_called()


def test_migrate_nrf_reports_target_bootloader_failure_stage(mocker, tmp_path: Path):
    mcu, application = _prepare_destructive_migration(mocker, tmp_path)
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_profile_volume",
        side_effect=MPFlashError("target missing"),
    )
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")

    with pytest.raises(MPFlashError, match="during target bootloader verification: target missing"):
        migrate_nrf(mcu, application, get_profile("s140-7.3.0"), confirm=lambda message: True)

    copy.assert_not_called()


def test_migrate_nrf_reports_application_copy_failure_stage(mocker, tmp_path: Path):
    mcu, application = _prepare_destructive_migration(mocker, tmp_path)
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2",
        side_effect=OSError("copy failed"),
    )

    with pytest.raises(MPFlashError, match="during matching application UF2 transfer: Could not copy.*copy failed"):
        migrate_nrf(mcu, application, get_profile("s140-7.3.0"), confirm=lambda message: True)


def test_migrate_nrf_reports_runtime_failure_stage(mocker, tmp_path: Path):
    mcu, application = _prepare_destructive_migration(mocker, tmp_path)
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port",
        side_effect=MPFlashError("runtime missing"),
    )

    with pytest.raises(MPFlashError, match="during runtime verification: runtime missing"):
        migrate_nrf(mcu, application, get_profile("s140-7.3.0"), confirm=lambda message: True)


def test_migrate_nrf_skips_dfu_when_exact_profile_is_installed(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    volume = Path("E:/")
    profile = get_profile("s140-6.1.1")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes", return_value=set())
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader", return_value=volume)
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=Uf2BoardInfo(
            board_id=profile.board_id,
            bootloader_version=profile.bootloader_version,
            softdevice=profile.softdevice,
        ),
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        return_value=BootloaderPort("COM76", profile.usb_vid, profile.usb_pid, "source", "1-1"),
    )
    serial_dfu = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port",
        return_value=BootloaderPort("COM77", 0x239A, 0x8052, "runtime", "1-1"),
    )
    confirm = mocker.Mock(return_value=True)

    migrate_nrf(mcu, application, profile, confirm=confirm)

    confirm.assert_not_called()
    serial_dfu.assert_not_called()
    copy.assert_called_once_with(application, volume)


def test_migrate_nrf_force_repairs_exact_profile(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    volume = Path("E:/")
    profile = get_profile("s140-7.3.0")
    info = Uf2BoardInfo(
        board_id=profile.board_id,
        bootloader_version=profile.bootloader_version,
        softdevice=profile.softdevice,
    )
    bootloader_port = BootloaderPort("COM79", profile.usb_vid, profile.usb_pid, "bootloader", "1-1")
    runtime_port = BootloaderPort("COM77", 0x239A, 0x8052, "runtime", "1-1")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes",
        side_effect=[set(), {volume}],
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader", return_value=volume)
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info", return_value=info)
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        side_effect=[bootloader_port, bootloader_port],
    )
    fingerprints = mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration._volume_fingerprints",
        return_value={str(volume).casefold(): info},
    )
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.wait_for_profile_volume", return_value=volume)
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.wait_for_runtime_port", return_value=runtime_port)
    inspect_package = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_dfu_package")
    serial_dfu = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")
    confirm = mocker.Mock(return_value=True)

    migrate_nrf(mcu, application, profile, confirm=confirm, force_repair=True)

    prompt = confirm.call_args.args[0]
    assert "Force-repair" in prompt
    assert "metadata" in prompt
    fingerprints.assert_called_once()
    inspect_package.assert_called_once()
    assert serial_dfu.call_args.args[1] == "COM79"
    copy.assert_called_once_with(application, volume)


def test_migrate_nrf_force_repair_cancellation_performs_no_writes(mocker, tmp_path: Path):
    mcu = _mcu()
    application = tmp_path / "firmware.uf2"
    application.write_bytes(b"uf2")
    volume = Path("E:/")
    profile = get_profile("s140-7.3.0")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.inspect_application_uf2")
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.mounted_uf2_volumes", return_value=set())
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.snapshot_bootloader_ports", return_value={})
    mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.enter_nrf_uf2_bootloader", return_value=volume)
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.read_uf2_board_info",
        return_value=Uf2BoardInfo(
            board_id=profile.board_id,
            bootloader_version=profile.bootloader_version,
            softdevice=profile.softdevice,
        ),
    )
    mocker.patch(
        "mpflash.flash.builtins.nrf_dfu.migration.wait_for_bootloader_port",
        return_value=BootloaderPort("COM79", profile.usb_vid, profile.usb_pid, "bootloader", "1-1"),
    )
    serial_dfu = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.flash_serial_dfu")
    copy = mocker.patch("mpflash.flash.builtins.nrf_dfu.migration.copy_firmware_to_uf2")

    with pytest.raises(MPFlashError, match="cancelled before any writes"):
        migrate_nrf(
            mcu,
            application,
            profile,
            confirm=lambda message: False,
            force_repair=True,
        )

    serial_dfu.assert_not_called()
    copy.assert_not_called()
