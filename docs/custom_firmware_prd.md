# Custom Firmware Support - Product Requirements Document

## Background
MPFlash currently has a basic implementation to add custom firmwares through the `add_firmware.py` module, but it needs refinement and proper testing. The feature aims to allow users to add custom-built MicroPython firmware from various sources.

## Current Implementation Analysis
The existing code in `add_firmware.py` has:
- Support for local files and HTTP(S) URLs
- Basic database integration with firmware versioning
- Simple file copying and downloading mechanisms
- Preliminary support for GitHub URLs (using mpremote's URL rewriting)

## Gaps Identified
1. **Source Validation**
   - No validation of firmware file format/structure
   - Limited source type support (only local files and HTTP)
   - No hash verification for downloaded files
   - No signature verification for security

2. **Metadata Management**
   - Version extraction from firmware is not implemented
   - Limited metadata storage (missing build info, toolchain version, git metadata)
   - No tracking of custom firmware dependencies
   - No git repository tracking (branch, commit, tags)

3. **Testing**
   - No test coverage for custom firmware functionality
   - No validation tests for different board types
   - Missing integration tests with the database

## Requirements

### 1. Source Management
- **Must Have:**
  - Support for local `.bin`, `.uf2`, and `.hex` files
  - Support for HTTPS downloads
  - Basic validation of firmware file format
  - Source URL/path persistence
  - do not attempt to download firmwae files when the --git-path is used

- **Should Have:**
  - GitHub release and branch integration
  - Build metadata extraction

- **Nice to Have:**
  - Integration with CI/CD pipelines
  - Automatic updates for tracked repositories
  - Peer-to-peer sharing capabilities

### 2. Metadata & Storage
- **Must Have:**
  - Firmware version tracking
    - Standard version numbers
    - Git-based versions (tag + commits since tag, e.g. "V1.26.0-preview-48")
  - Git repository metadata
    - Branch name
    - Commit hash
    - Latest relevant tag
  - Board compatibility information
  - Source tracking
  - Creation timestamp
  - Basic description field

- **Should Have:**
  - Build environment information
  - Toolchain version
  - Dependencies list
  - Change history
  - Custom tags support

### 3. Security
- **Must Have:**
  - File integrity verification
  - Source validation
  - Basic access control

- **Should Have:**
  - Signature verification
  - Malware scanning
  - Secure storage of credentials
  - Update authorization

### 4. User Interface
- **Must Have:**
  - CLI commands for adding custom firmware
    - Add with `--flash` option for immediate flashing
    - Support for git repository sources
  - Basic status reporting
  - Error handling with clear messages
  - List/search custom firmwares
  - Direct flashing integration with existing flash methods

- **Should Have:**
  - Interactive firmware selection
  - Detailed firmware information display
  - Update notifications
  - Batch import capabilities

### 5. Testing Requirements
- **Must Have:**
  - Unit tests for all new functionality
  - Integration tests with database
  - Validation tests for supported file formats
  - Cross-platform compatibility tests

- **Should Have:**
  - Error handling tests
  - Performance benchmarks
  - Security testing
  - Network failure handling tests

## Success Metrics
1. **Reliability:**
   - 99% success rate for firmware installations
   - All custom firmwares properly tracked in database

2. **Performance:**
   - Download and installation < 30 seconds
   - Database operations < 100ms
   - Memory usage < 50MB

3. **User Experience:**
   - Clear error messages
   - No user intervention needed for standard operations
   - Automatic recovery from common errors

## Future Considerations
1. **Scalability:**
   - Support for multiple firmware repositories
   - Distributed storage support
   - Caching mechanisms

2. **Integration:**
   - CI/CD pipeline integration
   - Cloud storage support
   - Third-party repository support

3. **Community:**
   - Firmware sharing platform
   - User ratings and reviews
   - Community build sharing

## Implementation Notes
Current implementation in `add_firmware.py` should be refactored to meet these requirements. The module currently provides basic functionality but needs significant enhancement to support all the features outlined in this PRD.

### Git Integration Requirements
1. **Version Detection**
   - Parse git repository information
   - Identify latest relevant tag
   - Calculate commits since tag
   - Generate version string (e.g. "V1.26.0-preview-48")

2. **Repository Tracking**
   - Store repository URL
   - Track active branch
   - Store commit hash
   - Store latest relevant tag
   - Enable firmware updates based on repository changes

3. **Direct Flashing Support**
   - Integrate with `--flash` option
   - Use existing flash methods
   - Validate firmware before flashing
   - Support immediate flash after download
   - Handle flash failures gracefully

### Device Firmware Tracking (mpflash.toml)
The `mpflash.toml` file serves as a record of the installed firmware and should be created or updated after successful flashing. This file helps track the device's firmware state and enables proper firmware management.

1. **Basic Information**
```toml
[firmware]
board_id = "ESP32_GENERIC"
port = "esp32"
version = "v1.21.0"
flash_date = "2025-07-08T14:30:00Z"
description = "Custom build with extended BLE support"
custom = true
```

2. **Source Information**
```toml
[source]
type = "git"  # Options: "git", "local", "http"
url = "https://github.com/user/custom-micropython"
filename = "firmware.bin"
hash = "sha256:abc123..."
```

3. **Git Metadata** (when source.type = "git")
```toml
[source.git]
branch = "feature/ble-extensions"
commit = "a1b2c3d4"
tag = "v1.21.0-preview"
commits_since_tag = 48
```

4. **Build Information**
```toml
[build]
toolchain_version = "esp-idf-v5.1"
python_version = "3.13.0"
build_date = "2025-07-07T23:15:00Z"
build_host = "CI-Runner-123"
```

5. **Custom Metadata**
```toml
[custom]
author = "John Doe"
organization = "MyOrg"
features = ["extended-ble", "custom-modules"]
dependencies = ["my-custom-module>=1.2.0"]
```

The `mpflash.toml` file should be:
- Created automatically after successful flashing
- Updated when firmware is modified
- Used for firmware verification and tracking
- Human-readable and machine-parseable
- Version controlled (optional)
- Located in the device's root directory

### TOML Validation Requirements

1. **Schema Validation**
```python
# Example validation schema
MPFLASH_TOML_SCHEMA = {
    "firmware": {
        "board_id": str,
        "port": str,
        "version": str,
        "flash_date": datetime,
        "description": Optional[str],
        "custom": bool
    },
    "source": {
        "type": Literal["git", "local", "http"],
        "url": Optional[str],
        "filename": str,
        "hash": str
    },
    "source.git": Optional[{
        "branch": str,
        "commit": str,
        "tag": Optional[str],
        "commits_since_tag": Optional[int]
    }],
    "build": Optional[{
        "toolchain_version": str,
        "python_version": str,
        "build_date": datetime,
        "build_host": str
    }],
    "custom": Optional[{
        "author": str,
        "organization": Optional[str],
        "features": List[str],
        "dependencies": List[str]
    }]
}
```

2. **Validation Rules**
   - Required fields must be present and non-empty
   - Dates must be in ISO 8601 format
   - Hash must be in format "algorithm:hash"
   - Version strings must follow semantic versioning
   - Git commit hashes must be valid hex strings
   - URLs must be properly formatted
   - File paths must be valid for the platform

3. **Test Cases**
   - Valid TOML files with all required fields
   - Optional sections present/missing
   - Different source types (git/local/http)
   - Invalid date formats
   - Missing required fields
   - Invalid hash formats
   - Invalid URLs
   - Invalid version strings

### Database Integration

1. **Firmware Table Updates**
   The TOML file should sync with the firmware table in the database:

```sql
ALTER TABLE firmware ADD COLUMN IF NOT EXISTS
    git_branch VARCHAR(255),
    git_commit CHAR(40),
    git_tag VARCHAR(255),
    git_commits_since_tag INTEGER,
    build_toolchain VARCHAR(255),
    build_python_version VARCHAR(20),
    build_date TIMESTAMP,
    build_host VARCHAR(255),
    custom_author VARCHAR(255),
    custom_organization VARCHAR(255),
    custom_features TEXT[],
    custom_dependencies TEXT[]
```

2. **Synchronization Rules**
   - TOML file is the source of truth for device state
   - Database records firmware history and availability
   - On flash:
     1. Update TOML file
     2. Sync to database
     3. Validate both are consistent
   - On database update:
     1. Update device TOML if connected
     2. Queue update for offline devices

3. **Integration Test Requirements**
   - Test database updates from TOML
   - Test TOML generation from database
   - Verify consistency between TOML and database
   - Test conflict resolution
   - Test partial updates
   - Test invalid data handling

4. **Error Handling**
   - Invalid TOML syntax
   - Missing required fields
   - Database connection failures
   - Synchronization conflicts
   - Version mismatches
   - File system errors

5. **Migration Path**
   - Add new columns to database
   - Generate TOML for existing firmware
   - Validate existing records
   - Update CLI tools for new format
   - Provide migration scripts
