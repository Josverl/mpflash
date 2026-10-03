"""Shared fixtures for backup/restore tests."""

from typing import Any, Callable

import pytest
from backup_helpers import FakeProvider, capability

from mpflash.backup import registry
from mpflash.backup.models import ComponentKind, ProviderCapability
from mpflash.mpremoteboard import MPRemoteBoard


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeProvider]:
    """Replace the provider registry with an empty one and return a registering factory."""
    import mpflash.backup.builtins  # noqa: F401 - register the built-ins before the registry is replaced

    monkeypatch.setattr(registry, "_providers", {})
    monkeypatch.setattr(registry, "_entry_points_loaded", True)

    def add(*capabilities: ProviderCapability, **options: Any) -> FakeProvider:
        provider = FakeProvider(capabilities, **options)
        registry.register(provider)
        return provider

    return add


@pytest.fixture
def full_provider(isolated_registry: Callable[..., FakeProvider]) -> FakeProvider:
    """One provider offering restorable raw flash (covering ROMFS) plus VFS and ROMFS."""
    return isolated_registry(
        capability(ComponentKind.FLASH, covers=(ComponentKind.ROMFS,), exclusions=("eFuses",)),
        capability(ComponentKind.VFS),
        capability(ComponentKind.ROMFS),
    )


@pytest.fixture
def mcu() -> MPRemoteBoard:
    board = MPRemoteBoard("COM9")
    board.connected = True
    board.family = "micropython"
    board.port = "esp32"
    board.board_id = "ESP32_GENERIC"
    board.version = "1.29.0"
    board.cpu = "ESP32"
    board.serial_number = "AAA"
    return board
