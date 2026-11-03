"""MainWindow routing, status and history contracts with GUI operations replaced."""
import configparser
import io
import sys
import tempfile
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
import clnch_commandline
import clnch_configmenu as menu
import clnch_mainwindow as main
import clnch_standard
import clnch_statusbar


class Window:
    activeMessageLoop = main.MainWindow.activeMessageLoop
    registerStatusBar = main.MainWindow.registerStatusBar
    unregisterStatusBar = main.MainWindow.unregisterStatusBar
    setStatusMessage = main.MainWindow.setStatusMessage
    clearStatusMessage = main.MainWindow.clearStatusMessage
    _onStatusMessageTimedout = main.MainWindow._onStatusMessageTimedout
    command_History = main.MainWindow.command_History

    def __init__(self):
        self.input_settings = {"COMPLETION_MODE": "standard"}
        self.commandline_history = ["np;C:\\日本語\\old", "np;C:\\日本語\\OLD"]
        self.commandline_list = []
        self.launcher = clnch_commandline.commandline_Launcher(self)
        self.cmd_keymap = SimpleNamespace(table={})
        self.keymap = SimpleNamespace(table={})
        self.commandLine = Mock()
        self.resetPos = Mock()
        self.inactivate = Mock()
        self.status_bar = clnch_statusbar.StatusBar()
        self.simple_status_bar_layer = clnch_statusbar.SimpleStatusBarLayer()
        self.simple_status_bar_resistered = False
        self.custom_status_bar_map = {}
        self.commandline_edit = None
        self.timers = {}
        self.paint = Mock()
        self.centerOfWindowInPixel = lambda: (10, 20)
        self.isEnabled = lambda: True
        self.isForeground = lambda: True
        self.enable = Mock()
        self.activate = Mock()

    def setTimer(self, handler, interval): self.timers[handler] = interval
    def killTimer(self, handler): self.timers.pop(handler, None)


class LauncherRoutingTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window.activeMessageLoop("initial", [1, 4])
        self.handlers = self.window.commandLine.call_args.kwargs
        self.window.commandline_edit = SimpleNamespace(getAutoComplete=Mock(return_value=True))

    def info(self, text, left=None):
        return SimpleNamespace(text=text, selectionLeft=lambda: len(text) if left is None else left)

    def test_public_entry_wires_input_without_owning_session_state(self):
        self.assertEqual(self.window.commandLine.call_args.args, ("",))
        self.assertEqual(self.handlers["text"], "initial")
        self.assertEqual(self.handlers["selection"], [1, 4])
        self.assertEqual(self.handlers["autofix_list"], ["\\/", ".", ";"])

    def test_auto_complete_defaults_types_and_menu_changes_reach_next_session(self):
        ini = main.clnch_ini
        with patch.object(ini, "ini", configparser.RawConfigParser()), patch.object(ini, "dirty", False):
            for stored, expected in ((None, 0), ("0", 0), ("1", 1), ("invalid", 0)):
                with self.subTest(stored=stored):
                    if stored is not None:
                        ini.set("MISC", "auto_complete", stored)
                    self.window.activeMessageLoop()
                    actual = self.window.commandLine.call_args.kwargs["auto_complete"]
                    self.assertIs(type(actual), int)
                    self.assertEqual(actual, expected)
            for result, expected in ((1, 1), (-1, 1), (0, 0)):
                with patch.object(menu.clnch_listwindow, "popMenu", return_value=result), patch.object(ini, "write") as write:
                    menu._configAutoComplete(self.window)
                    write.assert_not_called()
                self.window.activeMessageLoop()
                actual = self.window.commandLine.call_args.kwargs["auto_complete"]
                self.assertIs(type(actual), int)
                self.assertEqual(actual, expected)
                self.assertEqual(ini.get("MISC", "auto_complete"), str(expected))

    def test_candidates_keep_history_order_case_insensitive_dedup_and_replacement_offset(self):
        provider = SimpleNamespace(onCandidate=Mock(return_value=["old", "next", "", "NEXT"]))
        self.window.commandline_list = [provider]
        info = self.info("np;C:\\日本語\\o;ignored", len("np;C:\\日本語\\o"))
        self.assertEqual(self.handlers["candidate_handler"](info), (["old", "next"], 10))
        provider.onCandidate.assert_called_once_with(info)

    def test_off_completion_skips_all_providers_and_reads_current_settings(self):
        provider = SimpleNamespace(onCandidate=Mock(side_effect=AssertionError))
        self.window.commandline_list = [provider]
        self.window.input_settings = {"COMPLETION_MODE": "off"}
        self.assertEqual(self.handlers["candidate_handler"](self.info("np;dir/o")), ([], 7))
        provider.onCandidate.assert_not_called()

    def test_auto_complete_gates_all_candidate_modes_using_live_edit_state(self):
        provider = SimpleNamespace(onCandidate=Mock(return_value=["next-custom"]))
        self.window.launcher.command_list = [("next-name", None)]
        self.window.commandline_list = [self.window.launcher, provider]
        self.window.commandline_history = ["next-history"]
        candidate = self.handlers["candidate_handler"]
        ini = main.clnch_ini
        for enabled in (False, True):
            for mode in ("off", "commands", "standard"):
                with (self.subTest(enabled=enabled, mode=mode),
                      patch.object(ini, "ini", configparser.RawConfigParser()), patch.object(ini, "dirty", False)):
                    # The running edit takes priority over the opposite saved initial state.
                    ini.set("MISC", "auto_complete", str(int(not enabled)))
                    self.window.commandline_edit.getAutoComplete.return_value = enabled
                    self.window.input_settings["COMPLETION_MODE"] = mode
                    provider.onCandidate.reset_mock()
                    expected = {"off": [], "commands": ["next-name"],
                                "standard": ["next-history", "next-name", "next-custom"]}[mode] if enabled else []
                    self.assertEqual(candidate(self.info("next-")), (expected, 0))
                    self.assertEqual(provider.onCandidate.call_count, int(enabled and mode == "standard"))
                    self.assertEqual(self.window.commandline_history, ["next-history"])

    def test_runtime_auto_complete_commands_close_candidates_without_changing_text(self):
        edit = ckit.EditWidget.__new__(ckit.EditWidget)
        edit.auto_complete = False
        edit.text, edit.selection = "next-name", [2, 9]
        edit.closeList = Mock()
        self.window.commandline_edit = edit
        self.window.command = SimpleNamespace(
            AutoCompleteOn=lambda: main.MainWindow.command_AutoCompleteOn(self.window, None),
            AutoCompleteOff=lambda: main.MainWindow.command_AutoCompleteOff(self.window, None))
        before = (edit.getText(), edit.getSelection(), self.window.commandline_history.copy())
        with patch("sys.stdout", io.StringIO()):
            main.MainWindow.command_AutoCompleteOn(self.window, None)
            self.assertTrue(edit.getAutoComplete())
            edit.closeList.assert_not_called()
            main.MainWindow.command_AutoCompleteToggle(self.window, None)
            self.assertFalse(edit.getAutoComplete())
            edit.closeList.assert_called_once_with()
            main.MainWindow.command_AutoCompleteToggle(self.window, None)
            self.assertTrue(edit.getAutoComplete())
            main.MainWindow.command_AutoCompleteOff(self.window, None)
            self.assertFalse(edit.getAutoComplete())
            self.assertEqual(edit.closeList.call_count, 2)
        self.assertEqual((edit.getText(), edit.getSelection(), self.window.commandline_history), before)

    def test_registered_spelling_wins_without_reordering_history_or_changing_it(self):
        self.window.launcher.command_list = [(name, None) for name in ("reload", "MyTool", "MYTOOL")]
        self.window.commandline_history = ["Recent", "RELOAD", "mytool", "reload;KeepCASE"]
        history = self.window.commandline_history.copy()
        provider = SimpleNamespace(onCandidate=lambda info: ["RELOAD", "MYTOOL", "Recent", "Extra", "EXTRA"])
        self.window.commandline_list = [provider, self.window.launcher]
        self.assertEqual(self.handlers["candidate_handler"](self.info("")),
                         (["Recent", "reload", "MyTool", "reload;KeepCASE", "Extra"], 0))
        self.assertEqual(self.window.commandline_history, history)
        self.window.launcher.command_list = [("REload", None)]
        self.assertEqual(self.handlers["candidate_handler"](self.info("re")),
                         (["Recent", "REload", "reload;KeepCASE", "MYTOOL", "Extra"], 0))
        remove = self.handlers["candidate_remove_handler"]
        self.assertTrue(remove("REload"))
        self.assertNotIn("RELOAD", self.window.commandline_history)
        self.assertFalse(remove("reload"))

    def test_candidate_dedup_preserves_path_url_and_argument_spelling(self):
        for text, history, expected, offset in (
                ("C:\\Work\\r", ["C:\\Work\\RELOAD.txt", "C:\\Work\\reload.TXT"], ["RELOAD.txt"], 8),
                ("https://Host/", ["https://Host/KeepCASE", "https://host/keepcase"], ["KeepCASE"], 13),
                ("np;", ["np;RELOAD", "NP;reload"], ["RELOAD"], 3)):
            with self.subTest(text=text):
                self.window.launcher.command_list = [("reload", None), ("reload.txt", None), ("keepcase", None)]
                self.window.commandline_history = history.copy()
                self.window.commandline_list = [SimpleNamespace(onCandidate=lambda info: [])]
                self.assertEqual(self.handlers["candidate_handler"](self.info(text)), (expected, offset))
                self.assertEqual(self.window.commandline_history, history)

    def test_commands_completion_uses_only_live_registered_names(self):
        launcher = clnch_commandline.commandline_Launcher(self.window)
        launcher.command_list = [(name, None) for name in ("", "np", "NP", "next", "tools/np")]
        self.window.launcher = launcher
        provider = SimpleNamespace(onCandidate=Mock(return_value=["np-file", "np-folder/", "np-share/"]))
        self.window.commandline_list = [launcher, provider]
        self.window.commandline_history = ["np-history", "next-history"]
        self.window.input_settings["COMPLETION_MODE"] = "commands"
        candidate = self.handlers["candidate_handler"]
        self.assertEqual(candidate(self.info("n")), (["np", "next"], 0))
        self.assertEqual(candidate(self.info("tools/n")), (["tools/np"], 0))
        for text in ("", "np;", "C:\\", "\\\\server\\"):
            self.assertEqual(candidate(self.info(text)), ([], 0))
        launcher.command_list = [("new", None)]
        self.assertEqual(candidate(self.info("n")), (["new"], 0))
        provider.onCandidate.assert_not_called()
        self.assertEqual(self.window.commandline_history, ["np-history", "next-history"])
        self.window.input_settings["COMPLETION_MODE"] = "standard"
        self.assertEqual(candidate(self.info("np")),
                         (["np-history", "np-file", "np-folder/", "np-share/"], 0))

    def test_callbacks_read_replaced_history_and_provider_lists_after_reload(self):
        self.window.commandline_history = ["new", "next"]
        self.window.commandline_list = [SimpleNamespace(onCandidate=lambda info: ["newer"])]
        self.assertEqual(self.handlers["candidate_handler"](self.info("ne")), (["new", "next", "newer"], 0))
        remove = self.handlers["candidate_remove_handler"]
        self.assertTrue(remove("new"))
        self.assertFalse(remove("missing"))
        self.assertEqual(self.window.commandline_history, ["next"])

    def test_status_uses_first_non_none_and_skips_empty_input(self):
        ignored = SimpleNamespace()
        first = SimpleNamespace(onStatusString=Mock(return_value=None))
        empty = SimpleNamespace(onStatusString=Mock(return_value=""))
        last = SimpleNamespace(onStatusString=Mock(return_value="last"))
        self.window.commandline_list = [ignored, first, empty, last]
        status = self.handlers["status_handler"]
        self.assertIsNone(status(self.info("")))
        first.onStatusString.assert_not_called()
        self.assertEqual(status(self.info("text")), "")
        last.onStatusString.assert_not_called()

    def test_keymap_precedence_arguments_history_and_live_replacement(self):
        commandline = SimpleNamespace(getText=lambda: "np;日本語;;", executeCommand=Mock())
        key = ckit.KeyEvent(65, 2)
        ordinary, ending = Mock(), Mock()
        self.window.keymap = SimpleNamespace(table={key: ordinary})
        handler = self.handlers["keydown_handler"]
        self.assertTrue(handler(commandline, 65, 2))
        args, kwargs = commandline.executeCommand.call_args
        self.assertIs(args[0], ordinary)
        self.assertEqual((args[1].args, args[1].mod, args[2], kwargs),
                         (["np;日本語;;"], 0, None, {"quit": False}))
        self.window.cmd_keymap = SimpleNamespace(table={key: ending})
        self.assertTrue(handler(commandline, 65, 2))
        args, kwargs = commandline.executeCommand.call_args
        self.assertIs(args[0], ending)
        self.assertEqual((args[2], kwargs), ("np;日本語;;", {"quit": True}))
        commandline.executeCommand.reset_mock()
        self.assertIsNone(handler(commandline, 66, 0))
        commandline.executeCommand.assert_not_called()

    def test_disabled_standard_alt_enter_skips_execution_and_reads_live_settings(self):
        ui = clnch_standard._CommandUI(self.window, None, None)
        standard = ui.alt_enter
        key = ckit.KeyEvent(ckit.VK_RETURN, ckit.MODKEY_ALT)
        self.window.cmd_keymap.table[key] = standard
        self.window.altenter_settings = {"action": "none"}
        commandline = SimpleNamespace(getText=Mock(return_value="aaa"), executeCommand=Mock())
        handler = self.handlers["keydown_handler"]
        self.assertTrue(handler(commandline, ckit.VK_RETURN, ckit.MODKEY_ALT))
        commandline.getText.assert_not_called()
        commandline.executeCommand.assert_not_called()
        self.window.inactivate.assert_not_called()
        for action in ("application", "web", "properties", "none"):
            self.window.altenter_settings = {"action": action}
            commandline.executeCommand.reset_mock()
            self.assertTrue(handler(commandline, ckit.VK_RETURN, ckit.MODKEY_ALT))
            if action == "none":
                commandline.executeCommand.assert_not_called()
            else:
                args, kwargs = commandline.executeCommand.call_args
                self.assertEqual((args[0], args[2], kwargs), (standard, None, {"quit": True}))
        custom = lambda info: None
        self.window.cmd_keymap.table[key] = custom
        self.assertTrue(handler(commandline, ckit.VK_RETURN, ckit.MODKEY_ALT))
        args, kwargs = commandline.executeCommand.call_args
        self.assertEqual((args[0], args[2], kwargs), (custom, "aaa", {"quit": True}))

    def test_enter_short_circuits_providers_and_escape_resets_before_inactivation(self):
        providers = [SimpleNamespace(onEnter=Mock(return_value=value)) for value in (False, True, True)]
        self.window.commandline_list = providers
        commandline = object()
        self.assertTrue(self.handlers["enter_handler"](commandline, "np", 4))
        for provider in providers[:2]:
            provider.onEnter.assert_called_once_with(commandline, "np", 4)
        providers[2].onEnter.assert_not_called()
        events = Mock()
        events.attach_mock(self.window.resetPos, "reset")
        events.attach_mock(self.window.inactivate, "inactivate")
        self.assertTrue(self.handlers["escape_handler"](commandline))
        self.assertEqual([call[0] for call in events.mock_calls], ["reset", "inactivate"])

    def test_provider_failure_reaches_session_without_changing_shared_state(self):
        error = RuntimeError("provider")
        self.window.commandline_list = [SimpleNamespace(onCandidate=Mock(side_effect=error))]
        history = self.window.commandline_history
        with self.assertRaises(RuntimeError) as raised:
            self.handlers["candidate_handler"](self.info("np"))
        self.assertIs(raised.exception, error)
        self.assertIs(self.window.commandline_history, history)


class ExternalLaunchTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()

    def test_external_jobs_leave_focus_to_the_launched_application(self):
        for route in ("shell", "url_factory", "url_input", "file_input"):
            for fails in (False, True):
                with self.subTest(route=route, fails=fails), tempfile.TemporaryDirectory() as directory:
                    pending = []
                    info = SimpleNamespace(args=["日本語;arg"])
                    line = SimpleNamespace(appendHistory=Mock(), quit=Mock())
                    queue = SimpleNamespace(enqueue=pending.append)
                    with patch.object(ckit.JobQueue, "defaultQueue", return_value=queue), patch.object(
                            main.pyauto, "shellExecute", side_effect=OSError("launch failed") if fails else None):
                        if route == "shell":
                            main.MainWindow.ShellExecuteCommand(self.window, None, "tool.exe", "", "")(info)
                        elif route == "url_factory":
                            main.MainWindow.UrlCommand(self.window, "https://example.org/?q=%param%")(info)
                        elif route == "url_input":
                            clnch_commandline.commandline_ExecuteURL(self.window).onEnter(line, "https://example.org/", 0)
                        else:
                            target = Path(directory) / "file.txt"
                            target.touch()
                            self.window.association_list = []
                            clnch_commandline.commandline_ExecuteFile(self.window).onEnter(line, str(target), 0)
                        job, = pending
                        self.window.inactivate.assert_not_called()
                        with patch("sys.stdout", new_callable=io.StringIO):
                            if fails and route != "shell":
                                with self.assertRaises(OSError):
                                    job.subthread_func(job)
                            else:
                                job.subthread_func(job)
                        self.window.inactivate.assert_not_called()
                        for finished in job.finished_func_list:
                            finished(job)
                        self.window.inactivate.assert_not_called()


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.enterContext(patch.object(ckit, "getColor", return_value=(1, 2, 3)))

    def test_custom_layer_registration_timer_gating_and_removal(self):
        callback = Mock(return_value="日本語")
        self.window.registerStatusBar(callback, priority=-2, interval=20)
        layer = self.window.custom_status_bar_map[callback]
        self.window.registerStatusBar(callback, interval=50)
        self.assertEqual(self.window.status_bar.layer_list, [layer])
        self.assertEqual(self.window.timers[layer.onTimer], 20)
        layer.onTimer()
        self.window.paint.assert_called_once_with(main.PAINT_STATUS_BAR)
        self.window.paint.reset_mock()
        self.window.commandline_edit = object()
        layer.onTimer()
        self.window.commandline_edit = None
        front = clnch_statusbar.SimpleStatusBarLayer(priority=-3)
        self.window.status_bar.registerLayer(front)
        layer.onTimer()
        self.window.paint.assert_not_called()
        canvas = SimpleNamespace(putString=Mock())
        with patch.object(ckit, "adjustStringWidth", return_value=" displayed ") as adjust:
            layer.paint(canvas, 1, 2, 15, 1)
        callback.assert_called_once_with(15)
        adjust.assert_called_once_with(canvas, " 日本語", 14)
        self.assertEqual(canvas.putString.call_args.args[-1], " displayed ")
        self.window.unregisterStatusBar(callback)
        self.window.unregisterStatusBar(callback)
        self.assertEqual(self.window.custom_status_bar_map, {})
        self.assertEqual(self.window.timers, {})
        self.assertEqual(self.window.status_bar.layer_list, [front])

    def test_new_message_cancels_previous_timeout_even_without_new_timeout(self):
        self.window.setStatusMessage("old", timeout=100)
        self.window.setStatusMessage("new", error=True)
        self.assertNotIn(self.window._onStatusMessageTimedout, self.window.timers)
        self.assertEqual(self.window.simple_status_bar_layer.message, "new")
        self.assertTrue(self.window.simple_status_bar_layer.error)
        self.assertEqual(len(self.window.status_bar.layer_list), 1)

    def test_clear_is_safe_without_message_and_after_timeout(self):
        self.window.clearStatusMessage()
        self.window.setStatusMessage("timed", timeout=100)
        self.window._onStatusMessageTimedout()
        self.window.clearStatusMessage()
        self.assertFalse(self.window.simple_status_bar_resistered)
        self.assertEqual(self.window.status_bar.layer_list, [])
        self.assertEqual(self.window.timers, {})


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.window.commandline_history = ["", "first", "日本語"]
        self.dialog = SimpleNamespace(show=Mock(), messageLoop=Mock(), getResult=Mock(return_value=1),
                                      destroy=Mock())
        self.items = None
        self.hook = None
        def create(*args, **kwargs):
            self.items = args[9]
            self.hook = kwargs["keydown_hook"]
            self.dialog.remove = lambda index: self.items.pop(index)
            return self.dialog
        self.enterContext(patch.object(main.clnch_listwindow, "ListWindow", side_effect=create))
        self.adjust = self.enterContext(patch.object(main.clnch_misc, "adjustWindowPosition"))
        self.window.activeMessageLoop = Mock()

    def test_selection_and_delete_use_the_same_mutable_items(self):
        def loop():
            self.dialog.getResult.return_value = 0
            self.assertTrue(self.hook(ckit.VK_DELETE, 0))
        self.dialog.messageLoop.side_effect = loop
        self.window.command_History(None)
        self.assertEqual(self.window.commandline_history, ["", "日本語"])
        self.window.activeMessageLoop.assert_called_once_with("日本語", [0, 3])
        self.window.enable.assert_any_call(False)
        self.window.enable.assert_called_with(True)
        self.dialog.destroy.assert_called_once_with()

    def test_modifier_tuple_select_delete_cancel_and_result_call_count(self):
        self.dialog.getResult.return_value = (0, 4)
        def delete():
            hook = self.hook
            assert hook is not None
            self.assertTrue(hook(ckit.VK_DELETE, 0))
        self.dialog.messageLoop.side_effect = delete
        with patch.object(self.window, "activeMessageLoop") as selected:
            self.window.command_History(None)
            self.assertEqual(self.window.commandline_history, ["", "日本語"])
            selected.assert_called_once_with("日本語", [0, 3])
            self.assertEqual(self.dialog.getResult.call_count, 2)
            self.dialog.messageLoop.side_effect = None
            self.dialog.getResult.reset_mock(return_value=False)
            self.dialog.getResult.return_value = (-1, 8)
            selected.reset_mock()
            self.window.command_History(None)
            selected.assert_not_called()
            self.dialog.getResult.assert_called_once_with()

    def test_cancel_does_not_open_input(self):
        self.dialog.getResult.return_value = -1
        self.window.command_History(None)
        self.window.activeMessageLoop.assert_not_called()
        self.dialog.destroy.assert_called_once_with()

    def test_empty_history_delete_is_consumed_without_indexing(self):
        self.window.commandline_history = []
        self.dialog.getResult.return_value = -1
        self.dialog.messageLoop.side_effect = lambda: self.assertTrue(self.hook(ckit.VK_DELETE, 0))
        self.window.command_History(None)
        self.assertEqual(self.window.commandline_history, [])

    def test_failures_restore_parent_and_destroy_dialog(self):
        for target in (self.adjust, self.dialog.show, self.dialog.messageLoop, self.dialog.getResult):
            with self.subTest(target=target):
                target.side_effect = RuntimeError("history")
                self.window.enable.reset_mock()
                self.dialog.destroy.reset_mock()
                with self.assertRaisesRegex(RuntimeError, "history"):
                    self.window.command_History(None)
                self.window.enable.assert_called_with(True)
                self.dialog.destroy.assert_called_once_with()
                self.window.activeMessageLoop.assert_not_called()
                target.side_effect = None

    def test_parent_restore_failure_still_destroys_dialog(self):
        self.window.activate.side_effect = RuntimeError("activation")
        with self.assertRaisesRegex(RuntimeError, "activation"):
            self.window.command_History(None)
        self.window.enable.assert_called_with(True)
        self.dialog.destroy.assert_called_once_with()
        self.window.activeMessageLoop.assert_not_called()


