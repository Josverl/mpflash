
# Set shell for Windows OSs:
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# Show recipes
help:
  @just --list

# install project in edi mode and install dev dependencies
sync: 
  uv sync --extra dev,test,pyocd

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

# publish the project to PyPI
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

hil_pico2:
    uv run pytest -m hw_uf2 tests/hw -v


# [script('python')]
# python:
#   print('Hello from python!')
#   from pathlib import Path
#   print(f'Current directory: {Path.cwd()}')


