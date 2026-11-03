"""Candidate generations and keymap sequences without installing input hooks."""
import gc
import runpy
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_gui_drawing as drawing

from ckit import ckit_textwidget, ckit_textwindow, ckit_widget

ROOT = Path(__file__).resolve().parent.parent


class CandidateReuseTests(unittest.TestCase):
    def test_reused_window_uses_current_base_for_selection_undo_and_redo(self):
        for first_length, second_length in ((40, 50), (50, 40)):
            with self.subTest(first=first_length, second=second_length):
                fixture = drawing.EditCandidateTests()
                fixture.setUp()
                try:
                    edit = fixture.edit(lambda info: (["alpha", "alpine"], info.text.rfind("\\") + 1))
                    first = "C:\\" + "A" * first_length + "\\a"
                    second = "C:\\" + "B" * second_length + "\\a"
                    edit.setText(first)
                    edit.setSelection([len(first), len(first)])
                    edit.makeVisible(len(first))
                    edit.popupListPrepare(complete=False)
                    edit.popupList()
                    fixture.window.delayed.pop()[0]()
                    old = fixture.created[-1]
                    old_pos = edit.list_window_possize_info
                    edit.setText(second)
                    edit.setSelection([len(second), len(second)])
                    edit.makeVisible(len(second))
                    edit.popupListPrepare(complete=False)
                    base = second.rfind("\\") + 1
                    edit.popupList()
                    self.assertIs(edit.list_window, old)
                    self.assertIs(edit.list_window_possize_info, old_pos)
                    self.assertEqual(len(fixture.created), 2)
                    self.assertFalse(fixture.window.delayed)
                    self.assertEqual(edit.list_window_base_len, base)
                    self.assertIsNone(edit.list_window_prepared_info)
                    edit.onListSelChange(0, "alpha")
                    expected = second[:base] + "alpha"
                    self.assertEqual(edit.getText(), expected)
                    self.assertEqual(edit.getSelection(), [len(second), len(expected)])
                    edit.undo()
                    self.assertEqual(edit.getText(), second)
                    self.assertEqual(edit.getSelection(), [len(second), len(second)])
                    edit.redo()
                    self.assertEqual(edit.getText(), expected)
                    self.assertEqual(edit.getSelection(), [len(expected), len(expected)])
                finally:
                    fixture.doCleanups()

    def test_reused_window_item_failure_restores_base_and_retains_preparation(self):
        for first_length, second_length in ((40, 50), (50, 40)):
            for partial in (False, True):
                for error_type in (RuntimeError, KeyboardInterrupt, SystemExit):
                    with self.subTest(first=first_length, second=second_length, partial=partial, error=error_type):
                        fixture = drawing.EditCandidateTests()
                        fixture.setUp()
                        try:
                            edit = fixture.edit(lambda info: (["alpha", "alpine"], info.text.rfind("\\") + 1))
                            first = "C:\\" + "A" * first_length + "\\a"
                            second = "C:\\" + "B" * second_length + "\\a"
                            edit.setText(first)
                            edit.setSelection([len(first), len(first)])
                            edit.makeVisible(len(first))
                            edit.popupListPrepare(complete=False)
                            edit.popupList()
                            fixture.window.delayed.pop()[0]()
                            old = fixture.created[-1]
                            old_base = edit.list_window_base_len
                            old_pos = edit.list_window_possize_info
                            edit.setText(second)
                            edit.setSelection([len(second), len(second)])
                            edit.makeVisible(len(second))
                            edit.popupListPrepare(complete=False)
                            prepared = edit.list_window_prepared_info
                            expected_base = second.rfind("\\") + 1
                            observed = []
                            set_items = old.setItems.side_effect
                            failure = error_type("reused candidate update failed")
                            def failed(*args, observed=observed, edit=edit, partial=partial,
                                       set_items=set_items, failure=failure):
                                observed.append(edit.list_window_base_len)
                                if partial:
                                    set_items(*args)
                                raise failure
                            old.setItems.side_effect = failed
                            try:
                                with self.assertRaises(error_type) as caught:
                                    edit.popupList()
                            finally:
                                old.setItems.side_effect = set_items
                            self.assertIs(caught.exception, failure)
                            self.assertEqual(observed, [expected_base])
                            self.assertEqual(edit.list_window_base_len, old_base)
                            self.assertIs(edit.list_window_possize_info, old_pos)
                            self.assertIs(edit.list_window_prepared_info, prepared)
                            self.assertIs(edit.list_window, old)
                            old.destroy.assert_not_called()
                            self.assertEqual(len(fixture.created), 2)
                            self.assertFalse(fixture.window.delayed)
                            edit.popupList()
                            self.assertEqual(edit.list_window_base_len, expected_base)
                            self.assertIsNone(edit.list_window_prepared_info)
                        finally:
                            fixture.doCleanups()


