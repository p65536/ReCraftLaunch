"""IPC command dispatch; replace only UI, job scheduling and shell launch boundaries."""
import contextlib
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
import clnch_commandline as commandline
import clnch_commandplatform as platform
import clnch_ipc
import clnch_mainwindow
import clnch_standard
from clnch_commandexecutor import CommandExecutor
from clnch_commandregistry import CommandRegistry
from test_input_session import FakeEdit, FakeWindow

import ckit


class IpcExecuteTests(unittest.TestCase):
    def setUp(self):
        self.window = SimpleNamespace(association_list=[])
        self.window.ShellExecuteCommand = lambda *args, **kwargs: clnch_mainwindow.MainWindow.ShellExecuteCommand(self.window, *args, **kwargs)
        self.launcher = commandline.commandline_Launcher(self.window)
        self.window.commandline_list = [self.launcher, platform.SystemExecutableCommandline(self.window),
            commandline.commandline_ExecuteURL(self.window), commandline.commandline_ExecuteFile(self.window)]
        self.jobs = []
        self.shell = self.enterContext(patch.object(commandline.pyauto, "shellExecute"))
        self.enterContext(patch.object(ckit, "JobItem",
            side_effect=lambda job, finished: SimpleNamespace(job=job, finished=finished)))
        self.enterContext(patch.object(ckit.JobQueue, "defaultQueue",
            return_value=SimpleNamespace(enqueue=self.jobs.append)))

    def execute(self, *texts):
        ipc = clnch_ipc.IpcData()
        for text in texts:
            ipc.trySetOption("--execute", text)
        clnch_ipc.IpcData(ipc.getValue()).execute(self.window)

    def finish_jobs(self):
        self.shell.assert_not_called()
        for job in self.jobs:
            job.job(job)
            job.finished(job)

    def test_registered_command_runs_once_with_arguments_and_no_modifiers(self):
        calls = []
        self.launcher.command_list = [("Probe", lambda info: calls.append((info.args, info.mod)))]
        fallback = Mock()
        self.window.commandline_list.append(fallback)
        self.execute('pRoBe;日本語 "two words" "" tail\\', "probe")
        self.assertEqual(calls, [(["日本語", "two words", "", "tail\\"], 0), ([], 0)])
        fallback.onEnter.assert_not_called()
        self.assertEqual(self.jobs, [])

    def test_json_alias_keeps_fixed_dynamic_arguments_and_job_delegation(self):
        registry = CommandRegistry([])
        executor = CommandExecutor(self.window, registry)
        registry.rebuild(self.launcher, {
            "alias": {"target": {"link": "child", "args": '"fixed arg" --flag'}},
            "child": {"target": {"link": "target.exe", "workdir": "D:/Work", "view_mode": "minimized"}},
        }, executor.make_handler)
        self.execute('alias;日本語 "" "two words"')
        self.assertEqual(len(self.jobs), 1)
        self.finish_jobs()
        self.shell.assert_called_once_with(None, "target.exe", '"fixed arg" --flag 日本語 "" "two words"', "D:/Work", "normal")

    def test_relative_json_link_is_rejected_at_execution_without_blocking_the_next_request(self):
        registry = CommandRegistry([])
        executor = CommandExecutor(self.window, registry)
        registry.rebuild(self.launcher, {"bad": {"target": {"link": "tools/tool.exe"}},
            "ok": {"target": {"link": "notepad.exe"}}}, executor.make_handler)
        self.execute("bad", "ok;../document.txt")
        self.assertEqual(len(self.jobs), 2)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.finish_jobs()
        self.assertIn("tools/tool.exe", output.getvalue())
        self.shell.assert_called_once_with(None, "notepad.exe", "../document.txt", "", "normal")

    def test_association_receives_file_and_arguments_once(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "日本語.txt"
            file.touch()
            self.window.association_list = [("*.txt", lambda info: calls.append((info.args, info.mod)))]
            self.execute(f'{file};"two words" ""')
            self.assertEqual(calls, [([str(file), "two words", ""], 0)])
        self.assertEqual(self.jobs, [])

    def test_url_file_and_directory_still_enqueue_one_job_each(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "日本語.txt"
            file.touch()
            self.execute("https://example.invalid/a;b", f'{file};"two words" ""', directory)
            self.assertEqual(len(self.jobs), 3)
            self.finish_jobs()
            self.assertEqual([call.args for call in self.shell.call_args_list], [
                (None, "https://example.invalid/a;b", "", ""),
                (None, str(file), '"two words" ""', directory),
                (None, directory, "", str(Path(directory).parent)),
            ])

    def test_system_executable_preserves_windows_argument_parsing(self):
        with patch.object(platform, "resolve_system_executable", return_value="D:/tool.exe"):
            self.execute('tool;"日本語 文書" "" "a;b"')
        self.assertEqual(len(self.jobs), 1)
        self.finish_jobs()
        self.shell.assert_called_once_with(None, "D:/tool.exe", '"日本語 文書" "" "a;b"', "", None)

    def test_unknown_and_empty_input_remain_unhandled(self):
        output = io.StringIO()
        with patch.object(platform, "resolve_system_executable", return_value=None), contextlib.redirect_stdout(output):
            self.execute("missing-ipc-command", "", ";argument", '"unterminated')
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.jobs, [])

    def test_command_error_is_reported_and_next_execute_still_runs(self):
        failed = Mock(side_effect=ValueError("command failure"))
        called = Mock(return_value="unused input text")
        self.launcher.command_list = [("fail", failed), ("next", called)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.execute("fail;argument", "next")
        failed.assert_called_once()
        called.assert_called_once()
        self.assertEqual(output.getvalue(), "command failure\n")

    def test_provider_error_still_propagates(self):
        self.window.commandline_list = [SimpleNamespace(onEnter=Mock(side_effect=ValueError("provider failure")))]
        with self.assertRaisesRegex(ValueError, "provider failure"):
            self.execute("anything")

    def test_planned_commands_run_after_provider_returns_in_order(self):
        calls = []
        def accept(line, text, mod):
            line.planCommand(lambda info: calls.append(info), text + " first", text)
            line.planCommand(lambda info: calls.append(info), text + " second", text)
            self.assertEqual(calls, [] if text == "one" else ["one first", "one second"])
            return True
        self.window.commandline_list = [SimpleNamespace(onEnter=accept)]
        self.execute("one", "two")
        self.assertEqual(calls, ["one first", "one second", "two first", "two second"])

    def test_modal_builtins_do_not_reenter_reconfigure_or_request_quit(self):
        window = SimpleNamespace(isEnabled=lambda: False, foreground=Mock(),
            quit_requested=False, quit=Mock(), custom=object(), configure=Mock(),
            commandline_history=[], centerOfWindowInPixel=Mock())
        ui = clnch_standard._CommandUI(window, None, None)
        ui._open_command_editor = Mock()
        commands = {
            "config": lambda info: clnch_mainwindow.MainWindow.command_ConfigMenu(window, info),
            "new": ui.new_command,
            "history": lambda info: clnch_mainwindow.MainWindow.command_History(window, info),
            "reload": lambda info: clnch_mainwindow.MainWindow.command_Reload(window, info),
            "quit": lambda info: clnch_mainwindow.MainWindow.command_Quit(window, info),
        }
        with patch.object(clnch_mainwindow.clnch_configmenu, "doConfigMenu") as config:
            for name, command in commands.items():
                with self.subTest(command=name):
                    command(ckit.CommandInfo())
                    config.assert_not_called()
                    ui._open_command_editor.assert_not_called()
                    window.centerOfWindowInPixel.assert_not_called()
                    window.configure.assert_not_called()
                    window.quit.assert_not_called()
                    self.assertFalse(window.quit_requested)
        self.assertEqual(window.foreground.call_count, len(commands))

    def test_quit_with_text_does_not_start_another_input_loop(self):
        window = SimpleNamespace(isEnabled=lambda: True, quit_requested=False, quit=Mock())
        window.commandline_list = [commandline.commandline_Launcher(window)]
        window.commandline_list[0].command_list = [
            ("quit", lambda info: clnch_mainwindow.MainWindow.command_Quit(window, info))]
        ipc = clnch_ipc.IpcData()
        for option, value in (("--text", "ignored"), ("--execute", "quit"),
                              ("--selection", "A"), ("--position", "(50, 50)")):
            ipc.trySetOption(option, value)
        with patch.object(clnch_ipc.IpcData, "commandLine") as input_loop:
            clnch_mainwindow.MainWindow._onIpc(window, ipc.getValue())
        self.assertTrue(window.quit_requested)
        window.quit.assert_called_once_with()
        input_loop.assert_not_called()

    def test_normal_input_still_defers_until_cleanup_and_keeps_modifiers_and_history(self):
        window = FakeWindow()
        launcher = commandline.commandline_Launcher(window)
        window.commandline_list = [launcher]
        calls = []
        launcher.command_list = [("probe", lambda info: calls.append(
            (info.args, info.mod, window.commandline_edit, window.edits[-1].destroyed)))]
        def enter(check):
            window.keydown_hook(ckit.VK_RETURN, ckit.MODKEY_CTRL)
            self.assertEqual(calls, [])
        window.loop = enter
        with patch.object(ckit, "EditWidget", FakeEdit):
            window.commandLine("", text='probe;日本語 "" "two words"',
                enter_handler=commandline._LauncherInputHandlers(window).onEnter)
        self.assertEqual(calls, [(["日本語", "", "two words"], ckit.MODKEY_CTRL, None, True)])
        self.assertEqual(window.commandline_history, ['probe;日本語 "" "two words"'])


if __name__ == "__main__":
    unittest.main()