class CommandLineEditContracts(unittest.TestCase):
    def test_commands_reacquire_edit_and_preserve_missing_attribute_errors(self):
        class Owner:
            command_ContextMenu = main.MainWindow.command_ContextMenu
            command_RemoveHistory = main.MainWindow.command_RemoveHistory

            def __init__(self, edit):
                self.current: object = edit
                self.events = []

            @property
            def commandline_edit(self):
                self.events.append("read")
                return self.current

            def charToScreen(self, x, y):
                self.events.append(("coordinates", x, y))
                return x, y

            def removeKeyMessage(self):
                self.events.append("remove_keys")

            def getHWND(self):
                return 123

        class Edit:
            def __init__(self, owner, scenario):
                self.owner = owner
                self.scenario = scenario

            def __bool__(self):
                raise AssertionError("Input operations must not test edit truthiness")

            def closeList(self):
                self.owner.events.append("close")
                if self.scenario == "close_replace":
                    self.owner.current = SimpleNamespace(x=13, width=29)
                elif self.scenario == "close_clear":
                    self.owner.current = None

            @property
            def x(self):
                self.owner.events.append("x")
                if self.scenario == "x_replace":
                    self.owner.current = SimpleNamespace(x=13, width=29)
                elif self.scenario == "x_clear":
                    self.owner.current = None
                return 7

            @property
            def width(self):
                self.owner.events.append("width")
                return 11

            def removeCandidate(self):
                self.owner.events.append("remove_candidate")

        cases = (
            ("normal", ["read", "close", "read", "x", "read", "width", ("coordinates", 18, 1), "remove_keys"], None),
            ("close_replace", ["read", "close", "read", "read", ("coordinates", 42, 1), "remove_keys"], None),
            ("close_clear", ["read", "close", "read"], "x"),
            ("x_replace", ["read", "close", "read", "x", "read", ("coordinates", 36, 1), "remove_keys"], None),
            ("x_clear", ["read", "close", "read", "x", "read"], "width"),
            ("none", ["read"], "closeList"),
            ("no_args", [], None),
            ("missing_path", [], None),
            ("remove", ["read", "remove_candidate"], None),
            ("remove_none", ["read"], "removeCandidate"),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_text("")
            for scenario, expected_events, missing in cases:
                with self.subTest(scenario=scenario), patch.object(main.clnch_native, "popupContextMenu") as shell:
                    owner = Owner(None)
                    if scenario not in ("none", "remove_none"):
                        owner.current = Edit(owner, scenario)
                    args = ([] if scenario == "no_args" else
                            [str(path) + "-missing" if scenario == "missing_path" else str(path)])
                    command = owner.command_RemoveHistory if scenario.startswith("remove") else owner.command_ContextMenu
                    if missing:
                        with self.assertRaises(AttributeError) as caught:
                            command(SimpleNamespace(args=args))
                        self.assertEqual(str(caught.exception), f"'NoneType' object has no attribute '{missing}'")
                        self.assertEqual(caught.exception.name, missing)
                        self.assertIsNone(caught.exception.obj)
                    else:
                        self.assertIsNone(command(SimpleNamespace(args=args)))
                    self.assertEqual(owner.events, expected_events)
                    if scenario in ("normal", "close_replace", "x_replace"):
                        coordinates = expected_events[-2]
                        shell.assert_called_once_with(123, coordinates[1], coordinates[2], str(path.parent), [path.name])
                    else:
                        shell.assert_not_called()


if __name__ == "__main__":
    unittest.main()
