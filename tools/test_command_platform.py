"""Windows parsing and OS lookup; no programs are launched or registry keys written."""
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "clnch"))
import clnch_commandplatform as platform


class CommandPlatformTests(unittest.TestCase):
    def test_target_directory_requires_a_real_file_or_directory(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd() / "build") as directory:
            folder = Path(directory)
            target = folder / "tool.exe"
            target.touch()
            for path in (str(target), str(folder), os.path.relpath(target), os.path.relpath(folder),
                         '"' + str(target) + '"', '"' + str(folder) + '\\"'):
                with self.subTest(path=path):
                    self.assertEqual(platform._get_target_dir(path), directory)
            self.assertEqual(platform._get_target_dir("tool.exe", directory), directory)
            self.assertEqual(platform._get_target_dir(os.fsencode(target)), os.fsencode(directory))
            with patch.object(platform, "resolve_system_executable", return_value=None):
                for path in (str(folder / "missing.exe"), "missing.exe", "missing/sub.exe", "https://example.org/"):
                    with self.subTest(path=path):
                        self.assertIsNone(platform._get_target_dir(path))
                        self.assertIsNone(platform.get_mapped_directory(path, (directory,), directory))

    def test_target_directory_reuses_os_lookup_and_checks_the_result(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tool.exe"
            target.touch()
            with patch.object(platform, "resolve_system_executable", return_value=str(target)) as resolve:
                self.assertEqual(platform._get_target_dir("tool.exe"), directory)
                self.assertEqual(platform.get_mapped_directory("tool.exe", (directory,), "mapped"), "mapped")
            self.assertEqual(resolve.call_count, 2)
            target.unlink()
            with patch.object(platform, "resolve_system_executable", return_value=str(target)):
                self.assertIsNone(platform._get_target_dir("tool.exe"))

    def test_native_windows_argument_parsing_preserves_quotes_empty_and_unicode(self):
        args = ["head", "", "a b", 'a"b', "日本語", "C:\\two words\\", "one;two"]
        self.assertEqual(platform.split_commandline_args(subprocess.list2cmdline(args)), args)
        self.assertEqual(platform.split_commandline_args('"a b.txt" --fixed'), ["a b.txt", "--fixed"])
        self.assertEqual(platform.split_commandline_args(""), [])

    def test_parser_releases_native_buffer_and_propagates_failure(self):
        with patch.object(platform, "_LocalFree", wraps=platform._LocalFree) as free:
            self.assertEqual(platform.split_commandline_args("tool arg"), ["tool", "arg"])
        free.assert_called_once()
        with (patch.object(platform, "_CommandLineToArgvW", return_value=None),
              patch.object(platform, "_LocalFree") as free,
              self.assertRaises(OSError)):
            platform.split_commandline_args("tool")
        free.assert_not_called()

    def test_actual_path_and_pathext_lookup_precedes_app_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "recraft_lookup_test.CMD"
            executable.touch()
            with (patch.dict(os.environ, PATH=directory, PATHEXT=".CMD;.EXE"),
                  patch.object(platform, "_resolve_app_path") as app_paths):
                self.assertEqual(platform.resolve_system_executable("recraft_lookup_test"), str(executable))
            app_paths.assert_not_called()

    def test_app_paths_is_fallback_and_missing_name_is_unhandled(self):
        with (patch.object(platform.shutil, "which", return_value=None) as which,
              patch.object(platform, "_resolve_app_path", return_value="D:/app.exe") as app_paths):
            self.assertEqual(platform.resolve_system_executable("app"), "D:/app.exe")
        which.assert_called_once_with("app")
        app_paths.assert_called_once_with("app")
        with (patch.object(platform.shutil, "which", return_value=None),
              patch.object(platform, "_resolve_app_path", return_value=None)):
            self.assertIsNone(platform.resolve_system_executable("missing"))

    def test_drive_paths_and_urls_keep_existing_dispatch_boundary(self):
        with (patch.object(platform.shutil, "which") as which,
              patch.object(platform, "_resolve_app_path") as app_paths):
            self.assertEqual(platform.resolve_system_executable("c:"), "C:\\")
            for name in ("D:/tool.exe", "relative/tool.exe", "https://example.org/"):
                self.assertIsNone(platform.resolve_system_executable(name))
        which.assert_not_called()
        app_paths.assert_not_called()

    def test_missing_drive_root_is_not_resolved_or_scheduled(self):
        with (patch.object(platform.os.path, "isdir", return_value=False) as isdir,
              patch.object(platform.shutil, "which") as which,
              patch.object(platform, "_resolve_app_path") as app_paths):
            self.assertIsNone(platform.resolve_system_executable("z:"))
            isdir.assert_called_once_with("Z:\\")
            line = SimpleNamespace(planCommand=Mock(), quit=Mock())
            self.assertFalse(platform.SystemExecutableCommandline(None).onEnter(line, "z:;tail", 0))
            line.planCommand.assert_not_called()
            line.quit.assert_not_called()
            which.assert_not_called()
            app_paths.assert_not_called()

    def test_app_paths_searches_user_then_machine_and_all_views(self):
        reg = platform.winreg
        attempts = []
        destination = (reg.HKEY_LOCAL_MACHINE, reg.KEY_WOW64_32KEY)
        def open_key(root, key, reserved, access):
            view = access & ~reg.KEY_READ
            attempts.append((root, view, key))
            if (root, view) != destination:
                raise FileNotFoundError(key)
            return nullcontext("found")
        with (patch.object(reg, "OpenKey", side_effect=open_key),
              patch.object(reg, "QueryValueEx", return_value=(' "%RECRAFT_LOOKUP%/app.exe" ', reg.REG_EXPAND_SZ)),
              patch.dict(os.environ, RECRAFT_LOOKUP="D:/Apps"),
              patch.object(platform.os.path, "isfile", return_value=True) as isfile):
            self.assertEqual(platform._resolve_app_path("app"), "D:/Apps/app.exe")
        expected = [(root, view, platform._APP_PATHS_KEY + "\\app.exe")
                    for root in (reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE)
                    for view in (0, reg.KEY_WOW64_64KEY, reg.KEY_WOW64_32KEY)]
        self.assertEqual(attempts, expected)
        isfile.assert_called_once_with("D:/Apps/app.exe")

    def test_app_paths_user_priority_extension_and_invalid_values(self):
        reg = platform.winreg
        with (patch.object(reg, "OpenKey", side_effect=lambda *args: nullcontext("key")) as opened,
              patch.object(reg, "QueryValueEx", return_value=("user.exe", reg.REG_SZ)),
              patch.object(platform.os.path, "isfile", return_value=True)):
            self.assertEqual(platform._resolve_app_path("app.exe"), "user.exe")
        opened.assert_called_once_with(reg.HKEY_CURRENT_USER, platform._APP_PATHS_KEY + "\\app.exe", 0, reg.KEY_READ)
        with (patch.object(reg, "OpenKey", side_effect=lambda *args: nullcontext("key")),
              patch.object(reg, "QueryValueEx", side_effect=[(1, 0), ("", 0)] + [("missing.exe", 0)] * 4),
              patch.object(platform.os.path, "isfile", return_value=False)):
            self.assertIsNone(platform._resolve_app_path("app"))

    def test_commandline_protocol_preserves_modifiers_text_and_semicolons(self):
        window = SimpleNamespace(ShellExecuteCommand=Mock(return_value="command"))
        adapter = platform.SystemExecutableCommandline(window)
        commandline = SimpleNamespace(planCommand=Mock(), quit=Mock())
        text = ' app ;"a b" one;two'
        with patch.object(platform, "resolve_system_executable", return_value="app.exe") as resolve:
            self.assertTrue(adapter.onEnter(commandline, text, 6))
        resolve.assert_called_once_with("app")
        window.ShellExecuteCommand.assert_called_once_with(None, "app.exe", "", "")
        command, info, original = commandline.planCommand.call_args.args
        self.assertEqual((command, info.args, info.mod, original), ("command", ["a b", "one;two"], 6, text))
        commandline.quit.assert_called_once()
        self.assertEqual(adapter.onCandidate(None), [])
        self.assertIsNone(adapter.onStatusString(text))
        commandline.planCommand.reset_mock()
        commandline.quit.reset_mock()
        with patch.object(platform, "resolve_system_executable", return_value=None):
            self.assertFalse(adapter.onEnter(commandline, "missing", 0))
            self.assertFalse(adapter.onEnter(commandline, " ;arg", 0))
        commandline.planCommand.assert_not_called()
        commandline.quit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
