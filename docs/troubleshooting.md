# MPFlash Troubleshooting Guide

## Common Issues and Solutions

### Board Detection Issues

#### Problem: No boards detected
```bash
$ mpflash list
No boards found
```

**Possible Causes & Solutions:**

1. **USB Permission Issues (Linux/macOS)**
   ```bash
   # Add user to dialout group (Linux)
   sudo usermod -a -G dialout $USER
   
   # Log out and log back in, or use:
   newgrp dialout
   
   # Check permissions
   ls -la /dev/ttyUSB*
   ls -la /dev/ttyACM*
   ```

2. **Driver Issues (Windows)**
   - Install appropriate USB drivers for your board
   - Check Device Manager for unknown devices
   - Try different USB cables
   - Test different USB ports

3. **Board not in MicroPython mode**
   - Ensure MicroPython is flashed on the board
   - Check if board is in bootloader mode
   - Reset the board and try again

4. **Serial port conflicts**
   ```bash
   # Check what processes are using serial ports
   lsof /dev/ttyUSB*
   lsof /dev/ttyACM*
   
   # Kill conflicting processes
   sudo pkill -f "process_name"
   ```

#### Problem: Board detected but identification fails
```bash
$ mpflash list
Serial  │ Family  │ Port │ Board │ CPU │ Version │ Build
COM3    │ unknown │      │       │     │         │
```

**Solutions:**

1. **Check MicroPython REPL**
   ```bash
   # Connect manually to check REPL
   python -m serial.tools.miniterm COM3 115200
   
   # At REPL prompt, try:
   import sys
   print(sys.implementation)
   ```

2. **Increase timeout**
   ```bash
   mpflash list --timeout 20
   ```

3. **Enable debug logging**
   ```bash
   mpflash -vv list
   ```

### Download Issues

#### Problem: Firmware download fails
```bash
$ mpflash download --board ESP32_GENERIC
Error: Failed to download firmware
```

**Solutions:**

1. **Network connectivity**
   ```bash
   # Test connection to micropython.org
   ping micropython.org
   
   # Check if behind corporate firewall
   curl -I https://micropython.org/download/
   ```

2. **Check available firmwares**
   ```bash
   # List available versions
   mpflash download --version ?
   
   # Try different version
   mpflash download --version stable --board ESP32_GENERIC
   ```

3. **Custom firmware directory**
   ```bash
   # Set custom download location
   export MPFLASH_FIRMWARE=/path/to/firmware
   mpflash download --board ESP32_GENERIC
   ```

4. **Clear cache and retry**
   ```bash
   # Clear download cache
   rm -rf ~/.cache/mpflash
   mpflash download --board ESP32_GENERIC
   ```

#### Problem: Specific board not found
```bash
$ mpflash download --board MY_BOARD
Error: Board MY_BOARD not found
```

**Solutions:**

1. **List available boards**
   ```bash
   # Search for similar boards
   mpflash download --board ?
   
   # Check database for board variants
   mpflash list --json | jq '.[] | select(.board_id | contains("MY"))'
   ```

2. **Use board variant**
   ```bash
   # Try with variant
   mpflash download --board MY_BOARD --variant FLASH_4M
   ```

3. **Check board ID format**
   ```bash
   # Board IDs are usually uppercase with underscores
   mpflash download --board ESP32_GENERIC_S3
   ```

### Flashing Issues

#### Problem: Flash operation fails
```bash
$ mpflash flash
Error: Flash operation failed for board on COM3
```

**Solutions:**

1. **Check bootloader activation**
   ```bash
   # Try different bootloader methods
   mpflash flash --bootloader manual
   mpflash flash --bootloader touch1200
   mpflash flash --bootloader mpy
   ```

2. **Manual bootloader activation**
   - **ESP32/ESP8266**: Hold BOOT button while pressing RESET
   - **RP2040**: Hold BOOTSEL button while connecting USB
   - **STM32**: Hold BOOT0 button while pressing RESET

3. **Check firmware compatibility**
   ```bash
   # Verify board and firmware match
   mpflash list  # Check current board
   mpflash download --board DETECTED_BOARD_ID
   ```

4. **Platform-specific issues**

   **ESP32/ESP8266:**
   ```bash
   # Install/update esptool
   pip install --upgrade esptool
   
   # Try different baud rates
   mpflash flash --baud 115200
   
   # Check chip detection
   esptool.py --port COM3 chip_id
   ```

   **RP2040:**
   ```bash
   # Check if drive appears in bootloader mode
   ls /mnt  # Linux
   ls /Volumes  # macOS
   # Check for RPI-RP2 drive
   ```

   **STM32:**
   ```bash
   # Check DFU mode
   dfu-util -l
   
   # Try different DFU tool
   pip install --upgrade pydfu
   ```

