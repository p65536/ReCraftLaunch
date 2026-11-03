"""Bundled Japanese/English wording, placeholders and module checks; run with -B."""
import ast
import contextlib
import importlib
import importlib.util
import io
import json
import os
import py_compile
import re
import runpy
import shutil
import string
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_resource
import clnch_strings as strings

sys.path.insert(0, str(ROOT))
from tools.check_language import (
    check_distribution,
    check_library,
    read_definitions,
    resolve_language,
)


class StringTests(unittest.TestCase):
    def test_default_initialization_uses_english(self):
        previous = strings.get_language()
        try:
            strings.initialize()
            self.assertEqual(strings.get_language(), "en")
            for name, value in read_definitions(resolve_language("en")).items():
                self.assertEqual(getattr(strings, name), value)
        finally:
            strings.initialize(previous)

    def test_all_translations_match_standard_definitions(self):
        standard = read_definitions(ROOT / "clnch/clnch_strings_ja.py")
        for path in (ROOT / "clnch").glob("clnch_strings_*.py"):
            with self.subTest(path=path.name):
                self.assertEqual(resolve_language(path.stem.removeprefix("clnch_strings_")), path)
        english = read_definitions(resolve_language("en"))
        self.assertEqual(english.keys(), standard.keys())
        self.assertFalse(any(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value) for value in english.values()))
        self.assertEqual(english["CLOCK_FORMAT"], standard["CLOCK_FORMAT"])
        for definitions in (standard, english):
            self.assertEqual(definitions["LANGUAGE_JAPANESE"], "Japanese")
            self.assertEqual(definitions["LANGUAGE_ENGLISH"], "English")
        self.assertEqual(english["ACCESS_LABEL"].format(label="Name", key="N"), "Name (N)")

    def test_definitions_are_import_free_and_references_and_placeholders_match(self):
        tree = ast.parse((ROOT / "clnch/clnch_strings_ja.py").read_text(encoding="utf-8"))
        self.assertTrue(all(isinstance(n, (ast.Expr, ast.Assign)) for n in tree.body))
        for folder in ("clnch", "ckit"):
            for path in (ROOT / folder).glob("*.py"):
                source = path.read_text(encoding="utf-8-sig")
                if "import clnch_strings as strings" not in source:
                    continue
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "strings":
                        self.assertTrue(hasattr(strings, node.attr), (path.name, node.lineno, node.attr))
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "format" and isinstance(node.func.value, ast.Attribute)
                            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "strings"):
                        value = getattr(strings, node.func.value.attr)
                        fields = {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
                        self.assertEqual(fields, {kw.arg for kw in node.keywords}, (path.name, node.lineno))

    def test_rebuilt_copy_changes_app_and_ckit_by_editing_only_wording(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT / "clnch/clnch_strings_ja.py").read_text(encoding="utf-8")
            source = source.replace("編集禁止です.", "Translated read-only 全角")
            source = source.replace("version {version}", "translated version {version}")
            (root / "clnch_strings.py").write_text(source, encoding="utf-8")
            entries = {"clnch_strings_ja": root / "clnch_strings.py",
                       "clnch_strings": ROOT / "clnch/clnch_strings.py",
                       "clnch_resource": ROOT / "clnch/clnch_resource.py",
                       "clnch_text": ROOT / "clnch/clnch_text.py",
                       "ckit/ckit_resource": ROOT / "ckit/ckit_resource.py"}
            with zipfile.ZipFile(root / "library.zip", "w") as archive:
                for name, path in entries.items():
                    target = root / (name.replace("/", "_") + ".pyc")
                    py_compile.compile(str(path), str(target), doraise=True, optimize=2)
                    archive.write(target, name + ".pyc")
                archive.writestr("ckit/__init__.py", "from . import ckit_resource\n")
            code = '''import sys
sys.path.insert(0, sys.argv[1])
import clnch_resource, clnch_text
clnch_text.initialize()
from ckit import ckit_resource
assert "translated version" in clnch_resource.startupString()
assert ckit_resource.strings["readonly"] == "Translated read-only 全角"
assert len(ckit_resource.strings) == 12
assert not hasattr(ckit_resource, "TranslatedStrings")
'''
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root / "library.zip")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_startup_initialization_order(self):
        source = (ROOT / "clnch/clnch_main.py").read_text(encoding="utf-8-sig")
        markers = ["if existing_clnch_wnd:", "app_dir =", "clnch_ini.read()", "strings.initialize(",
                   "clnch_text.initialize()", "import clnch_mainwindow", "clnch_mainwindow.MainWindow("]
        positions = [source.index(marker) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        resource = (ROOT / "ckit/ckit_resource.py").read_text(encoding="utf-8")
        self.assertNotIn("locale", resource)
        self.assertNotIn("clnch", resource)

    def test_direct_ckit_entry_uses_supplied_wording_even_on_config_errors(self):
        package = ModuleType("ckit")
        package.__path__ = [str(ROOT / "ckit")]
        with patch.dict(sys.modules, {"ckit": package}):
            resource = importlib.import_module("ckit.ckit_resource")
            hooks = importlib.import_module("ckit.ckit_userconfig")
            self.addCleanup(sys.modules.pop, "ckit.ckit_resource", None)
            self.addCleanup(sys.modules.pop, "ckit.ckit_userconfig", None)
            import clnch_text
            clnch_text.initialize()
            expected = {"readonly", "search_found", "search_not_found", "modified_line_not_found",
                        "bookmark_not_found", "modified_line_or_bookmark_not_found",
                        "error_config_file_load_failed", "error_config_file_exec_failed"}
            self.assertTrue(expected.issubset(resource.strings))
            output = io.StringIO()
            with (
                contextlib.redirect_stdout(output),
                contextlib.redirect_stderr(io.StringIO()),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "bad.py"
                path.write_text("raise RuntimeError('test')", encoding="utf-8")
                hooks.reloadConfigScript(path)
                hooks.user_namespace["test"] = lambda: 1 / 0
                hooks.callConfigFunc("test")
            self.assertIn(strings.CKIT_CONFIG_LOAD_ERROR, output.getvalue())
            self.assertIn(strings.CKIT_CONFIG_EXEC_ERROR, output.getvalue())


class PackageBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        with patch.object(sys, "argv", ["makefile.py"]):
            self.namespace = runpy.run_path(str(ROOT / "makefile.py"))
        self.functions = self.namespace["target_dist"].__globals__
        directories = {"samples/scripts", "docs/html/ja", "docs/html/en",
                       "build/run/x64/Release/lib", "licenses"}
        sources = set(self.namespace["COPY_ITEMS"]) | set(self.namespace["NATIVE_PROJECTS"])
        sources.update({"Python315/tools/python.exe", "clnch/clnch_standard.py", "clnch/clnch_cmdeditor.py",
                        "clnch/clnch_cmdlist.py", "clnch/clnch_cmdstore.py", "clnch/clnch_execonfig.py",
                        "clnch/clnch_modifierconfig.py", "clnch/clnch_altenterconfig.py"})
        for name in sources:
            path = self.root / name
            if name in directories:
                path.mkdir(parents=True)
                path = path / ".gitkeep"
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
        package = self.root / "dist/ReCraftLaunch"
        package.mkdir(parents=True)
        (package / "obsolete.txt").write_bytes(b"old package")

    def run_package(self, fail=""):
        events = []

        def step(name):
            events.append(name)
            if name == fail:
                raise ValueError(name)

        def run(command, **kwargs):
            self.assertTrue(kwargs["check"])
            if command[0] == "MSBuild.exe":
                self.assertIn("/t:Rebuild", command)
                self.assertIn("/p:Configuration=Release", command)
                self.assertIn("/p:Platform=x64", command)
                step("native:" + command[1])
            else:
                self.assertEqual(command[1:5], ["-I", "-S", "-B", "tools/check_package.py"])
                step("import:" + command[-1])

        def check_files(package, generated_docs):
            self.assertEqual(package, Path("dist/ReCraftLaunch"))
            self.assertEqual(generated_docs, "docs/html")
            step("files")

        error = ""
        with (
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(io.StringIO()),
            patch.dict(self.functions, {
                "find_msbuild": lambda: Path("MSBuild.exe"),
                "subprocess": SimpleNamespace(run=run),
                "target_compile": lambda: step("compile"),
                "target_copy": lambda run_dir: step("copy:" + run_dir),
                "target_document": lambda: step("document"),
                "check_package_files": check_files,
                "target_archive": lambda verified=False: step("archive:" + str(verified)),
            }),
        ):
            try:
                self.namespace["target_release"]()
            except (ValueError, FileNotFoundError) as exc:
                error = str(exc)
        return events, error

    def test_single_package_rebuilds_and_generates_once_then_validates_both_languages(self):
        events, error = self.run_package()
        self.assertEqual(error, "")
        self.assertEqual(events, [*("native:" + name for name in self.namespace["NATIVE_PROJECTS"]),
                                  "compile", "copy:build/run/x64/Release", "document", "files",
                                  "import:ja", "import:en", "archive:True"])
        package = self.root / "dist/ReCraftLaunch"
        self.assertFalse((package / "obsolete.txt").exists())
        for source, destination in self.namespace["COPY_ITEMS"].items():
            original = self.root / source
            actual = package / destination
            if original.is_dir():
                self.assertEqual((actual / ".gitkeep").read_bytes(), (original / ".gitkeep").read_bytes())
            else:
                self.assertEqual(actual.read_bytes(), original.read_bytes())

    def test_generation_failure_preserves_existing_package_and_stops_later_steps(self):
        stages = [*("native:" + name for name in self.namespace["NATIVE_PROJECTS"]),
                  "compile", "copy:build/run/x64/Release", "document"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                events, error = self.run_package(fail=stage)
                self.assertEqual(error, stage)
                self.assertEqual(events, stages[:index + 1])
                self.assertEqual((self.root / "dist/ReCraftLaunch/obsolete.txt").read_bytes(), b"old package")

    def test_debug_option_keeps_distribution_build_and_runtime_in_release(self):
        with patch.object(sys, "argv", ["makefile.py", "-d", "dist"]):
            self.namespace = runpy.run_path(str(ROOT / "makefile.py"))
        self.functions = self.namespace["target_dist"].__globals__
        events, error = self.run_package()
        self.assertEqual(error, "")
        self.assertEqual([event for event in events if event.startswith("copy:")], ["copy:build/run/x64/Release"])

    def test_verification_failure_stops_before_later_imports_or_archive(self):
        for stage in ("files", "import:ja", "import:en"):
            with self.subTest(stage=stage):
                events, error = self.run_package(fail=stage)
                self.assertEqual(error, stage)
                self.assertEqual(events[-1], stage)
                self.assertFalse(any(event.startswith("archive:") for event in events))
                if stage == "files":
                    self.assertFalse(any(event.startswith("import:") for event in events))

    def test_missing_release_input_preserves_existing_package(self):
        (self.root / "themes/gray.ini").unlink()
        events, error = self.run_package()
        self.assertIn("themes", error)
        self.assertNotIn("files", events)
        self.assertEqual((self.root / "dist/ReCraftLaunch/obsolete.txt").read_bytes(), b"old package")

    def test_output_cannot_escape_repository(self):
        with (
            contextlib.chdir(self.root),
            patch.dict(self.functions, {"DIST_DIR": "../outside"}),
            self.assertRaisesRegex(ValueError, "inside this repository"),
        ):
            self.namespace["check_package_outputs"]()

    def test_output_links_are_rejected_before_build_or_deletion(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"keep")
        for name, target in (("dist/ReCraftLaunch/link", outside), ("build/obj/link", outside),
                             ("build/run/x64/Release/lib/link", outside),
                             ("build/Lib/dangling.pyc", self.root / "absent")):
            with self.subTest(name=name):
                link = self.root / name
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target, target_is_directory=target == outside)
                try:
                    events, error = self.run_package()
                    self.assertIn("links or reparse points", error)
                    self.assertEqual(events, [])
                    self.assertEqual((outside / "keep.txt").read_bytes(), b"keep")
                finally:
                    link.unlink()

    def test_junction_ancestor_is_rejected_before_build_or_deletion(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"keep")
        link = self.root / "build/obj"
        result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.returncode, 0)
        try:
            events, error = self.run_package()
            self.assertIn("links or reparse points", error)
            self.assertEqual(events, [])
            self.assertEqual((outside / "keep.txt").read_bytes(), b"keep")
        finally:
            link.rmdir()

    def test_vs_discovery_and_missing_tools(self):
        vswhere = self.root / "Microsoft Visual Studio/Installer/vswhere.exe"
        vswhere.parent.mkdir(parents=True)
        vswhere.write_bytes(b"vswhere")
        msbuild = self.root / "VS/MSBuild/Current/Bin/MSBuild.exe"
        msbuild.parent.mkdir(parents=True)
        msbuild.write_bytes(b"msbuild")
        run = Mock(return_value=SimpleNamespace(stdout=str(self.root / "VS") + "\n"))
        with patch.dict(os.environ, {"ProgramFiles(x86)": str(self.root)}), patch.dict(
            self.functions, {"subprocess": SimpleNamespace(run=run)},
        ):
            self.assertEqual(self.namespace["find_msbuild"](), msbuild)
            self.assertIn("[18.0,19.0)", run.call_args.args[0])
            self.assertTrue(run.call_args.kwargs["check"])
            msbuild.unlink()
            with self.assertRaises(FileNotFoundError):
                self.namespace["find_msbuild"]()
            run.return_value.stdout = ""
            with self.assertRaisesRegex(RuntimeError, "Visual Studio 2026"):
                self.namespace["find_msbuild"]()
            vswhere.unlink()
            with self.assertRaises(FileNotFoundError):
                self.namespace["find_msbuild"]()


class PackageLayoutTests(unittest.TestCase):
    def setUp(self):
        from tools.check_package_files import check_layout
        self.check_layout = check_layout
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.package = Path(self.directory.name)
        for name in ("reclnch.exe", "python315.dll", "settings/_custom.py", "settings/_commands.json",
                     "themes/black.ini", "themes/white.ini", "themes/gray.ini", "settings/scripts/.gitkeep",
                     "extensions/stamp.py", "extensions/netdrive.py", "extensions/clock.py",
                     "extensions/completion_keys.py", "extensions/list_keys.py"):
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"{}" if name.endswith(".json") else b"")
        self.members = {name + ".pyc": importlib.util.MAGIC_NUMBER for name in (
            "clnch_standard", "clnch_cmdeditor", "clnch_cmdlist", "clnch_cmdstore", "clnch_execonfig",
            "clnch_modifierconfig", "clnch_altenterconfig", "clnch_main", "ckit/__init__", "pyauto/__init__",
            "encodings/__init__")}
        self.write_library(self.members)

        for source, destination in (("LICENSE.md", "LICENSE.md"),
                                    ("licenses/craftlaunch_LICENSE.md", "licenses/craftlaunch_LICENSE.md"),
                                    ("ckit/LICENSE.md", "licenses/ckit_LICENSE.md"),
                                    ("pyauto/LICENSE.md", "licenses/pyauto_LICENSE.md"),
                                    ("licenses/python_LICENSE.txt", "licenses/python_LICENSE.txt"),
                                    ("licenses/expat_LICENSE.txt", "licenses/expat_LICENSE.txt")):
            target = self.package / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, target)

    def write_library(self, members):
        with zipfile.ZipFile(self.package / "library.zip", "w") as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def test_layout_accepts_expected_and_rejects_missing_or_forbidden_files(self):
        self.check_layout(self.package)
        for name in ("reclnch.exe", "settings/_custom.py", "settings/_commands.json", "extensions/clock.py"):
            path = self.package / name
            content = path.read_bytes()
            path.unlink()
            with self.subTest(missing=name), self.assertRaises((AssertionError, FileNotFoundError)):
                self.check_layout(self.package)
            path.write_bytes(content)
        for name in ("settings/custom.py", "sitecustomize.py", "reclnch.ini", "lib/vcruntime140.dll",
                     "settings/scripts/personal.py", "themes/old.ini"):
            path = self.package / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"forbidden")
            with self.subTest(extra=name), self.assertRaises(AssertionError):
                self.check_layout(self.package)
            path.unlink()
        for name in ("tools/check.pyc", "extensions/stamp.pyc", "stamp.pyc", "samples/custom.pyc",
                     "clnch_commandwindow.pyc", "ckit/ckit_migemo.pyc", "venv/__init__.pyc",
                     "nested/custom.pyc"):
            self.write_library({**self.members, name: b"forbidden"})
            with self.subTest(member=name), self.assertRaises(AssertionError):
                self.check_layout(self.package)
        self.write_library(self.members)

    def test_generated_help_copy_requires_identical_files_in_both_languages(self):
        from tools.check_package_files import check_package_files
        generated = self.package / "generated"
        for language in ("ja", "en"):
            for base in (generated, self.package / "docs"):
                directory = base / language
                directory.mkdir(parents=True)
                (directory / "index.html").write_bytes(language.encode())
                (directory / "asset.js").write_bytes(b"asset")
        with (
            patch("tools.check_package_files.check_layout"),
            patch("tools.check_package_files.check_release"),
            patch("tools.check_package_files.check_distribution"),
            patch("tools.check_package_files.check_package_versions"),
            patch("tools.check_package_files.source_version", return_value="1.2.3"),
            patch("tools.check_package_files.subprocess.run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            check_package_files(self.package, generated)
            run.assert_not_called()
            for language in ("ja", "en"):
                asset = self.package / "docs" / language / "asset.js"
                for mode in ("missing", "changed", "extra"):
                    if mode == "missing":
                        asset.unlink()
                    elif mode == "changed":
                        asset.write_bytes(b"changed")
                    else:
                        (asset.parent / "extra.js").write_bytes(b"extra")
                    with self.subTest(language=language, mode=mode), self.assertRaises(AssertionError):
                        check_package_files(self.package, generated)
                    asset.write_bytes(b"asset")
                    (asset.parent / "extra.js").unlink(missing_ok=True)
            check_package_files(self.package)
            self.assertEqual([call.args[0][-1] for call in run.call_args_list], ["ja", "en"])


class LanguageBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ("makefile.py", "tools/check_package_files.py", "tools/check_language.py", "tools/check_native_build.py", "tools/version_info.py", "clnch/clnch_strings.py", "clnch/clnch_strings_ja.py",
                     "clnch/clnch_strings_en.py", "clnch/clnch_resource.py", "clnch/clnch_text.py",
                     "ckit/ckit_resource.py"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        (self.root / "ckit/__init__.py").write_text("from . import ckit_resource\n", encoding="utf-8")
        (self.root / "Python315/tools/Lib").mkdir(parents=True)
        self.library = self.root / "build/run/x64/Release/library.zip"

    def run_build(self, *args, success=True):
        result = subprocess.run([sys.executable, "-B", "makefile.py", *args], cwd=self.root,
                                capture_output=True, text=True, encoding="utf-8", check=False)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def run_archive(self, success=True, native_error=None):
        # Layout/native/HTML have focused checks; keep real wording, documents and ZIP versions here.
        error = ""
        with (
            contextlib.chdir(self.root),
            patch.object(sys, "argv", ["makefile.py", "archive"]),
            patch("tools.version_info.check_executable_version", side_effect=native_error),
            patch("tools.check_package_files.check_layout"),
            patch("tools.check_package_files.check_release"),
            patch("tools.check_package_files.check_distribution", side_effect=lambda package: check_distribution(package, self.root)),
            patch("tools.check_package_files.source_version", return_value=clnch_resource.clnch_version),
            patch("tools.check_package_files.subprocess", SimpleNamespace(run=lambda *args, **kwargs: None)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            try:
                runpy.run_path(str(self.root / "makefile.py"), run_name="__main__")
            except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
                error = str(exc)
        self.assertEqual(not error, success, error)
        return SimpleNamespace(stderr=error)

    def test_copy_creates_empty_scripts_and_preserves_existing_settings(self):
        sources = {"Python315/tools/python315.dll": b"dll", "build/run/x64/Release/lib/ckitcore.pyd": b"ckit",
                   "build/run/x64/Release/lib/pyautocore.pyd": b"pyauto", "build/run/x64/Release/lib/clnch_native.pyd": b"native",
                   "samples/_custom.py": (ROOT / "samples/_custom.py").read_bytes(),
                   "samples/_commands.json": b"{}"}
        for name, data in sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / "Python315/tools/DLLs").mkdir()
        self.run_build("copy")
        settings = self.root / "build/run/x64/Release/settings"
        self.assertEqual(list((settings / "scripts").iterdir()), [])
        self.assertEqual((settings / "custom.py").read_bytes(), sources["samples/_custom.py"])
        self.assertEqual((settings / "commands.json").read_bytes(), b"{}")
        retained = {settings / "custom.py": b"# personal", settings / "commands.json": b'{"keep": {}}',
                    settings / "scripts/my_commands.py": b"# personal module"}
        for path, data in retained.items():
            path.write_bytes(data)
        self.run_build("copy")
        for path, data in retained.items():
            self.assertEqual(path.read_bytes(), data)
        site = (self.root / "build/run/x64/Release/sitecustomize.py").read_text(encoding="utf-8")
        self.assertIn("sys._clnch_app_dir", site)
        self.assertIn('os.path.dirname(__file__), "../../../.."', site)
        debug_lib = self.root / "build/run/x64/Debug/lib"
        debug_lib.mkdir(parents=True)
        for name in ("ckitcore", "pyautocore", "clnch_native"):
            (debug_lib / (name + ".pyd")).write_bytes(b"debug native")
        self.run_build("-d", "copy")
        for path, data in retained.items():
            self.assertEqual(path.read_bytes(), data)
        for name, data in sources.items():
            if name.endswith(".pyd"):
                self.assertEqual((self.root / name).read_bytes(), data)
                self.assertEqual((debug_lib / Path(name).name).read_bytes(), b"debug native")
        self.assertEqual((debug_lib.parent / "settings/commands.json").read_bytes(), b"{}")

    def test_one_library_selects_both_languages_and_supplies_all_ckit_wording(self):
        self.run_build("compile")
        check_library(self.library, self.root)
        original = self.library.read_bytes()
        code = """import sys, json
sys.path.insert(0, sys.argv[1])
import clnch_strings as strings, clnch_text, clnch_strings_ja, clnch_strings_en
before = [vars(module).copy() for module in (clnch_strings_ja, clnch_strings_en)]
strings.initialize(sys.argv[2])
clnch_text.initialize()
from ckit import ckit_resource
assert len(ckit_resource.strings) == 12
assert all(vars(module) == snapshot for module, snapshot in zip((clnch_strings_ja, clnch_strings_en), before))
expected = ("CKIT_READONLY", "CKIT_SEARCH_FOUND", "CKIT_SEARCH_NOT_FOUND", "CKIT_MODIFIED_LINE_NOT_FOUND",
            "CKIT_BOOKMARK_NOT_FOUND", "CKIT_MODIFIED_OR_BOOKMARK_NOT_FOUND", "CKIT_CONFIG_LOAD_ERROR",
            "CKIT_CONFIG_EXEC_ERROR", "CKIT_INVALID_KEY", "CKIT_COLOR_NOT_FOUND", "CKIT_JOB_SUSPENDED", "CKIT_JOB_RESUMED")
assert list(ckit_resource.strings.values()) == [getattr(strings, key) for key in expected]
print(json.dumps({k: v for k, v in vars(strings).items() if k.isupper()}))
"""
        for language in ("ja", "en", "invalid", "", "EN"):
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(self.library), language],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = read_definitions(resolve_language("ja" if language == "ja" else "en", self.root))
            self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(self.library.read_bytes(), original)

    def test_library_rejects_missing_extra_or_misplaced_wording_modules(self):
        self.run_build("compile")
        with zipfile.ZipFile(self.library) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        english = "clnch_strings_en.pyc"
        for replacement in (None, "clnch_strings_extra.pyc", "nested/clnch_strings_en.pyc"):
            with self.subTest(replacement=replacement):
                entries = original.copy()
                if replacement != "clnch_strings_extra.pyc":
                    del entries[english]
                if replacement is not None:
                    entries[replacement] = original[english]
                with zipfile.ZipFile(self.library, "w") as archive:
                    for name, data in entries.items():
                        archive.writestr(name, data)
                with self.assertRaisesRegex(ValueError, "unexpected wording modules"):
                    check_library(self.library, self.root)

    def test_old_build_language_option_fails_before_output_changes(self):
        self.run_build("compile")
        original = self.library.read_bytes()
        self.run_build("--lang", "en", "compile", success=False)
        self.assertEqual(self.library.read_bytes(), original)

    def test_bad_translation_structure_definitions_and_placeholders(self):
        path = self.root / "clnch/clnch_strings_en.py"
        original = path.read_text(encoding="utf-8")
        for source in (original.replace("BUTTON_ADD = 'Add'\n", ""),
                       original + "EXTRA = 'extra'\n", original + "BUTTON_ADD = 'duplicate'\n",
                       original + "import os\n", original + "VALUE = str(123)\n",
                       original.replace("{error}", "{failure}"), original.replace("{error}", "{error")):
            with self.subTest(source=source[-50:]):
                path.write_text(source, encoding="utf-8")
                with self.assertRaises((ValueError, SyntaxError)):
                    resolve_language("en", self.root)

    def stage_package(self):
        package = self.root / "dist/ReCraftLaunch"
        package.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.library, package / "library.zip")
        for lang in ("ja", "en"):
            help_dir = package / "docs" / lang
            help_dir.mkdir(parents=True, exist_ok=True)
            (help_dir / "index.html").write_bytes(b"bundled help")
            (help_dir / "style.css").write_bytes(b"help styles")
            (help_dir / "language.txt").write_text(lang, encoding="utf-8")
            for source, target in (("readme.txt", f"README.{lang}.txt"), ("commands.md", f"COMMANDS.{lang}.md")):
                path = self.root / "docs" / lang / source
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / "docs" / lang / source).read_bytes())
                shutil.copy2(path, package / target)
        return package

    def test_archive_includes_both_languages_and_rejects_missing_or_stale_content(self):
        self.run_build("compile")
        package = self.stage_package()
        self.run_archive()
        path = self.root / f"dist/ReCraftLaunch_{clnch_resource.clnch_version}.zip"
        original = path.read_bytes()
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("ReCraftLaunch/library.zip"), self.library.read_bytes())
            for lang in ("ja", "en"):
                self.assertEqual(archive.read(f"ReCraftLaunch/docs/{lang}/style.css"), b"help styles")
                self.assertEqual(archive.read(f"ReCraftLaunch/README.{lang}.txt"), (ROOT / f"docs/{lang}/readme.txt").read_bytes())
                self.assertIn(f"ReCraftLaunch/COMMANDS.{lang}.md", archive.namelist())
            self.assertNotIn("ReCraftLaunch/README.txt", archive.namelist())
        for name in ("docs/en/index.html", "docs/ja/language.txt", "README.en.txt", "COMMANDS.ja.md"):
            target = package / name
            content = target.read_bytes()
            target.unlink()
            self.run_archive(success=False)
            self.assertEqual(path.read_bytes(), original)
            target.write_bytes(content)
        (package / "docs/en/language.txt").write_text("ja", encoding="utf-8")
        self.run_archive(success=False)
        self.assertEqual(path.read_bytes(), original)

    def test_changed_version_names_archive_and_rejects_stale_artifacts(self):
        resource = self.root / "clnch/clnch_resource.py"
        source = resource.read_text(encoding="utf-8")
        resource.write_text(source.replace(f'clnch_version = "{clnch_resource.clnch_version}"',
                                           'clnch_version = "2.3.4"'), encoding="utf-8")
        self.run_build("compile")
        self.stage_package()
        archive = self.root / "dist/ReCraftLaunch_2.3.4.zip"
        with patch.object(clnch_resource, "clnch_version", "2.3.4"):
            self.run_archive()
            original = archive.read_bytes()
            self.run_archive( success=False,
                             native_error=subprocess.CalledProcessError(1, "native version check"))
            self.assertEqual(archive.read_bytes(), original)
        stale_name = self.root / "dist/ReCraftLaunch_2.3.5.zip"
        stale_name.write_bytes(b"preserve existing archive")
        with patch.object(clnch_resource, "clnch_version", "2.3.5"):
            self.run_archive( success=False)
        self.assertEqual(stale_name.read_bytes(), b"preserve existing archive")
        original_library = self.library.read_bytes()
        resource.write_text(source.replace(f'clnch_version = "{clnch_resource.clnch_version}"',
                                           'clnch_version = "2.3"'), encoding="utf-8")
        self.run_build("compile", success=False)
        self.assertEqual(self.library.read_bytes(), original_library)

    def test_document_copies_resources_and_propagates_failed_validation(self):
        version = "2.3.4"
        with (
            patch.object(sys, "argv", ["makefile.py", "dist"]),
            patch.object(clnch_resource, "clnch_version", version),
            patch("subprocess.run"),
        ):
            namespace = runpy.run_path(str(ROOT / "makefile.py"))
        output = self.root / "docs/html/en"
        sources = {"docs/en/index.txt": b"Title\n=====\n\n:Version: {{APP_VERSION}}\n",
                   "docs/en/images/app_icon.png": b"image", "docs/en/commands.md": (
                       b"# Operation Reference\n\n[Editor](#command-editor)\n\n## Command editor\n"
                       b"| Operation | Keys |\n|---|---|\n| Save | Enter |\n"),
                   "docs/en/extensions.md": b"# Python Extensions\n\n```python\npass\n```\n",
                   "docs/en/licenses.md": (ROOT / "docs/en/licenses.md").read_bytes(),
                   "LICENSE.md": b"license",
                   "ckit/LICENSE.md": b"ckit license", "pyauto/LICENSE.md": b"pyauto license",
                   "third_party/doxygen/bin/doxygen.exe": b"tool"}
        for name in ("licenses/craftlaunch_LICENSE.md", "licenses/python_LICENSE.txt", "licenses/expat_LICENSE.txt"):
            sources[name] = (ROOT / name).read_bytes()
        for name, data in sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        package = self.root / "dist/ReCraftLaunch"
        package.mkdir(parents=True)
        runtime = package / "library.zip"
        runtime.write_bytes(b"unchanged runtime")
        settings = self.root / "build/run/x64/Release/settings/custom.py"
        settings.parent.mkdir(parents=True)
        settings.write_bytes(b"unchanged settings")
        with (
            contextlib.chdir(self.root),
            contextlib.redirect_stdout(io.StringIO()),
            patch("subprocess.run") as run,
        ):
            namespace["document_language"]("en")
            self.assertEqual(run.call_args.args[0][-3:], ["tools/check_docs.py", "--lang", "en"])
            self.assertTrue(run.call_args.kwargs["check"])
            conversions = [call.args[0] for call in run.call_args_list
                           if "tools/rst2html_pygments.py" in call.args[0]]
            self.assertEqual([command[-2] for command in conversions],
                             ["docs/obj/en/index.txt", "docs/common/changes.txt", "docs/en/differences.txt",
                              "docs/en/command_json.txt"])
            self.assertTrue(all("--language=en" in command for command in conversions))
            config = (self.root / "docs/obj/en/doxyfile").read_text(encoding="utf-8")
            self.assertIn(f"PROJECT_NUMBER = {version}", config)
            staged_index = (self.root / "docs/obj/en/index.txt").read_text(encoding="utf-8")
            self.assertEqual(staged_index, sources["docs/en/index.txt"].decode().replace(
                "{{APP_VERSION}}", version))
            self.assertIn("OUTPUT_LANGUAGE = English", config)
            self.assertIn("ENABLED_SECTIONS = english", config)
            self.assertIn("MARKDOWN_ID_STYLE = GITHUB", config)
            self.assertIn("INPUT += docs/obj/en/commands.md docs/obj/en/extensions.md docs/obj/en/licenses.md", config)
            self.assertEqual((output / "language.txt").read_text(encoding="utf-8"), "en\n")
            self.assertEqual((output / "images/app_icon.png").read_bytes(), b"image")
            staged = (self.root / "docs/obj/en/commands.md").read_text(encoding="utf-8")
            self.assertEqual(staged, sources["docs/en/commands.md"].decode().replace(
                "# Operation Reference\n", "# Operation Reference {#commands}\n", 1))
            extensions = (self.root / "docs/obj/en/extensions.md").read_text(encoding="utf-8")
            self.assertEqual(extensions, sources["docs/en/extensions.md"].decode().replace(
                "# Python Extensions\n", "# Python Extensions {#extensions}\n", 1))
            licenses = (self.root / "docs/obj/en/licenses.md").read_text(encoding="utf-8")
            self.assertEqual(licenses, sources["docs/en/licenses.md"].decode().replace("\r\n", "\n"))
            for source, name in (("LICENSE.md", "recraftlaunch"),
                                 ("ckit/LICENSE.md", "ckit"), ("pyauto/LICENSE.md", "pyauto")):
                self.assertEqual((self.root / f"docs/obj/en/license_{name}.md").read_bytes(), sources[source])
            for name in ("COMMANDS.md", "README-help.txt", "LICENSE.md", "LICENSE-ckit.md"):
                self.assertFalse((output / name).exists())

            def fail_validation(command, **kwargs):
                if "tools/check_docs.py" in command:
                    raise subprocess.CalledProcessError(1, command)

            run.side_effect = fail_validation
            with self.assertRaises(subprocess.CalledProcessError):
                namespace["document_language"]("en")
        self.assertEqual(runtime.read_bytes(), b"unchanged runtime")
        self.assertEqual(settings.read_bytes(), b"unchanged settings")
        self.assertFalse((package / "docs").exists())

    def test_archive_rejects_corrupt_zip(self):
        with patch.object(sys, "argv", ["makefile.py", "dist"]), patch("subprocess.run"):
            namespace = runpy.run_path(str(ROOT / "makefile.py"))

        def corrupt_archive(filename, items):
            with zipfile.ZipFile(filename, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr("ReCraftLaunch/payload.txt", b"archive corruption probe")
            archive_path = Path(filename)
            data = archive_path.read_bytes().replace(b"archive corruption probe", b"Archive corruption probe")
            archive_path.write_bytes(data)

        with (
            contextlib.chdir(self.root),
            patch.dict(namespace["target_archive"].__globals__,
                       {"check_package_files": lambda package: None, "createZip": corrupt_archive}),
            self.assertRaises((ValueError, zipfile.BadZipFile)),
        ):
            namespace["target_archive"]()

    def test_release_and_all_build_one_distribution_and_archive(self):
        with patch.object(sys, "argv", ["makefile.py", "dist"]), patch("subprocess.run") as run:
            namespace = runpy.run_path(str(ROOT / "makefile.py"))
            run.assert_not_called()
        events = []
        functions = namespace["target_all"].__globals__
        with patch.dict(functions, {"target_dist": lambda: events.append("dist"),
                                    "target_archive": lambda verified=False: events.append(("archive", verified))}):
            namespace["target_release"]()
        self.assertEqual(events, ["dist", ("archive", True)])
        with (
            patch.dict(functions, {"target_dist": Mock(side_effect=ValueError("failed build")),
                                   "target_archive": lambda **kwargs: events.append("unexpected archive")}),
            self.assertRaisesRegex(ValueError, "failed build"),
        ):
            namespace["target_all"]()
        self.assertEqual(events, ["dist", ("archive", True)])


if __name__ == "__main__":
    unittest.main()
