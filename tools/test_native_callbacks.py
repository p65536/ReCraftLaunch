"""Real ckit callback/IPC failures and recovery; isolated desktop by default.

--ordinary-desktop uses hidden test windows on the current desktop, with no
physical input, foreground changes or application settings. --package DIR loads
only the packaged Python modules and PYDs. Faults patch only the test process.
"""
import ctypes as c
import faulthandler
import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import ExitStack, contextmanager, redirect_stderr
from ctypes import wintypes as w
from pathlib import Path
from unittest.mock import patch

import native_test_support
from native_test_support import NATIVE_NAMES, ROOT, RUN_DIR

PACKAGE = None
if "--package" in sys.argv:
    index = sys.argv.index("--package")
    PACKAGE = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
    native_test_support.RUN_DIR = PACKAGE
    sys.path[:0] = [str(PACKAGE / "library.zip"), str(PACKAGE / "lib")]
    # Load these before shared test helpers prepend their source search paths.
    import ckit
    import pyauto
else:
    sys.path[:0] = [str(ROOT), str(RUN_DIR)]

from check_standard_windows import IPC_SENDER

ORDINARY = "--ordinary-desktop" in sys.argv
if ORDINARY:
    sys.argv.remove("--ordinary-desktop")
    # The shared IAT helpers normally create a private station at import time.
    with patch("check_standard_windows.isolated_desktop", return_value=None):
        import test_native_shell as support
else:
    import test_native_shell as support

import ckit
import pyauto
from ckit import ckitcore as native

P, CALL, user = support.P, support.CALL, support.user
user.SendMessageW.argtypes = (P, w.UINT, w.WPARAM, w.LPARAM)
user.SendMessageW.restype = c.c_ssize_t
user.DefWindowProcW.argtypes = user.SendMessageW.argtypes
user.DefWindowProcW.restype = c.c_ssize_t
for name in ("GetMenu", "GetSubMenu"):
    getattr(user, name).argtypes = (P,) if name == "GetMenu" else (P, c.c_int)
    getattr(user, name).restype = P
user.GetMenuItemCount.argtypes = (P,)
user.GetMenuState.argtypes = (P, w.UINT, w.UINT)
user.GetMenuState.restype = w.UINT
user.GetMenuItemID.argtypes = (P, c.c_int)
user.GetMenuItemID.restype = w.UINT
user.GetMenuStringW.argtypes = (P, w.UINT, w.LPWSTR, c.c_int, w.UINT)


class CopyData(c.Structure):
    _fields_ = [("kind", c.c_size_t), ("size", w.DWORD), ("data", P)]


class BadIndex:
    def __index__(self):
        raise ValueError("index sentinel")


class GoodIndex:
    def __index__(self):
        return 2


BAD_RESULTS = (None, "invalid", 1.5, object(), 2**80, -(2**80), BadIndex())


def fail(*args):
    raise RuntimeError("callback sentinel")


def clear_last_exception():
    # PyErr_Print intentionally caches its traceback; it is not a leaked ref.
    for name in ("last_exc", "last_type", "last_value", "last_traceback"):
        if hasattr(sys, name):
            setattr(sys, name, None)


@contextmanager
def memory_error(name, *, integer_result=False, skip=0):
    address = c.cast(c.pythonapi.PyErr_NoMemory, P).value
    code = b"\x48\xb8" + struct.pack("<Q", address) + b"\xff\xe0"
    if integer_result:
        code = (b"\x48\x83\xec\x28\x48\xb8" + struct.pack("<Q", address)
                + b"\xff\xd0\xb8\xff\xff\xff\xff\x48\x83\xc4\x28\xc3")
    remaining = c.c_size_t(skip)
    if skip:
        original = P.from_address(support.imports(native)[name]).value
        code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(remaining))
                + b"\x48\x83\x38\x00\x74\x0f\x48\xff\x08\x48\xb8"
                + struct.pack("<Q", original) + b"\xff\xe0" + code)
    with (support.executable_thunk(code) as thunk,
          support.replace_import(name, thunk, module=native)):
        yield


@contextmanager
def count_native_calls(name):
    # Tail-call the real API without entering Python with a pending exception.
    count = c.c_size_t()
    original = P.from_address(support.imports(native)[name]).value
    code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(count)) + b"\x48\xff\x00"
            + b"\x48\xb8" + struct.pack("<Q", original) + b"\xff\xe0")
    with (support.executable_thunk(code) as thunk,
          support.replace_import(name, thunk, module=native)):
        yield count


