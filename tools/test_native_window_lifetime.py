"""Window construction/destruction faults in a child process on a private desktop.

Supports --package DIR and --ordinary-desktop through the callback test fixture.
The parent process never imports a native GUI extension.
"""
import ctypes as c
import faulthandler
import gc
import io
import struct
import subprocess
import sys
import unittest
import weakref
from contextlib import ExitStack, contextmanager, redirect_stderr
from ctypes import wintypes as w
from pathlib import Path

if __name__ == "__main__" and "--child" not in sys.argv:
    result = subprocess.run([sys.executable, "-B", __file__, "--child", *sys.argv[1:]],
                            check=False, timeout=120)
    if result.returncode:
        print(f"Native window child exited with {result.returncode:#x}", file=sys.stderr)
    sys.exit(result.returncode)
if "--child" in sys.argv:
    sys.argv.remove("--child")

import test_native_callbacks as fixture
from test_native_shell import CALL, P, executable_thunk, imports, replace_import

import ckit
from ckit import ckitcore as native

user = c.WinDLL("user32")
kernel = c.WinDLL("kernel32")
kernel.SetErrorMode(0x8003)  # Crash dialogs must not block the disposable child.
for name in ("IsWindow", "DestroyWindow"):
    getattr(user, name).argtypes = (P,)
    getattr(user, name).restype = w.BOOL
user.GetWindow.argtypes = (P, w.UINT)
user.GetWindow.restype = P
user.GetClassLongPtrW.argtypes = (P, c.c_int)
user.GetClassLongPtrW.restype = P
user.SetClassLongPtrW.argtypes = (P, c.c_int, P)
user.SetClassLongPtrW.restype = P
CREATE = CALL(P, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
              c.c_int, c.c_int, c.c_int, c.c_int, P, P, P, P)
PROC = CALL(c.c_ssize_t, P, w.UINT, w.WPARAM, w.LPARAM)


@contextmanager
def creation_failure(error=1400):
    def fail(*args):
        kernel.SetLastError(error)
    with replace_import("CreateWindowExW", CREATE(fail), native):
        yield


@contextmanager
def native_allocations():
    slots = imports(native)
    allocated, freed = c.c_size_t(), c.c_size_t()
    with ExitStack() as stack:
        for name, counter in (("malloc", allocated),
                              ("_free_dbg" if "_free_dbg" in slots else "free", freed)):
            code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(counter)) + b"\x48\xff\x00"
                    + b"\x48\xb8" + struct.pack("<Q", P.from_address(slots[name]).value)
                    + b"\xff\xe0")
            if counter is freed:
                code = b"\x48\x85\xc9\x74\x0d" + code
            thunk = stack.enter_context(executable_thunk(code))
            stack.enter_context(replace_import(name, thunk, native))
        yield allocated, freed


@contextmanager
def tray_popup_fixture(track=None, *, real_tracking=False):
    handles, tracked, notifications = [], [], []

    class IconData(c.Structure):
        _fields_ = [("size", w.DWORD), ("hwnd", P)]

    def notify(action, data):
        notifications.append(action)
        if action == 0:
            handles.append(c.cast(data, c.POINTER(IconData)).contents.hwnd)
        return 1

    def tracking(*args):
        tracked.append(args[5])
        return track(*args) if track else 1

    with ExitStack() as stack:
        for name, callback in (
                ("Shell_NotifyIconW", CALL(w.BOOL, w.DWORD, P)(notify)),
                ("SetForegroundWindow", CALL(w.BOOL, P)(lambda hwnd: 1)),
                ("SetFocus", CALL(P, P)(lambda hwnd: 0)),
                ("TrackPopupMenu", CALL(w.BOOL, P, w.UINT, c.c_int, c.c_int, c.c_int, P, P)(tracking))):
            if name != "TrackPopupMenu" or not real_tracking:
                stack.enter_context(replace_import(name, callback, native))
        yield handles, tracked, notifications


class NativeWindowLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        expected = (fixture.PACKAGE or fixture.RUN_DIR) / "lib/ckitcore.pyd"
        assert Path(native.__file__).resolve() == expected.resolve()
        if fixture.PACKAGE:
            assert ckit.__file__.startswith(str(fixture.PACKAGE / "library.zip"))
        if fixture.ORDINARY:
            user.GetProcessWindowStation.restype = P
            user.GetThreadDesktop.argtypes = (w.DWORD,)
            user.GetThreadDesktop.restype = P
            user.GetUserObjectInformationW.argtypes = (P, c.c_int, P, w.DWORD, c.POINTER(w.DWORD))
            names = []
            for handle in (user.GetProcessWindowStation(), user.GetThreadDesktop(kernel.GetCurrentThreadId())):
                name, needed = c.create_unicode_buffer(256), w.DWORD()
                assert user.GetUserObjectInformationW(handle, 2, name, c.sizeof(name), c.byref(needed))
                names.append(name.value)
            assert [name.lower() for name in names] == ["winsta0", "default"], names
            print("station/desktop:", names, flush=True)
        ckit.registerWindowClass("ReCLWindowLifetimeTest")
        print("ckitcore:", native.__file__, flush=True)

    def assert_dead(self, window, hwnd):
        self.assertFalse(user.IsWindow(hwnd))
        for operation in (window.getHWND, lambda: ckit.Window.destroy(window)):
            with self.assertRaises(ValueError):
                operation()

    def check_callback_destroy(self, kind):
        events = []
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        plane = ckit.TextPlane(window, (0, 0), (10, 10), 0)

        def callback():
            events.append("callback")
            window.destroy()
            self.assert_dead(window, hwnd)
            with self.assertRaises(ValueError):
                plane.destroy()
            for operation in (lambda: window.setTimer(callback, 10),
                              lambda: window.killTimer(callback),
                              lambda: window.delayedCall(callback, 0),
                              lambda: window.setHotKey(0x78, 2, callback),
                              lambda: window.killHotKey(callback)):
                with self.assertRaises(ValueError):
                    operation()
            # Delivery after destruction must not call Python again.
            fixture.user.SendMessageW(hwnd, message, ident, 0)

        message, ident = (0x312, 0) if kind == "hotkey" else (0x113, id(callback))
        references = sys.getrefcount(callback)
        unregistered = []
        def unregister(handle, ident):
            unregistered.append((handle, ident))
            return 1
        with ExitStack() as stack:
            if kind == "hotkey":
                stack.enter_context(replace_import("RegisterHotKey", CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)(lambda *args: 1), native))
                stack.enter_context(replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(unregister), native))
                window.setHotKey(0x78, 2, callback)
            elif kind == "delayed":
                window.delayedCall(callback, 0)
                window.delayedCall(lambda: events.append("unexpected"), 0)
                ident = 0x101  # TIMER_PAINT
            else:
                window.setTimer(callback, 60000)
            with redirect_stderr(io.StringIO()) as errors:
                fixture.user.SendMessageW(hwnd, message, ident, 0)
            self.assertEqual(errors.getvalue(), "")
        self.assertEqual(events, ["callback"])
        self.assertEqual(sys.getrefcount(callback), references)
        self.assertEqual(unregistered, [(hwnd, 0)] if kind == "hotkey" else [])
        self.assert_dead(window, hwnd)

    def test_image_direct_construction_is_rejected(self):
        initialized = []
        class Image(ckit.Image):
            pass
        class InitOnlyImage(ckit.Image):
            def __init__(self):
                initialized.append(self)
        class ObjectNewImage(ckit.Image):
            __new__ = object.__new__
        class BypassImage(ckit.Image):
            def __new__(cls):
                return object.__new__(cls)
        class DelegatingImage(ckit.Image):
            def __new__(cls):
                return super().__new__(cls)

        for kind in (ckit.Image, Image, InitOnlyImage, ObjectNewImage, BypassImage, DelegatingImage):
            for create, args in ((kind, ()), (ckit.Image.__new__, (kind,)), (object.__new__, (kind,))):
                with self.subTest(kind=kind.__name__, create=create), self.assertRaises(TypeError):
                    create(*args)
            # The inherited static factory must still return a valid base Image.
            image = kind.fromBytes((1, 1), bytes((0, 255, 0, 255)))
            self.assertIs(type(image), ckit.Image)
            self.assertEqual(image.getSize(), (1, 1))
            del image
        self.assertEqual(initialized, [])
        with self.assertRaisesRegex(TypeError, "use Image.fromBytes"):
            ckit.Image()
        gc.collect()

    def test_image_factory_empty_shared_lifetime_and_drawing(self):
        from test_window_show import WindowShowTests, gdi32

        window = ckit.Window(show=False, width=32, height=32)
        self.addCleanup(window.destroy)
        plane = ckit.ImagePlane(window, (0, 0), (32, 32), 0)
        image = ckit.Image.fromBytes((1, 1), bytes((0, 255, 0, 255)))
        plane.setImage(image)
        shared = plane.getImage()
        self.assertIsNot(shared, image)
        del image
        plane.destroy()
        gc.collect()
        self.assertEqual(shared.getSize(), (1, 1))
        plane = ckit.ImagePlane(window, (0, 0), (32, 32), 0)
        self.assertIsNone(plane.setImage(shared))
        del shared
        gc.collect()
        window.show(True, False)
        window.flushPaint()
        buffer = WindowShowTests.buffer(self, window)
        self.assertEqual(gdi32.GetPixel(buffer.dc, 1, 1), 0x00ff00)
        empty = ckit.Image.fromBytes((0, 0), b"")
        self.assertEqual(empty.getSize(), (0, 0))
        self.assertIsNone(plane.setImage(empty))
        del empty
        gc.collect()
        self.assertEqual(plane.getImage().getSize(), (0, 0))
        window.flushPaint()

    def test_plane_constructor_rejects_invalid_window_and_can_retry(self):
        window = ckit.Window(show=False)
        self.addCleanup(window.destroy)
        destroyed = ckit.Window(show=False)
        destroyed.destroy()
        os_destroyed = ckit.Window(show=False)
        self.assertTrue(user.DestroyWindow(os_destroyed.getHWND()))
        uninitialized = ckit.Window.__new__(ckit.Window)
        for kind in (ckit.ImagePlane, ckit.TextPlane):
            plane = kind.__new__(kind)
            references = sys.getrefcount(plane)
            for argument, error in ((None, TypeError), (1, TypeError),
                                    (object(), TypeError), (ckit.Font("MS Gothic", 16), TypeError),
                                    (uninitialized, ValueError), (destroyed, ValueError),
                                    (os_destroyed, ValueError)):
                with self.subTest(kind=kind.__name__, argument=type(argument).__name__, error=error):
                    argument_refs = sys.getrefcount(argument)
                    with (native_allocations() as (allocated, freed),
                          self.assertRaises(error)):
                        kind.__init__(plane, argument, (0, 0), (32, 32), 0)
                    self.assertEqual(allocated.value, 0)
                    self.assertEqual(freed.value, 0)
                    self.assertEqual(sys.getrefcount(argument), argument_refs)
                    self.assertEqual(sys.getrefcount(plane), references)
                    with self.assertRaises(ValueError):
                        plane.destroy()
            # A failed initializer must leave the same wrapper reusable.
            kind.__init__(plane, window, (0, 0), (32, 32), 0)
            self.assertEqual(sys.getrefcount(plane), references + 1)
            self.assertEqual(plane.getSize(), (32, 32))
            self.assertIsNone(plane.destroy())
            self.assertEqual(sys.getrefcount(plane), references)

    def test_plane_setters_reject_wrong_types_preserve_content_and_draw(self):
        from test_window_show import WindowShowTests, gdi32

        class Window(ckit.Window):
            pass
        class Font(ckit.Font):
            pass
        class TextPlane(ckit.TextPlane):
            pass
        class ImagePlane(ckit.ImagePlane):
            pass

        window = Window(show=False, width=64, height=32)
        self.addCleanup(window.destroy)
        text = TextPlane(window, (0, 0), (32, 32), 0)
        image = ImagePlane(window, (32, 0), (32, 32), 0)
        font = Font("MS Gothic", 16)
        bitmap = ckit.Image.fromBytes((1, 1), bytes((0, 255, 0, 255)))
        self.assertIsNone(text.setFont(font))
        self.assertIsNone(image.setImage(bitmap))
        text.putString(0, 0, 2, 1, ckit.Attribute(bg=(255, 0, 0)), "  ")
        window.show(True, False)
        window.flushPaint()
        buffer = WindowShowTests.buffer(self, window)
        for plane, method, resource, getter, other in (
                (text, text.setFont, font, text.getFont, bitmap),
                (image, image.setImage, bitmap, image.getImage, font)):
            resource_size = (resource.getCharSize() if plane is text else resource.getSize())
            for invalid in (None, 1, object(), other, window, plane):
                with self.subTest(setter=method.__name__, argument=type(invalid).__name__):
                    references = sys.getrefcount(invalid)
                    with self.assertRaises(TypeError):
                        method(invalid)
                    self.assertEqual(sys.getrefcount(invalid), references)
                    retained = getter()
                    self.assertEqual(retained.getCharSize() if plane is text else retained.getSize(),
                                     resource_size)
                    # Both the original and the shared native resource remain usable.
                    self.assertIsNone(method(retained))
                    self.assertIsNone(method(resource))
            with self.assertRaises(TypeError):
                method()
        font_ref = weakref.ref(font)
        del method, resource, retained, other, font, bitmap
        gc.collect()
        self.assertIsNone(font_ref())  # The plane owns the C++ Font, not its wrapper.
        window.flushPaint()
        self.assertEqual(gdi32.GetPixel(buffer.dc, 1, 1), 0x0000ff)
        self.assertEqual(gdi32.GetPixel(buffer.dc, 33, 1), 0x00ff00)
        self.assertEqual(text.getFont().getCharSize(), text.getCharSize())
        self.assertEqual(image.getImage().getSize(), (1, 1))

    def test_plane_rejection_and_recreation_release_owners(self):
        class Plane(ckit.ImagePlane):
            pass

        for destruction in ("plane", "clear", "window", "os"):
            with self.subTest(destruction=destruction):
                window = ckit.Window(show=False)
                plane = Plane(window, (0, 0), (32, 32), 0)
                references = sys.getrefcount(plane)
                with self.assertRaises(TypeError):
                    plane.setImage(None)
                self.assertEqual(sys.getrefcount(plane), references)
                reference = weakref.ref(plane)
                if destruction == "plane":
                    plane.destroy()
                elif destruction == "clear":
                    window.clear()
                elif destruction == "window":
                    window.destroy()
                else:
                    self.assertTrue(user.DestroyWindow(window.getHWND()))
                with self.assertRaises(ValueError):
                    plane.setImage(ckit.Image.fromBytes((1, 1), bytes(4)))
                del plane
                gc.collect()
                self.assertIsNone(reference())
                if destruction in ("plane", "clear"):
                    replacement = Plane(window, (0, 0), (32, 32), 0)
                    replacement.setImage(ckit.Image.fromBytes((1, 1), bytes(4)))
                    window.destroy()
                    with self.assertRaises(ValueError):
                        replacement.destroy()

    def test_timer_callback_self_destroy(self):
        self.check_callback_destroy("timer")

    def test_delayed_callback_self_destroy(self):
        self.check_callback_destroy("delayed")

    def test_hotkey_callback_self_destroy(self):
        self.check_callback_destroy("hotkey")

    def test_nested_dispatch_os_destroy_and_finalizer_reentry(self):
        events, checks = [], []
        class Window(ckit.Window):
            pass
        class Handler:
            def __call__(self, *args):
                events.append("inner")
                user.DestroyWindow(hwnd)
                checks.append(not user.IsWindow(hwnd))
                fixture.user.SendMessageW(hwnd, 0x100, 65, 0)
                events.append("inner return")

            def __del__(self):
                events.append("finalizer")
                try:
                    window.getHWND()
                except ValueError:
                    checks.append(True)
                fixture.user.SendMessageW(hwnd, 0x100, 65, 0)

        handler = Handler()
        handler_ref = weakref.ref(handler)
        window = Window(show=False, keydown_handler=handler)
        wrapper_ref = weakref.ref(window)
        hwnd = window.getHWND()
        del handler
        def timer():
            events.append("outer")
            fixture.user.SendMessageW(hwnd, 0x100, 65, 0)
            checks.append(handler_ref() is not None)
            events.append("outer return")
        window.setTimer(timer, 60000)
        with redirect_stderr(io.StringIO()) as errors:
            fixture.user.SendMessageW(hwnd, 0x113, id(timer), 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(events, ["outer", "inner", "inner return", "outer return", "finalizer"])
        self.assertEqual(checks, [True, True, True])
        self.assertIsNone(handler_ref())
        window = None
        self.assertIsNone(wrapper_ref())

    def test_move_destroy_skips_size_and_position_retry(self):
        events = []
        armed = False
        def move(*args):
            if armed:
                events.append("move")
                window.destroy()
        window = ckit.Window(show=False, move_handler=move,
                             size_handler=lambda *args: events.append("size") if armed else None)
        armed = True
        hwnd = window.getHWND()
        with redirect_stderr(io.StringIO()) as errors:
            window.setPositionAndSize(100, 100, 200, 100, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(events, ["move"])
        self.assert_dead(window, hwnd)

    def test_sizing_destroy_stops_geometry_write(self):
        def sizing(size):
            size[:] = [999, 999]
            window.destroy()
        window = ckit.Window(show=False, sizing_handler=sizing)
        hwnd = window.getHWND()
        rect = w.RECT(10, 20, 210, 120)
        with redirect_stderr(io.StringIO()) as errors:
            fixture.user.SendMessageW(hwnd, 0x214, 2, c.addressof(rect))
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual((rect.left, rect.top, rect.right, rect.bottom), (10, 20, 210, 120))
        self.assert_dead(window, hwnd)

    def test_nested_timer_hotkey_delayed_destroy(self):
        events = []
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        def delayed():
            events.append("destroy")
            window.destroy()
        def hotkey():
            events.append("hotkey")
            fixture.user.SendMessageW(hwnd, 0x113, 0x101, 0)
            events.append("hotkey return")
        def timer():
            events.append("timer")
            fixture.user.SendMessageW(hwnd, 0x312, 0, 0)
            events.append("timer return")
        with (replace_import("RegisterHotKey", CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)(lambda *args: 1), native),
              replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(lambda *args: 1), native),
              redirect_stderr(io.StringIO()) as errors):
            window.setTimer(timer, 60000)
            window.setHotKey(0x78, 2, hotkey)
            window.delayedCall(delayed, 0)
            fixture.user.SendMessageW(hwnd, 0x113, id(timer), 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(events, ["timer", "hotkey", "destroy", "hotkey return", "timer return"])
        self.assert_dead(window, hwnd)

    def test_destroy_failure_suppresses_nested_callback_then_recovers(self):
        events = []
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        def timer():
            events.append("timer")
            if len(events) == 1:
                with self.assertRaises(OSError):
                    window.destroy()
            else:
                window.destroy()
        def fail(handle):
            fixture.user.SendMessageW(handle, 0x113, id(timer), 0)
            fixture.user.SendMessageW(handle, 0x100, 65, 0)
            kernel.SetLastError(5)
            return 0
        window.setTimer(timer, 60000)
        with (replace_import("DestroyWindow", CALL(w.BOOL, P)(fail), native),
              redirect_stderr(io.StringIO()) as errors):
            fixture.user.SendMessageW(hwnd, 0x113, id(timer), 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(events, ["timer"])
        self.assertEqual(window.getHWND(), hwnd)
        fixture.user.SendMessageW(hwnd, 0x113, id(timer), 0)
        self.assertEqual(events, ["timer", "timer"])
        self.assert_dead(window, hwnd)

    def test_reinitialize_destroyed_wrapper_before_dispatch_returns(self):
        window = ckit.Window(show=False)
        def timer():
            window.destroy()
            ckit.Window.__init__(window, show=False)
        window.setTimer(timer, 60000)
        with redirect_stderr(io.StringIO()) as errors:
            fixture.user.SendMessageW(window.getHWND(), 0x113, id(timer), 0)
        self.assertEqual(errors.getvalue(), "")
        hwnd = window.getHWND()
        self.assertTrue(user.IsWindow(hwnd))
        window.destroy()
        self.assert_dead(window, hwnd)

    def test_callback_destroy_balances_native_and_gdi_allocations(self):
        import test_native_gdi as gdi
        for _ in range(100):
            for kind in ("timer", "delayed", "hotkey"):
                self.check_callback_destroy(kind)
        gc.collect()
        before = gdi.gdi_count()
        with native_allocations() as (allocated, freed):
            for _ in range(30):
                for kind in ("timer", "delayed", "hotkey"):
                    self.check_callback_destroy(kind)
        self.assertGreater(allocated.value, 90)
        self.assertEqual(allocated.value, freed.value)
        gc.collect()
        self.assertEqual(gdi.gdi_count(), before)

    def test_real_timer_and_delayed_delivery_self_destroy(self):
        for kind in ("timer", "delayed"):
            window = ckit.Window(show=False)
            hwnd = window.getHWND()
            events = []
            def callback(events=events, kind=kind, window=window):
                events.append(kind)
                window.destroy()
            if kind == "timer":
                window.setTimer(callback, 10)
            else:
                window.delayedCall(callback, 0)
            with redirect_stderr(io.StringIO()) as errors:
                window.messageLoop()
            self.assertEqual(errors.getvalue(), "")
            self.assertEqual(events, [kind])
            self.assert_dead(window, hwnd)

    def test_loop_condition_destroy_does_not_wait_again(self):
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        window.messageLoop(lambda: (window.destroy(), 1)[1])
        self.assert_dead(window, hwnd)

    def test_menu_callbacks_destroy_skip_remaining_callbacks(self):
        for stage in ("visible", "enabled", "checked", "items", "root"):
            for during_refresh in (False, True):
                if stage == "root" and not during_refresh:
                    continue  # Root enabled is evaluated only by WM_INITMENU.
                events = []
                armed = [not during_refresh]
                window = ckit.Window(show=False)
                hwnd = window.getHWND()
                def callback(name, value, armed=armed, events=events, stage=stage, window=window):
                    def call():
                        if armed[0]:
                            events.append(name)
                            if name == stage:
                                window.destroy()
                        return value
                    return call
                leaf = ckit.MenuNode("item", "Item", command=lambda info: None,
                                     visible=callback("visible", 1),
                                     enabled=callback("enabled", 1),
                                     checked=callback("checked", 0))
                dynamic = callback("items", [leaf])
                root = ckit.MenuNode("root", items=[ckit.MenuNode("menu", "Menu", items=[dynamic])],
                                     enabled=callback("root", 1))
                with redirect_stderr(io.StringIO()) as errors:
                    window.setMenu(root)
                    if during_refresh:
                        armed[0] = True
                        fixture.user.SendMessageW(hwnd, 0x116, 0, 0)
                self.assertEqual(errors.getvalue(), "")
                self.assertTrue(events)
                self.assertEqual(events[-1], stage)
                self.assert_dead(window, hwnd)

    def test_command_info_destroy_skips_menu_command(self):
        events = []
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        root = ckit.MenuNode("root", items=[ckit.MenuNode("menu", "Menu", items=[
            ckit.MenuNode("item", "Item", command=lambda info: events.append("unexpected"))])])
        window.setMenu(root)
        def info():
            events.append("info")
            window.destroy()
            return ckit.CommandInfo()
        ckit.registerCommandInfoConstructor(info)
        try:
            with redirect_stderr(io.StringIO()) as errors:
                fixture.user.SendMessageW(hwnd, 0x111, 0x100, 0)
            self.assertEqual(errors.getvalue(), "")
            self.assertEqual(events, ["info"])
            self.assert_dead(window, hwnd)
        finally:
            ckit.registerCommandInfoConstructor(ckit.CommandInfo)

    def test_popup_command_destroy_during_tracking(self):
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        track_type = CALL(w.BOOL, P, w.UINT, c.c_int, c.c_int, c.c_int, P, P)
        def track(menu, flags, x, y, reserved, owner, rect):
            fixture.user.SendMessageW(owner, 0x111, 1280, 0)
            return 1
        ckit.registerCommandInfoConstructor(ckit.CommandInfo)
        with (replace_import("TrackPopupMenu", track_type(track), native),
              redirect_stderr(io.StringIO()) as errors):
            window.popupMenu(0, 0, [("Destroy", lambda info: window.destroy())])
        self.assertEqual(errors.getvalue(), "")
        self.assert_dead(window, hwnd)

    def test_unregister_comparison_and_finalizer_can_destroy(self):
        for kind in ("timer", "hotkey"):
            for stage in ("compare", "finalize"):
                window = ckit.Window(show=False)
                hwnd = window.getHWND()
                events = []
                class Handler:
                    def __call__(self):
                        pass

                    def __del__(self, events=events, stage=stage, window=window):
                        events.append("finalize")
                        if stage == "finalize":
                            window.destroy()

                class Equal:
                    def __eq__(self, other, events=events, stage=stage, window=window):
                        events.append("compare")
                        if stage == "compare":
                            window.destroy()
                        return True
                with ExitStack() as stack:
                    if kind == "hotkey":
                        stack.enter_context(replace_import("RegisterHotKey", CALL(w.BOOL, P, c.c_int, w.UINT, w.UINT)(lambda *args: 1), native))
                        stack.enter_context(replace_import("UnregisterHotKey", CALL(w.BOOL, P, c.c_int)(lambda *args: 1), native))
                        window.setHotKey(0x78, 2, Handler())
                        window.killHotKey(Equal())
                    else:
                        window.setTimer(Handler(), 60000)
                        window.killTimer(Equal())
                self.assertEqual(events, ["compare", "finalize"])
                self.assert_dead(window, hwnd)

    @unittest.skipUnless(fixture.ORDINARY, "Run with --ordinary-desktop for OS hotkey registration")
    def test_real_hotkey_destroy_releases_registration(self):
        window = ckit.Window(show=False)
        hwnd = window.getHWND()
        window.setHotKey(0x87, 2 | 4, window.destroy)
        fixture.user.SendMessageW(hwnd, 0x312, 0, 0)
        self.assert_dead(window, hwnd)
        replacement = ckit.Window(show=False)
        try:
            callback = lambda: None
            replacement.setHotKey(0x87, 2 | 4, callback)
            replacement.killHotKey(callback)
        finally:
            replacement.destroy()

    def test_destroyed_parent_is_rejected(self):
        for cls in (ckit.Window, ckit.TextWindow):
            parent = cls(show=False)
            parent.destroy()
            for child_cls in (ckit.Window, ckit.TextWindow):
                options = {"font_name": "Consolas"} if child_cls is ckit.TextWindow else {}
                with self.assertRaises(ValueError):
                    child_cls(show=False, parent_window=parent, **options)
            if cls is ckit.TextWindow:
                with self.assertRaises(ValueError):
                    ckit.TextWindow(show=False, parent_window=parent)
        uninitialized = ckit.Window.__new__(ckit.Window)
        with self.assertRaises(ValueError):
            ckit.Window(show=False, parent_window=uninitialized)

    def test_create_failure_raises_and_can_retry(self):
        for code in (1400, 0):
            window = ckit.Window.__new__(ckit.Window)
            with creation_failure(code), self.assertRaises(OSError) as error:
                ckit.Window.__init__(window, show=False)
            self.assertEqual(error.exception.winerror, code or 31)
            with self.assertRaises(ValueError):
                window.getHWND()
            ckit.Window.__init__(window, show=False)
            hwnd = window.getHWND()
            window.destroy()
            self.assert_dead(window, hwnd)

    def test_create_error_survives_dpi_context_restore(self):
        original = CALL(P, P)(P.from_address(imports(native)["SetThreadDpiAwarenessContext"]).value)
        def restore(context):
            result = original(context)
            kernel.SetLastError(5)
            return result
        with (replace_import("SetThreadDpiAwarenessContext", CALL(P, P)(restore), native),
              creation_failure(1400), self.assertRaises(OSError) as error):
            ckit.Window(show=False)
        self.assertEqual(error.exception.winerror, 1400)

    def test_native_allocation_failure_and_live_reinitialization(self):
        real = CALL(P, c.c_size_t)(P.from_address(imports(native)["malloc"]).value)
        failed = []
        def allocate(size):
            # Target the Window block; Debug STL's small noexcept proxies must succeed.
            if size >= 512:
                failed.append(size)
                return None
            return real(size)
        with (replace_import("malloc", CALL(P, c.c_size_t)(allocate), native),
              self.assertRaises(MemoryError)):
            ckit.Window(show=False)
        self.assertEqual(len(failed), 1)
        window = ckit.Window(show=False)
        try:
            hwnd = window.getHWND()
            with self.assertRaises(ValueError):
                ckit.Window.__init__(window, show=False)
            self.assertEqual(window.getHWND(), hwnd)
        finally:
            window.destroy()

    def test_userdata_property_failure_releases_partial_window(self):
        with (replace_import("SetPropW", CALL(w.BOOL, P, w.LPCWSTR, P)(lambda *args: 0), native),
              self.assertRaises(OSError)):
            ckit.Window(show=False)
        ckit.Window(show=False).destroy()

    def test_parent_object_hwnd_omitted_zero_and_none(self):
        parent = ckit.Window(show=False)
        try:
            for owner in (parent, parent.getHWND(), 0):
                child = ckit.Window(show=False, parent_window=owner)
                try:
                    self.assertEqual(user.GetWindow(child.getHWND(), 4),
                                     parent.getHWND() if owner else None)
                finally:
                    child.destroy()
            ckit.Window(show=False).destroy()
            with self.assertRaises(TypeError):
                ckit.Window(show=False, parent_window=None)
            with self.assertRaises(OSError):
                ckit.Window(show=False, parent_window=0x1234567887654321)
        finally:
            parent.destroy()

    def test_failure_releases_callbacks_wrappers_native_and_gdi_resources(self):
        import test_native_gdi as gdi

        class Window(ckit.Window):
            pass

        class Handler:
            def __call__(self, *args):
                pass

        handler = Handler()
        names = ("activate", "close", "endsession", "move", "sizing", "size", "dpi",
                 "dropfiles", "ipc", "keydown", "keyup", "char", "lbuttondown", "lbuttonup",
                 "mbuttondown", "mbuttonup", "rbuttondown", "rbuttonup", "lbuttondoubleclick",
                 "mbuttondoubleclick", "rbuttondoubleclick", "mousemove", "mousewheel", "nchittest")
        handlers = {name + "_handler": handler for name in names}
        baseline = sys.getrefcount(handler)
        # Warm Windows' lazy GDI bookkeeping and font measurement before counting.
        with gdi.audit_gdi(), creation_failure():
            for cls in (Window,) * 100 + (ckit.TextWindow,):
                with self.assertRaises(OSError):
                    cls(show=False, **handlers)
        gc.collect()
        before = gdi.gdi_count()
        with (gdi.audit_gdi() as (created, deleted, errors, _), creation_failure(),
              native_allocations() as (allocated, freed)):
            for _ in range(100):
                window = Window.__new__(Window)
                ref = weakref.ref(window)
                refs = sys.getrefcount(window)
                with self.assertRaises(OSError):
                    Window.__init__(window, show=False, **handlers)
                self.assertEqual(sys.getrefcount(window), refs)
                self.assertEqual(sys.getrefcount(handler), baseline)
                del window
                self.assertIsNone(ref())
        self.assertGreaterEqual(allocated.value, 100)
        self.assertEqual(allocated.value, freed.value)
        self.assertEqual(len(created), 400)
        self.assertCountEqual(created, deleted)
        self.assertEqual(errors, [])
        gc.collect()
        self.assertEqual(gdi.gdi_count(), before)

        # TextWindow owns bound handlers even before its TextPlane exists.
        with creation_failure():
            for _ in range(30):
                with self.assertRaises(OSError):
                    ckit.TextWindow(show=False)
        gc.collect()
        self.assertEqual(gdi.gdi_count(), before)
        ckit.TextWindow(show=False).destroy()

    def test_os_failure_after_wm_create_does_not_delete_constructing_object(self):
        import test_native_gdi as gdi

        anchor = ckit.Window(show=False)
        original = PROC(user.GetClassLongPtrW(anchor.getHWND(), -24))
        messages, handles = [], []
        def procedure(hwnd, msg, wp, lp):
            result = original(hwnd, msg, wp, lp)
            if msg == 1:
                handles.append(hwnd)
                return -1
            if msg in (2, 0x82):
                messages.append(msg)
            return result
        callback = PROC(procedure)
        try:
            user.SetClassLongPtrW(anchor.getHWND(), -24, c.cast(callback, P))
            with (gdi.audit_gdi() as (created, deleted, errors, _),
                  native_allocations() as (allocated, freed), self.assertRaises(OSError)):
                ckit.Window(show=False)
            self.assertGreater(allocated.value, 0)
            self.assertEqual(allocated.value, freed.value)
            self.assertEqual(len(created), 4)
            self.assertCountEqual(created, deleted)
            self.assertEqual(errors, [])
        finally:
            user.SetClassLongPtrW(anchor.getHWND(), -24, c.cast(original, P))
            anchor.destroy()
        self.assertEqual(messages, [2, 0x82])
        self.assertFalse(user.IsWindow(handles[0]))
        ckit.Window(show=False).destroy()

    def test_destroy_during_initial_show_is_rejected(self):
        destroyed = []
        user.GetActiveWindow.restype = P
        def activate(active):
            if active:
                hwnd = user.GetActiveWindow()
                destroyed.append(hwnd)
                user.DestroyWindow(hwnd)
        with self.assertRaises(RuntimeError):
            ckit.Window(show=True, activate_handler=activate)
        self.assertEqual(len(destroyed), 1)
        self.assertFalse(user.IsWindow(destroyed[0]))
        ckit.Window(show=False).destroy()

    def test_hwnd_retains_wrapper_until_os_destroy(self):
        class Window(ckit.Window):
            pass
        window = Window(show=False)
        hwnd = window.getHWND()
        ref = weakref.ref(window)
        del window
        gc.collect()
        self.assertIsNotNone(ref())
        self.assertTrue(user.DestroyWindow(hwnd))
        self.assertIsNone(ref())

    def test_clear_plane_finalizers_can_reenter_without_reusing_owners(self):
        for kind in (ckit.TextPlane, ckit.ImagePlane):
            for action in ("clear", "destroy", "other_plane", "create"):
                with self.subTest(kind=kind.__name__, action=action):
                    events, created = [], []
                    window = ckit.Window(show=False)
                    hwnd = window.getHWND()
                    other = kind(window, (0, 0), (10, 10), 0)

                    class Replacement(kind):
                        pass

                    class Plane(kind):
                        def __del__(self, action=action, events=events, window=window,
                                    other=other, created=created, replacement=Replacement):
                            try:
                                self.destroy()
                            except ValueError:
                                events.append("invalidated")
                            if action == "clear":
                                window.clear()
                            elif action == "destroy":
                                window.destroy()
                            elif action == "other_plane":
                                other.destroy()
                            else:
                                new = replacement(window, (0, 0), (10, 10), 0)
                                created.append(weakref.ref(new))
                            events.append("returned")

                    plane = Plane(window, (0, 0), (10, 10), 1)
                    reference = weakref.ref(plane)
                    del plane
                    with redirect_stderr(io.StringIO()) as errors:
                        self.assertIsNone(window.clear())
                    self.assertEqual(errors.getvalue(), "")
                    self.assertEqual(events, ["invalidated", "returned"])
                    self.assertIsNone(reference())
                    self.assertTrue(all(ref() is None for ref in created))
                    with self.assertRaises(ValueError):
                        other.destroy()
                    if action == "destroy":
                        self.assert_dead(window, hwnd)
                    else:
                        replacement = kind(window, (0, 0), (10, 10), 0)
                        self.assertIsNone(replacement.destroy())
                        self.assertIsNone(window.clear())
                        window.destroy()

    def test_clear_and_tray_reentry_balance_native_and_gui_resources(self):
        from test_native_gdi import gdi_count

        class Plane(ckit.TextPlane):
            def __del__(self):
                window.destroy()

        class Items:
            def __len__(self):
                tray.destroy()
                return 0
            def __getitem__(self, index):
                raise IndexError

        # Warm up the OS and STL paths before measuring repeated destruction.
        with tray_popup_fixture():
            tray = ckit.TaskTrayIcon()
            tray.destroy()
            window = ckit.Window(show=False)
            window.destroy()
            gc.collect()
            process = kernel.GetCurrentProcess()
            before = (gdi_count(), fixture.user.GetGuiResources(process, 1))
            with native_allocations() as (allocated, freed):
                for _ in range(20):
                    window = ckit.Window(show=False)
                    plane = Plane(window, (0, 0), (10, 10), 0)
                    reference = weakref.ref(plane)
                    del plane
                    window.clear()
                    self.assertIsNone(reference())
                    self.assertEqual(gdi_count(), before[0], "Window destruction")
                    tray = ckit.TaskTrayIcon()
                    with self.assertRaises(ValueError):
                        tray.popupMenu(0, 0, Items())
                    self.assertEqual(gdi_count(), before[0], "TaskTrayIcon destruction")
                gc.collect()
            self.assertEqual(allocated.value, freed.value)
            self.assertEqual((gdi_count(), fixture.user.GetGuiResources(process, 1)), before)

    def test_tray_popup_sequence_destruction_stops_before_tracking(self):
        for stage in ("length", "item", "item_finalizer"):
            with self.subTest(stage=stage), tray_popup_fixture() as (handles, tracked, notifications):
                events = []
                tray = ckit.TaskTrayIcon()
                callback = lambda info: None

                class Item(tuple):
                    def __del__(self, stage=stage, tray=tray, events=events):
                        if stage == "item_finalizer":
                            tray.destroy()
                            events.append(stage)

                class Items:
                    def __len__(self, stage=stage, tray=tray, events=events):
                        if stage == "length":
                            tray.destroy()
                            events.append(stage)
                        return 1

                    def __getitem__(self, index, stage=stage, tray=tray, events=events,
                                    callback=callback, item_type=Item):
                        if stage == "item":
                            tray.destroy()
                            events.append(stage)
                        return item_type(("Entry", callback))

                references = sys.getrefcount(callback)
                with self.assertRaisesRegex(ValueError, "already destroyed"):
                    tray.popupMenu(0, 0, Items())
                self.assertEqual(events, [stage])
                self.assertEqual(tracked, [])
                self.assertFalse(user.IsWindow(handles[0]))
                self.assertEqual(notifications, [0, 2])
                self.assertEqual(sys.getrefcount(callback), references)
                with self.assertRaises(ValueError):
                    tray.destroy()

    def test_tray_popup_reentry_preserves_displayed_command(self):
        for stage in ("coordinate", "length", "item", "item_finalizer", "old_command", "command_info", "command"):
            with self.subTest(stage=stage):
                events, labels = [], []
                def track(menu, flags, x, y, reserved, owner, rect, labels=labels):
                    label = c.create_unicode_buffer(64)
                    fixture.user.GetMenuStringW(menu, 0, label, len(label), 0x400)
                    labels.append(label.value)
                    ident = fixture.user.GetMenuItemID(menu, 0)
                    fixture.user.SendMessageW(owner, 0x111, ident, 0)
                    return 1

                with tray_popup_fixture(track) as (_, tracked, _):
                    tray = ckit.TaskTrayIcon()
                    def inner(info, events=events):
                        events.append("Inner")
                    def reenter(tray=tray, inner=inner, events=events):
                        with self.assertRaisesRegex(ValueError, "popupMenu is already active"):
                            tray.popupMenu(0, 0, [("Inner", inner)])
                        events.append("rejected")
                    def outer(info, stage=stage, reenter=reenter, events=events):
                        if stage == "command":
                            reenter()
                        events.append("Outer")
                    def info(stage=stage, reenter=reenter):
                        if stage == "command_info":
                            reenter()
                        return ckit.CommandInfo()
                    class Coordinate:
                        def __index__(self, reenter=reenter):
                            reenter()
                            return 0
                    class Item(tuple):
                        def __del__(self, stage=stage, reenter=reenter):
                            if stage == "item_finalizer":
                                reenter()
                    class Items:
                        def __len__(self, stage=stage, reenter=reenter):
                            if stage == "length":
                                reenter()
                            return 1
                        def __getitem__(self, index, stage=stage, reenter=reenter, item_type=Item, outer=outer):
                            if stage == "item":
                                reenter()
                            return item_type(("Outer", outer))
                    class OldCommand:
                        def __call__(self, info):
                            pass
                        def __del__(self, reenter=reenter):
                            reenter()

                    ckit.registerCommandInfoConstructor(info)
                    try:
                        if stage == "old_command":
                            tray.popupMenu(0, 0, [("Old", OldCommand())])
                            labels.clear()
                            tracked.clear()
                        self.assertIsNone(tray.popupMenu(Coordinate() if stage == "coordinate" else 0, 0, Items()))
                        self.assertEqual(events, ["rejected", "Outer"])
                        self.assertEqual(labels, ["Outer"])
                        self.assertEqual(len(tracked), 1)
                        # Normal completion unlocks this same native instance.
                        self.assertIsNone(tray.popupMenu(0, 0, [("Again", lambda info: None)]))
                    finally:
                        ckit.registerCommandInfoConstructor(ckit.CommandInfo)
                        tray.destroy()

    def test_tray_popup_reentry_errors_cancel_and_other_icon(self):
        with tray_popup_fixture() as (_, tracked, _):
            tray, other = ckit.TaskTrayIcon(), ckit.TaskTrayIcon()
            class Items:
                def __len__(self):
                    self_test.assertIsNone(other.popupMenu(0, 0, [("Other", lambda info: None)]))
                    tray.popupMenu(0, 0, [])
                    return 0
                def __getitem__(self, index):
                    raise IndexError
            self_test = self
            try:
                with self.assertRaisesRegex(ValueError, "popupMenu is already active"):
                    tray.popupMenu(0, 0, Items())
                for args, exception in (((object(), 0, []), TypeError),
                                        ((0, 0, [("Bad", None, object())]), TypeError),
                                        ((0, 0, [None]), SystemError)):
                    with self.assertRaises(exception):
                        tray.popupMenu(*args)
                    self.assertIsNone(tray.popupMenu(0, 0, []))
                self.assertEqual(len(tracked), 4)  # Other icon plus three cancellations.
                def fail_menu():
                    kernel.SetLastError(5)
                with (replace_import("CreatePopupMenu", CALL(P)(fail_menu), native),
                      self.assertRaises(OSError) as error):
                    tray.popupMenu(0, 0, [])
                self.assertEqual(error.exception.winerror, 5)
                self.assertIsNone(tray.popupMenu(0, 0, []))
            finally:
                other.destroy()
                tray.destroy()

    def test_tray_live_init_rejected_without_changing_resources(self):
        handler = lambda *args: None
        callback = lambda info: None
        references = sys.getrefcount(handler), sys.getrefcount(callback)
        with tray_popup_fixture() as (handles, tracked, notifications):
            tray = ckit.TaskTrayIcon(title="Original", lbuttondown_handler=handler)
            hwnd = handles[0]
            try:
                tray.popupMenu(0, 0, [("Original", callback)])
                original_refs = sys.getrefcount(handler), sys.getrefcount(callback)
                for options in ({}, {"title": "Replacement", "lbuttondown_handler": object()}, {"title": object()}):
                    with self.assertRaisesRegex(ValueError, "already initialized"):
                        ckit.TaskTrayIcon.__init__(tray, **options)
                    self.assertEqual(handles, [hwnd])
                    self.assertEqual(notifications, [0])
                    self.assertTrue(user.IsWindow(hwnd))
                    self.assertEqual((sys.getrefcount(handler), sys.getrefcount(callback)), original_refs)
                self.assertIsNone(tray.popupMenu(0, 0, [("Still usable", callback)]))
            finally:
                tray.destroy()
            self.assertFalse(user.IsWindow(hwnd))
            self.assertEqual((sys.getrefcount(handler), sys.getrefcount(callback)), references)
            ckit.TaskTrayIcon.__init__(tray, title="New", lbuttondown_handler=handler)
            self.assertIsNone(tray.popupMenu(0, 0, []))
            self.assertEqual(tracked, [hwnd, hwnd, handles[1]])
            tray.destroy()
            self.assertFalse(user.IsWindow(handles[1]))
            self.assertEqual(notifications, [0, 2, 0, 2])

    def test_tray_init_failures_release_resources_and_retry(self):
        handler = lambda *args: None
        references = sys.getrefcount(handler)
        with tray_popup_fixture() as (handles, _, notifications):
            for failure in ("title", "create", "property", "after_create", "show"):
                with self.subTest(failure=failure):
                    tray = ckit.TaskTrayIcon.__new__(ckit.TaskTrayIcon)
                    with ExitStack() as stack:
                        if failure == "create":
                            stack.enter_context(creation_failure(1400))
                        elif failure == "property":
                            def fail_property(*args):
                                kernel.SetLastError(5)
                                return 0
                            stack.enter_context(replace_import("SetPropW", CALL(w.BOOL, P, w.LPCWSTR, P)(fail_property), native))
                        elif failure == "after_create":
                            real = CREATE(P.from_address(imports(native)["CreateWindowExW"]).value)
                            def fail_after_create(*args, real=real):
                                hwnd = real(*args)
                                self.assertTrue(hwnd)
                                self.assertTrue(user.DestroyWindow(hwnd))
                                kernel.SetLastError(1400)
                            stack.enter_context(replace_import("CreateWindowExW", CREATE(fail_after_create), native))
                        elif failure == "show":
                            def destroy_on_show(hwnd, show):
                                user.DestroyWindow(hwnd)
                                return 0
                            stack.enter_context(replace_import("ShowWindow", CALL(w.BOOL, P, c.c_int)(destroy_on_show), native))
                        exception = TypeError if failure == "title" else ValueError if failure == "show" else OSError
                        with self.assertRaises(exception):
                            ckit.TaskTrayIcon.__init__(tray, title=object() if failure == "title" else "Valid",
                                                      lbuttondown_handler=handler)
                    self.assertEqual(sys.getrefcount(handler), references)
                    with self.assertRaises(ValueError):
                        tray.destroy()
                    ckit.TaskTrayIcon.__init__(tray, lbuttondown_handler=handler)
                    tray.popupMenu(0, 0, [])
                    tray.destroy()
                    self.assertFalse(user.IsWindow(handles[-1]))
            self.assertEqual(notifications.count(0), 6)
            self.assertTrue(all(not user.IsWindow(hwnd) for hwnd in handles))

    def test_tray_real_popup_reentry_keeps_outer_selection(self):
        menus, events, errors = [], [], []
        user.CreatePopupMenu.restype = P
        user.EndMenu.argtypes = ()
        user.EndMenu.restype = w.BOOL
        timer_proc = CALL(None, P, w.UINT, c.c_size_t, w.DWORD)
        user.SetTimer.argtypes = (P, c.c_size_t, w.UINT, timer_proc)
        user.SetTimer.restype = c.c_size_t
        user.KillTimer.argtypes = (P, c.c_size_t)
        user.KillTimer.restype = w.BOOL
        def create():
            menu = user.CreatePopupMenu()
            menus.append(menu)
            return menu
        def select(hwnd, message, timer, ticks):
            try:
                with self.assertRaisesRegex(ValueError, "popupMenu is already active"):
                    tray.popupMenu(0, 0, [("Inner", lambda info: events.append("Inner"))])
                with self.assertRaisesRegex(ValueError, "already initialized"):
                    ckit.TaskTrayIcon.__init__(tray)
                label = c.create_unicode_buffer(64)
                fixture.user.GetMenuStringW(menus[-1], 0, label, len(label), 0x400)
                self.assertEqual(label.value, "Outer")
                # Drive selection through the actual tracking loop's owner queue.
                ident = fixture.user.GetMenuItemID(menus[-1], 0)
                fixture.user.SendMessageW(hwnd, 0x111, ident, 0)
            except AssertionError as error:
                errors.append(error)
            finally:
                user.EndMenu()
        callback = timer_proc(select)
        with (tray_popup_fixture(real_tracking=True) as (handles, _, _),
              replace_import("CreatePopupMenu", CALL(P)(create), native)):
            tray = ckit.TaskTrayIcon()
            try:
                for _ in range(3):
                    timer = user.SetTimer(handles[0], 0x7002, 30, callback)
                    self.assertTrue(timer)
                    try:
                        self.assertIsNone(tray.popupMenu(0, 0, [("Outer", lambda info: events.append("Outer"))]))
                    finally:
                        user.KillTimer(handles[0], timer)
                self.assertEqual(errors, [])
                self.assertEqual(events, ["Outer"] * 3)
            finally:
                tray.destroy()

    def test_tray_repeated_init_popup_and_destroy_balance_resources(self):
        from test_native_gdi import gdi_count

        callback = lambda info: None
        handler = lambda *args: None
        references = sys.getrefcount(callback), sys.getrefcount(handler)
        user.CreateIcon.argtypes = (P, c.c_int, c.c_int, w.BYTE, w.BYTE, P, P)
        user.CreateIcon.restype = P
        user.DestroyIcon.argtypes = (P,)
        user.DestroyIcon.restype = w.BOOL
        icons, released, menus, destroyed_menus = [], [], [], []
        and_bits, xor_bits = c.create_string_buffer(32), c.create_string_buffer(16 * 16 * 4)
        def load(*args):
            # python.exe has no application icon resource; create a real owned icon.
            icon = user.CreateIcon(None, 16, 16, 1, 32, and_bits, xor_bits)
            icons.append(icon)
            return icon
        def release(icon):
            released.append(icon)
            return user.DestroyIcon(icon)
        user.CreatePopupMenu.restype = P
        user.DestroyMenu.argtypes = (P,)
        user.DestroyMenu.restype = w.BOOL
        def create_menu():
            menu = user.CreatePopupMenu()
            menus.append(menu)
            return menu
        def destroy_menu(menu):
            destroyed_menus.append(menu)
            return user.DestroyMenu(menu)
        with (tray_popup_fixture() as (handles, _, notifications),
              replace_import("LoadImageW", CALL(P, P, P, w.UINT, c.c_int, c.c_int, w.UINT)(load), native),
              replace_import("DestroyIcon", CALL(w.BOOL, P)(release), native),
              replace_import("CreatePopupMenu", CALL(P)(create_menu), native),
              replace_import("DestroyMenu", CALL(w.BOOL, P)(destroy_menu), native)):
            tray = ckit.TaskTrayIcon()
            tray.popupMenu(0, 0, [("Warm", callback)])
            tray.destroy()
            gc.collect()
            before = gdi_count(), fixture.user.GetGuiResources(kernel.GetCurrentProcess(), 1)
            with native_allocations() as (allocated, freed):
                for _ in range(40):
                    ckit.TaskTrayIcon.__init__(tray, lbuttondown_handler=handler)
                    with self.assertRaises(ValueError):
                        ckit.TaskTrayIcon.__init__(tray)
                    for _ in range(3):
                        tray.popupMenu(0, 0, [("Entry", callback)])
                    tray.destroy()
                    self.assertFalse(user.IsWindow(handles[-1]))
                    self.assertEqual((sys.getrefcount(callback), sys.getrefcount(handler)), references)
                gc.collect()
            self.assertEqual(allocated.value, freed.value)
            self.assertEqual((gdi_count(), fixture.user.GetGuiResources(kernel.GetCurrentProcess(), 1)), before)
            self.assertEqual(icons, released)
            self.assertTrue(all(icons))
            self.assertEqual(menus, destroyed_menus)
            self.assertEqual(notifications, [0, 2] * 41)

    def test_tray_popup_sequence_errors_preserve_exception_and_recover(self):
        for stage in ("length", "item"):
            with self.subTest(stage=stage), tray_popup_fixture() as (_, tracked, _):
                tray = ckit.TaskTrayIcon()
                class Items:
                    def __len__(self, stage=stage):
                        if stage == "length":
                            raise RuntimeError("sequence sentinel")
                        return 1
                    def __getitem__(self, index):
                        raise RuntimeError("sequence sentinel")
                try:
                    with self.assertRaisesRegex(RuntimeError, "sequence sentinel"):
                        tray.popupMenu(0, 0, Items())
                    self.assertEqual(tracked, [])
                    for _ in range(3):
                        self.assertIsNone(tray.popupMenu(x=0, y=0, items=[("Entry", lambda info: None), ("-", None)]))
                    self.assertEqual(len(tracked), 3)
                finally:
                    tray.destroy()

    def test_tray_real_popup_layout_cancel_and_repeat(self):
        menus, observed = [], []
        user.CreatePopupMenu.argtypes = ()
        user.CreatePopupMenu.restype = P
        user.GetMenuItemRect.argtypes = (P, P, w.UINT, c.POINTER(w.RECT))
        user.GetMenuItemRect.restype = w.BOOL
        user.EndMenu.argtypes = ()
        user.EndMenu.restype = w.BOOL
        timer_proc = CALL(None, P, w.UINT, c.c_size_t, w.DWORD)
        user.SetTimer.argtypes = (P, c.c_size_t, w.UINT, timer_proc)
        user.SetTimer.restype = c.c_size_t
        user.KillTimer.argtypes = (P, c.c_size_t)
        user.KillTimer.restype = w.BOOL

        def create():
            menu = user.CreatePopupMenu()
            menus.append(menu)
            return menu

        def cancel(hwnd, message, timer, ticks):
            rect = w.RECT()
            result = user.GetMenuItemRect(hwnd, menus[-1], 0, c.byref(rect))
            observed.append((bool(result), rect.right > rect.left, rect.bottom > rect.top))
            user.EndMenu()

        callback = timer_proc(cancel)
        with (tray_popup_fixture(real_tracking=True) as (handles, _, _),
              replace_import("CreatePopupMenu", CALL(P)(create), native)):
            tray = ckit.TaskTrayIcon()
            try:
                for _ in range(3):
                    timer = user.SetTimer(handles[0], 0x7001, 30, callback)
                    self.assertTrue(timer)
                    try:
                        self.assertIsNone(tray.popupMenu(0, 0, [("Entry 日本語", lambda info: None)]))
                    finally:
                        user.KillTimer(handles[0], timer)
                self.assertEqual(observed, [(True, True, True)] * 3)
            finally:
                tray.destroy()

    def test_tray_old_command_finalizer_can_destroy_during_menu_clear(self):
        with tray_popup_fixture() as (handles, tracked, notifications):
            tray = ckit.TaskTrayIcon()
            events = []
            class Command:
                def __call__(self, info):
                    pass
                def __del__(self):
                    tray.destroy()
                    events.append("destroyed")
            tray.popupMenu(0, 0, [("Old", Command())])
            with self.assertRaises(ValueError):
                tray.popupMenu(0, 0, [])
            self.assertEqual(events, ["destroyed"])
            self.assertEqual(len(tracked), 1)
            self.assertEqual(notifications, [0, 2])
            self.assertFalse(user.IsWindow(handles[0]))

    def test_tray_popup_destroy_and_reinitialize_keeps_new_instance(self):
        with tray_popup_fixture() as (handles, tracked, notifications):
            tray = ckit.TaskTrayIcon()
            class Items:
                def __len__(self):
                    tray.destroy()
                    ckit.TaskTrayIcon.__init__(tray)
                    return 0
                def __getitem__(self, index):
                    raise IndexError
            with self.assertRaises(ValueError):
                tray.popupMenu(0, 0, Items())
            self.assertFalse(user.IsWindow(handles[0]))
            self.assertTrue(user.IsWindow(handles[1]))
            self.assertIsNone(tray.popupMenu(0, 0, []))
            self.assertEqual(tracked, [handles[1]])
            tray.destroy()
            self.assertEqual(notifications, [0, 2, 0, 2])

    def test_tray_popup_command_and_command_info_can_destroy(self):
        for stage in ("command", "info"):
            events = []
            def track(menu, flags, x, y, reserved, owner, rect):
                fixture.user.SendMessageW(owner, 0x111, 1280, 0)
                return 1
            with self.subTest(stage=stage), tray_popup_fixture(track) as (handles, tracked, notifications):
                tray = ckit.TaskTrayIcon()
                def command(info, events=events, tray=tray):
                    events.append("command")
                    tray.destroy()
                def info(events=events, tray=tray):
                    events.append("info")
                    tray.destroy()
                    return ckit.CommandInfo()
                ckit.registerCommandInfoConstructor(info if stage == "info" else ckit.CommandInfo)
                try:
                    with redirect_stderr(io.StringIO()) as errors:
                        self.assertIsNone(tray.popupMenu(0, 0, [("Destroy", command)]))
                    self.assertEqual(errors.getvalue(), "")
                    self.assertEqual(events, [stage])
                    self.assertEqual(len(tracked), 1)
                    self.assertEqual(notifications, [0, 2])
                    self.assertFalse(user.IsWindow(handles[0]))
                finally:
                    ckit.registerCommandInfoConstructor(ckit.CommandInfo)

    def test_callback_finalizer_observes_invalidated_wrapper(self):
        def check(os_destroy):
            observed = []
            class Handler:
                def __call__(self, *args):
                    pass

                def __del__(self):
                    for operation in (window.getHWND, window.destroy):
                        try:
                            operation()
                        except ValueError:
                            observed.append("invalidated")
            window = ckit.Window(show=False, keydown_handler=Handler())
            if os_destroy:
                self.assertTrue(user.DestroyWindow(window.getHWND()))
            else:
                window.destroy()
            self.assertEqual(observed, ["invalidated", "invalidated"])
        check(False)
        check(True)

    def test_os_destroy_invalidates_window_and_owned_planes(self):
        parent = ckit.Window(show=False)
        child = ckit.Window(show=False, parent_window=parent)
        plane = ckit.TextPlane(child, (0, 0), (10, 10), 0)
        parent_hwnd, child_hwnd = parent.getHWND(), child.getHWND()
        self.assertTrue(user.DestroyWindow(parent_hwnd))
        self.assert_dead(parent, parent_hwnd)
        self.assert_dead(child, child_hwnd)
        with self.assertRaises(ValueError):
            plane.destroy()

    def test_destroy_failure_keeps_wrapper_callbacks_and_retry(self):
        received = []
        handler = lambda *args: received.append(args)
        baseline = sys.getrefcount(handler)
        window = ckit.Window(show=False, keydown_handler=handler)
        hwnd = window.getHWND()
        def fail(hwnd):
            kernel.SetLastError(5)
            return 0
        try:
            with (replace_import("DestroyWindow", CALL(w.BOOL, P)(fail), native),
                  self.assertRaises(OSError) as error):
                window.destroy()
            self.assertEqual(error.exception.winerror, 5)
            self.assertEqual(window.getHWND(), hwnd)
            self.assertTrue(user.IsWindow(hwnd))
            self.assertEqual(sys.getrefcount(handler), baseline + 1)
            fixture.user.SendMessageW(hwnd, 0x100, 65, 0)
            self.assertEqual(received, [(65, 0)])
        finally:
            window.destroy()
        self.assertEqual(sys.getrefcount(handler), baseline)
        self.assert_dead(window, hwnd)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(90, exit=True)
    unittest.main(verbosity=2)
