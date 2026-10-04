"""Raw flash for the standard, unpartitioned 4 MiB Raspberry Pi Pico 2 layout."""

from __future__ import annotations

import struct
from typing import Any, Sequence

from mpflash.backup.models import ComponentKind, Exactness, ProviderCapability
from mpflash.backup.registry import register
from mpflash.errors import MPFlashError

from .rp2 import COVERS, Repl, ReplFlash, Rp2Device, Rp2FlashProvider

FLASH_SIZE = 4 * 1024 * 1024
FILESYSTEM_SIZE = 3 * 1024 * 1024
UF2_FAMILY_RP2350_ARM_S = 0xE48BFF59
EXCLUSIONS = (
    "Only the Pico 2's external 4 MiB QSPI flash is included; RAM, boot ROM, OTP and keys are excluded.",
    "Only the standard Arm firmware, unpartitioned layout and identity XIP mapping are supported.",
    "Secure boot, restricted BOOTSEL permissions, partition tables and unknown flash geometries are refused.",
    "Erased (all 0xFF) 4 KiB blocks were not transferred; they are stored as erased flash.",
)

# ROM APIs and register layouts are specified by the Pico SDK's bootrom.h, bootrom_constants.h,
# otp.h, qmi.h and bootram.h. FLASH_DEVINFO may default to 16 MiB; it is not a physical size probe.
DEVICE_CODE = r"""
import array, machine, micropython
if getattr(sys.implementation, "_build", "") != "RPI_PICO2" or sys.implementation._mpy >> 10 != 7:
    raise RuntimeError("RP2350 raw flash requires the standard Arm RPI_PICO2 firmware")
@micropython.asm_thumb
def _rom_secure(r0):
    mov(r0, 0)
    data(2, 0xe840, 0xf000)
if not _rom_secure(0) & (1 << 22):
    raise RuntimeError("RP2350 non-secure execution state is not supported")
@micropython.asm_thumb
def _rom_call(r0, r1, r2, r3):
    data(2, 0x4798)
@micropython.asm_thumb
def _rom_lookup(r0, r1, r2):
    data(2, 0x4790)
def _query(code, flags):
    entry = machine.mem16[0x16]
    if not entry & 1 or entry >= 65536:
        raise RuntimeError("Invalid RP2350 ROM lookup entry")
    fn = _rom_lookup(code, 4, entry)
    if not fn & 1 or fn >= 65536:
        raise RuntimeError("RP2350 ROM query is unavailable")
    out = array.array("I", [0, 0, 0, 0])
    rc = _rom_call(out, 4, flags, fn)
    return rc, tuple(out)
def _probe():
    system = _query(0x5347, 14)
    lock = 0x400e080c
    if not machine.mem32[lock]:
        raise RuntimeError("RP2350 ROM SHA lock is busy")
    try:
        partitions = _query(0x5047, 1)
    finally:
        machine.mem32[lock] = 0
    translations = tuple(machine.mem32[0x400d0034 + i * 4] for i in range(4))
    import rp2
    flash = rp2.Flash()
    return system, partitions, translations, uctypes.addressof(flash), _fs()
def _size():
    return 4194304
"""