class CandidateReplacementTests(unittest.TestCase):
    def test_failure_restores_old_state_and_cancels_registered_destruction(self):
        for stage in ("disable", "create", "schedule_before", "schedule_after", "items", "items_after_callback", "cleanup"):
            for enabled in (False, True):
                for error_type in (RuntimeError, KeyboardInterrupt, SystemExit):
                    with self.subTest(stage=stage, enabled=enabled, error=error_type):
                        fixture = drawing.EditCandidateTests()
                        fixture.setUp()
                        try:
                            edit = fixture.edit(lambda info: (["alpha", "alpine"], 0))
                            edit.popupListPrepare(complete=False)
                            edit.popupList()
                            fixture.window.delayed.pop()[0]()
                            old = fixture.created[-1]
                            old.isEnabled.return_value = enabled
                            old_base = edit.list_window_base_len
                            old_pos = edit.list_window_possize_info
                            old_items = old.items.copy()
                            edit.candidate_handler = lambda info: (["beta", "bravo", "bright"], 1)
                            edit.popupListPrepare(complete=False)
                            prepared = edit.list_window_prepared_info
                            failure = error_type("replacement failed")
                            calls = []
                            def enable(value, old=old, stage=stage, failure=failure, calls=calls):
                                old.isEnabled.return_value = value
                                calls.append(value)
                                if stage == "disable" and len(calls) == 1:
                                    raise failure
                                if stage == "cleanup" and len(calls) == 2:
                                    raise OSError("old restore failed")
                            old.enable.side_effect = enable
                            create = edit.createCandidateWindow
                            def created(stage=stage, failure=failure, create=create, fixture=fixture, old=old):
                                if stage == "create":
                                    raise failure
                                candidate = create()
                                set_items = candidate.setItems.side_effect
                                def items(*args):
                                    set_items(*args)
                                    if stage == "items_after_callback":
                                        fixture.window.delayed.pop()[0]()
                                        old.destroy.assert_not_called()
                                    if stage in ("items", "items_after_callback", "cleanup"):
                                        raise failure
                                candidate.setItems.side_effect = items
                                if stage == "cleanup":
                                    candidate.destroy.side_effect = OSError("new cleanup failed")
                                return candidate
                            schedule = fixture.window.delayedCall
                            def scheduled(callback, delay, stage=stage, failure=failure, schedule=schedule):
                                if stage == "schedule_before":
                                    raise failure
                                schedule(callback, delay)
                                if stage == "schedule_after":
                                    raise failure
                            with patch.object(edit, "createCandidateWindow", side_effect=created), \
                                 patch.object(fixture.window, "delayedCall", side_effect=scheduled), \
                                 self.assertRaises(error_type) as caught:
                                edit.popupList()
                            self.assertIs(caught.exception, failure)
                            self.assertIs(edit.list_window, old)
                            self.assertEqual(old.isEnabled(), enabled)
                            self.assertEqual(edit.list_window_base_len, old_base)
                            self.assertIs(edit.list_window_possize_info, old_pos)
                            self.assertIs(edit.list_window_prepared_info, prepared)
                            self.assertEqual(old.items, old_items)
                            for callback, delay in fixture.window.delayed:
                                self.assertEqual(delay, 50)
                                callback()
                            old.destroy.assert_not_called()
                            if len(fixture.created) == 3:
                                fixture.created[-1].destroy.assert_called_once_with()
                            if stage == "cleanup":
                                self.assertEqual(len(failure.__notes__), 2)
                                self.assertIn("new cleanup failed", failure.__notes__[0])
                                self.assertIn("old restore failed", failure.__notes__[1])
                        finally:
                            fixture.doCleanups()

    def test_early_callback_waits_for_successful_replacement(self):
        fixture = drawing.EditCandidateTests()
        fixture.setUp()
        try:
            edit = fixture.edit(lambda info: (["alpha", "alpine"], 0))
            old = fixture.created[0]
            schedule = fixture.window.delayedCall
            def immediate(callback, delay):
                schedule(callback, delay)
                callback()
                old.destroy.assert_not_called()
            with patch.object(fixture.window, "delayedCall", side_effect=immediate):
                edit.popupListPrepare(complete=False)
                edit.popupList()
            old.destroy.assert_called_once_with()
            self.assertIs(edit.list_window, fixture.created[1])
            self.assertEqual(fixture.created[1].items, ["alpha", "alpine"])
            self.assertIsNone(edit.list_window_prepared_info)
        finally:
            fixture.doCleanups()