#### Problem: Bootloader activation fails
```bash
$ mpflash flash
Error: Failed to enter bootloader mode
```

**Solutions:**

1. **Hardware reset**
   - Manually reset the board
   - Check reset button functionality
   - Try different USB cable

2. **Check board documentation**
   - Verify correct bootloader activation sequence
   - Check if board has special requirements

3. **Try different methods**
   ```bash
   # Try automatic detection
   mpflash flash --bootloader auto
   
   # Force manual mode
   mpflash flash --bootloader manual
   ```

### Database Issues

#### Problem: Database corruption
```bash
$ mpflash list
Error: Database error - unable to read board information
```

**Solutions:**

1. **Reset database**
   ```bash
   # Remove database file
   rm ~/.mpflash/mpflash.db
   
   # Reinitialize
   mpflash list
   ```

2. **Check database permissions**
   ```bash
   # Check permissions
   ls -la ~/.mpflash/
   
   # Fix permissions
   chmod 644 ~/.mpflash/mpflash.db
   ```

3. **Use custom database location**
   ```bash
   # Set custom database path
   export MPFLASH_DATABASE=/path/to/custom.db
   mpflash list
   ```

### Performance Issues

#### Problem: Slow board detection
```bash
$ mpflash list
# Takes very long time...
```

**Solutions:**

1. **Limit serial ports**
   ```bash
   # Only check specific ports
   mpflash list --serial COM3 --serial COM4
   
   # Ignore slow ports
   mpflash list --ignore COM1 --ignore COM2
   ```

2. **Reduce timeout**
   ```bash
   mpflash list --timeout 5
   ```

3. **Exclude Bluetooth ports**
   ```bash
   mpflash list --no-bluetooth
   ```

#### Problem: Large firmware downloads
```bash
$ mpflash download
# Download is very slow...
```

**Solutions:**

1. **Use local mirror**
   ```bash
   # Set custom download URL
   export MPFLASH_DOWNLOAD_URL="https://local-mirror.com/micropython/"
   ```

2. **Parallel downloads**
   ```bash
   # Download specific boards only
   mpflash download --board ESP32_GENERIC --board RPI_PICO
   ```

## Platform-Specific Issues

### Windows

#### Problem: "Access is denied" errors
```bash
$ mpflash flash
Error: Access is denied to COM3
```

**Solutions:**

1. **Close other applications**
   - Close Arduino IDE, PuTTY, or other serial applications
   - Check Task Manager for hidden processes

2. **Run as administrator**
   ```cmd
   # Run command prompt as administrator
   mpflash flash
   ```

3. **Check antivirus**
   - Temporarily disable antivirus
   - Add mpflash to antivirus exceptions

#### Problem: USB driver issues
**Solutions:**

1. **Install correct drivers**
   - ESP32: CP210x or CH340 drivers
   - RP2040: Usually works with built-in drivers
   - STM32: ST-Link drivers

2. **Use Device Manager**
   - Check for unknown devices
   - Update or reinstall drivers

### Linux

#### Problem: Permission denied on serial ports
```bash
$ mpflash list
Permission denied: '/dev/ttyUSB0'
```

**Solutions:**

1. **Add user to dialout group**
   ```bash
   sudo usermod -a -G dialout $USER
   sudo usermod -a -G tty $USER
   newgrp dialout
   ```

2. **Set udev rules**
   ```bash
   # Create udev rule file
   sudo nano /etc/udev/rules.d/99-mpflash.rules
   
   # Add content:
   SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", MODE="0666"
   SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666"
   
   # Reload udev rules
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

3. **Check SELinux/AppArmor**
   ```bash
   # Check SELinux status
   sestatus
   
   # Temporarily disable SELinux
   sudo setenforce 0
   ```

### macOS

#### Problem: Serial port not found
```bash
$ mpflash list
No serial ports found
```

**Solutions:**

1. **Install drivers**
   ```bash
   # Install CH340 driver for some boards
   brew install homebrew/cask/ch340-driver
   
   # Or download from manufacturer
   ```

2. **Check USB devices**
   ```bash
   system_profiler SPUSBDataType
   ls /dev/cu.*
   ls /dev/tty.*
   ```

3. **Grant permissions**
   - System Preferences → Security & Privacy → Privacy
   - Add Terminal/mpflash to "Developer Tools"

## Debugging Techniques

### Enable Debug Logging

```bash
# Basic verbose mode
mpflash -v list

