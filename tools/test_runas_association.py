"""Static association resolution and _ra integration; never request UAC or change associations."""
import contextlib
import ctypes
import io
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_argument_strings as support

platform = support.platform


class AssociationTests(unittest.TestCase):
    def setUp(self):
        if hasattr(support, "package"):
            for module in (platform, support.clnch_mainwindow):
                self.assertTrue(module.__file__.startswith(str(support.package / "library.zip")), module.__file__)
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.folder = Path(directory)
        self.document = self.folder / "日本語 some file %param%.txt"
        self.document.touch()
        self.exe = self.folder / "editor app.exe"
        self.exe.touch()

    def resolve(self, command, arguments="", **metadata):
        values = {1: command, 2: str(self.exe), **{int(k): v for k, v in metadata.items()}}
        with patch.object(platform, "_association_string", side_effect=lambda ext, kind: values.get(kind)):
            return platform.resolve_elevated_document(str(self.document), arguments)

    def test_fixed_arguments_quotes_placeholders_and_raw_tail(self):
        for placeholder in ("%1", "%l", "%L"):
            for quoted in (False, True):
                token = '"' + placeholder + '"' if quoted else placeholder
                for raw, argv in support.CASES:
                    for star in (False, True):
                        template = f'"{self.exe}" --fixed "a b" /file={token}' + (" %* --end" if star else "")
                        with self.subTest(template=template, raw=raw):
                            exe, parameters = self.resolve(template, raw)
                            self.assertEqual(exe, str(self.exe))
                            self.assertEqual(platform.split_commandline_args(parameters),
                                             ["--fixed", "a b", "/file=" + str(self.document),
                                              *argv, *(["--end"] if star else [])])
                            self.assertIn(raw, parameters)
                            self.assertIn(' --fixed "a b" /file="' + str(self.document) + '"', parameters)

    def test_unquoted_executable_spaces_environment_and_repeated_document(self):
        with patch.dict(os.environ, RECRAFT_ASSOC_DIR=str(self.folder)):
            command = '%RECRAFT_ASSOC_DIR%\\editor app.exe /fixed "%1" /again="%L"'
            exe, args = self.resolve(command)
            self.assertEqual(exe, str(self.exe))
            self.assertEqual(platform.split_commandline_args(args),
                             ["/fixed", str(self.document), "/again=" + str(self.document)])

    def test_unsupported_placeholders_and_malformed_commands_fail_clearly(self):
        for tail, reason in (("/fixed", "missing document"), ('"%1', "unbalanced"),
                             ('"%1" %2', "placeholder"), ('"%1" %V', "placeholder"),
                             ('"%1" "%*"', "placeholder"), ('"%1" prefix%*', "separate argument"),
                             (r'\%1', "quote escape"),
                             ('"%1" %UNKNOWN_ENV_RECRAFT%', "placeholder")):
            with self.subTest(tail=tail), self.assertRaisesRegex(ValueError, reason):
                self.resolve(f'"{self.exe}" ' + tail)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.resolve('"other.exe" "%1"')

    def test_missing_and_unsupported_associations_do_not_choose_another_app(self):
        with self.assertRaisesRegex(ValueError, "no static EXE"):
            self.resolve(None)
        for kind, value, label in ((7, "[open(%1)]", "DDE"), (8, "", "DDE"),
                                   (17, "{clsid}", "DropTarget"), (18, "", "DelegateExecute"),
                                   (21, "AppX!App", "packaged app")):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, label):
                self.resolve(f'"{self.exe}" "%1"', **{str(kind): value})
        for name in ("explorer.exe", "rundll32.exe", "cmd.exe", "script.cmd", "missing.exe"):
            exe = self.folder / name
            if name != "missing.exe":
                exe.touch()
            with self.subTest(name=name), patch.object(self, "exe", exe), \
                    self.assertRaisesRegex(ValueError, "unsupported EXE"):
                self.resolve(f'"{exe}" "%1"')

    def test_executables_shortcuts_folders_missing_paths_and_urls_keep_existing_route(self):
        for name in ("tool.exe", "tool.cmd", "tool.lnk", "tool.url", "tool.msi", "tool.scr"):
            (self.folder / name).touch()
        for filename in (*map(str, self.folder.iterdir()), str(self.folder),
                         str(self.folder / "missing.txt"), "https://example.invalid/"):
            if filename == str(self.document):
                continue
            with self.subTest(filename=filename), patch.object(platform, "_association_string") as query:
                self.assertEqual(platform.resolve_elevated_document(filename, '  "a b"  '),
                                 (filename, '  "a b"  '))
                query.assert_not_called()

    def test_api_buffer_sizes_flags_missing_and_errors(self):
        calls = []
        value = "x" * 2048
        def query(flags, kind, extension, verb, buffer, size):
            calls.append((flags, kind, extension, verb, buffer is None))
            size = ctypes.cast(size, ctypes.POINTER(wintypes.DWORD))
            if buffer is None:
                size[0] = len(value) + 1
                return 1
            self.assertEqual(size[0], len(value) + 1)
            buffer.value = value
            return 0
        with patch.object(platform, "_AssocQueryStringW", side_effect=query):
            self.assertEqual(platform._association_string(".txt", 1), value)
        self.assertEqual(calls, [(0x520, 1, ".txt", None, True), (0x520, 1, ".txt", None, False)])
        for result in (-2147023741, -2147024894):
            with patch.object(platform, "_AssocQueryStringW", return_value=result):
                self.assertIsNone(platform._association_string(".txt", 1))
        for result in (-2147024891, -2147467261):
            with patch.object(platform, "_AssocQueryStringW", return_value=result), self.assertRaises(OSError):
                platform._association_string(".txt", 1)
        def fail_second(*args):
            ctypes.cast(args[-1], ctypes.POINTER(wintypes.DWORD))[0] = 10
            return 1 if args[-2] is None else -2147467261
        with patch.object(platform, "_AssocQueryStringW", side_effect=fail_second), self.assertRaises(OSError):
            platform._association_string(".txt", 1)

    def test_actual_windows_default_txt_association_and_missing_extension(self):
        command = platform._association_string(".txt", 1)
        executable = platform._association_string(".txt", 2)
        self.assertTrue(command)
        self.assertTrue(executable)
        self.assertIsNone(platform._association_string(".recraft_no_association_20261102", 1))
        # Query the installed default; no registry writes or application launch.
        try:
            with ThreadPoolExecutor(max_workers=1) as worker:
                exe, args = worker.submit(platform.resolve_elevated_document, str(self.document), "").result(5)
        except ValueError as error:
            self.assertIn(str(self.document), str(error))
            print("Installed .txt association is unsupported:", error)
        else:
            self.assertEqual(exe, executable)
            self.assertIn(str(self.document), platform.split_commandline_args(args))
            print("Installed .txt static association resolved:", executable)


