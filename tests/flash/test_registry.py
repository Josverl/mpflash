"""Unit tests for the pluggable flash backend registry."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional
import types

import pytest

from mpflash.common import FlashMethod
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
from mpflash.flash import flash_mcu


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


def test_flash_mcu_pyocd_target_override_bypasses_target_lookup(
    tmp_path: Path, monkeypatch
):
    """Explicit target override should not require metadata-based pyOCD support."""
    mcu = _fake_mcu(port="rp2", board_id="RPI_PICO", cpu="RP2040")
    fw = tmp_path / "firmware.elf"
    fw.write_bytes(b"\x00")

    class _Backend:
        name = "pyocd"
        supported_formats = (".bin", ".hex", ".elf", ".axf")
        supported_platforms = frozenset(
            {Platform.LINUX, Platform.WINDOWS, Platform.MACOS, Platform.WSL2}
        )

        def is_available(self):
            return True

        def flash(self, ctx):
            assert ctx.options["target_override"] == "rp2040"
            return FlashResult(success=True, mcu=ctx.mcu, backend=self.name)

    monkeypatch.setattr("mpflash.flash.get_backend", lambda name: _Backend())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("select_backend should not be called with target override")

    monkeypatch.setattr("mpflash.flash.select_backend", _fail_if_called)

    updated = flash_mcu(
        mcu,
        fw_file=fw,
        method=FlashMethod.PYOCD,
        target_override="rp2040",
    )

    assert updated is not None


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


def test_register_backend_without_name_raises():
    class _Nameless(FlashBackend):
        name = ""

        def flash(self, ctx: FlashContext) -> FlashResult:
            return FlashResult(success=True, mcu=ctx.mcu, backend="")

    with pytest.raises(ValueError, match="has no 'name'"):
        register(_Nameless())


def test_discover_entry_points_old_api_and_failure_paths(mocker):
    import mpflash.flash.registry as reg

    class _EP:
        def __init__(self, name, loaded=None, exc=None):
            self.name = name
            self._loaded = loaded
            self._exc = exc

        def load(self):
            if self._exc:
                raise self._exc
            return self._loaded

    good_backend = _ToyBackend
    eps = [
        _EP("bad-load", exc=RuntimeError("boom")),
        _EP("good", loaded=good_backend),
        _EP("bad-register", loaded=object()),
    ]

    def fake_entry_points(*args, **kwargs):
        if kwargs:
            raise TypeError("old API")
        return {"mpflash.flash_plugins": eps}

    mocker.patch("importlib.metadata.entry_points", side_effect=fake_entry_points)
    reg._entry_points_loaded = False

    reg.discover_entry_points()
    assert reg.get_backend("toy") is not None
    unregister("toy")


def test_flash_mcu_pyocd_override_error_paths(tmp_path: Path, monkeypatch):
    import mpflash.flash as flash_mod

    mcu = _fake_mcu(port="rp2", board_id="RPI_PICO", cpu="RP2040")
    fw = tmp_path / "firmware.elf"
    fw.write_bytes(b"x")

    class _Backend:
        name = "pyocd"
        supported_formats = (".bin", ".hex", ".elf", ".axf")
        supported_platforms = frozenset({Platform.LINUX})

        def is_available(self):
            return True

        def flash(self, ctx):
            return FlashResult(success=True, mcu=ctx.mcu, backend=self.name)

    monkeypatch.setattr(flash_mod, "get_backend", lambda name: None)
    with pytest.raises(MPFlashError, match="Unknown flash method 'pyocd'"):
        flash_mcu(mcu, fw_file=fw, method=FlashMethod.PYOCD, target_override="rp2040")

    backend = _Backend()
    monkeypatch.setattr(flash_mod, "get_backend", lambda name: backend)
    with pytest.raises(MPFlashError, match="unsupported format"):
        flash_mcu(mcu, fw_file=tmp_path / "firmware.dfu", method=FlashMethod.PYOCD, target_override="rp2040")

    current = flash_mod.default_services.current_platform()
    other_platform = next(p for p in Platform if p != current)
    backend.supported_platforms = frozenset({other_platform})
    with pytest.raises(MPFlashError, match="does not run on"):
        flash_mcu(mcu, fw_file=fw, method=FlashMethod.PYOCD, target_override="rp2040")

    backend.supported_platforms = frozenset({flash_mod.default_services.current_platform()})
    backend.is_available = lambda: False
    with pytest.raises(MPFlashError, match="pyOCD is not installed"):
        flash_mcu(mcu, fw_file=fw, method=FlashMethod.PYOCD, target_override="rp2040")


def test_flash_mcu_wraps_select_and_backend_errors(tmp_path: Path, monkeypatch):
    import mpflash.flash as flash_mod

    mcu = _fake_mcu(port="rp2", board_id="RPI_PICO", cpu="RP2040")
    fw = tmp_path / "firmware.uf2"
    fw.write_bytes(b"x")

    monkeypatch.setattr(flash_mod, "select_backend", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("explode")))
    with pytest.raises(MPFlashError, match="Failed to select flash backend"):
        flash_mcu(mcu, fw_file=fw)

    class _Backend:
        name = "uf2"

        def flash(self, ctx):
            raise RuntimeError("flash exploded")

    monkeypatch.setattr(flash_mod, "select_backend", lambda *a, **k: _Backend())
    with pytest.raises(MPFlashError, match="Failed to flash"):
        flash_mcu(mcu, fw_file=fw)

    class _BackendResult:
        name = "uf2"

        def flash(self, ctx):
            return FlashResult(success=False, mcu=None, backend=self.name, message="bad")

    monkeypatch.setattr(flash_mod, "select_backend", lambda *a, **k: _BackendResult())
    with pytest.raises(MPFlashError, match="bad"):
        flash_mcu(mcu, fw_file=fw)
