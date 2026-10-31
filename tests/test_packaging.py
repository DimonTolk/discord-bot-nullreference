import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_worker import REQUIRED, verify_bundle, verify_vendor


def fixture_tree(root):
    checksums = {}
    for name in REQUIRED:
        value = b"from .blob import Blob\n" if name == "workers/__init__.py" else b"# SDK fixture\n"
        file = root / "python_modules" / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(value)
        checksums[name] = hashlib.sha256(value).hexdigest()
    (root / "dist").mkdir(exist_ok=True)
    (root / "dist/sdk-manifest.json").write_text(json.dumps(checksums), "utf-8")


def test_packaging_rejects_missing_sdk_even_when_tools_are_installed(tmp_path):
    with pytest.raises(RuntimeError, match="missing"):
        verify_vendor(tmp_path)
    fixture_tree(tmp_path)
    assert verify_vendor(tmp_path).is_dir()


def test_verify_the_uploaded_files_not_only_the_development_environment(tmp_path):
    fixture_tree(tmp_path)
    verify_bundle(tmp_path, tmp_path)
    file = tmp_path / "python_modules/workers/__init__.py"
    file.write_text("# wrong SDK", "utf-8")
    with pytest.raises(RuntimeError, match="changed SDK"):
        verify_bundle(tmp_path, tmp_path)
    file.unlink()
    with pytest.raises(RuntimeError, match="missing"):
        verify_bundle(tmp_path, tmp_path)
