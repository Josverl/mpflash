"""Provider registration and plugin discovery."""

from types import SimpleNamespace

import pytest
from backup_helpers import FakeProvider, capability

from mpflash.backup import registry
from mpflash.backup.models import ComponentKind


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(registry, "_providers", {})
    monkeypatch.setattr(registry, "_entry_points_loaded", False)


class NamedProvider(FakeProvider):
    def __init__(self):
        super().__init__([capability(ComponentKind.VFS)], name="from-class")


def test_register_instantiates_classes_and_replaces_by_name():
    first = registry.register(NamedProvider)
    replacement = registry.register(NamedProvider())

    assert isinstance(first, NamedProvider)
    assert registry.get_providers() == [replacement]


def test_register_requires_a_name():
    with pytest.raises(ValueError, match="no 'name'"):
        registry.register(FakeProvider([], name=""))


def test_unregister_removes_provider():
    registry.register(NamedProvider)
    registry.unregister("from-class")
    registry.unregister("never-registered")

    assert registry.get_providers() == []


def test_entry_point_plugins_are_loaded_once_and_broken_ones_are_ignored(monkeypatch):
    calls = []

    def broken():
        raise ImportError("missing dependency")

    def fake_entry_points(group):
        calls.append(group)
        return [SimpleNamespace(name="good", load=lambda: NamedProvider), SimpleNamespace(name="bad", load=broken)]

    monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)

    assert [provider.name for provider in registry.get_providers()] == ["from-class"]
    registry.get_providers()
    assert calls == [registry.ENTRY_POINT_GROUP]
    assert registry.ENTRY_POINT_GROUP == "mpflash.backup_plugins"
