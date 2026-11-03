"""Check release layout and metadata; reuse generated help checks only for an exact copy."""
import argparse
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.check_language import check_distribution
from tools.check_native_build import check_release
from tools.version_info import check_package_versions, source_version


def check_layout(package):
    package = Path(package)
    check_licenses(package)
    for name in ("reclnch.exe", "python315.dll", "library.zip",
                 "settings/_custom.py", "settings/_commands.json"):
        assert (package / name).is_file(), name
    assert not any(path.name.lower().startswith(("vcruntime", "msvcp", "concrt", "vccorlib"))
                   for path in package.rglob("*.dll")), "VC runtime DLLs must not be packaged"
    for name in ("custom.py", "config_local.py", "commands.json", "reclnch.ini", "reclnch_exe.ini", "clnch.ini",
                 "config.py", "_config.py", "theme", "_custom.py", "_config_local.py", "_commands.json",
                 "settings/custom.py", "settings/config_local.py", "settings/_config_local.py",
                 "settings/commands.json", "settings/reclnch.ini", "settings/reclnch_exe.ini",
                 "clnch.exe", "clnch_d.exe", "reclnch_d.exe", "sitecustomize.py", "dict"):
        assert not (package / name).exists(), "Personal settings must not be packaged"
    compile((package / "settings/_custom.py").read_bytes(), "_custom.py", "exec")
    json.loads((package / "settings/_commands.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(package / "library.zip") as archive:
        names = set(archive.namelist())
        assert archive.testzip() is None, "Corrupt library.zip"
        assert "ckit/ckit_migemo.pyc" not in names, "Retired Migemo in library.zip"
        assert "clnch_commandwindow.pyc" not in names, "Retired INI editor in library.zip"
        for name in ("clnch_standard.pyc", "clnch_cmdeditor.pyc", "clnch_cmdlist.pyc",
                     "clnch_cmdstore.pyc", "clnch_execonfig.pyc", "clnch_modifierconfig.pyc", "clnch_altenterconfig.pyc"):
            assert name in names, name
        assert not any(name in names for name in
                       ("config.pyc", "_config.pyc", "_custom.pyc", "_config_local.pyc")), "Settings in library.zip"
        assert not any(name.startswith("samples/") for name in names), "Samples in library.zip"
        assert not any(name.startswith(("ckit/test/", "pyauto/sample/", "pyauto/doc/", "pyauto/tool/", "tools/"))
                       or name in ("ckit/makefile.pyc", "pyauto/makefile.pyc")
                       for name in names), "Development scripts in library.zip"
        for name in ("clnch_main.pyc", "ckit/__init__.pyc", "pyauto/__init__.pyc", "encodings/__init__.pyc"):
            assert archive.read(name)[:4] == importlib.util.MAGIC_NUMBER, name
        assert not any(PurePosixPath(name).name in
                       ("custom.py", "custom.pyc", "config_local.py", "config_local.pyc",
                        "commands.json", "reclnch.ini", "reclnch_exe.ini", "clnch.ini")
                       for name in names), "Personal settings in library.zip"

    assert not any(name.split("/")[0] in {"venv", "ensurepip", "tkinter", "turtledemo"}
                   or name == "turtle.pyc" for name in names), "Unsupported Python tools in library.zip"
    assert {path.name for path in (package / "themes").iterdir()} == {"black.ini", "white.ini", "gray.ini"}, "Theme layout differs"
    official_extensions = {"stamp", "netdrive", "clock", "completion_keys", "list_keys"}
    assert "editor.pyc" not in names, "Retired editor extension in library.zip"
    assert {path.name for path in (package / "extensions").iterdir()} == {name + ".py" for name in official_extensions}
    assert {path.name for path in (package / "settings/scripts").iterdir()} == {".gitkeep"}
    assert not any(name.startswith("extensions/") or name in {module + ".pyc" for module in official_extensions}
                   for name in names), "Official extensions must remain source files outside library.zip"


def check_licenses(package):
    package = Path(package)
    sources = {
        "LICENSE.md": "LICENSE.md",
        "licenses/craftlaunch_LICENSE.md": "licenses/craftlaunch_LICENSE.md",
        "licenses/ckit_LICENSE.md": "ckit/LICENSE.md",
        "licenses/pyauto_LICENSE.md": "pyauto/LICENSE.md",
        "licenses/python_LICENSE.txt": "licenses/python_LICENSE.txt",
        "licenses/expat_LICENSE.txt": "licenses/expat_LICENSE.txt",
    }
    assert {path.name for path in (package / "licenses").iterdir()} == {
        Path(name).name for name in sources if name.startswith("licenses/")
    }, "License file set differs (including filename case)"
    for name, source in sources.items():
        assert (package / name).is_file(), f"Missing license: {name}"
        assert (package / name).read_bytes() == (ROOT / source).read_bytes(), f"License copy differs: {name}"


def check_package_files(package, generated_docs=None):
    package = Path(package).resolve()
    check_layout(package)
    check_release(package)
    check_distribution(package)
    check_package_versions(package, source_version())
    for language in ("ja", "en"):
        help_dir = package / "docs" / language
        if generated_docs is None:
            subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_docs.py"),
                            str(help_dir), "--lang", language], check=True)
        else:
            # document already validated these files; verify the copy, including missing/extra assets.
            source = Path(generated_docs) / language
            expected = {p.relative_to(source): p for p in source.rglob("*") if p.is_file()}
            actual = {p.relative_to(help_dir): p for p in help_dir.rglob("*") if p.is_file()}
            assert actual.keys() == expected.keys(), f"Help file set differs: {language}"
            for name, original in expected.items():
                assert actual[name].read_bytes() == original.read_bytes(), f"Help copy differs: {language}/{name}"
    print("Package files OK: layout, native binaries, versions and bilingual documents.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--generated-docs", type=Path)
    args = parser.parse_args()
    check_package_files(args.package, args.generated_docs)
