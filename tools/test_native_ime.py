"""Check bounded cross-process TextEdit queries; the provider simulates IME state."""
import ctypes as c
import faulthandler
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from ctypes import wintypes as w
from pathlib import Path

from native_test_support import RUN_DIR
from test_native_shell import (
    CALL,
    DESKTOP,
    ROOT,
    H,
    P,
    ShellDouble,
    replace_import,
    user,
)

import pyauto


class Variant(c.Structure):
    _fields_ = [("vt", w.WORD), ("reserved", w.WORD * 3), ("value", c.c_int64 * 2)]


class AutomationDouble(ShellDouble):
    """Only the UIA calls made by the compiled query; all references are counted."""
    def __init__(self, stage="ok", composing=False, focused=False):
        self.stage = stage
        self.keep, self.events, self.errors = [], [], []
        self.refs = dict.fromkeys(("automation", "element", "condition", "focused", "pattern", "range"), 0)
        self.objects = {}
        self.composing = composing
        self.focused = focused
        self.interface("automation", 64, {
            6: (H, (P, c.POINTER(P)), lambda this, hwnd, out: self.output("element", out)),
            23: (H, (c.c_int, Variant, c.POINTER(P)), self.condition),
            61: (H, (w.DWORD,), lambda this, value: self.timeout("connection", value)),
            63: (H, (w.DWORD,), lambda this, value: self.timeout("transaction", value)),
        })
        self.interface("element", 85, {
            5: (H, (c.c_int, P, c.POINTER(P)), self.find),
            14: (H, (c.c_int, P, c.POINTER(P)), self.pattern),
        })
        self.interface("condition", 3, {})
        self.interface("focused", 85, {14: (H, (c.c_int, P, c.POINTER(P)), self.pattern)})
        self.interface("pattern", 11, {9: (H, (c.POINTER(P),), self.composition)})
        self.interface("range", 6, {
            5: (H, (c.c_int, P, c.c_int, c.POINTER(c.c_int)), self.compare_endpoints),
        })

    def compare_endpoints(self, this, start, target, end, out):
        self.events.append(("endpoints", start, end, this == target))
        out[0] = 0 if self.stage == "empty" else -1
        if self.stage == "compare":
            return -2147024891
        if self.stage == "compare_notimpl":
            return -2147467263
        return 1 if self.stage == "compare_incomplete" else 0

    def condition(self, this, identifier, value, out):
        self.events.append(("condition", identifier, value.vt, value.value[0]))
        return self.output("condition", out)

    def find(self, this, scope, condition, out):
        self.events.append(("scope", scope))
        out[0] = None
        if self.stage == "find":
            return -2147024891
        return self.output("focused", out) if self.focused else 0

    def timeout(self, name, value):
        self.events.append((name, value))
        return -2147467259 if self.stage == name else 0

    def pattern(self, this, identifier, iid, out):
        self.events.append(("pattern_id", identifier))
        self.events.append(("pattern_target", this))
        if self.stage == "unsupported":
            out[0] = None
            return -2147220988  # UIA_E_NOTSUPPORTED
        return self.output("pattern", out)

    def composition(self, this, out):
        out[0] = None
        if self.stage == "composition":
            return -2147024891  # E_ACCESSDENIED
        if self.stage == "timeout":
            return -2146233083  # UIA_E_TIMEOUT
        if self.stage == "notimpl":
            return -2147467263  # E_NOTIMPL
        if self.stage == "incomplete":
            return 1  # S_FALSE is not a successful GetActiveComposition result.
        if self.composing:
            return self.output("range", out)
        return 0


class NativeImeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="recraft-ime-")
        cls.addClassCleanup(cls.temp.cleanup)
        vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
        install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-version",
            "[18.0,19.0)", "-property", "installationPath"], text=True).strip()
        vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
        cls.exe = Path(cls.temp.name) / "provider.exe"
        source = ROOT / "tools/native_ime_provider.cpp"
        command = (f'""{vcvars}" >nul && cl /nologo /EHsc /std:c++17 /utf-8 "{source}" '
                   f'/Fe:"{cls.exe}" /Fo:"{Path(cls.temp.name) / "provider.obj"}" '
                   '/link user32.lib ole32.lib oleaut32.lib uiautomationcore.lib"')
        built = subprocess.run(f'"{os.environ["COMSPEC"]}" /d /s /c {command}', check=False, timeout=30,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if built.returncode:
            raise RuntimeError(built.stdout)
        user.GetUserObjectInformationW.argtypes = (P, c.c_int, P, w.DWORD, P)
        name, size = c.create_unicode_buffer(256), w.DWORD()
        if not user.GetUserObjectInformationW(DESKTOP[1], 2, name, c.sizeof(name), c.byref(size)):
            raise c.WinError(c.get_last_error())
        cls.desktop = name.value + "\\StandardCommandTests"
        user.SendMessageW.argtypes = (P, w.UINT, w.WPARAM, w.LPARAM)
        user.SendMessageW.restype = c.c_ssize_t

    def setUp(self):
        startup = subprocess.STARTUPINFO()
        startup.lpDesktop = self.desktop
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        self.child = subprocess.Popen([str(self.exe)], startupinfo=startup, stdout=subprocess.PIPE)
        self.addCleanup(self.stop_child)
        # A startup watchdog also bounds readline if the fixture cannot create its HWNDs.
        self.parent, self.edit = map(int, self.child.stdout.readline().split())
        self.target = pyauto.Window.fromHWND(self.edit)

    def stop_child(self):
        if self.child.poll() is None:
            user.PostMessageW(self.parent, 0x10, 0, 0)
            try:
                self.child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=5)
        self.child.stdout.close()

    def mode(self, value):
        self.assertEqual(user.SendMessageW(self.edit, 0x8000, value, 0), 1)

    def test_cross_process_states_and_exact_target(self):
        self.assertIs(self.target.isImeConverting(5000), False)
        self.assertIsNone(pyauto.Window.fromHWND(self.parent).isImeConverting(5000))
        for mode, expected in ((0, False), (1, True), (0, False), (1, True), (0, False),
                               (2, None), (5, None)):
            self.mode(mode)
            self.assertIs(self.target.isImeConverting(5000), expected)
        self.mode(3)
        with self.assertRaises(OSError) as error:
            self.target.isImeConverting()
        self.assertEqual(error.exception.winerror, -2147024891)
        self.mode(0)
        self.assertIs(self.target.isImeConverting(), False)

    def test_deadline_and_recovery(self):
        self.assertIs(self.target.isImeConverting(5000), False)
        self.mode(4)
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.target.isImeConverting(100)
        self.assertLess(time.monotonic() - start, 0.8)
        self.assertGreater(user.SendMessageW(self.edit, 0x8001, 0, 0), 0)
        # The outstanding worker must not allow another background query to accumulate.
        try:
            self.target.isImeConverting(100)
        except OSError as error:
            self.assertIn(getattr(error, "winerror", None), (170, None))
        self.mode(0)
        deadline = time.monotonic() + 5
        while True:
            try:
                self.assertIs(self.target.isImeConverting(), False)
                break
            except OSError as error:
                if (not isinstance(error, TimeoutError) and getattr(error, "winerror", None) != 170
                        or time.monotonic() >= deadline):
                    raise
                time.sleep(0.02)

    def test_cross_process_windowless_focus_within_target(self):
        # The parent HWND and its virtual edit both report focus, as in normal Edge.
        parent = pyauto.Window.fromHWND(self.parent)
        for mode, expected in ((6, True), (7, False), (10, False), (6, True), (8, None)):
            self.mode(mode)
            self.assertIs(self.target.isImeConverting(5000), expected)
            self.assertIs(parent.isImeConverting(5000), expected)
        self.mode(9)
        for target in (self.target, parent):
            with self.assertRaises(OSError) as error:
                target.isImeConverting(5000)
            self.assertEqual(error.exception.winerror, -2147024891)
        self.mode(0)
        self.assertIs(self.target.isImeConverting(5000), False)
        self.assertIsNone(parent.isImeConverting(5000))

    def test_focus_in_another_window_is_not_selected(self):
        startup = subprocess.STARTUPINFO()
        startup.lpDesktop = self.desktop
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        with subprocess.Popen([str(self.exe)], startupinfo=startup, stdout=subprocess.PIPE) as other:
            other_parent, other_edit = map(int, other.stdout.readline().split())
            try:
                self.assertEqual(user.SendMessageW(other_edit, 0x8000, 6, 0), 1)
                self.assertIs(pyauto.Window.fromHWND(other_parent).isImeConverting(5000), True)
                self.assertIs(self.target.isImeConverting(5000), False)
                self.assertIsNone(pyauto.Window.fromHWND(self.parent).isImeConverting(5000))
            finally:
                user.PostMessageW(other_parent, 0x10, 0, 0)
                try:
                    other.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    other.kill()
                    other.wait(timeout=5)

    def test_unresponsive_window_and_destroyed_target(self):
        user.PostMessageW(self.edit, 0x8002, 0, 0)
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.target.isImeConverting(100)
        self.assertLess(time.monotonic() - start, 0.8)
        self.stop_child()
        with self.assertRaises(OSError) as error:
            self.target.isImeConverting()
        self.assertEqual(error.exception.winerror, 1400)

    def test_arguments_and_same_process(self):
        for timeout in (0, -1, 60001):
            with self.assertRaises(ValueError):
                self.target.isImeConverting(timeout)
        for args in ((None,), ("100",), (100, 1)):
            with self.assertRaises(TypeError):
                self.target.isImeConverting(*args)
        own = user.CreateWindowExW(0, "STATIC", "own", 0, 0, 0, 10, 10, None, None, None, None)
        self.assertTrue(own)
        try:
            with self.assertRaisesRegex(ValueError, "another process"):
                pyauto.Window.fromHWND(own).isImeConverting()
        finally:
            user.DestroyWindow(own)

    def test_compiled_com_failure_cleanup(self):
        for stage in ("ok", "automation", "automation_null", "connection", "transaction",
                      "element", "element_null", "condition", "condition_null", "find",
                      "pattern", "pattern_null", "unsupported", "composition",
                      "timeout", "notimpl", "notregistered", "incomplete"):
            for composing in (False, True):
                double = AutomationDouble(stage, composing)
                initialized, uninitialized = [], []
                def initialize(reserved, flags, initialized=initialized):
                    initialized.append(flags)
                    return 1  # S_FALSE still requires CoUninitialize.
                def create(clsid, outer, context, iid, out, double=double, stage=stage):
                    if stage == "notregistered":
                        out[0] = None
                        return -2147221164  # REGDB_E_CLASSNOTREG
                    return double.output("automation", out)
                with self.subTest(stage=stage, composing=composing), ExitStack() as stack:
                    for name, callback in (
                        ("CoInitializeEx", CALL(H, P, w.DWORD)(initialize)),
                        ("CoUninitialize", CALL(None)(lambda uninitialized=uninitialized: uninitialized.append(True))),
                        ("CoCreateInstance", CALL(H, P, P, w.DWORD, P, c.POINTER(P))(create)),
                    ):
                        stack.enter_context(replace_import(name, callback, module=pyauto.pyautocore))
                    if stage == "ok":
                        self.assertIs(self.target.isImeConverting(500), composing)
                    elif stage in ("pattern_null", "unsupported", "notimpl", "notregistered"):
                        self.assertIsNone(self.target.isImeConverting(500))
                    elif stage == "timeout":
                        with self.assertRaises(TimeoutError):
                            self.target.isImeConverting(500)
                    else:
                        with self.assertRaises(OSError):
                            self.target.isImeConverting(500)
                self.assertEqual(initialized, [0])  # COINIT_MULTITHREADED
                self.assertEqual(uninitialized, [True])
                self.assertEqual(set(double.refs.values()), {0})
                if stage == "ok":
                    self.assertIn(("connection", 500), double.events)
                    self.assertIn(("transaction", 500), double.events)
                    self.assertIn(("pattern_id", 10032), double.events)
                    self.assertIn(("condition", 30008, 11, 65535), double.events)
                    self.assertIn(("scope", 4), double.events)

    def test_focused_element_is_selected_and_errors_do_not_fall_back(self):
        for stage in ("ok", "unsupported", "composition"):
            double = AutomationDouble(stage, composing=True, focused=True)
            with self.subTest(stage=stage), replace_import("CoCreateInstance",
                    CALL(H, P, P, w.DWORD, P, c.POINTER(P))(
                        lambda clsid, outer, context, iid, out, double=double: double.output("automation", out)),
                    module=pyauto.pyautocore):
                if stage == "ok":
                    self.assertIs(self.target.isImeConverting(), True)
                elif stage == "unsupported":
                    self.assertIsNone(self.target.isImeConverting())
                else:
                    with self.assertRaises(OSError):
                        self.target.isImeConverting()
            self.assertEqual(set(double.refs.values()), {0})
            self.assertIn(("pattern_target", double.objects["focused"]), double.events)

    def test_empty_composition_and_endpoint_failures(self):
        for stage, expected in (("empty", False), ("ok", True), ("compare", OSError),
                                ("compare_notimpl", None), ("compare_incomplete", OSError)):
            double = AutomationDouble(stage, composing=True)
            with self.subTest(stage=stage), replace_import("CoCreateInstance",
                    CALL(H, P, P, w.DWORD, P, c.POINTER(P))(
                        lambda clsid, outer, context, iid, out, double=double: double.output("automation", out)),
                    module=pyauto.pyautocore):
                if expected is OSError:
                    with self.assertRaises(OSError):
                        self.target.isImeConverting()
                else:
                    self.assertIs(self.target.isImeConverting(), expected)
            self.assertEqual(set(double.refs.values()), {0})
            self.assertIn(("endpoints", 0, 1, True), double.events)

    def test_pending_query_is_bounded_and_released(self):
        started, release = threading.Event(), threading.Event()
        double = AutomationDouble()
        def create(clsid, outer, context, iid, out):
            started.set()
            if not release.wait(5):
                return -2147467259
            return double.output("automation", out)
        with replace_import("CoCreateInstance", CALL(H, P, P, w.DWORD, P, c.POINTER(P))(create),
                            module=pyauto.pyautocore):
            try:
                with self.assertRaises(TimeoutError):
                    self.target.isImeConverting(100)
                self.assertTrue(started.is_set())
                for _ in range(3):
                    with self.assertRaises(OSError) as error:
                        self.target.isImeConverting(100)
                    self.assertEqual(error.exception.winerror, 170)
            finally:
                release.set()
            deadline = time.monotonic() + 5
            while True:
                try:
                    self.assertIs(self.target.isImeConverting(), False)
                    break
                except OSError as error:
                    if getattr(error, "winerror", None) != 170 or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
        self.assertEqual(set(double.refs.values()), {0})

    def test_initialization_and_thread_creation_failures(self):
        uninitialized = []
        with ExitStack() as stack:
            stack.enter_context(replace_import("CoInitializeEx", CALL(H, P, w.DWORD)(
                lambda reserved, flags: -2147467259), module=pyauto.pyautocore))
            stack.enter_context(replace_import("CoUninitialize", CALL(None)(
                lambda: uninitialized.append(True)), module=pyauto.pyautocore))
            with self.assertRaises(OSError):
                self.target.isImeConverting()
        self.assertEqual(uninitialized, [])
        kernel = c.WinDLL("kernel32")
        for name, prototype in (
            ("CreateEventW", CALL(P, P, w.BOOL, w.BOOL, P)),
            ("CreateThread", CALL(P, P, c.c_size_t, P, P, w.DWORD, P)),
        ):
            def fail(*args):
                kernel.SetLastError(5)
            with self.subTest(name=name), replace_import(name, prototype(fail), module=pyauto.pyautocore):
                with self.assertRaises(OSError) as error:
                    self.target.isImeConverting()
                self.assertEqual(error.exception.winerror, 5)
            self.assertIs(self.target.isImeConverting(5000), False)

    def test_existing_open_status_is_independent(self):
        for opened in (0, 1):
            requests = []
            def send(hwnd, message, wp, lp, opened=opened, requests=requests):
                requests.append((hwnd, message, wp, lp))
                return opened
            with ExitStack() as stack:
                stack.enter_context(replace_import("ImmGetDefaultIMEWnd", CALL(P, P)(
                    lambda hwnd: self.parent), module=pyauto.pyautocore))
                stack.enter_context(replace_import("SendMessageW", CALL(c.c_ssize_t, P, w.UINT, w.WPARAM, w.LPARAM)(
                    send), module=pyauto.pyautocore))
                self.assertIs(self.target.getImeStatus(), bool(opened))
                self.assertIs(self.target.isImeConverting(5000), False)
            self.assertEqual(requests, [(self.parent, 0x283, 5, 0)])

    def test_observer_loads_selected_binary_without_input(self):
        startup = subprocess.STARTUPINFO()
        startup.lpDesktop = self.desktop
        startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_ime_composition.py"),
            "--package", str(RUN_DIR), "--seconds", "1"], startupinfo=startup,
            check=True, timeout=10, capture_output=True, text=True)
        self.assertIn(str(RUN_DIR / "lib/pyautocore.pyd"), result.stdout)
        self.assertRegex(result.stdout, r"Native SHA256: [0-9a-f]{64}")
        self.assertRegex(result.stdout, r"HWND=0x0: (?:No focus|PermissionError:.*WinError 5)")
        self.mode(6)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_ime_composition.py"),
            "--package", str(RUN_DIR), "--seconds", "1", "--hwnd", hex(self.parent)],
            startupinfo=startup, check=True, timeout=10, capture_output=True, text=True)
        self.assertIn(f"HWND={self.parent:#x}: True", result.stdout)
        self.assertIn("process=provider.exe class=ReCraftImeTest", result.stdout)
        result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/check_ime_composition.py"),
            "--package", str(RUN_DIR), "--hwnd", "0"], startupinfo=startup,
            check=False, timeout=10, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--hwnd must be positive", result.stderr)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(45, exit=True)
    unittest.main(verbosity=2)
