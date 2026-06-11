from pathlib import Path

from mpflash.flash.builtins.uf2 import volume
from mpflash.flash.context import Platform


def test_translate_volume_path_wsl2_drive_letters(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.WSL2)
    assert volume.translate_volume_path("D:\\") == "/mnt/d"
    assert volume.translate_volume_path("E:/") == "/mnt/e"


def test_translate_volume_path_passthrough_non_wsl(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.LINUX)
    assert volume.translate_volume_path("D:\\") == "D:\\"


def test_wait_for_volume_dispatches_by_platform(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.LINUX)
    m_linux = mocker.patch("mpflash.flash.builtins.uf2.linux.wait_for_UF2_linux", return_value=Path("/mnt/a"))
    assert volume.wait_for_volume("RP2", timeout=2) == Path("/mnt/a")
    m_linux.assert_called_once_with(board_id="RP2", s_max=2)

    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.WINDOWS)
    m_win = mocker.patch("mpflash.flash.builtins.uf2.windows.wait_for_UF2_windows", return_value=Path("D:/"))
    assert volume.wait_for_volume("RP2", timeout=2) == Path("D:/")
    m_win.assert_called_once_with(board_id="RP2", s_max=2)

    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.MACOS)
    m_mac = mocker.patch("mpflash.flash.builtins.uf2.macos.wait_for_UF2_macos", return_value=Path("/Volumes/RPI"))
    assert volume.wait_for_volume("RP2", timeout=2) == Path("/Volumes/RPI")
    m_mac.assert_called_once_with(board_id="RP2", s_max=2)

    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.WSL2)
    m_wsl = mocker.patch("mpflash.flash.builtins.uf2.wsl2.wait_for_UF2_wsl2", return_value=Path("/mnt/d"))
    assert volume.wait_for_volume("RP2", timeout=2) == Path("/mnt/d")
    m_wsl.assert_called_once_with(board_id="RP2", s_max=2)


def test_wait_for_volume_unknown_platform_returns_none(mocker):
    fake_platform = type("P", (), {"value": "unknown"})()
    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=fake_platform)
    assert volume.wait_for_volume("RP2", timeout=1) is None


def test_resolve_explicit_volume_valid_and_invalid(tmp_path, mocker):
    good = tmp_path / "uf2"
    good.mkdir()
    (good / "INFO_UF2.TXT").write_text("UF2")

    mocker.patch("mpflash.flash.builtins.uf2.volume.translate_volume_path", side_effect=lambda s: s)

    assert volume.resolve_explicit_volume(str(good)) == good
    assert volume.resolve_explicit_volume(str(tmp_path / "missing")) is None
    assert volume.resolve_explicit_volume("") is None


def test_dismount_dispatches_linux_and_wsl2(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.LINUX)
    m_linux = mocker.patch("mpflash.flash.builtins.uf2.linux.dismount_uf2_linux")
    volume.dismount()
    m_linux.assert_called_once()

    mocker.patch("mpflash.flash.builtins.uf2.volume._platform", return_value=Platform.WSL2)
    m_wsl = mocker.patch("mpflash.flash.builtins.uf2.wsl2.dismount_uf2_wsl2")
    volume.dismount()
    m_wsl.assert_called_once()
