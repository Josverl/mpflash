# Logger Fix for Angle Bracket Issues

## Problem

When using MPFlash's logger with external packages like `micropython-stubber`, logging errors occurred when messages contained angle bracket notation like `<board_default>`. The error was:

```
ValueError: Tag "<board_default>" does not correspond to any known color directive
```

This happened because Loguru's colorizer was interpreting angle brackets as color tags.

## Solution

The MPFlash logger has been updated with three key fixes:

### 1. Message Sanitization

The `_log_formatter` function now escapes angle brackets to prevent them from being interpreted as color tags:

```python
def _sanitize_message(message: str) -> str:
    """Sanitize log messages to prevent Loguru colorization issues."""
    return message.replace("<", "\\<").replace(">", "\\>")
```

### 2. Safe Logger Configuration

A `configure_safe_logging()` function provides a completely safe logging setup with no colorization:

```python
from mpflash.logger import configure_safe_logging
configure_safe_logging()
```

## Usage

```

### For other external packages:

If you encounter similar logging errors with other packages, use one of these approaches:

**Option 1: Safe configuration**
```python
from mpflash.logger import configure_safe_logging
configure_safe_logging()
```

## Verification

The fixes have been tested with all problematic message types:
- Messages with `<board_default>` placeholders
- Messages with curly braces `{}`
- Mixed messages with both angle and curly brackets
- Complex nested cases

All logging configurations now handle these cases without errors.
