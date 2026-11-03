"""Input lifecycle fault injection; native UI calls are replaced by fakes."""
import contextlib
import io
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_text

import ckit

clnch_text.initialize()
import clnch_inputsession as sessions
import clnch_mainwindow

from ckit import ckit_subprocess, ckit_widget

FIELDS = ("commandline_edit", "keydown_hook", "char_hook", "mouse_event_mask", "status_bar_paint_hook")


class FakeEdit:
    UpdateInfo = ckit.EditWidget.UpdateInfo

    def __init__(self, window, x, y, width, height, text, selection, **options):
        self.window, self.text, self.selection = window, text, selection
        self.options = options
        self.destroyed = False
        window.edits.append(self)
        window.events.append("create")

    def setImeRect(self, rect): self.window.event("ime-rect")
    def destroy(self):
        self.destroyed = True
        self.window.event("destroy")
    def getText(self): return self.text
    def getSelection(self): return self.selection
    def setSelection(self, selection): self.selection = selection
    def setText(self, text):
        update = self.UpdateInfo(text, [len(text), len(text)])
        if self.options["update_handler"](update) is not False:
            self.text, self.selection = update.text, update.selection
    def clear(self): self.setText("")
    def onKeyDown(self, vk, mod): return False
    def onChar(self, ch, mod): self.setText(self.text + chr(ch))
    def closeList(self): self.window.event("close-list")
    def makeVisible(self, pos): pass
    def setPosSize(self, *args): pass
    def enableCursor(self, active): self.window.events.append(("cursor", active))
    def paint(self): self.window.events.append("edit-paint")


class FakeWindow:
    commandLine = clnch_mainwindow.MainWindow.commandLine
    subThreadCall = clnch_mainwindow.MainWindow.subThreadCall
    subProcessCall = clnch_mainwindow.MainWindow.subProcessCall

    def __init__(self):
        self.events, self.edits = [], []
        self.failures = {}
        self.commandline_edit = None
        self.keydown_hook = self.char_hook = self.status_bar_paint_hook = None
        self.mouse_event_mask = False
        self.input_settings = {"HISTORY_MODE": "session"}
        self.commandline_history = []
        self.console_window = SimpleNamespace(isVisible=lambda: self.console_visible, show=self.show_console)
        self.console_visible = False
        self.active = True
        self.size = 18
        self.loop = lambda check: None

    def event(self, name):
        self.events.append(name)
        if name in self.failures:
            raise self.failures[name]
    def show_console(self, visible): self.console_visible = visible
    def width(self): return self.size
    def height(self): return 1
    def getStringWidth(self, text): return len(text)
    def getWindowRect(self): return (0, 0, self.size, 1)
    def setPosSize(self, x, y, width, height, origin):
        self.event("resize")
        self.size = width
    def putString(self, *args): pass
    def isLauncherActive(self): return self.active
    def paint(self, *args): self.event("paint")
    def enableIme(self, enabled): self.event("ime-off")
    def setCursorPos(self, x, y): self.event("caret-off")
    def removeKeyMessage(self): self.event("remove-keys")
    def messageLoop(self, check):
        self.event("loop")
        self.loop(check)
    def quit(self): self.events.append("quit")


