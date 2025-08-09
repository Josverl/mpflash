# MPFlash Documentation Index

This is the comprehensive documentation for MPFlash, a command-line tool and Python library for downloading and flashing MicroPython firmware to various microcontrollers.

## 📖 Documentation Overview

### User Documentation
- **[README.md](../README.md)** - Quick start guide and basic usage
- **[User Guide](user-guide.md)** - Detailed usage instructions *(to be created)*
- **[Installation Guide](installation.md)** - Installation instructions *(to be created)*

### Developer Documentation
- **[Developer Guide](developer.md)** - Complete development setup and code standards
- **[API Reference](api-reference.md)** - Comprehensive API documentation
- **[Architecture](architecture.md)** - System architecture and design patterns
- **[Contributing](contributing.md)** - How to contribute to the project

### Reference Documentation
- **[Troubleshooting](troubleshooting.md)** - Common issues and solutions
- **[Hardware Support](hardware-support.md)** - Supported boards and platforms *(to be created)*
- **[CLI Reference](cli-reference.md)** - Complete CLI command reference *(to be created)*

### Examples and Tutorials
- **[API Examples](mpflash_api_example.ipynb)** - Jupyter notebook with API usage examples
- **[Advanced Usage](advanced-usage.md)** - Advanced features and use cases *(to be created)*
- **[CI/CD Integration](ci-cd-integration.md)** - Using MPFlash in CI/CD pipelines *(to be created)*

## 🚀 Quick Start

### Installation
```bash
# Install with uv (recommended)
uv tool install mpflash

# Or with pipx
pipx install mpflash

# Or with pip
pip install mpflash
```

### Basic Usage
```bash
# List connected boards
mpflash list

# Download firmware
mpflash download --board ESP32_GENERIC

# Flash firmware
mpflash flash
```

## 📚 Documentation Structure

### For Users
If you're new to MPFlash, start with:
1. [README.md](../README.md) - Overview and basic commands
2. [Installation Guide](installation.md) - Detailed installation
3. [User Guide](user-guide.md) - Complete usage instructions
4. [Troubleshooting](troubleshooting.md) - When things go wrong

### For Developers
If you want to contribute or use MPFlash as a library:
1. [Developer Guide](developer.md) - Development setup
2. [API Reference](api-reference.md) - Programming interface
3. [Architecture](architecture.md) - System design
4. [Contributing](contributing.md) - Contribution guidelines

### For Integrators
If you want to integrate MPFlash into your project:
1. [API Reference](api-reference.md) - Programming interface
2. [API Examples](mpflash_api_example.ipynb) - Code examples
3. [CI/CD Integration](ci-cd-integration.md) - Automation setup

## 🎯 Key Features

### Supported Platforms
- **ESP32/ESP8266** - Via esptool
- **RP2040** - Via UF2 file copy
- **STM32** - Via DFU
- **SAMD** - Via UF2 file copy

### Core Functionality
- **Automatic board detection** - Identifies connected MicroPython boards
- **Firmware download** - Downloads from micropython.org
- **Automated flashing** - Handles bootloader activation
- **Database management** - SQLite database for board/firmware info
- **CLI and API** - Command-line tool and Python library

### Advanced Features
- **Concurrent operations** - Flash multiple boards simultaneously
- **Custom firmware support** - Use your own firmware files
- **Variant selection** - Choose specific board variants
- **Progress reporting** - Real-time operation progress
- **Error recovery** - Robust error handling and recovery

## 📋 Common Tasks

### Board Management
```bash
# List all connected boards
mpflash list

# List specific boards
mpflash list --serial COM3

# Get board info as JSON
mpflash list --json
```

### Firmware Operations
```bash
# Download latest stable firmware
mpflash download

# Download specific version
mpflash download --version v1.25.0

# Download for specific board
mpflash download --board ESP32_GENERIC
```

### Flashing Operations
```bash
# Flash all connected boards
mpflash flash

# Flash specific board
mpflash flash --serial COM3

# Flash with specific firmware
mpflash flash --board ESP32_GENERIC --version stable
```

## 🔧 Configuration

