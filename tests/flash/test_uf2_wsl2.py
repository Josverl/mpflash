from pathlib import Path

from mpflash.flash.builtins.uf2 import wsl2


def test_candidate_mounts_returns_existing_dirs(mocker):
    m_is_dir = mocker.patch("pathlib.Path.is_dir", autospec=True)

    def fake_is_dir(self):
        p = self.as_posix()
        if p == "/mnt":
            return True
        if p in {"/mnt/c", "/mnt/d"}:
            return True
        if p == "/mnt/e":
            raise OSError("drvfs error")
        return False

    m_is_dir.side_effect = fake_is_dir

    mounts = wsl2._candidate_mounts()

    assert Path("/mnt/c") in mounts
    assert Path("/mnt/d") in mounts
    assert Path("/mnt/e") not in mounts


def test_candidate_mounts_returns_empty_when_mnt_missing(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.Path.is_dir", return_value=False)
    assert wsl2._candidate_mounts() == []


def test_wait_for_uf2_wsl2_finds_matching_board(mocker):
    mount = Path("/mnt/d")
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.track", side_effect=lambda it, **_: it)
    mocker.patch("mpflash.flash.builtins.uf2.wsl2._candidate_mounts", return_value=[mount])
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.get_board_id", return_value="RPI-RP2")
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.time.sleep")
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.Path.exists", return_value=True)

    assert wsl2.wait_for_UF2_wsl2("RP2", s_max=1) == mount


def test_wait_for_uf2_wsl2_times_out(mocker):
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.track", side_effect=lambda it, **_: it)
    mocker.patch("mpflash.flash.builtins.uf2.wsl2._candidate_mounts", return_value=[])
    m_sleep = mocker.patch("mpflash.flash.builtins.uf2.wsl2.time.sleep")

    assert wsl2.wait_for_UF2_wsl2("RP2", s_max=1) is None
    m_sleep.assert_called_once_with(1)


def test_wait_for_uf2_wsl2_ignores_mount_probe_errors(mocker):
    mount = Path("/mnt/d")
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.track", side_effect=lambda it, **_: it)
    mocker.patch("mpflash.flash.builtins.uf2.wsl2._candidate_mounts", return_value=[mount])
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.Path.exists", return_value=True)
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.get_board_id", side_effect=OSError("read error"))
    mocker.patch("mpflash.flash.builtins.uf2.wsl2.time.sleep")

    assert wsl2.wait_for_UF2_wsl2("RP2", s_max=1) is None


def test_dismount_uf2_wsl2_is_noop():
    assert wsl2.dismount_uf2_wsl2() is None
