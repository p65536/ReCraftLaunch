"""JSON command checks; native GUI and program launches are replaced. Run with -B."""
import ast
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from test_modal_lifecycle import _cleanup_on_exit, load_functions

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_modifierconfig


def action(link, args="", workdir="", view_mode="normal"):
    return {"link": link, "args": args, "workdir": workdir, "view_mode": view_mode}


class JsonCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "commands.json"
        self.calls = []
        self.clipboard = []
        self.editor_calls = []
        self.editor = ModuleType("clnch_cmdeditor")
        self.editor.open_editor = lambda *args, **kwargs: self.editor_calls.append(kwargs)
        self.command_list = ModuleType("clnch_cmdlist")
        self.command_list.open_list = lambda *args, **kwargs: None
        ckit = ModuleType("ckit")
        ckit.dataPath = lambda: self.temp.name
        ckit.MODKEY_CTRL, ckit.MODKEY_SHIFT = 2, 4
        ckit.setClipboardText = self.clipboard.append
        ckit.JobItem = lambda work, finished: SimpleNamespace(subthread_func=work)
        ckit.JobQueue = SimpleNamespace(defaultQueue=lambda: SimpleNamespace(enqueue=lambda job: job.subthread_func(job)))
        pyauto = ModuleType("pyauto")
        pyauto.shellExecute = lambda *args: self.calls.append(args)
        path_namespace = {"os": os, "subprocess": subprocess}
        load_functions("clnch/clnch_misc.py", {"_require_data_path", "_require_job_queue", "replaceMacro", "joinArgs"}, path_namespace)
        module_patch = patch.dict(sys.modules, {
            "clnch_cmdeditor": self.editor, "clnch_cmdlist": self.command_list,
            "clnch_misc": SimpleNamespace(_require_data_path=path_namespace["_require_data_path"],
                                          _require_job_queue=path_namespace["_require_job_queue"],
                                          replaceMacro=path_namespace["replaceMacro"], joinArgs=path_namespace["joinArgs"]),
            "ckit": ckit, "ckit.ckit_misc": SimpleNamespace(_cleanup_on_exit=_cleanup_on_exit), "pyauto": pyauto})
        module_patch.start()
        self.addCleanup(module_patch.stop)

        # Import actual components, replacing only native GUI/launch boundaries.
        for name in ("clnch_standard", "clnch_commandexecutor", "clnch_commandregistry",
                     "clnch_commandplatform"):
            sys.modules.pop(name, None)
        self.standard = importlib.import_module("clnch_standard")
        self.env = vars(self.standard)
        self.window = SimpleNamespace(custom=SimpleNamespace(),
            modifier_settings=clnch_modifierconfig.DEFAULTS.copy(),
            launcher=SimpleNamespace(command_list=[]), commandline_list=[], cmd_keymap={},
            commandline_edit=SimpleNamespace(getText=lambda: ""), show=lambda visible: None,
            isVisible=lambda: True, isEnabled=lambda: True)
        self.window.ShellExecuteCommand = self.shell_command

    def shell_command(self, *args, **kwargs):
        return lambda info: self.calls.append((args, list(info.args)))

    def configure(self, commands):
        self.path.write_text(json.dumps(commands), encoding="utf-8")
        self.env["configure"](self.window, self.env["load_commands"](self.path))
        return dict(self.window.launcher.command_list)

    def run_command(self, name, args=(), mod=0):
        dict(self.window.launcher.command_list)[name](SimpleNamespace(args=list(args), mod=mod))

    def test_ra_registration_and_launcher_dispatch(self):
        tree = ast.parse((ROOT / "clnch/clnch_commandline.py").read_text(encoding="utf-8-sig"))
        launcher = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                        and n.name == "commandline_Launcher")
        namespace = {"ckit": SimpleNamespace(CommandInfo=SimpleNamespace),
                     "split_commandline_args": sys.modules["clnch_commandplatform"].split_commandline_args}
        exec(compile(ast.Module(body=[launcher], type_ignores=[]), "launcher-test", "exec"), namespace)  # noqa: S102  # Execute the real input protocol without native imports.
        self.window.launcher = namespace["commandline_Launcher"](self.window)
        handlers = self.configure({"np": {"target": action("notepad.exe")}})
        self.assertIn("_ra", handlers)
        self.assertNotIn("_elevate", handlers)
        line = SimpleNamespace(planCommand=lambda command, info, text: command(info), quit=lambda: None)
        for text, target, args in (
            ("_ra;np", "notepad.exe", []),
            (r"_ra;np C:\work\report.txt", "notepad.exe", [r"C:\work\report.txt"]),
            (r"_ra;C:\Windows\System32\cmd.exe", r"C:\Windows\System32\cmd.exe", []),
        ):
            with self.subTest(text=text):
                self.assertTrue(self.window.launcher.onEnter(line, text, 0))
                self.assertEqual(self.calls[-1][0][:3], ("runas", target, ""))
                self.assertEqual(self.calls[-1][1], args)

    def test_edit_is_an_ordinary_json_editor_command_with_arguments(self):
        tree = ast.parse((ROOT / "clnch/clnch_commandline.py").read_text(encoding="utf-8-sig"))
        launcher = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                        and n.name == "commandline_Launcher")
        namespace = {"ckit": SimpleNamespace(CommandInfo=SimpleNamespace),
                     "split_commandline_args": sys.modules["clnch_commandplatform"].split_commandline_args}
        exec(compile(ast.Module(body=[launcher], type_ignores=[]), "launcher-test", "exec"), namespace)  # noqa: S102  # Exercise real dispatch without native imports.
        self.window.launcher = namespace["commandline_Launcher"](self.window)
        self.assertNotIn("edit", self.configure({}))
        self.configure({"EDIT": {"target": action("notepad.exe", '"fixed file.txt"')},
                        "alias": {"target": action("edit")}})
        line = SimpleNamespace(planCommand=lambda command, info, text: command(info), quit=lambda: None)
        for name in ("edit", "EDIT", "Edit", "alias"):
            with self.subTest(name=name):
                self.assertTrue(self.window.launcher.onEnter(line, name + ';"日本語 file.txt"', 0))
                self.assertEqual(self.calls[-1],
                    ((None, "notepad.exe", '"fixed file.txt" %param%', "", "normal"), ["日本語 file.txt"]))
        self.assertEqual(len(self.calls), 4)
        self.path.write_text("{}", encoding="utf-8")
        self.window.cmd_keymap["F12"].__self__.reload_commands()
        self.assertFalse(self.window.launcher.onEnter(line, "edit;file.txt", 0))
        self.assertEqual(len(self.calls), 4)

    def test_alt_enter_forwards_whole_input(self):
        self.configure({})
        self.window.commandline_edit = SimpleNamespace(getText=lambda: "日本語;two words")
        with patch.object(self.env["clnch_altenterconfig"], "execute") as forward:
            for key, (_section, _label, binding) in self.env["clnch_altenterconfig"].KEYS.items():
                handler = self.window.cmd_keymap[binding]
                self.assertIs(handler._alt_enter, True)
                self.assertEqual(handler._alt_enter_key, key)
                self.assertIs(handler._append_history, False)
                handler(SimpleNamespace())
                forward.assert_called_with(self.window, "日本語;two words", key)
            self.assertEqual(forward.call_count, 4)
        self.assertEqual(self.calls, [])

    def test_sample_includes_working_empty_command(self):
        commands = json.loads((ROOT / "samples/_commands.json").read_text(encoding="utf-8"))
        handlers = self.configure(commands)
        self.assertIn("", handlers)
        self.run_command("", ["document.txt"])
        self.assertEqual(self.calls[-1], ((None, "notepad.exe", "", "", "normal"), ["document.txt"]))
        for name in commands:
            with self.subTest(name=name):
                self.calls.clear()
                self.run_command(name)
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][0][0], None)
                self.assertEqual(self.calls[0][1], [])

    def test_four_actions_and_arguments(self):
        self.configure({"tool": {"target": action("tool.exe", "--fixed"),
            "on_ctrl": action("ctrl.exe", workdir="D:/Work", view_mode="minimized"),
            "on_shift": action("shift.exe", "--output %param%", view_mode="maximized"),
            "on_ctrl_shift": action("both.exe")}})
        expected = [(0, "tool.exe", "--fixed %param%", "", "normal"),
                    (2, "ctrl.exe", "", "D:/Work", "minimized"),
                    (4, "shift.exe", "--output %param%", "", "maximized"),
                    (6, "both.exe", "", "", "normal")]
        for mod, link, args, workdir, mode in expected:
            self.run_command("tool", ["a b.txt"], mod)
            self.assertEqual(self.calls[-1], ((None, link, args, workdir, mode), ["a b.txt"]))
        count = len(self.calls)
        self.run_command("tool", mod=1)
        self.assertEqual(len(self.calls), count)

    def test_zero_actions_override_builtin_for_input_and_alias_without_fallback(self):
        tree = ast.parse((ROOT / "clnch/clnch_commandline.py").read_text(encoding="utf-8-sig"))
        launcher = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "commandline_Launcher")
        namespace = {"ckit": SimpleNamespace(CommandInfo=SimpleNamespace),
                     "split_commandline_args": sys.modules["clnch_commandplatform"].split_commandline_args}
        exec(compile(ast.Module(body=[launcher], type_ignores=[]), "launcher-test", "exec"), namespace)  # noqa: S102  # Exercise real dispatch without native imports.
        self.window.launcher = namespace["commandline_Launcher"](self.window)
        builtin_calls = []
        self.window.launcher.command_list = [("about", lambda info: builtin_calls.append(info))]
        self.configure({"about": {}, "disabled": {}, "": {}, "alias": {"target": action("ABOUT")}})
        line = SimpleNamespace(planCommand=lambda command, info, text: command(info), quit=lambda: None)
        for name in ("ABOUT", "disabled", "", "alias"):
            for mod in (0, 2, 4, 6):
                with self.subTest(name=name, mod=mod):
                    self.assertTrue(self.window.launcher.onEnter(line, name + ";arg", mod))
        self.assertEqual(builtin_calls, [])
        self.assertEqual(self.calls, [])
        self.window.commandline_edit.getText = lambda: "alias"
        self.window.cmd_keymap["F12"](None)
        self.assertEqual(self.clipboard, [])
        self.run_command("new")
        self.path.write_text("{}", encoding="utf-8")
        self.editor_calls[-1]["on_saved"]()
        self.assertTrue(self.window.launcher.onEnter(line, "About", 0))
        self.assertEqual(len(builtin_calls), 1)

    def test_alias_arguments_overrides_and_path(self):
        self.configure({"alias": {"target": action("child", '"a b.txt" --fixed', "D:/Parent", "maximized")},
                        "child": {"target": action("tool.exe", workdir="D:/Child", view_mode="minimized")}})
        self.run_command("alias", ["dynamic"])
        self.assertEqual(self.calls[-1], ((None, "tool.exe", "", "D:/Parent", "maximized"),
                                        ["a b.txt", "--fixed", "dynamic"]))
        self.window.commandline_edit.getText = lambda: "alias;ignored"
        self.window.cmd_keymap["F12"](None)
        self.assertEqual(self.clipboard, ["tool.exe"])

    def test_multistage_alias_argument_order_matches_folder_defaults(self):
        executor = sys.modules["clnch_commandexecutor"]
        cases = (
            ("A", "B", "input", "B A input"),
            ('A "%param%" tail', 'B %param% end', '  input;C:\\raw\\  ',
             'B A "  input;C:\\raw\\  " tail end'),
            ('A %param% tail', 'B "%param%" end', '"two words"  C:\\raw\\;last',
             'B "A "two words"  C:\\raw\\;last tail" end'),
        )
        for outer, inner, incoming, expected in cases:
            with self.subTest(outer=outer, inner=inner):
                self.configure({"a": {"target": action("b", outer, "D:/Outer")},
                                "b": {"target": action("c", inner, "D:/Inner")},
                                "c": {"target": action("C:/%param%/tool.exe")}})
                handler = dict(self.window.launcher.command_list)["a"]
                captured = []
                self.window.ShellExecuteCommand = lambda *args, captured=captured, **kwargs: lambda info: captured.append(info.arg_string)
                handler(SimpleNamespace(args=[], arg_string=incoming, mod=0))
                self.assertEqual(captured, [expected])
                for modifier, mod in (("CTRL", 2), ("SHIFT", 4), ("CTRL_SHIFT", 6)):
                    for default in ("target_folder", "mapped_folder"):
                        self.window.modifier_settings[modifier + "_ACTION"] = default
                        with patch.object(executor, "split_commandline_args",
                                wraps=executor.split_commandline_args) as split, \
                             patch.object(executor, "_get_target_dir", return_value=None) as target_dir, \
                             patch.object(executor, "get_mapped_directory", return_value=None) as mapped_dir:
                            handler(SimpleNamespace(args=[], arg_string=incoming, mod=mod))
                            split.assert_called_once_with(expected)
                            folder = target_dir if default == "target_folder" else mapped_dir
                            self.assertEqual(folder.call_args.args[-1], "D:/Outer")

    def test_alias_defaults_to_normal_and_elevation_keeps_target_mode(self):
        self.configure({"alias": {"target": {"link": "child"}},
                        "child": {"target": action("tool.exe", view_mode="minimized")}})
        self.run_command("alias")
        self.assertEqual(self.calls[-1][0][-1], "normal")
        self.run_command("_ra", ["child", "document.txt"])
        self.assertEqual(self.calls[-1], (("runas", "tool.exe", "", "", "minimized"), ["document.txt"]))

    def test_alias_chain_uses_origin_mode_for_all_modifiers(self):
        for mode in (None, "normal", "minimized", "maximized"):
            with self.subTest(mode=mode):
                origin = {"link": "middle"}
                if mode is not None:
                    origin["view_mode"] = mode
                self.configure({
                    "origin": {key: origin.copy() for key in ("target", "on_ctrl", "on_shift", "on_ctrl_shift")},
                    "middle": {"target": action("child", view_mode="maximized"),
                               **{key: action("wrong-middle.exe") for key in ("on_ctrl", "on_shift", "on_ctrl_shift")}},
                    "child": {"target": action("tool.exe", view_mode="minimized"),
                              **{key: action("wrong-child.exe") for key in ("on_ctrl", "on_shift", "on_ctrl_shift")}},
                })
                for mod in (0, 2, 4, 6):
                    self.run_command("origin", mod=mod)
                    self.assertEqual(self.calls[-1][0], (None, "tool.exe", "", "", mode or "normal"))

    def test_default_modifiers_and_file_directory(self):
        target = str(Path(self.temp.name) / "tool.exe")
        Path(target).touch()
        self.window.modifier_settings.update(SOURCE_ROOTS=(self.temp.name,),
            CTRL_ACTION="mapped_folder", CTRL_SHIFT_ACTION="mapped_folder",
            CTRL_DESTINATION_ROOT=self.temp.name, CTRL_SHIFT_DESTINATION_ROOT=self.temp.name)
        self.configure({"tool": {"target": action(target)}})
        self.run_command("tool")
        # Auto WorkDir is now decided inside ShellExecuteCommand's expanded job.
        self.assertEqual(self.calls[-1][0][3], "")
        for mod in (2, 4, 6):
            self.run_command("tool", mod=mod)
            self.assertEqual(self.calls[-1], (None, self.temp.name, "", ""))

    def test_folder_jobs_defer_io_and_keep_the_accepted_context(self):
        executor = sys.modules["clnch_commandexecutor"]
        pending = []
        self.configure({"outer": {"target": action("child", '"fixed arg"', "D:/Work")},
                        "child": {"target": action("%RECRAFT_FOLDER%/%param%/tool.exe")}})
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder", SOURCE_ROOTS=["D:/Source"],
                                            CTRL_DESTINATION_ROOT="D:/Destination")
        with patch.object(executor.ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=pending.append)), \
             patch.object(executor, "_get_target_dir", return_value=self.temp.name) as target, \
             patch.object(executor, "get_mapped_directory", return_value=self.temp.name) as mapped, \
             patch.object(executor.os.path, "isdir", return_value=True) as exists, \
             patch.dict(os.environ, RECRAFT_FOLDER="D:/Accepted"):
            handler = dict(self.window.launcher.command_list)["outer"]
            for mod in (4, 2):
                handler(SimpleNamespace(args=[], arg_string='  "input arg"  ', mod=mod))
            target.assert_not_called()
            mapped.assert_not_called()
            exists.assert_not_called()
            self.assertEqual(self.calls, [])
            self.assertEqual(len(pending), 2)
            # Pending work must not reread edited registrations, input or modifier settings.
            os.environ["RECRAFT_FOLDER"] = "D:/Changed"
            self.window.modifier_settings["SOURCE_ROOTS"].append("D:/Added")
            self.window.modifier_settings["CTRL_DESTINATION_ROOT"] = "D:/Changed"
            self.configure({"outer": {"target": action("changed.exe")}})
            for job in pending:
                job.subthread_func(job)
            path = "D:/Accepted/fixed arg input arg/tool.exe"
            target.assert_called_once_with(path, "D:/Work")
            mapped.assert_called_once_with(path, ("D:/Source",), "D:/Destination", "D:/Work")
            self.assertEqual(self.calls, [(None, self.temp.name, "", "")] * 2)

    def test_folder_job_failures_report_once_and_allow_the_next_launch(self):
        executor = sys.modules["clnch_commandexecutor"]
        self.configure({"tool": {"target": action("tool.exe")}})
        self.window.modifier_settings["CTRL_ACTION"] = "mapped_folder"
        for mod in (2, 4):
            helper = "_get_target_dir" if mod == 4 else "get_mapped_directory"
            for stage in ("resolve", "exists", "shell"):
                with self.subTest(mod=mod, stage=stage):
                    pending = []
                    output = io.StringIO()
                    failure = OSError("folder launch failed")
                    self.calls.clear()
                    with patch.object(executor.ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=pending.append)), \
                         patch.object(executor, helper, side_effect=failure if stage == "resolve" else None,
                                      return_value=self.temp.name) as resolve, \
                         patch.object(executor.os.path, "isdir", side_effect=failure if stage == "exists" else None,
                                      return_value=True) as exists, \
                         patch.object(executor, "shellExecute", side_effect=failure if stage == "shell" else None) as shell, \
                         contextlib.redirect_stdout(output):
                        self.run_command("tool", mod=mod)
                        self.assertEqual(output.getvalue(), "")
                        self.assertEqual(len(pending), 1)
                        pending[0].subthread_func(pending[0])
                        self.assertEqual(output.getvalue().splitlines(),
                                         [self.env["strings"].EXECUTE_ERROR, "  folder launch failed"])
                        self.assertEqual(shell.call_count, int(stage == "shell"))
                        resolve.side_effect = exists.side_effect = shell.side_effect = None
                        shell.reset_mock()
                        self.run_command("tool", mod=mod)
                        self.assertEqual(len(pending), 2)
                        pending[1].subthread_func(pending[1])
                        shell.assert_called_once_with(None, self.temp.name, "", "")

    def test_fallback_actions_follow_live_settings_and_explicit_actions_win(self):
        self.configure({"tool": {"target": action("tool.exe", "--fixed", "D:/Work", "maximized"),
                                 "on_ctrl": action("override.exe")}})
        for modifier, mod in (("CTRL", 2), ("SHIFT", 4), ("CTRL_SHIFT", 6)):
            for default in clnch_modifierconfig.ACTIONS:
                self.window.modifier_settings[modifier + "_ACTION"] = default
                self.calls.clear()
                if mod == 2:
                    self.run_command("tool", ["dynamic"], mod)
                    self.assertEqual(self.calls[-1][0][1], "override.exe")
                elif default == "execute":
                    self.run_command("tool", ["dynamic"], mod)
                    self.assertEqual(self.calls, [((None, "tool.exe", "--fixed %param%", "D:/Work", "maximized"),
                                                  ["dynamic"])])
                elif default in ("none", "mapped_folder"):
                    self.run_command("tool", mod=mod)
                    self.assertEqual(self.calls, [])

    def test_execute_fallback_runs_elevation_with_normal_child_action(self):
        self.configure({})
        self.window.modifier_settings["CTRL_ACTION"] = "execute"
        # _ra is a callable target; the called command still uses its normal action.
        self.configure({"child": {"target": action("child.exe"), "on_ctrl": action("other.exe")}})
        self.run_command("_ra", ["child", "dynamic"], 2)
        self.assertEqual(self.calls[-1], (("runas", "child.exe", "", "", "normal"), ["dynamic"]))

    def test_mapping_handles_multiple_roots_order_boundaries_and_missing_folders(self):
        root = Path(self.temp.name)
        program = root / "Programs" / "Special" / "Tool"
        program.mkdir(parents=True)
        target = program / "tool.exe"
        target.touch()
        destination = root / "Related"
        expected = destination / "Tool"
        expected.mkdir(parents=True)
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
            SOURCE_ROOTS=(str(root / "Other"), str(root / "Programs" / "Special"), str(root / "Programs")),
            CTRL_DESTINATION_ROOT=str(destination))
        self.configure({"alias": {"target": action("tool")}, "tool": {"target": action(str(target))}})
        self.run_command("alias", mod=2)
        self.assertEqual(self.calls[-1], (None, str(expected), "", ""))
        for sources, dest in (((), str(destination)), ((str(root / "Program"),), str(destination)),
                              ((str(program),), ""), ((str(root / "Programs"),), str(destination))):
            self.window.modifier_settings.update(SOURCE_ROOTS=sources, CTRL_DESTINATION_ROOT=dest)
            self.calls.clear()
            self.run_command("alias", mod=2)
            self.assertEqual(self.calls, [])
        mapping = self.env["get_mapped_directory"]
        self.assertEqual(mapping(str(target), (str(program),), str(destination)), str(destination))
        self.assertEqual(mapping(str(target), (str(root / "Programs"),), str(destination)),
                         str(destination / "Special" / "Tool"))
        drive = Path(target.anchor)
        self.assertEqual(mapping(str(target), (str(drive),), str(destination)),
                         str(destination / program.relative_to(drive)))

    def test_target_folder_handles_directory_and_unresolvable_alias(self):
        self.configure({"folder": {"target": action(self.temp.name)},
                        "a": {"target": action("b")}, "b": {"target": action("a")}})
        self.run_command("folder", mod=4)
        self.assertEqual(self.calls[-1], (None, self.temp.name, "", ""))
        self.calls.clear()
        self.run_command("a", mod=4)
        self.assertEqual(self.calls, [])

    def test_folder_defaults_resolve_aliases_variables_relative_paths_and_os_names(self):
        root = Path(self.temp.name)
        folder = root / "program" / "bin"
        folder.mkdir(parents=True)
        target = folder / "tool.exe"
        target.touch()
        mapped = root / "related" / "bin"
        mapped.mkdir(parents=True)
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder",
            SOURCE_ROOTS=(str(root / "program"),), CTRL_DESTINATION_ROOT=str(mapped.parent))
        platform = sys.modules["clnch_commandplatform"]
        for link, workdir in ((str(target), ""),
                              ("tool.exe", str(folder)), ("tool.exe", "%RECRAFT_FOLDER%"),
                              ("%RECRAFT_FOLDER%/tool.exe", ""),
                              (str(folder), ""), ("found-by-os.exe", "")):
            with self.subTest(link=link), patch.dict(os.environ, RECRAFT_FOLDER=str(folder)):
                self.configure({"outer": {"target": action("middle", workdir=workdir)},
                    "middle": {"target": action("child")}, "child": {"target": action(link)}})
                with patch.object(platform, "resolve_system_executable", return_value=str(target)) as resolve:
                    for mod, expected in ((4, folder), (2, mapped)):
                        self.calls.clear()
                        self.run_command("outer", mod=mod)
                        self.assertEqual(self.calls, [(None, str(expected), "", "")])
                    self.assertEqual(resolve.call_count, 2 if link == "found-by-os.exe" else 0)
                with patch.object(platform, "resolve_system_executable", side_effect=AssertionError("F12 must not search")):
                    self.clipboard.clear()
                    self.window.commandline_edit.getText = lambda: "outer;ignored"
                    self.window.cmd_keymap["F12"](None)
                    self.assertEqual(self.clipboard, [link])
        for link in (str(folder / "missing.exe"), "missing.exe"):
            self.configure({"missing": {"target": action(link)}})
            with patch.object(platform, "resolve_system_executable", return_value=None):
                for mod in (2, 4):
                    self.calls.clear()
                    self.run_command("missing", mod=mod)
                    self.assertEqual(self.calls, [])

    def test_folder_defaults_reject_relative_links_after_alias_and_environment_resolution(self):
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder", SOURCE_ROOTS=(self.temp.name,),
            CTRL_DESTINATION_ROOT=self.temp.name)
        for link in ("tools/tool.exe", r".\tool.exe", "../folder", r"\tool.exe", "C:tool.exe",
                     "%RECRAFT_RELATIVE%/tool.exe"):
            self.configure({"outer": {"target": action("child", workdir=self.temp.name)},
                            "child": {"target": action(link)}})
            with patch.dict(os.environ, RECRAFT_RELATIVE="tools"):
                for mod in (2, 4):
                    with self.subTest(link=link, mod=mod), self.assertRaises(ValueError) as raised:
                        self.run_command("outer", mod=mod)
                    self.assertIn("outer", str(raised.exception))
                    self.assertEqual(self.calls, [])
            self.window.commandline_edit.getText = lambda: "outer"
            self.window.cmd_keymap["F12"](None)
            self.assertEqual(self.clipboard[-1], link)


    def test_literal_semicolon_path_and_alias_cycle_path(self):
        self.configure({"tool": {"target": action("D:/a;b/tool.exe")},
                        "a": {"target": action("b")}, "b": {"target": action("a")}})
        self.run_command("tool")
        self.assertEqual(self.calls[-1][0][1], "D:/a;b/tool.exe")
        self.window.commandline_edit.getText = lambda: "a"
        self.window.cmd_keymap["F12"](None)
        self.assertEqual(self.clipboard, [])

    def test_validation_rejects_legacy_and_invalid_fields(self):
        for commands in ([1], {"bad": "tool.exe"}, {"bad": {"target": "tool.exe"}},
                         {"bad": {"target": {"link": 1}}},
                         {"bad": {"target": {"link": "tool.exe", "view_mode": "invalid"}}},
                         {"bad": {"target": {"link": "tool.exe", "unknown": "x"}}}):
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                self.configure(commands)

    def test_reload_read_and_parse_failures_preserve_all_handlers(self):
        handlers = self.configure({"Tool": {"target": {"link": "tool.exe"}}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        custom = ("custom", lambda info: None)
        self.window.launcher.command_list.append(custom)
        before = self.window.launcher.command_list.copy()
        with patch("builtins.open", side_effect=PermissionError("locked")), \
                self.assertRaisesRegex(PermissionError, "locked"):
            reload_commands()
        self.assertEqual(self.window.launcher.command_list, before)
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            reload_commands()
        self.assertEqual(self.window.launcher.command_list, before)
        self.run_command("tool")
        self.assertEqual(self.calls[-1][0][1], "tool.exe")

    def test_missing_json_on_startup_and_reload_does_not_create_file(self):
        with patch("builtins.print") as output:
            self.env["configure"](self.window, {})
        output.assert_called_once_with(self.env["strings"].COMMAND_FILE_MISSING)
        self.assertFalse(self.path.exists())
        handlers = self.configure({"tool": {"target": {"link": "tool.exe"}}})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"tool": {"target": {"link": "tool.exe"}}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        self.path.unlink()
        with patch("builtins.print") as output:
            self.editor_calls[-1]["on_saved"]()
        output.assert_not_called()
        self.assertFalse(self.path.exists())
        self.assertNotIn("tool", dict(self.window.launcher.command_list))

    def test_reload_replaces_json_and_preserves_fixed_commands(self):
        handlers = self.configure({"old": {"target": action("old.exe")}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        self.path.write_text(json.dumps({"newer": {"target": action("new.exe")}}), encoding="utf-8")
        reload_commands()
        self.assertEqual(set(dict(self.window.launcher.command_list)), {"_ra", "new", "newer"})
        self.path.write_text('{"invalid":{"target":"old.exe"}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            reload_commands()
        self.run_command("newer")
        self.assertEqual(self.calls[-1][0][1], "new.exe")

    def test_json_saves_preserve_added_custom_commands_and_replace_json_entries(self):
        handlers = self.configure({"old": {"target": action("old.exe")}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        calls = []
        stamp = ("stamp", lambda info: calls.append(("stamp", list(info.args))))
        netdrive = ("NetDrive", lambda info: calls.append(("NetDrive", list(info.args))))
        self.window.launcher.command_list += [stamp, netdrive]
        for commands in ({"old": {"target": action("updated.exe")}},
                         {"renamed": {"target": action("renamed.exe")}}, {}):
            with self.subTest(commands=commands):
                self.path.write_text(json.dumps(commands), encoding="utf-8")
                reload_commands()
                self.assertEqual(set(dict(self.window.launcher.command_list)),
                                 {"_ra", "new", "stamp", "NetDrive", *commands})
                self.assertIs(self.window.launcher.command_list[-2], stamp)
                self.assertIs(self.window.launcher.command_list[-1], netdrive)
                self.run_command("stamp", ["value"])
                self.run_command("NetDrive", ["L"])
                self.assertEqual(calls[-2:], [("stamp", ["value"]), ("NetDrive", ["L"])])
                for name, params in commands.items():
                    self.run_command(name)
                    self.assertEqual(self.calls[-1][0][1], params["target"]["link"])
        self.path.write_text('{"invalid":{"target":"bad.exe"}}', encoding="utf-8")
        previous = self.window.launcher.command_list
        with self.assertRaises(ValueError):
            reload_commands()
        self.assertIs(self.window.launcher.command_list, previous)

    def test_json_name_priority_stays_ahead_of_added_custom_command(self):
        handlers = self.configure({"stamp": {"target": action("json.exe")}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        custom_calls = []
        custom = ("STAMP", lambda info: custom_calls.append(list(info.args)))
        self.window.launcher.command_list.append(custom)
        for _ in range(2):
            reload_commands()
            matching = [item for item in self.window.launcher.command_list if item[0].lower() == "stamp"]
            self.assertEqual(len(matching), 2)
            self.assertIs(matching[1], custom)
            matching[0][1](SimpleNamespace(args=["query"], mod=0))
            self.assertEqual(self.calls[-1], ((None, "json.exe", "", "", "normal"), ["query"]))
            self.assertEqual(custom_calls, [])
        self.path.write_text("{}", encoding="utf-8")
        reload_commands()
        matching = [item for item in self.window.launcher.command_list if item[0].lower() == "stamp"]
        self.assertEqual(matching, [custom])
        matching[0][1](SimpleNamespace(args=["custom"], mod=0))
        self.assertEqual(custom_calls, [["custom"]])

    def test_main_reload_removes_or_replaces_custom_commands_without_save_rerunning_hooks(self):
        from test_input_settings import InputSettingsTests

        main = InputSettingsTests("test_defaults_deleted_settings_and_hook_order")
        main.setUp()
        self.addCleanup(main.doCleanups)
        self.env["dataPath"] = lambda: main.temp.name
        Path(main.temp.name, "commands.json").write_text("{}", encoding="utf-8")
        main.namespace["clnch_standard"].configure = self.env["configure"]
        main.window.ShellExecuteCommand = self.shell_command
        main.window.show = lambda visible: None
        main.window.isVisible = lambda: True
        template = ('def configure(window):\n'
                    '    window.events.append("hook-{version}")\n'
                    '    def command_stamp(info):\n'
                    '        window.events.append("stamp-{version}")\n'
                    '    window.launcher.command_list += [("stamp", command_stamp)]\n')
        for version in ("old", "new"):
            main.configure(template.format(version=version))
            dict(main.window.launcher.command_list)["new"](SimpleNamespace(args=[], mod=0))
            reload_commands = self.editor_calls[-1]["on_saved"]
            for _ in range(2):
                reload_commands()
                matches = [item for item in main.window.launcher.command_list if item[0] == "stamp"]
                self.assertEqual(len(matches), 1)
                matches[0][1](SimpleNamespace(args=[], mod=0))
                self.assertEqual(main.events[-1], "stamp-" + version)
            self.assertEqual(main.events.count("hook-" + version), 1)
            main.configure("")
            self.assertNotIn("stamp", dict(main.window.launcher.command_list))

    def test_command_name_and_custom_commands_are_available_with_json(self):
        calls = []
        self.window.launcher.command_list = [("custom", lambda info: calls.append(list(info.args)))]
        self.configure({"command": {"target": action("tool.exe")}})
        self.run_command("command")
        self.assertEqual(self.calls[-1][0][1], "tool.exe")
        self.run_command("custom", ["value"])
        self.assertEqual(calls, [["value"]])

    def test_launcher_priority_alias_boundary_and_completion_after_rebuild(self):
        tree = ast.parse((ROOT / "clnch/clnch_commandline.py").read_text(encoding="utf-8-sig"))
        launcher = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                        and n.name == "commandline_Launcher")
        namespace = {"ckit": SimpleNamespace(CommandInfo=SimpleNamespace),
                     "split_commandline_args": sys.modules["clnch_commandplatform"].split_commandline_args}
        exec(compile(ast.Module(body=[launcher], type_ignores=[]), "launcher-test", "exec"), namespace)  # noqa: S102  # Execute the real input protocol without native imports.
        self.window.launcher = namespace["commandline_Launcher"](self.window)
        self.window.input_settings = {"COMPLETION_MODE": "commands"}
        self.window.commandline_list = [self.window.launcher, "url", "file"]
        builtin_calls, custom_calls = [], []
        def builtin(info):
            builtin_calls.append(list(info.args))
        self.window.launcher.command_list = [("Builtin", builtin)]
        data = {"shared": {"target": action("json.exe")},
                "alias": {"target": action(" SHARED ")},
                "builtin_alias": {"target": action("BUILTIN")}}
        handlers = self.configure(data)
        self.window.launcher.command_list.append(("SHARED", lambda info: custom_calls.append(list(info.args))))
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        line = SimpleNamespace(planCommand=lambda command, info, text: command(info), quit=lambda: None)
        for _ in range(2):
            reload_commands()
            self.assertTrue(self.window.launcher.onEnter(line, "sHaReD;direct", 0))
            self.run_command("alias", ["alias"])
            self.assertEqual(self.calls[-2:], [((None, "json.exe", "", "", "normal"), ["direct"]),
                                              ((None, "json.exe", "", "", "normal"), ["alias"])])
            self.assertEqual(custom_calls, [])
            self.run_command("builtin_alias", ["arg"])
            self.assertEqual(builtin_calls[-1], ["arg"])
            self.assertEqual(self.window.launcher.onCandidate(SimpleNamespace(text="sh")), ["shared", "SHARED"])
            self.assertIs(self.window.commandline_list[0], self.window.launcher)
            self.assertEqual(self.window.commandline_list[2:], ["url", "file"])
            self.assertTrue(self.window.launcher.onEnter(line, " shared ;arg", 0))
            self.assertEqual(self.calls[-1], ((None, "json.exe", "", "", "normal"), ["arg"]))
        del data["shared"]
        self.path.write_text(json.dumps(data), encoding="utf-8")
        reload_commands()
        self.assertTrue(self.window.launcher.onEnter(line, "SHARED;custom", 0))
        self.assertEqual(custom_calls, [["custom"]])
        # Appended custom commands are direct-input entries, not alias targets.
        self.run_command("alias")
        self.assertEqual(self.calls[-1][0][1], "SHARED")
        self.assertEqual(self.window.launcher.onCandidate(SimpleNamespace(text="sh")), ["SHARED"])

    def test_failed_validation_keeps_alias_targets_handlers_and_copy_path(self):
        handlers = self.configure({"alias": {"target": action("child")},
                                   "child": {"target": action("old.exe")}})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        reload_commands = self.editor_calls[-1]["on_saved"]
        before = self.window.launcher.command_list
        self.path.write_text(json.dumps({"child": {"target": action("new.exe")},
                                         "bad": {"target": {"link": 1}}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            reload_commands()
        self.assertIs(self.window.launcher.command_list, before)
        self.run_command("alias")
        self.assertEqual(self.calls[-1][0][1], "old.exe")
        self.window.commandline_edit.getText = lambda: " ALIAS ;arg"
        self.window.cmd_keymap["F12"](None)
        self.assertEqual(self.clipboard, ["old.exe"])
        with patch.object(self.standard, "setClipboardText", side_effect=OSError("clipboard busy")):
            self.window.cmd_keymap["F12"](None)

    def test_invalid_name_reload_preserves_handlers_aliases_and_file(self):
        self.configure({"alias": {"target": action("child")}, "child": {"target": action("old.exe")}})
        self.run_command("new")
        reload_commands = self.editor_calls[-1]["on_saved"]
        before = self.window.launcher.command_list
        data = {"child": {"target": action("new.exe")}, "bad;name": {}}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            reload_commands()
        self.assertIs(self.window.launcher.command_list, before)
        self.assertEqual(self.path.read_bytes(), original)
        self.run_command("alias")
        self.assertEqual(self.calls[-1][0][1], "old.exe")

    def test_cyclic_alias_execution_reports_path_and_keeps_f12_unresolved(self):
        for commands, path in (
            ({"a": {"target": action(" A ")}}, "a → a"),
            ({"_ra": {"target": action("_ra")}}, "_ra → _ra"),
            ({"a": {"target": action("b")}, "b": {"target": action("c")},
              "c": {"target": action("A", "--growing")}}, "a → b → c → a"),
            ({"": {"target": action("b")}, "b": {"target": action("b")}}, "'' → b → b"),
            ({"a": {"on_ctrl": action("b")}, "b": {"target": action("b")}}, "a → b → b"),
        ):
            with self.subTest(path=path):
                handlers = self.configure(commands)
                name = next(iter(commands))
                info = SimpleNamespace(args=[], mod=2 if "on_ctrl" in commands[name] else 0)
                before = vars(info).copy()
                with self.assertRaises(ValueError) as caught:
                    handlers[name](info)
                self.assertNotIsInstance(caught.exception, RecursionError)
                self.assertEqual(str(caught.exception),
                                 self.env["strings"].COMMAND_ALIAS_CYCLE.format(path=path))
                # A failed execution leaves no traversal state on reusable input.
                with self.assertRaises(ValueError):
                    handlers[name](info)
                self.assertEqual(vars(info), before)
                self.window.commandline_edit.getText = lambda name=name: name
                self.window.cmd_keymap["F12"](None)
                self.assertEqual(self.clipboard, [])
                self.assertEqual(self.calls, [])

    def test_alias_traversals_are_independent_and_modifier_self_reference_is_valid(self):
        self.configure({"a": {"target": action("tool.exe"), "on_ctrl": action(" A ")},
                        "b": {"target": action("a")}})
        for name, mod in (("a", 2), ("b", 0), ("b", 0), ("a", 0)):
            self.run_command(name, ["dynamic"], mod)
        self.assertEqual(self.calls, [((None, "tool.exe", "", "", "normal"), ["dynamic"])] * 4)

    def test_elevated_alias_cycle_reports_path_and_finite_nested_elevation_still_runs(self):
        self.configure({"a": {"target": action("b")}, "b": {"target": action("a")}})
        with self.assertRaisesRegex(ValueError, "_ra → a → b → a"):
            self.run_command("_ra", ["a"])
        self.configure({"a": {"target": action("_ra", "a")}})
        with self.assertRaisesRegex(ValueError, "a → _ra → a"):
            self.run_command("a")
        self.configure({"a": {"target": action("_ra")}})
        self.run_command("a", ["a", "tool.exe", "dynamic"])
        self.assertEqual(self.calls, [(("runas", "tool.exe", "", "", "normal"), ["dynamic"])])
        for link in ("_ra tool.exe", "_ra _ra tool.exe"):
            dict(self.window.launcher.command_list)["_ra"](SimpleNamespace(args=[], mod=0, arg_string=link))
            self.assertEqual(self.calls[-1], (("runas", "tool.exe", "", "", None), []))

    def test_alias_failure_uses_existing_notification_and_next_command_runs(self):
        tree = ast.parse((ROOT / "clnch/clnch_inputsession.py").read_text(encoding="utf-8-sig"))
        execute = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                       and node.name == "executeCommand")
        namespace = {}
        exec(compile(ast.Module(body=[execute], type_ignores=[]), "notification-test", "exec"), namespace)  # noqa: S102  # Exercise the existing command error boundary without a GUI.
        handlers = self.configure({"a": {"target": action("a")}, "ok": {"target": action("tool.exe")}})
        history = []
        line = SimpleNamespace(appendHistory=history.append, quit=lambda: history.append("quit"))
        info = SimpleNamespace(args=[], mod=0)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            namespace["executeCommand"](line, handlers["a"], info, "a", True)
        self.assertEqual(output.getvalue(),
                         self.env["strings"].COMMAND_ALIAS_CYCLE.format(path="a → a") + "\n")
        self.assertEqual(history, [])
        namespace["executeCommand"](line, handlers["ok"], info, "ok", False)
        self.assertEqual(history, ["ok"])
        self.assertEqual(self.calls[-1][0][1], "tool.exe")

    def test_elevation_fixed_arguments_and_incoming_context(self):
        handlers = self.configure({"child": {"target": action("tool.exe", "--child", "D:/Child", "minimized")}})
        handlers["_ra"](SimpleNamespace(mod=0, args=[], arg_string='child "a b" --fixed dynamic',
            workdir="D:/Caller", view_mode="maximized"))
        self.assertEqual(self.calls[-1], (("runas", "tool.exe", "--child %param%", "D:/Caller", "maximized"),
                                        ["a b", "--fixed", "dynamic"]))
        count = len(self.calls)
        self.run_command("_ra")
        self.assertEqual(len(self.calls), count)

    def test_live_settings_replacement_does_not_require_new_handlers(self):
        handler = self.configure({"tool": {"target": action("tool.exe")}})["tool"]
        self.window.modifier_settings = {**self.window.modifier_settings, "CTRL_ACTION": "execute"}
        handler(SimpleNamespace(args=["dynamic"], mod=2))
        self.assertEqual(self.calls[-1][0][1], "tool.exe")
        self.window.modifier_settings = {**self.window.modifier_settings, "CTRL_ACTION": "none"}
        handler(SimpleNamespace(args=[], mod=2))
        self.assertEqual(len(self.calls), 1)
        for mod in (1, 3, 5, 7, 8):
            handler(SimpleNamespace(args=[], mod=mod))
        self.assertEqual(len(self.calls), 1)

    def test_edit_list_and_new_callbacks_keep_their_contract(self):
        self.command_list.open_list = lambda *args, **kwargs: self.editor_calls.append(kwargs)
        handlers = self.configure({})
        handlers["new"](SimpleNamespace(args=[], mod=0))
        self.assertIsNone(self.editor_calls[-1]["target_cmd"])
        self.window.commandline_edit.getText = lambda: " Tool ;arg"
        self.window.cmd_keymap["C-e"](None)
        self.assertEqual(self.editor_calls[-1]["target_cmd"], "tool")
        self.window.commandline_edit.getText = lambda: ""
        self.window.cmd_keymap["C-e"](None)
        callbacks = self.editor_calls[-1]
        callbacks["on_edit"]("tool", on_shown=lambda: None)
        self.assertEqual(self.editor_calls[-1]["target_cmd"], "tool")
        self.assertTrue(callable(self.editor_calls[-1]["on_shown"]))
        self.assertEqual(callbacks["on_saved"], self.editor_calls[-1]["on_saved"])

    def install_shell_command(self, *, deferred=False):
        tree = ast.parse((ROOT / "clnch/clnch_mainwindow.py").read_text(encoding="utf-8-sig"))
        main_window = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        shell = next(node for node in main_window.body if isinstance(node, ast.FunctionDef) and node.name == "ShellExecuteCommand")
        misc_tree = ast.parse((ROOT / "clnch/clnch_misc.py").read_text(encoding="utf-8-sig"))
        helpers = [node for node in misc_tree.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("replaceMacro", "joinArgs", "_require_job_queue")]
        namespace = {"os": os, "subprocess": subprocess}
        exec(compile(ast.Module(body=helpers, type_ignores=[]), "shell-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.

        class JobItem:
            def __init__(self, work, finished):
                self.work = work

        self.jobs = []
        queue = SimpleNamespace(enqueue=lambda job: self.jobs.append(job) if deferred else job.work(job))
        namespace.update(ckit=SimpleNamespace(JobItem=JobItem, JobQueue=SimpleNamespace(defaultQueue=lambda: queue)),
            validate_link=sys.modules["clnch_cmdstore"].validate_link,
            unquote_path=sys.modules["clnch_cmdstore"].unquote_path, strings=self.env["strings"],
            clnch_misc=SimpleNamespace(replaceMacro=namespace["replaceMacro"], joinArgs=namespace["joinArgs"],
                                      _require_job_queue=namespace["_require_job_queue"]),
            pyauto=SimpleNamespace(shellExecute=lambda *args: self.calls.append(args)))
        exec(compile(ast.Module(body=[shell], type_ignores=[]), "shell-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.
        self.window.ShellExecuteCommand = lambda *args, **kwargs: namespace["ShellExecuteCommand"](self.window, *args, **kwargs)

    def test_actual_shell_command_expands_macros_and_forwards_view_mode(self):
        self.install_shell_command()
        self.configure({"tool": {"target": action("%STEP1_TEST%/tool.exe", "--fixed", "%STEP1_TEST%", "maximized")}})
        with patch.dict(os.environ, STEP1_TEST="D:/Test"):
            self.run_command("tool", ["a b.txt", "second.txt"])
        self.assertEqual(self.calls[-1], (None, "D:/Test/tool.exe", '--fixed "a b.txt" second.txt', "D:/Test", "maximized"))

        args = ["D:\\日本語 path\\", "", 'a"b', "a\tb"]
        for param, expected in ((None, subprocess.list2cmdline(args)),
                                ("", subprocess.list2cmdline(args)),
                                ("--fixed", "--fixed"),
                                ("--before %param% --after", "--before " + subprocess.list2cmdline(args) + " --after")):
            with self.subTest(param=param), patch.dict(os.environ, STEP1_TEST="D:/Test"):
                command = self.window.ShellExecuteCommand(
                    "open", "%STEP1_TEST%/%param%/%%", param, "%param%", "normal")
                command(SimpleNamespace(args=args))
                path_text = " ".join(args)
                self.assertEqual(self.calls[-1], (
                    "open", "D:/Test/" + path_text + "/%", expected, path_text, "normal"))
                self.assertEqual(args, ["D:\\日本語 path\\", "", 'a"b', "a\tb"])

    def test_shell_auto_workdir_uses_expanded_existing_file_and_preserves_overrides(self):
        self.install_shell_command()
        target = Path(self.temp.name) / "target folder" / "tool.exe"
        target.parent.mkdir()
        target.touch()
        with patch.dict(os.environ, RECRAFT_TARGET=str(target), RECRAFT_WORK=self.temp.name):
            for link, args in ((str(target), []), ("%RECRAFT_TARGET%", []), ("%param%", [str(target)]),
                               ('"' + str(target) + '"', []), ('"%RECRAFT_TARGET%"', []),
                               ('"%param%"', [str(target)])):
                with self.subTest(link=link):
                    self.configure({"tool": {"target": action(link, "--fixed", view_mode="maximized")}})
                    self.run_command("tool", args)
                    expected_args = "--fixed" + (" " + subprocess.list2cmdline(args) if args else "")
                    self.assertEqual(self.calls[-1], (None, str(target), expected_args,
                                                     str(target.parent), "maximized"))
            for outer, middle, child, expected in (
                    ("", "", "%RECRAFT_WORK%", self.temp.name),
                    ("", "%RECRAFT_WORK%", "C:/Child", self.temp.name),
                    ("%RECRAFT_WORK%", "C:/Middle", "C:/Child", self.temp.name)):
                with self.subTest(outer=outer, middle=middle, child=child):
                    self.configure({"outer": {"target": action("middle", workdir=outer)},
                                    "middle": {"target": action("child", workdir=middle)},
                                    "child": {"target": action("%RECRAFT_TARGET%", workdir=child)}})
                    self.run_command("outer")
                    self.assertEqual(self.calls[-1], (None, str(target), "", expected, "normal"))
            for link in (str(target.parent / "missing.exe"), "missing.exe", str(target.parent)):
                self.configure({"tool": {"target": action(link)}})
                self.run_command("tool")
                self.assertEqual(self.calls[-1], (None, link, "", "", "normal"))
            # The public API keeps an empty directory even for an existing file.
            self.window.ShellExecuteCommand(None, str(target), "", "")(SimpleNamespace(args=[]))
            self.assertEqual(self.calls[-1], (None, str(target), "", "", None))
            # An explicitly supplied directory retains priority even if it expands to empty.
            with patch.dict(os.environ, RECRAFT_EMPTY=""):
                self.configure({"tool": {"target": action(str(target), workdir="%RECRAFT_EMPTY%")}})
                self.run_command("tool")
                self.assertEqual(self.calls[-1][3], "")

    def test_auto_workdir_uses_job_time_link_and_does_not_expand_derived_parent(self):
        self.install_shell_command(deferred=True)
        folder = Path(self.temp.name) / "%RECRAFT_LITERAL%"
        folder.mkdir()
        target = folder / "tool.exe"
        target.touch()
        self.configure({"tool": {"target": action("%RECRAFT_TARGET%")}})
        with patch.dict(os.environ, RECRAFT_TARGET="C:/old/tool.exe", RECRAFT_LITERAL="wrong"):
            self.run_command("tool")
            self.assertEqual(self.calls, [])
            os.environ["RECRAFT_TARGET"] = str(target)
            job = self.jobs.pop()
            job.work(job)
        self.assertEqual(self.calls, [(None, str(target), "", str(folder), "normal")])

    def test_registered_shell_rejects_relative_links_and_reports_the_input_alias_once(self):
        self.install_shell_command()
        for link in ("tools/tool.exe", r".\tool.exe", "../folder", r"\tool.exe", "C:tool.exe",
                     "%RECRAFT_RELATIVE%/tool.exe", "%param%"):
            self.configure({"outer": {"target": action("middle", '"tools/tool.exe"')},
                            "middle": {"target": action("child")},
                            "child": {"target": action(link, workdir="C:/Tools")}})
            output = io.StringIO()
            with contextlib.redirect_stdout(output), patch.dict(os.environ, RECRAFT_RELATIVE="tools"):
                self.run_command("outer")
            self.assertEqual(self.calls, [])
            self.assertEqual(output.getvalue().count(self.env["strings"].EXECUTE_ERROR), 1)
            self.assertIn("outer", output.getvalue())
            self.assertIn("Link:", output.getvalue())
        self.configure({"good": {"target": action("notepad.exe", "--fixed"),
                                 "on_ctrl": action("tools/bad.exe")}})
        self.run_command("good", ["../document.txt"])
        self.assertEqual(self.calls[-1], (None, "notepad.exe", "--fixed ../document.txt", "", "normal"))
        self.calls.clear()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.run_command("good", mod=2)
        self.assertEqual(self.calls, [])
        self.assertIn("tools/bad.exe", output.getvalue())

    def test_registered_link_guard_uses_macros_at_job_execution_and_keeps_custom_shell_commands(self):
        self.install_shell_command(deferred=True)
        self.configure({"tool": {"target": action("%RECRAFT_TARGET%")}})
        with patch.dict(os.environ, RECRAFT_TARGET="C:/Tools/tool.exe"):
            self.run_command("tool")
            os.environ["RECRAFT_TARGET"] = "tools/tool.exe"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                job = self.jobs.pop()
                job.work(job)
            self.assertIn("tools/tool.exe", output.getvalue())
        self.assertEqual(self.calls, [])
        self.window.ShellExecuteCommand(None, "tools/custom.exe", "", "")(SimpleNamespace(args=[]))
        job = self.jobs.pop()
        job.work(job)
        self.assertEqual(self.calls[-1][:2], (None, "tools/custom.exe"))

    def test_only_the_selected_modifier_link_is_rejected(self):
        self.install_shell_command()
        modifiers = (("target", 0), ("on_ctrl", 2), ("on_shift", 4), ("on_ctrl_shift", 6))
        for invalid, _ in modifiers:
            self.configure({"tool": {key: action("tools/bad.exe" if key == invalid else "notepad.exe")
                                     for key, _ in modifiers}})
            for key, mod in modifiers:
                self.calls.clear()
                output = io.StringIO()
                with self.subTest(invalid=invalid, selected=key), contextlib.redirect_stdout(output):
                    self.run_command("tool", mod=mod)
                self.assertEqual(bool(self.calls), key != invalid)
                self.assertEqual(bool(output.getvalue()), key == invalid)

    def test_folder_macros_use_alias_arguments_and_reject_relative_results(self):
        target = Path(self.temp.name) / "tool.exe"
        target.touch()
        self.configure({"outer": {"target": action("middle", '"' + str(target) + '"')},
                        "middle": {"target": action("child")}, "child": {"target": action("%param%")}})
        self.window.modifier_settings.update(CTRL_ACTION="mapped_folder", SOURCE_ROOTS=(self.temp.name,),
            CTRL_DESTINATION_ROOT=self.temp.name)
        for mod in (2, 4):
            self.calls.clear()
            self.run_command("outer", mod=mod)
            self.assertEqual(self.calls, [(None, self.temp.name, "", "")])
        self.configure({"outer": {"target": action("child", '"tools/tool.exe"')},
                        "child": {"target": action("%param%")}})
        for mod in (2, 4):
            with self.assertRaises(ValueError):
                self.run_command("outer", mod=mod)

    def test_main_drop_opens_json_editor_with_all_paths(self):
        self.configure({})
        tree = ast.parse((ROOT / "clnch/clnch_mainwindow.py").read_text(encoding="utf-8-sig"))
        main = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        drop = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "_onDropFiles")
        namespace = {}
        exec(compile(ast.Module(body=[drop], type_ignores=[]), "drop-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.
        self.window.hotkey_Activate = lambda: None
        files = ["D:/a b.txt", "D:/second.txt"]
        namespace["_onDropFiles"](self.window, 0, 0, files)
        self.assertEqual(self.editor_calls[-1]["dropped_files"], files)
        self.assertIsNone(self.editor_calls[-1]["target_cmd"])


if __name__ == "__main__":
    unittest.main()