### Environment Variables
- `MPFLASH_FIRMWARE` - Custom firmware storage directory
- `MPFLASH_IGNORE` - Space-separated list of ports to ignore
- `MPFLASH_DATABASE` - Custom database file location

### Configuration Files
- `~/.mpflash/config.toml` - User configuration *(future feature)*
- `board_info.toml` - Per-board configuration

## 📊 Project Status

### Current Version
- **Latest**: v1.25.1
- **Python**: 3.9.2+ required
- **Platforms**: Windows, Linux, macOS

### Hardware Support Status
- ✅ **ESP32/ESP8266** - Full support
- ✅ **RP2040** - Full support  
- ✅ **STM32** - Full support
- ✅ **SAMD** - Full support
- ⏳ **Nordic nRF** - Planned
- ⏳ **CC3200** - Planned
- ⏳ **i.MX RT** - Planned

### Feature Status
- ✅ Board detection and identification
- ✅ Firmware download and caching
- ✅ Automated flashing
- ✅ Database management
- ✅ CLI interface
- ✅ Python API
- ⏳ Web interface - Planned
- ⏳ GUI application - Planned

## 🤝 Community

### Getting Help
- **GitHub Issues** - Bug reports and feature requests
- **Discussions** - Questions and community support
- **Documentation** - Comprehensive guides and references

### Contributing
- **Bug Reports** - Help identify issues
- **Feature Requests** - Suggest improvements
- **Code Contributions** - Submit pull requests
- **Documentation** - Improve or add documentation
- **Testing** - Test with different hardware

### License
MPFlash is licensed under the MIT License. See [LICENSE](../LICENSE) for details.

## 📈 Roadmap

### Short Term (Next Release)
- [ ] Web interface for remote board management
- [ ] Enhanced board variant support
- [ ] Improved error messages and recovery
- [ ] Performance optimizations

### Medium Term (Next 6 Months)
- [ ] GUI application
- [ ] Nordic nRF support
- [ ] Cloud firmware storage
- [ ] Firmware verification and signing

### Long Term (Next Year)
- [ ] Plugin system for custom boards
- [ ] Advanced automation features
- [ ] Multi-user support
- [ ] Enterprise features

## 📝 Release Notes

### v1.25.1 (Current)
- Added support for variant selection
- Improved database performance
- Enhanced error handling
- Better board identification

### v1.25.0
- SQLite database implementation
- Automatic firmware download
- Improved board identification
- Bug fixes and performance improvements

### Earlier Versions
See [CHANGELOG.md](../CHANGELOG.md) for complete release history.

## 🔍 Search Documentation

### By Topic
- **Installation**: [Installation Guide](installation.md)
- **Usage**: [User Guide](user-guide.md), [CLI Reference](cli-reference.md)
- **Development**: [Developer Guide](developer.md), [API Reference](api-reference.md)
- **Troubleshooting**: [Troubleshooting Guide](troubleshooting.md)
- **Hardware**: [Hardware Support](hardware-support.md)

### By Platform
- **ESP32/ESP8266**: [Hardware Support](hardware-support.md#esp32esp8266)
- **RP2040**: [Hardware Support](hardware-support.md#rp2040)
- **STM32**: [Hardware Support](hardware-support.md#stm32)
- **SAMD**: [Hardware Support](hardware-support.md#samd)

### By Use Case
- **CI/CD**: [CI/CD Integration](ci-cd-integration.md)
- **Custom Firmware**: [Advanced Usage](advanced-usage.md)
- **Library Usage**: [API Reference](api-reference.md)
- **Automation**: [API Examples](mpflash_api_example.ipynb)

## 📞 Support

If you need help with MPFlash:

1. **Check the documentation** - Most questions are answered here
2. **Search existing issues** - Someone might have had the same problem
3. **Create a new issue** - Provide detailed information
4. **Join discussions** - Ask questions and share experiences

### Issue Templates
- **Bug Report** - For reporting bugs
- **Feature Request** - For suggesting new features
- **Question** - For asking questions
- **Documentation** - For documentation improvements

---

*This documentation is continuously updated. Last updated: January 2025*
