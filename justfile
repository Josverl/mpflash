
# Set shell for Windows OSs:
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# Show recipes
help:
  @just --list

# install project in edi mode and install dev dependencies
sync: 
  uv sync --extra dev,test,pyocd

init:
  @just sync

# run full pytest suite
test: 
  uv run pytest -v

# create coverage report, build html report
coverage:
  uv run pytest --cov --cov-report=term-missing
  coverage html
  start coverage/index.html

# bump mpflash's version [major, minor, patch, stable, alpha, beta, rc, post, dev]
bump bump="patch":
  uv version --bump {{bump}}

# build the project for distribution
build:
  uv build

# -----------------------------------------------------------------------------------------------
# Release process
# Pushing a `v*` tag triggers .github/workflows/release.yml, which builds the sdist + wheel,
# publishes to PyPI using trusted publishing (OIDC, no token) and creates a GitHub release
# with auto-generated notes. Use `just release` to cut a release; do not publish manually.
# -----------------------------------------------------------------------------------------------

# run tests, bump the version, then commit, tag and push - triggering the PyPI release
# bump = major | minor | patch (default) | stable | alpha | beta | rc | post | dev
[confirm("Run tests, bump the version and push a new tag? This triggers a PyPI release. Continue?")]
release bump="patch":
  uv run pytest
  uv version --bump {{bump}}
  git add pyproject.toml uv.lock
  git commit -m "Release v$(uv version --short)"
  git tag -a "v$(uv version --short)" -m "Release v$(uv version --short)"
  git push --follow-tags

# manual fallback: publish to PyPI directly (normally handled by GitHub Actions on tag push)
[confirm("Are you sure you want to publish to PyPI directly? This is normally handled by GitHub Actions on tag push. Continue?")]
publish : build
  uv publish

# delete and regen the lockfile - useful in merge conficts
lock:
  del uv.lock -erroraction ignore
  uv lock

# -----------------------------------------------------------------------------------------------
# HIL testing 
# Configure environment for the port and firmware selection in the .env file, then run the test suite 
# -----------------------------------------------------------------------------------------------
# export LOGURU_LEVEL := "TRACE"
export LOGURU_LEVEL := "INFO"

hil_uf2_pico2:
    uv run pytest -m hw_uf2 tests/hw -v

hil_dfu_pybv11:
    uv run pytest -m hw_dfu tests/hw -v

hil_pyocd_pybv11:
  uv run pytest -m hw_pyocd tests/hw -v

hil_esptool_esp32:
  uv run pytest -m hw_esptool tests/hw -v

# [script('python')]
# python:
#   print('Hello from python!')
#   from pathlib import Path
#   print(f'Current directory: {Path.cwd()}')