class CandidateConstructionTests(unittest.TestCase):
    def setUp(self):
        drawing.ckit.setTheme("black", {})

    def test_cleanup_starts_only_after_base_initialization_and_preserves_first_error(self):
        for cls in (ckit_widget.CandidateWindow, ckit_textwidget.CandidateWindow):
            for stage in ("success", "base", "field", "items", "cleanup"):
                for error_type in (RuntimeError, KeyboardInterrupt, SystemExit):
                    with self.subTest(candidate=cls.__module__, stage=stage, error=error_type):
                        calls = []
                        failure = error_type("candidate initialization failed")
                        assign = cls.__setattr__
                        def set_attribute(obj, name, value, stage=stage, failure=failure, assign=assign):
                            if stage == "field" and name == "min_width":
                                raise failure
                            assign(obj, name, value)
                        def initialize(obj, *, stage=stage, calls=calls, failure=failure, **kwargs):
                            calls.append("base")
                            if stage == "base":
                                raise failure
                        def items(*args, stage=stage, calls=calls, failure=failure):
                            calls.append("items")
                            if stage in ("items", "cleanup"):
                                raise failure
                        def destroy(obj, stage=stage, calls=calls):
                            calls.append("destroy")
                            if stage == "cleanup":
                                raise OSError("cleanup failed")
                        with patch.object(ckit_textwindow.TextWindow, "__init__", initialize), \
                             patch.object(ckit_textwindow.TextWindow, "destroy", destroy), \
                             patch.object(cls, "__setattr__", set_attribute), \
                             patch.object(cls, "destroy", side_effect=AssertionError("Unfinished derived resources")), \
                             patch.object(cls, "setItems", side_effect=items):
                            if stage == "success":
                                cls(1, 2, 10, 1, 80, 16, drawing.Window())
                            else:
                                with self.assertRaises(error_type) as caught:
                                    cls(1, 2, 10, 1, 80, 16, drawing.Window())
                                self.assertIs(caught.exception, failure)
                                if stage == "cleanup":
                                    self.assertTrue(any("cleanup failed" in note
                                                        for note in getattr(failure, "__notes__", [])))
                        self.assertEqual(calls, {"success": ["base", "items"], "base": ["base"],
                            "field": ["base", "destroy"], "items": ["base", "items", "destroy"],
                            "cleanup": ["base", "items", "destroy"]}[stage])


