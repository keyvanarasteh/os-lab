import json
import sys
from pathlib import Path

import pytest

# Make "import ext_scan" work however pytest is started.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

LAB = Path(__file__).resolve().parents[1] / "lab"


@pytest.fixture
def lab():
    return LAB


@pytest.fixture
def make_ext(tmp_path):
    """Write a small extension (manifest + files) into a temp folder."""
    def _make(manifest, files=None):
        manifest = {"manifest_version": 3, "name": "t", "version": "1", **manifest}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        for name, text in (files or {}).items():
            (tmp_path / name).write_text(text, encoding="utf-8")
        return tmp_path
    return _make
