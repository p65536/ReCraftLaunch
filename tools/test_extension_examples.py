"""Execute the bilingual manual's code; replace UI calls in these contract checks."""
import ast
import contextlib
import io
import re
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_commandline
import clnch_inputconfig

import ckit


def example_sources(language="ja"):
    text = (ROOT / f"docs/{language}/extensions.md").read_text(encoding="utf-8")
    pairs = re.findall(r"<!-- example: (\w+) -->\s*```python\n(.*?)```", text, re.DOTALL)
    assert len(dict(pairs)) == len(pairs), "Duplicate example identifier"
    return dict(pairs)


def load_example(name, module_name="manual_example"):
    module = types.ModuleType(module_name)
    source = example_sources()[name]
    exec(compile(source, f"docs/ja/extensions.md:{name}", "exec"), module.__dict__)  # noqa: S102  # Run the documented code, not a duplicated test implementation.
    return module


class ExtensionExamplesTests(unittest.TestCase):
    def setUp(self):
        ckit.Keymap.init()
        self.window = SimpleNamespace(
            launcher=SimpleNamespace(command_list=[]), keymap=ckit.Keymap(), cmd_keymap=ckit.Keymap(),
            registerConfigCleanup=lambda func: None)

    def handler(self, name):
        return dict(self.window.launcher.command_list)[name]

    def test_bilingual_examples_have_same_code_and_all_compile(self):
        japanese, english = example_sources(), example_sources("en")
        self.assertEqual(set(japanese), set(english))
        self.assertTrue(japanese)
        for name, source in japanese.items():
            with self.subTest(name=name):
                self.assertEqual(ast.dump(ast.parse(source)), ast.dump(ast.parse(english[name])))
                compile(source, name, "exec")

    def test_ime_query_reports_unsupported_and_failures(self):
        describe = load_example("ime_query").describe_ime
        self.assertEqual(describe(None), "No focus")
        for state, expected in ((True, "Composing"), (False, "Idle"), (None, "Unsupported")):
            calls = []
            def query(timeout, state=state, calls=calls):
                calls.append(timeout)
                return state
            self.assertEqual(describe(SimpleNamespace(isImeConverting=query)), expected)
            self.assertEqual(calls, [250])
        for error in (TimeoutError("deadline"), OSError("access"), ValueError("same process")):
            def fail(timeout, error=error):
                raise error
            self.assertEqual(describe(SimpleNamespace(isImeConverting=fail)),
                             f"{type(error).__name__}: {error}")

    def test_cleanup_example_captures_and_releases_the_registered_status(self):
        callbacks, layers = [], {}
        self.window.registerConfigCleanup = callbacks.append
        self.window.registerStatusBar = lambda func, interval: layers.__setitem__(func, interval)
        self.window.unregisterStatusBar = layers.pop
        load_example("reload_cleanup").configure(self.window)
        self.assertEqual(len(layers), 1)
        callback, interval = next(iter(layers.items()))
        self.assertEqual((callback(40), interval), ("Reload safe", 1000))
        callbacks.pop()()
        self.assertEqual(layers, {})

    def test_inline_command_through_real_named_dispatch(self):
        load_example("echo_inline").configure(self.window)
        launcher = clnch_commandline.commandline_Launcher(self.window)
        launcher.command_list = self.window.launcher.command_list
        for text, expected in (("myecho", "Usage:"), ("MYECHO;hello world", "hello | world"),
                               ('myecho;hello "" world', "hello |  | world")):
            with self.subTest(text=text):
                planned = []
                session = SimpleNamespace(planCommand=lambda *args, planned=planned: planned.append(args), quit=lambda: None)
                self.assertTrue(launcher.onEnter(session, text, ckit.MODKEY_CTRL))
                command, info, history = planned[0]
                self.assertEqual(info.mod, ckit.MODKEY_CTRL)
                self.assertEqual(history, text)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    command(info)
                self.assertIn(expected, output.getvalue())

    def test_module_setup_and_actual_main_key_arguments(self):
        module = load_example("echo_module", "my_echo")
        with patch.dict(sys.modules, my_echo=module):
            load_example("echo_setup").configure(self.window)
        output = io.StringIO()
        session = SimpleNamespace(getText=lambda: "draft;one")
        received = []
        def execute(command, info, history, quit):
            received.append((info.args, info.mod, history, quit))
            command(info)
        session.executeCommand = execute
        with contextlib.redirect_stdout(output):
            self.assertTrue(clnch_commandline._LauncherInputHandlers(self.window).onKeyDown(
                session, ckit.VK_F9, ckit.MODKEY_CTRL))
        self.assertEqual(received, [(["draft;one"], 0, None, False)])
        self.assertEqual(output.getvalue(), "Input: draft;one\n")

    def test_script_import_reload_and_apply_failure_boundary(self):
        sources = example_sources()
        previous = sys.modules.get("custom")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            module_path = root / "scripts/my_echo.py"
            module_path.write_text(sources["echo_module"], encoding="utf-8")
            config = root / "custom.py"
            config.write_text(sources["echo_setup"], encoding="utf-8")
            with patch.object(sys, "path", [str(root / "scripts"), *sys.path]), patch.dict(sys.modules):
                sys.modules.pop("my_echo", None)
                try:
                    clnch_inputconfig.load(config).configure(self.window)
                    loaded = sys.modules["my_echo"]
                    module_path.write_text('raise RuntimeError("edited module")\n', encoding="utf-8")
                    self.window.launcher.command_list.clear()
                    with self.assertRaisesRegex(RuntimeError, "edited module"):
                        clnch_inputconfig.load(config).configure(self.window)
                    self.assertNotIn("myecho", dict(self.window.launcher.command_list))
                    self.assertNotIn("my_echo", sys.modules)
                    module_path.write_text(sources["echo_module"], encoding="utf-8")
                    clnch_inputconfig.load(config).configure(self.window)
                    self.assertIsNot(sys.modules["my_echo"], loaded)
                    self.assertIn("myecho", dict(self.window.launcher.command_list))
                finally:
                    if previous is None:
                        sys.modules.pop("custom", None)
                    else:
                        sys.modules["custom"] = previous

    def test_input_completion_accept_empty_and_cancel(self):
        for result, expected in (("apple", "Fruit: apple"), ("", "Fruit: "), (None, "Canceled")):
            with self.subTest(result=result):
                def prompt(title, result=result, **options):
                    self.assertEqual(title, "Fruit")
                    self.assertIs(options["auto_complete"], False)
                    callback = options["candidate_handler"]
                    self.assertEqual(callback(ckit.EditWidget.UpdateInfo("ap", [2, 2])),
                                     (["apple", "apricot"], 0))
                    self.assertEqual(callback(ckit.EditWidget.UpdateInfo("z", [1, 1])), ([], 0))
                    return result
                self.window.commandLine = prompt
                module = load_example("input_module", "my_input")
                with patch.dict(sys.modules, my_input=module):
                    load_example("input_setup").configure(self.window)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.handler("myask")(ckit.CommandInfo())
                self.assertEqual(output.getvalue(), expected + "\n")

    def test_menu_checks_cancel_before_negative_index(self):
        module = load_example("menu_module", "my_menu")
        with patch.dict(sys.modules, my_menu=module):
            load_example("menu_setup").configure(self.window)
        for result, expected in ((0, "Choice: docs"), (1, "Choice: downloads"), (-1, "Canceled")):
            with self.subTest(result=result), patch.object(module, "popMenu", return_value=result) as menu:
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.handler("mypick")(ckit.CommandInfo())
                self.assertEqual(output.getvalue(), expected + "\n")
                self.assertEqual(menu.call_args.kwargs["items"],
                                 [("Documents", "docs"), ("Downloads", "downloads")])

    def test_worker_result_and_cancel_use_real_subthread_call(self):
        from test_input_session import FakeWindow

        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                window = FakeWindow()
                window.launcher = SimpleNamespace(command_list=[])
                statuses = []
                owner = threading.get_ident()
                window.setStatusMessage = lambda *args, statuses=statuses, **kwargs: statuses.append(
                    (args, kwargs, threading.get_ident()))
                def loop(alive, cancel=cancel, window=window):
                    if cancel:
                        window.keydown_hook(ckit.VK_ESCAPE, 0)
                    deadline = time.monotonic() + 3
                    while alive() and time.monotonic() < deadline:
                        time.sleep(0.001)
                    self.assertFalse(alive(), "Example worker failed to finish")
                window.loop = loop
                module = load_example("worker_module", "my_worker")
                with patch.dict(sys.modules, my_worker=module):
                    load_example("worker_setup").configure(window)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    dict(window.launcher.command_list)["mycount"](ckit.CommandInfo())
                if cancel:
                    self.assertEqual(output.getvalue(), "Canceled\n")
                    self.assertEqual(statuses, [])
                else:
                    self.assertEqual(statuses, [(("Count: 20",), {"timeout": 2000}, owner)])
                self.assertIsNone(window.keydown_hook)
                self.assertIsNone(window.char_hook)

    def test_documented_form_always_restores_parent(self):
        for accepted, enabled, failed in ((True, True, False), (False, True, False),
                                          (True, False, False), (False, True, True)):
            with self.subTest(accepted=accepted, enabled=enabled, failed=failed):
                events = []
                class Form:
                    RESULT_OK = 1
                    Edit = ckit.Dialog.Edit
                    Choice = ckit.Dialog.Choice
                    def __init__(self, window, title, items):
                        self.title = title
                        self.items = items
                    def destroy(self, events=events): events.append("destroy")
                    def messageLoop(self, failed=failed):
                        if failed:
                            raise ValueError("dialog failure")
                    def getResult(self, accepted=accepted):
                        return int(accepted), {"name": "Alex", "style": 0}
                self.window.isEnabled = lambda enabled=enabled: enabled
                self.window.enable = lambda value, events=events: events.append(("enable", value))
                self.window.activate = lambda events=events: events.append("activate")
                module = load_example("dialog_module", "my_form")
                with patch.dict(sys.modules, my_form=module):
                    load_example("dialog_setup").configure(self.window)
                output = io.StringIO()
                with patch.object(ckit, "Dialog", Form), contextlib.redirect_stdout(output):
                    if failed:
                        with self.assertRaisesRegex(ValueError, "dialog failure"):
                            self.handler("myform")(ckit.CommandInfo())
                    else:
                        self.handler("myform")(ckit.CommandInfo())
                        self.assertEqual(output.getvalue(), "Profile: Alex, 0\n" if accepted else "Canceled\n")
                self.assertEqual(events, [("enable", False), "destroy"] + (
                    [("enable", True), "activate"] if enabled else []))

    def test_documented_job_completion_cancel_and_error(self):
        module = load_example("job_module", "my_job")
        statuses = []
        owner = threading.get_ident()
        self.window.setStatusMessage = lambda *args, **kwargs: statuses.append((args, threading.get_ident()))
        queue = ckit.JobQueue()
        try:
            with patch.object(ckit.JobQueue, "defaultQueue", return_value=queue), patch.dict(sys.modules, my_job=module):
                load_example("job_setup").configure(self.window)
                for cancel, failed in ((False, False), (True, False), (False, True)):
                    with self.subTest(cancel=cancel, failed=failed):
                        output = io.StringIO()
                        worker_sleep = patch.object(module.time, "sleep", side_effect=ValueError("worker failed"))
                        with contextlib.redirect_stdout(output), (worker_sleep if failed else contextlib.nullcontext()):
                            self.handler("myjob")(ckit.CommandInfo())
                            self.assertIsNotNone(module._active)
                            self.assertEqual(module._active.count, 0)
                            self.handler("myjob")(ckit.CommandInfo())
                            self.assertIn("Already queued", output.getvalue())
                            if cancel:
                                self.handler("mycancel")(ckit.CommandInfo())
                            deadline = time.monotonic() + 3
                            while module._active is not None and time.monotonic() < deadline:
                                queue.check()
                                threading.Event().wait(0.001)
                            self.assertIsNone(module._active, "Documented job failed to finish")
                        if cancel:
                            self.assertIn("Canceled", output.getvalue())
                        elif failed:
                            self.assertIn("Job failed: worker failed", output.getvalue())
                        else:
                            self.assertEqual(statuses, [(("Job: 20",), owner)])
        finally:
            queue.cancel()
            queue.join()
            queue.destroy()

    def test_list_hook_binds_existing_commands(self):
        called = []
        window = SimpleNamespace(keymap=ckit.Keymap(), executeCommand=lambda name, info: called.append(name) or True)
        window.command = ckit.CommandMap(window)
        load_example("list_setup").configure_ListWindow(window)
        window.keymap["C-P"](ckit.CommandInfo())
        window.keymap["C-N"](ckit.CommandInfo())
        self.assertEqual(called, ["CursorUp", "CursorDown"])


if __name__ == "__main__":
    unittest.main()
