"""Build and publish the package to PyPI using uv.

This script builds the package as a wheel and uploads it to PyPI using the uv tool.
It retrieves the PyPI token securely from the system keyring.
"""

import subprocess

import keyring

# Get the token from the keyring
pypi_token = keyring.get_password("pypi", "uv_publish")

if not pypi_token:
    raise ValueError("PyPI token not found in keyring. Please add it using keyring.set_password('pypi', 'uv_publish', '<your_token>')")

# uv build --wheel
subprocess.run(["uv", "build", "--wheel"])


subprocess.run(
    [
        "uv",
        "publish",
        "--username",
        "__token__",
        "--password",
        pypi_token,
    ]
)
