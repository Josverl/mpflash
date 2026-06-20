from pathlib import Path

import pytest

from mpflash.build import (
    BuildManager,
    _detect_port_from_board_id,
    get_port_preferred_suffixes,
    import_firmware_to_database,
)
from mpflash.config import config
from mpflash.db.models import Board, Firmware


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
