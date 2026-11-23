# pragma: no cover
"""Erase the filesystem block device, then reset the board.

Run on the board via ``mpremote run``. It locates the port's block device
(polling the factory each MicroPython port exposes), unmounts every writable
filesystem found via ``vfs.mount()`` (the same enumeration as ``mpremote df``),
erases every block using the extended block-device protocol and finally calls
``machine.reset()``. The board reboots into MicroPython and ``_boot.py``
recreates a fresh, empty filesystem.

Only the filesystem storage region is erased - the firmware itself lives in a
separate flash region and is left untouched. Entering the UF2 bootloader is a
separate step handled by mpflash.
"""

# Extended block-device ioctl opcodes (see py/vfs.h).
_IOCTL_BLOCK_COUNT = 4
_IOCTL_BLOCK_ERASE = 6


def _vfs():
    """Return the module providing ``mount``/``umount`` (``vfs`` or legacy ``os``)."""
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


def _umount(vfs):
    """Unmount writable filesystems so erasing does not fight cached writes."""
    points = [point for fs, point in _list_mounts(vfs) if "Rom" not in str(fs)]
    for point in points + ["/", "/flash"]:
        if not point:
            continue
        try:
            vfs.umount(point)
        except Exception:
            pass


def _erase(bdev):
    """Erase every block of the filesystem region via the ioctl protocol."""
    count = bdev.ioctl(_IOCTL_BLOCK_COUNT, 0)
    for block in range(count):
        bdev.ioctl(_IOCTL_BLOCK_ERASE, block)
        if block % 50 == 0:
            print(f"ERASE: erased {block}/{count} blocks")
    return count


def main():
    bdev = _get_bdev()
    if bdev is None:
        print("ERASE: no filesystem block device found")
        return
    _umount(_vfs())
    try:
        count = _erase(bdev)
    except Exception as exc:
        print("ERASE: failed:", exc)
        return
    print("ERASE: erased", count, "blocks")
    print("ERASE: resetting")

    import machine

    # Reset (not machine.bootloader()) so the board reboots into MicroPython
    # with a fresh filesystem.
    machine.reset()


main()
