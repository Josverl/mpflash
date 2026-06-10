"""Unit tests for the pluggable flash backend registry."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from mpflash.errors import MPFlashError
from mpflash.flash.base import FlashBackend
from mpflash.flash.context import FlashContext, FlashResult, Platform, Reason
from mpflash.flash.registry import (
    get_backend,
    get_backends,
    register,
    select_backend,
    unregister,
)


def _fake_mcu(port: str = "rp2", board_id: str = "PIMORONI_TINY2040", cpu: str = "RP2040"):
    """Return a minimal stand-in for MPRemoteBoard with just the fields the registry reads."""
    return SimpleNamespace(
        port=port,
        board=board_id,
        board_id=board_id,
        cpu=cpu,
        serialport="/dev/ttyACM0",
    )


# ---------------------------------------------------------------------------
# Built-in registration sanity checks
# ---------------------------------------------------------------------------


def test_builtin_backends_register_on_import():
    names = {b.name for b in get_backends()}
    assert {"uf2", "dfu", "esptool", "pyocd"}.issubset(names)


# ---------------------------------------------------------------------------
# select_backend: auto + explicit + error paths
# ---------------------------------------------------------------------------


def test_select_uf2_for_rp2_uf2(tmp_path: Path):
    mcu = _fake_mcu(port="rp2")
    fw = tmp_path / "firmware.uf2"
    fw.write_bytes(b"\x00")
    backend = select_backend(mcu, fw)
    assert backend.name == "uf2"


def test_select_dfu_for_stm32_dfu(tmp_path: Path):
    mcu = _fake_mcu(port="stm32", board_id="PYBV11", cpu="STM32F405")
    fw = tmp_path / "firmware.dfu"
    fw.write_bytes(b"\x00")
    backend = select_backend(mcu, fw)
    assert backend.name == "dfu"


def test_auto_prefers_dfu_over_pyocd_for_stm32_bin(tmp_path: Path):
    """A ``.bin`` for stm32 should auto-pick DFU (priority 10) over pyOCD (-10)."""
    mcu = _fake_mcu(port="stm32", board_id="PYBV11", cpu="STM32F405")
    fw = tmp_path / "firmware.bin"
    fw.write_bytes(b"\x00")
    backend = select_backend(mcu, fw)
    assert backend.name == "dfu"


def test_explicit_pyocd_method_routes_to_pyocd(tmp_path: Path, monkeypatch):
    """Even though auto skips pyOCD, requesting it by name should succeed when supported."""
    mcu = _fake_mcu(port="stm32", board_id="PYBV11", cpu="STM32F405")
    fw = tmp_path / "firmware.bin"
    fw.write_bytes(b"\x00")
    # Stub out pyOCD availability + target lookup so the test doesn't need pyOCD installed.
    monkeypatch.setattr(
        "mpflash.flash.builtins.pyocd_backend.PyOCDBackend.is_available",
        lambda self: True,
    )
    monkeypatch.setattr(
        "mpflash.flash.builtins.pyocd.core.is_pyocd_supported", lambda mcu: True
    )
    backend = select_backend(mcu, fw, requested_name="pyocd")
    assert backend.name == "pyocd"


def test_unsupported_port_raises_with_reasons(tmp_path: Path):
    mcu = _fake_mcu(port="unknown_port", board_id="MYSTERY")
    fw = tmp_path / "firmware.uf2"
    fw.write_bytes(b"\x00")
    with pytest.raises(MPFlashError) as excinfo:
        select_backend(mcu, fw)
    msg = str(excinfo.value)
    # Diagnostic should mention at least one backend's rejection reason.
    assert "uf2" in msg or "dfu" in msg or "esptool" in msg


def test_unknown_requested_method_raises(tmp_path: Path):
    mcu = _fake_mcu(port="rp2")
    fw = tmp_path / "firmware.uf2"
    fw.write_bytes(b"\x00")
    with pytest.raises(MPFlashError, match="Unknown flash method"):
        select_backend(mcu, fw, requested_name="does-not-exist")


# ---------------------------------------------------------------------------
# Third-party plugin registration
# ---------------------------------------------------------------------------


class _ToyBackend(FlashBackend):
    name = "toy"
    supported_ports = frozenset({"toy"})
    supported_formats = (".toy",)
    supported_platforms = frozenset(
        {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
    )
    priority = 50

    def flash(self, ctx: FlashContext) -> FlashResult:
        return FlashResult(success=True, mcu=ctx.mcu, backend=self.name)


def test_external_plugin_registration(tmp_path: Path):
    register(_ToyBackend())
    try:
        assert get_backend("toy") is not None
        mcu = _fake_mcu(port="toy", board_id="TOY1", cpu="TOY")
        fw = tmp_path / "firmware.toy"
        fw.write_bytes(b"\x00")
        backend = select_backend(mcu, fw)
        assert backend.name == "toy"
    finally:
        unregister("toy")


# ---------------------------------------------------------------------------
# WSL2 path handling (uf2.volume.translate_volume_path)
# ---------------------------------------------------------------------------


def test_translate_volume_path_wsl2(monkeypatch):
    from mpflash.flash.builtins.uf2 import volume

    monkeypatch.setattr(volume, "_platform", lambda: Platform.WSL2)
    assert volume.translate_volume_path("D:\\") == "/mnt/d"
    assert volume.translate_volume_path("D:/") == "/mnt/d"
    assert volume.translate_volume_path("/mnt/d") == "/mnt/d"  # passthrough


def test_translate_volume_path_other_platforms(monkeypatch):
    from mpflash.flash.builtins.uf2 import volume

    for plat in (Platform.LINUX, Platform.WINDOWS, Platform.MACOS):
        monkeypatch.setattr(volume, "_platform", lambda p=plat: p)
        assert volume.translate_volume_path("D:\\") == "D:\\"


# ---------------------------------------------------------------------------
# supports() returns a Reason for unsupported combos
# ---------------------------------------------------------------------------


def test_supports_returns_reason_for_wrong_format(tmp_path: Path):
    from mpflash.flash.builtins.uf2_backend import UF2Backend

    mcu = _fake_mcu(port="rp2")
    fw = tmp_path / "firmware.bin"
    fw.write_bytes(b"\x00")
    reason = UF2Backend().supports(mcu, fw, Platform.LINUX)
    assert isinstance(reason, Reason)
    assert reason.kind == "format"