# Maximum verbosity
mpflash -vv flash

# Specific component debugging
MPFLASH_LOG_LEVEL=DEBUG mpflash list
```

### Check System Information

```bash
# Python version and dependencies
python --version
pip show mpflash

# System information
uname -a  # Linux/macOS
systeminfo  # Windows

# USB devices
lsusb  # Linux
system_profiler SPUSBDataType  # macOS
```

### Test Serial Connection

```bash
# Test serial connection manually
python -c "
import serial
import time
ser = serial.Serial('COM3', 115200, timeout=1)
time.sleep(2)
ser.write(b'\\r\\n')
response = ser.read(100)
print(f'Response: {response}')
ser.close()
"
```

### Verify Firmware Files

```bash
# Check firmware file integrity
ls -la ~/.mpflash/firmware/
file ~/.mpflash/firmware/esp32/ESP32_GENERIC-v1.25.0.bin

# Verify download
curl -I https://micropython.org/download/ESP32_GENERIC/ESP32_GENERIC-v1.25.0.bin
```

## Advanced Troubleshooting

### Custom Board Support

If you have a custom board not recognized by MPFlash:

1. **Create board_info.toml**
   ```toml
   # In board's root directory
   [board]
   description = "My Custom Board"
   board_id = "CUSTOM_BOARD"
   mcu = "ESP32"
   port = "esp32"
   
   [mpflash]
   firmware_url = "https://example.com/firmware.bin"
   ```

2. **Manual board addition**
   ```python
   # Add to database manually
   from mpflash.db.core import get_database_session
   from mpflash.db.models import Board
   
   with get_database_session() as session:
       board = Board(
           board_id="CUSTOM_BOARD",
           version="v1.25.0",
           board_name="My Custom Board",
           mcu="ESP32",
           port="esp32",
           path="custom",
           description="Custom board description"
       )
       session.add(board)
       session.commit()
   ```

### Network Issues

For corporate networks or firewalls:

1. **Configure proxy**
   ```bash
   export HTTP_PROXY=http://proxy.company.com:8080
   export HTTPS_PROXY=https://proxy.company.com:8080
   mpflash download
   ```

2. **Use alternative download sources**
   ```bash
   # Use GitHub releases instead
   export MPFLASH_USE_GITHUB=1
   mpflash download
   ```

### Recovery Procedures

#### Corrupted Firmware
```bash
# For ESP32/ESP8266 - erase flash completely
esptool.py --port COM3 erase_flash

# For RP2040 - use recovery mode
# Hold BOOTSEL while connecting, then copy firmware
```

#### Bricked Board
```bash
# ESP32 - try different flash modes
esptool.py --port COM3 --baud 115200 write_flash --flash_mode dio --flash_size detect 0x0 firmware.bin

# STM32 - use DFU recovery
dfu-util -a 0 -D firmware.dfu
```

## Getting Help

### Before Asking for Help

1. **Check logs**
   ```bash
   mpflash -vv [command] > mpflash.log 2>&1
   ```

2. **Gather system information**
   ```bash
   # Create debug report
   mpflash --version
   python --version
   pip list | grep -E "(mpflash|serial|esptool)"
   ```

3. **Test with minimal setup**
   ```bash
   # Test with single board
   mpflash list --serial COM3
   ```

### Where to Get Help

1. **GitHub Issues**: https://github.com/Josverl/mpflash/issues
2. **Documentation**: https://github.com/Josverl/mpflash/blob/main/README.md
3. **MicroPython Forum**: https://forum.micropython.org/

### When Reporting Issues

Include:
- Operating system and version
- Python version
- MPFlash version
- Complete error message
- Debug logs (with `-vv` flag)
- Steps to reproduce
- Hardware information (board type, USB cable, etc.)

## Prevention

### Best Practices

1. **Regular updates**
   ```bash
   pip install --upgrade mpflash
   ```

2. **Use virtual environments**
   ```bash
   python -m venv mpflash-env
   source mpflash-env/bin/activate
   pip install mpflash
   ```

3. **Keep drivers updated**
   - Update USB drivers regularly
   - Check board manufacturer websites

4. **Backup configurations**
   ```bash
   # Backup firmware directory
   cp -r ~/.mpflash/firmware ~/backup/
   
   # Backup database
   cp ~/.mpflash/mpflash.db ~/backup/
   ```

This troubleshooting guide should help resolve most common issues with MPFlash. If you encounter problems not covered here, please refer to the project's GitHub issues or create a new issue with detailed information.