class InputStateTests(unittest.TestCase):
    def test_none_custom_hooks_nesting_and_only_changed_attributes(self):
        for old in (None, lambda *args: "old"):
            with self.subTest(old=old):
                window = SimpleNamespace(keydown_hook=old, char_hook=old, other=0)
                with sessions._TemporaryInputState(window) as outer:
                    outer.set(keydown_hook="outer")
                    window.other = 1
                    with sessions._TemporaryInputState(window) as inner:
                        inner.set(keydown_hook="inner", char_hook="char")
                        self.assertEqual(window.keydown_hook, "inner")
                    self.assertEqual(window.keydown_hook, "outer")
                    self.assertIs(window.char_hook, old)
                self.assertIs(window.keydown_hook, old)
                self.assertEqual(window.other, 1)
                if old:
                    self.assertEqual(window.keydown_hook(65, 0), "old")
                    self.assertEqual(window.char_hook(65, 0), "old")

    def test_partial_application_and_lifo_even_if_setter_mutates_before_raising(self):
        for mutate in (False, True):
            events = []
            class Window:
                keydown_hook = char_hook = mouse_event_mask = "old"
                def __setattr__(self, name, value, events=events, mutate=mutate):
                    events.append((name, value))
                    if name == "char_hook" and value == "new":
                        if mutate:
                            object.__setattr__(self, name, value)
                        raise RuntimeError("setter")
                    object.__setattr__(self, name, value)
            window = Window()
            with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, "setter"), \
                 sessions._TemporaryInputState(window) as state:
                state.set(keydown_hook="new", char_hook="new", mouse_event_mask=True)
            self.assertEqual(events, [("keydown_hook", "new"), ("char_hook", "new"),
                                      ("char_hook", "old"), ("keydown_hook", "old")])
            self.assertEqual((window.keydown_hook, window.char_hook, window.mouse_event_mask), ("old",) * 3)

    def test_restore_failure_attempts_other_restores_and_preserves_primary(self):
        class Window:
            keydown_hook = char_hook = "old"
            def __setattr__(self, name, value):
                if name == "char_hook" and value == "old":
                    raise ValueError("restore")
                object.__setattr__(self, name, value)
        window = Window()
        primary = RuntimeError("body")
        with self.assertRaises(RuntimeError) as raised, sessions._TemporaryInputState(window) as state:
            state.set(keydown_hook="new", char_hook="new")
            raise primary
        self.assertIs(raised.exception, primary)
        self.assertIn("restore", str(primary.__notes__))
        self.assertEqual(window.keydown_hook, "old")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.window = FakeWindow()
        self.enterContext(patch.object(sessions.ckit, "EditWidget", FakeEdit))
        self.enterContext(patch.object(sessions.ckit, "getColor", return_value=(0, 0, 0)))
        self.enterContext(patch.object(sessions.clnch_ini, "getint", side_effect=lambda section, key, default: default))
        self.original = tuple(getattr(self.window, field) for field in FIELDS)

    def assert_restored(self):
        self.assertEqual(tuple(getattr(self.window, field) for field in FIELDS), self.original)
        self.assertTrue(all(edit.destroyed for edit in self.window.edits))

    def test_success_order_options_and_repeated_sessions(self):
        candidate, remove = Mock(), Mock()
        for _ in range(2):
            self.window.events.clear()
            def loop(check):
                self.assertTrue(check())
                edit = self.window.commandline_edit
                self.assertEqual(edit.getSelection(), [1, 3])
                self.assertTrue(edit.options["auto_complete"])
                self.assertEqual(edit.options["autofix_list"], ["."])
                self.assertIs(edit.options["candidate_handler"], candidate)
                self.assertIs(edit.options["candidate_remove_handler"], remove)
                self.window.keydown_hook(13, 2)
            self.window.loop = loop
            self.assertEqual(self.window.commandLine("Title", "text", [1, 3], True, ["."],
                             candidate_handler=candidate, candidate_remove_handler=remove), "text")
            self.assert_restored()
            self.assertEqual(self.window.events[-4:], ["destroy", "ime-off", "caret-off", "paint"])

    def test_initial_status_failure_never_attaches_an_edit(self):
        with self.assertRaisesRegex(ValueError, "status"):
            self.window.commandLine("", status_handler=Mock(side_effect=ValueError("status")))
        self.assert_restored()
        self.assertEqual(self.window.events, [])

    def test_constructor_failure_still_resets_ime_caret_and_status(self):
        class FailingEdit:
            def __init__(self, *args, **kwargs): raise ValueError("create")
        with patch.object(sessions.ckit, "EditWidget", FailingEdit), self.assertRaisesRegex(ValueError, "create"):
            self.window.commandLine("")
        self.assert_restored()
        self.assertEqual(self.window.events, ["ime-off", "caret-off", "paint"])

    def test_failures_at_each_stage_restore_and_skip_planned_commands(self):
        for stage in ("ime-rect", "resize", "paint", "remove-keys", "loop", "destroy", "ime-off", "caret-off"):
            with self.subTest(stage=stage):
                self.window = FakeWindow()
                self.window.failures[stage] = ValueError(stage)
                planned = Mock()
                def loop(check, planned=planned):
                    session = self.window.keydown_hook.__self__
                    session.planCommand(planned, None, "never")
                self.window.loop = loop
                with self.assertRaisesRegex(ValueError, stage):
                    self.window.commandLine("", "x" * 30)
                self.assert_restored()
                planned.assert_not_called()
                self.assertEqual(self.window.events[-3:], ["ime-off", "caret-off", "paint"])

    def test_body_failure_survives_multiple_cleanup_failures(self):
        primary = RuntimeError("loop")
        self.window.failures = {"loop": primary, "destroy": ValueError("destroy"),
                                "ime-off": ValueError("ime-off"), "paint": ValueError("paint")}
        # Fail only the final repaint, so the intended primary occurs inside the loop.
        self.window.paint = lambda *args: self.window.event("paint") if self.window.edits[0].destroyed else None
        with self.assertRaises(RuntimeError) as raised:
            self.window.commandLine("")
        self.assertIs(raised.exception, primary)
        for stage in ("destroy", "ime-off", "paint"):
            self.assertIn(stage, str(primary.__notes__))
        self.assert_restored()

    def test_nested_session_restores_outer_edit_handlers_and_text(self):
        def outer(check):
            attached = tuple(getattr(self.window, field) for field in FIELDS)
            self.window.loop = lambda check: self.window.keydown_hook(13, 0)
            self.assertEqual(self.window.commandLine("inner", "inner"), "inner")
            self.assertEqual(tuple(getattr(self.window, field) for field in FIELDS), attached)
            self.assertEqual(self.window.commandline_edit.getText(), "outer")
            self.window.char_hook(ord("!"), 0)
            self.window.keydown_hook(13, 0)
        self.window.loop = outer
        self.assertEqual(self.window.commandLine("", "outer"), "outer!")
        self.assert_restored()

    def test_partial_hook_application_destroys_owned_edit_and_restores_custom_hooks(self):
        class Window(FakeWindow):
            def __setattr__(self, name, value):
                object.__setattr__(self, name, value)
                if name == "char_hook" and getattr(self, "fail_apply", False):
                    object.__setattr__(self, "fail_apply", False)
                    raise RuntimeError("hook apply")
        self.window = Window()
        self.window.keydown_hook = lambda vk, mod: "key"
        self.window.char_hook = lambda ch, mod: "char"
        self.original = tuple(getattr(self.window, field) for field in FIELDS)
        self.window.fail_apply = True
        with self.assertRaisesRegex(RuntimeError, "hook apply"):
            self.window.commandLine("")
        self.assert_restored()
        self.assertEqual(self.window.keydown_hook(65, 0), "key")
        self.assertEqual(self.window.char_hook(65, 0), "char")
        self.window.commandLine("")
        self.assert_restored()

    def test_enter_continue_keeps_last_capture_after_later_escape(self):
        calls = []
        def enter(line, text, mod):
            calls.append((text, mod))
            line.setText("later")
            return True
        def loop(check):
            self.window.keydown_hook(13, 4)
            self.window.keydown_hook(27, 0)
            self.assertEqual(self.window.commandline_edit.getText(), "")
            self.window.keydown_hook(27, 0)
        self.window.loop = loop
        self.assertEqual(self.window.commandLine("", "captured", enter_handler=enter), "captured")
        self.assertEqual(calls, [("captured", 4)])
        self.assertEqual(self.window.events.count("quit"), 1)

    def test_escape_priority_and_custom_key_char_handlers(self):
        escape = Mock(return_value=True)
        self.window.console_visible = True
        def loop(check):
            self.window.keydown_hook(27, 0)
            self.assertEqual(self.window.commandline_edit.getText(), "")
            self.assertTrue(self.window.console_visible)
            self.window.keydown_hook(27, 0)
            self.assertFalse(self.window.console_visible)
            self.window.keydown_hook(27, 0)
            escape.assert_called_once_with(self.window.keydown_hook.__self__)
            self.assertNotIn("quit", self.window.events)
        self.window.loop = loop
        self.window.commandLine("", "draft", escape_handler=escape)
        key, char = Mock(return_value=True), Mock(return_value=True)
        def overridden(check):
            self.window.keydown_hook(13, 2)
            self.window.char_hook(ord("a"), 4)
            self.assertEqual(self.window.commandline_edit.getText(), "draft")
        self.window.loop = overridden
        self.assertIsNone(self.window.commandLine("", "draft", keydown_handler=key, char_handler=char))
        self.assertEqual(key.call_args.args[1:], (13, 2))
        self.assertEqual(char.call_args.args[1:], (ord("a"), 4))

    def test_callback_exceptions_restore_and_allow_next_input(self):
        for name, action in (("keydown_handler", lambda: self.window.keydown_hook(65, 0)),
                             ("char_handler", lambda: self.window.char_hook(65, 0)),
                             ("enter_handler", lambda: self.window.keydown_hook(13, 0)),
                             ("escape_handler", lambda: self.window.keydown_hook(27, 0)),
                             ("update_handler", lambda: self.window.char_hook(65, 0)),
                             ("status_handler", lambda: self.window.char_hook(65, 0))):
            with self.subTest(handler=name):
                handler = Mock(side_effect=ValueError(name))
                if name == "status_handler":
                    handler.side_effect = ["initial", ValueError(name)]
                self.window.loop = lambda check, action=action: action()
                with self.assertRaisesRegex(ValueError, name):
                    self.window.commandLine("", **{name: handler})
                self.assert_restored()
                self.window.loop = lambda check: self.window.char_hook(ord("a"), 0)
                self.assertIsNone(self.window.commandLine(""))
                self.assert_restored()

    def test_normalization_selection_update_rejection_and_status(self):
        captured = []
        def update(info):
            captured.append((info.text, list(info.selection)))
            return info.text != "reject"
        def loop(check):
            line = self.window.keydown_hook.__self__
            info = FakeEdit.UpdateInfo("a\t  b\tc", [4, 6])
            line._onUpdate(info)
            self.assertEqual((info.text, info.selection), ("a   b c", [4, 6]))
            line.setText("reject")
            self.assertEqual(line.getText(), "before")
            line.setText("new")
            line.selectAll()
            self.assertEqual((line.getText(), line.getSelection()), ("new", [0, 3]))
            line._onPaint(0, 0, 30, 1)
            self.assertIn(("cursor", True), self.window.events)
            self.window.active = False
            line._onPaint(0, 0, 30, 1)
            self.assertIn(("cursor", False), self.window.events)
            line.paint()
        self.window.loop = loop
        self.window.commandLine("Title", "before", update_handler=update, status_handler=lambda info: info.text)
        self.assertEqual(captured[0], ("a   b c", [4, 6]))

    def test_execute_string_history_dedup_limit_and_command_errors(self):
        self.window.commandline_history = ["old", "NEW   entry"]
        def loop(check):
            line = self.window.keydown_hook.__self__
            line.executeCommand(lambda info: "input again", None, "no history", True)
            self.assertEqual((line.getText(), line.getSelection()), ("input again", [0, 11]))
            self.assertEqual(self.window.commandline_history, ["old", "NEW   entry"])
            self.assertNotIn("quit", self.window.events)
            line.executeCommand(lambda info: None, None, "new\t  entry", False)
            self.assertEqual(self.window.commandline_history, ["new   entry", "old"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                line.executeCommand(Mock(side_effect=ValueError("command")), None, "no history", True)
            self.assertEqual(out.getvalue(), "command\n")
            self.assertNotIn("quit", self.window.events)
            self.window.input_settings["HISTORY_MODE"] = "off"
            line.appendHistory("ignored")
            self.assertEqual(self.window.commandline_history, ["new   entry", "old"])
            self.window.input_settings["HISTORY_MODE"] = "session"
            self.window.commandline_history = [str(i) for i in range(1000)]
            line.executeCommand(lambda info: None, None, "last", True)
            self.assertEqual(len(self.window.commandline_history), 1000)
            self.assertEqual(self.window.commandline_history[:2], ["last", "0"])
            self.assertIn("quit", self.window.events)
        self.window.loop = loop
        self.window.commandLine("")

    def test_top_level_deferred_string_without_restored_input(self):
        for result in ("returned text", ""):
            with self.subTest(result=result):
                self.window = FakeWindow()
                lines = []
                command_info = object()
                def command(info, command_info=command_info, lines=lines, result=result):
                    self.assertIs(info, command_info)
                    self.assert_restored()
                    self.assertIsNone(lines[0].edit)
                    self.assertEqual(self.window.events[-4:], ["destroy", "ime-off", "caret-off", "paint"])
                    return result
                planned = Mock(side_effect=command)
                def enter(line, text, mod, lines=lines, planned=planned, command_info=command_info):
                    lines.append(line)
                    line.planCommand(planned, command_info, "ignored history")
                    return False
                self.window.loop = lambda check: self.window.keydown_hook(13, 0)
                self.assertEqual(self.window.commandLine("", "captured", enter_handler=enter), "captured")
                planned.assert_called_once_with(command_info)
                self.assert_restored()
                self.assertEqual(self.window.edits[0].text, "captured")
                self.assertEqual(self.window.commandline_history, [])
                self.assertEqual(self.window.events.count("quit"), 1)
                self.assertEqual(self.window.events[-4:], ["destroy", "ime-off", "caret-off", "paint"])

    def test_nested_deferred_strings_update_outer_input(self):
        for result in ("outer replacement", ""):
            with self.subTest(result=result):
                self.window = FakeWindow()
                planned = Mock(return_value=result)
                def inner_enter(line, text, mod, planned=planned):
                    line.planCommand(planned, None, "ignored history")
                    return False
                def outer(check, result=result, inner_enter=inner_enter):
                    attached = tuple(getattr(self.window, field) for field in FIELDS)
                    self.window.loop = lambda check: self.window.keydown_hook(13, 0)
                    self.assertEqual(self.window.commandLine("inner", "inner text", enter_handler=inner_enter), "inner text")
                    self.assertEqual(tuple(getattr(self.window, field) for field in FIELDS), attached)
                    self.assertEqual(self.window.commandline_edit.getText(), result)
                    self.assertEqual(self.window.commandline_edit.getSelection(), [0, len(result)])
                    self.assertFalse(self.window.edits[0].destroyed)
                    self.assertTrue(self.window.edits[1].destroyed)
                    self.assertEqual(self.window.edits[1].text, "inner text")
                    self.window.keydown_hook(13, 0)
                self.window.loop = outer
                self.assertEqual(self.window.commandLine("outer", "outer text"), result)
                planned.assert_called_once_with(None)
                self.assert_restored()
                self.assertEqual(self.window.commandline_history, [])
                self.assertEqual(self.window.events.count("quit"), 2)

    def test_top_level_deferred_results_errors_and_order(self):
        calls = []
        commands = []
        def enter(line, text, mod):
            for info, result in enumerate(("returned text", "", None, False, 42, ValueError("command failure"), None)):
                def command(info, result=result):
                    self.assert_restored()
                    calls.append(info)
                    if isinstance(result, Exception):
                        raise result
                    return result
                planned = Mock(side_effect=command)
                commands.append(planned)
                line.planCommand(planned, info, None if info == 6 else f"history {info}")
            self.assertEqual(calls, [])
            return False
        self.window.loop = lambda check: self.window.keydown_hook(13, 0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(self.window.commandLine("", "captured", enter_handler=enter), "captured")
        self.assertEqual(calls, list(range(7)))
        for info, planned in enumerate(commands):
            planned.assert_called_once_with(info)
        self.assertEqual(output.getvalue(), "command failure\n")
        self.assertEqual(self.window.commandline_history, ["history 4", "history 3", "history 2"])
        self.assertEqual(self.window.events.count("quit"), 1)
        self.assert_restored()

    def test_deferred_commands_run_after_cleanup_in_order_and_use_restored_input(self):
        restored = FakeEdit(self.window, 0, 0, 18, 1, "outer", [0, 5], update_handler=lambda info: None)
        self.window.commandline_edit = restored
        def command(info):
            self.assertIs(self.window.commandline_edit, restored)
            self.assertIsNone(self.window.keydown_hook)
            self.assertEqual(self.window.events[-1], "paint")
            self.window.events.append(info)
        def loop(check):
            line = self.window.keydown_hook.__self__
            line.planCommand(command, "first", "first history")
            line.planCommand(lambda info: "returned text", None, "ignored")
            line.planCommand(lambda info: self.window.events.append("last"), None, None)
        self.window.loop = loop
        self.window.commandLine("")
        self.assertEqual(restored.text, "returned text")
        self.assertEqual(self.window.commandline_history, ["first history"])
        self.assertLess(self.window.events.index("first"), self.window.events.index("last"))
        self.assertFalse(restored.destroyed)
        self.assertTrue(self.window.edits[-1].destroyed)


class EditConstructionTests(unittest.TestCase):
    def test_partial_edit_releases_candidate_and_preserves_constructor_error(self):
        for stage in ("makeVisible", "paint"):
            for destroy_fails in (False, True):
                candidate = Mock()
                if destroy_fails:
                    candidate.destroy.side_effect = ValueError("destroy")
                error = RuntimeError(stage)
                with self.subTest(stage=stage, destroy_fails=destroy_fails), \
                     patch.object(ckit_widget.EditWidget, "enableIme"), \
                     patch.object(ckit_widget.EditWidget, "createCandidateWindow", return_value=candidate), \
                     patch.object(ckit_widget.EditWidget, "makeVisible"), \
                     patch.object(ckit_widget.EditWidget, "paint"), \
                     patch.object(ckit_widget.EditWidget, stage, side_effect=error), \
                     self.assertRaises(RuntimeError) as raised:
                    ckit_widget.EditWidget(Mock(), 0, 0, 20, 1, "text", candidate_handler=lambda info: [])
                self.assertIs(raised.exception, error)
                candidate.destroy.assert_called_once()
                if destroy_fails:
                    self.assertIn("destroy", str(error.__notes__))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.window = FakeWindow()
        self.window.keydown_hook = lambda vk, mod: "normal-key"
        self.window.char_hook = lambda ch, mod: "normal-char"
        self.original = tuple(getattr(self.window, field) for field in FIELDS)

    def assert_restored(self):
        self.assertEqual(tuple(getattr(self.window, field) for field in FIELDS), self.original)
        self.assertEqual(self.window.keydown_hook(65, 0), "normal-key")
        self.assertEqual(self.window.char_hook(65, 0), "normal-char")

    def test_success_waits_for_worker_and_restores_before_result(self):
        release = threading.Event()
        def loop(check):
            self.assertTrue(check())
            self.assertTrue(self.window.keydown_hook(65, 0))
            self.assertTrue(self.window.char_hook(65, 0))
            self.assertTrue(self.window.mouse_event_mask)
            release.set()
        self.window.loop = loop
        self.assertEqual(self.window.subThreadCall(lambda: release.wait(2) and "result", ()), "result")
        self.assert_restored()

    def test_thread_start_and_join_failures_restore_hooks(self):
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("start")), \
             self.assertRaisesRegex(RuntimeError, "start"):
            self.window.subThreadCall(lambda: None, ())
        self.assert_restored()
        finished = threading.Event()
        self.window.loop = lambda check: self.assertTrue(finished.wait(2))
        with patch.object(threading.Thread, "join", side_effect=RuntimeError("join")), \
             self.assertRaisesRegex(RuntimeError, "join"):
            self.window.subThreadCall(finished.set, ())
        self.assert_restored()

    def test_worker_error_raise_and_traceback_contract(self):
        for raise_error in (False, True):
            for print_traceback in (False, True):
                error = ValueError("worker failed")
                out, err = io.StringIO(), io.StringIO()
                with self.subTest(raise_error=raise_error, print_traceback=print_traceback), \
                     contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    if raise_error:
                        with self.assertRaises(ValueError) as raised:
                            self.window.subThreadCall(Mock(side_effect=error), (), raise_error=True,
                                                      print_traceback=print_traceback)
                        self.assertIs(raised.exception, error)
                    else:
                        self.assertIsNone(self.window.subThreadCall(Mock(side_effect=error), (),
                                          print_traceback=print_traceback))
                self.assertEqual(out.getvalue(), "" if raise_error else "worker failed\n")
                self.assertEqual("Traceback" in err.getvalue(), print_traceback)
                self.assert_restored()

    def test_cancel_requests_exit_but_loop_keeps_worker_alive_until_completion(self):
        canceled, release = threading.Event(), threading.Event()
        def cancel(value):
            self.assertEqual(value, "arg")
            canceled.set()
        def loop(check):
            self.window.keydown_hook(27, 0)
            self.assertTrue(canceled.is_set())
            self.assertTrue(check())
            release.set()
        self.window.loop = loop
        self.assertTrue(self.window.subThreadCall(lambda: release.wait(2), (), cancel, ("arg",)))
        self.assert_restored()

    def test_subprocess_escape_during_startup_and_disabled_cancel(self):
        def check_cancel(enabled):
            entered, release = threading.Event(), threading.Event()
            process = Mock(pid=123, returncode=7, stdout=io.BytesIO())
            process.poll.side_effect = [None, 7] if enabled else [7]
            def popen(*args, **kwargs):
                entered.set()
                self.assertTrue(release.wait(3))
                return process
            def loop(check):
                self.assertTrue(entered.wait(3))
                try:
                    self.assertTrue(self.window.keydown_hook(27, 0))
                    self.assertTrue(check())
                finally:
                    release.set()
            self.window.loop = loop
            with self.subTest(enabled=enabled), \
                 patch.object(ckit_subprocess.subprocess, "Popen", side_effect=popen), \
                 patch.object(ckit_subprocess.ckit_misc, "terminateProcess") as terminate:
                self.assertEqual(self.window.subProcessCall(["program"], enable_cancel=enabled), 7)
                self.assert_restored()
                if enabled:
                    terminate.assert_called_once_with(123)
                else:
                    terminate.assert_not_called()
            process.stdout.close()

        for enabled in (False, True):
            check_cancel(enabled)

    def test_subprocess_start_failure_uses_existing_error_reporting(self):
        self.window.loop = lambda check: None
        output = io.StringIO()
        with patch.object(ckit_subprocess.subprocess, "Popen", side_effect=OSError("cannot start")), \
             contextlib.redirect_stdout(output):
            self.assertIsNone(self.window.subProcessCall(["program"], enable_cancel=True))
        self.assertEqual(output.getvalue(), "cannot start\n")
        self.assert_restored()

    def test_ui_and_cancel_failures_restore_without_joining_live_worker(self):
        for stage in ("loop", "remove-keys", "cancel"):
            release, finished = threading.Event(), threading.Event()
            workers = []
            original_join = threading.Thread.join
            def worker(workers=workers, release=release, finished=finished):
                workers.append(threading.current_thread())
                try:
                    release.wait(3)
                finally:
                    finished.set()
            def join(thread, *args, **kwargs):
                self.fail("abnormal UI exit must not block on worker join")
            error = RuntimeError(stage)
            if stage == "cancel":
                self.window.loop = lambda check: self.window.keydown_hook(27, 0)
            else:
                self.window.failures = {stage: error}
            try:
                with self.subTest(stage=stage), patch.object(threading.Thread, "join", join), \
                     self.assertRaises(RuntimeError) as raised:
                    self.window.subThreadCall(worker, (), Mock(side_effect=error))
                self.assertIs(raised.exception, error)
                self.assert_restored()
                self.assertFalse(finished.is_set())
            finally:
                release.set()
                self.assertTrue(finished.wait(2))
                for thread in workers:
                    original_join(thread, 2)
                self.window.failures = {}


if __name__ == "__main__":
    unittest.main()
