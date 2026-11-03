"""Run the startup module with real INI/imports; replace window discovery/construction."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = r'''
import builtins
import os
import runpy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(sys.argv[1])
mode, language, storage, existing = sys.argv[2:]
if mode == "source":
    native_dir = root / "build/run/x64" / os.environ.get("RECRAFT_TEST_CONFIGURATION", "Release") / "lib"
    sys.path[:0] = [str(root / "clnch"), str(root), str(native_dir)]
else:
    native_dir = root / "dist/ReCraftLaunch/lib"
    sys.path[:0] = [str(root / "dist/ReCraftLaunch/library.zip"), str(native_dir)]
native_dir = Path(getattr(sys, "_clnch_test_native_dir", native_dir))

import importlib.abc
import importlib.util
class NativeFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        native = native_dir / (fullname.split(".")[-1] + ".pyd")
        if native.is_file():
            return importlib.util.spec_from_file_location(fullname, native)
sys.meta_path.insert(0, NativeFinder())
import ckit
import pyauto
import clnch_strings as strings
import clnch_native
for name in ("ckit.ckitcore", "pyauto.pyautocore", "clnch_native"):
    assert Path(sys.modules[name].__file__).resolve().parent == native_dir.resolve()
assert not any(name in sys.modules for name in ("clnch_cmdeditor", "clnch_cmdlist", "clnch_modifierconfig", "clnch_altenterconfig"))

class Finished(Exception): pass
with tempfile.TemporaryDirectory() as directory:
    app = Path(directory) / "app"
    app.mkdir()
    profile = Path(directory) / "profile"
    settings = profile / "ReCraftLaunch" if storage == "appdata" else app / "settings"
    settings.mkdir(parents=True)
    ini = settings / "reclnch.ini"
    original = b"[OTHER]\r\nkeep = yes\r\n" if language == "missing" else f"[MISC]\r\nlanguage = {language}\r\n".encode()
    if language != "first":
        ini.write_bytes(original)
    (app / "reclnch_exe.ini").write_text("[DATA]\nmulti_user = " + str(int(storage == "appdata")), encoding="utf-8")
    real_import = builtins.__import__
    imports = []
    mainwindow_class = []
    def construct(**kwargs):
        assert set(kwargs) == {"debug"}
        import clnch_ini, clnch_modifierconfig, clnch_altenterconfig, clnch_cmdeditor, clnch_cmdlist
        from ckit import ckit_resource
        assert Path(clnch_ini.ini_filename) == ini
        assert strings.get_language() == ("ja" if language == "ja" else "en")
        assert clnch_modifierconfig.ACTIONS["none"] == strings.ACTION_NONE
        assert clnch_altenterconfig.ACTIONS["none"] == strings.ALT_ENTER_NONE
        assert clnch_cmdeditor.FIELD_DEFS[0][1] == strings.FIELD_NAME
        assert clnch_cmdlist.EMPTY_LABEL == strings.COMMAND_EMPTY
        assert ckit_resource.strings["readonly"] == strings.CKIT_READONLY
        assert len(ckit_resource.strings) == 12
        assert clnch_ini.get("MISC", "language", "en") == ("en" if language in ("missing", "first") else language)
        assert not clnch_ini.dirty
        assert (ini.read_bytes() == original if language != "first" else not ini.exists())
        assert (settings / "scripts").is_dir()
        clnch_ini.set("MISC", "language", "ja" if strings.get_language() == "en" else "en")
        items = []
        help_path = app / "docs" / strings.get_language() / "index.html"
        help_path.parent.mkdir(parents=True)
        help_path.write_text("help", encoding="utf-8")
        with patch.object(ckit, "getAppExePath", return_value=str(app)), \
             patch.object(ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=items.append)), \
             patch.object(pyauto, "shellExecute") as launch:
            mainwindow_class[0].command_Help(SimpleNamespace(), None)
            items[0].subthread_func(items[0])
        launch.assert_called_once_with(None, str(help_path), "", "")
        raise Finished()
    def importing(name, *args, **kwargs):
        if name in ("clnch_mainwindow", "clnch_modifierconfig", "clnch_altenterconfig", "clnch_cmdeditor", "clnch_cmdlist"):
            assert existing == "no"
            assert strings.get_language() == ("ja" if language == "ja" else "en")
            from ckit import ckit_resource
            assert ckit_resource.strings["readonly"] == strings.CKIT_READONLY
        module = real_import(name, *args, **kwargs)
        imports.append(name)
        if name == "clnch_mainwindow":
            if not mainwindow_class:
                mainwindow_class.append(module.MainWindow)
            module.MainWindow = construct
        return module
    class Window:
        def getClassName(self): return "ReClnchWindowClass"
        def getText(self): return "ReCraftLaunch MainWindow"
        def getHWND(self): return 42
    def enumerate_windows(callback, arg):
        if existing == "yes": callback(Window(), arg)
    sys.argv[:] = [str(app / "reclnch.exe")]
    with patch.object(sys, "executable", str(app / "reclnch.exe")), patch.object(pyauto, "Window", SimpleNamespace(enum=enumerate_windows)), \
         patch.object(ckit, "getAppDataPath", return_value=str(profile)), patch.object(builtins, "__import__", importing), \
         patch.object(ckit.TextWindow, "sendIpc") as sent:
        try:
            runpy.run_module("clnch_main", run_name="__main__")
        except Finished:
            assert existing == "no"
        except SystemExit as exit_result:
            assert existing == "yes" and exit_result.code == 0
        else:
            raise AssertionError("startup did not reach its expected endpoint")
    if existing == "yes":
        assert "clnch_ini" not in imports
        assert "clnch_mainwindow" not in imports
        sent.assert_called_once()
    else:
        sent.assert_not_called()
        ckit.JobQueue.cancelAll()
        ckit.JobQueue.joinAll()
        ckit.JobQueue.defaultQueue().destroy()
    assert (ini.read_bytes() == original if language != "first" else not ini.exists())
print("startup OK")
'''


class LanguageStartupTests(unittest.TestCase):
    def test_embedded_debug_and_release_import_sources_and_select_languages(self):
        for mode, name in (("source", "reclnch_d.exe"), ("library", "reclnch.exe")):
            with tempfile.TemporaryDirectory(prefix="language-exe-", dir=ROOT / "build/run/x64") as directory:
                app = Path(directory)
                shutil.copy2(ROOT / "build/run/x64" / ("Debug" if mode == "source" else "Release") / name, app / name)
                shutil.copy2(ROOT / "build/run/x64/Release/python315.dll", app / "python315.dll")
                shutil.copy2(ROOT / "dist/ReCraftLaunch/library.zip", app / "library.zip")
                shutil.copytree(ROOT / "build/run/x64" / ("Debug" if mode == "source" else "Release") / "lib", app / "lib")
                marker = app / "result.txt"
                startup = ((ROOT / "clnch/clnch_main.py").read_text(encoding="utf-8") if mode == "source" else None)
                for language in ("ja", "en", "first", "missing", "invalid", "", "EN"):
                    with self.subTest(mode=mode, language=language):
                        # Only the entry wrapper is added to the isolated copy.
                        probe = PROBE.replace('runpy.run_module("clnch_main", run_name="__main__")',
                                              'exec(_startup, {"__name__": "__main__"})')
                        wrapper = "import sys, traceback\nfrom pathlib import Path\ntry:\n"
                        wrapper += f"    sys._clnch_test_native_dir = {str(app / 'lib')!r}\n"
                        wrapper += "    import clnch_strings\n"
                        expected = ROOT / "clnch/clnch_strings.py" if mode == "source" else app / "library.zip/clnch_strings.pyc"
                        wrapper += f"    assert Path(clnch_strings.__file__) == Path({str(expected)!r}), clnch_strings.__file__\n"
                        wrapper += f"    sys.argv[:] = ['probe', {str(ROOT)!r}, {mode!r}, {language!r}, 'portable', 'no']\n"
                        if mode == "source":
                            wrapper += f"    _startup = {startup!r}\n"
                        else:
                            wrapper += "    import marshal, zipfile\n"
                            wrapper += f"    with zipfile.ZipFile({str(app / 'library.zip')!r}) as library:\n"
                            wrapper += "        _startup = marshal.loads(library.read('clnch_main.pyc')[16:])\n"
                        wrapper += f"    exec({probe!r}, {{'__name__': 'probe', '_startup': _startup}})\n"
                        wrapper += f"    Path({str(marker)!r}).write_text('OK', encoding='utf-8')\n"
                        wrapper += f"except BaseException:\n    Path({str(marker)!r}).write_text(traceback.format_exc(), encoding='utf-8')\n    raise\n"
                        (app / "clnch_main.py").write_text(wrapper, encoding="utf-8")
                        result = subprocess.run([str(app / name)], capture_output=True, timeout=30, check=False)
                        self.assertTrue(marker.is_file(), result.stderr)
                        self.assertEqual(marker.read_text(encoding="utf-8"), "OK")
                        self.assertEqual(result.returncode, 0, result.stderr)
                        marker.unlink()

    def probe(self, mode, language, storage, existing="no"):
        result = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, str(ROOT), mode,
                                 language, storage, existing], capture_output=True, text=True,
                                encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("startup OK", result.stdout)

    def test_startup_ini_selection_precedes_gui_imports_in_source_and_release(self):
        for mode in ("source", "library"):
            for storage in ("portable", "appdata"):
                for language in ("ja", "en", "first", "missing", "invalid", "", "EN"):
                    with self.subTest(mode=mode, storage=storage, language=language):
                        self.probe(mode, language, storage)

    def test_existing_instance_path_skips_ini_and_gui_in_source_and_release(self):
        for mode in ("source", "library"):
            with self.subTest(mode=mode):
                self.probe(mode, "en", "portable", existing="yes")


if __name__ == "__main__":
    unittest.main()
