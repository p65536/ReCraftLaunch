"""Regression checks for imports, key handling and completion."""
import ast
import configparser
import contextlib
import ctypes
import hashlib
import importlib.util
import io
import locale
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]

import clnch_text

import ckit

clnch_text.initialize()
import clnch_debug
import clnch_misc
import clnch_resource

import clnch
import pyauto
from ckit import ckit_textwidget, ckit_theme


class ImportCleanupTests(unittest.TestCase):
    def test_clipboard_text_copies_all_utf16_units_and_the_terminator(self):
        from ckit import ckit_misc

        for text in ("", "日本\r\n", "🙂tail\r", "𐀀🙂", "\ud800tail"):
            with self.subTest(text=repr(text)):
                expected = text.encode("utf-16-le", "surrogatepass") + b"\x00\x00"
                destination = ctypes.create_string_buffer(b"X" * (len(expected) + 8))
                kernel = ckit_misc._clipboard_kernel32
                user = ckit_misc._clipboard_user32
                with (patch.object(kernel, "GlobalAlloc", return_value=1) as allocate,
                      patch.object(kernel, "GlobalLock", return_value=ctypes.addressof(destination)),
                      patch.object(kernel, "GlobalUnlock"),
                      patch.object(user, "OpenClipboard", return_value=True),
                      patch.object(user, "EmptyClipboard", return_value=True),
                      patch.object(user, "SetClipboardData") as publish,
                      patch.object(user, "CloseClipboard")):
                    ckit_misc.setClipboardText(text)
                self.assertEqual(allocate.call_args.args[1], len(expected))
                self.assertEqual(destination.raw[:len(expected)], expected)
                self.assertEqual(destination.raw[len(expected):len(expected) + 8], b"X" * 8)
                publish.assert_called_once()

    def test_command_jobs_keep_argument_identity_and_live_worker_reads(self):
        import clnch_mainwindow

        original_item = ckit.JobItem
        for route in ("shell", "url"):
            for change in ("unchanged", "mutate", "replace_info", "replace_job", "tuple", "empty"):
                with self.subTest(route=route, change=change):
                    events, pending = [], []
                    arguments = ["old value", "second"]
                    info = SimpleNamespace(args=arguments)

                    def create(*args, events=events):
                        item = original_item(*args)
                        self.assertIs(type(item), original_item)
                        self.assertNotIn("args", vars(item))
                        with self.assertRaises(AttributeError) as raised:
                            _ = item.args
                        self.assertEqual(str(raised.exception), "'JobItem' object has no attribute 'args'")
                        self.assertEqual(raised.exception.name, "args")
                        self.assertIs(raised.exception.obj, item)
                        events.append("create")
                        return item

                    def enqueue(item, arguments=arguments, events=events, pending=pending):
                        self.assertIs(item.args, arguments)
                        events.append("enqueue")
                        pending.append(item)

                    def fetch(events=events, enqueue=enqueue):
                        events.append("queue")
                        return SimpleNamespace(enqueue=enqueue)

                    command = (clnch_mainwindow.MainWindow.ShellExecuteCommand(
                        None, None, "tool.exe", "%param%", "") if route == "shell" else
                        clnch_mainwindow.MainWindow.UrlCommand(None, "https://example.test/%param%"))
                    with patch.object(ckit, "JobItem", side_effect=create), \
                         patch.object(ckit.JobQueue, "defaultQueue", side_effect=fetch), \
                         patch.object(pyauto, "shellExecute") as launch:
                        command(info)
                        self.assertEqual(events, ["create", "queue", "enqueue"])
                        self.assertEqual(len(pending), 1)
                        item = pending[0]
                        self.assertIs(item.args, arguments)
                        launch.assert_not_called()
                        if change == "mutate":
                            arguments[0] = "new 日本語"
                        elif change == "replace_info":
                            info.args = ["ignored replacement"]
                        elif change == "replace_job":
                            item.args = ["new 日本語", "second"]
                        elif change == "tuple":
                            item.args = ("old value", "second")
                        elif change == "empty":
                            arguments.clear()
                        item.subthread_func(item)
                    if route == "shell":
                        expected = ("" if change == "empty" else '"new 日本語" second'
                                    if change in ("mutate", "replace_job") else '"old value" second')
                        launch.assert_called_once_with(None, "tool.exe", expected, "", None)
                    else:
                        expected = ("" if change == "empty" else "new+%E6%97%A5%E6%9C%AC%E8%AA%9E"
                                    if change in ("mutate", "replace_job") else "old+value")
                        launch.assert_called_once_with(None, "https://example.test/" + expected, "", "")
                    if change != "replace_job" and change != "tuple":
                        self.assertIs(item.args, arguments)

    def test_help_job_state_is_initialized_by_help_and_read_live_at_completion(self):
        import clnch_mainwindow

        original_item = ckit.JobItem
        events, pending = [], []

        def create(*args):
            item = original_item(*args)
            self.assertIs(type(item), original_item)
            for name in ("help_message", "help_opened"):
                self.assertNotIn(name, vars(item))
                with self.assertRaises(AttributeError) as raised:
                    getattr(item, name)
                self.assertEqual(str(raised.exception), f"'JobItem' object has no attribute '{name}'")
                self.assertEqual(raised.exception.name, name)
                self.assertIs(raised.exception.obj, item)
            events.append("create")
            return item

        def enqueue(item):
            events.append("enqueue")
            self.assertIsNone(item.help_message)
            self.assertIs(item.help_opened, False)
            pending.append(item)

        console = SimpleNamespace(debug=False, write=Mock())
        owner = SimpleNamespace(console_window=console)
        with patch.object(ckit, "JobItem", side_effect=create), \
             patch.object(ckit.JobQueue, "defaultQueue", return_value=SimpleNamespace(enqueue=enqueue)):
            clnch_mainwindow.MainWindow.command_Help(owner, None)
        self.assertEqual(events, ["create", "enqueue"])
        self.assertEqual(len(pending), 1)
        item = pending[0]
        finished = item.finished_func_list[0]
        finished(item)
        console.write.assert_not_called()
        message = "updated help result"
        item.help_message = message
        item.help_opened = True
        finished(item)
        self.assertIs(item.help_message, message)
        console.write.assert_called_once_with(message + "\n\n", auto_show=False)

    def test_app_resource_path_preserves_live_module_attribute_contract(self):
        from ckit import ckit_misc

        class ResourceModule(ModuleType):
            def __getattribute__(self, name):
                if name == "_clnch_app_dir":
                    namespace = ModuleType.__getattribute__(self, "__dict__")
                    namespace["events"].append("lookup")
                    value = ModuleType.__getattribute__(self, name)
                    if namespace["disappear"]:
                        ModuleType.__delattr__(self, name)
                    return value
                return ModuleType.__getattribute__(self, name)

        tree = ast.parse((ROOT / "ckit/ckit_misc.py").read_text(encoding="utf-8"))
        current = next(node for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name == "getAppExePath")
        original = ast.parse('''def getAppExePath():
    if hasattr(sys, "_clnch_app_dir"):
        return sys._clnch_app_dir
    return os.path.split(getArgv()[0])[0]
''').body[0]
        marker = object()

        def observe(node, case, warmup, optimize):
            module = ResourceModule("resource_contract")
            events = []
            namespace = module.__dict__
            namespace.update(events=events, disappear=case == "disappear")
            if case in ("normal", "disappear"):
                namespace["_clnch_app_dir"] = marker
            if case.startswith("dynamic"):
                def dynamic(name):
                    events.append("dynamic")
                    if case == "dynamic_missing" or (case == "dynamic_fail" and events.count("dynamic") == 2):
                        raise AttributeError("dynamic resource missing", name=name, obj=module)
                    return object() if events.count("dynamic") == 1 else marker
                namespace["__getattr__"] = dynamic

            def argv():
                events.append("argv")
                return [r"C:\app\reclnch.exe"]

            training = ModuleType("resource_training")
            training.__dict__["_clnch_app_dir"] = marker
            scope = dict(ckit_misc.__dict__, sys=training, getArgv=argv)
            code = compile(ast.Module(body=[node], type_ignores=[]), "resource_contract", "exec", optimize=optimize)
            exec(code, scope)  # noqa: S102  # Compare only the isolated resource-path function at both optimization levels.
            function = scope["getAppExePath"]
            for _ in range(warmup):
                self.assertIs(function(), marker)
            scope["sys"] = module
            try:
                result = function()
            except AttributeError as error:
                outcome = ("error", str(error), error.name, error.obj is module, error.obj is None)
            else:
                outcome = ("return", result is marker, result if isinstance(result, str) else None)
            return outcome, events

        for optimize in (0, 2):
            for warmup in (0, 1, 2, 3, 5, 10, 100):
                for case in ("normal", "missing", "dynamic", "dynamic_missing", "disappear", "dynamic_fail"):
                    with self.subTest(optimize=optimize, warmup=warmup, case=case):
                        before = observe(original, case, warmup, optimize)
                        after = observe(current, case, warmup, optimize)
                        self.assertEqual(after, before)
                        outcome, events = after
                        missing = case in ("missing", "dynamic_missing")
                        expected_events = ["lookup"] * (1 if missing else 2)
                        if case.startswith("dynamic"):
                            expected_events = [event for _ in expected_events for event in ("lookup", "dynamic")]
                        if missing:
                            expected_events.append("argv")
                            self.assertEqual(outcome, ("return", False, r"C:\app"))
                        elif case in ("normal", "dynamic"):
                            self.assertEqual(outcome, ("return", True, None))
                        else:
                            self.assertEqual(outcome[0], "error")
                        self.assertEqual(events, expected_events)
        for name in ("_Protocol", "_TypeGuard", "_AppResourceSys", "_has_app_resource_dir"):
            self.assertNotIn(name, ckit.__dict__)

    def test_required_data_path_keeps_public_none_identity_and_native_errors(self):
        from ckit import ckit_misc
        self.assertIs(ckit.dataPath, ckit_misc.dataPath)
        self.assertIs(ckit.setDataPath, ckit_misc.setDataPath)
        with patch.object(ckit_misc, "_data_path", None):
            self.assertIsNone(ckit.dataPath())
            for name, args in (("join", (None, "file")), ("abspath", (None,))):
                with self.assertRaises(TypeError) as original:
                    getattr(os.path, name)(*args)
                with self.assertRaises(TypeError) as current:
                    clnch_misc._require_data_path(ckit.dataPath(), for_abspath=name == "abspath")
                self.assertEqual(current.exception.args, original.exception.args)
                self.assertEqual(current.exception.__dict__, original.exception.__dict__)
            for value in ("", "日本語 folder", Path("relative path"), b"bytes", 17):
                ckit.setDataPath(value)
                self.assertIs(ckit.dataPath(), value)
                self.assertIs(clnch_misc._require_data_path(ckit.dataPath()), value)
            ckit.setDataPath(None)
            self.assertIsNone(ckit.dataPath())

    def test_all_data_path_operations_keep_lookup_conversion_and_failure_contracts(self):
        from ckit import ckit_misc
        class PathProbe:
            def __init__(self):
                self.calls = 0
            def __fspath__(self):
                self.calls += 1
                return str(ROOT / "日本語 folder")
        def capture(operation):
            try:
                result = operation()
                return type(result), result
            except Exception as error:  # noqa: BLE001  # Compare the actual path operation's failure contract.
                return type(error), error.args
        routes = []
        for name in ("clnch_cmdeditor.py", "clnch_cmdlist.py", "clnch_configmenu.py", "clnch_main.py", "clnch_mainwindow.py", "clnch_standard.py"):
            tree = ast.parse((ROOT / "clnch" / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("join", "abspath") and node.args):
                    continue
                argument = node.args[0]
                if (isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute)
                        and argument.func.attr == "_require_data_path"):
                    argument = argument.args[0]
                if (isinstance(argument, ast.Call)
                        and ((isinstance(argument.func, ast.Attribute) and argument.func.attr == "dataPath")
                             or (isinstance(argument.func, ast.Name) and argument.func.id == "dataPath"))):
                    routes.append((name, node))
        self.assertEqual(len(routes), 10)
        probe = PathProbe()
        for name, node in routes:
            operation = getattr(os.path, node.func.attr)
            tail = [ast.literal_eval(arg) for arg in node.args[1:]]
            code = compile(ast.Expression(node), name, "eval")
            for value in (None, "", "日本語 folder", Path("relative path"), b"bytes", 17, probe):
                with self.subTest(file=name, line=node.lineno, value=value), patch.object(ckit_misc, "_data_path", value):
                    probe.calls = 0
                    expected = capture(lambda operation=operation, value=value, tail=tail: operation(value, *tail))
                    conversions = probe.calls
                    probe.calls = 0
                    getter = Mock(wraps=ckit.dataPath)
                    namespace = {"os": os, "ckit": SimpleNamespace(dataPath=getter),
                                 "dataPath": getter, "clnch_misc": clnch_misc}
                    actual = capture(lambda code=code, namespace=namespace: eval(code, namespace))  # Evaluate only the current source's isolated path expression.
                    self.assertEqual(actual, expected)
                    getter.assert_called_once_with()
                    self.assertEqual(probe.calls, conversions)
                    self.assertIs(ckit.dataPath(), value)

    def test_startup_data_path_reads_and_effect_order(self):
        tree = ast.parse((ROOT / "clnch/clnch_main.py").read_text(encoding="utf-8"))
        nodes = [node for block in tree.body if isinstance(block, ast.Try)
                 for node in block.body if any(
            isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
            and child.func.attr == "dataPath" for child in ast.walk(node))]
        self.assertEqual(len(nodes), 3)
        code = compile(ast.Module(body=nodes, type_ignores=[]), "startup-paths", "exec")
        for missing_at in (None, 0, 1, 2):
            with self.subTest(missing_at=missing_at):
                events = []
                values: list[str | None] = ["first 日本語", "second path", "third path"]
                if missing_at is not None:
                    values[missing_at] = None
                iterator = iter(values)
                def get(values=iterator, events=events):
                    value = next(values)
                    events.append(("get", value))
                    return value
                paths, ini = [], SimpleNamespace()
                namespace = {"ckit": SimpleNamespace(dataPath=get, getAppExePath=lambda events=events: events.append("app") or "app path"),
                             "clnch_misc": clnch_misc, "clnch_ini": ini, "sys": SimpleNamespace(path=paths),
                             "os": SimpleNamespace(path=os.path, makedirs=lambda path, events=events, **kw: events.append(("mkdir", path, kw)))}
                if missing_at is None:
                    exec(code, namespace)  # noqa: S102  # Execute only the real startup path statements against controlled effects.
                    self.assertEqual(ini.ini_filename, os.path.join("third path", "reclnch.ini"))
                else:
                    with self.assertRaisesRegex(TypeError, "^expected str, bytes or os.PathLike object, not NoneType$"):
                        exec(code, namespace)  # noqa: S102  # Check the failure position within the actual startup sequence.
                    self.assertNotIn("ini_filename", vars(ini))
                expected = [("get", None if missing_at == 0 else "first 日本語")]
                if missing_at != 0:
                    expected += [("mkdir", os.path.join("first 日本語", "scripts"), {"exist_ok": True}),
                                 "app", ("get", None if missing_at == 1 else "second path")]
                    if missing_at != 1:
                        expected.append(("get", None if missing_at == 2 else "third path"))
                self.assertEqual(events, expected)
                self.assertEqual(paths, [] if missing_at in (0, 1) else [os.path.join("app path", "extensions"), os.path.join("second path", "scripts")])

    def test_editor_data_path_is_captured_at_import_and_none_import_still_fails(self):
        from ckit import ckit_misc
        first, second = "first path 日本語", "second path"
        def load():
            spec = importlib.util.spec_from_file_location("data_path_editor_probe", ROOT / "clnch/clnch_cmdeditor.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        with patch.object(ckit_misc, "_data_path", first):
            with patch.object(ckit, "dataPath", wraps=ckit.dataPath) as getter:
                editor = load()
                getter.assert_called_once_with()
            self.assertEqual(vars(editor)["JSON_PATH"], os.path.join(first, "commands.json"))
            ckit.setDataPath(second)
            self.assertEqual(ckit.dataPath(), second)
            self.assertEqual(vars(editor)["JSON_PATH"], os.path.join(first, "commands.json"))
            ckit.setDataPath(None)
            with self.assertRaisesRegex(TypeError, "^expected str, bytes or os.PathLike object, not NoneType$"):
                load()

    def test_force_abort_displays_current_app_name_before_aborting(self):
        events = []
        def message(hwnd, text, title, flags):
            self.assertEqual((hwnd, title, flags), (0, clnch_resource.clnch_appname, 0))
            self.assertIn("Remaining threads:", text)
            self.assertIn("ThreadID:", text)
            events.append("message")
        with patch.object(clnch_debug.ctypes.windll.user32, "MessageBoxW", side_effect=message), \
             patch.object(clnch_debug.os, "abort", side_effect=lambda: events.append("abort")):
            clnch_debug._forceAbort()
        self.assertEqual(events, ["message", "abort"])

    def test_join_args_roundtrips_windows_arguments(self):
        from clnch_commandplatform import split_commandline_args

        values = ["abc123", "a b", "a\tb", "", "日本語😀", "C:\\tail\\",
                  "C:\\two words\\", 'a"b', 'a' + "\\" * 3 + '"b', " leading "]
        for args in ([], ["abc", "123"], *([value] for value in values), values):
            with self.subTest(args=args):
                encoded = clnch_misc.joinArgs(args)
                # CommandLineToArgvW treats argv[0] as an executable, not an argument.
                self.assertEqual(split_commandline_args("probe.exe " + encoded)[1:], args)
        self.assertEqual(clnch_misc.joinArgs([]), "")
        self.assertEqual(clnch_misc.joinArgs(["abc", "123"]), "abc 123")

    def test_compare_time_keeps_one_second_tolerance_and_order(self):
        base = (2026, 10, 15, 12, 0, 0)
        for ignore, seconds, expected in ((True, 0, 0), (True, 1, 0),
                                          (True, 2, -1), (False, 1, -1)):
            with self.subTest(ignore=ignore, seconds=seconds), \
                 patch.object(clnch_misc, "ignore_1second", ignore):
                other = (2026, 10, 15, 12, 0, seconds)
                self.assertEqual(clnch_misc.compareTime(base, other), expected)
                self.assertEqual(clnch_misc.compareTime(other, base), -expected)

    def test_regex_lexer_marks_unmatched_text_and_keeps_matching_tokens(self):
        for text, tokens in (("y", [(0, ckit_textwidget.Token_Error)]),
                             ("x", [(0, ckit_textwidget.Token_Text)]),
                             ("xy", [(0, ckit_textwidget.Token_Text), (1, ckit_textwidget.Token_Error)]),
                             ("", [])):
            with self.subTest(text=text):
                lexer = ckit_textwidget.RegexLexer()
                lexer.rule_map = {"root": [("x", ckit_textwidget.Token_Text)]}
                self.assertEqual(lexer.lex("root", text, True), (tokens, "root"))
                self.assertEqual(lexer.lex("root", text, False), "root")

    def test_regex_lexer_preserves_rule_priority_groups_and_contexts(self):
        cases = (
            ({"root": [("z", 1), ("x", 2), (None, 7)]}, "abx", [(0, 7), (2, 2)], "root"),
            ({"root": [("z", 1), ("x", 2), (None, 7)]}, "x--z", [(0, 2), (1, 7), (3, 1)], "root"),
            ({"root": [("z", 1), ("x", 2), (None, 7)]}, "--x-z", [(0, 7), (2, 2), (3, 7), (4, 1)], "root"),
            ({"root": [("x", 2), ("z", 1), (None, 7)]}, "--x-z", [(0, 7), (2, 2), (3, 7), (4, 1)], "root"),
            ({"root": [("x", 1), ("x", 2), (None, 7)]}, "ax", [(0, 7), (1, 1)], "root"),
            ({"root": [(r"(a)(b)", (1, 2)), (None, 7)]}, "ab?", [(0, 1), (1, 2), (2, 7)], "root"),
            ({"root": [(r"(a)(b)", [1, 2]), (None, 7)]}, "ab?", [(0, 1), (1, 2), (2, 7)], "root"),
            ({"root": [(None, 7)]}, "abc", [(0, 7)], "root"),
            ({"root": [('"', 4, "quoted"), (None, 0)],
              "quoted": [('"', 4, "root"), (None, 6)]}, '"a"', [(0, 4), (1, 6), (2, 4)], "root"),
            ({"root": [(r"$", 0), (None, 7)]}, "", [], "root"),
        )
        for rules, text, tokens, ctx in cases:
            with self.subTest(rules=rules, text=text):
                lexer = ckit_textwidget.RegexLexer()
                lexer.rule_map = {name: entries[:] for name, entries in rules.items()}
                self.assertEqual(lexer.lex("root", text, True), (tokens, ctx))
                self.assertEqual(lexer.lex("root", text, False), ctx)
        lexer = ckit_textwidget.RegexLexer()
        lexer.rule_map = {"root": [("x", 1, "other", lexer.Detail), (None, 0)], "other": [(None, 2)]}
        self.assertEqual(lexer.lex("root", "x", True), ([(0, 1)], "other"))
        self.assertEqual(lexer.lex("root", "x", False), "root")

    def test_public_reexports_remain_available(self):
        import clnch_consolelog
        import clnch_consolewindow

        from ckit import ckitcore
        from pyauto import pyautocore

        for package, native in ((ckit, ckitcore), (pyauto, pyautocore)):
            for name, value in vars(native).items():
                if not name.startswith("_"):
                    self.assertIs(getattr(package, name), value)
        self.assertIs(clnch_consolewindow.Log, clnch_consolelog.Log)
        self.assertIs(ckit.Image, ckitcore.Image)
        self.assertIs(clnch.shellExecute, pyauto.shellExecute)
        self.assertIs(clnch.MainWindow, sys.modules["clnch_mainwindow"].MainWindow)

    def test_url_command_queues_encoded_first_argument(self):
        for args, encoding, keyword in (([], "utf8", ""),
                                        (["日本語 a&b", "ignored"], "utf8", "%E6%97%A5%E6%9C%AC%E8%AA%9E+a%26b"),
                                        (["あ"], "cp932", "%82%A0")):
            with self.subTest(args=args, encoding=encoding), \
                 patch.object(ckit.JobQueue, "defaultQueue") as default_queue, \
                 patch.object(pyauto, "shellExecute") as launch:
                command = clnch.MainWindow.UrlCommand(None, "https://example.test/%%/%param%", encoding)
                info = ckit.CommandInfo()
                info.args = args
                command(info)
                launch.assert_not_called()
                job = default_queue.return_value.enqueue.call_args.args[0]
                job.subthread_func(job)
                launch.assert_called_once_with(None, "https://example.test/%/" + keyword, "", "")


    def _default_queue_routes(self, path, commandline):
        import clnch_altenterconfig
        import clnch_commandline
        window = clnch.MainWindow.__new__(clnch.MainWindow)
        window.association_list = []
        window.altenter_settings = {
            **clnch_altenterconfig.DEFAULTS, "action": "application", "executable": "tool.exe"}
        info = ckit.CommandInfo()
        info.args = ["one", "two"]
        shell = clnch.MainWindow.ShellExecuteCommand(window, None, str(path), None, None)
        url = clnch.MainWindow.UrlCommand(window, "https://example.test/%param%")
        file_handler = clnch_commandline.commandline_ExecuteFile(window)
        url_handler = clnch_commandline.commandline_ExecuteURL(window)
        return [("alt", lambda: clnch_altenterconfig.execute(window, "hello")),
                ("file", lambda: file_handler.onEnter(commandline, str(path) + ";one;two", 0)),
                ("url", lambda: url_handler.onEnter(commandline, "https://example.test/", 0)),
                ("shell", lambda: shell(info)), ("url_command", lambda: url(info)),
                ("help", lambda: clnch.MainWindow.command_Help(window, info))]

    def test_default_queue_routes_keep_evaluation_order_and_enqueue_once(self):
        events, pending = [], []
        queue = SimpleNamespace(enqueue=lambda job: (events.append("enqueue"), pending.append(job)))
        original_item = ckit.JobItem
        def item(*args, **kwargs):
            events.append("job")
            return original_item(*args, **kwargs)
        def fetch():
            events.append("queue")
            return queue
        commandline = SimpleNamespace(appendHistory=Mock(), quit=Mock())
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            path = Path(directory) / "target.txt"
            path.write_text("target", encoding="utf-8")
            with patch.object(ckit.JobQueue, "defaultQueue", side_effect=fetch) as default, \
                 patch.object(ckit.JobQueue, "createDefaultQueue") as create, \
                 patch.object(ckit, "JobItem", side_effect=item), \
                 patch.object(pyauto, "shellExecute") as launch:
                for name, invoke in self._default_queue_routes(path, commandline):
                    with self.subTest(route=name):
                        events.clear()
                        commandline.appendHistory.reset_mock()
                        commandline.quit.reset_mock()
                        invoke()
                        self.assertEqual(events, ["queue", "job", "enqueue"] if name == "alt"
                                         else ["job", "queue", "enqueue"])
                        self.assertEqual(commandline.appendHistory.called, name in ("file", "url"))
                        self.assertEqual(commandline.quit.called, name in ("file", "url"))
                self.assertEqual(default.call_count, 6)
                self.assertEqual(len(pending), 6)
                self.assertEqual(len({id(job) for job in pending}), 6)
                create.assert_not_called()
                launch.assert_not_called()

    def test_default_queue_routes_keep_missing_queue_error_and_no_enqueue_side_effects(self):
        from ckit import ckit_threadutil
        events = []
        original_item = ckit.JobItem
        def item(*args, **kwargs):
            events.append("job")
            return original_item(*args, **kwargs)
        def fetch():
            events.append("queue")
        commandline = SimpleNamespace(appendHistory=Mock(), quit=Mock())
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            path = Path(directory) / "target.txt"
            path.write_text("target", encoding="utf-8")
            with patch.object(ckit_threadutil, "_job_queue", None):
                self.assertIsNone(ckit.JobQueue.defaultQueue())
                with patch.object(ckit.JobQueue, "defaultQueue", side_effect=fetch) as default, \
                     patch.object(ckit.JobQueue, "createDefaultQueue") as create, \
                     patch.object(ckit, "JobItem", side_effect=item):
                    for name, invoke in self._default_queue_routes(path, commandline):
                        with self.subTest(route=name):
                            events.clear()
                            with self.assertRaises(AttributeError) as raised:
                                invoke()
                            self.assertEqual(str(raised.exception), "'NoneType' object has no attribute 'enqueue'")
                            self.assertEqual(raised.exception.name, "enqueue")
                            self.assertIsNone(raised.exception.obj)
                            self.assertEqual(events, ["queue"] if name == "alt" else ["job", "queue"])
                    self.assertEqual(default.call_count, 6)
                    create.assert_not_called()
                self.assertIsNone(ckit.JobQueue.defaultQueue())
                commandline.appendHistory.assert_not_called()
                commandline.quit.assert_not_called()

    @staticmethod
    def load_keymap_sample():
        names = ("VK_LSHIFT", "VK_RSHIFT", "VK_LCONTROL", "VK_RCONTROL",
                 "VK_LMENU", "VK_RMENU", "VK_LWIN", "VK_RWIN")
        stub = SimpleNamespace(Hook=SimpleNamespace, **{name: getattr(pyauto, name) for name in names})
        spec = importlib.util.spec_from_file_location(
            "keymap_cleanup_test", ROOT / "pyauto/sample/keymap/keymap_hook.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"pyauto": stub}):
            spec.loader.exec_module(module)
        return module

    def test_key_event_comparison_keeps_optional_extra_and_single_truth_test(self):
        for left, right, expected in ((None, None, True), (None, 1, True),
                                     (1, None, True), (1, 1, True), (1, 2, False)):
            self.assertIs(ckit.KeyEvent(65, 0, left) == ckit.KeyEvent(65, 0, right), expected)
        events = []
        class Verdict:
            def __bool__(self):
                events.append("truth")
                return True
        class Extra:
            def __ne__(self, other):
                events.append("compare")
                return Verdict()
        self.assertIs(ckit.KeyEvent(65, 0, Extra()) == ckit.KeyEvent(65, 0, Extra()), False)
        self.assertEqual(events, ["compare", "truth"])
        self.assertIs(ckit.KeyEvent(65, 1) == ckit.KeyEvent(65, 0), False)
        self.assertIs(ckit.KeyEvent(65, 0) == ckit.KeyEvent(66, 0), False)

    def test_keymap_sample_comparison_returns_bool_for_modifier_combinations(self):
        module = self.load_keymap_sample()
        modifiers = (0, 1, 2, 3, 4, 5, 8, 16, 32, 0x101, 0x10001, 0x202, 0x20002, 0x303, 0x30003)
        for left in modifiers:
            for right in modifiers:
                expected = ((left & 0xff) == (right & 0xff)
                            and not (((left >> 8) & 0xff) & ((right >> 16) & 0xff))
                            and not (((left >> 16) & 0xff) & ((right >> 8) & 0xff)))
                self.assertIs(module.checkModifier(left, right), expected)
                self.assertIs(module.KeyStroke(65, left) == module.KeyStroke(65, right), expected)
        self.assertIs(module.KeyStroke(65) == module.KeyStroke(66), False)
        self.assertIs(module.KeyStroke(65, prefix="a") == module.KeyStroke(65, prefix="b"), False)

    def test_keymap_sample_callbacks_keep_shared_modifier_state(self):
        module = self.load_keymap_sample()
        events = []
        module._current_keymap = SimpleNamespace(
            onKeyDown=lambda vk, mod: events.append(("down", vk, mod)) or True,
            onKeyUp=lambda vk, mod: events.append(("up", vk, mod)) or False)
        self.assertIs(module._hook.keydown(pyauto.VK_LCONTROL, 0), True)
        self.assertEqual(module._modifier, module.MODKEY_CTRL_L)
        self.assertIs(module._hook.keydown(65, 0), True)
        self.assertIs(module._hook.keyup(pyauto.VK_LCONTROL, 0), False)
        self.assertEqual(module._modifier, 0)
        self.assertEqual(events, [("down", pyauto.VK_LCONTROL, module.MODKEY_CTRL_L),
                                  ("down", 65, module.MODKEY_CTRL_L),
                                  ("up", pyauto.VK_LCONTROL, 0)])
        module._current_keymap = None
        self.assertIs(module._hook.keydown(65, 0), False)

    def test_word_completion_scans_buffers_and_keeps_input_range(self):
        left, right = object(), object()
        point = SimpleNamespace(wordLeft=lambda: left, wordRight=lambda: right)
        text = {"hint": "alp", "tail": ""}
        edit = SimpleNamespace(getText=lambda begin, end: text["hint" if end is point else "tail"])
        document = lambda lines: SimpleNamespace(doc=SimpleNamespace(lines=[SimpleNamespace(s=s) for s in lines]))
        window = SimpleNamespace(edit_list=[
            document(["alpha alpine", "alphabet alpha"]),
            document(["alphanumeric"]),
            document(["alphanumeric" + "x" * 1000]),
            document(["alpinist"] * 10001)])
        completion = ckit_textwidget.WordCompletion()
        result = completion.getCandidateList(window, edit, point)
        self.assertEqual(result.items, ["alpha", "alphabet", "alphanumeric", "alpine"])
        self.assertEqual(result.selection, 0)
        self.assertIs(result.left, left)
        self.assertIs(result.right, point)
        window.edit_list = []
        self.assertEqual(completion.getCandidateList(window, edit, point).items, [])
        for hint, tail in (("", ""), ("日本語", ""), ("alp", "ha")):
            text.update(hint=hint, tail=tail)
            self.assertIsNone(completion.getCandidateList(window, edit, point))

    def test_network_connection_only_handles_unc_roots(self):
        cases = [("", []), ("C:/folder", []), ("relative/folder", []),
                 (r"\\server\share\folder", [r"\\server\share"]),
                 ("//server/share/folder", [r"\\server\share"]),
                 (r"\\日本語\共有\階層", [r"\\日本語\共有"]),
                 (Path("C:/folder"), [])]
        for path, expected in cases:
            events = []
            with self.subTest(path=path), patch.object(clnch_misc, "_net_connection_handler", events.append):
                clnch_misc.checkNetConnection(path)
            self.assertEqual(events, expected)

    def test_network_handler_unregistered_failure_and_replacement_notifications(self):
        output, events = io.StringIO(), []
        def first(root):
            events.append(("first", root))
            clnch_misc.registerNetConnectionHandler(lambda root: events.append(("second", root)))
        with patch.object(clnch_misc, "_net_connection_handler", None), contextlib.redirect_stdout(output):
            self.assertIsNone(clnch_misc._net_connection_handler)
            self.assertIsNone(clnch_misc.checkNetConnection("C:/local"))
            self.assertEqual(output.getvalue(), "")
            self.assertIsNone(clnch_misc.checkNetConnection("//server/share/file"))
            self.assertEqual(output.getvalue(), "'NoneType' object is not callable\n")
            clnch_misc.registerNetConnectionHandler(first)
            self.assertIs(clnch_misc._net_connection_handler, first)
            clnch_misc.checkNetConnection("//server/share/first")
            clnch_misc.checkNetConnection("//server/share/second")
            failure = Mock(side_effect=ValueError("connection failed"))
            clnch_misc.registerNetConnectionHandler(failure)
            self.assertIsNone(clnch_misc.checkNetConnection("//server/share/failure"))
            failure.assert_called_once_with(r"\\server\share")
            self.assertEqual(output.getvalue(), "'NoneType' object is not callable\nconnection failed\n")
            clnch_misc.registerNetConnectionHandler(None)
            self.assertIsNone(clnch_misc._net_connection_handler)
        self.assertEqual(events, [("first", r"\\server\share"), ("second", r"\\server\share")])

    def test_theme_uninitialized_and_missing_color_keep_black_notification(self):
        parser = configparser.RawConfigParser()
        outputs = []
        for value in (None, parser):
            output = io.StringIO()
            with self.subTest(parser=value), patch.object(ckit_theme, "ini", value), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(ckit_theme.getColor("missing"), (0, 0, 0))
                outputs.append(output.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        self.assertIn("missing", outputs[0])
        self.assertEqual(len(outputs[0].splitlines()), 1)

    def test_theme_parser_replacement_preserves_public_alias_and_invalid_color(self):
        exported = ckit.ini
        with patch.object(ckit_theme, "ini", None), \
             patch.object(ckit_theme, "theme_name", ckit_theme.theme_name), \
             patch.object(configparser.RawConfigParser, "read", return_value=[]):
            ckit_theme.setTheme("first", {"valid": (1, 2, 3), "invalid": "invalid"})
            first = ckit_theme.ini
            self.assertIsInstance(first, configparser.RawConfigParser)
            self.assertIs(ckit.ini, exported)
            self.assertEqual(ckit_theme.getColor("valid"), (1, 2, 3))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertIsNone(ckit_theme.getColor("invalid"))
            self.assertEqual(output.getvalue(), "")
            ckit_theme.setTheme("second", {"valid": (4, 5, 6)})
            self.assertIsNot(ckit_theme.ini, first)
            self.assertIs(ckit.ini, exported)
            self.assertEqual(ckit_theme.getColor("valid"), (4, 5, 6))

    def test_theme_read_failure_keeps_created_parser_and_propagates_error(self):
        failure = configparser.Error("theme read failed")
        with patch.object(ckit_theme, "ini", None), \
             patch.object(ckit_theme, "theme_name", ckit_theme.theme_name), \
             patch.object(configparser.RawConfigParser, "read", side_effect=failure):
            with self.assertRaises(configparser.Error) as raised:
                ckit_theme.setTheme("failure", {"valid": (1, 2, 3)})
            self.assertIs(raised.exception, failure)
            self.assertIsInstance(ckit_theme.ini, configparser.RawConfigParser)
            self.assertEqual(ckit_theme.getColor("valid"), (1, 2, 3))

    def test_theme_and_lexer_accept_keys_only_mappings(self):
        class KeysOnly:
            def __init__(self, data): self.data = data
            def keys(self): return self.data.keys()
            def __getitem__(self, key): return self.data[key]
        lexer = ckit_textwidget.RegexLexer()
        lexer.rule_map = KeysOnly({"root": [("x", ckit_textwidget.Token_Text)]})
        self.assertEqual(lexer.lex("root", "xy", True),
                         ([(0, ckit_textwidget.Token_Text), (1, ckit_textwidget.Token_Error)], "root"))
        with patch.object(ckit_theme, "ini", ckit_theme.ini), \
             patch.object(ckit_theme, "theme_name", ckit_theme.theme_name), \
             patch.object(ckit_theme.configparser.RawConfigParser, "read", return_value=[]):
            ckit_theme.setTheme("mapping-contract", KeysOnly({"contract_color": (1, 2, 3)}))
            self.assertEqual(ckit_theme.getColor("contract_color"), (1, 2, 3))

class ResourceCleanupTests(unittest.TestCase):
    @staticmethod
    def source_nodes(relative, names):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
        return [node for node in tree.body if getattr(node, "name", None) in names]

    @staticmethod
    def execute(nodes, namespace):
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "resource-cleanup-test", "exec"), namespace)  # noqa: S102  # Execute isolated source without sample startup or packaging.

    def test_user_config_file_is_closed_before_compile_and_error_reporting(self):
        from ckit import ckit_userconfig as hooks
        for source, read_error, reports in ((b"value = 42", False, 0),
                                            (b"invalid =", False, 1),
                                            (b"raise SystemExit(7)", False, 1),
                                            (b"", True, 1)):
            with self.subTest(source=source, read_error=read_error):
                fd = io.BytesIO(source)
                self.addCleanup(fd.close)
                def checked_compile(*args, stream=fd):
                    self.assertTrue(stream.closed)
                    return compile(*args)
                def report(stream=fd):
                    self.assertTrue(stream.closed)
                with (
                    patch.object(hooks, "open", return_value=fd, create=True),
                    patch.object(hooks, "compile", side_effect=checked_compile, create=True),
                    patch.object(hooks, "user_namespace", {"old": True}, create=True),
                    patch.object(hooks.traceback, "print_exc", side_effect=report) as errors,
                    patch.object(fd, "read", side_effect=OSError("read")) if read_error else contextlib.nullcontext(),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    hooks.reloadConfigScript("config-probe.py")
                    self.assertTrue(fd.closed)
                    self.assertEqual(errors.call_count, reports)
                    if read_error:
                        self.assertEqual(hooks.user_namespace, {"old": True})
                    elif not reports:
                        self.assertEqual(hooks.user_namespace["value"], 42)

    def test_keymap_config_closes_before_compile_and_returns_on_missing_file(self):
        nodes = self.source_nodes("pyauto/sample/keymap/keymap_config.py", {"loadConfigFile"})
        namespace = {"user_namespace": {}}
        self.execute(nodes, namespace)
        fd = io.StringIO("value = 42")
        self.addCleanup(fd.close)
        def checked_compile(*args):
            self.assertTrue(fd.closed)
            return compile(*args)
        namespace.update(open=Mock(return_value=fd), compile=checked_compile)
        with contextlib.redirect_stdout(io.StringIO()):
            namespace["loadConfigFile"]()
        self.assertEqual(namespace["user_namespace"]["value"], 42)
        compiler = Mock()
        namespace.update(open=Mock(side_effect=FileNotFoundError("missing")), compile=compiler)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            namespace["loadConfigFile"]()
        compiler.assert_not_called()
        self.assertEqual(namespace["user_namespace"]["value"], 42)
        self.assertIn("ERROR : no config file.", output.getvalue())

    def test_ini_read_closes_on_lock_and_parse_failure_before_reporting(self):
        import clnch_ini
        wait = clnch_ini._winapi.WaitForSingleObject
        for failure in ("none", "lock", "parse"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
                fd = io.StringIO("[broken" if failure == "parse" else "[S]\nvalue=ok\n")
                self.addCleanup(fd.close)
                reports = []
                with (
                    patch.object(clnch_ini, "ini_filename", str(Path(directory) / "probe.ini")),
                    patch.object(clnch_ini, "ini", None),
                    patch.object(clnch_ini, "dirty", True),
                    patch.object(clnch_ini, "read_failed", False),
                    patch.object(clnch_ini, "open", return_value=fd, create=True),
                    patch.object(clnch_ini._winapi, "WaitForSingleObject", wraps=wait,
                                 side_effect=OSError("lock") if failure == "lock" else None),
                    patch.object(clnch_ini.clnch_debug, "printErrorInfo",
                                 side_effect=lambda stream=fd, log=reports: log.append(stream.closed)),
                ):
                    clnch_ini.read()
                    self.assertEqual(fd.closed, failure != "lock")
                    self.assertFalse(clnch_ini.dirty)
                    self.assertEqual(reports, [] if failure == "none" else [failure != "lock"])
                    if failure == "none":
                        self.assertEqual(clnch_ini.ini.get("S", "value"), "ok")

    def test_ini_write_keeps_dirty_until_close_succeeds(self):
        import clnch_ini
        create = tempfile.NamedTemporaryFile
        wait = clnch_ini._winapi.WaitForSingleObject
        for failure in ("none", "lock", "write", "close"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
                path = Path(directory) / "probe.ini"
                path.write_bytes(b"[S]\r\nvalue = old\r\n")
                streams = []
                reports = []
                @contextlib.contextmanager
                def temporary(failure=failure, streams=streams, **kwargs):
                    with create(**kwargs) as fd:
                        streams.append(fd)
                        yield fd
                    if failure == "close":
                        raise OSError("close")
                def opened(*args, streams=streams, **kwargs):
                    fd = open(*args, **kwargs)  # noqa: SIM115  # The caller's with statement owns this tracked stream.
                    streams.append(fd)
                    return fd
                ini = configparser.RawConfigParser()
                ini["S"] = {"value": "ok"}
                with (
                    patch.object(clnch_ini, "ini_filename", str(path)),
                    patch.object(clnch_ini, "ini", ini),
                    patch.object(clnch_ini, "dirty", True),
                    patch.object(clnch_ini, "open", side_effect=opened, create=True) as open_mock,
                    patch.object(clnch_ini.tempfile, "NamedTemporaryFile", side_effect=temporary),
                    patch.object(clnch_ini._winapi, "WaitForSingleObject", wraps=wait,
                                 side_effect=OSError("lock") if failure == "lock" else None),
                    patch.object(ini, "write", side_effect=OSError("write")) if failure == "write" else contextlib.nullcontext(),
                    patch.object(clnch_ini.clnch_debug, "printErrorInfo",
                                 side_effect=lambda streams=streams, log=reports: log.append(all(fd.closed for fd in streams))),
                ):
                    clnch_ini.write()
                    self.assertEqual(clnch_ini.dirty, failure != "none")
                    self.assertTrue(all(fd.closed for fd in streams))
                    self.assertEqual(reports, [] if failure == "none" else [True])
                    self.assertEqual(list(Path(directory).glob("*.tmp")), [])
                    open_mock.reset_mock()
                    clnch_ini.dirty = False
                    clnch_ini.write()
                    open_mock.assert_not_called()


    def test_ini_failure_releases_real_windows_lock_before_error_report(self):
        import clnch_ini
        for operation in ("read", "write"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "probe.ini"
                path.write_bytes(b"[broken\r\n")
                reports = []
                def report(log=reports):
                    name = created.call_args.args[2]
                    handle = clnch_ini._winapi.OpenMutexW(0x100000, False, name)
                    if handle:
                        clnch_ini._winapi.CloseHandle(handle)
                    self.assertFalse(handle)
                    log.append("unlocked")
                ini = Mock(write=Mock(side_effect=OSError("write")))
                with (
                    patch.object(clnch_ini, "ini_filename", str(path)),
                    patch.object(clnch_ini, "ini", ini),
                    patch.object(clnch_ini, "dirty", True),
                    patch.object(clnch_ini._winapi, "CreateMutexW", wraps=clnch_ini._winapi.CreateMutexW) as created,
                    patch.object(clnch_ini, "read_failed", False),
                    patch.object(clnch_ini.clnch_debug, "printErrorInfo", side_effect=report),
                ):
                    getattr(clnch_ini, operation)()
                    self.assertEqual(reports, ["unlocked"])
                    self.assertEqual(clnch_ini.dirty, operation == "write")

    def test_ini_setters_keep_missing_same_and_invalid_integer_behavior(self):
        import clnch_ini
        for name, value, old in (("set", "new", None), ("set", "new", "old"),
                                  ("set", "new", "new"), ("setint", 42, None),
                                  ("setint", 42, "old"), ("setint", 42, "42")):
            with self.subTest(name=name, old=old):
                ini = configparser.RawConfigParser()
                if old is not None:
                    ini["S"] = {"value": old}
                with patch.object(clnch_ini, "ini", ini), patch.object(clnch_ini, "dirty", False):
                    getattr(clnch_ini, name)("S", "value", value)
                    self.assertEqual(ini.get("S", "value"), str(value))
                    self.assertEqual(clnch_ini.dirty, old != str(value))
                    clnch_ini.dirty = True
                    getattr(clnch_ini, name)("S", "value", value)
                    self.assertTrue(clnch_ini.dirty)
        for name, value in (("set", "added"), ("setint", 42)):
            ini = configparser.RawConfigParser()
            ini.add_section("S")
            with patch.object(clnch_ini, "ini", ini), patch.object(clnch_ini, "dirty", False):
                getattr(clnch_ini, name)("S", "value", value)
                self.assertEqual(ini.get("S", "value"), str(value))
                self.assertTrue(clnch_ini.dirty)

    def test_ini_setters_propagate_unexpected_lookup_errors_without_writing(self):
        import clnch_ini
        for name, getter, value in (("set", "get", "new"), ("setint", "getint", 42)):
            with self.subTest(name=name):
                ini = Mock()
                getattr(ini, getter).side_effect = RuntimeError("unexpected")
                with (
                    patch.object(clnch_ini, "ini", ini),
                    patch.object(clnch_ini, "dirty", False),
                    self.assertRaisesRegex(RuntimeError, "unexpected"),
                ):
                    getattr(clnch_ini, name)("S", "value", value)
                ini.add_section.assert_not_called()
                ini.set.assert_not_called()

    def test_huge_text_lines_preserve_encoding_offsets_and_end_of_file(self):
        from ckit.ckit_hugefile import HugeTextFile

        reader_type = HugeTextFile
        for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
            for text in ("first\r\n日本語\nthird\rtail", "no newline", "one\n", ""):
                lines = text.splitlines(keepends=True)
                if not text or text.endswith(("\r", "\n")):
                    lines.append("")
                for prefix in (b"", b"prefix"):
                    if not text and not prefix:
                        continue
                    with self.subTest(encoding=encoding, text=text, prefix=prefix), tempfile.TemporaryFile() as fd:
                        fd.write(prefix + text.encode(encoding))
                        fd.flush()
                        with contextlib.closing(reader_type(fd.fileno(), encoding, len(prefix))) as reader:
                            for index in reversed(range(len(lines))):
                                self.assertEqual(reader.getLine(index), lines[index].encode(encoding))
                            with self.assertRaises(IndexError):
                                reader.getLine(len(lines))

    def test_hugefile_import_has_no_file_or_output_side_effects(self):
        spec = importlib.util.spec_from_file_location("hugefile_probe", ROOT / "ckit/ckit_hugefile.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        output = io.StringIO()
        with patch("builtins.open", side_effect=AssertionError("unexpected file access")), \
             contextlib.redirect_stdout(output):
            spec.loader.exec_module(module)
        self.assertEqual(output.getvalue(), "")

    def test_huge_text_block_boundaries_long_lines_and_mapping_ownership(self):
        from ckit.ckit_hugefile import HugeTextFile

        for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
            for ending in ("\r", "\n", "\r\n"):
                for delta in range(-4, 5):
                    width = len("a".encode(encoding))
                    first = "a" * ((65536 + delta) // width) + ending
                    lines = (first, "日本語" + ending, "x" * 150000 + ending, "tail")
                    prefix = b"BOM"
                    with self.subTest(encoding=encoding, ending=ending, delta=delta), tempfile.TemporaryFile() as fd:
                        content = prefix + "".join(lines).encode(encoding)
                        fd.write(content)
                        fd.flush()
                        reader = HugeTextFile(fd.fileno(), encoding, len(prefix))
                        try:
                            for index in (0, 2, 1, 3, 0, 2):
                                self.assertEqual(reader.getLine(index), lines[index].encode(encoding))
                            for _ in range(2):
                                with self.assertRaises(IndexError):
                                    reader.getLine(4)
                        finally:
                            reader.close()
                        self.assertTrue(reader.mm.closed)
                        self.assertFalse(fd.closed)
                        fd.seek(0)
                        self.assertEqual(fd.read(), content)

    def test_huge_text_scans_bounded_blocks_and_reuses_cached_endpoints(self):
        from ckit.ckit_hugefile import HugeTextFile

        with tempfile.TemporaryFile() as fd:
            fd.write(b"line\r\n" * 100000)
            fd.flush()
            with contextlib.closing(HugeTextFile(fd.fileno(), "utf-8", 0)) as reader:
                self.assertEqual(reader.line_pos, [0])
                scanner = Mock(wraps=reader.line_end_re_object)
                reader.line_end_re_object = scanner
                self.assertEqual(reader.getLine(0), b"line\r\n")
                self.assertLess(reader.line_pos[-1], 65536 + 4)
                count = scanner.finditer.call_count
                for _ in range(10):
                    for index in (0, 2, 1):
                        self.assertEqual(reader.getLine(index), b"line\r\n")
                self.assertEqual(scanner.finditer.call_count, count)
                self.assertEqual(reader.getLine(99999), b"line\r\n")
                self.assertEqual(reader.getLine(100000), b"")
                for args, _ in scanner.finditer.call_args_list:
                    self.assertIs(args[0], reader.mm)
                    self.assertLessEqual(args[2] - args[1], 65536 + 3)

    def test_huge_binary_reads_and_closes_mapping(self):
        from ckit.ckit_hugefile import HugeBinaryFile

        content = bytes(range(256)) * 2
        with tempfile.TemporaryFile() as fd:
            fd.write(content)
            fd.flush()
            with contextlib.closing(HugeBinaryFile(fd.fileno())) as reader:
                self.assertEqual(reader.getBytes(0, 16), content[:16])
                self.assertEqual(reader.getBytes(250, 20), content[250:270])
                self.assertEqual(reader.getBytes(len(content), 16), b"")
            self.assertTrue(reader.mm.closed)
        self.assertTrue(fd.closed)

    def test_archive_digest_closes_on_error_without_generating_distribution(self):
        nodes = self.source_nodes("makefile.py", {"target_archive"})
        for failure, verified in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(failure=failure, verified=verified):
                fd = io.BytesIO(b"archive-data")
                self.addCleanup(fd.close)
                path = SimpleNamespace(basename=os.path.basename)
                namespace = {
                    "check_package_files": Mock(), "zipfile": SimpleNamespace(ZipFile=MagicMock()),
                    "DIST_DIR": "dist/ReCraftLaunch", "ARCHIVE_NAME": "probe.zip",
                    "makedirs": Mock(), "createZip": Mock(),
                    "os": SimpleNamespace(path=path, chdir=Mock()),
                    "hashlib": hashlib, "open": Mock(return_value=fd),
                }
                namespace["zipfile"].ZipFile.return_value.__enter__.return_value.testzip.return_value = None
                self.execute(nodes, namespace)
                output = io.StringIO()
                with (
                    patch.object(fd, "read", side_effect=OSError("read")) if failure else contextlib.nullcontext(),
                    contextlib.redirect_stdout(output),
                ):
                    if failure:
                        with self.assertRaisesRegex(OSError, "read"):
                            namespace["target_archive"](verified=verified)
                    else:
                        namespace["target_archive"](verified=verified)
                self.assertTrue(fd.closed)
                if verified:
                    namespace["check_package_files"].assert_not_called()
                else:
                    namespace["check_package_files"].assert_called_once_with("dist/ReCraftLaunch")
                namespace["open"].assert_called_once_with("dist/probe.zip", "rb")
                self.assertEqual(output.getvalue(), "" if failure else
                                 "\nSHA256 probe.zip: " + hashlib.sha256(b"archive-data").hexdigest() + "\n")

    def test_document_locale_only_swallows_expected_locale_errors(self):
        for relative in ("tools/rst2html_pygments.py",):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            index = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Try))
            for error in (None, locale.Error("unsupported"), RuntimeError("unexpected"),
                          KeyboardInterrupt(), SystemExit(7)):
                with self.subTest(relative=relative, error=type(error).__name__):
                    fake = SimpleNamespace(LC_ALL=locale.LC_ALL, Error=locale.Error,
                                           setlocale=Mock(side_effect=error))
                    output = io.StringIO()
                    with patch.dict(sys.modules, {"locale": fake}), contextlib.redirect_stdout(output):
                        if error is None or isinstance(error, locale.Error):
                            self.execute(tree.body[:index + 1], {})
                        else:
                            with self.assertRaises(type(error)):
                                self.execute(tree.body[:index + 1], {})
                    self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