class CandidateLifetimeTests(unittest.TestCase):
    def test_delayed_close_retains_old_candidate_and_looks_up_destroy_on_delivery(self):
        pending = []
        class Parent(drawing.Window):
            def delayedCall(self, callback, timeout):
                pending.append((callback, timeout))
        with patch.object(drawing.ckit.TextWidget, "paint"):
            edit = drawing.ckit.TextWidget(Parent(), 0, 0, 30, 5)
            old = Mock(spec=ckit_textwidget.CandidateWindow)
            current = Mock(spec=ckit_textwidget.CandidateWindow)
            old_ref = weakref.ref(old)
            edit.candidate_window = old
            try:
                edit.closeList(delay=True)
                self.assertIsNone(edit.candidate_window)
                callback, timeout = pending.pop()
                self.assertEqual(timeout, 50)
                self.assertIs(vars(callback)["candidate_window"], old)
                empty = type(callback)()
                with self.assertRaises(AttributeError) as caught:
                    empty()
                self.assertEqual(caught.exception.name, "candidate_window")
                self.assertIs(caught.exception.obj, empty)
                edit.candidate_window = current
                del old
                gc.collect()
                self.assertIsNotNone(old_ref())
                retained = old_ref()
                assert retained is not None
                retained.destroy.assert_not_called()
                calls = []
                def delivered():
                    calls.append("destroy")
                retained.destroy = delivered
                del retained
                callback()
                self.assertEqual(calls, ["destroy"])
                current.destroy.assert_not_called()
                self.assertIs(edit.candidate_window, current)
                del callback
                gc.collect()
                self.assertIsNone(old_ref())
            finally:
                edit.destroy()

    def test_delayed_close_registration_failure_preserves_candidate_and_exception(self):
        for error_type in (RuntimeError, KeyboardInterrupt, SystemExit):
            with self.subTest(error=error_type), patch.object(drawing.ckit.TextWidget, "paint"):
                failure = error_type("registration failed before enqueue")
                old = Mock(spec=ckit_textwidget.CandidateWindow)
                observed = []
                class Parent(drawing.Window):
                    def delayedCall(self, callback, timeout, observed=observed, failure=failure):
                        observed.append((vars(callback)["candidate_window"], timeout))
                        raise failure
                edit = drawing.ckit.TextWidget(Parent(), 0, 0, 30, 5)
                edit.candidate_window = old
                try:
                    with self.assertRaises(error_type) as caught:
                        edit.closeList(delay=True)
                    self.assertIs(caught.exception, failure)
                    self.assertEqual(observed, [(old, 50)])
                    self.assertIs(edit.candidate_window, old)
                    old.destroy.assert_not_called()
                    edit.closeList()
                    old.destroy.assert_called_once_with()
                    self.assertIsNone(edit.candidate_window)
                finally:
                    edit.destroy()

    def test_stale_keys_leave_current_candidate_text_and_delayed_owner_unchanged(self):
        for key in (drawing.ckit.VK_RETURN, drawing.ckit.VK_TAB):
            for replacement in (False, True):
                with self.subTest(key=key, replacement=replacement), \
                     patch.object(drawing.ckit.TextWidget, "paint"):
                    pending = []
                    class Parent(drawing.Window):
                        def charToScreen(self, x, y):
                            return x, y
                        def delayedCall(self, callback, timeout, pending=pending):
                            pending.append((callback, timeout))
                    parent = Parent()
                    edit = drawing.ckit.TextWidget(parent, 0, 0, 30, 5)
                    try:
                        edit.modifyText(text="pre")
                        old_result = SimpleNamespace(items=["old"], selection=0,
                            left=edit.pointDocumentBegin(), right=edit.pointDocumentEnd())
                        new_result = SimpleNamespace(items=["new0", "new1"] if replacement else [],
                            selection=1, left=edit.pointDocumentBegin(), right=edit.pointDocumentEnd())
                        windows = []
                        class Candidate:
                            def __init__(self, keydown_hook):
                                self.keydown_hook = keydown_hook
                                self.getSelection = Mock(return_value=1)
                                self.setItems = Mock()
                                self.destroy = Mock()
                        def create(*args, windows=windows, **kwargs):
                            candidate = Candidate(kwargs["keydown_hook"])
                            windows.append(candidate)
                            return candidate
                        with patch.object(ckit_textwidget, "CandidateWindow", side_effect=create), \
                             patch.object(edit.doc.mode.completion, "getCandidateList",
                                          side_effect=[old_result, new_result]):
                            edit.popupList(auto_fix=False)
                            old = windows[0]
                            edit.popupList(auto_fix=False)
                            current = edit.candidate_window
                            undo = list(edit.doc.undo_list)
                            self.assertTrue(old.keydown_hook(key, 0))
                            self.assertIsNone(old.keydown_hook(key, drawing.ckit.MODKEY_SHIFT))
                            self.assertIsNone(old.keydown_hook(drawing.ckit.VK_ESCAPE, 0))
                            self.assertEqual(edit.doc.lines[0].s, "pre")
                            self.assertEqual(edit.doc.undo_list, undo)
                            self.assertIs(edit.candidate_window, current)
                            old.getSelection.assert_not_called()
                            for candidate in windows:
                                candidate.destroy.assert_not_called()
                            callback, timeout = pending.pop()
                            self.assertEqual(timeout, 50)
                            callback()
                            old.destroy.assert_called_once_with()
                            if current is not None:
                                windows[-1].destroy.assert_not_called()
                            retained_hook = old.keydown_hook
                            old_ref = weakref.ref(old)
                            gc_enabled = gc.isenabled()
                            gc.disable()
                            try:
                                del old, callback, candidate
                                windows.pop(0)
                                self.assertIsNone(old_ref())
                            finally:
                                if gc_enabled:
                                    gc.enable()
                            self.assertTrue(retained_hook(key, 0))
                    finally:
                        edit.destroy()


