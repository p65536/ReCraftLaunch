"""Alt+Enter settings, forwarding and menu checks; OS launches are replaced."""
import ast
import configparser
import contextlib
import ctypes
import io
import os
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_modal_lifecycle import (
    _cleanup_on_exit,
    _modal_dialog_scope,
    _split_list_result,
    load_functions,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "clnch")]
import clnch_altenterconfig as config
import clnch_strings as strings


class Ini:
    def __init__(self):
        self.parser = configparser.RawConfigParser()
        self.writes = 0
        self.dirty = False
        self.read_failed = False

    @property
    def ini(self):
        return self.parser

    @ini.setter
    def ini(self, value):
        self.parser = value

    def get(self, section, name, default):
        return self.parser.get(section, name, fallback=default)

    def set(self, section, name, value):
        if not self.parser.has_section(section):
            self.parser.add_section(section)
        self.parser.set(section, name, value)
        self.dirty = True

    def write(self):
        self.writes += 1
        self.dirty = False


class AltEnterTests(unittest.TestCase):
    def settings(self, **changes):
        return dict(config.DEFAULTS, **changes)

    def test_four_independent_sections_defaults_and_invalid_modified_values(self):
        ini = Ini()
        expected = {}
        for index, key in enumerate(config.KEYS):
            defaults = config.MODIFIED_DEFAULTS if key else config.DEFAULTS
            self.assertEqual(config.read(ini, key), defaults)
            self.assertEqual(defaults["action"], "none")
            settings = dict(defaults, action="application" if index % 2 else "web",
                executable=f"tool{index}.exe", arguments=f"--key{index} %param%",
                url=f"https://example.org/{index}?q=%param%")
            config.write(ini, settings, key)
            expected[key] = settings
        self.assertTrue(config.DEFAULTS["properties_first"])
        for key, settings in expected.items():
            self.assertEqual(config.read(ini, key), settings)
            # Switching action retains this key's stored destinations.
            config.write(ini, dict(settings, action="none"), key)
            self.assertEqual(config.read(ini, key), dict(settings, action="none"))
        for key in config.MODIFIED_SETTINGS:
            section = config.KEYS[key][0]
            ini.set(section, "action", "properties")
            with self.assertRaises(ValueError):
                config.read(ini, key)
            ini.set(section, "action", "none")
            for changes in ({"properties_first": True}, {"url": "bad"}, {"arguments": None}):
                with self.subTest(key=key, changes=changes), self.assertRaises(ValueError):
                    config.write(ini, dict(config.MODIFIED_DEFAULTS, **changes), key)
            incomplete = config.MODIFIED_DEFAULTS.copy()
            del incomplete["arguments"]
            with self.assertRaises(ValueError):
                config.validate(incomplete, key)
        self.assertEqual(config.read(Ini(), "ctrl"), config.MODIFIED_DEFAULTS)

    def test_modified_keys_never_test_paths_or_use_properties(self):
        with tempfile.TemporaryDirectory() as directory:
            for key in config.MODIFIED_SETTINGS:
                for action in ("application", "web"):
                    settings = dict(config.MODIFIED_DEFAULTS, action=action, executable=key + ".exe",
                        arguments="--query", url=f"https://example.org/{key}?q=%param%")
                    with self.subTest(key=key, action=action), patch.object(config.os.path, "exists") as exists:
                        result = config.build_action(settings, directory, key)
                        exists.assert_not_called()
                        self.assertIsNone(result[0])
                        self.assertEqual(result[1], settings["executable"] if action == "application" else
                            settings["url"].replace("%param%", urllib.parse.quote_plus(directory)))

    def test_each_queued_key_uses_its_own_snapshot(self):
        pending, calls = [], []
        window = SimpleNamespace(altenter_settings=self.settings(), altenter_modified_settings={})
        ckit = SimpleNamespace(JobItem=lambda func: func,
            JobQueue=SimpleNamespace(defaultQueue=lambda: SimpleNamespace(enqueue=pending.append)))
        misc = SimpleNamespace(_require_job_queue=lambda queue: queue)
        with patch.dict(sys.modules, {"ckit": ckit, "clnch_misc": misc,
                "pyauto": SimpleNamespace(shellExecute=lambda *args: calls.append(args))}):
            for key in config.MODIFIED_SETTINGS:
                window.altenter_modified_settings[key] = dict(config.MODIFIED_DEFAULTS,
                    action="web", url=f"https://example.org/{key}?q=%param%")
                config.execute(window, ' 日本語 a"b &+;?# ', key)
                window.altenter_modified_settings[key]["url"] = "https://changed.org/?q=%param%"
            config.execute(window, "disabled")
            config.execute(window, " \t", "ctrl")
            self.assertEqual(len(pending), 3)
            for job in pending:
                job(None)
        self.assertEqual([call[1] for call in calls], [
            f"https://example.org/{key}?q=" + urllib.parse.quote_plus('日本語 a"b &+;?#')
            for key in config.MODIFIED_SETTINGS])

    def test_defaults_and_ini_round_trip_preserve_percent_and_unicode(self):
        ini = Ini()
        self.assertEqual(config.read(ini), config.DEFAULTS)
        self.assertEqual(ini.parser.sections(), [])
        settings = self.settings(action="application", executable=r"C:\辞書 tools\EBWin4.exe",
            arguments="/G=0 /C=1 /M=p /S=%param%", url="https://example.org/search?q=%param%",
            properties_first=True)
        config.write(ini, settings)
        self.assertEqual(config.read(ini), settings)
        output = io.StringIO()
        ini.parser.write(output)
        self.assertIn("%param%", output.getvalue())
        self.assertEqual(ini.get("ALT_ENTER", "properties_first", ""), "1")

    def test_invalid_settings_and_url_templates(self):
        for changes in ({"action": "bad"}, {"properties_first": "1"}, {"arguments": "bad\narg"},
                        {"executable": "bad\0.exe"}, {"url": "file:///tmp/%param%"},
                        {"url": "https://example.org/search"}, {"url": "https:///%param%"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config.validate(self.settings(**changes))
        ini = Ini()
        ini.set("ALT_ENTER", "properties_first", "True")
        with self.assertRaises(ValueError):
            config.read(ini)

    def test_disabled_empty_and_incomplete_settings(self):
        self.assertIsNone(config.build_action(self.settings(properties_first=True), "anything"))
        self.assertIsNone(config.build_action(self.settings(action="application"), " "))
        for mode in ("application", "web"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                config.build_action(self.settings(action=mode), "hello")

    def test_application_whole_input_survives_windows_argument_parsing(self):
        parse = ctypes.windll.shell32.CommandLineToArgvW
        parse.argtypes = (ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int))
        parse.restype = ctypes.POINTER(ctypes.c_wchar_p)
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = (ctypes.c_void_p,)
        free.restype = ctypes.c_void_p
        settings = self.settings(action="application", executable=r"C:\Program Files\EBWin4.exe",
                                 arguments="/G=0 /C=1 /M=p /S=%param%")
        for text in ('日本語 & Python', 'a;b', 'a"b', 'space \\', '%TEMP% %param%', 'x & calc.exe'):
            with self.subTest(text=text):
                verb, exe, arguments, workdir = config.build_action(settings, text)
                self.assertEqual((verb, exe, workdir), (None, settings["executable"], os.path.dirname(settings["executable"])))
                count = ctypes.c_int()
                argv = parse('tool.exe ' + arguments, ctypes.byref(count))
                self.assertTrue(argv)
                try:
                    self.assertEqual([argv[i] for i in range(count.value)],
                                     ['tool.exe', '/G=0', '/C=1', '/M=p', '/S=' + text])
                finally:
                    free(ctypes.cast(argv, ctypes.c_void_p))
        settings["arguments"] = "--query"
        self.assertEqual(config.build_action(settings, "two words")[2], '--query "two words"')

    def test_web_accepts_user_url_and_encodes_query_exactly_once(self):
        text = '日本語 & Python + 100%;a?b#c'
        for template in ("https://example.org/search?q=%param%&lang=ja",
                         "https://wiki.example.net/find/%param%"):
            with self.subTest(template=template):
                action = config.build_action(self.settings(action="web", url=template), text)
                self.assertEqual(action, (None, template.replace("%param%", urllib.parse.quote_plus(text)), "", ""))
                self.assertNotIn('日本語', action[1])
                self.assertIn('%26', action[1])
                self.assertIn('%25', action[1])

    def test_properties_and_priority_for_files_and_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "日本語 file.txt"
            path.write_text("example", encoding="utf-8")
            for target in (str(path), str(path.parent), '"' + str(path) + '"'):
                with self.subTest(target=target):
                    expected = ("properties", os.path.abspath(target.strip('"')), "", "")
                    self.assertEqual(config.build_action(self.settings(action="properties"), target), expected)
                    self.assertEqual(config.build_action(self.settings(action="application", properties_first=True), target), expected)
                    self.assertEqual(config.build_action(self.settings(action="web", properties_first=True), target), expected)
            with self.assertRaises(FileNotFoundError):
                config.build_action(self.settings(action="properties"), str(path) + ".missing")
            application = self.settings(action="application", executable="tool.exe", properties_first=True)
            self.assertEqual(config.build_action(application, "plain text")[1], "tool.exe")
            application["properties_first"] = False
            self.assertEqual(config.build_action(application, str(path))[1], "tool.exe")

    def test_launch_is_queued_and_errors_are_reported(self):
        pending = []
        shell = Mock()
        ckit = SimpleNamespace(JobItem=lambda func: SimpleNamespace(subthread_func=func),
            JobQueue=SimpleNamespace(defaultQueue=lambda: SimpleNamespace(enqueue=pending.append)))
        namespace = {"_ckit": ckit}
        load_functions("clnch/clnch_misc.py", {"_require_job_queue"}, namespace)
        misc = SimpleNamespace(_require_job_queue=namespace["_require_job_queue"])
        window = SimpleNamespace(altenter_settings=self.settings(action="application", executable="tool.exe"))
        with patch.dict(sys.modules, {"ckit": ckit, "pyauto": SimpleNamespace(shellExecute=shell),
                                      "clnch_misc": misc}):
            config.execute(window, "hello")
            shell.assert_not_called()
            window.altenter_settings["action"] = "none"
            pending.pop().subthread_func(None)
            shell.assert_called_once_with(None, "tool.exe", "hello", "")
            config.execute(window, "hello")
            self.assertFalse(pending)
            window.altenter_settings["action"] = "properties"
            config.execute(window, "not-an-existing-path")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                pending.pop().subthread_func(None)
            self.assertIn(strings.ALT_ENTER_FAILED.split("{error}")[0], output.getvalue())
            shell.assert_called_once()


class AltEnterMenuTests(unittest.TestCase):
    def setUp(self):
        self.ini = Ini()
        self.main = SimpleNamespace(isEnabled=lambda: True, altenter_settings=config.DEFAULTS.copy(),
            altenter_modified_settings={key: config.MODIFIED_DEFAULTS.copy() for key in config.MODIFIED_SETTINGS},
            getStringWidth=lambda text: sum(1 if ord(c) < 128 else 2 for c in text),
            enable=Mock(), activate=Mock(), configure=Mock())
        self.popup = Mock(return_value=-1)
        self.dialogs = []
        self.specs = []
        def make_dialog(parent, title, items):
            self.specs.append(items)
            return self.dialogs.pop(0)
        make_dialog.Edit = lambda name, indent, width, label, value: (name, width, label, value)
        make_dialog.StaticText = lambda indent, text, **kwargs: ("guide", text, kwargs)
        make_dialog.RESULT_OK = 1
        self.namespace = {"deepcopy": deepcopy, "ExitStack": ExitStack, "_cleanup_on_exit": _cleanup_on_exit, "sys": sys, "os": os, "_configValuePreview": lambda window, value: value, "strings": strings, "clnch_altenterconfig": config,
            "clnch_ini": self.ini, "clnch_listwindow": SimpleNamespace(popMenu=self.popup, _split_list_result=_split_list_result),
            "ckit": SimpleNamespace(Dialog=make_dialog, ALIGN_RIGHT=1),
            "clnch_misc": SimpleNamespace(adjustWindowPosition=Mock(), getDialogFont=Mock(),
                _modal_dialog_scope=_modal_dialog_scope),
            "clnch_msgbox": SimpleNamespace(popMessageBox=Mock(), MSGBOX_TYPE_OK=0)}
        tree = ast.parse((ROOT / "clnch/clnch_configmenu.py").read_text(encoding="utf-8"))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and (n.name.startswith("_configAltEnter") or n.name in ("_saveAltEnterSettings", "_settingItem", "_iterConfigMenu"))]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "altenter-menu-test", "exec"), self.namespace)  # noqa: S102  # Execute isolated source under test.

    def test_submenu_only_shows_relevant_settings(self):
        for mode, count in (("none", 1), ("application", 3), ("web", 3), ("properties", 1)):
            self.main.altenter_settings["action"] = mode
            self.namespace["_configAltEnterKey"](self.main)
            self.assertEqual(len(self.popup.call_args.args[4]), count)
        self.assertEqual(self.ini.writes, 0)

    def test_key_selector_and_modified_menus(self):
        self.main.altenter_modified_settings["ctrl"]["action"] = "web"
        self.namespace["_configAltEnter"](self.main)
        self.assertEqual([item[0] for item in self.popup.call_args.args[4]], [
            "Alt+Enter: " + strings.ALT_ENTER_NONE,
            "[C]+Alt+Enter: " + strings.ALT_ENTER_WEB,
            "[S]+Alt+Enter: " + strings.ALT_ENTER_NONE,
            "[C]+[S]+Alt+Enter: " + strings.ALT_ENTER_NONE])
        for key in config.MODIFIED_SETTINGS:
            self.main.altenter_modified_settings[key]["action"] = "application"
            self.namespace["_configAltEnterKey"](self.main, key)
            self.assertEqual(len(self.popup.call_args.args[4]), 2)
            self.namespace["_configAltEnterAction"](self.main, key)
            self.assertEqual(self.popup.call_args.args[4], list(config.ACTIONS.values())[:3])
        self.assertEqual(self.ini.writes, 0)

    def test_selector_routes_each_key_and_refreshes_its_summary_in_both_languages(self):
        import clnch_strings_en
        import clnch_strings_ja

        for language in (clnch_strings_ja, clnch_strings_en):
            actions = {"none": language.ALT_ENTER_NONE, "application": language.ALT_ENTER_APPLICATION,
                       "web": language.ALT_ENTER_WEB, "properties": language.ALT_ENTER_PROPERTIES}
            for index, key in enumerate(config.KEYS):
                current = config.get_settings(self.main, key)
                current["action"] = "none"
                captured = []
                def popup(*args, index=index, captured=captured):
                    captured.append(args[4][index][0])
                    return index if len(captured) == 1 else -1
                def configure(window, selected_key, key=key, current=current):
                    self.assertIs(window, self.main)
                    self.assertEqual(selected_key, key)
                    current["action"] = "application"
                with patch.dict(self.namespace, strings=language, _configAltEnterKey=configure), \
                        patch.object(config, "ACTIONS", actions):
                    self.popup.side_effect = popup
                    self.namespace["_configAltEnter"](self.main)
                label = config.KEYS[key][1]
                self.assertEqual(captured, [label + ": " + language.ALT_ENTER_NONE,
                                            label + ": " + language.ALT_ENTER_APPLICATION])
        self.main.configure.assert_not_called()

    def test_independent_edits_and_save_failure_preserve_active_and_ini_state(self):
        save = self.namespace["_saveAltEnterSettings"]
        self.ini.set("OTHER", "pending", "keep")
        for key in config.KEYS:
            self.ini.set("OTHER", "pending", key)
            current = config.get_settings(self.main, key)
            before = deepcopy(self.ini.ini)
            for failure in ("dirty", "read_failed", "exception"):
                def failed_write(failure=failure):
                    if failure == "read_failed":
                        self.ini.read_failed = True
                    if failure == "exception":
                        raise OSError("save failed")
                with patch.object(self.ini, "write", side_effect=failed_write):
                    if failure == "exception":
                        with self.assertRaises(OSError):
                            save(self.main, key, action="web")
                    else:
                        self.assertFalse(save(self.main, key, action="web"))
                self.assertIs(config.get_settings(self.main, key), current)
                self.assertEqual(dict(self.ini.ini), dict(before))
                self.assertTrue(self.ini.dirty)
                self.ini.read_failed = False
            self.assertTrue(save(self.main, key, action="web", url=f"https://example.org/{key}?q=%param%"))
            self.assertEqual(config.get_settings(self.main, key)["url"], f"https://example.org/{key}?q=%param%")
        self.assertEqual(len({config.get_settings(self.main, key)["url"] for key in config.KEYS}), 4)
        self.main.configure.assert_not_called()

    def test_change_cancel_same_value_and_immediate_save_without_custom_reload(self):
        self.popup.side_effect = [1, 1, -1]
        for _ in range(3):
            self.namespace["_configAltEnterAction"](self.main)
        self.assertEqual(self.main.altenter_settings["action"], "application")
        self.assertEqual(self.ini.writes, 1)
        self.popup.side_effect = [0, -1]
        self.namespace["_configAltEnterPriority"](self.main)
        self.namespace["_configAltEnterPriority"](self.main)
        self.assertFalse(self.main.altenter_settings["properties_first"])
        self.assertEqual(self.ini.writes, 2)
        self.main.configure.assert_not_called()

    def test_application_has_two_fields_web_has_one_and_cancel_discards_edits(self):
        for mode, fields in (("application", ["executable", "arguments"]), ("web", ["url"])):
            self.main.altenter_settings["action"] = mode
            dialog = Mock()
            dialog.getResult.return_value = (0, {})
            self.dialogs.append(dialog)
            self.namespace["_configAltEnterTarget"](self.main)
            self.assertEqual([item[0] for item in self.specs[-1] if item[0] != "guide"], fields)
            controls = strings.CONFIG_EDIT_FIELDS_GUIDE if mode == "application" else strings.CONFIG_EDIT_GUIDE
            self.assertEqual(self.specs[-1][-1], ("guide", controls, {"align": 1}))
            dialog.destroy.assert_called_once()
        self.assertEqual(self.ini.writes, 0)

    def test_invalid_url_can_be_corrected_and_values_are_retained(self):
        self.main.altenter_settings["action"] = "web"
        first, second = Mock(), Mock()
        first.getResult.return_value = (1, {"url": "https://example.org/no-placeholder"})
        second.getResult.return_value = (1, {"url": "https://search.example.net/?q=%param%"})
        self.dialogs.extend([first, second])
        self.namespace["_configAltEnterTarget"](self.main)
        self.assertEqual(self.specs[-1][0][3], "https://example.org/no-placeholder")
        self.assertEqual(self.main.altenter_settings["url"], "https://search.example.net/?q=%param%")
        self.assertEqual(self.ini.writes, 1)
        self.namespace["clnch_msgbox"].popMessageBox.assert_called_once()
        first.destroy.assert_called_once()
        second.destroy.assert_called_once()

    def test_dialog_exception_restores_parent(self):
        self.main.altenter_settings["action"] = "application"
        dialog = Mock()
        dialog.messageLoop.side_effect = RuntimeError("dialog failure")
        self.dialogs.append(dialog)
        with self.assertRaises(RuntimeError):
            self.namespace["_configAltEnterTarget"](self.main)
        self.main.enable.assert_any_call(True)
        self.main.activate.assert_called_once()
        dialog.destroy.assert_called_once()
        self.assertEqual(self.ini.writes, 0)


if __name__ == "__main__":
    unittest.main()
