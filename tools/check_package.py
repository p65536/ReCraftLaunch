"""Verify isolated release imports and language binding; run with Python -I -S -B."""
import os
import sys

bootstrap_modules = set(sys.modules)
# Resolve all subsequent standard-library imports from the package as well.
package_dir = os.path.abspath(sys.argv[1])
sys.path[:] = [package_dir, os.path.join(package_dir, "library.zip"), os.path.join(package_dir, "lib")]
# Python initializes this package before the checker can replace sys.path.
sys.modules["encodings"].__path__[:] = [os.path.join(package_dir, "library.zip", "encodings")]
dll_directory = os.add_dll_directory(os.path.join(package_dir, "lib"))

import importlib
import importlib.abc
import importlib.util
import json
from pathlib import Path

package = Path(sys.argv[1]).resolve()


class PackageFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        native = package / "lib" / (fullname.split(".")[-1] + ".pyd")
        if native.is_file():
            return importlib.util.spec_from_file_location(fullname, native)


sys.meta_path.insert(0, PackageFinder())
sys.path[:] = [str(package), str(package / "library.zip"), str(package / "lib")]
sys._clnch_app_dir = str(package)

import clnch_strings
import clnch_text

import ckit

language = sys.argv[2] if len(sys.argv) > 2 else "ja"
assert language in ("ja", "en"), language
clnch_strings.initialize(language)
clnch_text.initialize()

from ckit import ckit_resource

assert ckit_resource.strings["readonly"] == clnch_strings.CKIT_READONLY
assert ckit_resource.strings["error_config_file_load_failed"] == clnch_strings.CKIT_CONFIG_LOAD_ERROR
assert clnch_strings.get_language() == language
assert len(ckit_resource.strings) == 12
import clnch_altenterconfig
import clnch_commandexecutor
import clnch_commandplatform
import clnch_commandregistry
import clnch_configmenu
import clnch_consolelog
import clnch_consolewindow
import clnch_execonfig
import clnch_inputconfig
import clnch_listwindow
import clnch_mainwindow
import clnch_modifierconfig
import clnch_standard

import clnch_native
import pyauto

ckit.setDataPath(str(package / "settings"))
import clnch_cmddraft
import clnch_cmdeditor
import clnch_cmdlist
import clnch_cmdstore

assert Path(clnch_cmdeditor.JSON_PATH) == package / "settings" / "commands.json"

for module in (ckit, pyauto, clnch_text, clnch_strings, clnch_mainwindow, clnch_consolelog, clnch_consolewindow,
               clnch_listwindow, clnch_configmenu, clnch_standard, clnch_execonfig, clnch_inputconfig, clnch_modifierconfig,
               clnch_commandexecutor, clnch_commandplatform, clnch_commandregistry,
               clnch_cmddraft, clnch_cmdeditor, clnch_cmdlist, clnch_cmdstore, clnch_altenterconfig):
    assert Path(module.__file__).is_relative_to(package / "library.zip"), module.__file__
for module in (sys.modules["ckit.ckitcore"], sys.modules["pyauto.pyautocore"], clnch_native):
    assert Path(module.__file__).parent == package / "lib", module.__file__

assert clnch_modifierconfig.ACTIONS["none"] == clnch_strings.ACTION_NONE
assert clnch_altenterconfig.ACTIONS["none"] == clnch_strings.ALT_ENTER_NONE
assert clnch_cmdeditor.FIELD_DEFS[0][1] == clnch_strings.FIELD_NAME
assert clnch_cmdlist.EMPTY_LABEL == clnch_strings.COMMAND_EMPTY
if language == "ja":
    clnch_cmdstore.validate_commands(json.loads((package / "settings/_commands.json").read_text(encoding="utf-8")))

    # Preserve the optional native standard library used by custom and extensions.
    for native in sorted((package / "lib").glob("*.pyd")):
        name = native.stem
        if name in {"ckitcore", "pyautocore", "clnch_native"}:
            continue
        module = importlib.import_module(name)
        assert Path(module.__file__).parent == package / "lib", module.__file__

    sys.path.append(str(package / "extensions"))
    for name in ("stamp", "netdrive", "clock", "completion_keys", "list_keys"):
        module = importlib.import_module(name)
        assert Path(module.__file__).parent == package / "extensions", module.__file__
    for name in ("asyncio", "bz2", "ctypes", "decimal", "hashlib", "lzma", "sqlite3", "ssl",
                 "subprocess", "xml.etree.ElementTree", "compression.zstd", "doctest", "multiprocessing",
                 "unittest.mock", "urllib.request", "pdb", "platform", "uuid", "zoneinfo",
                 "unicodedata", "concurrent.futures"):
        importlib.import_module(name)

for name, module in tuple(sys.modules.items()):
    filename = getattr(module, "__file__", None)
    if (filename and name not in bootstrap_modules and module is not sys.modules["__main__"]
            and getattr(getattr(module, "__spec__", None), "origin", None) != "frozen"):
        assert Path(filename).is_relative_to(package), (name, filename)
print(f"Package imports OK: {language} (shared native/stdlib imports checked once in Japanese).")
dll_directory.close()
