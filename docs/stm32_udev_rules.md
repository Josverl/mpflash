## Linux permissions for USB devices

In order to flash STM32 boards in DFU mode without `sudo`, your user needs
permission on the DFU USB device node.

Ready-to-use rule file in this repository:

- `mpflash/udev_rules/65-mpflash-stm32-dfu.rules`

### Install (copy/paste)

```bash
sudo cp /home/jos/mpflash/mpflash/udev_rules/65-mpflash-stm32-dfu.rules /etc/udev/rules.d/65-mpflash-stm32-dfu.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/replug the STM32 board (or re-enter DFU mode).

### Rule contents

```udev
# mpflash STM32 DFU access rule
# Device: STMicroelectronics STM Device in DFU Mode (0483:df11)
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="df11", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

### Verify

```bash
lsusb | grep -i "0483:df11"
groups
```

If your user is not in `plugdev`, add it and log out/in once:

```bash
sudo usermod -aG plugdev "$USER"
```


## To check

Enter STM32 bootloader mode:
``` bash
mpremote bootloader 
```


List usb devices
```bash
(.venv) jos@jvnuc:~/projects/mpflash$ lsusb -vv -t
/:  Bus 02.Port 1: Dev 1, Class=root_hub, Driver=xhci_hcd/6p, 10000M
    ID 1d6b:0003 Linux Foundation 3.0 root hub
    /sys/bus/usb/devices/usb2  /dev/bus/usb/002/001
/:  Bus 01.Port 1: Dev 1, Class=root_hub, Driver=xhci_hcd/12p, 480M
    ID 1d6b:0002 Linux Foundation 2.0 root hub
    /sys/bus/usb/devices/usb1  /dev/bus/usb/001/001
    |__ Port 1: Dev 2, If 0, Class=Hub, Driver=hub/4p, 12M
        ID 0a05:7211 Unknown Manufacturer hub
        /sys/bus/usb/devices/1-1  /dev/bus/usb/001/002
        |__ Port 1: Dev 4, If 0, Class=Hub, Driver=hub/4p, 12M
            ID 0a05:7211 Unknown Manufacturer hub
            /sys/bus/usb/devices/1-1.1  /dev/bus/usb/001/004
        |__ Port 2: Dev 22, If 0, Class=Application Specific Interface, Driver=, 12M
            ID 0483:df11 STMicroelectronics STM Device in DFU Mode
            /sys/bus/usb/devices/1-1.2  /dev/bus/usb/001/022
    |__ Port 10: Dev 3, If 0, Class=Wireless, Driver=btusb, 12M
        ID 8087:0aaa Intel Corp. Bluetooth 9460/9560 Jefferson Peak (JfP)
        /sys/bus/usb/devices/1-10  /dev/bus/usb/001/003
    |__ Port 10: Dev 3, If 1, Class=Wireless, Driver=btusb, 12M
        ID 8087:0aaa Intel Corp. Bluetooth 9460/9560 Jefferson Peak (JfP)
        /sys/bus/usb/devices/1-10  /dev/bus/usb/001/003
```
Lookup the STM32 device path (`/dev/bus/usb/001/022`), and check if group
`plugdev` is granted access:
```bash
(.venv) jos@jvnuc:~/projects/mpflash$ ll /dev/bus/usb/001/022
crw-rw-r-- 1 root plugdev 189, 21 mrt 11 22:38 /dev/bus/usb/001/022
```

Check `groups` to see if user is in `plugdev`:
```
(.venv) jos@jvnuc:~/projects/mpflash$ groups
jos adm disk dialout cdrom sudo dip plugdev kvm lpadmin lxd sambashare usb
```