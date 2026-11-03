"""Raw Windows argument contracts; replace only job scheduling and Shell execution."""
import contextlib
import ctypes
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import native_test_support

ROOT = Path(__file__).resolve().parent.parent
if "--package" in sys.argv:
    index = sys.argv.index("--package")
    package = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
    native_test_support.RUN_DIR = package
    sys.path[:0] = [str(package / "library.zip"), str(package / "lib")]
else:
    sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(native_test_support.RUN_DIR / "lib")]
import clnch_commandline as commandline
import clnch_commandplatform as platform
import clnch_inputsession
import clnch_ipc
import clnch_mainwindow
import clnch_misc
from clnch_commandexecutor import CommandExecutor
from clnch_commandregistry import CommandRegistry
from test_input_session import FakeWindow

import ckit

CASES = [
    (r'"Z:\Temp\test.txt" -Y=3', [r"Z:\Temp\test.txt", "-Y=3"]),
    ("one two", ["one", "two"]),
    ("one;two", ["one;two"]),
    ('"one;two" three', ["one;two", "three"]),
    ('"a b.txt" "" /flag', ["a b.txt", "", "/flag"]),
    (r'"C:\two words\\" "" C:\tail' + '\\', ["C:\\two words\\", "", "C:\\tail\\"]),
    (r'  "a\"b"  \\"x y"  ', ['a"b', "\\x y"]),
    ('"日本語 😀"\t""   end  ', ["日本語 😀", "", "end"]),
    ("%RAW_LITERAL% %% %param%", ["%RAW_LITERAL%", "%%", "%param%"]),
    ("", []),
]


