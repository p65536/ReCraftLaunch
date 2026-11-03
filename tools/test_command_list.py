"""Command-list orchestration and failure checks with GUI windows replaced."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_modal_lifecycle import (
    _cleanup_on_exit,
    _modal_dialog_scope,
    _require_data_path,
    _split_list_result,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))

import clnch_cmdstore as store


class CommandListTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name, "commands.json")
        self.events, self.windows = [], []
        self.drivers = []
        self.parent = SimpleNamespace(
            centerOfWindowInPixel=lambda: (100, 100),
            isEnabled=lambda: self.parent.enabled, enabled=True,
            enable=Mock(side_effect=lambda enabled: (setattr(self.parent, "enabled", enabled), self.events.append(("enable", enabled)))),
            activate=Mock(side_effect=lambda: self.events.append("activate")),
        )
        modules = {
            "ckit": SimpleNamespace(dataPath=lambda: self.temp.name,
                VK_DELETE=46, VK_INSERT=45, VK_E=69, MODKEY_CTRL=2),
            "clnch_listwindow": SimpleNamespace(ListWindow=object, _split_list_result=_split_list_result),
            "clnch_isearch": SimpleNamespace(),
            "clnch_ini": SimpleNamespace(getint=lambda section, key, default: default),
            "clnch_misc": SimpleNamespace(_require_data_path=_require_data_path, adjustWindowPosition=Mock(), _modal_dialog_scope=_modal_dialog_scope),
            "clnch_msgbox": SimpleNamespace(MSGBOX_TYPE_OK=0, MSGBOX_TYPE_YESNO=1,
                MSGBOX_RESULT_YES=2, popMessageBox=Mock(return_value=2)),
        }
        modules["ckit.ckit_misc"] = SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit)
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("command_list_test", ROOT / "clnch/clnch_cmdlist.py")
            assert spec is not None and spec.loader is not None
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.module.CommandListWindow = self.create_window

    def create_window(self, *args, **options):
        index = len(self.windows)
        listing = SimpleNamespace(items=args[9], options=options, isearch=None,
            result=options["initial_select"], visible=False, destroyed=False)
        def show(visible):
            listing.visible = visible
            self.events.append(("show", visible))
        def destroy():
            listing.destroyed = True
            self.events.append("destroy")
        def loop():
            self.events.append("loop")
            if index < len(self.drivers):
                self.drivers[index](listing)
            else:
                listing.result = -1
        listing.show = Mock(side_effect=show)
        listing.destroy = Mock(side_effect=destroy)
        listing.quit = Mock()
        listing.messageLoop = Mock(side_effect=loop)
        listing.getResult = Mock(side_effect=lambda: listing.result)
        self.windows.append(listing)
        return listing

    def write(self, data):
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.path.read_bytes()

    def operation(self, key, vk=None, mod=0):
        def drive(listing):
            listing.result = next(i for i, item in enumerate(listing.items) if item[1] == key)
            if vk is not None:
                self.assertTrue(listing.options["keydown_hook"](vk, mod))
                listing.quit.assert_called_once_with()
        return drive

    def selected(self, index):
        listing = self.windows[index]
        return listing.items[listing.options["initial_select"]][1]

    def test_missing_and_empty_store_show_blank_entry_without_writing(self):
        for exists in (False, True):
            with self.subTest(exists=exists):
                if exists:
                    self.write({})
                before = self.path.read_bytes() if exists else None
                with patch.object(self.module, "save_commands") as save:
                    self.module.open_list(self.parent)
                self.assertEqual(self.windows[-1].items, [(self.module.EMPTY_LABEL, "")])
                self.assertEqual(self.path.read_bytes() if self.path.exists() else None, before)
                save.assert_not_called()

    def test_duplicate_json_names_report_load_error_before_list_or_save(self):
        for second in ("Tool", "tool"):
            with self.subTest(second=second):
                self.path.write_text('{"Tool": {"target": {"link": "first.exe"}}, '
                                     '"' + second + '": {"target": {"link": "last.exe"}}}', encoding="utf-8")
                before = self.path.read_bytes()
                on_edit, on_saved = Mock(), Mock()
                with patch.object(self.module, "save_commands") as save:
                    self.module.open_list(self.parent, on_saved=on_saved, on_edit=on_edit)
                save.assert_not_called()
                on_edit.assert_not_called()
                on_saved.assert_not_called()
                error = self.module.strings.COMMAND_NAME_DUPLICATE.format(first="Tool", second=second)
                self.module.clnch_msgbox.popMessageBox.assert_called_with(self.parent, 0,
                    self.module.strings.ERROR_TITLE, self.module.strings.COMMAND_LOAD_ERROR.format(error=error))
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.windows, [])
                self.parent.enable.assert_not_called()

    def test_load_and_error_notification_failures_never_create_or_disable_a_list(self):
        before = self.write({"a": {}})
        for error in (OSError("read failed"), ValueError("invalid json")):
            with self.subTest(error=error), patch.object(self.module, "load_commands", side_effect=error):
                self.module.open_list(self.parent)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.windows, [])
        self.parent.enable.assert_not_called()
        popup = self.module.clnch_msgbox.popMessageBox
        self.assertEqual(popup.call_count, 2)
        popup.side_effect = RuntimeError("popup failed")
        with patch.object(self.module, "load_commands", side_effect=OSError("read failed")), \
             self.assertRaisesRegex(RuntimeError, "popup failed"):
            self.module.open_list(self.parent)

    def test_item_order_preserves_names_and_uses_case_insensitive_sort(self):
        data = {name: {} for name in ("z", "A", "b", "日本語", "")}
        self.assertEqual([key for _, key in self.module._command_items(data)], ["", "A", "b", "z", "日本語"])
        self.assertEqual(list(data), ["z", "A", "b", "日本語", ""])

    def test_existing_edit_handoff_runs_disabled_before_cleanup_and_keeps_saved_selection(self):
        self.write({"a": {}, "tool": {}})
        self.drivers = [self.operation("tool", 69, 2)]
        def edit(name, parent_window):
            self.assertEqual(name, "tool")
            self.assertEqual(self.events[-2:], [("enable", False), "loop"])
            self.assertTrue(self.windows[0].visible)
            self.assertFalse(self.windows[0].destroyed)
            self.assertIs(parent_window, self.windows[0])
            self.assertTrue(self.windows[0].visible)
            self.write({"": {}, "a": {}})
            return ""
        on_saved = Mock()
        self.module.open_list(self.parent, on_edit=edit, on_saved=on_saved)
        self.assertEqual(self.selected(1), "")
        self.assertEqual(self.events[:5], [("show", True), ("enable", False), "loop", ("show", True), "destroy"])
        self.assertEqual(self.events[-2:], [("enable", True), "activate"])
        self.parent.activate.assert_called_once_with()
        on_saved.assert_not_called()

    def test_editor_return_keeps_old_list_until_replacement_is_shown(self):
        self.write({"tool": {}})
        self.drivers = [self.operation("tool")]
        original_create = self.create_window
        def create(*args, **options):
            previous = self.windows[-1] if self.windows else None
            if previous:
                self.assertFalse(previous.destroyed)
                self.assertTrue(previous.visible)
            listing = original_create(*args, **options)
            show = listing.show
            def shown(visible):
                if previous:
                    self.assertFalse(previous.destroyed)
                    self.assertTrue(previous.visible)
                show(visible)
            listing.show = Mock(side_effect=shown)
            destroy = listing.destroy
            def retired():
                if listing is self.windows[0]:
                    self.assertEqual(len(self.windows), 2)
                    self.assertTrue(self.windows[1].visible)
                destroy()
            listing.destroy = Mock(side_effect=retired)
            return listing
        self.module.CommandListWindow = create
        def edit(name, parent_window):
            self.write({"renamed": {}})
            return "renamed"
        self.module.open_list(self.parent, on_edit=edit)
        self.assertEqual(self.selected(1), "renamed")
        self.assertTrue(all(listing.destroyed for listing in self.windows))
        for listing in self.windows:
            listing.destroy.assert_called_once_with()
        self.parent.activate.assert_called_once_with()

    def test_replacement_failures_release_both_lists_and_restore_parent(self):
        for stage in ("load", "create", "position", "show", "retire"):
            with self.subTest(stage=stage):
                self.setUp()
                self.write({"tool": {}})
                self.drivers = [self.operation("tool")]
                original_create = self.create_window
                def failed(*args, **kwargs):
                    raise RuntimeError("replacement")
                def create(*args, stage=stage, original_create=original_create, **options):
                    if self.windows and stage == "create":
                        failed()
                    listing = original_create(*args, **options)
                    if len(self.windows) == 2:
                        if stage == "position":
                            self.module.clnch_misc.adjustWindowPosition.side_effect = failed
                        elif stage == "show":
                            listing.show.side_effect = failed
                    if len(self.windows) == 1 and stage == "retire":
                        destroy = listing.destroy
                        def retired():
                            destroy()
                            failed()
                        listing.destroy = Mock(side_effect=retired)
                    return listing
                def edit(name, parent_window, stage=stage):
                    self.assertFalse(parent_window.destroyed)
                    if stage == "load":
                        self.module.load_commands = Mock(side_effect=OSError("reload"))
                self.module.CommandListWindow = create
                if stage == "load":
                    self.module.open_list(self.parent, on_edit=edit)
                else:
                    with self.assertRaisesRegex(RuntimeError, "replacement"):
                        self.module.open_list(self.parent, on_edit=edit)
                self.assertTrue(self.parent.enabled)
                self.parent.activate.assert_called_once_with()
                self.assertTrue(all(listing.destroyed for listing in self.windows))
                for listing in self.windows:
                    listing.destroy.assert_called_once_with()

    def test_modifier_tuple_keeps_edit_handoff_and_single_virtual_result_call(self):
        self.write({"a": {}, "tool": {}})
        def choose(listing):
            self.operation("tool", 69, 2)(listing)
            listing.result = (listing.result, 4)
        self.drivers = [choose]
        def edit(name, parent_window):
            self.assertEqual(name, "tool")
            self.assertFalse(self.windows[0].destroyed)
            self.windows[0].getResult.assert_called_once_with()
            self.assertIs(parent_window, self.windows[0])
        self.module.open_list(self.parent, on_edit=edit)
        self.assertEqual(self.selected(1), "tool")
        self.assertTrue(all(listing.destroyed for listing in self.windows))

    def test_new_and_drop_keep_list_parent_alive_and_cancel_keeps_selection(self):
        self.write({"a": {}, "tool": {}})
        files = ["D:/日本語.txt", "D:/two.txt"]
        def drop(listing):
            self.operation("tool")(listing)
            listing.options["dropfiles_handler"](0, 0, [])
            listing.quit.assert_not_called()
            listing.isearch = object()
            listing.options["dropfiles_handler"](0, 0, files)
            listing.quit.assert_not_called()
            listing.isearch = None
            listing.options["dropfiles_handler"](0, 0, files)
        self.drivers = [self.operation("tool", 45), drop]
        edits = []
        def edit(name, **options):
            self.assertIsNone(name)
            self.assertFalse(self.windows[-1].destroyed)
            self.assertTrue(self.windows[-1].visible)
            self.assertFalse(self.parent.enabled)
            self.assertIs(options.pop("parent_window"), self.windows[-1])
            edits.append(options)
        self.module.open_list(self.parent, on_edit=edit)
        self.assertEqual(edits, [{}, {"dropped_files": files}])
        self.assertEqual([self.selected(i) for i in (1, 2)], ["tool", "tool"])

    def test_save_failure_preserves_snapshot_selection_and_allows_retry_in_same_list(self):
        for vk, mod, expected in ((46, 0, "z"), (45, 2, "tool_copy_1")):
            with self.subTest(vk=vk):
                self.windows.clear()
                self.write({"a": {}, "tool": {}, "z": {}})
                snapshot = store.load_commands(self.path)
                self.drivers = [self.operation("tool", vk, mod)] * 2
                original_save = store.save_commands
                attempts = []
                def save(path, candidate, attempts=attempts, snapshot=snapshot, original_save=original_save):
                    attempts.append(candidate)
                    self.assertIn("tool", snapshot)
                    self.assertNotIn("tool_copy_1", snapshot)
                    if len(attempts) == 1:
                        raise OSError("write failed")
                    return original_save(path, candidate)
                saved = Mock()
                with patch.object(self.module, "load_commands", wraps=store.load_commands) as load, \
                     patch.object(self.module, "save_commands", side_effect=save):
                    load.side_effect = lambda *args, snapshot=snapshot, attempts=attempts, **kwargs: (
                        snapshot if not attempts else store.load_commands(*args, **kwargs))
                    self.module.open_list(self.parent, on_saved=saved)
                self.assertEqual(self.selected(1), "tool")
                self.assertEqual(self.selected(2), expected)
                self.assertEqual(len(attempts), 2)
                saved.assert_called_once_with()
                self.assertEqual(set(snapshot), {"a", "tool", "z"})

    def test_callback_failure_is_reported_as_saved_and_preserves_committed_selection(self):
        for vk, mod, expected in ((46, 0, "z"), (45, 2, "tool_copy_1")):
            with self.subTest(vk=vk):
                self.windows.clear()
                self.write({"a": {}, "tool": {}, "z": {}})
                self.drivers = [self.operation("tool", vk, mod)]
                def callback(vk=vk):
                    self.assertTrue(self.windows[-1].destroyed)
                    data = store.load_commands(self.path)
                    self.assertEqual("tool" in data, vk != 46)
                    raise RuntimeError("reload failed")
                saved = Mock(side_effect=callback)
                self.module.open_list(self.parent, on_saved=saved)
                saved.assert_called_once_with()
                self.assertEqual(self.selected(1), expected)
                self.assertEqual(self.module.clnch_msgbox.popMessageBox.call_args.args[3],
                    self.module.strings.COMMAND_APPLY_ERROR.format(error="reload failed"))

    def test_delete_cancel_blank_and_last_command(self):
        self.write({"tool": {}})
        self.drivers = [self.operation("tool", 46), self.operation("", 46), self.operation("tool", 46)]
        with patch.object(self.module, "_confirm_delete", side_effect=[False, True]) as confirm:
            saved = Mock()
            self.module.open_list(self.parent, on_saved=saved)
        self.assertEqual(confirm.call_count, 2)
        self.assertEqual(self.windows[3].items, [(self.module.EMPTY_LABEL, "")])
        self.assertEqual(store.load_commands(self.path), {})
        saved.assert_called_once_with()

    def test_invalid_names_remain_visible_and_deletable_but_cannot_be_duplicated(self):
        before = self.write({"bad;one": {}, "bad two": {}, "bad\tthree": {}, "bad　four": {}, "good": {}})
        saved = Mock()
        self.drivers = [self.operation(name, 45, 2) for name in ("bad;one", "bad two", "bad\tthree", "bad　four")]
        self.module.open_list(self.parent, on_saved=saved)
        self.assertEqual(self.path.read_bytes(), before)
        saved.assert_not_called()
        self.assertEqual(self.selected(1), "bad;one")
        self.assertEqual(self.module.clnch_msgbox.popMessageBox.call_args.args[2:],
            (self.module.strings.ERROR_INPUT_TITLE,
             self.module.strings.COMMAND_NAME_ERROR.format(name="bad　four")))
        self.windows.clear()
        self.drivers = [self.operation(name, 46) for name in ("bad;one", "bad two", "bad\tthree", "bad　four")]
        with patch.object(self.module, "_confirm_delete", return_value=True):
            self.module.open_list(self.parent, on_saved=saved)
        self.assertEqual(saved.call_count, 4)
        self.assertEqual(store.load_commands(self.path), {"good": {}})

    def test_invalid_results_and_absent_editor_never_save(self):
        self.write({"tool": {}})
        for result in (None, -1, 999):
            with self.subTest(result=result):
                self.windows.clear()
                def invalid(listing):
                    listing.result = result  # noqa: B023  # Executed during this iteration.
                    listing.options["keydown_hook"](46, 0)
                self.drivers = [invalid]
                with patch.object(self.module, "save_commands") as save:
                    self.module.open_list(self.parent)
                save.assert_not_called()
        for vk, mod in ((None, 0), (69, 2), (45, 0)):
            self.windows.clear()
            self.drivers = [self.operation("tool", vk, mod)]
            self.module.open_list(self.parent)
            self.assertEqual(self.selected(1), "tool")

    def test_cancelled_result_never_edits_or_saves_highlighted_command(self):
        before = self.write({"tool": {"target": {"link": "tool.exe"}}})
        for result in (-1, (-1, 8)):
            with self.subTest(result=result):
                self.windows.clear()
                def cancelled(listing):
                    listing.result = result  # noqa: B023  # The modal driver completes during this iteration.
                self.drivers = [cancelled]
                edit, saved = Mock(), Mock()
                with patch.object(self.module, "save_commands") as save:
                    self.module.open_list(self.parent, on_edit=edit, on_saved=saved)
                edit.assert_not_called()
                saved.assert_not_called()
                save.assert_not_called()
                self.assertEqual(self.path.read_bytes(), before)
                self.assertTrue(self.parent.enabled)
                self.windows[0].destroy.assert_called_once_with()

    def test_window_failure_matrix_always_attempts_remaining_cleanup(self):
        for stage in ("position", "show", "disable", "loop", "result", "edit",
                      "enable", "activate", "destroy"):
            with self.subTest(stage=stage):
                self.windows.clear()
                self.events.clear()
                self.parent.enable.reset_mock(side_effect=True)
                self.parent.activate.reset_mock(side_effect=True)
                self.parent.enabled = True
                self.parent.enable.side_effect = lambda enabled: (setattr(self.parent, "enabled", enabled), self.events.append(("enable", enabled)))
                self.parent.activate.side_effect = lambda: self.events.append("activate")
                error = RuntimeError(stage)
                original_create = self.create_window
                def create(*args, original_create=original_create, **kwargs):
                    listing = original_create(*args, **kwargs)
                    method = {"show": "show", "loop": "messageLoop", "result": "getResult",
                              "destroy": "destroy"}.get(stage)  # noqa: B023  # Executed during this iteration.
                    if method:
                        getattr(listing, method).side_effect = error  # noqa: B023  # Executed during this iteration.
                    return listing
                def enable(enabled):
                    self.parent.enabled = enabled
                    self.events.append(("enable", enabled))
                    if enabled == (stage == "enable"):  # noqa: B023  # Executed during this iteration.
                        raise error  # noqa: B023  # Executed during this iteration.
                if stage in ("enable", "disable"):
                    self.parent.enable.side_effect = enable
                if stage == "activate":
                    self.parent.activate.side_effect = error
                def edit(key, parent_window):
                    self.assertIs(parent_window, self.windows[-1])
                    raise error  # noqa: B023  # Executed during this iteration.
                adjust = self.module.clnch_misc.adjustWindowPosition
                adjust.side_effect = error if stage == "position" else None
                self.module.CommandListWindow = create
                self.drivers = [self.operation("")]
                with self.assertRaisesRegex(RuntimeError, stage):
                    self.module.open_list(self.parent, on_edit=edit if stage == "edit" else None)
                self.parent.enable.assert_called_with(True)
                self.parent.activate.assert_called_once_with()
                self.windows[0].destroy.assert_called_once_with()

    def test_creation_failure_leaves_parent_untouched(self):
        self.module.CommandListWindow = Mock(side_effect=RuntimeError("create"))
        with self.assertRaisesRegex(RuntimeError, "create"):
            self.module.open_list(self.parent)
        self.parent.enable.assert_not_called()
        self.parent.activate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
