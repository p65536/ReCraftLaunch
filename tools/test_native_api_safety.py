"""S1 native lifetime, image boundary, style and plane-order regressions.

Windows and pixels are real, on the private desktop from test_native_shell.
Shell notification and allocation/GDI failures use local IAT replacements.
"""
import ctypes as c
import faulthandler
import gc
import struct
import subprocess
import sys
import time
import unittest
import weakref
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path

import native_test_support
from native_test_support import CONFIGURATION, ROOT, RUN_DIR

PACKAGE = None
if "--package" in sys.argv:
    index = sys.argv.index("--package")
    PACKAGE = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
    native_test_support.RUN_DIR = PACKAGE
    RUN_DIR = PACKAGE
    sys.path[:0] = [str(PACKAGE / "library.zip"), str(PACKAGE / "lib")]
    import ckit
    import pyauto

import test_window_show as window_show
from test_native_shell import executable_thunk, replace_import, user

import ckit
from ckit import ckitcore


class NotifyIconData(c.Structure):
    # Only the prefix needed here; cbSize includes the remaining zeroed fields.
    _fields_ = [("size", w.DWORD), ("hwnd", w.HWND), ("id", w.UINT),
                ("flags", w.UINT), ("message", w.UINT), ("icon", w.HICON),
                ("tip", c.c_uint16 * 128)]


user.SendMessageW.argtypes = (w.HWND, w.UINT, w.WPARAM, w.LPARAM)
user.SendMessageW.restype = c.c_ssize_t
user.IsWindow.argtypes = (w.HWND,)
user.RegisterWindowMessageW.argtypes = (w.LPCWSTR,)
TASKBAR_CREATED = user.RegisterWindowMessageW("TaskbarCreated")
RETRY_TIMER = 0x103


class TaskTrayIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReCLTrayRegistrationTests")

    @contextmanager
    def registration(self, replies, *, timer_failure=False, real_timer=False):
        calls, timers, killed = [], [], []
        replies = iter(replies)
        kernel = c.WinDLL("kernel32")

        def notify(message, address):
            data = NotifyIconData.from_address(address)
            tip_end = NotifyIconData.tip.offset + c.sizeof(data.tip)
            calls.append((message, data.hwnd, bytes(data.tip),
                          c.string_at(address + tip_end, data.size - tip_end)))
            if message == 2:  # NIM_DELETE
                return True
            success, error = next(replies)
            if error is not None:
                kernel.SetLastError(error)
            return success

        def set_timer(hwnd, timer, interval, callback):
            timers.append((hwnd, timer, interval, callback))
            kernel.SetLastError(8)
            return 0 if timer_failure else timer

        def kill_timer(hwnd, timer):
            killed.append((hwnd, timer))
            return True

        with ExitStack() as stack:
            stack.enter_context(replace_import("Shell_NotifyIconW",
                c.WINFUNCTYPE(w.BOOL, w.DWORD, c.c_void_p)(notify), module=ckitcore))
            if not real_timer:
                stack.enter_context(replace_import("SetTimer",
                    c.WINFUNCTYPE(c.c_size_t, w.HWND, c.c_size_t, w.UINT, c.c_void_p)(set_timer),
                    module=ckitcore))
                stack.enter_context(replace_import("KillTimer",
                    c.WINFUNCTYPE(w.BOOL, w.HWND, c.c_size_t)(kill_timer), module=ckitcore))
            yield calls, timers, killed

    def test_titles_and_utf16_boundary(self):
        for title in (None, "", "日本語", "a" * 126, "a" * 127, "😀" * 63 + "a",
                      "a" * 125 + "😀"):
            with self.subTest(title=title), self.registration([(True, 0)]) as (calls, timers, _):
                tray = ckit.TaskTrayIcon() if title is None else ckit.TaskTrayIcon(title=title)
                try:
                    self.assertEqual(calls[0][0], 0)
                    expected = (title or "").encode("utf-16-le") + b"\0\0"
                    self.assertEqual(calls[0][2], expected.ljust(256, b"\0"))
                    self.assertTrue(calls[0][3])
                    self.assertEqual(set(calls[0][3]), {0})
                    self.assertTrue(user.IsWindow(calls[0][1]))
                    self.assertEqual(timers, [])
                finally:
                    tray.destroy()
                self.assertEqual([entry[0] for entry in calls], [0, 2])
                self.assertFalse(user.IsWindow(calls[0][1]))

    def test_rejected_titles_have_no_native_side_effects(self):
        counter = c.c_size_t()
        # Count calls without entering Python while a conversion error is pending.
        code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(counter))
                + b"\x48\xff\x00\x31\xc0\xc3")
        callback = lambda *args: None
        baseline = sys.getrefcount(callback)
        with executable_thunk(code) as thunk, ExitStack() as stack:
            for name in ("CreateWindowExW", "Shell_NotifyIconW", "SetTimer"):
                stack.enter_context(replace_import(name, thunk, module=ckitcore))
            for title in ("a" * 128, "a" * 129, "a" * 4096, "😀" * 64, "a" * 126 + "😀",
                          "a\0b", "a" * 127 + "\0"):
                with self.subTest(title=title), self.assertRaises(ValueError):
                    ckit.TaskTrayIcon(title=title, lbuttondown_handler=callback)
            for title in (None, 1, b"abc"):
                with self.subTest(title=title), self.assertRaises(TypeError):
                    ckit.TaskTrayIcon(title=title, lbuttondown_handler=callback)
        self.assertEqual(counter.value, 0)
        self.assertEqual(sys.getrefcount(callback), baseline)

    def test_retry_sequence_and_modify_success(self):
        for error in (0, 1460, None):
            with self.subTest(error=error), self.registration(
                    [(False, error), (False, 0), (False, error), (True, 0)]) as (calls, timers, killed):
                tray = ckit.TaskTrayIcon(title="retry😀")
                hwnd = calls[0][1]
                try:
                    self.assertEqual([entry[0] for entry in calls], [0])
                    self.assertEqual(timers, [(hwnd, RETRY_TIMER, 1000, None)])
                    user.SendMessageW(hwnd, 0x113, RETRY_TIMER + 1, 0)
                    self.assertEqual(len(calls), 1)
                    user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                    self.assertEqual([entry[0] for entry in calls], [0, 1, 0])
                    user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                    self.assertEqual([entry[0] for entry in calls], [0, 1, 0, 1])
                    # Ignore a WM_TIMER already queued when the timer was killed.
                    user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                    self.assertEqual(len(calls), 4)
                    self.assertEqual(killed, [(hwnd, RETRY_TIMER)] * 2)
                finally:
                    tray.destroy()
                self.assertEqual(calls[-1][0], 2)
                self.assertEqual(killed, [(hwnd, RETRY_TIMER)] * 2)

    def test_window_creation_failure_releases_handlers_before_registration(self):
        calls = c.c_size_t()
        code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(calls))
                + b"\x48\xff\x00\x31\xc0\xc3")
        kernel = c.WinDLL("kernel32")

        def fail_window(*args):
            kernel.SetLastError(8)
            return 0

        callback = lambda *args: None
        baseline = sys.getrefcount(callback)
        create = c.WINFUNCTYPE(c.c_void_p, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                              c.c_int, c.c_int, c.c_int, c.c_int,
                              w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p)(fail_window)
        with executable_thunk(code) as thunk, ExitStack() as stack:
            stack.enter_context(replace_import("CreateWindowExW", create, module=ckitcore))
            for name in ("Shell_NotifyIconW", "SetTimer"):
                stack.enter_context(replace_import(name, thunk, module=ckitcore))
            for _ in range(3):
                with self.assertRaises(OSError) as caught:
                    ckit.TaskTrayIcon(lbuttondown_handler=callback, lbuttonup_handler=callback,
                                      rbuttondown_handler=callback, rbuttonup_handler=callback,
                                      lbuttondoubleclick_handler=callback)
                self.assertEqual(caught.exception.winerror, 8)
                self.assertEqual(sys.getrefcount(callback), baseline)
        self.assertEqual(calls.value, 0)
        with self.registration([(True, 0)]):
            ckit.TaskTrayIcon().destroy()

    def test_repeated_failure_returns_and_can_be_destroyed(self):
        with self.registration([(False, 1460)] + [(False, 0)] * 40) as (calls, timers, killed):
            tray = ckit.TaskTrayIcon()
            hwnd = calls[0][1]
            for _ in range(20):
                user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
            self.assertEqual([entry[0] for entry in calls], [0] + [1, 0] * 20)
            self.assertEqual(len(timers), 21)
            tray.destroy()
            self.assertEqual(len(killed), 21)
            self.assertFalse(user.IsWindow(hwnd))
            with self.assertRaises(ValueError):
                tray.destroy()

    def test_terminal_failure_and_timer_failure(self):
        for replies, failure, expected_timers in (([(False, 5)], False, 0),
                                                 ([(False, 0)], True, 1)):
            with self.subTest(replies=replies), self.registration(
                    replies, timer_failure=failure) as (calls, timers, killed):
                tray = ckit.TaskTrayIcon()
                hwnd = calls[0][1]
                user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(timers), expected_timers)
                tray.destroy()
                self.assertEqual(killed, [])

    def test_taskbar_recreation_cancels_pending_retry_and_recovers(self):
        with self.registration([(False, 0), (True, 0), (False, 1460),
                                (False, 0), (True, 0)]) as (calls, timers, killed):
            tray = ckit.TaskTrayIcon()
            hwnd = calls[0][1]
            try:
                user.SendMessageW(hwnd, TASKBAR_CREATED, 0, 0)
                self.assertEqual([entry[0] for entry in calls], [0, 2, 0])
                self.assertEqual(killed, [(hwnd, RETRY_TIMER)])
                user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                self.assertEqual(len(calls), 3)
                user.SendMessageW(hwnd, TASKBAR_CREATED, 0, 0)
                user.SendMessageW(hwnd, 0x113, RETRY_TIMER, 0)
                self.assertEqual([entry[0] for entry in calls], [0, 2, 0, 2, 0, 1, 0])
                self.assertEqual(len(timers), 2)
            finally:
                tray.destroy()

    def test_real_timer_dispatch_recovers_and_removes_timer(self):
        with self.registration([(False, 0), (False, 0), (True, 0)], real_timer=True) as (calls, _, _):
            tray = ckit.TaskTrayIcon()
            window = ckit.Window(show=False, width=80, height=40)
            try:
                deadline = time.monotonic() + 4
                window.messageLoop(lambda: len(calls) < 3 and time.monotonic() < deadline)
                self.assertEqual([entry[0] for entry in calls], [0, 1, 0])
                # A late timer message must not add or modify the recovered icon.
                user.SendMessageW(calls[0][1], 0x113, RETRY_TIMER, 0)
                self.assertEqual(len(calls), 3)
            finally:
                window.destroy()
                tray.destroy()


