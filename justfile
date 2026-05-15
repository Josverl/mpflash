
# Set shell for Windows OSs:
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# Show recipes
help:
  @just --list

# install project in edit mode and install dev dependencies
sync: 
  uv sync --extra dev,test,build

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

update:
  uv lock -U

# [script('python')]
# python:
#   print('Hello from python!')
#   from pathlib import Path
#   print(f'Current directory: {Path.cwd()}')


