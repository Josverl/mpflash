# pragma: no cover
"""Erase the filesystem block device, then reset the board.

Run on the board via ``mpremote run``. It locates the port's filesystem
``bdev`` (the same one ``_boot.py`` mounts), unmounts it, erases every block
using the extended block-device protocol and finally calls ``machine.reset()``.
The board reboots into MicroPython and ``_boot.py`` recreates a fresh, empty
filesystem.

Only the filesystem storage region is erased - the firmware itself lives in a
separate flash region and is left untouched. Entering the UF2 bootloader is a
separate step handled by mpflash.
"""

# Extended block-device ioctl opcodes (see py/vfs.h).
_IOCTL_BLOCK_COUNT = 4
_IOCTL_BLOCK_ERASE = 6


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
    return None, None


def _umount(mount_point):
    """Unmount the filesystem so erasing does not fight cached writes."""
    try:
        import vfs

        umount = vfs.umount
    except Exception:
        import os

        umount = os.umount
    for point in (mount_point, "/", "/flash"):
        if not point:
            continue
        try:
            umount(point)
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
    bdev, mount_point = _get_bdev()
    if bdev is None:
        print("ERASE: no filesystem block device found")
        return
    _umount(mount_point)
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
