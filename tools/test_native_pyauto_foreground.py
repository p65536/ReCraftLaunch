"""Exercise real PYD foreground branches with local IAT doubles, never OS activation."""
import ctypes as c
import faulthandler
import itertools
import unittest
from contextlib import ExitStack
from ctypes import wintypes as w

from test_native_pyauto_documentation import InputEvent
from test_native_shell import CALL, P, pyautocore, replace_import


class NativePyautoForegroundTests(unittest.TestCase):
    def check_transition(self, *, force=1, same_thread=False, timeout=0xf1234567,
                         get=True, set_zero=True, restore=True, attach=True,
                         detach=True, foreground=True):
        calls, logs = [], []
        error = [0]
        target, previous = 0x123456789, 0x23456789a

        def result(success):
            error[0] = 0 if success else 5
            return 2 if success else 0  # BOOL success means nonzero, not just TRUE.

        def thread(hwnd, process):
            calls.append(("thread", hwnd, process))
            return 11 if hwnd == previous or same_thread else 22

        def attach_input(first, second, enabled):
            calls.append(("attach", first, second, enabled))
            return result(attach if enabled else detach)

        def parameters(action, unused, value, flags):
            if action == 0x2000:
                calls.append(("get", unused, bool(value), flags))
                # Also write on failure: failed GET must never authorize SET.
                w.DWORD.from_address(value).value = timeout
                return result(get)
            calls.append(("set", action, unused, value or 0, flags))
            return result(set_zero if sum(call[0] == "set" for call in calls) == 1 else restore)

        def activate(hwnd):
            calls.append(("foreground", hwnd))
            return result(foreground)

        def log(options, stream, fmt, locale, arguments):
            logs.append(c.string_at(fmt).decode())
            error[0] = 999  # Logging must not replace the foreground error.
            return 0

        window = pyautocore.Window.fromHWND(target)
        with ExitStack() as stack:
            for name, callback in (
                ("GetForegroundWindow", CALL(P)(lambda: previous)),
                ("GetWindowThreadProcessId", CALL(w.DWORD, P, P)(thread)),
                ("AttachThreadInput", CALL(w.BOOL, w.DWORD, w.DWORD, w.BOOL)(attach_input)),
                ("SystemParametersInfoW", CALL(w.BOOL, w.UINT, w.UINT, P, w.UINT)(parameters)),
                ("SetForegroundWindow", CALL(w.BOOL, P)(activate)),
                ("GetLastError", CALL(w.DWORD)(lambda: error[0])),
                ("__stdio_common_vfprintf", CALL(c.c_int, c.c_uint64, P, P, P, P)(log)),
            ):
                stack.enter_context(replace_import(name, callback, module=pyautocore))
            if foreground:
                self.assertIsNone(window.setForeground(force))
            else:
                with self.assertRaises(OSError) as caught:
                    window.setForeground(force)
                self.assertEqual(caught.exception.winerror, 5)

        expected = [("thread", previous, None), ("thread", target, None)]
        expected_logs = []
        forced = force and not same_thread
        if forced:
            expected += [("attach", 22, 11, 1), ("get", 0, True, 0)]
            if not attach:
                expected_logs.append("AttachThreadInput")
            if get:
                expected.append(("set", 0x2001, 0, 0, 0))
                if not set_zero:
                    expected_logs.append("SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT)")
            else:
                expected_logs.append("SystemParametersInfo(SPI_GETFOREGROUNDLOCKTIMEOUT)")
        expected.append(("foreground", target))
        if not foreground:
            expected_logs.append("SetForegroundWindow")
        if forced:
            if get and set_zero:
                expected.append(("set", 0x2001, 0, timeout, 0))
                if not restore:
                    expected_logs.append("SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT)")
            if attach:
                expected.append(("attach", 22, 11, 0))
                if not detach:
                    expected_logs.append("AttachThreadInput")
        self.assertEqual(calls, expected)
        self.assertEqual(logs, [name + " failed %d\n" for name in expected_logs])

    def test_forced_success_failure_matrix(self):
        for timeout in (0, 0xf1234567):
            for values in itertools.product((False, True), repeat=6):
                options = dict(zip(("get", "set_zero", "restore", "attach", "detach", "foreground"), values))
                with self.subTest(timeout=timeout, **options):
                    self.check_transition(timeout=timeout, **options)

    def test_nonforced_and_same_thread_do_not_change_input_or_timeout(self):
        for force, same_thread, foreground in itertools.product((0, 1), (False, True), (False, True)):
            if force and not same_thread:
                continue
            with self.subTest(force=force, same_thread=same_thread, foreground=foreground):
                self.check_transition(force=force, same_thread=same_thread, foreground=foreground)

    def test_instance_sizes_match_native_layout(self):
        class InputObject(c.Structure):
            _fields_ = [("head", c.c_byte * object.__basicsize__), ("num", c.c_int),
                        ("input", InputEvent * 2)]

        class HookObject(c.Structure):
            _fields_ = [("head", c.c_byte * object.__basicsize__), ("callbacks", P * 9)]

        self.assertEqual(pyautocore.Input.__basicsize__, c.sizeof(InputObject))
        self.assertEqual(pyautocore.Hook.__basicsize__, c.sizeof(HookObject))
        self.assertEqual(pyautocore.Input.__itemsize__, 0)
        self.assertEqual(pyautocore.Hook.__itemsize__, 0)
        self.assertIsInstance(pyautocore.Input(), pyautocore.Input)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(30, exit=True)
    unittest.main(verbosity=2)
