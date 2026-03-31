# CLI Startup Speed

This document describes how to measure and visualise `mpflash` startup time,
and records the improvements made to reduce it.

---

## Measuring tools

### 1 — Wall-clock time (PowerShell)

Quick sanity check:

```powershell
# Single run
Measure-Command { mpflash --help } | Select-Object TotalMilliseconds

# Average over 5 runs
1..5 | ForEach-Object { (Measure-Command { mpflash --help }).TotalMilliseconds } | Measure-Object -Average -Minimum -Maximum | Format-List
```

### 2 — Import flame graph with `tuna`

`tuna` reads Python's built-in `-X importtime` output and renders an interactive
flame graph in the browser at `http://localhost:8000`.

```powershell
# Install (once)
uv pip install tuna

# --- mpflash startup (--help path, imports only) ---
python -X importtime -c "import mpflash.cli_main" 2> import_time.log
python -m tuna import_time.log

# --- mpflash --help (full CLI resolution) ---
python -X importtime -c "import sys; sys.argv=['mpflash','--help']; from mpflash.cli_main import mpflash; mpflash()" 2> help.log
python -m tuna help.log

# --- specific command: list ---
python -X importtime -c "import sys; sys.argv=['mpflash','list','--no-progress']; from mpflash.cli_main import mpflash; mpflash()" 2> list.log
python -m tuna list.log

# --- specific command: download --help ---
python -X importtime -c "import sys; sys.argv=['mpflash','download','--help']; from mpflash.cli_main import mpflash; mpflash()" 2> download.log
python -m tuna download.log

# --- specific command: flash --help ---
python -X importtime -c "import sys; sys.argv=['mpflash','flash','--help']; from mpflash.cli_main import mpflash; mpflash()" 2> flash.log
python -m tuna flash.log
```

> **Tip:** compare `help.log` (startup only) with `list.log` (full list run)
> to see exactly which modules are deferred by the lazy-import changes.

### 3 — Call-tree profiler with `pyinstrument`

`pyinstrument` is a statistical profiler that shows wall-clock time with a
readable call tree.  Unlike `tuna` it includes *runtime* cost, not just imports.

```powershell
# Install (once)
uv pip install pyinstrument

# Profile --help (text output to terminal)
python -m pyinstrument -c "from mpflash.cli_main import mpflash; mpflash()" -- --help

# Profile the list command (no connected boards expected)
python -m pyinstrument -c "from mpflash.cli_main import mpflash; mpflash()" -- list --no-progress

# Save as HTML report (auto-opens in browser)
python -m pyinstrument -r html -o profile_help.html -c "from mpflash.cli_main import mpflash; mpflash()" -- --help

# Save list command profile as HTML
python -m pyinstrument -r html -o profile_list.html -c "from mpflash.cli_main import mpflash; mpflash()" -- list --no-progress
```

### 4 — Sorted importtime table (no extra tools)

```powershell
python -X importtime -c "import mpflash.cli_main" 2>&1 `
  | Select-String "import time" `
  | ForEach-Object { $_ -replace "import time:\s+", "" } `
  | ForEach-Object {
      $p = $_ -split "\s*\|\s*"
      if ($p.Length -ge 3) {
          [PSCustomObject]@{
              self_us    = [int]$p[0].Trim()
              cumulative = [int]$p[1].Trim()
              package    = $p[2].Trim()
          }
      }
    } `
  | Sort-Object cumulative -Descending `
  | Select-Object -First 30 `
  | Format-Table
```

---

## Measurements

### Before optimisation

| Metric | Value |
|--------|-------|
| `python -X importtime` cumulative | 833 ms |
| `pyinstrument` duration (`--help`) | 0.668 s |
| `Measure-Command` wall clock (`--help`) | 771 ms |

Top import costs before:

| Module | Cumulative |
|--------|-----------|
| `mpremote.mip` (via `custom/__init__`) | ~94 ms |
| `esptool` (via `flash/__init__`) | ~52 ms |
| `psutil` (via `flash/uf2/windows`) | ~20 ms |
| `unittest.mock` (via `runner.py`) | ~18 ms |
| `mpremoteboard` + `tenacity` (via `connected`) | ~65 ms |
| `mpboard_id` + `peewee` (via `ask_input`) | ~62 ms |

### After optimisation

| Metric | Value | Change |
|--------|-------|--------|
| `python -X importtime` cumulative | 467 ms | **-44 %** |
| `pyinstrument` duration (`--help`) | 0.406 s | **-39 %** |
| `Measure-Command` wall clock (`--help`) | ~660 ms | **-14 %** |

> The ~200 ms gap between import time (-44 %) and wall-clock (-14 %) is
> unavoidable Python process startup overhead (interpreter, site-packages, venv).

### Remaining unavoidable startup cost

| Module | Cost | Reason |
|--------|------|--------|
| `loguru` | ~160 ms | needed for logging; pulls asyncio + ssl |
| `rich.console` | ~100 ms | needed by rich-click group |
| `click` / `rich-click` | ~85 ms | needed for CLI group definition |
| `peewee` + `db.core` | ~38 ms | `migrate_database()` called on every run |

---

## Changes made

All optimisations use the **"move heavy imports inside the command callback"**
pattern — no new runtime dependencies, no AST rewriting, fully backwards
compatible.

| File | Change | Approx saving |
|------|--------|---------------|
| `mpflash/mpremoteboard/runner.py` | Replace `from unittest.mock import DEFAULT` with `DEFAULT = object()` | ~18 ms |
| `mpflash/custom/__init__.py` | Remove unused `from mpremote.mip import _rewrite_url` | ~94 ms |
| `mpflash/flash/__init__.py` | Move `flash_esp`, `flash_stm32`, `flash_uf2` imports inside `flash_mcu()` | ~72 ms |
| `mpflash/cli_add.py` | Move `add_custom_firmware` import inside callback | latent |
| `mpflash/cli_download.py` | Move `connected`, `downloaded`, `mpboard_id`, `download`, `ask_input` inside callback | ~82 ms |
| `mpflash/cli_flash.py` | Move `jid`, `flash_tasks`, `worklist`, `mpremoteboard`, `mpboard_id` inside callback | ~75 ms |
| `mpflash/cli_list.py` | Move `list_mcus`, `show_mcus` imports inside callback | ~65 ms |

---

## Guidelines for keeping startup fast

1. **Command-specific imports** (`esptool`, `mpremote`, `tenacity`, `psutil`, …)
   belong *inside* the Click callback function, **not** at module top level.
2. **Framework imports** (`click`, `loguru`, `rich`) stay at module level —
   they are always needed and deferring them adds complexity without benefit.
3. Re-measure with `python -X importtime` whenever a new heavy dependency is
   added to a CLI module.