class RunAsDocumentTests(unittest.TestCase):
    setUp = support.ArgumentStringTests.setUp
    configure = support.ArgumentStringTests.configure
    enter = support.ArgumentStringTests.enter

    def fixture(self):
        self.configure({})
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        document = folder / "日本語 some file %literal%.txt"
        exe = folder / "editor app.exe"
        document.touch()
        exe.touch()
        self.values = {1: f'"{exe}" --fixed "%1" %*', 2: str(exe)}
        self.enterContext(patch.object(platform, "_association_string",
                                      side_effect=lambda extension, kind: self.values.get(kind)))
        return document, exe

    def test_direct_json_alias_fixed_args_macros_workdir_and_view_mode(self):
        document, exe = self.fixture()
        raw = '  "a b" "" one;two C:\\tail\\  '
        for workdir in ("", str(document.parent / "work")):
            self.configure({"doc": {"target": {"link": str(document), "args": "--json %param%"}},
                            "alias": {"target": {"link": "doc", "args": "--alias %param%"}},
                            "json": {"target": {"link": "_ra", "args": '"%RA_DOC%" --json',
                                                "workdir": workdir, "view_mode": "maximized"}}})
            with patch.dict(os.environ, RA_DOC=str(document)):
                for text, fixed, mode in ((f'_ra;"{document}" ' + raw, "", None),
                                           ("_ra;alias " + raw, "--json --alias ", "normal"),
                                           ("json;" + raw, "--json ", "maximized")):
                    with self.subTest(text=text, workdir=workdir):
                        call = self.enter(text)
                        self.assertEqual(call[0:2], ("runas", str(exe)))
                        self.assertEqual(platform.split_commandline_args(call[2]),
                                         ["--fixed", str(document), *platform.split_commandline_args(fixed + raw)])
                        self.assertTrue(call[2].endswith(raw))
                        self.assertEqual(call[3], workdir if text.startswith("json;") and workdir else str(document.parent))
                        self.assertEqual(call[4], mode)

    def test_queries_run_only_inside_job_after_macro_expansion(self):
        document, exe = self.fixture()
        pending = []
        self.configure({"json": {"target": {"link": "_ra", "args": '"%RA_DOC%"'}}})
        with patch.dict(os.environ, RA_DOC=str(document)), \
                patch.object(support.ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=pending.append)), \
                patch.object(platform, "_association_string", wraps=platform._association_string) as query:
            self.assertTrue(self.launcher.onEnter(self.line, "json", 0))
            query.assert_not_called()
            self.shell.assert_not_called()
            self.assertEqual(len(pending), 1)
            pending[0].job(pending[0])
            query.assert_called()
            self.assertEqual(self.shell.call_args.args[1], str(exe))

    def test_unquoted_document_target(self):
        _document, exe = self.fixture()
        plain = r"Z:\temp\test.txt"
        original = platform.os.path.isfile
        with patch.object(platform.os.path, "isfile", side_effect=lambda path: path == plain or original(path)):
            call = self.enter("_ra;" + plain)
        self.assertEqual(call[:2], ("runas", str(exe)))
        self.assertEqual(platform.split_commandline_args(call[2]), ["--fixed", plain])

    def test_errors_and_cancellation_and_normal_document_launch(self):
        document, exe = self.fixture()
        for error in (ctypes.WinError(1223), ctypes.WinError(5), ctypes.WinError(2)):
            self.shell.side_effect = error
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.enter(f'_ra;"{document}"')
            self.assertEqual(not output.getvalue(), error.winerror == 1223)
        self.shell.side_effect = None
        for metadata in ({}, {18: "{delegate}"}, {1: f'"{exe}" %V', 2: str(exe)}):
            self.values = metadata
            output = io.StringIO()
            self.shell.reset_mock()
            with contextlib.redirect_stdout(output):
                self.assertTrue(self.launcher.onEnter(self.line, f'_ra;"{document}"', 0))
            self.shell.assert_not_called()
            self.assertIn(str(document), output.getvalue())
            self.assertIn(support.clnch_mainwindow.strings.EXECUTE_ERROR, output.getvalue())
        # Normal Shell document opening remains delegated to Windows unchanged.
        with patch.object(platform, "_association_string") as query:
            self.assertEqual(self.enter(str(document))[:3], (None, str(document), ""))
            query.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
