"""Exercise real pyautocore dispatch, lifetime and private-desktop registration.

Reuse the native Shell test's IAT fixture and private, noninteractive desktop.
The registration test installs/removes real hooks only on that private desktop.
Dispatch tests call the native procedures directly. No physical input is sent.
"""
import ctypes as c
import faulthandler
import gc
import io
import unittest
import weakref
from contextlib import ExitStack, redirect_stderr
from ctypes import wintypes as w

from test_native_shell import CALL, DESKTOP, P, pyautocore, replace_import, user


class KeyboardEvent(c.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD),
                ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]


class MouseEvent(c.Structure):
    _fields_ = [("pt", w.POINT), ("mouseData", w.DWORD),
                ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]


class NativeHookTests(unittest.TestCase):
    def setUp(self):
        # Release prior callback traceback cycles before creating the singleton Hook.
        gc.collect()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.procs = {}
        self.forwarded = []
        self.unhooked = []

        def register(kind, proc, module, thread):
            self.procs[kind] = c.PYFUNCTYPE(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)(proc)
            return kind

        def forward(handle, code, message, event):
            self.forwarded.append((handle, code, message, event))
            return 0x1234

        def unhook(handle):
            self.unhooked.append(handle)
            return 1

        for name, callback in (
            ("SetWindowsHookExW", CALL(P, c.c_int, P, P, w.DWORD)(register)),
            ("CallNextHookEx", CALL(c.c_ssize_t, P, c.c_int, w.WPARAM, w.LPARAM)(forward)),
            ("UnhookWindowsHookEx", CALL(w.BOOL, P)(unhook)),
        ):
            self.stack.enter_context(replace_import(name, callback, module=pyautocore))
        self.hook = pyautocore.Hook()
        self.addCleanup(self.destroy_hook)

    def destroy_hook(self):
        self.hook.destroy()

    def check_returns(self, kind, routes):
        cases = ((None, None), (0, None), (1, None), (-7, None),
                 (2**31 - 1, None), (-2**31, None),
                 ("invalid", TypeError), (1.5, TypeError),
                 (2**31, OverflowError), (-2**31 - 1, OverflowError),
                 (2**100, OverflowError), (-2**100, OverflowError),
                 (RuntimeError("callback failed"), RuntimeError))
        for name, message, event, expected_args in routes:
            for value, error_type in cases:
                with self.subTest(callback=name, message=hex(message), value=value):
                    calls = []

                    def callback(*args, calls=calls, value=value):
                        calls.append(args)
                        if isinstance(value, Exception):
                            raise value
                        return value

                    setattr(self.hook, name, callback)
                    self.forwarded.clear()
                    errors = io.StringIO()
                    with redirect_stderr(errors):
                        result = self.procs[kind](0, message, c.addressof(event))
                    self.assertEqual(calls, [expected_args])
                    suppress = error_type is None and value is not None and value != 0
                    self.assertEqual(result, value if suppress else 0x1234)
                    self.assertEqual(self.forwarded, [] if suppress else [
                        (kind, 0, message, c.addressof(event))])
                    if error_type:
                        self.assertIn(error_type.__name__ + ":", errors.getvalue())
                        # The next native entry must work after the printed exception.
                        setattr(self.hook, name, lambda *args: 0)
                        self.forwarded.clear()
                        with redirect_stderr(errors):
                            self.assertEqual(self.procs[kind](0, message, c.addressof(event)), 0x1234)
                        self.assertEqual(len(self.forwarded), 1)
                    else:
                        self.assertEqual(errors.getvalue(), "")
                    setattr(self.hook, name, None)

    def test_keyboard_down_up_and_system_keys(self):
        event = KeyboardEvent(65, 30, 0, 1, 0)
        self.check_returns(13, [(name, message, event, (65, 30)) for name, message in (
            ("keydown", 0x100), ("keyup", 0x101),
            ("keydown", 0x104), ("keyup", 0x105))])

    def test_mouse_buttons_down_up_and_double_click(self):
        event = MouseEvent(w.POINT(-10, 20), 0, 0, 1, 0)
        self.check_returns(14, [(name, base + offset, event, (-10, 20, vk))
            for base, vk in ((0x201, 1), (0x204, 2), (0x207, 4))
            for offset, name in enumerate(("mousedown", "mouseup", "mousedblclk"))])

    def test_mouse_move(self):
        self.check_returns(14, [("mousemove", 0x200,
            MouseEvent(w.POINT(-1920, -300), 0, 0, 1, 0), (-1920, -300))])

    def test_move_filter_inactive_and_negative_code(self):
        calls = []
        self.hook.mousemove = lambda *args: calls.append(args)
        proc = self.procs[14]
        event = MouseEvent(w.POINT(-10, 20), 0, 1, 1,
                           c.WinDLL(pyautocore.__file__)._handle)
        self.assertEqual(proc(0, 0x200, c.addressof(event)), 0x1234)
        self.assertEqual(calls, [])
        event.extra = 0  # Input injected by another source is still delivered.
        self.assertEqual(proc(0, 0x200, c.addressof(event)), 0x1234)
        self.assertEqual(calls, [(-10, 20)])
        calls.clear()
        self.assertEqual(proc(-1, 0x200, 0), 0x1234)
        self.hook.destroy()
        self.assertEqual(proc(0, 0x200, c.addressof(event)), 0x1234)
        self.assertEqual(calls, [])

    def test_destroy_inside_callback(self):
        key = KeyboardEvent(65, 30, 0, 1, 0)
        mouse = MouseEvent(w.POINT(10, 20), 0, 0, 1, 0)
        routes = (("keydown", 13, 0x100, key), ("keyup", 13, 0x101, key),
                  ("mousedown", 14, 0x201, mouse), ("mouseup", 14, 0x202, mouse),
                  ("mousedblclk", 14, 0x203, mouse), ("mousemove", 14, 0x200, mouse),
                  ("mousewheel", 14, 0x20a, mouse), ("mousehorizontalwheel", 14, 0x20e, mouse),
                  ("clipboard", None, 0x31d, None))
        for name, kind, message, event in routes:
            calls = []
            class Callback:
                def __call__(callback, *args, calls=calls):
                    self.hook.destroy()
                    calls.append("returned")
                    return 0

                def __del__(callback, calls=calls):
                    calls.append("released")

            with self.subTest(name=name):
                setattr(self.hook, name, Callback())
                if kind:
                    self.assertEqual(self.procs[kind](0, message, c.addressof(event)), 0x1234)
                else:
                    hwnd = pyautocore.Window.find("pyauto", "pyauto").getHWND()
                    user.SendMessageW.argtypes = (P, w.UINT, w.WPARAM, w.LPARAM)
                    self.assertEqual(user.SendMessageW(hwnd, message, 0, 0), 0)
                self.assertEqual(calls, ["returned", "released"])
                self.hook = pyautocore.Hook()

    def test_destroy_releases_all_callbacks_and_receiver(self):
        names = ("keydown", "keyup", "mousedown", "mouseup", "mousedblclk",
                 "mousemove", "mousewheel", "mousehorizontalwheel", "clipboard")
        refs, listeners = [], []
        callback = lambda *args: None
        for name in names:
            value = type("Callback", (), {"__call__": callback})()
            refs.append(weakref.ref(value))
            setattr(self.hook, name, value)
        del value
        window = pyautocore.Window.find("pyauto", "pyauto").getHWND()
        user.IsWindow.argtypes = (P,)
        def remove(hwnd):
            listeners.append(hwnd)
            return original_remove(hwnd)
        with replace_import("RemoveClipboardFormatListener", CALL(w.BOOL, P)(remove), module=pyautocore) as address:
            original_remove = CALL(w.BOOL, P)(address)
            self.hook.reset()
            self.hook.destroy()
            self.hook.destroy()
        self.assertEqual(self.unhooked, [13, 14, 13, 14])
        self.assertEqual(listeners, [window, window])
        self.assertFalse(user.IsWindow(window))
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertTrue(all(getattr(self.hook, name) is None for name in names))
        with self.assertRaises(ValueError):
            self.hook.reset()
        for name in names:
            with self.subTest(name=name), self.assertRaises(ValueError):
                setattr(self.hook, name, callback)

    def test_old_owner_and_reentrant_release_do_not_stop_replacement(self):
        old, events, replacements = self.hook, [], []

        class Callback:
            def __call__(callback, *args):
                return None

            def __del__(callback):
                self.hook.destroy()
                events.append((self.hook.keydown, self.hook.mousemove))
                replacement = pyautocore.Hook()
                replacements.append(replacement)
                replacement.mousemove = lambda x, y: None

        old.keydown = Callback()
        old.mousemove = lambda x, y: None
        old.destroy()
        self.hook = replacements[0]
        self.assertEqual(events, [(None, None)])
        count = len(self.unhooked)
        old.destroy()
        with self.assertRaises(ValueError):
            old.reset()
        with self.assertRaises(ValueError):
            old.mousemove = None
        del old
        gc.collect()
        self.assertEqual(len(self.unhooked), count)
        self.hook.reset()
        self.assertEqual(self.unhooked[count:], [14])

    def test_second_hook_and_reinitialization_leave_owner_intact(self):
        self.hook.mousemove = lambda x, y: None
        with self.assertRaises(ValueError):
            pyautocore.Hook()
        with self.assertRaises(ValueError):
            self.hook.__init__()
        self.assertEqual(self.unhooked, [])
        self.hook.reset()
        self.assertEqual(self.unhooked, [14])

    def test_replacing_callback_can_destroy_owner(self):
        class Callback:
            def __call__(callback, *args):
                return None

            def __del__(callback):
                self.hook.destroy()

        self.hook.mousemove = Callback()
        self.hook.mousemove = lambda x, y: None
        self.assertIsNone(self.hook.mousemove)
        self.assertEqual(self.unhooked, [14])

    def test_failed_clipboard_removal_does_not_poison_next_owner(self):
        self.hook.clipboard = lambda: None
        with replace_import("RemoveClipboardFormatListener", CALL(w.BOOL, P)(lambda hwnd: 0), module=pyautocore):
            self.hook.destroy()
        added = []
        with replace_import("AddClipboardFormatListener", CALL(w.BOOL, P)(
                lambda hwnd: added.append(hwnd) or 1), module=pyautocore):
            self.hook = pyautocore.Hook()
            self.hook.clipboard = lambda: None
            self.assertEqual(len(added), 1)
            # No real registration was made by this double.
            with replace_import("RemoveClipboardFormatListener", CALL(w.BOOL, P)(lambda hwnd: 1), module=pyautocore):
                self.hook.destroy()

    def test_dealloc_active_owner(self):
        self.hook.destroy()
        hook = pyautocore.Hook()
        hook.keydown = lambda vk, scan: None
        hook.mousemove = lambda x, y: None
        window = pyautocore.Window.find("pyauto", "pyauto").getHWND()
        del hook
        self.assertEqual(self.unhooked, [13, 14])
        self.assertFalse(user.IsWindow(window))

    def test_initialization_failure_does_not_publish_owner(self):
        self.hook.destroy()
        create = CALL(P, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                      c.c_int, c.c_int, c.c_int, c.c_int, P, P, P, P)
        def fail(*args):
            c.windll.kernel32.SetLastError(5)
            return 0
        with replace_import("CreateWindowExW", create(fail), module=pyautocore), self.assertRaises(OSError):
            pyautocore.Hook()
        with replace_import("RegisterClassExW", CALL(w.WORD, P)(fail), module=pyautocore), self.assertRaises(OSError):
            pyautocore.Hook()
        self.hook = pyautocore.Hook()
        self.hook.mousemove = lambda x, y: None
        self.assertEqual(self.unhooked, [])

    def test_vertical_and_horizontal_wheels_both_directions(self):
        self.check_returns(14, [(name, message,
            MouseEvent(w.POINT(-10, 20), (delta & 0xffff) << 16, 0, 1, 0),
            (-10, 20, delta / 120))
            for name, message in (("mousewheel", 0x20a), ("mousehorizontalwheel", 0x20e))
            for delta in (120, -120)])


