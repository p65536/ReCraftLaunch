"""Compile and exercise the real launcher startup boundary in both configurations."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from native_test_support import CONFIGURATION, ROOT, RUN_DIR


class NativeStartupTests(unittest.TestCase):
    def test_real_executable_python_initialization(self):
        # Match Debug's relative home depth and override only the test main module.
        with tempfile.TemporaryDirectory(prefix="startup-", dir=ROOT / "build/run/x64") as temporary:
            directory = Path(temporary)
            executable = "reclnch_d.exe" if CONFIGURATION == "Debug" else "reclnch.exe"
            files = (executable, "python315.dll") + (("library.zip",) if CONFIGURATION == "Release" else ())
            for name in files:
                shutil.copy2(RUN_DIR / name, directory / name)
            (directory / "clnch_main.py").write_text('''import json, os, sys
from pathlib import Path
Path(__file__).with_name("result.json").write_text(json.dumps({
    "path": sys.path, "argv": sys.argv, "bytecode": sys.dont_write_bytecode,
    "home": sys.prefix, "environment": os.environ["PATH"]}), encoding="utf-8")
''', encoding="utf-8")
            environment = dict(os.environ, PATH="original;日本語")
            tested = subprocess.run([str(directory / executable), "--startup-probe", "日本語"],
                                    cwd=directory, env=environment, capture_output=True,
                                    text=True, timeout=15, check=False)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["bytecode"])
            self.assertEqual(result["argv"][1:], ["--startup-probe", "日本語"])
            self.assertEqual(result["environment"], str(directory) + "/lib;original;日本語")
            self.assertEqual(Path(result["path"][0]), directory)
            if CONFIGURATION == "Debug":
                self.assertEqual(Path(result["home"]).resolve(), ROOT / "Python315/tools")
                self.assertIn(ROOT / "clnch", [Path(path).resolve() for path in result["path"]])
            else:
                self.assertEqual(Path(result["home"]).resolve(), directory)
                self.assertIn(directory / "library.zip", [Path(path) for path in result["path"]])
            self.assertFalse((directory / "__pycache__").exists())

    def test_startup_api_boundaries(self):
        vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
        install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-version",
            "[18.0,19.0)", "-property", "installationPath"], text=True).strip()
        vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
        runtime = Path(sys.executable).parent
        environment = dict(os.environ, PYTHONHOME=str(runtime))
        environment["PATH"] = str(runtime) + os.pathsep + environment["PATH"]
        options = "/MDd /D_DEBUG /Od" if CONFIGURATION == "Debug" else "/MD /O2 /DNDEBUG"
        with tempfile.TemporaryDirectory(prefix="recraft-native-startup-") as temporary:
            executable = Path(temporary) / "startup.exe"
            command = (f'""{vcvars}" >nul && cl /nologo /EHsc /std:c++17 /utf-8 {options} '
                       f'/I"{runtime / "include"}" "{ROOT / "tools/native_startup_probe.cpp"}" '
                       f'/Fe:"{executable}" /link /LIBPATH:"{runtime / "libs"}" python315.lib user32.lib shell32.lib"')
            built = subprocess.run(f'"{os.environ["COMSPEC"]}" /d /s /c {command}', cwd=temporary,
                                   capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            try:
                tested = subprocess.run([str(executable)], env=environment, cwd=temporary,
                                        capture_output=True, text=True, timeout=10, check=False)
            except subprocess.TimeoutExpired as error:
                self.fail(f"Probe timed out: {error.stdout!r} {error.stderr!r}")
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            self.assertIn("0 failures", tested.stdout)
            print(f"{CONFIGURATION}: {tested.stdout.strip()}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
