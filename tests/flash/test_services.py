"""Tests for flash services platform detection and best-effort reenumeration."""

from __future__ import annotations

from types import SimpleNamespace

from mpflash.flash.context import Platform
from mpflash.flash.services import FlashServices


def test_detect_current_platform_variants(monkeypatch):
    import mpflash.flash.services as services

    fake_mpremote = SimpleNamespace(ON_WSL2=True)
    monkeypatch.setitem(__import__("sys").modules, "mpflash.mpremoteboard", fake_mpremote)

    monkeypatch.setattr(services.sys, "platform", "linux")
    assert services._detect_current_platform() == Platform.WSL2

    fake_mpremote.ON_WSL2 = False
    assert services._detect_current_platform() == Platform.LINUX

    monkeypatch.setattr(services.sys, "platform", "win32")
    assert services._detect_current_platform() == Platform.WINDOWS

    monkeypatch.setattr(services.sys, "platform", "darwin")
    assert services._detect_current_platform() == Platform.MACOS

    monkeypatch.setattr(services.sys, "platform", "mystery-os")
    assert services._detect_current_platform() == Platform.LINUX


def test_reenumerate_swallows_errors(monkeypatch):
    services = FlashServices()

    class _MCU:
        def get_mcu_info(self):
            raise RuntimeError("usb glitch")

    mcu = _MCU()
    services.reenumerate(mcu)