def validate_probe(probe: Any) -> None:
    """Reject anything other than a fully accessible, unpartitioned Pico 2 layout."""
    try:
        system, partitions, translations, fs_address, fs_size = probe
        system_rc, (system_flags, critical, cpu, devinfo) = system
        partition_rc, (partition_flags, count, permissions, families) = partitions
    except (TypeError, ValueError) as exc:
        raise MPFlashError("The RP2350 returned malformed geometry/security information") from exc
    values = (system_rc, system_flags, critical, cpu, devinfo, partition_rc, partition_flags, count, permissions, families)
    if not all(isinstance(value, int) and 0 <= value <= 0xFFFFFFFF for value in values):
        raise MPFlashError("The RP2350 returned invalid geometry/security values")
    if system_rc != 4 or system_flags != 14 or partition_rc != 4 or partition_flags != 1:
        raise MPFlashError("The RP2350 ROM could not establish flash geometry, security and partition state")
    if critical & 1:
        raise MPFlashError("RP2350 secure boot is enabled; raw flash backup/restore is refused")
    if cpu != 0:
        raise MPFlashError("Only Arm RP2350 firmware is supported")
    if count:
        raise MPFlashError("RP2350 partition tables are not supported for raw flash backup/restore")
    if permissions & 0xFC000000 != 0xFC000000 or families & 0x20000 == 0:
        raise MPFlashError("The RP2350 unpartitioned flash is not fully accessible through the Arm UF2 bootloader")
    cs0_size, cs1_size = (devinfo >> 8) & 15, (devinfo >> 12) & 15
    if not 10 <= cs0_size <= 12 or cs1_size:
        raise MPFlashError("The RP2350 ROM flash window is inconsistent with the Pico 2's single 4 MiB flash")
    if not isinstance(translations, (tuple, list)) or tuple(translations) != tuple(0x04000000 + i * 0x400 for i in range(4)):
        raise MPFlashError("RP2350 translated XIP layouts are not supported")
    if fs_address != 0x10100000 or fs_size != FILESYSTEM_SIZE:
        raise MPFlashError("The RP2350 filesystem does not match the Pico 2's standard 4 MiB flash layout")


class Pico2Flash(ReplFlash):
    """Use confirmed board geometry instead of probing XIP aliases past the physical flash."""

    def __init__(self, repl: Repl):
        super().__init__(repl)
        # Missing assembler mnemonics are encoded as TT r0,r0 (SDK security-state check) and BLX r3/r2.
        repl.exec(DEVICE_CODE)
        validate_probe(repl.eval("_probe()"))


class RP2350FlashProvider(Rp2FlashProvider):
    """Reuse verified RP2 transfers with conservative Pico 2 geometry and security gates."""

    name = "rp2350-flash"
    uf2_family = UF2_FAMILY_RP2350_ARM_S
    exclusions = EXCLUSIONS

    def capabilities(self, mcu: Any) -> Sequence[ProviderCapability]:
        if (
            not getattr(mcu, "connected", False)
            or getattr(mcu, "family", "") != "micropython"
            or getattr(mcu, "port", "") != "rp2"
            or str(getattr(mcu, "cpu", "")).upper() != "RP2350"
            or getattr(mcu, "board_id", "") != "RPI_PICO2"
        ):
            return ()
        return (
            ProviderCapability(
                component=ComponentKind.FLASH,
                can_backup=True,
                can_restore=True,
                exactness=Exactness.EXACT,
                covers=COVERS,
                exclusions=EXCLUSIONS,
            ),
        )

    def _device(self, mcu: Any, repl: Repl) -> Rp2Device:
        return Pico2Flash(repl)

    def _validate_image(self, image: bytes) -> None:
        if len(image) != FLASH_SIZE:
            raise MPFlashError("Only a 4 MiB Pico 2 flash image can be restored")
        marker = struct.pack("<I", 0xFFFFDED3)
        start = image.find(marker)
        arm_image = False
        while start != -1:
            if start % 4 == 0:
                offset = start + 4
                end = min(start + 0x280, len(image))
                while offset + 4 <= end:
                    item = struct.unpack_from("<I", image, offset)[0]
                    kind = item & 255
                    if kind == 0x0A:
                        raise MPFlashError("The RP2350 image contains a partition table; raw restore is refused")
                    if kind == 0x42:
                        if (item >> 16) & 0x773F != 0x1021:
                            raise MPFlashError("Only RP2350 Arm secure-mode executable images are supported")
                        if start < 65536:
                            arm_image = True
                    if kind == 0xFF:
                        break
                    words = (item >> 8) & (65535 if kind & 128 else 255)
                    if not words or offset + words * 4 > end:
                        break
                    offset += words * 4
            start = image.find(marker, start + 4)
        if not arm_image:
            raise MPFlashError("The Pico 2 flash image has no supported Arm executable in its boot window")


register(RP2350FlashProvider())