class NativeHookRegistrationTests(unittest.TestCase):
    def test_real_registration_and_teardown_on_private_desktop(self):
        self.assertIsNotNone(DESKTOP, "real hooks require the private desktop")
        registered, removed, listeners = [], [], []
        with ExitStack() as stack:
            def register(kind, proc, module, thread):
                handle = original_register(kind, proc, module, thread)
                registered.append((kind, handle))
                return handle
            def unhook(handle):
                result = original_unhook(handle)
                removed.append((handle, result))
                return result
            def listen(hwnd):
                result = original_listen(hwnd)
                listeners.append((hwnd, result))
                return result
            original_register = CALL(P, c.c_int, P, P, w.DWORD)(stack.enter_context(
                replace_import("SetWindowsHookExW", CALL(P, c.c_int, P, P, w.DWORD)(register), module=pyautocore)))
            original_unhook = CALL(w.BOOL, P)(stack.enter_context(
                replace_import("UnhookWindowsHookEx", CALL(w.BOOL, P)(unhook), module=pyautocore)))
            original_listen = CALL(w.BOOL, P)(stack.enter_context(
                replace_import("RemoveClipboardFormatListener", CALL(w.BOOL, P)(listen), module=pyautocore)))
            hook = pyautocore.Hook()
            try:
                hook.keydown = lambda vk, scan: None
                hook.mousemove = lambda x, y: None
                hook.clipboard = lambda: None
                hook.reset()
            finally:
                hook.destroy()
        self.assertEqual([kind for kind, handle in registered], [13, 14, 13, 14])
        self.assertTrue(all(handle for kind, handle in registered))
        self.assertEqual([handle for handle, result in removed], [handle for kind, handle in registered])
        self.assertTrue(all(result for handle, result in removed))
        self.assertEqual(len(listeners), 2)
        self.assertTrue(all(result for hwnd, result in listeners))


if __name__ == "__main__":
    faulthandler.dump_traceback_later(30, exit=True)
    unittest.main(verbosity=2)
