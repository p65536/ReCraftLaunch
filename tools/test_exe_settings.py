"""Executable-local storage selection; native menu/message windows are replaced."""
import ast
import configparser
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_modal_lifecycle import _split_list_result

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_execonfig


class ExeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "reclnch_exe.ini"

    def test_missing_and_unset_default_to_portable_without_creating_file(self):
        self.assertFalse(clnch_execonfig.read(self.root))
        self.assertFalse(self.path.exists())
        for text in ("", "[DATA]\n", "[OTHER]\nvalue = keep\n"):
            self.path.write_text(text, encoding="utf-8")
            self.assertFalse(clnch_execonfig.read(self.root))

    def test_roundtrip_preserves_other_settings(self):
        self.path.write_text("[OTHER]\nvalue = keep\n", encoding="utf-8")
        for value in (True, False):
            clnch_execonfig.write(self.root, value)
            self.assertEqual(clnch_execonfig.read(self.root), value)
            ini = configparser.RawConfigParser()
            ini.read(self.path, encoding="utf-8")
            self.assertEqual(ini["OTHER"]["value"], "keep")
            self.assertEqual(ini["DATA"]["multi_user"], str(int(value)))
        self.assertEqual(list(self.root.glob(".reclnch-exe-*")), [])

    def test_utf8_bom_is_read_and_rewritten_without_bom(self):
        self.path.write_bytes(b"\xef\xbb\xbf[DATA]\r\nmulti_user = 1\r\n")
        self.assertTrue(clnch_execonfig.read(self.root))
        clnch_execonfig.write(self.root, False)
        self.assertEqual(self.path.read_bytes(), b"[DATA]\nmulti_user = 0\n\n")
        self.assertFalse(clnch_execonfig.read(self.root))

    def test_invalid_or_unreadable_file_does_not_silently_change_location(self):
        for value in ("2", "true", ""):
            self.path.write_text(f"[DATA]\nmulti_user = {value}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                clnch_execonfig.read(self.root)
        self.path.write_text("not an INI file", encoding="utf-8")
        with self.assertRaises(configparser.Error):
            clnch_execonfig.read(self.root)
        with patch("builtins.open", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                clnch_execonfig.read(self.root)
            with self.assertRaises(PermissionError):
                clnch_execonfig.write(self.root, True)

    def test_failed_replace_preserves_original_and_cleans_temporary_file(self):
        clnch_execonfig.write(self.root, False)
        original = self.path.read_bytes()
        with (
            patch.object(clnch_execonfig.os, "replace", side_effect=PermissionError("locked")),
            self.assertRaises(PermissionError),
        ):
            clnch_execonfig.write(self.root, True)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".reclnch-exe-*")), [])

    def menu(self, result, fail_write=False):
        self.messages = []
        self.initial = []
        def pop_menu(window, width, height, title, items, initial):
            self.initial.append(initial)
            self.assertEqual(title, "設定の保存先")
            self.assertEqual(items, ["アプリフォルダ", "AppDataフォルダ"])
            return result
        tree = ast.parse((ROOT / "clnch/clnch_configmenu.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "_configDataPath")
        namespace = {"strings": __import__("clnch_strings"), "sys": SimpleNamespace(executable=str(self.root / "reclnch.exe"),
                                           _clnch_app_dir="unused-resource-directory", maxsize=sys.maxsize),
                     "os": clnch_execonfig.os, "clnch_execonfig": clnch_execonfig,
                     "clnch_listwindow": SimpleNamespace(popMenu=pop_menu, _split_list_result=_split_list_result),
                     "clnch_msgbox": SimpleNamespace(MSGBOX_TYPE_OK=0,
                         popMessageBox=lambda *args: self.messages.append(args))}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "storage-menu-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.
        if fail_write:
            with patch.object(clnch_execonfig, "write", side_effect=PermissionError("read only")):
                return namespace["_configDataPath"](None)
        return namespace["_configDataPath"](None)

    def test_menu_cancel_and_reselect_leave_file_untouched(self):
        for result in (-1, 0):
            self.menu(result)
            self.assertFalse(self.path.exists())
            self.assertEqual(self.initial, [0])
            self.assertEqual(self.messages, [])
        clnch_execonfig.write(self.root, True)
        original = self.path.read_bytes()
        for result in (-1, 1):
            self.menu(result)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.initial, [1])

    def test_menu_changes_only_next_start_selection_and_preserves_data(self):
        for folder in (self.root / "settings", self.root / "appdata"):
            folder.mkdir(exist_ok=True)
            for name in ("reclnch.ini", "custom.py", "commands.json"):
                (folder / name).write_bytes((str(folder) + name).encode("utf-8"))
        originals = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        for result in (1, 0):
            self.assertFalse(self.menu(result))
            self.assertEqual(clnch_execonfig.read(self.root), bool(result))
            self.assertIn("ReCraftLaunchを再起動", self.messages[-1][-1])
            for path, data in originals.items():
                self.assertEqual(path.read_bytes(), data)

    def test_menu_reports_write_error_without_replacing_selection(self):
        clnch_execonfig.write(self.root, False)
        original = self.path.read_bytes()
        self.assertFalse(self.menu(1, fail_write=True))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(len(self.messages), 1)
        self.assertIn("エラー", self.messages[0][-2])


if __name__ == "__main__":
    unittest.main()