class NativeCallbackTests(unittest.TestCase):
    def test_modifier_high_bit_keyboard_and_mouse_events(self):
        received, states = [], {}
        keys = (0x12, 0x11, 0x10, 0x5b, 0x5c)
        keyboard = {0x100: "keydown", 0x104: "keydown", 0x101: "keyup",
                    0x105: "keyup", 0x102: "char", 0x286: "char"}
        mouse = {0x201: "lbuttondown", 0x202: "lbuttonup", 0x203: "lbuttondoubleclick",
                 0x204: "rbuttondown", 0x205: "rbuttonup", 0x206: "rbuttondoubleclick",
                 0x207: "mbuttondown", 0x208: "mbuttonup", 0x209: "mbuttondoubleclick",
                 0x200: "mousemove", 0x20a: "mousewheel"}
        def handler(name):
            return lambda *args: received.append((name, args))
        window = self.window(**{name + "_handler": handler(name)
                                for name in set(keyboard.values()) | set(mouse.values())})
        def state(vk):
            return c.c_short(states.get(vk, 0)).value
        with support.replace_import("GetKeyState", CALL(c.c_short, c.c_int)(state), module=native):
            for value in (0, 1, 0xf0, 0x7fff, 0x8000, 0x8001, 0xffff):
                for subset in range(32):
                    states.update({vk: value if subset & (1 << i) else 0 for i, vk in enumerate(keys)})
                    mod = ((subset & 7) | (8 if subset & 24 else 0)) if value & 0x8000 else 0
                    with self.subTest(value=hex(value), subset=subset):
                        for message, name in keyboard.items():
                            self.send(window, message, 65)
                            self.assertEqual(received.pop(), (name, (65, mod)))
                        for message, name in mouse.items():
                            self.send(window, message, 120 << 16, (11 << 16) | (-7 & 0xffff))
                            args = (-7, 11, 1.0, mod) if name == "mousewheel" else (-7, 11, mod)
                            self.assertEqual(received.pop(), (name, args))

    def drop_data(self, files):
        kernel = support.kernel
        kernel.GlobalAlloc.argtypes = (w.UINT, c.c_size_t)
        kernel.GlobalAlloc.restype = P
        kernel.GlobalLock.argtypes = (P,)
        kernel.GlobalLock.restype = P
        kernel.GlobalUnlock.argtypes = (P,)
        payload = struct.pack("<IiiII", 20, -7, 11, 0, 1)
        payload += ("\0".join(files) + "\0\0").encode("utf-16-le")
        drop = kernel.GlobalAlloc(2, len(payload))
        self.assertTrue(drop)
        pointer = kernel.GlobalLock(drop)
        self.assertTrue(pointer)
        c.memmove(pointer, payload, len(payload))
        kernel.GlobalUnlock(drop)
        return drop

    def test_hotkey_success_failure_references_ids_and_late_messages(self):
        register_type = CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)
        unregister_type = CALL(w.BOOL, P, c.c_int)
        calls, removed, received = [], [], []
        reject = [False]
        def register(hwnd, ident, mod, vk):
            calls.append((ident, mod, vk))
            if reject[0]:
                c.WinDLL("kernel32").SetLastError(1409)
                return 0
            return 1
        def unregister(hwnd, ident):
            removed.append(ident)
            return 1
        window = self.window()
        callback = lambda: received.append(True)
        baseline = sys.getrefcount(callback)
        with (support.replace_import("RegisterHotKey", register_type(register), module=native),
              support.replace_import("UnregisterHotKey", unregister_type(unregister), module=native)):
            for _ in range(100):
                reject[0] = True
                with self.assertRaises(OSError) as error:
                    window.setHotKey(0x78, 2, callback)
                self.assertEqual(error.exception.winerror, 1409)
                self.assertEqual(sys.getrefcount(callback), baseline)
                reject[0] = False
                self.assertIsNone(window.setHotKey(0x78, 2, callback))
                self.assertEqual(sys.getrefcount(callback), baseline + 1)
                self.send(window, 0x312, 0)
                self.assertIsNone(window.killHotKey(callback))
                self.assertEqual(sys.getrefcount(callback), baseline)
                self.send(window, 0x312, 0)
            self.assertEqual(calls, [(0, 2, 0x78)] * 200)
            self.assertEqual(removed, [0] * 100)
            self.assertEqual(received, [True] * 100)

    def test_hotkey_unregister_failure_and_comparison_error_keep_registration(self):
        window = self.window()
        callback = lambda: None
        baseline = sys.getrefcount(callback)
        def fail_unregister(hwnd, ident):
            c.WinDLL("kernel32").SetLastError(5)
            return 0
        class BadEqual:
            def __eq__(self, other):
                raise ValueError("comparison sentinel")
        with (support.replace_import("RegisterHotKey", CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)(lambda *args: 1), module=native),
              support.replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(fail_unregister), module=native)):
            window.setHotKey(0x78, 2, callback)
            with self.assertRaisesRegex(ValueError, "comparison sentinel"):
                window.killHotKey(BadEqual())
            with self.assertRaises(OSError) as error:
                window.killHotKey(callback)
            self.assertEqual(error.exception.winerror, 5)
            self.assertEqual(sys.getrefcount(callback), baseline + 1)
        with support.replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(lambda *args: 1), module=native):
            window.killHotKey(callback)
        self.assertEqual(sys.getrefcount(callback), baseline)

    @unittest.skipUnless(ORDINARY, "Run with --ordinary-desktop on an interactive station")
    def test_hotkey_real_os_conflict_and_recovery(self):
        first, second = self.window(), self.window()
        callback = lambda: None
        first.setHotKey(0x87, 2 | 4, callback)  # Ctrl+Shift+F24 on the private desktop.
        try:
            with self.assertRaises(OSError):
                second.setHotKey(0x87, 2 | 4, callback)
        finally:
            first.killHotKey(callback)
        second.setHotKey(0x87, 2 | 4, callback)
        second.killHotKey(callback)

    def test_hotkey_self_unregister_and_nested_late_message(self):
        window = self.window()
        calls = []
        def callback():
            calls.append(True)
            window.killHotKey(callback)
            self.send(window, 0x312, 0)
        with (support.replace_import("RegisterHotKey", CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)(lambda *args: 1), module=native),
              support.replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(lambda *args: 1), module=native)):
            window.setHotKey(0x78, 2, callback)
            self.send(window, 0x312, 0)
            window.setHotKey(0x78, 2, callback)
            self.send(window, 0x312, 0)
        self.assertEqual(calls, [True, True])

    def test_dropfiles_capacity_lengths_and_real_paths(self):
        shell = c.WinDLL("shell32")
        query_type = CALL(w.UINT, P, w.UINT, P, w.UINT)
        query = query_type(("DragQueryFileW", shell))
        received, calls = [], []
        window = self.window(dropfiles_handler=lambda x, y, paths: received.append((x, y, paths)))

        def observe(drop, index, buffer, capacity):
            calls.append((index, capacity))
            # Bound writes even if a regressed build passes bytes instead of WCHARs.
            required = query(drop, index, None, 0)
            return query(drop, index, buffer, min(capacity, required + 1) if buffer else capacity)

        paths = ["a", "C:\\日本語😀.txt", "長" * 260 + "😀"]
        paths += ["C:\\" + "長" * (n - 3) for n in (260, 261, 262, 263, 600)]
        expected_calls = []
        for files in ([], paths[:1], paths):
            with self.subTest(files=len(files)):
                drop = self.drop_data(files)
                expected_calls.append((0xffffffff, 0))
                # Direct real API checks include the NUL and one untouched guard.
                for index, path in enumerate(files):
                    required = len(path.encode("utf-16-le")) // 2
                    self.assertEqual(query(drop, index, None, 0), required)
                    buffer = c.create_unicode_buffer(required + 2)
                    buffer[required + 1] = "Z"
                    length = query(drop, index, buffer, required + 1)
                    self.assertEqual(length, required)
                    self.assertEqual(buffer.value, path)
                    self.assertEqual(buffer[length], "\0")
                    self.assertEqual(buffer[required + 1], "Z")
                    expected_calls.extend(((index, 0), (index, required + 1)))
                with (support.replace_import("DragQueryFileW", query_type(observe), module=native),
                      count_native_calls("DragFinish") as finished):
                    self.send(window, 0x233, drop)
                self.assertEqual(finished.value, 1)
                self.assertEqual(received[-1], (-7, 11, files))
        self.assertEqual(calls, expected_calls)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / ("長" * 100) / ("名" * 100)
            folder.mkdir(parents=True)
            file = folder / ("日本語😀" * 10 + ".txt")
            file.write_text("drop test", encoding="utf-8")
            self.assertGreater(len(str(file).encode("utf-16-le")) // 2, 260)
            self.send(window, 0x233, self.drop_data([str(file)]))
            self.assertEqual(received[-1], (-7, 11, [str(file)]))
            self.assertTrue(Path(received[-1][2][0]).is_file())

    def test_dropfiles_zero_return_without_buffer_write(self):
        received, calls = [], []
        window = self.window(dropfiles_handler=lambda x, y, paths: received.append(paths))
        shell = c.WinDLL("shell32")
        query_type = CALL(w.UINT, P, w.UINT, P, w.UINT)
        real_query = query_type(("DragQueryFileW", shell))
        length, copied = [0], [0]
        def query(drop, index, buffer, capacity):
            calls.append((index, capacity))
            if index == 0xffffffff:
                return 2
            if index == 0:
                return real_query(drop, index, buffer, capacity)
            return length[0] if not buffer else copied[0]
        # Empty names terminate real HDROP lists; test failed/empty queries separately.
        for invalid, returned in ((0, 0), (0xffffffff, 0), (3, 0), (3, 2), (3, 4)):
            length[0] = invalid
            copied[0] = returned
            calls.clear()
            with (support.replace_import("DragQueryFileW", query_type(query), module=native),
                  count_native_calls("DragFinish") as finished,
                  count_native_calls("PyMem_Free") as freed,
                  redirect_stderr(io.StringIO()) as errors):
                self.send(window, 0x233, self.drop_data(["ok", "bad"]))
            self.assertIn("ValueError", errors.getvalue())
            self.assertEqual(finished.value, 1)
            self.assertEqual(freed.value, 2 if invalid == 3 else 1)
            self.assertEqual(calls, [(0xffffffff, 0), (0, 0), (0, 3), (1, 0)]
                             + ([(1, 4)] if invalid == 3 else []))
            self.assertEqual(received, [])
        self.send(window, 0x233, self.drop_data(["recovered"]))
        self.assertEqual(received, [["recovered"]])

    def test_dropfiles_python_failures_release_and_recover(self):
        received = []
        marker = object()
        def handler(x, y, paths):
            received.append(paths)
            return marker
        window = self.window(dropfiles_handler=handler)
        baseline = sys.getrefcount(marker), sys.getrefcount(handler)
        tracked = []
        item = "tracked path " + uuid.uuid4().hex
        def new_list(size):
            c.pythonapi.Py_IncRef(c.py_object(tracked))
            return id(tracked)
        # Native Py_NewRef also works while a fault is pending on a later item.
        newref = c.cast(c.pythonapi.Py_NewRef, P).value
        item_code = (b"\x48\xb9" + struct.pack("<Q", id(item))
                     + b"\x48\xb8" + struct.pack("<Q", newref) + b"\xff\xe0")
        refs = sys.getrefcount(tracked), sys.getrefcount(item)
        for name, skip in (("PyList_New", 0), ("PyMem_Calloc", 0), ("PyMem_Calloc", 1),
                           ("PyUnicode_FromWideChar", 0), ("PyUnicode_FromWideChar", 1),
                           ("PyList_Append", 0), ("PyList_Append", 1), ("Py_BuildValue", 0)):
            for _ in range(20):
                drop = self.drop_data(["first😀", "second"])
                with self.subTest(api=name, skip=skip), ExitStack() as stack:
                    if name != "PyList_New":
                        stack.enter_context(support.replace_import(
                            "PyList_New", c.PYFUNCTYPE(P, c.c_ssize_t)(new_list), module=native))
                    thunk = stack.enter_context(support.executable_thunk(item_code))
                    stack.enter_context(support.replace_import("PyUnicode_FromWideChar", thunk, module=native))
                    finished = stack.enter_context(count_native_calls("DragFinish"))
                    freed = stack.enter_context(count_native_calls("PyMem_Free"))
                    stack.enter_context(memory_error(name, integer_result=name == "PyList_Append", skip=skip))
                    errors = stack.enter_context(redirect_stderr(io.StringIO()))
                    self.send(window, 0x233, drop)
                self.assertIn("MemoryError", errors.getvalue())
                self.assertEqual(received, [])
                self.assertEqual(finished.value, 1)
                expected_frees = {"PyList_New": 0, "PyMem_Calloc": skip,
                                  "Py_BuildValue": 2}.get(name, skip + 1)
                self.assertEqual(freed.value, expected_frees)
                clear_last_exception()
                self.assertEqual((sys.getrefcount(marker), sys.getrefcount(handler)), baseline)
                tracked.clear()
                self.assertEqual((sys.getrefcount(tracked), sys.getrefcount(item)), refs)
                self.send(window, 0x233, self.drop_data(["recovered😀"]))
                self.assertEqual(received.pop(), ["recovered😀"])
        # No-handler and raising-handler paths must release the owned list/items too.
        for callback in (None, fail):
            other = self.window(**({"dropfiles_handler": callback} if callback else {}))
            tracked = ["tracked😀"]
            def new_list(size, tracked=tracked):
                c.pythonapi.Py_IncRef(c.py_object(tracked))
                return id(tracked)
            refs = sys.getrefcount(tracked)
            with (support.replace_import("PyList_New", c.PYFUNCTYPE(P, c.c_ssize_t)(new_list), module=native),
                  count_native_calls("DragFinish") as finished,
                  redirect_stderr(io.StringIO()) as errors):
                self.send(other, 0x233, self.drop_data([]))
            self.assertEqual(finished.value, 1)
            self.assertEqual(bool(errors.getvalue()), callback is fail)
            clear_last_exception()
            self.assertEqual(sys.getrefcount(tracked), refs)

    def test_class_name_capacity_return_length_and_real_api(self):
        from pyauto import pyautocore
        get_type = CALL(c.c_int, P, P, c.c_int)
        get = get_type(("GetClassNameW", user))
        window = self.window()
        wrapper = pyauto.Window.fromHWND(window.getHWND())
        actual = c.create_unicode_buffer(256)
        length = get(window.getHWND(), actual, 256)
        self.assertGreater(length, 0)
        self.assertEqual(wrapper.getClassName(), actual.value)
        for size in (1, 2, length, length + 1):
            buffer = c.create_unicode_buffer(size + 1)
            buffer[size] = "Z"
            copied = get(window.getHWND(), buffer, size)
            self.assertEqual(copied, min(length, size - 1))
            self.assertEqual(buffer[copied], "\0")
            self.assertEqual(buffer[size], "Z")
        class WindowClass(c.Structure):
            _fields_ = [("style", w.UINT), ("procedure", P), ("class_extra", c.c_int),
                        ("window_extra", c.c_int), ("instance", P), ("icon", P),
                        ("cursor", P), ("background", P), ("menu", w.LPCWSTR),
                        ("name", w.LPCWSTR)]
        user.RegisterClassW.argtypes = (c.POINTER(WindowClass),)
        user.UnregisterClassW.argtypes = (w.LPCWSTR, P)
        name = "長" * 223 + uuid.uuid4().hex
        definition = WindowClass(name=name, procedure=c.cast(user.DefWindowProcW, P))
        self.assertTrue(user.RegisterClassW(c.byref(definition)))
        try:
            long_window = user.CreateWindowExW(0, name, "", 0, 0, 0, 10, 10, None, None, None, None)
            self.assertTrue(long_window)
            try:
                self.assertEqual(pyauto.Window.fromHWND(long_window).getClassName(), name)
            finally:
                user.DestroyWindow(long_window)
        finally:
            self.assertTrue(user.UnregisterClassW(name, None))
        # Exercise long/empty names independent of the OS class-name length limit.
        for text in ("", "名", "名" * 254, "名" * 255, "名" * 256, "名" * 600):
            capacities = []
            def query(hwnd, output, capacity, text=text, capacities=capacities):
                capacities.append(capacity)
                copied = min(len(text), 255, capacity - 1)
                c.memmove(output, (text[:copied] + "\0").encode("utf-16-le"), (copied + 1) * 2)
                return copied
            with support.replace_import("GetClassNameW", get_type(query), module=pyautocore):
                self.assertEqual(wrapper.getClassName(), text[:255])
            self.assertEqual(capacities, [256])
        # A stale, non-NULL HWND gives a real zero return with no valid class name.
        stale = user.CreateWindowExW(0, "STATIC", "", 0, 0, 0, 10, 10, None, None, None, None)
        self.assertTrue(stale)
        stale_wrapper = pyauto.Window.fromHWND(stale)
        self.assertTrue(user.DestroyWindow(stale))
        self.assertEqual(stale_wrapper.getClassName(), "")

    def test_inactivate_class_name_capacity_and_failure(self):
        window = self.window()
        capacities, selected = [], []
        target = window.getHWND()
        real_query = CALL(c.c_int, P, P, c.c_int)(("GetClassNameW", user))
        for text in (None, "", "名", "名" * 255, "名" * 600, "real"):
            def query(hwnd, output, capacity, text=text):
                capacities.append(capacity)
                if text == "real":
                    return real_query(hwnd, output, min(capacity, 256))
                if text is None:
                    return 0  # Deliberately leave the output untouched on failure.
                copied = min(len(text), 255, capacity - 1)
                c.memmove(output, (text[:copied] + "\0").encode("utf-16-le"), (copied + 1) * 2)
                return copied
            with (support.replace_import("GetForegroundWindow", CALL(P)(lambda: target), module=native),
                  support.replace_import("GetClassNameW", CALL(c.c_int, P, P, c.c_int)(query), module=native),
                  support.replace_import("GetWindow", CALL(P, P, w.UINT)(lambda hwnd, relation: None), module=native),
                  support.replace_import("IsWindowVisible", CALL(w.BOOL, P)(lambda hwnd: 1), module=native),
                  support.replace_import("GetLastActivePopup", CALL(P, P)(lambda hwnd: hwnd), module=native),
                  support.replace_import("SetForegroundWindow", CALL(w.BOOL, P)(
                      lambda hwnd: selected.append(hwnd) or 1), module=native)):
                self.assertIsNone(window.inactivate())
        self.assertEqual(capacities, [256] * 6)
        self.assertEqual(selected, [target] * 5)

    def test_drag_posts_signed_screen_coordinates_to_real_queue(self):
        window = self.window()
        hwnd = window.getHWND()
        procedure_type = CALL(c.c_ssize_t, P, w.UINT, w.WPARAM, w.LPARAM)
        user.SetWindowLongPtrW.argtypes = (P, c.c_int, P)
        user.SetWindowLongPtrW.restype = P
        user.CallWindowProcW.argtypes = (P, P, w.UINT, w.WPARAM, w.LPARAM)
        user.CallWindowProcW.restype = c.c_ssize_t
        user.PeekMessageW.argtypes = (c.POINTER(w.MSG), P, w.UINT, w.UINT, w.UINT)
        user.DispatchMessageW.argtypes = (c.POINTER(w.MSG),)
        user.DispatchMessageW.restype = c.c_ssize_t
        received = []
        def procedure(handle, message, wp, lp):
            if message == 0xa1:
                received.append((handle, wp, c.c_short(lp & 0xffff).value, c.c_short((lp >> 16) & 0xffff).value))
                return 0  # Observe delivery without entering the OS move modal loop.
            return user.CallWindowProcW(original, handle, message, wp, lp)
        callback = procedure_type(procedure)
        original = user.SetWindowLongPtrW(hwnd, -4, c.cast(callback, P))
        self.assertTrue(original)
        try:
            values = (-2147483648, -32769, -32768, -1920, -1, 0, 1, 1080, 32767, 32768, 2147483647)
            for x in values:
                for y in values:
                    with self.subTest(x=x, y=y):
                        before = len(received)
                        self.assertIsNone(window.drag(x, y))
                        self.assertEqual(len(received), before)  # Must stay asynchronous.
                        message = w.MSG()
                        self.assertTrue(user.PeekMessageW(c.byref(message), hwnd, 0xa1, 0xa1, 1))
                        self.assertEqual(message.wParam, 2)  # HTCAPTION
                        self.assertEqual(message.lParam & 0xffffffff, (x % 65536) + (y % 65536) * 65536)
                        user.DispatchMessageW(c.byref(message))
                        self.assertEqual(received[-1], (hwnd, 2, c.c_short(x).value, c.c_short(y).value))
        finally:
            user.SetWindowLongPtrW(hwnd, -4, original)

    @classmethod
    def setUpClass(cls):
        user.GetProcessWindowStation.restype = P
        user.GetThreadDesktop.argtypes = (w.DWORD,)
        user.GetThreadDesktop.restype = P
        user.GetUserObjectInformationW.argtypes = (P, c.c_int, P, w.DWORD, c.POINTER(w.DWORD))
        names = []
        for handle in (user.GetProcessWindowStation(),
                       user.GetThreadDesktop(support.kernel.GetCurrentThreadId())):
            name = c.create_unicode_buffer(256)
            needed = w.DWORD()
            assert user.GetUserObjectInformationW(handle, 2, name, c.sizeof(name), c.byref(needed))
            names.append(name.value)
        if ORDINARY:
            assert [name.lower() for name in names] == ["winsta0", "default"], names
        cls.desktop_names = names
        ckit.registerWindowClass("CallbackTests" + uuid.uuid4().hex)
        ckit.registerCommandInfoConstructor(ckit.CommandInfo)
        expected = PACKAGE / "lib" if PACKAGE else RUN_DIR / "lib"
        for name in NATIVE_NAMES:
            module = sys.modules.get(name)
            if module:
                assert Path(module.__file__).parent == expected, module.__file__
        if PACKAGE:
            for module in (ckit, pyauto):
                assert module.__file__.startswith(str(PACKAGE / "library.zip")), module.__file__
        print(f"station/desktop={names}; hidden windows; PYD={native.__file__}")

    def setUp(self):
        self.windows = []

    def tearDown(self):
        for window in reversed(self.windows):
            window.destroy()
        clear_last_exception()

    def window(self, **kwargs):
        window = ckit.Window(x=100, y=100, width=160, height=120,
                             show=False, title="Callback test", **kwargs)
        self.windows.append(window)
        return window

    def send(self, window, message, wp=0, lp=0):
        return user.SendMessageW(window.getHWND(), message, wp, lp)

    def ipc(self, window, payload, *, size=None, kind=0x101):
        buffer = c.create_string_buffer(payload) if payload is not None else None
        packet = CopyData(kind, len(payload) if size is None else size,
                          c.cast(buffer, P) if buffer is not None else None)
        return self.send(window, 0x4a, lp=c.addressof(packet))

    def test_hit_test_invalid_values_exceptions_refs_and_recovery(self):
        state = [1]
        positions = []
        def callback(x, y):
            positions.append((x, y))
            return state[0]() if callable(state[0]) else state[0]
        window = self.window(nchittest_handler=callback)
        position = ((-30 & 0xffff) << 16) | (-20 & 0xffff)
        expected = user.DefWindowProcW(window.getHWND(), 0x84, 0, position)
        for returned in (*BAD_RESULTS, fail):
            state[0] = returned
            clear_last_exception()
            baseline = sys.getrefcount(returned)
            with self.subTest(result=returned), redirect_stderr(io.StringIO()) as errors:
                for _ in range(30):
                    self.assertEqual(self.send(window, 0x84, lp=position), expected)
                self.assertIn("Error", errors.getvalue())
            clear_last_exception()
            self.assertEqual(sys.getrefcount(returned), baseline)
        state[0] = GoodIndex()
        self.assertEqual(self.send(window, 0x84, lp=position), 2)
        for value in (0, -1, -(2**31), 2**31 - 1):
            state[0] = value
            self.assertEqual(self.send(window, 0x84, lp=position), value)
        self.assertEqual(positions[-1], (-20, -30))
        with memory_error("Py_BuildValue"), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.send(window, 0x84, lp=position), expected)
        self.assertIn("MemoryError", errors.getvalue())
        self.assertEqual(self.send(window, 0x84, lp=position), 2**31 - 1)

    def test_condition_failure_continues_and_loop_recovers(self):
        window = self.window()
        for returned in (*BAD_RESULTS, fail, GoodIndex(), 1, True):
            calls = []
            def condition(calls=calls, returned=returned):
                calls.append(1)
                if len(calls) > 1:
                    return 0
                return returned() if callable(returned) else returned
            clear_last_exception()
            baseline = sys.getrefcount(returned)
            timer = user.SetTimer(window.getHWND(), 0x9876, 10, None)
            self.assertTrue(timer)
            try:
                with self.subTest(result=returned), redirect_stderr(io.StringIO()) as errors:
                    self.assertIsNone(window.messageLoop(condition))
                self.assertEqual(len(calls), 2)
                self.assertEqual(bool(errors.getvalue()), any(returned is bad for bad in BAD_RESULTS) or returned is fail)
            finally:
                user.KillTimer(window.getHWND(), timer)
                clear_last_exception()
            self.assertEqual(sys.getrefcount(returned), baseline)
            self.assertIsNone(window.messageLoop(lambda: 0))
        window.quit()
        self.assertIsNone(window.messageLoop(lambda: self.fail("quit must precede condition")))
        self.assertIsNone(window.messageLoop(lambda: 0))

    def menu_state(self, window):
        menu = user.GetSubMenu(user.GetMenu(window.getHWND()), 0)
        result = []
        for i in range(user.GetMenuItemCount(menu)):
            text = c.create_unicode_buffer(80)
            user.GetMenuStringW(menu, i, text, len(text), 0x400)
            result.append((text.value, user.GetMenuState(menu, i, 0x400) & 0xb))
        return result

    def test_menu_predicate_failures_defaults_refs_refresh_and_commands(self):
        window = self.window()
        executed = []
        def command(info):
            executed.append(info)
        for attribute in ("visible", "enabled", "checked", "root_enabled", "top_enabled"):
            for returned in (*BAD_RESULTS, fail):
                def predicate(returned=returned):
                    return returned() if callable(returned) else returned
                leaf_args = {attribute: predicate} if attribute in ("visible", "enabled", "checked") else {}
                leaf = ckit.MenuNode(text="leaf", command=command, **leaf_args)
                top = ckit.MenuNode(text="top", items=[leaf],
                                    **({"enabled": predicate} if attribute == "top_enabled" else {}))
                root = ckit.MenuNode(items=[top],
                                     **({"enabled": predicate} if attribute == "root_enabled" else {}))
                clear_last_exception()
                baseline = sys.getrefcount(returned), sys.getrefcount(command)
                with self.subTest(attribute=attribute, result=returned), redirect_stderr(io.StringIO()) as errors:
                    window.setMenu(root)
                    for _ in range(20):
                        self.send(window, 0x116)
                        self.assertEqual(self.menu_state(window), [("leaf", 0)])
                    self.assertIn("Error", errors.getvalue())
                clear_last_exception()
                self.assertEqual(sys.getrefcount(returned), baseline[0])
                menu = user.GetSubMenu(user.GetMenu(window.getHWND()), 0)
                self.send(window, 0x111, user.GetMenuItemID(menu, 0))
                self.assertIsInstance(executed.pop(), ckit.CommandInfo)
                window.setMenu(None)
                self.assertEqual(sys.getrefcount(command), baseline[1])
        # Successful predicates still hide/disable/check, with inherited disabling.
        leaves = [ckit.MenuNode(text="hidden", command=command, visible=lambda: 0),
                  ckit.MenuNode(text="disabled", command=command, enabled=lambda: 0),
                  ckit.MenuNode(text="checked", command=command, checked=lambda: GoodIndex())]
        root = ckit.MenuNode(items=[ckit.MenuNode(text="top", items=leaves)])
        window.setMenu(root)
        self.send(window, 0x116)
        self.assertEqual(self.menu_state(window), [("disabled", 3), ("checked", 8)])
        disabled = ckit.MenuNode(enabled=lambda: 0, items=root.items)
        window.setMenu(disabled)
        self.send(window, 0x116)
        self.assertEqual(self.menu_state(window), [("disabled", 3), ("checked", 11)])

    def test_menu_sequence_failures_dynamic_refs_and_recovery(self):
        window = self.window()
        leaf = ckit.MenuNode(text="leaf", command=lambda info: None)
        class LengthError:
            def __len__(self):
                raise ValueError("length sentinel")
            def __getitem__(self, index):
                return leaf
        class FetchError:
            def __len__(self):
                return 2
            def __getitem__(self, index):
                if index:
                    raise ValueError("fetch sentinel")
                return leaf
        for items in (LengthError(), FetchError()):
            def dynamic(items=items):
                return items
            root = ckit.MenuNode(items=[ckit.MenuNode(text="top", items=[dynamic])])
            baseline = sys.getrefcount(items), sys.getrefcount(leaf)
            with redirect_stderr(io.StringIO()) as errors:
                window.setMenu(root)
                for _ in range(30):
                    self.send(window, 0x116)
                    self.assertEqual(self.menu_state(window), [] if isinstance(items, LengthError) else [("leaf", 0)])
            self.assertIn("sentinel", errors.getvalue())
            clear_last_exception()
            window.setMenu(None)
            self.assertEqual((sys.getrefcount(items), sys.getrefcount(leaf)), baseline)
        window.setMenu(ckit.MenuNode())
        with redirect_stderr(io.StringIO()) as errors:
            window.setMenu(ckit.MenuNode(items=[ckit.MenuNode(text="top", items=[lambda: [leaf], fail])]))
            self.send(window, 0x116)
        self.assertIn("callback sentinel", errors.getvalue())
        self.assertEqual(self.menu_state(window), [("leaf", 0)])

    def test_sizing_invalid_mutation_and_partial_parse_recovery(self):
        values = [None]
        original_size = []
        def sizing(size):
            original_size[:] = size
            if values[0] is fail:
                fail()
            size[:] = values[0]
        window = self.window(sizing_handler=sizing)
        for mutation in ([1, "bad"], [None, 2], [1], [1, 2**80], fail):
            values[0] = mutation
            rect = w.RECT(100, 100, 400, 300)
            with redirect_stderr(io.StringIO()) as errors:
                self.send(window, 0x214, 8, c.addressof(rect))
            self.assertIn("Error", errors.getvalue())
            self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (100, 100, 400, 300))
        values[0] = [120, 90]
        rect = w.RECT(100, 100, 400, 300)
        self.send(window, 0x214, 8, c.addressof(rect))
        self.assertEqual((rect.right, rect.bottom), (400 + 120 - original_size[0], 300 + 90 - original_size[1]))
        rect = w.RECT(100, 100, 400, 300)
        with memory_error("Py_BuildValue"), redirect_stderr(io.StringIO()) as errors:
            self.send(window, 0x214, 8, c.addressof(rect))
        self.assertIn("MemoryError", errors.getvalue())
        self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (100, 100, 400, 300))

    def test_real_enum_invalid_return_stops_and_next_enum_recovers(self):
        windows = [self.window(), self.window()]
        arg = object()
        for returned in (*BAD_RESULTS, fail, 0, 1, -1, -(2**31), 2**31 - 1, GoodIndex()):
            calls = []
            def callback(window, context, calls=calls, returned=returned):
                self.assertIs(context, arg)
                calls.append(window.getHWND())
                return returned() if callable(returned) else returned
            clear_last_exception()
            baseline = sys.getrefcount(arg), sys.getrefcount(returned)
            invalid = any(returned is bad for bad in BAD_RESULTS) or returned is fail
            with self.subTest(result=returned), redirect_stderr(io.StringIO()) as errors:
                for _ in range(30):
                    calls.clear()
                    self.assertIsNone(pyauto.Window.enum(callback, arg))
                    if invalid or returned == 0:
                        self.assertEqual(len(calls), 1)
                    else:
                        self.assertTrue({window.getHWND() for window in windows} <= set(calls))
            self.assertEqual(bool(errors.getvalue()), invalid)
            clear_last_exception()
            self.assertEqual((sys.getrefcount(arg), sys.getrefcount(returned)), baseline)
        seen = []
        pyauto.Window.enum(lambda window, arg: seen.append(window.getHWND()) or 1, arg)
        self.assertTrue({window.getHWND() for window in windows} <= set(seen))

    def test_ipc_utf8_null_size_failures_handler_errors_and_recovery(self):
        received = []
        state = [False]
        marker = object()
        def handler(text):
            if state[0]:
                fail()
            self.assertIs(type(text), str)
            received.append(text)
            return marker
        window = self.window(ipc_handler=handler)
        for payload in (b"\xff", b"\xc0\xaf", b"\xe3\x81", b"\xed\xa0\x80"):
            with redirect_stderr(io.StringIO()) as errors:
                for _ in range(30):
                    self.assertEqual(self.ipc(window, payload), 0)
            self.assertIn("UnicodeDecodeError", errors.getvalue())
            self.assertEqual(received, [])
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.send(window, 0x4a), 0)
            self.assertEqual(self.ipc(window, None, size=1), 0)
            self.assertEqual(self.ipc(window, None, size=0xffffffff), 0)
        self.assertEqual(errors.getvalue().count("ValueError:"), 3)
        self.assertEqual(self.ipc(window, b"ignored", kind=0x999), 1)
        self.assertEqual(received, [])
        for payload in (b"", "日本語😀".encode(), b"a\0b", b"after failure"):
            self.assertEqual(self.ipc(window, payload), 1)
            self.assertEqual(received.pop(), payload.decode())
        self.assertEqual(self.ipc(window, None, size=0), 1)
        self.assertEqual(received.pop(), "")
        self.assertEqual(self.ipc(window, b"abc\xff", size=3), 1)
        self.assertEqual(received.pop(), "abc")
        with memory_error("Py_BuildValue"), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.ipc(window, b"valid"), 0)
        self.assertIn("MemoryError", errors.getvalue())
        state[0] = True
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.ipc(window, b"valid"), 0)
        self.assertIn("callback sentinel", errors.getvalue())
        state[0] = False
        self.assertEqual(self.ipc(window, b"recovered"), 1)
        self.assertEqual(received, ["recovered"])
        baseline = sys.getrefcount(marker)
        for _ in range(100):
            self.assertEqual(self.ipc(window, b"repeated"), 1)
            self.assertEqual(received.pop(), "repeated")
        self.assertEqual(sys.getrefcount(marker), baseline)
        with redirect_stderr(io.StringIO()) as errors:
            self.assertIsNone(ckit.Window.sendIpc(window.getHWND(), b"\xff"))
        self.assertIn("UnicodeDecodeError", errors.getvalue())
        self.assertIsNone(ckit.Window.sendIpc(window.getHWND(), "有効なIPC😀"))
        self.assertEqual(received.pop(), "有効なIPC😀")

    def test_ipc_dword_length_uses_py_ssize_t(self):
        window = self.window(ipc_handler=lambda text: self.fail("handler reached"))
        length = c.c_size_t()
        # Record the x64 third argument (R8), then tail-call PyErr_NoMemory.
        code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(length)) + b"\x4c\x89\x00"
                + b"\x48\xb8" + struct.pack("<Q", c.cast(c.pythonapi.PyErr_NoMemory, P).value)
                + b"\xff\xe0")
        with (support.executable_thunk(code) as thunk,
              support.replace_import("Py_BuildValue", thunk, module=native),
              redirect_stderr(io.StringIO()) as errors):
            self.assertEqual(self.ipc(window, b"x", size=0xffffffff), 0)
        self.assertEqual(length.value, 0xffffffff)
        self.assertIn("MemoryError", errors.getvalue())

    def test_cross_process_ipc_invalid_then_valid_repeated(self):
        received = []
        window = self.window(ipc_handler=received.append)
        sender = IPC_SENDER[:IPC_SENDER.index('payload =')]
        sender = sender.replace('"StandardCommandTests"', repr(self.desktop_names[1]))
        sender += '''
import json
u.SendMessageTimeoutW.argtypes = (w.HWND, w.UINT, w.WPARAM, w.LPARAM,
    w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t))
results = []
for _ in range(10):
    for raw in (b"\\xff", "日本語😀".encode("utf-8")):
        payload = ctypes.create_string_buffer(raw)
        packet = CopyData(0x101, len(raw), ctypes.cast(payload, w.LPVOID))
        result = ctypes.c_size_t()
        if not u.SendMessageTimeoutW(int(sys.argv[2]), 0x4a, 0, ctypes.addressof(packet), 2, 5000, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        results.append(result.value)
print(json.dumps(results))
'''
        with subprocess.Popen([sys.executable, "-B", "-c", sender, self.desktop_names[0], str(window.getHWND())],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            timer = user.SetTimer(window.getHWND(), 0x9876, 10, None)
            try:
                with redirect_stderr(io.StringIO()) as errors:
                    window.messageLoop(lambda: child.poll() is None)
            finally:
                user.KillTimer(window.getHWND(), timer)
            stdout, stderr = child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0, stderr.decode(errors="replace"))
        self.assertEqual(json.loads(stdout), [0, 1] * 10)
        self.assertEqual(received, ["日本語😀"] * 10)
        self.assertEqual(errors.getvalue().count("UnicodeDecodeError:"), 10)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
