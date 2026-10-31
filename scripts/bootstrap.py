"""Portable Workers Builds entry point; no credentials are read during build."""

import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version


def run(*args):
    subprocess.run([sys.executable, *args], check=True)


if __name__ == "__main__":
    try:
        installed = version("uv")
    except PackageNotFoundError:
        installed = None
    if installed != "0.13.6":
        run("-m", "pip", "install", "uv==0.13.6")
    run("-m", "uv", "sync", "--locked")
    run("-m", "uv", "run", "python", "scripts/build.py")
