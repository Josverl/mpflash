# Cross platform shebang:
shebang := if os() == 'windows' {
  'pwsh.exe'
} else {
  '/usr/bin/env pwsh'
}

# Set shell for non-Windows OSs:
set shell := ["pwsh", "-c"]

# Set shell for Windows OSs:
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

default:
  @just --list



# install project in edi mode and install dev dependencies
sync: 
  uv sync --extra dev,test

# run full pytest suite
test: 
  uv run pytest -v

# bump mpflash's version
bump bump="patch":
  uv version --bump {{bump}}

# build
build:
  uv build

publish : build
  uv publish

# delete and regen the lockfile - useful in merge conficts
lock:
  #!{{shebang}}
  del uv.lock -erroraction ignore
  uv lock


[script('python')]
python:
  print('Hello from python!')
  from pathlib import Path
  print(f'Current directory: {Path.cwd()}')


