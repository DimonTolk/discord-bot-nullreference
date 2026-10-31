"""Vendor the universal Python SDK explicitly and verify the exact upload bundle.

pywrangler's native/Pyodide venv layouts differ across build platforms. Runtime
files must be under python_modules/, regardless of where uv installed tooling.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK_VERSION = "1.9.5"
REQUIRED = (
    "workers/__init__.py",
    "workers/entrypoints.py",
    "workers/fetch.py",
    "workers/response.py",
    "workers/workflows.js",
    "_workers_sdk_patch_loader.pth",
    "_workers_sdk_patch_loader.py",
    "pyvenv.cfg",
)


def verify_vendor(root=ROOT):
    vendor = root / "python_modules"
    missing = [
        name
        for name in REQUIRED
        if not (vendor / name).is_file() or (vendor / name).stat().st_size == 0
    ]
    if missing:
        raise RuntimeError("Worker SDK files missing: " + ", ".join(missing))
    if "from .blob import" not in (vendor / "workers/__init__.py").read_text("utf-8"):
        raise RuntimeError("Expected the external workers-runtime-sdk, not a runtime placeholder")
    return vendor


def prepare():
    if version("workers-runtime-sdk") != SDK_VERSION:
        raise RuntimeError("Unexpected workers-runtime-sdk version; run the locked build")
    # The SDK wheel is pure Python/JS. --target avoids any native/Pyodide venv
    # path inference (including interpreter overrides inherited from uv run).
    # No native dependencies are copied into the Worker.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "uv",
            "pip",
            "install",
            "--target",
            str(ROOT / "python_modules"),
            "--only-binary",
            ":all:",
            "--no-deps",
            "--reinstall",
            f"workers-runtime-sdk=={SDK_VERSION}",
        ],
        check=True,
    )
    (ROOT / "python_modules/pyvenv.cfg").write_text(
        "# Python Workers vendored virtual environment\n", encoding="utf-8"
    )
    vendor = verify_vendor()
    hashes = {}
    for file in vendor.rglob("*"):
        if file.is_file() and (file.suffix in (".py", ".pth", ".js") or file.name == "pyvenv.cfg"):
            if "__pycache__" not in file.parts:
                hashes[file.relative_to(vendor).as_posix()] = hashlib.sha256(
                    file.read_bytes()
                ).hexdigest()
    (ROOT / "dist").mkdir(exist_ok=True)
    (ROOT / "dist/sdk-manifest.json").write_text(json.dumps(hashes, indent=2), "utf-8")
    print(f"Verified workers-runtime-sdk {SDK_VERSION}: {len(hashes)} runtime files.")


def wrangler(*args):
    # Resolve npx.cmd on Windows as well as npx on Linux. No shell interpolation.
    executable = shutil.which("npx")
    if not executable:
        raise RuntimeError("Node.js/npx is missing")
    subprocess.run([executable, "--no-install", "wrangler", *args], cwd=ROOT, check=True)


def verify_bundle(outdir, root=ROOT):
    manifest = root / "dist/sdk-manifest.json"
    if not manifest.is_file():
        raise RuntimeError("SDK manifest missing; run npm run build")
    expected = json.loads(manifest.read_text("utf-8"))
    if not expected or any(name not in expected for name in REQUIRED):
        raise RuntimeError("Incomplete SDK manifest")
    for name, checksum in expected.items():
        file = outdir / "python_modules" / name
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise RuntimeError("Upload bundle is missing or changed SDK file: " + name)
    print(f"Upload bundle verified: all {len(expected)} Python SDK files are included.")


def package():
    verify_vendor()
    outdir = ROOT / "dist/worker"
    wrangler("deploy", "--dry-run", "--outdir", str(outdir))
    verify_bundle(outdir)


if __name__ == "__main__":
    if "--check-bundle" in sys.argv:
        package()
    else:
        prepare()
