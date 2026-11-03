"""Input settings checks with native GUI calls replaced; run with Python -B."""
import ast
import configparser
import contextlib
import datetime
import fnmatch
import importlib
import io
import os
import sys
import tempfile
import threading
import traceback
import unittest
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from native_test_support import RUN_DIR
from test_modal_lifecycle import _split_list_result

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_altenterconfig
import clnch_inisettings as ini_settings
import clnch_inputconfig
import clnch_modifierconfig
from clnch_cmdstore import load_commands
from clnch_commandplatform import split_commandline_args


def source_tree(name):
    return ast.parse((ROOT / "clnch" / name).read_text(encoding="utf-8-sig"))


def execute(nodes, namespace):
    import clnch_strings
    namespace["strings"] = clnch_strings
    namespace["ini_settings"] = ini_settings
    namespace["clnch_inputconfig"] = clnch_inputconfig
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "input-settings-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.


class Keymap(dict):
    @staticmethod
    def init():
        pass


class InputSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "custom.py"
        previous = sys.modules.get("custom")
        self.addCleanup(self.restore_module, previous)
        self.ini = {}
        self.events = []
        self.namespace = {
            "pyauto": SimpleNamespace(Window=SimpleNamespace(getForeground=lambda: None)),
            "load_commands": load_commands,
            "split_commandline_args": split_commandline_args,
            "os": os, "sys": sys, "fnmatch": fnmatch, "traceback": traceback, "configparser": configparser,
            "clnch_inputconfig": clnch_inputconfig,
            "clnch_altenterconfig": clnch_altenterconfig,
            "clnch_modifierconfig": clnch_modifierconfig,
            "_commandline_normalize_table": str.maketrans("\t\r\n", "   "),
        }
        helpers = [n for n in source_tree("clnch_misc.py").body
                   if isinstance(n, ast.FunctionDef) and n.name in ("normalizeCommandLineText", "_require_data_path", "commandlineArgumentStart")]
        execute(helpers, self.namespace)
        self.namespace["clnch_misc"] = SimpleNamespace(
            normalizeCommandLineText=self.namespace["normalizeCommandLineText"],
            commandlineArgumentStart=self.namespace["commandlineArgumentStart"],
            _require_data_path=self.namespace["_require_data_path"])
        classes = [n for n in source_tree("clnch_commandline.py").body if isinstance(n, ast.ClassDef)]
        execute(classes, self.namespace)
        self.namespace["clnch_commandline"] = SimpleNamespace(
            **{n.name: self.namespace[n.name] for n in classes})
        self.namespace["ckit"] = SimpleNamespace(
            Keymap=Keymap, FILE_ATTRIBUTE_DIRECTORY=16, dataPath=lambda: self.temp.name,
            ckit_userconfig=SimpleNamespace(), getAppExePath=lambda: self.temp.name)
        self.namespace["clnch_standard"] = SimpleNamespace(
            configure=lambda window, commands: self.events.append("standard-apply"))
        self.namespace["clnch_ini"] = SimpleNamespace(
            get=self.ini_get, set=lambda section, key, value: self.ini.__setitem__((section, key), value),
            remove_option=self.ini_remove,
            ini=SimpleNamespace(options=lambda section: [key for sec, key in self.ini if sec == section]),
            dirty=False, write=self.ini_write)
        main = next(n for n in source_tree("clnch_mainwindow.py").body
                    if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        names = {"configure", "commandLineHistoryLoad", "commandLineHistorySave", "saveState",
                 "command_InsertSpace", "command_ClearInput", "applyInputSettings", "isLauncherActive",
                 "registerConfigCleanup", "_releaseConfigResources", "command_Reload", "destroy"}
        methods = [n for n in main.body if isinstance(n, ast.FunctionDef) and n.name in names]
        test_class = ast.ClassDef(name="Window", bases=[], keywords=[], body=methods, decorator_list=[])
        execute([ast.fix_missing_locations(test_class)], self.namespace)
        self.window = self.namespace["Window"]()
        self.window.custom = None
        self.window.isEnabled = lambda: True
        self.window._config_cleanup = []
        self.window.input_settings = clnch_inputconfig.DEFAULTS.copy()
        self.window.input_settings["HISTORY_MODE"] = "off"
        self.window.commandline_history = []
        self.window.events = self.events
        self.window.command = SimpleNamespace(
            **{name: getattr(self.window, "command_" + name, lambda info=None: None)
               for name in ("RemoveHistory", "ConsoleToggle", "Help", "InsertSpace", "ClearInput", "ContextMenu",
                            "History", "ConfigMenu", "Reload", "About", "Quit")})
        self.window.launcher = self.namespace["commandline_Launcher"](self.window)
        self.window.active = False
        self.window.initialized = True
        self.text = ["unchanged"]
        self.window.commandline_edit = SimpleNamespace(
            getAutoComplete=lambda: True,
            setText=lambda text: self.text.__setitem__(0, text),
            insertText=lambda text: self.text.__setitem__(0, self.text[0] + text))
        self.window.removeKeyMessage = lambda: None
        self.window.width = lambda: 18
        self.window.height = lambda: 1
        self.window.console_window = SimpleNamespace(
            opened=False, saveState=lambda: self.events.append("console-save"))
        session = next(n for n in source_tree("clnch_inputsession.py").body
                       if isinstance(n, ast.ClassDef) and n.name == "_CommandLineSession")
        execute([session], self.namespace)
        self.commandline = SimpleNamespace(window=self.window, preserve_argument_text=True)
        self.namespace["appendHistory"] = self.namespace["_CommandLineSession"].appendHistory
        handlers = self.namespace["_LauncherInputHandlers"](self.window)
        self.namespace["onCandidate"] = handlers.onCandidate
        self.namespace["onKeyDown"] = handlers.onKeyDown

    @staticmethod
    def restore_module(previous):
        if previous is None:
            sys.modules.pop("custom", None)
        else:
            sys.modules["custom"] = previous

    def ini_remove(self, section, key):
        removed = self.ini.pop((section, key), None) is not None
        if removed:
            self.namespace["clnch_ini"].dirty = True
        return removed

    def ini_write(self):
        self.events.append("ini-write")
        self.namespace["clnch_ini"].dirty = False

    def ini_get(self, section, key, *default):
        if (section, key) in self.ini:
            return self.ini[section, key]
        if default:
            return default[0]
        raise configparser.NoOptionError(key, section)

    def configure(self, text="", **settings):
        for name in clnch_inputconfig.DEFAULTS:
            self.ini.pop(("INPUT", name.lower()), None)
        for name, value in settings.items():
            self.ini["INPUT", name.lower()] = str(int(value)) if type(value) is bool else value
        self.path.write_text(text, encoding="utf-8")
        self.window.configure()

    def test_defaults_deleted_settings_and_hook_order(self):
        self.configure('HISTORY_MODE="session"\nSPACE_ACTION="complete"\n'
                       'def configure(window):\n'
                       '    window.events.append("local-apply")\n'
                       '    window.keymap["Space"]="custom"\n')
        self.assertEqual(self.events, ["standard-apply", "local-apply"])
        self.assertEqual(self.window.input_settings, clnch_inputconfig.DEFAULTS)
        self.assertEqual({name for name, handler in self.window.launcher.command_list},
            {"history", "config", "reload", "about", "quit"})
        self.assertEqual(self.window.keymap["Space"], "custom")
        self.assertIs(self.window.keymap["C-F10"], self.window.command.ConsoleToggle)
        self.assertNotIn("C-F10", self.window.cmd_keymap)
        self.configure("")
        self.assertEqual(self.window.input_settings, clnch_inputconfig.DEFAULTS)
        self.assertFalse(hasattr(self.window.custom, "HISTORY_MODE"))
        self.assertFalse(hasattr(self.window.custom, "configure"))
        self.window.keymap["Space"](None)
        self.assertEqual(self.text[0], "unchanged ")
        self.assertNotIn("Tab", self.window.cmd_keymap)
        self.configure(TAB_ACTION="clear")
        self.window.cmd_keymap["Tab"](None)
        self.assertEqual(self.text[0], "")
        self.configure(SPACE_ACTION="complete", TAB_ACTION="complete")
        self.assertNotIn("Space", self.window.keymap)
        self.assertNotIn("Tab", self.window.cmd_keymap)
        self.path.unlink()
        self.ini.clear()
        self.window.configure()
        self.assertEqual(self.window.input_settings, clnch_inputconfig.DEFAULTS)

    def test_invalid_json_reload_preserves_registration_keys_and_custom_resources(self):
        self.configure('def configure(window):\n    window.launcher.command_list.append(("custom", lambda info: None))\n')
        cleanup = []
        self.window.registerConfigCleanup(lambda: cleanup.append("released"))
        previous_custom = self.window.custom
        previous_commands = self.window.launcher.command_list
        previous_keymap = self.window.keymap
        previous_events = self.events.copy()
        for contents in ('{"bad;name": {}}', '{"bad": {"target": {"link": 1}}}', '{broken'):
            with self.subTest(contents=contents):
                commands_path = Path(self.temp.name, "commands.json")
                commands_path.write_text(contents, encoding="utf-8")
                output = io.StringIO()
                with contextlib.redirect_stderr(output):
                    self.window.command_Reload(None)
                self.assertIn("Error", output.getvalue())
                self.assertIs(self.window.custom, previous_custom)
                self.assertIs(self.window.launcher.command_list, previous_commands)
                self.assertIs(self.window.keymap, previous_keymap)
                self.assertEqual(self.events, previous_events)
                self.assertEqual(cleanup, [])
                self.assertEqual(commands_path.read_text(encoding="utf-8"), contents)
        commands_path.write_text("{}", encoding="utf-8")
        self.window.configure()
        self.assertEqual(cleanup, ["released"])

    def test_builtin_names_execute_case_insensitively_and_completion_prefers_registration(self):
        self.configure(HISTORY_MODE="session")
        self.namespace["ckit"].CommandInfo = SimpleNamespace
        self.window.commandline_history = ["reLOad"]
        for name in ("history", "config", "reload", "about", "quit"):
            for spelling in (name, name.upper(), name.title()):
                with self.subTest(name=name, spelling=spelling):
                    planned = []
                    line = SimpleNamespace(planCommand=lambda *args, planned=planned: planned.append(args), quit=lambda: None)
                    self.assertTrue(self.window.launcher.onEnter(line, spelling + ";KeepCASE", 2))
                    command, info, history = planned.pop()
                    api_name = "ConfigMenu" if name == "config" else name.title()
                    self.assertIs(command, getattr(self.window.command, api_name))
                    self.assertEqual((info.args, info.mod, history), (["KeepCASE"], 2, spelling + ";KeepCASE"))
                    self.namespace["appendHistory"](self.commandline, history)
            self.assertEqual(self.window.commandline_history[0], name.title() + ";KeepCASE")
            self.assertEqual(sum(item.lower() == name + ";keepcase" for item in self.window.commandline_history), 1)
        for mode, expected in (("standard", ["Reload;KeepCASE", "reload"]),
                               ("commands", ["reload"]), ("off", [])):
            self.window.input_settings["COMPLETION_MODE"] = mode
            update = SimpleNamespace(text="re", selectionLeft=lambda: 2)
            self.assertEqual(self.namespace["onCandidate"](update), (expected, 0))

    def test_invalid_json_on_initial_startup_keeps_builtin_and_custom_configuration(self):
        Path(self.temp.name, "commands.json").write_text('{"bad;name": {}}', encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.configure('def configure(window):\n    window.events.append("custom-applied")\n')
        self.assertIn("bad;name", output.getvalue())
        self.assertEqual(self.events, ["standard-apply", "custom-applied"])
        self.assertIn("reload", dict(self.window.launcher.command_list))

    def test_initial_custom_load_failure_keeps_standard_recovery_and_can_reload(self):
        sources = ('def broken(\n', 'raise RuntimeError("load failed")\n',
                   'raise SystemExit("load exit")\n', 'raise KeyboardInterrupt("load interrupt")\n',
                   'configure = None\n', 'configure_ListWindow = 1\n')
        for source in sources:
            with self.subTest(source=source), patch.dict(sys.modules):
                sys.modules.pop("custom", None)
                self.window.custom = None
                self.events.clear()
                self.namespace["ckit"].ckit_userconfig.user_namespace = {"stale": True}
                self.path.write_text(source, encoding="utf-8")
                with contextlib.redirect_stderr(io.StringIO()) as errors, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertIsNone(self.window.command_Reload(None))
                self.assertTrue(errors.getvalue())
                self.assertEqual(output.getvalue(), "")
                self.assertTrue(self.window._config_failed)
                self.assertIsNone(self.window.custom)
                self.assertNotIn("custom", sys.modules)
                self.assertEqual(self.namespace["ckit"].ckit_userconfig.user_namespace, {})
                self.assertEqual(self.events, ["standard-apply"])
                commands = dict(self.window.launcher.command_list)
                self.assertTrue({"config", "reload", "quit", "history", "about"} <= commands.keys())
                for key, name in (("C-S", "ConfigMenu"), ("C-F10", "ConsoleToggle"), ("F1", "Help")):
                    self.assertIs(self.window.keymap[key], getattr(self.window.command, name))
                self.assertEqual(self.window.input_settings, clnch_inputconfig.DEFAULTS)
                self.path.write_text('def configure(window):\n    window.events.append("recovered")\n',
                                     encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    commands["reload"](None)
                self.assertFalse(self.window._config_failed)
                self.assertEqual(self.events, ["standard-apply", "standard-apply", "recovered"])
                self.assertEqual(output.getvalue(), self.namespace["strings"].CONFIG_RELOADED + "\n")

    def test_custom_baseexception_keeps_partial_application_and_suppresses_success(self):
        for exception in ("SystemExit", "KeyboardInterrupt"):
            with self.subTest(exception=exception):
                self.configure()
                self.path.write_text('def configure(window):\n'
                    '    window.keymap["Space"] = "partial"\n'
                    '    window.registerConfigCleanup(lambda: window.events.append("partial-cleanup"))\n'
                    f'    raise {exception}("custom failed")\n', encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()) as output, \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.window.command_Reload(None)
                self.assertIn(exception + ": custom failed", errors.getvalue())
                self.assertEqual(output.getvalue(), "")
                self.assertTrue(self.window._config_failed)
                self.assertEqual(self.window.keymap["Space"], "partial")
                self.events.clear()
                self.configure()
                self.assertEqual(self.events, ["partial-cleanup", "standard-apply"])

    def test_internal_baseexception_is_not_suppressed(self):
        for owner, name in ((clnch_inputconfig, "read"), (self.namespace["clnch_standard"], "configure")):
            with self.subTest(name=name), patch.object(owner, name, side_effect=KeyboardInterrupt("internal")), \
                    self.assertRaisesRegex(KeyboardInterrupt, "internal"):
                self.window.configure()

    def test_reload_application_failure_reports_error_without_success_notification(self):
        self.configure()
        for stage in ("standard", "custom"):
            with self.subTest(stage=stage):
                self.path.write_text('def configure(window):\n'
                    '    window.events.append("custom-applied")\n'
                    + ('    raise RuntimeError("custom failed")\n' if stage == "custom" else ""),
                    encoding="utf-8")
                standard = self.namespace["clnch_standard"].configure
                with patch.object(self.namespace["clnch_standard"], "configure",
                                  side_effect=RuntimeError("standard failed") if stage == "standard" else standard), \
                        contextlib.redirect_stdout(io.StringIO()) as output, \
                        contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertIsNone(self.window.command_Reload(None))
                self.assertIn(stage + " failed", errors.getvalue())
                self.assertNotIn(self.namespace["strings"].CONFIG_RELOADED, output.getvalue())
                self.assertEqual(self.events[-1], "custom-applied")
        self.path.write_text("", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.window.command_Reload(None)
        self.assertEqual(output.getvalue(), self.namespace["strings"].CONFIG_RELOADED + "\n")

    def test_reload_menu_and_command_share_notifications_for_every_stage(self):
        reload_menu = next(n for n in source_tree("clnch_configmenu.py").body
                           if isinstance(n, ast.FunctionDef) and n.name == "_reloadConfigFile")
        execute([reload_menu], self.namespace)
        for route in ("command", "menu"):
            for stage in ("json", "python", "settings", "cleanup", "standard", "custom",
                          "load_exit", "load_interrupt", "cleanup_exit", "cleanup_interrupt",
                          "custom_exit", "custom_interrupt", "list_hook", "success"):
                with self.subTest(route=route, stage=stage):
                    self.ini.clear()
                    self.window._config_cleanup.clear()
                    commands = Path(self.temp.name, "commands.json")
                    commands.write_text("{}", encoding="utf-8")
                    self.configure()
                    previous = self.window.custom
                    if stage == "json":
                        commands.write_text("{broken", encoding="utf-8")
                    elif stage == "python":
                        self.path.write_text("def broken(\n", encoding="utf-8")
                    elif stage == "settings":
                        self.ini["ALT_ENTER", "action"] = "invalid"
                    elif stage.startswith("load_"):
                        exception = "SystemExit" if stage.endswith("exit") else "KeyboardInterrupt"
                        self.path.write_text(f'raise {exception}("load failed")\n', encoding="utf-8")
                    elif stage.startswith("cleanup"):
                        exception = {"cleanup": RuntimeError, "cleanup_exit": SystemExit,
                                     "cleanup_interrupt": KeyboardInterrupt}[stage]
                        def fail_cleanup(exception=exception):
                            raise exception("cleanup failed")
                        self.window.registerConfigCleanup(fail_cleanup)
                    elif stage.startswith("custom"):
                        exception = {"custom": "RuntimeError", "custom_exit": "SystemExit",
                                     "custom_interrupt": "KeyboardInterrupt"}[stage]
                        self.path.write_text(f'def configure(window):\n    raise {exception}("custom failed")\n',
                                             encoding="utf-8")
                    elif stage == "list_hook":
                        self.path.write_text('configure_ListWindow = None\n', encoding="utf-8")
                    standard = self.namespace["clnch_standard"].configure
                    with patch.object(self.namespace["clnch_standard"], "configure",
                                      side_effect=RuntimeError("standard failed") if stage == "standard" else standard), \
                            contextlib.redirect_stdout(io.StringIO()) as output, \
                            contextlib.redirect_stderr(io.StringIO()) as errors:
                        result = (self.window.command_Reload(None) if route == "command"
                                  else self.namespace["_reloadConfigFile"](self.window))
                    self.assertIs(result, None if route == "command" else False)
                    self.assertEqual(output.getvalue(),
                                     self.namespace["strings"].CONFIG_RELOADED + "\n" if stage == "success" else "")
                    self.assertEqual(bool(errors.getvalue()), stage != "success")
                    if stage not in ("cleanup", "cleanup_exit", "cleanup_interrupt",
                                     "standard", "custom", "custom_exit", "custom_interrupt", "success"):
                        self.assertIs(self.window.custom, previous)
                    else:
                        self.assertIsNot(self.window.custom, previous)

    def test_main_f1_is_standard_and_keeps_input_without_adding_history(self):
        self.configure()
        self.assertIs(self.window.keymap["F1"], self.window.command.Help)
        self.assertNotIn("F1", self.window.cmd_keymap)
        self.namespace["ckit"].KeyEvent = lambda vk, mod: (vk, mod)
        self.namespace["ckit"].CommandInfo = SimpleNamespace
        self.window.cmd_keymap.table = {}
        self.window.keymap.table = {(112, 0): self.window.keymap["F1"]}
        calls = []
        commandline = SimpleNamespace(getText=lambda: "keep;日本語",
            executeCommand=lambda *args, **kwargs: calls.append((args, kwargs)))
        self.assertTrue(self.namespace["onKeyDown"](commandline, 112, 0))
        args, kwargs = calls[0]
        self.assertIs(args[0], self.window.command.Help)
        self.assertEqual(args[1].args, ["keep;日本語"])
        self.assertIsNone(args[2])
        self.assertEqual(kwargs, {"quit": False})
        self.configure('def configure(window):\n    window.keymap["F1"]="custom-help"\n')
        self.assertEqual(self.window.keymap["F1"], "custom-help")
        self.configure()
        self.assertIs(self.window.keymap["F1"], self.window.command.Help)

    def test_main_ctrl_s_opens_config_without_changing_input_or_history(self):
        main = next(n for n in source_tree("clnch_mainwindow.py").body
                    if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        config = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "command_ConfigMenu")
        execute([config], self.namespace)
        self.namespace["executeCommand"] = self.namespace["_CommandLineSession"].executeCommand
        calls = []
        self.namespace["clnch_configmenu"] = SimpleNamespace(doConfigMenu=calls.append)
        self.namespace["ckit"].KeyEvent = lambda vk, mod: (vk, mod)
        self.namespace["ckit"].CommandInfo = SimpleNamespace
        self.window.command.ConfigMenu = self.namespace["command_ConfigMenu"].__get__(self.window)
        for text in ("", "keep;日本語  input"):
            with self.subTest(text=text):
                self.configure()
                self.window.commandline_history[:] = ["previous"]
                self.assertIs(self.window.keymap["C-S"], self.window.command.ConfigMenu)
                self.assertNotIn("C-S", self.window.cmd_keymap)
                self.window.cmd_keymap.table = {}
                self.window.keymap.table = {(83, 2): self.window.keymap["C-S"]}
                commandline = SimpleNamespace(getText=lambda text=text: text,
                    setText=self.fail, setSelection=self.fail, paint=self.fail,
                    appendHistory=self.fail, quit=lambda: self.fail("input loop ended"))
                commandline.executeCommand = self.namespace["executeCommand"].__get__(commandline)
                self.assertTrue(self.namespace["onKeyDown"](commandline, 83, 2))
                self.assertIs(calls[-1], self.window)
                self.assertEqual(commandline.getText(), text)
                self.assertEqual(self.window.commandline_history, ["previous"])
        self.assertEqual(len(calls), 2)
        self.configure('def configure(window):\n    window.keymap["C-S"]="custom-config"\n')
        self.assertEqual(self.window.keymap["C-S"], "custom-config")
        self.configure()
        self.assertIs(self.window.keymap["C-S"], self.window.command.ConfigMenu)

    def test_local_sample_is_inactive_and_activated_examples_use_current_hooks(self):
        self.enterContext(patch.object(sys, "path", [*sys.path, str(ROOT / "extensions")]))
        source = (ROOT / "samples/_custom.py").read_text(encoding="utf-8")
        self.assertFalse((ROOT / "samples/_config.py").exists())
        disabled = {}
        execute(ast.parse(source).body, disabled)
        enabled = source
        for name in ("stamp", "netdrive", "clock", "completion_keys", "list_keys"):
            enabled = enabled.replace(f"#    import {name}\n", f"    import {name}\n")
            enabled = enabled.replace(f"#    {name}.configure(window)", f"    {name}.configure(window)")
        namespace = {}
        execute(ast.parse(enabled).body, namespace)
        calls, connections = [], []
        exit_code = [0]
        def process(*args, **kwargs):
            calls.append((args, kwargs))
            return exit_code[0]
        window = SimpleNamespace(clock_format="default", keymap={},
            command=SimpleNamespace(AutoCompleteToggle=object(), CursorUp=object(), CursorDown=object()),
            launcher=SimpleNamespace(command_list=[("existing", object())]), subProcessCall=process)
        copied = []
        fixed_time = datetime.datetime(2026, 10, 18, 15, 30, 0)
        with patch.dict(sys.modules, {"clnch_misc": SimpleNamespace(checkNetConnection=connections.append),
                                      "ckit": SimpleNamespace(setClipboardText=copied.append),
                                      "datetime": SimpleNamespace(datetime=SimpleNamespace(now=lambda: fixed_time))}):
            disabled["configure"](window)
            disabled["configure_ListWindow"](window)
            for name in ("stamp", "netdrive", "clock", "completion_keys", "list_keys"):
                module = __import__(name)
                self.assertTrue(callable(module.configure))
            self.assertEqual(window.launcher.command_list[0][0], "existing")
            self.assertEqual(len(window.launcher.command_list), 1)
            self.assertEqual(window.keymap, {})
            self.assertEqual(window.clock_format, "default")
            self.assertEqual(calls, [])
            self.assertEqual(connections, [])
            self.assertEqual(copied, [])
            namespace["configure"](window)
        self.assertIs(window.keymap["A-Space"], window.command.AutoCompleteToggle)
        self.assertEqual(window.clock_format, "%Y/%m/%d(%a) %H:%M:%S")
        self.assertNotIn("F1", window.keymap)
        self.assertNotIn("C-E", window.keymap)
        self.assertEqual([name for name, _ in window.launcher.command_list], ["existing", "stamp", "NetDrive"])
        dict(window.launcher.command_list)["stamp"](SimpleNamespace(args=[]))
        self.assertEqual(copied, ["2026-10-18_153000"])
        net_drive = dict(window.launcher.command_list)["NetDrive"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            net_drive(SimpleNamespace(args=["L", "//server/share"]))
            net_drive(SimpleNamespace(args=["L"]))
        self.assertEqual(connections, ["//server/share"])
        self.assertEqual(calls[0], ((["net", "use", "L:", os.path.normpath("//server/share"), "/yes"],),
                                   {"cwd": None, "env": None, "enable_cancel": False}))
        self.assertEqual(calls[1][0], (["net", "use", "L:", "/D"],))
        self.assertIn("Mapped drive L: to //server/share.", out.getvalue())
        self.assertIn("Drive L: has been unmapped.", out.getvalue())
        before = len(calls)
        with contextlib.redirect_stdout(io.StringIO()):
            net_drive(SimpleNamespace(args=[]))
            net_drive(SimpleNamespace(args=["L", "share", "extra"]))
        self.assertEqual(len(calls), before)
        exit_code[0] = 1
        with contextlib.redirect_stdout(io.StringIO()) as failed:
            net_drive(SimpleNamespace(args=["L"]))
        self.assertEqual(failed.getvalue(), "")
        namespace["configure_ListWindow"](window)
        self.assertIs(window.keymap["C-P"], window.command.CursorUp)
        self.assertIs(window.keymap["C-N"], window.command.CursorDown)

    def test_template_enables_stamp_by_uncommenting_only_its_two_lines(self):
        self.enterContext(patch.object(sys, "path", [*sys.path, str(ROOT / "extensions")]))
        source = (ROOT / "samples/_custom.py").read_text(encoding="utf-8")
        self.configure(source)
        self.assertNotIn("stamp", dict(self.window.launcher.command_list))
        enabled = "\n".join(line[1:] if line in ("#    import stamp", "#    stamp.configure(window)") else line
                            for line in source.splitlines())
        copied = []
        with patch.dict(sys.modules, {"ckit": SimpleNamespace(setClipboardText=copied.append)}):
            self.configure(enabled)
        commands = dict(self.window.launcher.command_list)
        self.assertIn("stamp", commands)
        self.assertNotIn("NetDrive", commands)
        self.assertNotIn("A-Space", self.window.keymap)
        commands["stamp"](SimpleNamespace(args=[]))
        self.assertEqual(len(copied), 1)
        self.assertRegex(copied[0], r"^\d{4}-\d{2}-\d{2}_\d{6}$")
        self.configure(source)
        self.assertNotIn("stamp", dict(self.window.launcher.command_list))

    def test_explicit_extensions_reload_order_and_disable(self):
        extensions = Path(self.temp.name) / "extensions"
        scripts = Path(self.temp.name) / "scripts"
        extensions.mkdir()
        scripts.mkdir()
        shared = extensions / "rc_test_shared.py"
        personal = scripts / "rc_test_personal.py"
        shared.write_text('VALUE = "old"\n'
                          'def configure(window):\n'
                          '    window.events.append(VALUE)\n'
                          '    window.keymap["Space"] = VALUE\n'
                          '    window.launcher.command_list.append(("shared", VALUE))\n',
                          encoding="utf-8")
        personal.write_text('def configure(window):\n'
                            '    window.events.append("personal")\n'
                            '    window.keymap["Space"] = "personal"\n'
                            'def configure_list(window):\n'
                            '    window.keymap["C-P"] = "personal-list"\n',
                            encoding="utf-8")
        (extensions / "rc_test_unused.py").write_text('raise RuntimeError("must not run")\n', encoding="utf-8")
        with patch.object(sys, "path", [*sys.path, str(extensions), str(scripts)]), patch.dict(sys.modules):
            self.configure()
            self.assertNotIn("rc_test_unused", sys.modules)
            self.assertNotIn("rc_test_shared", sys.modules)
            enabled = ('def configure(window):\n'
                       '    import rc_test_shared, rc_test_personal\n'
                       '    rc_test_shared.configure(window)\n'
                       '    rc_test_personal.configure(window)\n'
                       'def configure_ListWindow(window):\n'
                       '    import rc_test_personal\n'
                       '    rc_test_personal.configure_list(window)\n')
            self.events.clear()
            self.configure(enabled)
            self.assertEqual(self.events, ["standard-apply", "old", "personal"])
            self.assertEqual(self.window.keymap["Space"], "personal")
            listing = SimpleNamespace(keymap={})
            self.window.custom.configure_ListWindow(listing)
            self.assertEqual(listing.keymap, {"C-P": "personal-list"})
            module = sys.modules["rc_test_shared"]
            shared.write_text(shared.read_text(encoding="utf-8").replace('"old"', '"new"'), encoding="utf-8")
            self.events.clear()
            self.configure(enabled)
            self.assertIsNot(sys.modules["rc_test_shared"], module)
            self.assertEqual(self.events, ["standard-apply", "new", "personal"])
            self.assertEqual([name for name, _ in self.window.launcher.command_list].count("shared"), 1)
            self.configure()
            self.assertNotIn("configure_ListWindow", vars(self.window.custom))
            self.assertNotIn("shared", dict(self.window.launcher.command_list))
            self.assertNotEqual(self.window.keymap["Space"], "personal")

    def test_dynamic_import_refreshes_top_level_and_both_hooks(self):
        import py_compile
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        original_import = importlib.import_module
        for route in ("top", "configure", "configure_ListWindow"):
            with self.subTest(route=route), patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
                name = "rc_dynamic_" + route
                source = scripts / (name + ".py")
                source.write_text('VALUE = "old"\n', encoding="utf-8")
                py_compile.compile(str(source), doraise=True)
                timestamp = source.stat().st_mtime_ns
                importlib.invalidate_caches()
                cached = importlib.import_module(name)
                if route == "top":
                    text = (f'import importlib\nselected = importlib.import_module({name!r})\n'
                            'def configure(window):\n    window.value = selected.VALUE\n')
                else:
                    text = (f'import importlib\ndef {route}(window):\n'
                            f'    window.value = importlib.import_module({name!r}).VALUE\n')
                self.configure(text)
                listing = SimpleNamespace()
                if route == "configure_ListWindow":
                    self.assertNotIn(name, self.window.custom._config_modules.modules)
                    self.window.custom.configure_ListWindow(listing)
                target = listing if route == "configure_ListWindow" else self.window
                self.assertEqual(target.value, "old")
                first = sys.modules[name]
                self.assertIsNot(first, cached)
                source.write_text('VALUE = "new"\n', encoding="utf-8")
                os.utime(source, ns=(timestamp, timestamp))
                self.configure(text)
                if route == "configure_ListWindow":
                    listing = SimpleNamespace()
                    self.window.custom.configure_ListWindow(listing)
                    target = listing
                self.assertEqual(target.value, "new")
                self.assertIsNot(sys.modules[name], first)
                self.assertIs(importlib.import_module, original_import)
                self.assertNotIn(self.window.custom._config_modules, sys.meta_path)

    def test_dynamic_import_local_packages_dependencies_and_cycles(self):
        extensions = Path(self.temp.name) / "extensions"
        scripts = Path(self.temp.name) / "scripts"
        extensions.mkdir()
        scripts.mkdir()
        for namespace in (False, True):
            with self.subTest(namespace=namespace), patch.object(sys, "path", [*sys.path, str(extensions), str(scripts)]), patch.dict(sys.modules):
                name = "rc_dynamic_pkg_" + str(int(namespace))
                package = scripts / name
                package.mkdir()
                if not namespace:
                    (package / "__init__.py").write_text('VERSION = "old"\n', encoding="utf-8")
                (extensions / "rc_dynamic_entry.py").write_text(
                    'from importlib import import_module as load\n'
                    f'def read():\n    return load({(name + ".child")!r}).read()\n', encoding="utf-8")
                (package / "child.py").write_text(
                    'import importlib.util\nfrom . import sibling\n'
                    'def read():\n'
                    '    assert importlib.util.resolve_name(".leaf", __package__) == __package__ + ".leaf"\n'
                    '    return importlib.import_module(".leaf", __package__).VALUE\n', encoding="utf-8")
                (package / "sibling.py").write_text('from . import child\n', encoding="utf-8")
                leaf = package / "leaf.py"
                leaf.write_text('VALUE = "old"\nDELETED = True\n', encoding="utf-8")
                text = ('import rc_dynamic_entry\ndef configure(window):\n'
                        '    window.value = rc_dynamic_entry.read()\n')
                importlib.invalidate_caches()
                cached = importlib.import_module(name + ".child")
                self.configure(text)
                self.assertEqual(self.window.value, "old")
                self.assertIsNot(sys.modules[name + ".child"], cached)
                first_package = sys.modules[name]
                leaf.write_text('VALUE = "new"\n', encoding="utf-8")
                if not namespace:
                    (package / "__init__.py").write_text('VERSION = "new"\n', encoding="utf-8")
                self.configure(text)
                self.assertEqual(self.window.value, "new")
                self.assertFalse(hasattr(sys.modules[name + ".leaf"], "DELETED"))
                self.assertIsNot(sys.modules[name], first_package)
                if not namespace:
                    self.assertEqual(sys.modules[name].VERSION, "new")

    def test_dynamic_import_load_failure_restores_generation_and_cached_package(self):
        scripts = Path(self.temp.name) / "scripts"
        package = scripts / "rc_dynamic_safe"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('', encoding="utf-8")
        child = package / "child.py"
        child.write_text('VALUE = "old"\n', encoding="utf-8")
        text = ('from importlib import import_module\n'
                'selected = import_module("rc_dynamic_safe.child")\n'
                'def configure(window):\n'
                '    window.keymap["Space"] = selected.VALUE\n'
                '    window.registerConfigCleanup(lambda: window.events.append("cleanup"))\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.configure(text)
            previous = self.window.custom, self.window.keymap, sys.modules["rc_dynamic_safe.child"]
            old_package = sys.modules["rc_dynamic_safe"]
            for source in ('bad syntax !!!', 'raise RuntimeError("load")\n', None, 'VALUE = "new"\n'):
                with self.subTest(source=source):
                    if source is None:
                        child.unlink()
                    else:
                        child.write_text(source, encoding="utf-8")
                    self.events.clear()
                    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as output:
                        # A later validation failure must also restore a successfully staged import.
                        self.path.write_text(text + ('configure_ListWindow = None\n' if source == 'VALUE = "new"\n' else ''),
                                             encoding="utf-8")
                        self.window.command_Reload(None)
                    self.assertEqual((self.window.custom, self.window.keymap,
                                      sys.modules["rc_dynamic_safe.child"]), previous)
                    self.assertIs(sys.modules["rc_dynamic_safe"], old_package)
                    self.assertIs(old_package.child, previous[2])
                    self.assertIs(sys.modules["custom"], previous[0])
                    self.assertTrue(previous[0]._config_modules.active)
                    self.assertEqual(self.events, [])
                    self.assertEqual(output.getvalue(), "")
            self.configure(text)
            self.assertEqual(self.window.keymap["Space"], "new")
            self.assertEqual(self.events, ["cleanup", "standard-apply"])

    def test_dynamic_import_hook_failure_keeps_partial_application_contract(self):
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        child = scripts / "rc_dynamic_partial.py"
        child.write_text('bad syntax !!!', encoding="utf-8")
        text = ('import importlib\ndef configure(window):\n'
                '    window.keymap["Space"] = "partial"\n'
                '    window.registerConfigCleanup(lambda: window.events.append("partial-cleanup"))\n'
                '    importlib.import_module("rc_dynamic_partial")\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.path.write_text(text, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as output:
                self.window.command_Reload(None)
            self.assertTrue(self.window._config_failed)
            self.assertEqual(self.window.keymap["Space"], "partial")
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("rc_dynamic_partial", sys.modules)
            self.events.clear()
            child.write_text('VALUE = "fixed"\n', encoding="utf-8")
            self.configure(text)
            self.assertFalse(self.window._config_failed)
            self.assertEqual(self.events, ["partial-cleanup", "standard-apply"])

    def test_dynamic_import_leaves_unrelated_imports_and_other_threads_unchanged(self):
        scripts = Path(self.temp.name) / "scripts"
        outside = Path(self.temp.name) / "outside"
        scripts.mkdir()
        outside.mkdir()
        (outside / "rc_dynamic_external.py").write_text('import importlib\nVALUE = "outside"\n', encoding="utf-8")
        for name in ("unrelated", "worker"):
            (scripts / ("rc_dynamic_" + name + ".py")).write_text('VALUE = "old"\n', encoding="utf-8")
        (scripts / "rc_dynamic_unused.py").write_text('raise RuntimeError("unused")\n', encoding="utf-8")
        (scripts / "rc_dynamic_selected.py").write_text(
            'import rc_dynamic_probe\nrc_dynamic_probe.check()\nVALUE = "selected"\n', encoding="utf-8")
        original_import = importlib.import_module
        def check():
            self.assertIs(importlib.import_module, original_import)
            worker = threading.Thread(target=lambda: original_import("rc_dynamic_worker"))
            worker.start()
            worker.join(2)
            self.assertFalse(worker.is_alive())
        text = ('import importlib, os, clnch_inputconfig\ndef configure(window):\n'
                '    window.value = importlib.import_module("rc_dynamic_selected").VALUE\n'
                '    window.external = importlib.import_module("rc_dynamic_external")\n')
        with patch.object(sys, "path", [*sys.path, str(outside), str(scripts)]), patch.dict(sys.modules):
            sys.modules["rc_dynamic_probe"] = SimpleNamespace(check=check)
            unrelated = original_import("rc_dynamic_unrelated")
            external = original_import("rc_dynamic_external")
            (scripts / "rc_dynamic_unrelated.py").write_text('raise RuntimeError("unrelated")\n', encoding="utf-8")
            (outside / "rc_dynamic_external.py").write_text('raise RuntimeError("outside")\n', encoding="utf-8")
            for _ in range(2):
                self.configure(text)
                self.assertFalse(self.window._config_failed)
                self.assertEqual(self.window.value, "selected")
                self.assertIs(self.window.external, external)
                self.assertIs(external.importlib, importlib)
                self.assertIs(sys.modules["rc_dynamic_unrelated"], unrelated)
                self.assertIs(sys.modules["os"], os)
                self.assertIs(sys.modules["clnch_inputconfig"], clnch_inputconfig)
                self.assertNotIn("rc_dynamic_unused", sys.modules)
                self.assertNotIn("rc_dynamic_worker", self.window.custom._config_modules.modules)
                self.assertIn("rc_dynamic_worker", sys.modules)
                self.assertEqual(sys.meta_path.count(self.window.custom._config_modules), 0)

    def test_extension_search_paths_preserve_core_and_shared_priority(self):
        directories = [Path(self.temp.name) / name for name in ("core", "extensions", "scripts")]
        for directory in directories:
            directory.mkdir()
            (directory / "rc_test_priority.py").write_text(f"SOURCE = {directory.name!r}\n", encoding="utf-8")
        with patch.object(sys, "path", [*sys.path, *map(str, directories)]), patch.dict(sys.modules):
            rc_test_priority = importlib.import_module("rc_test_priority")
            self.assertEqual(rc_test_priority.SOURCE, "core")
            del sys.modules["rc_test_priority"]
            sys.path.remove(str(directories[0]))
            rc_test_priority = importlib.import_module("rc_test_priority")
            self.assertEqual(rc_test_priority.SOURCE, "extensions")

    def test_reload_dependency_cycle_from_import_deletion_and_pyc_cache(self):
        scripts = Path(self.temp.name) / "scripts"
        package = scripts / "rc_reload_pkg"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('from .entry import value\n', encoding="utf-8")
        entry = package / "entry.py"
        entry.write_text('from . import leaf\ndef value():\n    return leaf.VALUE\n', encoding="utf-8")
        leaf = package / "leaf.py"
        leaf.write_text('from . import entry\nVALUE = "old"\nDELETED = True\n', encoding="utf-8")
        import py_compile
        py_compile.compile(str(leaf), doraise=True)
        timestamp = leaf.stat().st_mtime_ns
        text = ('from rc_reload_pkg import value\n'
                'def configure(window):\n'
                '    window.launcher.command_list.append(("value", value))\n'
                '    window.keymap["Space"] = value\n'
                'def configure_ListWindow(window):\n'
                '    from rc_reload_pkg import value\n'
                '    window.value = value()\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.configure(text)
            old = sys.modules["rc_reload_pkg.leaf"]
            old_ref = weakref.ref(old)
            self.assertEqual(self.window.keymap["Space"](), "old")
            # Same timestamp/size, then deletion of a definition on the next pass.
            leaf.write_text(leaf.read_text(encoding="utf-8").replace('"old"', '"new"'), encoding="utf-8")
            os.utime(leaf, ns=(timestamp, timestamp))
            self.configure(text)
            self.assertEqual(self.window.keymap["Space"](), "new")
            leaf.write_text('from . import entry\nVALUE = "end"\n', encoding="utf-8")
            self.configure(text)
            self.assertFalse(hasattr(sys.modules["rc_reload_pkg.leaf"], "DELETED"))
            listing = SimpleNamespace()
            self.window.custom.configure_ListWindow(listing)
            self.assertEqual(listing.value, "end")
            self.assertEqual(dict(self.window.launcher.command_list)["value"](), "end")
            del old
            import gc
            gc.collect()
            self.assertIsNone(old_ref())
            self.configure()
            self.assertNotIn("rc_reload_pkg", sys.modules)
            self.assertNotIn("value", dict(self.window.launcher.command_list))

    def test_reload_load_failure_preserves_modules_keys_namespace_and_resources(self):
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        module = scripts / "rc_reload_safe.py"
        module.write_text('VALUE = "old"\n', encoding="utf-8")
        text = ('from rc_reload_safe import VALUE\n'
                'def configure(window):\n'
                '    window.keymap["Space"] = VALUE\n'
                '    window.registerConfigCleanup(lambda: window.events.append("cleanup"))\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.configure(text)
            previous = self.window.custom, self.window.keymap, sys.modules["rc_reload_safe"]
            for source in ('bad syntax !!!', 'raise RuntimeError("load")\n',
                           'raise SystemExit("load exit")\n', 'raise KeyboardInterrupt("load interrupt")\n', None):
                with self.subTest(source=source):
                    if source is None:
                        module.unlink()
                    else:
                        module.write_text(source, encoding="utf-8")
                    self.events.clear()
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.configure(text)
                    self.assertEqual((self.window.custom, self.window.keymap,
                                      sys.modules["rc_reload_safe"]), previous)
                    self.assertIs(sys.modules["custom"], previous[0])
                    self.assertIs(self.namespace["ckit"].ckit_userconfig.user_namespace, vars(previous[0]))
                    self.assertTrue(self.window._config_failed)
                    self.assertEqual(self.events, [])
            module.write_text('VALUE = "new"\n', encoding="utf-8")
            self.configure(text)
            self.assertEqual(self.events, ["cleanup", "standard-apply"])
            self.assertEqual(self.window.keymap["Space"], "new")

    def test_invalid_list_hook_preserves_old_generation_before_cleanup(self):
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        module = scripts / "rc_list_safe.py"
        module.write_text('VALUE = "old"\n', encoding="utf-8")
        text = ('import rc_list_safe\n'
                'def configure(window):\n'
                '    window.launcher.command_list.append(("custom", lambda info: rc_list_safe.VALUE))\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.configure(text)
            old = self.window.custom, self.window.keymap, self.window.launcher.command_list, sys.modules["rc_list_safe"]
            def cleanup():
                self.events.append("cleanup")
            self.window.registerConfigCleanup(cleanup)
            module.write_text('VALUE = "new"\n', encoding="utf-8")
            self.events.clear()
            for value in ("None", "1", "'invalid'"):
                with self.subTest(value=value):
                    self.path.write_text(text + f'configure_ListWindow = {value}\n', encoding="utf-8")
                    with contextlib.redirect_stderr(io.StringIO()) as errors, \
                            contextlib.redirect_stdout(io.StringIO()) as output:
                        self.window.command_Reload(None)
                    self.assertIn("custom.configure_ListWindow must be callable", errors.getvalue())
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual((self.window.custom, self.window.keymap,
                                      self.window.launcher.command_list, sys.modules["rc_list_safe"]), old)
                    self.assertIs(sys.modules["custom"], old[0])
                    self.assertIs(self.namespace["ckit"].ckit_userconfig.user_namespace, vars(old[0]))
                    self.assertEqual(self.window._config_cleanup, [cleanup])
                    self.assertEqual(self.events, [])
            self.configure(text + 'def configure_ListWindow(window):\n    window.value = rc_list_safe.VALUE\n')
            listing = SimpleNamespace()
            self.window.custom.configure_ListWindow(listing)
            self.assertEqual(listing.value, "new")
            self.assertEqual(self.events, ["cleanup", "standard-apply"])

    def test_cleanup_baseexceptions_run_all_and_retry_only_failures(self):
        self.configure()
        old = self.window.custom, self.window.keymap, self.window.launcher.command_list
        failures = [True]
        def first():
            self.events.append("first")
            if failures[0]:
                raise KeyboardInterrupt("first failed")
        def last():
            self.events.append("last")
            if failures[0]:
                raise SystemExit("last failed")
        self.window.registerConfigCleanup(first)
        self.window.registerConfigCleanup(lambda: self.events.append("middle"))
        self.window.registerConfigCleanup(last)
        self.events.clear()
        with contextlib.redirect_stderr(io.StringIO()) as errors, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.window.command_Reload(None)
        self.assertIn("SystemExit: last failed", errors.getvalue())
        self.assertIn("KeyboardInterrupt('first failed')", errors.getvalue())
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.events, ["last", "middle", "first", "standard-apply"])
        self.assertEqual(self.window._config_cleanup, [first, last])
        self.assertIsNone(self.window.custom)
        self.assertIsNot(self.window.keymap, old[1])
        self.assertIsNot(self.window.launcher.command_list, old[2])
        self.assertEqual(self.namespace["ckit"].ckit_userconfig.user_namespace, {})
        self.assertIs(sys.modules["custom"], old[0])
        failures[0] = False
        self.events.clear()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.window.command_Reload(None)
        self.assertEqual(self.events, ["last", "first", "standard-apply"])
        self.assertEqual(self.window._config_cleanup, [])
        self.assertEqual(output.getvalue(), self.namespace["strings"].CONFIG_RELOADED + "\n")

    def test_shutdown_custom_baseexception_does_not_interrupt_host_cleanup(self):
        for exception in (SystemExit, KeyboardInterrupt):
            with self.subTest(exception=exception):
                self.events.clear()
                def fail(exception=exception):
                    self.events.append("custom-failed")
                    raise exception("shutdown failed")
                self.window._config_cleanup = [lambda: self.events.append("remaining"), fail]
                self.window.console_window = SimpleNamespace(
                    unregisterStdio=lambda: self.events.append("unregister"),
                    destroy=lambda: self.events.append("console-destroy"))
                self.namespace["ckit"].destroyTemp = lambda: self.events.append("temp-destroy")
                self.namespace["ckit"].TextWindow = SimpleNamespace(
                    destroy=lambda window: self.events.append("native-destroy"))
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.window.destroy()
                self.assertIn(exception.__name__ + ": shutdown failed", errors.getvalue())
                self.assertEqual(self.events, ["custom-failed", "remaining", "unregister",
                                               "console-destroy", "temp-destroy", "native-destroy"])
                self.assertEqual(self.window._config_cleanup, [fail])

    def test_reload_cleanup_order_retry_and_partial_application(self):
        self.configure()
        failure = [True]
        def retry():
            self.events.append("retry")
            if failure[0]:
                raise RuntimeError("running job")
        self.window.registerConfigCleanup(lambda: self.events.append("first"))
        self.window.registerConfigCleanup(retry)
        self.window.registerConfigCleanup(retry)
        self.window.registerConfigCleanup(lambda: self.events.append("last"))
        old = self.window.custom, self.window.keymap
        self.events.clear()
        with contextlib.redirect_stderr(io.StringIO()):
            self.path.write_text('def configure(window):\n    window.events.append("new")\n', encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.window.command_Reload(None)
            self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.events, ["last", "retry", "first", "standard-apply"])
        self.assertIsNone(self.window.custom)
        self.assertIsNot(self.window.keymap, old[1])
        self.assertIs(sys.modules["custom"], old[0])
        self.assertEqual(self.window._config_cleanup, [retry])
        failure[0] = False
        self.events.clear()
        with contextlib.redirect_stderr(io.StringIO()):
            self.configure('def configure(window):\n'
                           '    window.registerConfigCleanup(lambda: window.events.append("partial-cleanup"))\n'
                           '    window.keymap["Space"] = "partial"\n'
                           '    raise RuntimeError("apply")\n')
        self.assertEqual(self.events, ["retry", "standard-apply"])
        self.assertEqual(self.window.keymap["Space"], "partial")
        self.events.clear()
        self.configure()
        self.assertEqual(self.events, ["partial-cleanup", "standard-apply"])
        with self.assertRaises(TypeError):
            self.window.registerConfigCleanup(None)

    def test_reload_ignores_unselected_local_modules_and_product_modules(self):
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        (scripts / "rc_unselected.py").write_text('VALUE = "old"\n', encoding="utf-8")
        (scripts / "rc_never.py").write_text('raise RuntimeError("unselected")\n', encoding="utf-8")
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            unrelated = importlib.import_module("rc_unselected")
            (scripts / "rc_unselected.py").write_text('raise RuntimeError("unrelated")\n', encoding="utf-8")
            for _ in range(3):
                self.configure('import os, clnch_inputconfig\n')
                self.assertIs(sys.modules["rc_unselected"], unrelated)
                self.assertIs(sys.modules["os"], os)
                self.assertIs(sys.modules["clnch_inputconfig"], clnch_inputconfig)
                self.assertNotIn("rc_never", sys.modules)

    def test_reload_namespace_package_and_previously_cached_source(self):
        scripts = Path(self.temp.name) / "scripts"
        package = scripts / "rc_reload_namespace"
        package.mkdir(parents=True)
        child = package / "child.py"
        child.write_text('VALUE = "old"\n', encoding="utf-8")
        text = ('from rc_reload_namespace import child\n'
                'def configure(window):\n    window.keymap["Space"] = child.VALUE\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            old = importlib.import_module("rc_reload_namespace.child")
            child.write_text('VALUE = "new"\n', encoding="utf-8")
            self.configure(text)
            self.assertEqual(self.window.keymap["Space"], "new")
            self.assertIsNot(sys.modules["rc_reload_namespace.child"], old)
            child.write_text('VALUE = "end"\n', encoding="utf-8")
            self.configure(text)
            self.assertEqual(self.window.keymap["Space"], "end")

    def test_reload_staging_serializes_old_worker_import_until_rollback(self):
        scripts = Path(self.temp.name) / "scripts"
        scripts.mkdir()
        leaf = scripts / "rc_thread_leaf.py"
        leaf.write_text('VALUE = "old"\n', encoding="utf-8")
        text = ('import rc_thread_leaf\n'
                'def read():\n    import rc_thread_leaf\n    return rc_thread_leaf.VALUE\n')
        with patch.object(sys, "path", [*sys.path, str(scripts)]), patch.dict(sys.modules):
            self.configure(text)
            previous = self.window.custom
            leaf.write_text('VALUE = "new"\n', encoding="utf-8")
            entered, finished = threading.Event(), threading.Event()
            results = []
            def read():
                entered.set()
                results.append(previous.read())
                finished.set()
            worker = threading.Thread(target=read)
            def defer():
                worker.start()
                self.assertTrue(entered.wait(1))
                self.assertFalse(finished.wait(0.05))
                raise RuntimeError("defer until worker completion")
            self.window.registerConfigCleanup(defer)
            with contextlib.redirect_stderr(io.StringIO()):
                self.configure(text)
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results, ["old"])
            self.assertIsNone(self.window.custom)
            self.assertIs(sys.modules["custom"], previous)
            self.window._config_cleanup.clear()

    def test_reload_removes_clock_overrides(self):
        self.configure('def configure(window):\n'
                       '    window.clock_format = "%H:%M"\n')
        self.assertEqual(self.window.clock_format, "%H:%M")
        self.configure()
        self.assertEqual(self.window.clock_format, self.namespace["strings"].CLOCK_FORMAT)

    def test_modifier_settings_reload_and_invalid_values_keep_active_configuration(self):
        self.ini["MODIFIER", "ctrl_action"] = "mapped_folder"
        self.ini["MODIFIER", "source_roots"] = "C:\\Programs\nD:\\Tools"
        self.ini["MODIFIER", "ctrl_destination_root"] = "D:\\Related"
        self.configure()
        self.assertEqual(self.window.modifier_settings["CTRL_ACTION"], "mapped_folder")
        self.assertEqual(self.window.modifier_settings["SOURCE_ROOTS"], ("C:\\Programs", "D:\\Tools"))
        before = self.window.modifier_settings.copy(), self.window.cmd_keymap, self.events[:]
        self.ini["MODIFIER", "ctrl_action"] = "invalid"
        with contextlib.redirect_stderr(io.StringIO()):
            self.window.configure()
        self.assertEqual((self.window.modifier_settings, self.window.cmd_keymap, self.events), before)
        self.ini.clear()
        self.window.configure()
        self.assertEqual(self.window.modifier_settings, clnch_modifierconfig.DEFAULTS)

    def test_alt_enter_settings_reload_and_invalid_values_keep_active_configuration(self):
        self.ini["ALT_ENTER", "action"] = "application"
        self.ini["ALT_ENTER", "executable"] = "EBWin4.exe"
        self.ini["ALT_ENTER", "arguments"] = "/G=0 /C=1 /M=p /S=%param%"
        self.configure('def configure(window):\n    window.cmd_keymap["A-Return"] = "custom-alt"\n')
        previous = self.window.altenter_settings
        previous_keys = self.window.cmd_keymap
        self.assertEqual(previous["executable"], "EBWin4.exe")
        self.assertEqual(self.window.cmd_keymap["A-Return"], "custom-alt")
        self.ini["ALT_ENTER", "action"] = "invalid"
        with contextlib.redirect_stderr(io.StringIO()):
            self.window.configure()
        self.assertIs(self.window.altenter_settings, previous)
        self.assertIs(self.window.cmd_keymap, previous_keys)
        self.ini.clear()
        self.configure()
        self.assertEqual(self.window.altenter_settings, clnch_altenterconfig.DEFAULTS)

    def test_modified_alt_enter_reload_validates_before_replacing_any_configuration(self):
        for key in clnch_altenterconfig.MODIFIED_SETTINGS:
            section = clnch_altenterconfig.KEYS[key][0]
            self.ini[section, "action"] = "web"
            self.ini[section, "url"] = f"https://example.org/{key}?q=%param%"
        self.configure()
        previous = self.window.altenter_modified_settings
        previous_normal, previous_keys = self.window.altenter_settings, self.window.cmd_keymap
        for key in previous:
            self.assertEqual(previous[key]["url"], f"https://example.org/{key}?q=%param%")
            section = clnch_altenterconfig.KEYS[key][0]
            self.ini[section, "action"] = "properties"
            with contextlib.redirect_stderr(io.StringIO()):
                self.window.configure()
            self.assertIs(self.window.altenter_modified_settings, previous)
            self.assertIs(self.window.altenter_settings, previous_normal)
            self.assertIs(self.window.cmd_keymap, previous_keys)
            self.ini[section, "action"] = "web"
        self.ini.clear()
        self.configure()
        self.assertEqual(self.window.altenter_modified_settings, {
            key: clnch_altenterconfig.MODIFIED_DEFAULTS for key in previous})

    def test_list_hook_uses_fresh_local_namespace(self):
        self.configure('def configure_ListWindow(window):\n    window.customized = True\n')
        hooks = self.namespace["ckit"].ckit_userconfig
        self.assertIs(hooks.user_namespace, vars(self.window.custom))
        # Exercise the same dispatcher used by ListWindow, with the real local namespace.
        tree = ast.parse((ROOT / "ckit/ckit_userconfig.py").read_text(encoding="utf-8"))
        dispatcher = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name == "callConfigFunc")
        namespace = {"user_namespace": hooks.user_namespace}
        execute([dispatcher], namespace)
        window = SimpleNamespace()
        namespace["callConfigFunc"]("configure_ListWindow", window)
        self.assertTrue(window.customized)
        self.configure("")
        self.assertNotIn("configure_ListWindow", hooks.user_namespace)

    def test_list_hook_baseexception_is_reported_and_next_call_continues(self):
        tree = ast.parse((ROOT / "ckit/ckit_userconfig.py").read_text(encoding="utf-8"))
        dispatcher = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name == "callConfigFunc")
        for exception in ("SystemExit", "KeyboardInterrupt"):
            with self.subTest(exception=exception):
                self.configure('def configure_ListWindow(window):\n'
                               '    window.calls += 1\n'
                               f'    raise {exception}("list failed")\n')
                namespace = {"user_namespace": vars(self.window.custom), "traceback": traceback,
                             "ckit_resource": SimpleNamespace(strings={"error_config_file_exec_failed": "hook failed"})}
                execute([dispatcher], namespace)
                listing = SimpleNamespace(calls=0)
                with contextlib.redirect_stderr(io.StringIO()) as errors, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    for _ in range(2):
                        namespace["callConfigFunc"]("configure_ListWindow", listing)
                    namespace["callConfigFunc"]("undefined", listing)
                self.assertEqual(listing.calls, 2)
                self.assertEqual(errors.getvalue().count(exception + ": list failed"), 2)
                self.assertEqual(output.getvalue(), "hook failed\nhook failed\n")

    def test_history_modes_and_reload(self):
        self.ini["COMMANDLINE", "history_0"] = "old"
        self.configure(HISTORY_MODE="off")
        self.namespace["appendHistory"](self.commandline, "ignored")
        self.window.commandLineHistorySave()
        self.assertEqual(self.window.commandline_history, [])
        self.assertNotIn(("COMMANDLINE", "history_0"), self.ini)
        self.configure(HISTORY_MODE="session")
        self.namespace["appendHistory"](self.commandline, "new  entry")
        self.window.commandLineHistorySave()
        self.configure(HISTORY_MODE="session")
        self.assertEqual(self.window.commandline_history, ["new  entry"])
        self.assertNotIn(("COMMANDLINE", "history_0"), self.ini)
        self.configure(HISTORY_MODE="persistent")
        self.assertEqual(self.window.commandline_history, [])
        self.namespace["appendHistory"](self.commandline, "new  entry")
        self.namespace["appendHistory"](self.commandline, "NEW  entry")
        self.assertEqual(self.window.commandline_history, ["NEW  entry"])
        self.window.commandLineHistorySave()
        self.assertEqual(self.ini["COMMANDLINE", "history_0"], "NEW  entry")
        self.configure(HISTORY_MODE="off")
        self.assertEqual(self.window.commandline_history, [])
        self.configure(HISTORY_MODE="persistent")
        self.assertEqual(self.window.commandline_history, [])

    @contextlib.contextmanager
    def history_ini(self, mode):
        import clnch_ini
        path = self.path.parent / "history.ini"
        parser = configparser.RawConfigParser()
        parser.read_dict({"INPUT": {"history_mode": mode}, "COMMANDLINE": {
            "history_0": "saved", "history_2": "gap", "history_1001": "beyond limit",
            "history_0003": "leading zeros", "history_": "keep", "history_name": "keep",
            "history_-1": "keep", "history_1.extra": "keep", "history_²": "keep",
            "history_１": "keep", "other": "keep"}, "OTHER": {"key": "value"}})
        with patch.object(clnch_ini, "ini", parser), patch.object(clnch_ini, "dirty", True), \
                patch.object(clnch_ini, "ini_filename", str(path)), \
                patch.dict(self.namespace, clnch_ini=clnch_ini):
            clnch_ini.write()
            yield clnch_ini, path

    def test_nonpersistent_startup_deletes_sparse_saved_history_immediately(self):
        for mode in ("off", "session"):
            with self.subTest(mode=mode), self.history_ini(mode) as (ini, path):
                self.window.input_settings["HISTORY_MODE"] = "off"
                self.window.commandline_history = []
                with patch.object(ini, "write", wraps=ini.write) as write:
                    self.window.configure()
                    write.assert_called_once_with()
                disk = configparser.RawConfigParser()
                disk.read(path, encoding="utf-8")
                expected = {key: "keep" for key in (
                    "history_", "history_name", "history_-1", "history_1.extra",
                    "history_²", "history_１", "other")}
                self.assertEqual(dict(disk.items("COMMANDLINE")), expected)
                self.assertEqual(disk.get("OTHER", "key"), "value")
                self.assertEqual(self.window.commandline_history, [])
                self.namespace["appendHistory"](self.commandline, "session-only")
                history = self.window.commandline_history
                self.window.configure()
                self.assertIs(self.window.commandline_history, history)
                self.assertEqual(history, ["session-only"] if mode == "session" else [])
                self.window.saveState()
                ini.write()
                ini.read()
                self.assertEqual(dict(ini.ini.items("COMMANDLINE")), expected)
                # Simulate a fresh MainWindow and startup using the saved mode.
                self.window.input_settings["HISTORY_MODE"] = "off"
                self.window.commandline_history = []
                self.window.configure()
                self.assertEqual(self.window.commandline_history, [])

    def test_history_menu_transitions_save_mode_and_deletion_together(self):
        for first in (0, 1):
            with self.subTest(first=first), self.history_ini("persistent") as (ini, path):
                self.window.input_settings["HISTORY_MODE"] = "off"
                self.window.configure()
                self.assertEqual(self.window.commandline_history, ["saved"])
                for choice in (first, 1 - first, 1, 2):
                    menu = self.menu_namespace([choice])
                    current = self.window.input_settings["HISTORY_MODE"]
                    with patch.object(ini, "write", wraps=ini.write) as write:
                        menu["_configInputSetting"](self.window, "HISTORY_MODE")
                        self.assertEqual(write.call_count,
                            int(current != ("off", "session", "persistent")[choice]))
                    disk = configparser.RawConfigParser()
                    disk.read(path, encoding="utf-8")
                    self.assertEqual(disk.get("INPUT", "history_mode"),
                        self.window.input_settings["HISTORY_MODE"])
                    self.assertFalse(any(key.startswith("history_") and key[8:].isascii()
                        and key[8:].isdecimal() for key in disk.options("COMMANDLINE")))
                    if choice == 1:
                        self.namespace["appendHistory"](self.commandline, "new command")
                        self.window.commandLineHistorySave()
                        self.window.configure()
                        self.assertEqual(self.window.commandline_history, ["new command"])
                    else:
                        self.assertEqual(self.window.commandline_history, [])
                for choice in (-1, 2):
                    before = path.read_bytes()
                    with patch.object(ini, "write", wraps=ini.write) as write:
                        self.menu_namespace([choice])["_configInputSetting"](self.window, "HISTORY_MODE")
                        write.assert_not_called()
                    self.assertEqual(path.read_bytes(), before)

    def test_history_deletion_save_failure_keeps_original_and_retries(self):
        for startup in (False, True):
            for mode in ("off", "session"):
                with self.subTest(startup=startup, mode=mode), \
                        self.history_ini(mode if startup else "persistent") as (ini, path):
                    self.window.input_settings["HISTORY_MODE"] = "off"
                    if not startup:
                        self.window.configure()
                    original = path.read_bytes()
                    with patch.object(ini.os, "replace", side_effect=OSError("replace failed")), \
                            patch.object(ini.clnch_debug, "printErrorInfo") as error, \
                            contextlib.redirect_stdout(io.StringIO()) as output:
                        if startup:
                            self.window.configure()
                        else:
                            self.menu_namespace([0 if mode == "off" else 1])["_configInputSetting"](
                                self.window, "HISTORY_MODE")
                    error.assert_called_once_with()
                    self.assertEqual(output.getvalue(), "")
                    self.assertEqual(path.read_bytes(), original)
                    self.assertTrue(ini.dirty)
                    self.assertEqual(self.window.commandline_history, [])
                    self.assertEqual(ini.get("INPUT", "history_mode"), mode)
                    self.assertEqual(list(path.parent.glob("*.tmp")), [])
                    ini.write()
                    self.assertFalse(ini.dirty)
                    ini.read()
                    self.assertEqual(self.window.commandLineHistoryLoad(), [])
                    self.assertEqual(ini.get("INPUT", "history_mode"), mode)
                    self.assertEqual(ini.get("OTHER", "key"), "value")

    def test_persistent_history_save_and_restart(self):
        with self.history_ini("persistent") as (ini, _path):
            self.window.input_settings["HISTORY_MODE"] = "off"
            self.window.configure()
            self.namespace["appendHistory"](self.commandline, "new command")
            self.namespace["appendHistory"](self.commandline, "NEW command")
            self.window.configure()
            self.assertEqual(self.window.commandline_history, ["NEW command", "saved"])
            self.window.saveState()
            ini.write()
            ini.read()
            self.window.input_settings["HISTORY_MODE"] = "off"
            self.window.commandline_history = []
            self.window.configure()
            self.assertEqual(self.window.commandline_history, ["NEW command", "saved"])

    def test_empty_history_is_not_added_but_spaces_are_kept(self):
        for mode in ("off", "session", "persistent"):
            for preserve in (False, True):
                with self.subTest(mode=mode, preserve_argument_text=preserve):
                    self.window.input_settings["HISTORY_MODE"] = mode
                    self.commandline.preserve_argument_text = preserve
                    self.window.commandline_history = ["old"]
                    for entry in ("", "new  entry", " ", "  ", ""):
                        self.namespace["appendHistory"](self.commandline, entry)
                    self.assertEqual(self.window.commandline_history,
                        ["old"] if mode == "off" else ["  ", " ", "new  entry", "old"])

    def test_empty_saved_history_is_skipped_and_save_packs_entries(self):
        for i, entry in enumerate(("", "old", "", " ", "")):
            self.ini["COMMANDLINE", f"history_{i}"] = entry
        self.ini["INPUT", "history_mode"] = "persistent"
        saved = self.ini.copy()
        self.configure(HISTORY_MODE="persistent")
        self.assertEqual(self.window.commandline_history, ["old", " "])
        self.assertEqual(self.ini, saved)
        # Saving also excludes empty entries supplied directly by custom code.
        self.window.commandline_history[:] = ["", "new", "", "old", " ", ""]
        self.window.commandLineHistorySave()
        self.assertEqual({key: value for (section, key), value in self.ini.items()
                          if section == "COMMANDLINE"},
                         {"history_0": "new", "history_1": "old", "history_2": " "})
        self.assertEqual(self.window.commandLineHistoryLoad(), ["new", "old", " "])
        for mode in ("off", "session"):
            self.configure(HISTORY_MODE=mode)
            saved = self.ini.copy()
            self.window.commandline_history[:] = ["", "session-only"]
            self.window.commandLineHistorySave()
            self.assertEqual(self.ini, saved)

    def test_all_empty_history_loads_and_saves_as_empty(self):
        for i in range(3):
            self.ini["COMMANDLINE", f"history_{i}"] = ""
        self.configure(HISTORY_MODE="persistent")
        self.assertEqual(self.window.commandline_history, [])
        self.window.commandLineHistorySave()
        self.assertFalse(any(section == "COMMANDLINE" for section, key in self.ini))

    def test_default_profile_loads_saved_history_and_keeps_it_on_reload(self):
        main = next(n for n in source_tree("clnch_mainwindow.py").body
                    if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        initialize = next(n for n in main.body
                          if isinstance(n, ast.FunctionDef) and n.name == "__init__")
        assignments = [n for n in initialize.body if isinstance(n, ast.Assign)
                       and any(isinstance(target, ast.Attribute) and target.attr == "input_settings"
                               or isinstance(target, ast.Subscript)
                               and isinstance(target.value, ast.Attribute)
                               and target.value.attr == "input_settings" for target in n.targets)]
        execute(assignments, dict(self.namespace, self=self.window))
        self.ini["COMMANDLINE", "history_0"] = "saved command;two words"
        self.configure()
        self.assertEqual(self.window.input_settings["HISTORY_MODE"], "persistent")
        self.assertEqual(self.window.input_settings["COMPLETION_MODE"], "standard")
        self.assertEqual(self.window.commandline_history, ["saved command;two words"])
        self.namespace["appendHistory"](self.commandline, "new command")
        self.configure()
        self.assertEqual(self.window.commandline_history, ["new command", "saved command;two words"])
        self.window.commandLineHistorySave()
        self.assertEqual(self.ini["COMMANDLINE", "history_0"], "new command")

    def test_failed_history_menu_preserves_mode_list_and_saved_history_then_retries(self):
        self.configure(HISTORY_MODE="session")
        previous = ["session-only"]
        self.window.commandline_history = previous
        for i in range(3):
            self.ini["COMMANDLINE", f"history_{i}"] = f"saved-{i}"
        saved = self.ini.copy()
        events = self.events[:]
        original_get = self.namespace["clnch_ini"].get
        def fail(section, key, *default):
            if (section, key) == ("COMMANDLINE", "history_1"):
                raise RuntimeError("simulated history error")
            return original_get(section, key, *default)
        self.namespace["clnch_ini"].get = fail
        menu = self.menu_namespace([2])
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            menu["_configInputSetting"](self.window, "HISTORY_MODE")
        self.assertIs(self.window.commandline_history, previous)
        self.assertEqual(self.window.input_settings["HISTORY_MODE"], "session")
        self.assertEqual(self.ini, saved)
        self.assertEqual(self.events, events)
        self.assertEqual(output.getvalue().count(self.namespace["strings"].HISTORY_LOAD_ERROR), 1)
        self.assertEqual(error.getvalue().count("RuntimeError: simulated history error"), 1)
        self.window.commandLineHistorySave()
        self.assertEqual(self.ini, saved)
        self.namespace["clnch_ini"].get = original_get
        menu["clnch_listwindow"].popMenu = lambda *args: 2
        menu["_configInputSetting"](self.window, "HISTORY_MODE")
        self.assertEqual(self.window.commandline_history, ["saved-0", "saved-1", "saved-2"])
        self.assertEqual(self.window.input_settings["HISTORY_MODE"], "persistent")
        self.assertEqual(self.ini["INPUT", "history_mode"], "persistent")
        self.assertEqual(self.events[len(events):], ["ini-write"])

    def test_failed_history_startup_and_reload_keep_input_usable_and_saved_entries(self):
        for previous_mode in ("off", "session"):
            with self.subTest(previous_mode=previous_mode):
                self.configure(HISTORY_MODE=previous_mode)
                previous = ["previous session"] if previous_mode == "session" else []
                self.window.commandline_history = previous
                for i in range(3):
                    self.ini["COMMANDLINE", f"history_{i}"] = f"saved-{i}"
                original_get = self.namespace["clnch_ini"].get
                def fail(section, key, *default, original_get=original_get):
                    if (section, key) == ("COMMANDLINE", "history_1"):
                        raise RuntimeError("simulated history error")
                    return original_get(section, key, *default)
                self.namespace["clnch_ini"].get = fail
                self.events.clear()
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.configure('def configure(window):\n    window.events.append("local-apply")\n',
                                   HISTORY_MODE="persistent", SPACE_ACTION="complete")
                self.assertIs(self.window.commandline_history, previous)
                self.assertEqual(self.window.input_settings["HISTORY_MODE"], previous_mode)
                self.assertEqual(self.window.input_settings["SPACE_ACTION"], "complete")
                self.assertEqual(self.events, ["standard-apply", "local-apply"])
                self.assertEqual(len(self.window.commandline_list), 3)
                self.assertNotIn("Space", self.window.keymap)
                self.assertIs(self.window.keymap["C-F10"], self.window.command.ConsoleToggle)
                self.window.saveState()
                entries = [self.ini["COMMANDLINE", f"history_{i}"] for i in range(3)]
                self.assertEqual(entries, ["saved-0", "saved-1", "saved-2"])
                self.namespace["clnch_ini"].get = original_get
                self.window.configure()
                self.assertEqual(self.window.commandline_history, entries)
                self.assertEqual(self.window.input_settings["HISTORY_MODE"], "persistent")

    def test_history_read_terminators_and_limit_do_not_mutate_current_history(self):
        previous = ["keep"]
        self.window.commandline_history = previous
        for exception in (configparser.NoSectionError("COMMANDLINE"),
                          configparser.NoOptionError("history_0", "COMMANDLINE")):
            def missing(*args, exception=exception):
                raise exception
            self.namespace["clnch_ini"].get = missing
            self.assertEqual(self.window.commandLineHistoryLoad(), [])
            self.assertIs(self.window.commandline_history, previous)
        reads = []
        def unlimited(section, key, *default):
            reads.append(key)
            return key
        self.namespace["clnch_ini"].get = unlimited
        loaded = self.window.commandLineHistoryLoad()
        self.assertEqual(loaded, [f"history_{i}" for i in range(1000)])
        self.assertEqual(reads, loaded)
        self.assertIs(self.window.commandline_history, previous)

    def test_history_mode_change_does_not_swallow_interruptions(self):
        self.configure(HISTORY_MODE="session")
        previous = self.window.input_settings
        history = self.window.commandline_history
        requested = dict(previous, HISTORY_MODE="persistent")
        for exception in (KeyboardInterrupt(), SystemExit()):
            def interrupt(*args, exception=exception):
                raise exception
            self.namespace["clnch_ini"].get = interrupt
            with self.assertRaises(type(exception)):
                self.window.applyInputSettings(requested)
            self.assertIs(self.window.input_settings, previous)
            self.assertIs(self.window.commandline_history, history)
            self.assertEqual(requested["HISTORY_MODE"], "persistent")

    def test_clear_and_normalization(self):
        self.configure("")
        self.window.saveState()
        self.assertEqual(self.text[0], "")
        self.assertIn("console-save", self.events)
        self.text[0] = "keep"
        self.configure(CLEAR_ON_DEACTIVATE=False)
        self.window.saveState()
        self.assertEqual(self.text[0], "keep")
        self.configure("")
        self.window.active = True
        self.window.saveState()
        self.assertEqual(self.text[0], "keep")
        self.assertEqual(self.namespace["normalizeCommandLineText"]("  a\t  b\r\n  "), "  a   b    ")

    def test_completion_modes_and_file_candidates(self):
        update = SimpleNamespace(text="Ab", selectionLeft=lambda: 2)
        self.configure("")
        self.window.commandline_history = ["Ab history"]
        self.assertEqual(self.namespace["onCandidate"](update), (["Ab history", "about"], 0))
        self.configure(COMPLETION_MODE="off")
        self.assertEqual(self.namespace["onCandidate"](update), ([], 0))
        self.configure(COMPLETION_MODE="commands")
        self.assertIn("about", self.window.launcher.onCandidate(update))
        self.window.commandline_history = ["Ab history"]
        self.assertEqual(self.namespace["onCandidate"](update), (["about"], 0))
        update.text = ""
        self.assertEqual(self.window.launcher.onCandidate(update), [])
        self.configure(COMPLETION_MODE="standard")
        self.namespace["clnch_native"] = SimpleNamespace(
            findFile=lambda *args, **kwargs: [("file.txt", 0, 0, 0)])
        self.namespace["ckit"].joinPath = os.path.join
        update.text = "folder\\fi"
        update.selectionLeft = lambda: len(update.text)
        self.assertEqual(self.window.launcher.onCandidate(update), ["file.txt"])
        connections = []
        self.namespace["clnch_misc"].checkNetConnection = connections.append
        self.namespace["clnch_native"].enumShare = lambda server: [("share", 0)]
        self.namespace["ckit"].pathSlash = lambda: False
        update.text = "\\\\server\\sh"
        self.assertEqual(self.window.launcher.onCandidate(update), ["share\\"])
        self.assertTrue(connections)
        self.configure(COMPLETION_MODE="off")
        self.assertEqual(self.window.launcher.onCandidate(update), [])

    def test_invalid_settings_keep_previous_configuration(self):
        self.configure(HISTORY_MODE="session")
        previous = self.window.custom
        old_keys = self.window.keymap
        for settings in ({"HISTORY_MODE": "bad"}, {"CLEAR_ON_DEACTIVATE": "True"}):
            with contextlib.redirect_stderr(io.StringIO()):
                self.configure(**settings)
            self.assertIs(self.window.custom, previous)
            self.assertIs(self.window.keymap, old_keys)
            self.assertIs(sys.modules["custom"], previous)
        for text in ('configure=1', 'invalid python !'):
            with contextlib.redirect_stderr(io.StringIO()):
                self.configure(text, HISTORY_MODE="session")
            self.assertIs(self.window.custom, previous)
            self.assertIs(self.window.keymap, old_keys)
            self.assertIs(sys.modules["custom"], previous)

    def test_local_import_sees_fresh_module(self):
        self.configure('CUSTOM_VALUE="old"\n')
        self.configure('CUSTOM_VALUE="new"\nimport custom\n'
                       'assert custom.CUSTOM_VALUE == "new"\n', HISTORY_MODE="persistent")
        self.assertEqual(self.window.input_settings["HISTORY_MODE"], "persistent")

    def test_only_custom_filename_is_loaded(self):
        (self.path.parent / "config_local.py").write_text(
            'raise AssertionError("retired filename was loaded")\n', encoding="utf-8")
        self.configure('def configure(window):\n    window.events.append("custom-file")\n')
        self.assertEqual(self.events, ["standard-apply", "custom-file"])
        self.path.unlink()
        self.events.clear()
        self.window.configure()
        self.assertEqual(self.events, ["standard-apply"])
        self.assertFalse(hasattr(self.window.custom, "configure"))

    def menu_namespace(self, results):
        namespace = {"sys": sys, "clnch_ini": self.namespace["clnch_ini"],
                     "clnch_listwindow": SimpleNamespace(popMenu=lambda *args: results.pop(0), _split_list_result=_split_list_result)}
        nodes = [n for n in source_tree("clnch_configmenu.py").body
                 if (isinstance(n, ast.FunctionDef) and n.name in ("_configInputSetting", "_configInput", "_settingItem", "_iterConfigMenu"))
                 or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_input_options"
                                                      for t in n.targets))]
        execute(nodes, namespace)
        return namespace

    def test_menu_apply_save_cancel_and_custom_keys(self):
        self.configure('def configure(window):\n'
                       '    window.events.append("local-apply")\n'
                       '    window.keymap["Space"]="custom-space"\n'
                       '    window.cmd_keymap["Tab"]="custom-tab"\n')
        menu = self.menu_namespace([])
        for name, (_, options) in menu["_input_options"].items():
            for index, (_, value) in enumerate(options):
                old_value = self.window.input_settings[name]
                before = self.events[:]
                menu["clnch_listwindow"].popMenu = lambda *args, index=index: index
                menu["_configInputSetting"](self.window, name)
                self.assertEqual(self.window.input_settings[name], value)
                if value != old_value:
                    encoded = str(int(value)) if type(value) is bool else value
                    self.assertEqual(self.ini["INPUT", name.lower()], encoded)
                    self.assertEqual(self.events[len(before):], ["ini-write"])
                else:
                    self.assertEqual(self.events, before)
        self.assertNotIn(("INPUT", "preserve_multiple_spaces"), self.ini)
        self.assertEqual(self.window.keymap["Space"], "custom-space")
        self.assertEqual(self.window.cmd_keymap["Tab"], "custom-tab")
        before = (self.ini.copy(), self.window.input_settings.copy(), self.events[:])
        menu["clnch_listwindow"].popMenu = lambda *args: -1
        menu["_configInputSetting"](self.window, "HISTORY_MODE")
        self.assertEqual(before, (self.ini, self.window.input_settings, self.events))
        self.path.write_text("", encoding="utf-8")
        self.window.configure()
        self.assertNotIn("Space", self.window.keymap)
        self.assertNotIn("Tab", self.window.cmd_keymap)

    def test_menu_key_reversal_and_history_transition(self):
        self.configure(HISTORY_MODE="off")
        menu = self.menu_namespace([])
        def select(name, index):
            menu["clnch_listwindow"].popMenu = lambda *args: index
            menu["_configInputSetting"](self.window, name)
        select("SPACE_ACTION", 1)
        select("TAB_ACTION", 1)
        self.assertNotIn("Space", self.window.keymap)
        self.assertNotIn("Tab", self.window.cmd_keymap)
        select("SPACE_ACTION", 0)
        select("TAB_ACTION", 0)
        self.assertIs(self.window.keymap["Space"], self.window.command.InsertSpace)
        self.assertIs(self.window.cmd_keymap["Tab"], self.window.command.ClearInput)
        select("HISTORY_MODE", 2)
        self.assertEqual(self.window.commandline_history, [])
        self.window.commandline_history.append("memory")
        select("HISTORY_MODE", 2)
        self.assertEqual(self.window.commandline_history, ["memory"])
        select("HISTORY_MODE", 1)
        self.assertEqual(self.window.commandline_history, [])
        self.assertNotIn(("COMMANDLINE", "history_0"), self.ini)
        self.path.unlink()
        self.window.configure()
        self.assertEqual(self.window.input_settings["HISTORY_MODE"], "session")

    def test_input_menu_routes_all_five_items(self):
        self.configure()
        menu = self.menu_namespace([])
        menu["_configKeyMap"] = lambda window: None
        menu["_configAutoComplete"] = lambda window: None
        selected = []
        menu["_configInputSetting"] = lambda window, name: selected.append(name)
        results = iter([2, 3, 4, 5, 6, -1])
        def popup(window, width, height, title, items, initial):
            self.assertEqual(len(items), 7)
            self.assertTrue(all(":" in item[0] for item in items[2:]))
            return next(results)
        menu["clnch_listwindow"].popMenu = popup
        menu["_configInput"](self.window)
        self.assertEqual(selected, list(clnch_inputconfig.DEFAULTS))


if __name__ == "__main__":
    unittest.main()
