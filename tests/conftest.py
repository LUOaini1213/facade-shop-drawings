import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """Fresh build of every output except the PDFs."""
    out = tmp_path_factory.mktemp("out")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), "--out", str(out), "--no-pdf"],
                   check=True, stdout=subprocess.DEVNULL)
    return out


@pytest.fixture()
def built_copy(built, tmp_path):
    """A disposable copy of the fresh build, for tamper tests."""
    dst = tmp_path / "out"
    shutil.copytree(built, dst)
    return dst