class KeymapSequenceTests(unittest.TestCase):
    def test_list_and_tuple_sequences_preserve_order_identity_and_hook(self):
        import pyauto
        hook = SimpleNamespace()
        with patch.object(pyauto, "Hook", return_value=hook):
            loaded = runpy.run_path(str(ROOT / "pyauto/sample/keymap/keymap_hook.py"))
        namespace = loaded["_onKeyDown"].__globals__
        for event, table in (("_onKeyDown", "keydown_table"), ("_onKeyUp", "keyup_table")):
            for container in (list, tuple):
                for values in ([], [object(), object()]):
                    with self.subTest(event=event, container=container, count=len(values)):
                        namespace["_hook"] = hook
                        handler = container(values)
                        keymap = namespace["Keymap"](0)
                        getattr(keymap, table)[namespace["KeyStroke"](65)] = handler
                        namespace["_current_keymap"] = keymap
                        before, after = object(), object()
                        calls = []
                        def up(mod, calls=calls, before=before):
                            calls.append("up")
                            return [before]
                        def down(mod, calls=calls, after=after):
                            calls.append("down")
                            return [after]
                        namespace["createKeySequence_ModifierUp"] = up
                        namespace["createKeySequence_ModifierDown"] = down
                        send = Mock(side_effect=lambda sequence, calls=calls: calls.append("send"))
                        with patch.object(pyauto, "Input", SimpleNamespace(send=send)):
                            self.assertTrue(namespace[event](65, 0))
                        sequence = send.call_args.args[0]
                        self.assertEqual(calls, ["up", "down", "send"])
                        self.assertEqual(sequence, [before, *values, after])
                        self.assertTrue(all(a is b for a, b in zip(sequence[1:-1], values)))
                        self.assertIs(getattr(keymap, table)[namespace["KeyStroke"](65)], handler)
                        self.assertIs(namespace["_hook"], hook)
                        self.assertFalse(namespace[event](66, 0))


if __name__ == "__main__":
    unittest.main()
