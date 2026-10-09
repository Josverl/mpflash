
# Set shell for Windows OSs:
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# Show recipes
help:
  @just --list

# install workspace projects in editable mode and install test dependencies
sync: 
  uv sync --extra test --extra pyocd

init:
  @just sync

# run the MPFlash and standalone mpremoteboard test suites
test: test-all

# run all workspace tests without publishing either package
test-all:
  uv run --extra test --extra pyocd pytest tests packages/mpremoteboard/tests

# run only the MPFlash test suite against the local workspace package
test-mpflash:
  uv run --extra test --extra pyocd pytest tests

# run standalone package tests in an isolated environment
test-mpremoteboard:
  uv run --isolated --package mpremoteboard --with pytest pytest -c packages/mpremoteboard/pyproject.toml packages/mpremoteboard/tests

# create coverage report, build html report
coverage:
  uv run pytest --cov --cov-report=term-missing
  coverage html
  start coverage/index.html

# Build a new board databases update from the specified MicroPython repository
gather-boards mpy="../micropython-stubs/repos/micropython": 
  uv run python mpflash\db\gather_boards.py --mpy-path {{mpy}}

# bump mpflash's version [major, minor, patch, stable, alpha, beta, rc, post, dev]
bump bump="patch":
  uv version --bump {{bump}}

# build both workspace distributions into separate directories
build: build-all

# build both publishable packages locally
build-all: build-mpremoteboard build-mpflash

# build only MPFlash, validating its published dependency metadata
build-mpflash:
  uv run --isolated --no-project python -c "import shutil; shutil.rmtree('dist/mpflash', ignore_errors=True)"
  uv build --package mpflash --no-sources --out-dir dist/mpflash

# build only the standalone board package
build-mpremoteboard:
  uv run --isolated --no-project python -c "import shutil; shutil.rmtree('dist/mpremoteboard', ignore_errors=True)"
  uv build --package mpremoteboard --no-sources --out-dir dist/mpremoteboard

# smoke-test both local wheels without publishing them
check-packages: build-all
  uv run --isolated --no-project python -c "import glob, subprocess; wheel = glob.glob('dist/mpremoteboard/mpremoteboard-*.whl')[0]; result = subprocess.run(['uv', 'run', '--isolated', '--no-project', '--with', wheel, 'python', '-c', 'from importlib.metadata import distribution; import mpremoteboard; print(distribution(mpremoteboard.__name__).version)'], check=True, capture_output=True, text=True); print(f'Verified mpremoteboard {result.stdout.strip()} wheel import')"
  uv run --isolated --no-project python -c "import glob, subprocess; wheel = glob.glob('dist/mpflash/mpflash-*.whl')[0]; result = subprocess.run(['uv', 'run', '--isolated', '--no-project', '--find-links', 'dist/mpremoteboard', '--with', wheel, 'mpflash', '--version'], check=True, capture_output=True, text=True); print(f'Verified {result.stdout.strip()} using local mpremoteboard wheel')"

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
  just test
  uv version --bump {{bump}}
  git add pyproject.toml uv.lock
  git commit -m "Release v$(uv version --short)"
  git tag -a "v$(uv version --short)" -m "Release v$(uv version --short)"
  git push --follow-tags --force

# manual fallback: publish both packages in dependency order
publish: publish-all

# publish both packages, with the dependency package first
[confirm("Publish both workspace packages to PyPI? Continue?")]
publish-all: build-all
  uv publish "dist/mpremoteboard/*"
  uv publish "dist/mpflash/*"

# publish only MPFlash; its required mpremoteboard version must already exist
[confirm("Publish only mpflash to PyPI? Continue?")]
publish-mpflash: build-mpflash
  uv publish "dist/mpflash/*"

# publish only the standalone board package
[confirm("Publish only mpremoteboard to PyPI? Continue?")]
publish-mpremoteboard: build-mpremoteboard
  uv publish "dist/mpremoteboard/*"

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
