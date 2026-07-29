# pragma: no cover
"""Reformat the filesystem block device, keeping the board on MicroPython.

Run on the board via ``mpremote run``. It discovers the mounted filesystem
using the same ``vfs.mount()`` enumeration as ``mpremote df`` (so the mount
point and filesystem type are detected at runtime, not hardcoded per port),
locates the port's block device, then recreates an empty filesystem of the
same type and remounts it at the same mount point.

Only the filesystem storage region is reformatted - the firmware itself lives
in a separate flash region and is left untouched.
"""


def _vfs():
    """Return the module providing the Vfs* classes (``vfs`` or legacy ``os``)."""
    try:
        import vfs

        return vfs
    except ImportError:
        import os

        return os


# (module, attribute, kwargs): the block-device factory each MicroPython port
# exposes. Instantiated as ``module.attribute(**kwargs)``. Adding a new port is
# a new entry here, not a port-name check elsewhere.
_BDEV_FACTORIES = (
    ("rp2", "Flash", {}),
    ("samd", "Flash", {}),
    ("nrf", "Flash", {}),
    ("mimxrt", "Flash", {}),
    ("alif", "Flash", {}),
    ("pyb", "Flash", {"start": 0}),  # stm32
    ("psoc_edge", "QSPI_Flash", {}),
)


def _get_bdev():
    """Return the internal-flash block device for the running port, or None.

    Polls the known block-device factories in turn; the first that imports and
    instantiates wins. esp32 / esp8266 instead expose a ready-made ``bdev``.
    """
    for mod_name, attr, kwargs in _BDEV_FACTORIES:
        try:
            return getattr(__import__(mod_name), attr)(**kwargs)
        except Exception:
            pass
    try:
        from flashbdev import bdev  # esp32 / esp8266

        return bdev
    except Exception:
        pass
    return None


def _list_mounts(vfs):
    """Return [(fs, mount_point), ...] via ``vfs.mount()`` (like ``mpremote df``)."""
    try:
        return list(vfs.mount())
    except (AttributeError, TypeError):
        return []


def _target_mount(vfs):
    """Return (fs, mount_point) for the writable internal filesystem.

    Uses the runtime mount table, skipping the read-only ROM filesystem and
    removable SD cards. Falls back to probing the usual internal-flash mount
    points when the mount table cannot be enumerated (older firmware).
    """
    for fs, point in _list_mounts(vfs):
        if "Rom" in str(fs) or point.startswith("/sd"):
            continue
        return fs, point
    import os

    for point in ("/", "/flash"):
        try:
            os.statvfs(point)
            return None, point
        except OSError:
            pass
    return None, "/"


def _detect_fs(vfs, bdev):
    """Probe the block device to detect its filesystem class.

    Only Vfs* classes present in this firmware build are considered; some ports
    (for example nrf) are built without ``VfsFat``, so look them up defensively
    to avoid an ``AttributeError``.
    """
    candidates = []
    for name in ("VfsLfs2", "VfsLfs1", "VfsFat"):
        cls = getattr(vfs, name, None)
        if cls is not None:
            candidates.append(cls)
    for cls in candidates:
        try:
            cls(bdev)
            return cls
        except Exception:
            pass
    return candidates[0] if candidates else None


def _fs_class(vfs, fs, bdev):
    """Return the Vfs* class to recreate.

    Prefers the type of the currently mounted filesystem (from its repr, e.g.
    ``<VfsLfs2>``), which is the most reliable signal; if there is no mounted
    filesystem to learn from, probe the block device instead.
    """
    if fs is not None:
        text = str(fs)
        for name in ("VfsLfs2", "VfsLfs1", "VfsFat"):
            if name in text:
                cls = getattr(vfs, name, None)
                if cls is not None:
                    return cls
    return _detect_fs(vfs, bdev)


def main():
    vfs = _vfs()
    bdev = _get_bdev()
    if bdev is None:
        print("FORMAT: no filesystem block device found")
        return
    fs, mount_point = _target_mount(vfs)
    fs_cls = _fs_class(vfs, fs, bdev)
    if fs_cls is None:
        print("FORMAT: no supported filesystem type available")
        return
    for point in (mount_point, "/", "/flash"):
        try:
            vfs.umount(point)
        except Exception:
            pass
    try:
        if fs_cls is getattr(vfs, "VfsLfs2", None):
            fs_cls.mkfs(bdev, progsize=256)
            new_fs = fs_cls(bdev, progsize=256)
        else:
            fs_cls.mkfs(bdev)
            new_fs = fs_cls(bdev)
        vfs.mount(new_fs, mount_point or "/")
    except Exception as exc:
        print("FORMAT: failed:", exc)
        return
    print("FORMAT: done")


main()