class NativeApiSafetyTests(unittest.TestCase):
    window = window_show.WindowShowTests.window
    buffer = window_show.WindowShowTests.buffer

    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("ReCLApiSafetyTest")

    def test_tray_safety_in_child(self):
        self.assertEqual(Path(ckitcore.__file__).resolve(), RUN_DIR / "lib/ckitcore.pyd")
        if PACKAGE:
            self.assertTrue(str(ckit.__file__).startswith(str(PACKAGE / "library.zip")))
            self.assertTrue(str(pyauto.__file__).startswith(str(PACKAGE / "library.zip")))
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--tray-child"]
            + (["--package", str(PACKAGE)] if PACKAGE else []),
            cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_window_releases_hit_test_and_menu_tree(self):
        events = []

        class Callback:
            def __call__(self, *args):
                return 1

            def __del__(self):
                try:
                    window.destroy()
                except ValueError:
                    events.append("invalidated")

        hit, command = Callback(), Callback()
        # Set the hit-test handler at construction; no public setter exists.
        window = ckit.Window(show=False, width=80, height=40, nchittest_handler=hit)
        leaf = ckit.MenuNode("leaf", "Leaf", command=command)
        menu = ckit.MenuNode(items=[ckit.MenuNode("top", "Top", items=[leaf])])
        window.setMenu(menu)
        refs = [weakref.ref(hit), weakref.ref(command)]
        del hit, command, leaf, menu
        window.destroy()
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertEqual(events, ["invalidated", "invalidated"])
        with self.assertRaises(ValueError):
            window.destroy()

    def test_image_normal_empty_short_and_large_dimensions(self):
        self.assertEqual(ckit.Image.fromBytes((2, 1), bytes(8), None, True).getSize(), (2, 1))
        for size in ((0, 0), (0, 4), (-1, 4), (4, -1)):
            with self.subTest(size=size):
                self.assertEqual(ckit.Image.fromBytes(size, b"").getSize(), (0, 0))
        for size in ((1, 1), (65536, 65536), (536870912, 2)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                ckit.Image.fromBytes(size, b"")
        with self.assertRaises(OverflowError):
            ckit.Image.fromBytes((2147483647, 2147483647), b"")

    def test_image_rgba_rows_color_key_and_halftone(self):
        window = self.window()
        plane = ckit.ImagePlane(window, (0, 0), (2, 2), 0.0)
        pixels = bytes((255, 0, 0, 0, 0, 255, 0, 255,
                        0, 0, 255, 255, 255, 255, 255, 255))
        background = 17 | 34 << 8 | 51 << 16
        for halftone in (False, True):
            for key in (None, (0, 255, 0)):
                with self.subTest(halftone=halftone, key=key):
                    plane.setImage(ckit.Image.fromBytes((2, 2), pixels, key, halftone))
                    window.flushPaint()
                    dc = self.buffer(window).dc
                    actual = [window_show.gdi32.GetPixel(dc, x, y)
                              for y in range(2) for x in range(2)]
                    self.assertEqual(actual, [0x0000ff, background if key else 0x00ff00,
                                              0xff0000, 0xffffff])

    def test_image_buffer_allocation_failure(self):
        with executable_thunk(b"\x31\xc0\xc3") as address:
            unavailable = c.CFUNCTYPE(c.c_void_p, c.c_size_t)(address.value)
            with replace_import("malloc", unavailable, module=ckitcore):
                for size, pixels in (((1, 1), bytes(4)), ((0, 0), b"")):
                    with self.subTest(size=size), self.assertRaises(MemoryError):
                        ckit.Image.fromBytes(size, pixels)

    def test_image_wrapper_allocation_failure_releases_bitmap(self):
        error = c.cast(c.pythonapi.PyErr_NoMemory, c.c_void_p).value
        code = (b"\x48\x83\xec\x28\x48\xb8" + struct.pack("<Q", error)
                + b"\xff\xd0\x48\x83\xc4\x28\xc3")
        user.GetGuiResources.argtypes = (w.HANDLE, w.DWORD)
        user.GetGuiResources.restype = w.DWORD
        before = user.GetGuiResources(w.HANDLE(-1), 0)
        with executable_thunk(code) as address:
            unavailable = c.CFUNCTYPE(c.c_void_p, c.c_void_p)(address.value)
            with (replace_import("_PyObject_New", unavailable, module=ckitcore),
                  self.assertRaises(MemoryError)):
                ckit.Image.fromBytes((1, 1), bytes(4))
        self.assertEqual(user.GetGuiResources(w.HANDLE(-1), 0), before)

    def test_image_gdi_failures(self):
        cases = (
            ("GetDC", c.WINFUNCTYPE(w.HDC, w.HWND)),
            ("CreateCompatibleBitmap", c.WINFUNCTYPE(w.HBITMAP, w.HDC, c.c_int, c.c_int)),
            ("SetDIBits", c.WINFUNCTYPE(c.c_int, w.HDC, w.HBITMAP, w.UINT,
                                       w.UINT, c.c_void_p, c.c_void_p, w.UINT)),
        )
        for name, prototype in cases:
            with self.subTest(api=name):
                unavailable = prototype(lambda *args: 0)
                with (replace_import(name, unavailable, module=ckitcore),
                      self.assertRaisesRegex(RuntimeError, name)):
                    ckit.Image.fromBytes((1, 1), bytes(4))
        self.assertEqual(ckit.Image.fromBytes((1, 1), bytes(4)).getSize(), (1, 1))

    def test_window_button_flags_are_independent(self):
        for resizable in (False, True):
            for minimize in (False, True):
                for maximize in (False, True):
                    with self.subTest(resizable=resizable, minimize=minimize, maximize=maximize):
                        window = ckit.Window(show=False, width=80, height=40,
                                             resizable=resizable, minimizebox=minimize,
                                             maximizebox=maximize)
                        try:
                            style = user.GetWindowLongPtrW(window.getHWND(), -16)
                            self.assertEqual(bool(style & 0x20000), minimize)
                            self.assertEqual(bool(style & 0x10000), maximize and resizable)
                            self.assertEqual(bool(style & 0x40000), resizable)
                        finally:
                            window.destroy()

    def test_plane_priority_reorders_pixels_and_preserves_ties(self):
        window = self.window()
        font = ckit.Font("MS Gothic", 16)
        text = ckit.TextPlane(window, (0, 0), (32, 32), 0.0)
        text.setFont(font)
        text.putString(0, 0, 2, 1, ckit.Attribute(bg=(255, 0, 0)), "  ")
        image = ckit.ImagePlane(window, (0, 0), (32, 32), 1.0)
        image.setImage(ckit.Image.fromBytes((1, 1), bytes((0, 255, 0, 255))))
        window.show(True, False)

        def pixel():
            window.flushPaint()
            return window_show.gdi32.GetPixel(self.buffer(window).dc, 1, 1)

        self.assertEqual(pixel(), 0x0000ff)
        image.setPriority(-1.0)
        self.assertEqual(image.getPriority(), -1.0)
        self.assertEqual(pixel(), 0x00ff00)
        text.setPriority(-2.0)
        self.assertEqual(pixel(), 0x0000ff)
        # Sorting keeps the existing relative order when priorities become equal.
        image.setPriority(-2.0)
        self.assertEqual(pixel(), 0x0000ff)
        text.setPriority(-2.0)
        self.assertEqual(pixel(), 0x0000ff)
        text.setPriority(2.0)
        self.assertEqual(pixel(), 0x00ff00)


def tray_child():
    ckit.registerWindowClass("ReCLTraySafetyChild")
    events = []
    tray = None

    class Callback:
        def __call__(self, *args):
            return None

        def __del__(self):
            for operation, args in ((tray.destroy, ()), (tray.popupMenu, (0, 0, []))):
                try:
                    operation(*args)
                except ValueError:
                    events.append("invalidated")

    notify = c.WINFUNCTYPE(w.BOOL, w.DWORD, c.c_void_p)(lambda *args: True)
    track = c.WINFUNCTYPE(w.BOOL, w.HMENU, w.UINT, c.c_int, c.c_int,
                         c.c_int, w.HWND, c.c_void_p)(lambda *args: False)
    with (replace_import("Shell_NotifyIconW", notify, module=ckitcore),
          replace_import("TrackPopupMenu", track, module=ckitcore)):
        callback = Callback()
        tray = ckit.TaskTrayIcon(title="test", lbuttondown_handler=callback,
                                 lbuttonup_handler=callback, rbuttondown_handler=callback,
                                 rbuttonup_handler=callback, lbuttondoubleclick_handler=callback)
        baseline = sys.getrefcount(tray)
        tray.popupMenu(0, 0, [("command", callback)])
        reference = weakref.ref(callback)
        del callback
        tray.destroy()
        assert reference() is None
        assert events == ["invalidated", "invalidated"], events
        assert sys.getrefcount(tray) == baseline - 1  # Native owner released its wrapper.
        for operation, args in ((tray.destroy, ()), (tray.popupMenu, (0, 0, []))):
            try:
                operation(*args)
            except ValueError:
                pass
            else:
                raise AssertionError("destroyed tray accepted an operation")
        tray = None
        gc.collect()
        # OS-driven destruction must run the same cleanup as the public method.
        callback = Callback()
        tray = ckit.TaskTrayIcon(lbuttondown_handler=callback)
        reference = weakref.ref(callback)
        del callback
        native_address = c.c_void_p.from_address(id(tray) + 2 * c.sizeof(c.c_void_p)).value
        hwnd = w.HWND.from_address(native_address).value
        assert user.DestroyWindow(hwnd)
        assert reference() is None
        assert events == ["invalidated"] * 4
        tray = None
        gc.collect()


if __name__ == "__main__":
    faulthandler.dump_traceback_later(25, exit=True)
    print(f"{CONFIGURATION}: {RUN_DIR / 'lib/ckitcore.pyd'}", flush=True)
    if "--tray-child" in sys.argv:
        sys.argv.remove("--tray-child")
        tray_child()
        unittest.main(defaultTest="TaskTrayIconTests", verbosity=2)
    else:
        unittest.main(defaultTest="NativeApiSafetyTests", verbosity=2)
