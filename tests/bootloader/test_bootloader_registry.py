"""Tests for the pluggable bootloader activator registry."""

from __future__ import annotations

import pytest

from mpflash.bootloader.base import BootloaderActivator
from mpflash.bootloader.registry import (
    get_activator,
    get_activators,
    register,
    resolve_methods,
    unregister,
)

pytestmark = [pytest.mark.mpflash]


def test_builtins_are_registered():
    names = {a.name for a in get_activators()}
    assert {"mpy", "touch1200", "manual"}.issubset(names)


def test_get_activator_returns_instance():
    activator = get_activator("mpy")
    assert activator is not None
    assert activator.name == "mpy"


def test_get_activator_unknown_returns_none():
    assert get_activator("does-not-exist") is None


def test_resolve_methods_none_returns_empty():
    assert resolve_methods("none") == []


def test_resolve_methods_explicit_appends_manual():
    # Asking for touch1200 should still fall back to manual as a last resort.
    assert resolve_methods("touch1200") == ["touch1200", "manual"]


def test_resolve_methods_dedupes_preferred():
    result = resolve_methods("mpy", ["mpy", "touch1200", "manual"])
    assert result == ["mpy", "touch1200", "manual"]


def test_resolve_methods_auto_uses_preferred_order():
    assert resolve_methods("auto", ["touch1200", "mpy", "manual"]) == [
        "touch1200",
        "mpy",
        "manual",
    ]


def test_resolve_methods_auto_default_fallback():
    # Without preferred order, AUTO falls back to a generic ladder.
    assert resolve_methods("auto") == ["mpy", "manual"]


def test_register_plugin_activator_and_unregister():
    class CustomActivator(BootloaderActivator):
        name = "test-plugin"

        def activate(self, mcu, *, timeout: int = 10) -> bool:
            return True

    try:
        register(CustomActivator())
        assert get_activator("test-plugin") is not None
        assert resolve_methods("test-plugin") == ["test-plugin", "manual"]
    finally:
        unregister("test-plugin")
    assert get_activator("test-plugin") is None


def test_register_requires_name():
    class Nameless(BootloaderActivator):
        name = ""

        def activate(self, mcu, *, timeout: int = 10) -> bool:
            return True

    with pytest.raises(ValueError):
        register(Nameless())
