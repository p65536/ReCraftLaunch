"""Select one native build for source tests; never fall back to another build."""
import importlib.abc
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGURATION = os.environ.get("RECRAFT_TEST_CONFIGURATION", "Release")
if CONFIGURATION not in ("Debug", "Release"):
    raise ValueError("RECRAFT_TEST_CONFIGURATION must be Debug or Release")
RUN_DIR = ROOT / "build/run/x64" / CONFIGURATION
NATIVE_NAMES = {"ckit.ckitcore", "pyauto.pyautocore", "clnch_native"}


class NativeTestFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in NATIVE_NAMES:
            native = RUN_DIR / "lib" / (fullname.rsplit(".", 1)[-1] + ".pyd")
            if not native.is_file():
                raise FileNotFoundError(native)
            return importlib.util.spec_from_file_location(fullname, native)


sys.meta_path.insert(0, NativeTestFinder())
