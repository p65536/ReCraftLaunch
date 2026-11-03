"""Retained argument contracts with native ckit and isolated GUI substitutes."""
import ast
import json
import re
import unittest
import winreg
from pathlib import Path
from unittest.mock import Mock, call, patch

import test_command_list as command_lists
import test_command_platform as command_platform
import test_gui_drawing as drawing
import test_input_session as input_sessions

ROOT = Path(__file__).resolve().parent.parent
ckit = drawing.ckit
platform = command_platform.platform


class ArgumentContractTests(unittest.TestCase):
    def test_invalid_selection_still_allows_drop_with_live_list_parent(self):
        for result in (None, -1, 100, (-1, 4)):
            for operation in ("drop", "new", "kill", "duplicate"):
                with self.subTest(result=result, operation=operation):
                    fixture = command_lists.CommandListTests()
                    fixture.setUp()
                    try:
                        fixture.write({"tool": {}})
                        files = ["D:/日本語.txt"]
                        def drive(listing, result=result, operation=operation, files=files):
                            listing.result = result
                            if operation == "drop":
                                listing.options["dropfiles_handler"](0, 0, files)
                            else:
                                key, mod = {"new": (45, 0), "kill": (46, 0), "duplicate": (45, 2)}[operation]
                                listing.options["keydown_hook"](key, mod)
                        fixture.drivers = [drive]
                        def edit(name, fixture=fixture, files=files, **options):
                            self.assertIsNone(name)
                            self.assertIs(options["dropped_files"], files)
                            self.assertIs(options["parent_window"], fixture.windows[0])
                            self.assertFalse(fixture.windows[0].destroyed)
                            self.assertTrue(fixture.windows[0].visible)
                            self.assertFalse(fixture.parent.enabled)
                            fixture.parent.activate.assert_not_called()
                        editor = Mock(side_effect=edit)
                        saved = Mock()
                        fixture.module.open_list(fixture.parent, on_edit=editor, on_saved=saved)
                        self.assertEqual(editor.call_count, int(operation == "drop"))
                        saved.assert_not_called()
                        self.assertEqual(json.loads(fixture.path.read_text(encoding="utf-8")), {"tool": {}})
                        fixture.windows[0].getResult.assert_called_once_with()
                        self.assertEqual(len(fixture.windows), 2 if operation == "drop" else 1)
                        for listing in fixture.windows:
                            self.assertTrue(listing.destroyed)
                            listing.destroy.assert_called_once_with()
                        self.assertTrue(fixture.parent.enabled)
                        fixture.parent.activate.assert_called_once_with()
                    finally:
                        fixture.doCleanups()

    def test_mapped_directory_keeps_truth_checks_conversion_and_unresolved_noop(self):
        events = []
        class ChangingPath:
            def __bool__(self):
                events.append("bool")
                return events.count("bool") == 1
            def __fspath__(self):
                events.append("fspath")
                return str(ROOT)
        self.assertIsNone(platform.get_mapped_directory(ChangingPath(), (), "destination"))
        self.assertEqual(events, ["bool", "bool"])
        events.clear()
        self.assertEqual(platform._get_target_dir(ChangingPath()), str(ROOT))
        self.assertEqual(events, ["bool", "fspath"])
        for value in (None, "", b""):
            self.assertIsNone(platform._get_target_dir(value))
            self.assertIsNone(platform.get_mapped_directory(value, (), "destination"))
        destination = "destination"
        self.assertIs(platform.get_mapped_directory(str(ROOT), (str(ROOT),), destination), destination)

    def test_none_text_keeps_undo_redo_and_block_failure_state(self):
        from ckit.ckit_textwidget import UndoInfo
        info = UndoInfo()
        self.assertIsNone(info.old_text)
        self.assertIsNone(info.new_text)
        with patch.object(ckit.TextWidget, "paint"):
            edit = ckit.TextWidget(drawing.Window(), 0, 0, 30, 5)
            self.addCleanup(edit.destroy)
            edit.modifyText(text="abc")
            edit.setSelection(edit.point(0, 0), edit.point(0, 3))
            edit.modifyText(text=None)
            self.assertEqual(edit.doc.lines[0].s, "")
            record = edit.doc.undo_list[-1]
            self.assertIsNone(record.new_text)
            self.assertTrue(edit.undo())
            self.assertEqual(edit.doc.lines[0].s, "abc")
            self.assertTrue(edit.redo())
            self.assertEqual(edit.doc.lines[0].s, "")
            self.assertIs(edit.doc.undo_list[-1], record)
            edit.setSelection(edit.point(0, 0), edit.point(0, 0), block_mode=True)
            before = (list(edit.doc.undo_list), list(edit.doc.redo_list), edit.doc.modcount)
            with self.assertRaises(AttributeError) as raised:
                edit.modifyText(text=None)
            self.assertEqual(raised.exception.args, ("'NoneType' object has no attribute 'splitlines'",))
            self.assertEqual(raised.exception.name, "splitlines")
            self.assertIsNone(raised.exception.obj)
            self.assertEqual((edit.doc.undo_list, edit.doc.redo_list, edit.doc.modcount), before)
            edit.doc.readonly = True
            with patch.object(edit, "setMessage") as message:
                edit.modifyText(text=None)
            message.assert_called_once()

    def test_prepared_candidates_keep_failure_and_clear_timing(self):
        fixture = drawing.EditCandidateTests()
        fixture.setUp()
        try:
            edit = fixture.edit(lambda info: (["alpha"], 0))
            window = fixture.created[0]
            self.assertIs(edit.list_window, window)
            with self.assertRaises(TypeError) as raised:
                edit.popupList()
            self.assertEqual(raised.exception.args, ("cannot unpack non-iterable NoneType object",))
            window.enable.assert_not_called()
            window.setItems.assert_not_called()
            self.assertIsNone(edit.list_window_prepared_info)
            edit.popupListPrepare(complete=False)
            prepared = edit.list_window_prepared_info
            with patch.object(edit, "alternateText", side_effect=RuntimeError("alternate")), self.assertRaises(RuntimeError):
                edit.popupList()
            self.assertIs(edit.list_window_prepared_info, prepared)
            self.assertIs(edit.list_window, window)
            edit.popupList()
            self.assertIsNone(edit.list_window_prepared_info)
            edit.popupListPrepare(complete=False)
            edit.candidate_handler = None
            edit.popupList()
            self.assertIsNone(edit.list_window_prepared_info)
        finally:
            fixture.doCleanups()

    def test_integer_completion_flags_reach_session_and_widget_unchanged(self):
        for value in (False, True, 0, 1, -7, 23):
            with self.subTest(value=value):
                window = input_sessions.FakeWindow()
                with patch.object(input_sessions.sessions.ckit, "EditWidget", input_sessions.FakeEdit):
                    def loop(check, window=window, value=value):
                        self.assertIs(window.edits[-1].options["auto_complete"], value)
                    window.loop = loop
                    window.commandLine("", auto_complete=value)
                with patch.object(ckit.EditWidget, "paint"):
                    edit = ckit.EditWidget(drawing.Window(), 0, 0, 30, 1, "", auto_complete=value)
                    try:
                        self.assertIs(edit.getAutoComplete(), value)
                    finally:
                        edit.destroy()

    def test_regex_conditions_keep_compilation_order_and_registration(self):
        tree = ast.parse((ROOT / "pyauto/sample/keymap/keymap_hook.py").read_text(encoding="utf-8"))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "registorKeymap")
        registry = []
        namespace = {"re": re, "_keymap_list": registry}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "keymap-registration", "exec"), namespace)  # noqa: S102  # Extract registration without installing the global input hook.
        register = namespace["registorKeymap"]
        constructor = object()
        register((None, None, None), constructor)
        self.assertEqual(registry, [((None, None, None), constructor)])
        with patch.object(re, "compile", wraps=re.compile) as compile_pattern:
            register(("first", None, "third"), constructor)
        self.assertEqual(compile_pattern.call_args_list, [call("first"), call("third")])
        self.assertEqual([pattern.pattern if pattern else None for pattern in registry[0][0]], ["first", None, "third"])
        self.assertIs(registry[0][1], constructor)
        before = registry.copy()
        with self.assertRaises(re.PatternError):
            register(("valid", "[", "later"), constructor)
        self.assertEqual(registry, before)

    def test_registry_default_names_match_for_present_and_missing_values(self):
        for root, subkey in ((winreg.HKEY_CLASSES_ROOT, r"exefile\shell\open\command"),
                             (winreg.HKEY_CURRENT_USER, "Software")):
            with self.subTest(key=subkey), winreg.OpenKey(root, subkey) as key:
                results = []
                for name in (None, ""):
                    try:
                        results.append(("value", Mock(wraps=winreg.QueryValueEx)(key, name)))
                    except OSError as error:
                        results.append((type(error), error.args, error.winerror))
                self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
