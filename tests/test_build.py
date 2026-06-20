from pathlib import Path
import subprocess
import types

import pytest

from mpflash.build import (
    BuildManager,
    _split_board_variant,
    build_firmware,
    clean_firmware,
    _detect_port_from_board_id,
    get_build_unavailable_reason,
    get_port_preferred_suffixes,
    import_firmware_to_database,
    is_build_available,
)
from mpflash.config import config
from mpflash.db.models import Board, Firmware
from mpflash.errors import MPFlashError


@pytest.mark.parametrize(
    "board_id, expected_port",
    [
        ("NUCLEO_H563ZI", "stm32"),
        ("RPI_PICO2", "rp2"),
        ("ESP32_GENERIC", "esp32"),
        ("ESP8266_GENERIC", "esp8266"),
        ("SEEED_WIO_TERMINAL", "samd"),
        ("UNKNOWN_BOARD", "unknown"),
    ],
)
def test_detect_port_from_board_id(board_id: str, expected_port: str):
    assert _detect_port_from_board_id(board_id) == expected_port


def test_import_firmware_to_database_creates_board_and_firmware_records(session_fx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_firmware_folder", tmp_path)

    inside_file = tmp_path / "esp8266" / "ESP8266_GENERIC-v1.26.0.bin"
    inside_file.parent.mkdir(parents=True, exist_ok=True)
    inside_file.write_bytes(b"firmware")

    outside_file = tmp_path.parent / "ESP8266_GENERIC-v1.26.0.elf"
    outside_file.write_bytes(b"elf")

    imported = import_firmware_to_database(
        [inside_file, outside_file],
        board_id="ESP8266_GENERIC",
        version="v1.26.0",
    )

    assert imported == 2

    board = Board.get((Board.board_id == "ESP8266_GENERIC") & (Board.version == "v1.26.0"))
    assert board.port == "esp8266"
    assert board.custom is True
    assert board.path == "built"

    firmware_rows = list(Firmware.select().where((Firmware.board_id == "ESP8266_GENERIC") & (Firmware.version == "v1.26.0")))
    assert len(firmware_rows) == 2
    assert any(fw.firmware_file == "esp8266/ESP8266_GENERIC-v1.26.0.bin" for fw in firmware_rows)
    assert any(fw.firmware_file == outside_file.as_posix() for fw in firmware_rows)


def test_import_firmware_to_database_upserts_existing_firmware(session_fx, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_firmware_folder", tmp_path)

    firmware_file = tmp_path / "rp2" / "RPI_PICO2-v1.26.0.uf2"
    firmware_file.parent.mkdir(parents=True, exist_ok=True)
    firmware_file.write_bytes(b"uf2")

    first = import_firmware_to_database(
        [firmware_file],
        board_id="RPI_PICO2",
        version="v1.26.0",
    )
    second = import_firmware_to_database(
        [firmware_file],
        board_id="RPI_PICO2",
        version="v1.26.0",
    )

    assert first == 1
    assert second == 1

    rows = list(Firmware.select().where((Firmware.board_id == "RPI_PICO2") & (Firmware.version == "v1.26.0")))
    assert len(rows) == 1
    assert rows[0].firmware_file == "rp2/RPI_PICO2-v1.26.0.uf2"


@pytest.mark.parametrize(
    "port, expected",
    [
        ("esp8266", {".bin"}),
        ("esp32", {".bin"}),
        ("rp2", {".uf2"}),
        ("stm32", {".dfu", ".bin"}),
        ("unknown", set()),
    ],
)
def test_get_port_preferred_suffixes(port: str, expected: set[str]):
    assert get_port_preferred_suffixes(port) == expected


def test_find_firmware_files_in_repo_finds_correct_port(tmp_path):
    """Verify _find_firmware_files_in_repo finds firmware in the correct port directory."""
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"

    # Create wrong build in wrong port
    wrong_build = mpy_root / "ports" / "psoc-edge" / "build-KIT_PSE84_AI"
    wrong_build.mkdir(parents=True, exist_ok=True)
    (wrong_build / "firmware.hex").write_bytes(b"wrong")

    # Create correct build in correct port
    right_build = mpy_root / "ports" / "esp8266" / "build-ESP8266_GENERIC"
    right_build.mkdir(parents=True, exist_ok=True)
    (right_build / "firmware.bin").write_bytes(b"right")

    # Search for files with preferred extension
    found = manager._find_firmware_files_in_repo(
        mpy_root,
        "ESP8266_GENERIC",
        port="esp8266",
        preferred_suffixes={".bin"},
    )

    assert len(found) == 1
    assert found[0].name == "firmware.bin"
    assert found[0].parent == right_build


def test_find_firmware_files_with_variant(tmp_path):
    """Verify _find_firmware_files_in_repo handles board variants correctly."""
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"

    # Create build with variant in path
    build_with_variant = mpy_root / "ports" / "rp2" / "build-RPI_PICO2-RISCV"
    build_with_variant.mkdir(parents=True, exist_ok=True)
    (build_with_variant / "firmware.uf2").write_bytes(b"uf2")

    found = manager._find_firmware_files_in_repo(
        mpy_root,
        "RPI_PICO2",
        variant="RISCV",
        port="rp2",
        preferred_suffixes={".uf2"},
    )

    assert len(found) == 1
    assert found[0].suffix == ".uf2"
    assert "RISCV" in str(found[0].parent)


def test_find_firmware_files_prefers_suffixes_in_order(tmp_path):
    """Verify _find_firmware_files_in_repo prefers extensions in specified order."""
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"

    build_dir = mpy_root / "ports" / "rp2" / "build-RPI_PICO2"
    build_dir.mkdir(parents=True, exist_ok=True)

    # Create multiple firmware files
    (build_dir / "firmware.uf2").write_bytes(b"uf2")
    (build_dir / "firmware.bin").write_bytes(b"bin")
    (build_dir / "firmware.hex").write_bytes(b"hex")

    # Request in specific order: .uf2 first
    found = manager._find_firmware_files_in_repo(
        mpy_root,
        "RPI_PICO2",
        port="rp2",
        preferred_suffixes={".uf2", ".bin"},
    )

    assert len(found) >= 1
    assert found[0].suffix == ".uf2"


def test_get_or_build_returns_cached_files(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    cached = [tmp_path / "cache" / "fw.bin"]

    m_find_cached = mocker.patch.object(manager, "_find_cached", return_value=cached)
    m_ensure = mocker.patch.object(manager, "_ensure_mpbuild_available")
    m_docker = mocker.patch.object(manager, "_check_docker_available")
    m_build = mocker.patch.object(manager, "_build_firmware")

    result = manager.get_or_build("ESP32_GENERIC", "v1.29.0")

    assert result == cached
    m_find_cached.assert_called_once()
    m_ensure.assert_not_called()
    m_docker.assert_not_called()
    m_build.assert_not_called()


def test_get_or_build_force_rebuilds_even_when_cache_exists(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")

    m_find_cached = mocker.patch.object(manager, "_find_cached")
    m_ensure = mocker.patch.object(manager, "_ensure_mpbuild_available")
    m_docker = mocker.patch.object(manager, "_check_docker_available")
    m_build = mocker.patch.object(manager, "_build_firmware", return_value=[])

    manager.get_or_build("ESP32_GENERIC", "v1.29.0", force=True)

    m_find_cached.assert_not_called()
    m_ensure.assert_called_once()
    m_docker.assert_called_once()
    m_build.assert_called_once()


def test_find_cached_filters_by_suffix(tmp_path):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    cache_dir = manager.cache_dir / manager._cache_key("ESP32_GENERIC", "v1.0.0")
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "a.bin").write_bytes(b"x")
    (cache_dir / "a.hex").write_bytes(b"x")

    files = manager._find_cached("ESP32_GENERIC", "v1.0.0", preferred_suffixes={".bin"})

    assert [f.name for f in files] == ["a.bin"]


def test_ensure_mpbuild_available_import_error(tmp_path, monkeypatch):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "mpbuild":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(MPFlashError, match="mpbuild is not installed"):
        manager._ensure_mpbuild_available()


def test_ensure_mpbuild_available_type_error_variants(tmp_path, monkeypatch):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    real_import = __import__

    def old_python_import(name, *args, **kwargs):
        if name == "mpbuild":
            raise TypeError("unsupported operand type(s) for |")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", old_python_import)
    with pytest.raises(MPFlashError, match="requires Python 3.10"):
        manager._ensure_mpbuild_available()

    def generic_type_error_import(name, *args, **kwargs):
        if name == "mpbuild":
            raise TypeError("other type error")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", generic_type_error_import)
    with pytest.raises(MPFlashError, match="Error importing mpbuild"):
        manager._ensure_mpbuild_available()


def test_check_docker_available_error_paths(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")

    # non-zero exit code
    mocker.patch(
        "mpflash.build.subprocess.run",
        return_value=types.SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(MPFlashError, match="Docker command failed"):
        manager._check_docker_available()

    # docker executable not found
    mocker.patch("mpflash.build.subprocess.run", side_effect=FileNotFoundError())
    with pytest.raises(MPFlashError, match="Docker not found"):
        manager._check_docker_available()

    # timeout while checking docker
    mocker.patch(
        "mpflash.build.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker --version", timeout=10),
    )
    with pytest.raises(MPFlashError, match="timed out"):
        manager._check_docker_available()


def test_build_firmware_caches_preferred_suffix(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"
    build_dir = mpy_root / "ports" / "esp32" / "build-ESP32_GENERIC"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "firmware.bin").write_bytes(b"bin")
    (build_dir / "firmware.elf").write_bytes(b"elf")

    fake_build_mod = types.ModuleType("mpbuild.build")
    fake_find_mod = types.ModuleType("mpbuild.find_boards")
    fake_build_mod.build_board = mocker.Mock()
    fake_build_mod.clean_board = mocker.Mock()
    fake_find_mod.find_mpy_root = mocker.Mock(return_value=(mpy_root, None))

    mocker.patch.dict(
        "sys.modules",
        {
            "mpbuild.build": fake_build_mod,
            "mpbuild.find_boards": fake_find_mod,
        },
    )

    files = manager._build_firmware(
        "ESP32_GENERIC",
        "v1.30.0",
        preferred_suffixes={".bin"},
    )

    assert len(files) == 1
    assert files[0].suffix == ".bin"
    assert files[0].exists()


def test_build_firmware_wraps_unexpected_errors(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"
    mpy_root.mkdir(parents=True, exist_ok=True)

    fake_build_mod = types.ModuleType("mpbuild.build")
    fake_find_mod = types.ModuleType("mpbuild.find_boards")
    fake_build_mod.build_board = mocker.Mock(side_effect=RuntimeError("boom"))
    fake_find_mod.find_mpy_root = mocker.Mock(return_value=(mpy_root, None))

    mocker.patch.dict(
        "sys.modules",
        {
            "mpbuild.build": fake_build_mod,
            "mpbuild.find_boards": fake_find_mod,
        },
    )

    with pytest.raises(MPFlashError, match="Build failed"):
        manager._build_firmware("ESP32_GENERIC", "latest")


def test_clean_calls_clean_board(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"
    mpy_root.mkdir(parents=True, exist_ok=True)

    mocker.patch.object(manager, "_ensure_mpbuild_available")
    mocker.patch.object(manager, "_check_docker_available")

    fake_build_mod = types.ModuleType("mpbuild.build")
    fake_find_mod = types.ModuleType("mpbuild.find_boards")
    fake_clean = mocker.Mock()
    fake_build_mod.clean_board = fake_clean
    fake_find_mod.find_mpy_root = mocker.Mock(return_value=(mpy_root, None))

    mocker.patch.dict(
        "sys.modules",
        {
            "mpbuild.build": fake_build_mod,
            "mpbuild.find_boards": fake_find_mod,
        },
    )

    manager.clean("RPI_PICO2-RISCV")

    fake_clean.assert_called_once_with("RPI_PICO2", variant="RISCV", mpy_dir=str(mpy_root))


def test_clean_raises_when_repo_not_found(tmp_path, mocker):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mocker.patch.object(manager, "_ensure_mpbuild_available")
    mocker.patch.object(manager, "_check_docker_available")

    fake_build_mod = types.ModuleType("mpbuild.build")
    fake_find_mod = types.ModuleType("mpbuild.find_boards")
    fake_build_mod.clean_board = mocker.Mock()
    fake_find_mod.find_mpy_root = mocker.Mock(side_effect=SystemExit())

    mocker.patch.dict(
        "sys.modules",
        {
            "mpbuild.build": fake_build_mod,
            "mpbuild.find_boards": fake_find_mod,
        },
    )

    with pytest.raises(MPFlashError, match="Could not find a MicroPython repository"):
        manager.clean("RPI_PICO2")


def test_find_build_output_and_split_variant(tmp_path):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    search = tmp_path / "root"
    search.mkdir()
    (search / "build").mkdir()

    assert manager._find_build_output(search, "ESP32_GENERIC") == search / "build"
    assert _split_board_variant("RPI_PICO2-RISCV") == ("RPI_PICO2", "RISCV")
    assert _split_board_variant("RPI_PICO2") == ("RPI_PICO2", None)


def test_find_build_output_raises_when_missing(tmp_path):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    with pytest.raises(MPFlashError, match="Could not locate build output"):
        manager._find_build_output(tmp_path / "none", "ESP32_GENERIC")


def test_find_firmware_files_in_repo_errors_and_fallback(tmp_path):
    manager = BuildManager(cache_dir=tmp_path / "cache")
    mpy_root = tmp_path / "micropython"

    with pytest.raises(MPFlashError, match="not specific enough"):
        manager._find_firmware_files_in_repo(mpy_root, "ESP32_GENERIC", port="unknown")

    # canonical path missing, fallback path exists
    fallback_dir = mpy_root / "ports" / "rp2" / "build-RPI_PICO2"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    fw = fallback_dir / "firmware.uf2"
    fw.write_bytes(b"uf2")

    found = manager._find_firmware_files_in_repo(
        mpy_root,
        "RPI_PICO2",
        variant="RISCV",
        port="rp2",
        preferred_suffixes={".uf2"},
    )
    assert fw in found


def test_build_helpers_and_availability(mocker):
    m_get = mocker.patch.object(BuildManager, "get_or_build", return_value=[])
    m_clean = mocker.patch.object(BuildManager, "clean")
    m_ensure = mocker.patch.object(BuildManager, "_ensure_mpbuild_available")
    m_docker = mocker.patch.object(BuildManager, "_check_docker_available")

    assert is_build_available() is True
    assert get_build_unavailable_reason() == ""

    build_firmware("ESP32_GENERIC", "latest")
    clean_firmware("ESP32_GENERIC")
    m_get.assert_called_once()
    m_clean.assert_called_once()
    m_ensure.assert_called()
    m_docker.assert_called()


def test_build_helpers_report_unavailable_reason(mocker):
    mocker.patch.object(BuildManager, "_ensure_mpbuild_available", side_effect=MPFlashError("missing mpbuild"))
    assert is_build_available() is False
    assert get_build_unavailable_reason() == "missing mpbuild"