class ArgumentStringTests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(association_list=[], modifier_settings={
            "CTRL_ACTION": "execute", "SHIFT_ACTION": "execute", "CTRL_SHIFT_ACTION": "execute"})
        self.window.ShellExecuteCommand = lambda *a, **kw: clnch_mainwindow.MainWindow.ShellExecuteCommand(self.window, *a, **kw)
        self.launcher = commandline.commandline_Launcher(self.window)
        self.registry = CommandRegistry([])
        self.executor = CommandExecutor(self.window, self.registry)
        self.registry.register("_ra", self.executor.elevate, self.executor.elevate)
        self.window.commandline_list = [self.launcher, platform.SystemExecutableCommandline(self.window),
            commandline.commandline_ExecuteURL(self.window), commandline.commandline_ExecuteFile(self.window)]
        self.shell = self.enterContext(patch.object(commandline.pyauto, "shellExecute"))
        self.enterContext(patch.object(ckit, "JobItem", side_effect=lambda job, done: SimpleNamespace(job=job)))
        self.enterContext(patch.object(ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=lambda item: item.job(item))))
        self.line = SimpleNamespace(planCommand=lambda cmd, info, text: cmd(info), quit=Mock(), appendHistory=Mock())

    def configure(self, commands):
        self.registry.rebuild(self.launcher, commands, self.executor.make_handler)

    def enter(self, text, mod=0):
        self.shell.reset_mock()
        self.assertTrue(any(provider.onEnter(self.line, text, mod) for provider in self.window.commandline_list))
        self.shell.assert_called_once()
        return self.shell.call_args.args

    def test_registered_system_file_and_json_preserve_identical_raw_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "tool file.exe"
            file.touch()
            for raw, args in CASES:
                with self.subTest(raw=raw):
                    self.assertEqual(platform.split_commandline_args(raw), args)
                    self.configure({"skr": {"target": {"link": str(file)}}})
                    for mod in (0, 2, 4, 6):
                        self.assertEqual(self.enter("skr;" + raw, mod)[2], raw)
                    self.assertEqual(self.enter(str(file) + ";" + raw)[2], raw)
                    with patch.object(platform, "resolve_system_executable", return_value=str(file)):
                        self.assertEqual(self.enter("unregistered;" + raw)[2], raw)
                    self.configure({"skr": {"target": {"link": str(file), "args": raw}}})
                    self.assertEqual(self.enter("skr")[2], clnch_misc.replaceMacro(
                        raw, {"%%": "%", "%param%": ""}, environ=True))

    def test_direct_paths_accept_one_quote_pair_and_keep_history_and_raw_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "日本語 folder"
            folder.mkdir()
            file = folder / "実行 file.exe"
            file.touch()
            for path in (str(file), str(folder), str(folder) + "\\"):
                for quoted in (False, True):
                    target = '"' + path + '"' if quoted else path
                    for suffix in ("", *(";" + raw for raw, _args in CASES)):
                        text = target + suffix
                        with self.subTest(text=text):
                            self.line.appendHistory.reset_mock()
                            self.line.quit.reset_mock()
                            call = self.enter(text)
                            self.assertEqual(call, (None, path, suffix[1:], ckit.splitPath(path)[0]))
                            self.line.appendHistory.assert_called_once_with(text)
                            self.line.quit.assert_called_once_with()

    def test_unmatched_and_extra_quotes_do_not_match_or_change_input(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "日本語 file.txt"
            file.touch()
            for target in ('"' + str(file), str(file) + '"', '""' + str(file) + '""',
                           str(file) + ".missing", '"' + str(file) + '.missing"', '"', '""'):
                text = target + ';  "a b" "" one;two  '
                with self.subTest(text=text):
                    self.line.planCommand = Mock()
                    self.assertFalse(any(provider.onEnter(self.line, text, 0)
                                         for provider in self.window.commandline_list))
                    self.shell.assert_not_called()
                    self.line.planCommand.assert_not_called()
                    self.line.appendHistory.assert_not_called()
                    self.line.quit.assert_not_called()

    def test_file_acceptance_requires_exists_before_association_or_fallback(self):
        file = r"\\unreachable\share\file.txt"
        text = '"' + file + '";  "a b" "" one;two  '
        handler = commandline.commandline_ExecuteFile(self.window)
        for present in (False, True):
            for associated in (False, True):
                with self.subTest(present=present, associated=associated):
                    pending, events = [], []
                    self.line.planCommand = Mock()
                    self.line.appendHistory.reset_mock()
                    self.line.quit.reset_mock()
                    association = Mock()
                    self.window.association_list = [("*.txt", association)] if associated else []
                    def exists(path, events=events, present=present):
                        self.assertEqual(path, file)
                        self.line.planCommand.assert_not_called()
                        self.line.appendHistory.assert_not_called()
                        self.line.quit.assert_not_called()
                        events.append("exists")
                        return present
                    def fallback(line, value, mod, events=events):
                        events.append("fallback")
                        self.assertEqual((line, value, mod), (self.line, text, 4))
                        return True
                    with patch.object(commandline.os.path, "exists", side_effect=exists), \
                         patch.object(ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=pending.append)), \
                         patch.object(commandline.clnch_misc, "checkNetConnection") as network, \
                         patch.object(commandline.clnch_native, "findFile") as find:
                        providers = [handler, SimpleNamespace(onEnter=fallback)]
                        self.assertTrue(any(provider.onEnter(self.line, text, 4) for provider in providers))
                        self.assertEqual(events, ["exists"] if present else ["exists", "fallback"])
                        self.assertEqual(len(pending), int(present and not associated))
                        self.assertEqual(self.line.planCommand.call_count, int(present and associated))
                        self.assertEqual(self.line.appendHistory.call_count, int(present and not associated))
                        self.assertEqual(self.line.quit.call_count, int(present))
                        association.assert_not_called()
                        self.shell.assert_not_called()
                        network.assert_not_called()
                        find.assert_not_called()

    def test_name_whitespace_keeps_registered_priority_and_original_arguments(self):
        for raw, _args in CASES:
            for padding in (" ", "\t", "\u3000", "\u00a0"):
                with self.subTest(raw=raw, padding=padding):
                    self.configure({"notepad": {"target": {"link": "registered.exe"}}})
                    text = padding + "NoTePaD" + padding + ";" + raw
                    with patch.object(platform, "resolve_system_executable") as lookup:
                        self.assertEqual(self.enter(text)[:3], (None, "registered.exe", raw))
                        lookup.assert_not_called()
        self.configure({"notepad": {}})
        with patch.object(platform, "resolve_system_executable") as lookup:
            self.assertTrue(self.launcher.onEnter(self.line, "notepad ", 0))
            lookup.assert_not_called()

    def test_quoted_json_link_alias_workdir_and_raw_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "日本語 file.exe"
            target.touch()
            for raw, _args in CASES:
                for link in (str(target), '"' + str(target) + '"', '"%RECRAFT_TARGET%"'):
                    for workdir in ("", directory + "\\override"):
                        self.configure({"outer": {"target": {"link": "child", "workdir": workdir}},
                                        "child": {"target": {"link": link}}})
                        with patch.dict(platform.os.environ, RECRAFT_TARGET=str(target)):
                            self.assertEqual(self.enter("outer;" + raw),
                                             (None, str(target), raw, workdir or directory, "normal"))

    def test_fixed_input_placeholder_alias_chain_and_modifier_order(self):
        raw = '  "a b.txt" "" one;two C:\\tail\\  '
        fixed = '  --fixed "C:\\fixed path\\\\"  '
        for modifier in ("target", "on_ctrl", "on_shift", "on_ctrl_shift"):
            for template, expected in ((fixed, fixed + " " + raw),
                                       ("before %param% after", "before " + raw + " after"),
                                       ("%param%", raw)):
                with self.subTest(modifier=modifier, template=template):
                    self.configure({"outer": {modifier: {"link": "middle", "args": template}},
                        "middle": {"target": {"link": "child", "args": 'middle %param% ""'}},
                        "child": {"target": {"link": "tool.exe", "args": "terminal %param% end"}}})
                    mod = {"target": 0, "on_ctrl": 2, "on_shift": 4, "on_ctrl_shift": 6}[modifier]
                    self.assertEqual(self.enter("outer;" + raw, mod)[2], 'terminal middle ' + expected + ' "" end')

    def test_ra_consumes_only_target_and_preserves_tail(self):
        self.configure({"alias": {"target": {"link": "child", "args": '"fixed arg"'}},
                        "child": {"target": {"link": "tool.exe"}}})
        for raw, _args in CASES:
            with self.subTest(raw=raw):
                call = self.enter("_ra;alias " + raw)
                self.assertEqual(call[:3], ("runas", "tool.exe", '"fixed arg"' + (" " + raw if raw else "")))
                call = self.enter('_ra;"C:\\Program Files\\tool.exe" ' + raw)
                self.assertEqual(call[:3], ("runas", "C:\\Program Files\\tool.exe", raw))
                self.assertEqual(self.enter("_ra;_ra child " + raw)[:3], ("runas", "tool.exe", raw))

    def test_ra_uac_cancellation_is_silent_and_other_failures_are_reported(self):
        self.configure({"child": {"target": {"link": "tool.exe"}},
                        "alias": {"target": {"link": "child"}}})
        for text, error, silent in (
            ("_ra;child", ctypes.WinError(1223), True),
            ("_ra;alias", ctypes.WinError(1223), True),
            ("_ra;tool.exe", ctypes.WinError(1223), True),
            ("_ra;child", ctypes.WinError(2), False),
            ("_ra;child", ctypes.WinError(5), False),
            ("_ra;child", OSError(1223, "no Windows error code"), False),
            ("_ra;child", ValueError("launch failure"), False),
            ("child", ctypes.WinError(1223), False),
        ):
            with self.subTest(text=text, error=error):
                self.shell.side_effect = error
                output, errors = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                    self.enter(text)
                self.assertEqual(errors.getvalue(), "")
                expected = "" if silent else clnch_mainwindow.strings.EXECUTE_ERROR + "\n  " + str(error) + "\n"
                self.assertEqual(output.getvalue(), expected)
        self.shell.side_effect = None
        self.assertEqual(self.enter("child")[:3], (None, "tool.exe", ""))

    def test_association_retains_raw_tail_and_windows_args(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "a file.txt"
            file.touch()
            received = []
            self.window.association_list = [("*.txt", received.append)]
            self.line.planCommand = Mock(side_effect=self.line.planCommand)
            for target in (str(file), '"' + str(file) + '"'):
                for suffix, args in [("", []), *((";" + raw, args) for raw, args in CASES)]:
                    text = target + suffix
                    with self.subTest(text=text):
                        self.assertTrue(self.window.commandline_list[-1].onEnter(self.line, text, 6))
                        info = received[-1]
                        self.assertEqual(info.args, [str(file), *args])
                        self.assertEqual(info.arg_string, subprocess.list2cmdline([str(file)])
                                         + (" " + suffix[1:] if suffix else ""))
                        self.assertEqual(info.mod, 6)
                        self.assertEqual(self.line.planCommand.call_args.args, (received.append, info, text))
                        self.window.ShellExecuteCommand(None, "viewer.exe", "", "")(info)
                        self.assertEqual(self.shell.call_args.args[2], info.arg_string)

    def test_ipc_serialization_keeps_leading_trailing_spaces_and_url_semicolons(self):
        self.configure({"skr": {"target": {"link": "tool.exe"}}})
        for raw, _args in CASES:
            with self.subTest(raw=raw):
                ipc = clnch_ipc.IpcData()
                ipc.trySetOption("--execute", "skr;" + raw)
                ipc.trySetOption("--text", "skr;" + raw)
                ipc.trySetOption("--selection", "4")
                received = clnch_ipc.IpcData(ipc.getValue())
                self.assertEqual(received.getExecuteList(), ["skr;" + raw])
                self.shell.reset_mock()
                received.execute(self.window)
                self.assertEqual(self.shell.call_args.args[2], raw)
                target = SimpleNamespace(isEnabled=lambda: True, restore=Mock(), foreground=Mock(), activate=Mock(),
                    activeMessageLoop=Mock(), resetPos=Mock())
                received.commandLine(target)
                self.assertEqual(target.activeMessageLoop.call_args.kwargs["text"], "skr;" + raw)
                self.assertEqual(target.activeMessageLoop.call_args.kwargs["selection"], [4, 4 + len(raw)])
        url = "https://example.invalid/a;one;two?q=a;b"
        self.assertEqual(self.enter(url)[:3], (None, url, ""))

    def test_main_keys_receive_whole_input_and_programmatic_args_keep_list_contract(self):
        text = 'skr;"a b" "" one;two'
        key = ckit.KeyEvent(ckit.VK_F9, ckit.MODKEY_CTRL)
        self.window.cmd_keymap = SimpleNamespace(table={})
        self.window.keymap = SimpleNamespace(table={key: Mock()})
        line = SimpleNamespace(getText=lambda: text, executeCommand=Mock())
        commandline._LauncherInputHandlers(self.window).onKeyDown(line, ckit.VK_F9, ckit.MODKEY_CTRL)
        info = line.executeCommand.call_args.args[1]
        self.assertEqual((info.args, info.arg_string, info.mod), ([text], text, 0))
        self.window.ShellExecuteCommand(None, "tool.exe", "", "")(SimpleNamespace(args=["a b", "", 'a"b']))
        self.assertEqual(self.shell.call_args.args[2], subprocess.list2cmdline(["a b", "", 'a"b']))

    def test_context_menu_key_uses_path_before_argument_separator(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "a file.txt"
            file.touch()
            self.window.commandline_edit = SimpleNamespace(closeList=Mock(), x=0, width=20)
            self.window.charToScreen = lambda x, y: (x, y)
            self.window.removeKeyMessage = Mock()
            self.window.getHWND = lambda: 1
            for path in (str(file), '"' + str(file) + '"'):
                text = path + ';"a b" one;two'
                with patch.object(commandline.clnch_native, "popupContextMenu") as popup:
                    clnch_mainwindow.MainWindow.command_ContextMenu(
                        self.window, SimpleNamespace(args=[text], arg_string=text))
                    popup.assert_called_once_with(1, 20, 1, directory, [file.name])

    def test_context_menu_missing_target_does_not_execute_or_commit_input(self):
        ckit.Keymap.init()
        self.window.cmd_keymap, self.window.keymap = ckit.Keymap(), ckit.Keymap()
        binding = ckit.CommandMap(self.window).ContextMenu
        self.window.cmd_keymap["C-Slash"] = binding
        for text in ("", "unregistered name", '"C:\\missing file"', '"C:\\missing',
                     'C:\\missing"', '""C:\\missing""', "missing;raw;tail"):
            line = SimpleNamespace(getText=lambda text=text: text, executeCommand=Mock())
            self.assertTrue(commandline._LauncherInputHandlers(self.window).onKeyDown(
                line, ckit.VK_OEM_2, ckit.MODKEY_CTRL))
            line.executeCommand.assert_not_called()
        # An override on the same physical key retains the ordinary cmd_keymap contract.
        self.window.cmd_keymap["C-Slash"] = lambda info: None
        commandline._LauncherInputHandlers(self.window).onKeyDown(line, ckit.VK_OEM_2, ckit.MODKEY_CTRL)
        line.executeCommand.assert_called_once()

    def test_normalization_keeps_spaces_and_selection_in_standard_and_custom_sessions(self):
        texts = ("cmd  arg", "cmd;one  two", r"C:\My  Tools\app.exe",
                 "https://example.invalid/a  b;q=one  two", "  cmd  arg  ")
        for preserve_raw in (False, True):
            session = clnch_inputsession._CommandLineSession(
                FakeWindow(), 0, "", preserve_argument_text=preserve_raw)
            for text in texts:
                for left in range(len(text) + 1):
                    for right in range(len(text) + 1):
                        with self.subTest(raw=preserve_raw, text=text, selection=[left, right]):
                            update = ckit.EditWidget.UpdateInfo(text, [left, right])
                            session._normalize(update)
                            self.assertEqual((update.text, update.selection), (text, [left, right]))

    def test_standard_raw_tail_and_custom_control_character_conversion(self):
        window = FakeWindow()
        text = 'skr;  "a  b"\t""  one;two  '
        for selection in ([0, 0], [4, 15], [0, len(text)], [len(text), len(text)]):
            session = clnch_inputsession._CommandLineSession(window, 0, "", preserve_argument_text=True)
            update = ckit.EditWidget.UpdateInfo(text, selection)
            session._normalize(update)
            self.assertEqual((update.text, update.selection), (text, selection))
        session.appendHistory(text)
        self.assertEqual(window.commandline_history[0], text)
        update = ckit.EditWidget.UpdateInfo("cmd\t;one\t  two\r\n", [2, 9])
        session._normalize(update)
        self.assertEqual((update.text, update.selection), ("cmd ;one\t  two\r\n", [2, 9]))
        url = "https://example.invalid/a\t  b\r\n"
        update = ckit.EditWidget.UpdateInfo(url, [0, len(url)])
        session._normalize(update)
        session.appendHistory(url)
        self.assertEqual(update.text, url)
        self.assertEqual(window.commandline_history[0], url)
        session = clnch_inputsession._CommandLineSession(window, 0, "")
        update = ckit.EditWidget.UpdateInfo("  custom\t;one  two\r\n  ", [3, 15])
        session._normalize(update)
        self.assertEqual((update.text, update.selection), ("  custom ;one  two    ", [3, 15]))
        session.appendHistory("  custom\t;one  two\r\n  ")
        self.assertEqual(window.commandline_history[0], update.text)

    def test_completion_uses_windows_word_boundaries_not_later_semicolons(self):
        for text, suffix in (("skr;one;tw", "one;tw"), ('skr;"a b;tw', "a b;tw"),
                             ('skr;"a b" C:\\folder\\fi', "C:\\folder\\fi"),
                             ('skr;one two', "two"), ("skr;", ""), ("sk", "sk")):
            with self.subTest(text=text):
                self.assertEqual(text[clnch_misc.commandlineArgumentStart(text):], suffix)


if __name__ == "__main__":
    unittest.main()
