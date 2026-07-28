# pragma: no cover
"""Reformat the filesystem block device, keeping the board on MicroPython.

Run on the board via ``mpremote run``. It locates the port's filesystem
``bdev`` (the same one ``_boot.py`` mounts), detects the current filesystem
type (``VfsLfs2`` or ``VfsFat``) and recreates an empty filesystem of that
type, then remounts it.

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


def _get_bdev():
    """Return (bdev, mount_point) for the running port, or (None, None)."""
    try:
        import rp2

        return rp2.Flash(), "/"
    except Exception:
        pass
    try:
        import samd

        return samd.Flash(), "/"
    except Exception:
        pass
    try:
        import nrf

        return nrf.Flash(), "/flash"
    except Exception:
        pass
    try:
        from flashbdev import bdev  # esp32 / esp8266

        return bdev, "/"
    except Exception:
        pass
    try:
        import pyb  # stm32

        return pyb.Flash(start=0), "/"
    except Exception:
        pass
    return None, None


def _detect_fs(vfs, bdev):
    """Detect the current filesystem class, defaulting to the first available.

    Only Vfs* classes present in this firmware build are considered; some ports
    (for example nrf) are built without ``VfsFat``, so look them up defensively
    to avoid an ``AttributeError``.
    """
    candidates = []
    for name in ("VfsLfs2", "VfsFat"):
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


def main():
    vfs = _vfs()
    bdev, mount_point = _get_bdev()
    if bdev is None:
        print("FORMAT: no filesystem block device found")
        return
    fs_cls = _detect_fs(vfs, bdev)
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
            fs = fs_cls(bdev, progsize=256)
        else:
            fs_cls.mkfs(bdev)
            fs = fs_cls(bdev)
        vfs.mount(fs, mount_point or "/")
    except Exception as exc:
        print("FORMAT: failed:", exc)
        return
    print("FORMAT: done")


main()
