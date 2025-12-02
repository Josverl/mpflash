"""Update all project dependencies to their latest compatible versions.

This script uses uv to update the lock file and sync dependencies.
"""

import subprocess
import sys


def main():
    """Update dependencies and sync the virtual environment."""
    print("Updating dependencies...")
    
    # Update lock file with latest compatible versions
    result = subprocess.run(["uv", "lock", "--upgrade"], check=False)
    
    if result.returncode != 0:
        print("Failed to update lock file", file=sys.stderr)
        sys.exit(1)
    
    print("\nSyncing virtual environment...")
    
    # Sync the virtual environment with updated dependencies
    result = subprocess.run(["uv", "sync"], check=False)
    
    if result.returncode != 0:
        print("Failed to sync dependencies", file=sys.stderr)
        sys.exit(1)
    
    print("\nDependencies updated successfully!")


if __name__ == "__main__":
    main()
