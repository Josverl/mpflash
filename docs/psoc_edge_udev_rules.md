## Linux permissions for Infineon KitProg3 (PSOC Edge)

Flashing a PSOC Edge board with the `openocd` method opens the on-board KitProg3 USB probe (`04b4:f155`).
Without permission on that USB device node, only root can do that.

mpflash detects this case. On an interactive Linux terminal it asks before installing the rule with `sudo`,
and then retries once. It never installs anything without your confirmation (`--yes` does not skip it).

Ready-to-use rule file in this repository:

- `mpflash/udev_rules/65-mpflash-infineon-kitprog3.rules`

### Install (copy/paste)

```bash
sudo cp mpflash/udev_rules/65-mpflash-infineon-kitprog3.rules /etc/udev/rules.d/65-mpflash-infineon-kitprog3.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=04b4 --action=add
```

Then unplug/replug the board.

### Rule contents

```udev
# mpflash Infineon KitProg3 access rule
# Grants non-root users access to the KitProg3 debug probe on Infineon kits
# (PSOC Edge, PSOC 6), which OpenOCD opens over USB.
# Device IDs and names as listed in 50-cmsis-dap.rules (from pyOCD):
#   04b4:f154 KitProg3 CMSIS-DAPv1 HID + I2C/SPI/UART
#   04b4:f155 KitProg3 CMSIS-DAPv2 Bulk + I2C/SPI/UART
#   04b4:f166 KitProg3 CMSIS-DAPv2 Bulk + 2xUART
SUBSYSTEM=="usb|hidraw", ATTRS{idVendor}=="04b4", ATTRS{idProduct}=="f154", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb|hidraw", ATTRS{idVendor}=="04b4", ATTRS{idProduct}=="f155", MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb|hidraw", ATTRS{idVendor}=="04b4", ATTRS{idProduct}=="f166", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

### Verify

```bash
lsusb -d 04b4:f155
groups
```

Access is granted to the `plugdev` group and, through `uaccess`, to the user of the active desktop session.
If your user is not in `plugdev` (for example on a headless machine or WSL), add it and log out/in once:

```bash
sudo usermod -aG plugdev "$USER"
```
