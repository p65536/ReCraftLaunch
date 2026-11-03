"""Application identity checks with window enumeration and IPC replaced; run with Python -B."""
import ast
import configparser
import contextlib
import ctypes
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "clnch"))
import clnch_execonfig
import clnch_inisettings as ini_settings
import clnch_inputconfig
import clnch_resource


def source_tree(name):
    return ast.parse((ROOT / "clnch" / name).read_text(encoding="utf-8-sig"))


def execute(nodes, namespace):
    import clnch_strings
    namespace["strings"] = clnch_strings
    namespace["json"] = json
    namespace["ini_settings"] = ini_settings
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app-identity-test", "exec"), namespace)  # noqa: S102  # Execute isolated source under test.


def window(class_name, title, hwnd=1, previous=None):
    return SimpleNamespace(getClassName=lambda: class_name, getText=lambda: title,
                           getHWND=lambda: hwnd, getPrevious=lambda: previous,
                           isVisible=lambda: True, getProcessName=lambda: "launcher.exe")


class AppIdentityTests(unittest.TestCase):
    def test_existing_instance_and_ipc_are_isolated(self):
        old = window("ClnchWindowClass", "CraftLaunch MainWindow")
        wrong_class = window("ClnchWindowClass", "ReCraftLaunch MainWindow")
        wrong_title = window("ReClnchWindowClass", "CraftLaunch MainWindow")
        child = window("ReClnchWindowClass", "ReCraftLaunch")
        current = window("ReClnchWindowClass", "ReCraftLaunch MainWindow", hwnd=42)
        for filename in ("clnch_main.py", "clnch_misc.py"):
            for candidates, expected in (([old, wrong_class, wrong_title, child], None),
                                         ([old, wrong_class, wrong_title, child, current], current)):
                with self.subTest(filename=filename, found=expected is not None):
                    def enum(callback, arg):
                        for candidate in candidates:  # noqa: B023  # Used within this test iteration.
                            if not callback(candidate, arg):
                                break
                    sent = []
                    namespace = {
                        "clnch_resource": clnch_resource, "sys": sys,
                        "ctypes": SimpleNamespace(
                            c_ulong=ctypes.c_ulong, c_void_p=ctypes.c_void_p,
                            byref=ctypes.byref, windll=SimpleNamespace(user32=Mock())),
                        "pyauto": SimpleNamespace(Window=SimpleNamespace(enum=enum)),
                        "ckit": SimpleNamespace(TextWindow=SimpleNamespace(
                            sendIpc=lambda hwnd, data: sent.append((hwnd, data)))),  # noqa: B023  # Used within this test iteration.
                        "ipc_data": SimpleNamespace(getValue=lambda: "request"),
                    }
                    tree = source_tree(filename)
                    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                                 and node.name in ("findExistingClnchWindow", "sendIpc")]
                    execute(functions, namespace)
                    self.assertIs(namespace["findExistingClnchWindow"](), expected)
                    if filename == "clnch_main.py":
                        start = next(i for i, node in enumerate(tree.body)
                                     if isinstance(node, ast.Assign)
                                     and isinstance(node.targets[0], ast.Name)
                                     and node.targets[0].id == "existing_clnch_wnd")
                        with contextlib.redirect_stdout(io.StringIO()):
                            if expected is None:
                                execute(tree.body[start:start + 2], namespace)
                            else:
                                with self.assertRaises(SystemExit) as exit_result:
                                    execute(tree.body[start:start + 2], namespace)
                                self.assertEqual(exit_result.exception.code, 0)
                        self.assertEqual(sent, [] if expected is None else [(42, "request")])

    def test_registration_and_about(self):
        prefixes = []
        namespace = {"clnch_resource": clnch_resource,
                     "ckit": SimpleNamespace(registerWindowClass=prefixes.append)}
        call = next(node for node in source_tree("clnch_main.py").body
                    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "registerWindowClass")
        execute([call], namespace)
        self.assertEqual(prefixes, ["ReClnch"])
        self.assertEqual(prefixes[0] + "WindowClass", clnch_resource.clnch_window_class)
        self.assertIn(f"ReCraftLaunch version {clnch_resource.clnch_version}", clnch_resource.startupString())
        self.assertIn("CraftLaunch 3.40", clnch_resource.startupString())
        about = clnch_resource.startupString()
        for url in ("https://github.com/p65536/ReCraftLaunch",
                    "https://github.com/p65536/ReCraftLaunch/releases",
                    "https://github.com/crftwr/clnch",
                    "https://sites.google.com/site/craftware/"):
            self.assertIn(url + "\n", about)
        self.assertIn("craftware", about)
        method = next(node for node in source_tree("clnch_mainwindow.py").body
                      if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        execute([node for node in method.body if isinstance(node, ast.FunctionDef)
                 and node.name == "command_About"], namespace)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            namespace["command_About"](None, None)
        self.assertEqual(output.getvalue(), about + "\n")

    def test_ini_paths_keep_old_settings(self):
        misc_namespace = {}
        execute([node for node in source_tree("clnch_misc.py").body
                 if isinstance(node, ast.FunctionDef) and node.name == "_require_data_path"], misc_namespace)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe_dir = root / "run"
            exe_dir.mkdir()
            old_dir = root / "CraftLaunch"
            old_dir.mkdir()
            old_ini = old_dir / "clnch.ini"
            old_ini.write_bytes(b"[OLD]\r\nvalue=keep\r\n")
            (exe_dir / "clnch.ini").write_bytes(old_ini.read_bytes())
            root_settings = {exe_dir / name: ("root-" + name).encode("utf-8")
                             for name in ("reclnch.ini", "commands.json", "custom.py")}
            for path, data in root_settings.items():
                path.write_bytes(data)
            for mode in ("default", "portable", "appdata", "development"):
                with self.subTest(mode=mode):
                    locator = exe_dir / "reclnch_exe.ini"
                    if mode == "default":
                        if locator.exists():
                            locator.unlink()
                    else:
                        clnch_execonfig.write(str(exe_dir), mode == "appdata")
                    original_locator = locator.read_bytes() if locator.exists() else None
                    state = {}
                    original_paths = sys.path[:]
                    fake_sys = SimpleNamespace(executable=str(exe_dir / "reclnch.exe"), path=original_paths[:])
                    if mode == "development":
                        fake_sys._clnch_app_dir = str(ROOT)
                    ckit = SimpleNamespace(
                        getAppExePath=lambda: str(ROOT), getAppDataPath=lambda: directory,
                        setDataPath=lambda path: state.update(path=path), dataPath=lambda: state["path"])  # noqa: B023  # Used within this test iteration.
                    namespace = {"os": os, "sys": fake_sys, "ckit": ckit,
                                 "clnch_misc": SimpleNamespace(_require_data_path=misc_namespace["_require_data_path"]),
                                 "clnch_resource": clnch_resource, "clnch_ini": SimpleNamespace(),
                                 "clnch_execonfig": clnch_execonfig}
                    tree = source_tree("clnch_main.py")
                    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                                 and isinstance(node.targets[0], ast.Name)
                                 and node.targets[0].id == "app_dir")
                    end = next(i for i, node in enumerate(tree.body[start:], start)
                               if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                               and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "read")
                    execute(tree.body[start:end], namespace)
                    expected = (root / "ReCraftLaunch" if mode == "appdata" else exe_dir / "settings") / "reclnch.ini"
                    self.assertEqual(Path(namespace["clnch_ini"].ini_filename), expected)
                    self.assertTrue(expected.parent.is_dir())
                    self.assertTrue((expected.parent / "scripts").is_dir())
                    self.assertEqual(fake_sys.path, [*original_paths, str(ROOT / "extensions"),
                                                    str(expected.parent / "scripts")])
                    script = expected.parent / "scripts" / "keep.py"
                    script.write_bytes(b"# keep\r\n")
                    execute(tree.body[start:end], namespace)
                    self.assertEqual(fake_sys.path.count(str(expected.parent / "scripts")), 1)
                    self.assertEqual(fake_sys.path.count(str(ROOT / "extensions")), 1)
                    self.assertEqual(script.read_bytes(), b"# keep\r\n")
                    personal = expected.parent / "scripts" / "rc_test_selected.py"
                    personal.write_text("def configure(window):\n    window.source = __file__\n", encoding="utf-8")
                    custom = expected.parent / "custom.py"
                    custom.write_text("def configure(window):\n"
                                      "    import stamp, rc_test_selected\n"
                                      "    rc_test_selected.configure(window)\n", encoding="utf-8")
                    with patch.object(sys, "path", fake_sys.path), patch.dict(sys.modules):
                        local = clnch_inputconfig.load(str(custom))
                        target = SimpleNamespace()
                        local.configure(target)
                        self.assertEqual(Path(target.source), personal)
                    custom.unlink()
                    for path, data in root_settings.items():
                        self.assertEqual(path.read_bytes(), data)
                        self.assertFalse((expected.parent / path.name).exists())
                    self.assertTrue(locator.is_file())
                    self.assertEqual(clnch_execonfig.read(str(exe_dir)), mode == "appdata")
                    if original_locator is not None:
                        self.assertEqual(locator.read_bytes(), original_locator)
                    else:
                        self.assertIn(b"multi_user = 0", locator.read_bytes())
                    self.assertEqual(old_ini.read_bytes(), b"[OLD]\r\nvalue=keep\r\n")
                    self.assertEqual((exe_dir / "clnch.ini").read_bytes(), old_ini.read_bytes())

    def test_storage_initialization_error_is_shown_and_reraised(self):
        tree = source_tree("clnch_main.py")
        block = next(node for node in tree.body if isinstance(node, ast.Try)
                     and any(isinstance(item, ast.Assign) and item.targets[0].id == "multi_user"
                             for item in node.body if isinstance(item, ast.Assign)))
        message_box = Mock()
        namespace = {"os": os, "app_dir": "unused",
                     "ctypes": SimpleNamespace(windll=SimpleNamespace(user32=SimpleNamespace(MessageBoxW=message_box))),
                     "clnch_resource": clnch_resource,
                     "clnch_execonfig": SimpleNamespace(write=Mock(), read=Mock(side_effect=ValueError("bad value")))}
        with patch.object(os.path, "exists", return_value=True), self.assertRaisesRegex(ValueError, "bad value"):
            execute([block], namespace)
        message_box.assert_called_once_with(None, "bad value", clnch_resource.clnch_appname, 0x10)

    def test_topmost_ignores_own_windows(self):
        main = next(node for node in source_tree("clnch_mainwindow.py").body
                    if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        method = next(node for node in main.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_onTimerTopmost")
        for class_name, expected in (("ReClnchWindowClass", []), ("SysShadow", []),
                                     ("ClnchWindowClass", [True]), ("OtherWindow", [True])):
            with self.subTest(class_name=class_name):
                previous = window(class_name, "console")
                topmost = []
                namespace = {"clnch_resource": clnch_resource, "pyauto": SimpleNamespace(
                    Window=SimpleNamespace(fromHWND=lambda hwnd: window("self", "", previous=previous)))}  # noqa: B023  # Used within this test iteration.
                execute([method], namespace)
                namespace["_onTimerTopmost"](SimpleNamespace(getHWND=lambda: 42, topmost=topmost.append))
                self.assertEqual(topmost, expected)

    def make_ipc_data(self):
        namespace = {"ast": ast, "configparser": configparser, "io": io, "math": math,
                     "pyauto": SimpleNamespace()}
        node = next(node for node in source_tree("clnch_ipc.py").body
                    if isinstance(node, ast.ClassDef) and node.name == "IpcData")
        execute([node], namespace)
        return namespace["IpcData"](), namespace

    def test_empty_ipc_uses_configured_activation_or_toggle(self):
        data, _namespace = self.make_ipc_data()
        payload = data.getValue()
        self.assertEqual(payload, "")
        main_class = next(node for node in source_tree("clnch_mainwindow.py").body
                          if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        methods = [node for node in main_class.body if isinstance(node, ast.FunctionDef)
                   and node.name in ("_onIpc", "hotkey_Activate")]
        for behavior in ("activate", "toggle"):
            for active in (False, True):
                with self.subTest(behavior=behavior, active=active):
                    parser = Mock()
                    namespace = {"clnch_ini": SimpleNamespace(get=Mock(return_value=behavior)),
                                 "clnch_ipc": SimpleNamespace(IpcData=parser)}
                    execute(methods, namespace)
                    main = SimpleNamespace(active=active, isEnabled=lambda: True,
                                           inactivate=Mock(), restore=Mock(),
                                           foreground=Mock(), activate=Mock())
                    main.hotkey_Activate = lambda target=main, env=namespace: env["hotkey_Activate"](target)
                    namespace["_onIpc"](main, payload)
                    if behavior == "toggle" and active:
                        main.inactivate.assert_called_once_with()
                        main.restore.assert_not_called()
                        main.foreground.assert_not_called()
                        main.activate.assert_not_called()
                    else:
                        main.inactivate.assert_not_called()
                        main.restore.assert_called_once_with()
                        main.foreground.assert_called_once_with()
                        main.activate.assert_called_once_with()
                    parser.assert_not_called()

    def test_nonempty_ipc_keeps_execution_and_input_order(self):
        main_class = next(node for node in source_tree("clnch_mainwindow.py").body
                          if isinstance(node, ast.ClassDef) and node.name == "MainWindow")
        method = next(node for node in main_class.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_onIpc")
        for option, value in (("--execute", "About"), ("--text", "ipc-check"),
                              ("--selection", "A"), ("--position", "(50,25)")):
            with self.subTest(option=option):
                data, _namespace = self.make_ipc_data()
                data.trySetOption(option, value)
                payload = data.getValue()
                self.assertTrue(payload)
                ipc = Mock()
                namespace = {"clnch_ipc": ipc}
                execute([method], namespace)
                main = SimpleNamespace(quit_requested=False, hotkey_Activate=Mock())
                namespace["_onIpc"](main, payload)
                self.assertEqual(ipc.mock_calls, [call.IpcData(payload),
                                                  call.IpcData().execute(main),
                                                  call.IpcData().commandLine(main)])
                main.hotkey_Activate.assert_not_called()

    def test_ipc_sender_allows_only_receiver_before_synchronous_send(self):
        function = next(node for node in source_tree("clnch_main.py").body
                        if isinstance(node, ast.FunctionDef) and node.name == "sendIpc")
        for allowed in (0, 1):
            with self.subTest(allowed=allowed):
                events = []
                hwnd = 0x123456789
                def process_id(handle, result, target=hwnd, event_log=events):
                    self.assertEqual(handle.value, target)
                    result._obj.value = 1234
                    event_log.append("pid")
                    return 42
                def allow(pid, event_log=events, result=allowed):
                    event_log.append(("allow", pid.value))
                    return result
                api = SimpleNamespace(GetWindowThreadProcessId=process_id,
                                      AllowSetForegroundWindow=allow)
                namespace = {
                    "clnch_resource": clnch_resource,
                    "ctypes": SimpleNamespace(c_ulong=ctypes.c_ulong,
                                              c_void_p=ctypes.c_void_p,
                                              byref=ctypes.byref,
                                              windll=SimpleNamespace(user32=api)),
                    "ckit": SimpleNamespace(TextWindow=SimpleNamespace(
                        sendIpc=lambda target, data, event_log=events: event_log.append(("send", target, data)))),
                    "ipc_data": SimpleNamespace(getValue=lambda: "request"),
                }
                execute([function], namespace)
                with contextlib.redirect_stdout(io.StringIO()):
                    namespace["sendIpc"](SimpleNamespace(getHWND=lambda target=hwnd: target))
                self.assertEqual(events, ["pid", ("allow", 1234), ("send", hwnd, "request")])

    def test_ipc_text_uses_normal_activation_and_keeps_selection(self):
        for selection, expected in ((None, [9, 9]), ("A", [0, 9]), ("0", [0, 0])):
            with self.subTest(selection=selection):
                data, namespace = self.make_ipc_data()
                data.trySetOption("--text", "ipc-check")
                namespace["pyauto"].Window = Mock()
                if selection is not None:
                    data.trySetOption("--selection", selection)
                events = []
                main = SimpleNamespace(
                    isEnabled=lambda: True, getHWND=lambda: 42,
                    restore=lambda event_log=events: event_log.append("restore"),
                    foreground=lambda event_log=events: event_log.append("foreground"),
                    activate=lambda event_log=events: event_log.append("activate"),
                    activeMessageLoop=lambda event_log=events, **args: event_log.append(("loop", args)),
                    resetPos=lambda event_log=events: event_log.append("reset"),
                )
                data.commandLine(main)
                self.assertEqual(namespace["pyauto"].Window.mock_calls, [])
                self.assertEqual(events, ["restore", "foreground", "activate",
                                         ("loop", {"text": "ipc-check", "selection": expected}),
                                         "reset"])

    def test_ipc_modal_and_empty_requests_do_not_start_input(self):
        for text, enabled, expected in ((None, True, []),
                                        ("ipc-check", False, ["foreground"])):
            with self.subTest(text=text, enabled=enabled):
                data, _namespace = self.make_ipc_data()
                if text is not None:
                    data.trySetOption("--text", text)
                events = []
                main = SimpleNamespace(isEnabled=lambda state=enabled: state,
                                       foreground=lambda event_log=events: event_log.append("foreground"))
                data.commandLine(main)
                self.assertEqual(events, expected)

    def test_ipc_selection_ranges_after_serialization(self):
        # Expected ranges for 0, 1, 2, 3, 4, 5, A, and the omitted default.
        cases = (
            ("command;arg", ([0, 0], [0, 7], [7, 7], [8, 8], [8, 11], [11, 11], [0, 11], [11, 11])),
            ("command", ([0, 0], [0, 7], [7, 7], [7, 7], [7, 7], [7, 7], [0, 7], [7, 7])),
            ("", ([0, 0],) * 8),
            ("command;", ([0, 0], [0, 7], [7, 7], [8, 8], [8, 8], [8, 8], [0, 8], [8, 8])),
            (";abc", ([0, 0], [0, 0], [0, 0], [1, 1], [1, 4], [4, 4], [0, 4], [4, 4])),
            ("command;arg1;arg2", ([0, 0], [0, 7], [7, 7], [8, 8], [8, 17], [17, 17], [0, 17], [17, 17])),
            ("https://x/a;b;c", ([0, 0], [0, 11], [11, 11], [12, 12], [12, 15], [15, 15], [0, 15], [15, 15])),
            (' 日本語; "a b";  ', ([0, 0], [0, 4], [4, 4], [5, 5], [5, 14], [14, 14], [0, 14], [14, 14])),
        )
        for text, ranges in cases:
            for selection, expected in zip(("0", "1", "2", "3", "4", "5", "A", None), ranges):
                with self.subTest(text=text, selection=selection):
                    data, namespace = self.make_ipc_data()
                    data.trySetOption("--text", text)
                    if selection is not None:
                        data.trySetOption("--selection", selection)
                    received = namespace["IpcData"](data.getValue())
                    main = Mock()
                    main.isEnabled.return_value = True
                    received.commandLine(main)
                    if text or selection is not None:
                        main.activeMessageLoop.assert_called_once_with(text=text, selection=expected)
                        self.assertTrue(0 <= expected[0] <= expected[1] <= len(text))
                    else:
                        main.activeMessageLoop.assert_not_called()

    def test_ipc_unknown_selection_reports_error_and_falls_back(self):
        for selection in ("6", "a", "unknown", ""):
            with self.subTest(selection=selection):
                data, namespace = self.make_ipc_data()
                data.trySetOption("--text", "command;arg")
                data.trySetOption("--selection", selection)
                received = namespace["IpcData"](data.getValue())
                main = Mock()
                main.isEnabled.return_value = True
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    received.commandLine(main)
                self.assertEqual(output.getvalue(),
                                 namespace["strings"].IPC_SELECTION_ERROR.format(selection=selection) + "\n")
                main.activeMessageLoop.assert_called_once_with(text="command;arg", selection=[0, 0])

    def test_ipc_position_keeps_geometry_and_reset_order(self):
        positions = (("(50,25)", 450, 345), ("(0,0)", 100, 200),
                     ("(12.5,-25.5)", 187, 52), ("[-50,125]", -250, 925),
                     ("(-0.0,+25.5)", 100, 347), ("[20.5,40.25]", 243, 433),
                     (" ( +20, -40 ) ", 240, -32))
        for position, x, y in positions:
            for text in (None, "ipc-check"):
                with self.subTest(position=position, text=text):
                    data, namespace = self.make_ipc_data()
                    if text is not None:
                        data.trySetOption("--text", text)
                    data.trySetOption("--position", position)
                    data = namespace["IpcData"](data.getValue())
                    namespace["pyauto"].Window = SimpleNamespace(
                        fromHWND=lambda hwnd: SimpleNamespace(getRect=lambda: (0, 0, 100, 20)),
                        getForeground=lambda: SimpleNamespace(getRect=lambda: (100, 200, 900, 800)),
                    )
                    events = []
                    main = SimpleNamespace(
                        isEnabled=lambda: True, getHWND=lambda: 42, width=lambda: 10, height=lambda: 1,
                        setPosSize=lambda *args, event_log=events: event_log.append(("position", args)),
                        restore=lambda event_log=events: event_log.append("restore"),
                        foreground=lambda event_log=events: event_log.append("foreground"),
                        activate=lambda event_log=events: event_log.append("activate"),
                        activeMessageLoop=lambda event_log=events, **args: event_log.append(("loop", args)),
                        resetPos=lambda event_log=events: event_log.append("reset"),
                    )
                    data.commandLine(main)
                    expected_text = text or ""
                    self.assertEqual(events, [("position", (x, y, 10, 1, 0)),
                                              "restore", "foreground", "activate",
                                              ("loop", {"text": expected_text,
                                                        "selection": [len(expected_text)] * 2}),
                                              "reset"])

    def test_ipc_position_without_foreground_keeps_input_selection_and_reset(self):
        for text, selections in (
            (None, ((None, [0, 0]), ("A", [0, 0]), ("4", [0, 0]))),
            ("command;日本語", ((None, [11, 11]), ("A", [0, 11]), ("4", [8, 11]))),
        ):
            for selection, expected_selection in selections:
                with self.subTest(text=text, selection=selection):
                    data, namespace = self.make_ipc_data()
                    data.trySetOption("--position", "(50,25)")
                    if text is not None:
                        data.trySetOption("--text", text)
                    if selection is not None:
                        data.trySetOption("--selection", selection)
                    data = namespace["IpcData"](data.getValue())
                    namespace["pyauto"].Window = Mock()
                    namespace["pyauto"].Window.getForeground.return_value = None
                    main = Mock()
                    main.isEnabled.return_value = True
                    expected_text = text or ""
                    data.commandLine(main)
                    namespace["pyauto"].Window.getForeground.assert_called_once_with()
                    self.assertEqual(main.mock_calls, [call.isEnabled(), call.getHWND(),
                        call.restore(), call.foreground(), call.activate(),
                        call.activeMessageLoop(text=expected_text, selection=expected_selection),
                        call.resetPos()])

    def test_ipc_position_rejects_invalid_values_without_starting_input(self):
        positions = ("", " ", "(", "(20,)", "()", "[]", "[20,40,60]", "(20,40,60)", "20",
                     "{0:20,1:40}", "{20,40}", "'20,40'", "('20',40)", "(20,b'40')",
                     "(True,40)", "(20,False)", "(None,40)", "((20,),40)", "(20,1+0j)",
                     "(1e309,40)", "(20,-1e309)", "(nan,40)", "(20,NaN)", "(inf,40)",
                     "(float('nan'),40)", "(20,float('inf'))", "(10+10,40)",
                     "[x for x in (20,40)]", "(*[20,40],)")
        for position in positions:
            for text in (None, "ipc-check"):
                for enabled in (False, True):
                    with self.subTest(position=position, text=text, enabled=enabled):
                        data, namespace = self.make_ipc_data()
                        data.trySetOption("--position", position)
                        if text is not None:
                            data.trySetOption("--text", text)
                        data = namespace["IpcData"](data.getValue())
                        namespace["pyauto"].Window = Mock()
                        main = Mock()
                        main.isEnabled.return_value = enabled
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            data.commandLine(main)
                        self.assertEqual(output.getvalue(),
                                         namespace["strings"].IPC_POSITION_ERROR.format(position=position.strip()) + "\n")
                        self.assertEqual(main.mock_calls, [])
                        self.assertEqual(namespace["pyauto"].Window.mock_calls, [])

    def test_ipc_position_does_not_execute_expressions(self):
        for position in ("(attack(),25)", "(50,25) if attack() else (20,40)",
                         "(__import__('os').system('ipc-position-test'),25)"):
            with self.subTest(position=position):
                data, namespace = self.make_ipc_data()
                namespace["attack"] = Mock(return_value=50)
                data.trySetOption("--position", position)
                main = Mock()
                output = io.StringIO()
                with patch("os.system", return_value=50) as system, contextlib.redirect_stdout(output):
                    data.commandLine(main)
                namespace["attack"].assert_not_called()
                system.assert_not_called()
                self.assertEqual(main.mock_calls, [])
                self.assertEqual(output.getvalue(),
                                 namespace["strings"].IPC_POSITION_ERROR.format(position=position) + "\n")


if __name__ == "__main__":
    unittest.main()
