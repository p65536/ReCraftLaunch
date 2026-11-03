"""Reference ownership and NULL paths in the selected, real x64 pyautocore PYD."""
import ctypes as c
import faulthandler
import io
import struct
import sys
import unittest
from contextlib import ExitStack, contextmanager, redirect_stderr
from ctypes import wintypes as w

from test_native_hooks import KeyboardEvent
from test_native_pyauto_documentation import InputEvent
from test_native_shell import (
    CALL,
    P,
    executable_thunk,
    imports,
    replace_import,
    replace_pointer,
    user,
)

import pyauto
from pyauto import pyautocore as native


class GuiThreadInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("flags", w.DWORD),
               *[(name, P) for name in ("active", "focus", "capture", "menu", "move", "caret")],
               ("rect", w.RECT)]


@contextmanager
def caret(hwnd):
    def get_info(thread, pointer):
        info = GuiThreadInfo.from_address(pointer)
        info.caret = hwnd
        info.rect = w.RECT(1, 2, 3, 4)
        return 1
    with replace_import("GetGUIThreadInfo", CALL(w.BOOL, w.DWORD, P)(get_info), module=native):
        yield


@contextmanager
def enumerate_handles(handles):
    results = []
    def enum(callback, data):
        invoke = c.PYFUNCTYPE(w.BOOL, P, w.LPARAM)(callback)
        for hwnd in handles:
            result = invoke(hwnd, data)
            results.append(result)
            if not result:
                return 0
        return 1
    with replace_import("EnumWindows", CALL(w.BOOL, P, w.LPARAM)(enum), module=native):
        yield results


@contextmanager
def memory_error(name):
    # Tail-call the real C API: never enter a ctypes callback with an exception set.
    address = c.cast(c.pythonapi.PyErr_NoMemory, P).value
    with (executable_thunk(b"\x48\xb8" + struct.pack("<Q", address) + b"\xff\xe0") as thunk,
          replace_import(name, thunk, module=native)):
        yield


@contextmanager
def count_calls(address):
    counter = c.c_size_t()
    original = P.from_address(address).value
    code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(counter)) + b"\x48\xff\x00"
            + b"\x48\xb8" + struct.pack("<Q", original) + b"\xff\xe0")
    with executable_thunk(code) as thunk, replace_pointer(address, thunk):
        yield counter


@contextmanager
def window_destructions():
    # Stable-ABI slot lookup, then locate that pointer in the PyTypeObject prefix.
    get_slot = c.pythonapi.PyType_GetSlot
    get_slot.argtypes = (c.py_object, c.c_int)
    get_slot.restype = P
    dealloc = get_slot(pyauto.Window, 52)  # Py_tp_dealloc
    prefix = (P * 8).from_address(id(pyauto.Window))
    offsets = [i * c.sizeof(P) for i, value in enumerate(prefix) if value == dealloc]
    assert len(offsets) == 1
    with count_calls(id(pyauto.Window) + offsets[0]) as counter:
        yield counter


@contextmanager
def input_allocations():
    slots = imports(native)
    with ExitStack() as stack:
        allocated = stack.enter_context(count_calls(slots["malloc"]))
        freed = [stack.enter_context(count_calls(slots[name]))
                 for name in ("free", "_free_dbg") if name in slots]
        yield allocated, freed


class NativePyautoOwnershipTests(unittest.TestCase):
    def test_native_allocation_failures(self):
        with executable_thunk(b"\x31\xc0\xc3") as unavailable, window_destructions() as destroyed:
            with replace_import("malloc", unavailable, module=native):
                with self.assertRaises(MemoryError):
                    pyauto.Window.fromHWND(0x6789abcde)
                self.assertEqual(destroyed.value, 1)
                with self.assertRaises(MemoryError):
                    pyauto.Input.send([pyauto.Key("A")])
            # Failed index insertion must free its wrapper, leaving no cached object.
            with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                pyauto.Window.fromHWND(0x6789abcde)

    def test_from_hwnd_new_reused_none_and_release(self):
        with window_destructions() as destroyed:
            window = pyauto.Window.fromHWND(0x123456789)
            baseline = sys.getrefcount(window)
            for _ in range(300):
                other = pyauto.Window.fromHWND(window.getHWND())
                self.assertIs(other, window)
                self.assertEqual(sys.getrefcount(window), baseline + 1)
                del other
                self.assertIsNone(pyauto.Window.fromHWND(0))
            self.assertEqual(sys.getrefcount(window), baseline)
            del window
            self.assertEqual(destroyed.value, 1)
            # A fresh allocation is required after removal from the non-owning index.
            with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                pyauto.Window.fromHWND(0x123456789)

    def test_caret_repetition_and_build_failure(self):
        window = pyauto.Window.fromHWND(0x23456789a)
        baseline = sys.getrefcount(window)
        for hwnd in (window.getHWND(), 0):
            with self.subTest(hwnd=hwnd), caret(hwnd):
                for _ in range(300):
                    result = pyauto.Window.getCaret()
                    self.assertIs(result[0], window if hwnd else None)
                    self.assertEqual(result[1], (1, 2, 3, 4))
                    del result
                with memory_error("Py_BuildValue"), self.assertRaises(MemoryError):
                    pyauto.Window.getCaret()
                self.assertEqual(sys.getrefcount(window), baseline)
        with window_destructions() as destroyed, caret(0x3456789ab):
            for _ in range(100):
                pyauto.Window.getCaret()
            self.assertEqual(destroyed.value, 100)
            with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                pyauto.Window.getCaret()
            with memory_error("Py_BuildValue"), self.assertRaises(MemoryError):
                pyauto.Window.getCaret()
            self.assertEqual(destroyed.value, 101)

    def test_enum_success_stop_exception_invalid_result_and_refs(self):
        window = pyauto.Window.fromHWND(0x456789abc)
        arg = object()
        baseline = sys.getrefcount(window), sys.getrefcount(arg)
        for returned in (1, 0, None, 2**100, "bad", object()):
            calls = []
            def callback(current, context, calls=calls, returned=returned):
                self.assertIs(current, window)
                self.assertIs(context, arg)
                calls.append(current.getHWND())
                return returned
            returned_refs = sys.getrefcount(returned)
            with self.subTest(result=returned), enumerate_handles([window.getHWND()] * 3) as results:
                errors = io.StringIO()
                with redirect_stderr(errors):
                    for _ in range(100):
                        self.assertIsNone(pyauto.Window.enum(callback, arg))
                valid = isinstance(returned, int) and returned < 2**31
                self.assertEqual(len(calls), 300 if returned == 1 else 100)
                self.assertEqual(set(results), {1 if returned == 1 else 0})
                self.assertEqual(bool(errors.getvalue()), not valid)
            self.assertEqual((sys.getrefcount(window), sys.getrefcount(arg)), baseline)
            self.assertEqual(sys.getrefcount(returned), returned_refs)
        def fail(current, context):
            raise RuntimeError("callback sentinel")
        with enumerate_handles([window.getHWND()] * 2) as results, redirect_stderr(io.StringIO()) as errors:
            pyauto.Window.enum(fail, arg)
            self.assertEqual(results, [0])
            self.assertIn("callback sentinel", errors.getvalue())
        # PyErr_Print retains the traceback (and its callback arguments) in sys.last_exc.
        for name in ("last_exc", "last_type", "last_value", "last_traceback"):
            if hasattr(sys, name):
                setattr(sys, name, None)
        self.assertEqual((sys.getrefcount(window), sys.getrefcount(arg)), baseline)

    def test_enum_null_failures_and_unretained_wrappers(self):
        arg = object()
        baseline = sys.getrefcount(arg)
        for name in ("_PyObject_New", "Py_BuildValue"):
            with self.subTest(fault=name), enumerate_handles([0x56789abcd] * 2) as results:
                with window_destructions() as destroyed, memory_error(name), redirect_stderr(io.StringIO()) as errors:
                    pyauto.Window.enum(lambda *args: self.fail("callback reached"), arg)
                self.assertEqual(results, [0])
                self.assertIn("MemoryError", errors.getvalue())
                self.assertEqual(destroyed.value, int(name == "Py_BuildValue"))
                self.assertEqual(sys.getrefcount(arg), baseline)
        with window_destructions() as destroyed, enumerate_handles([0x56789abcd] * 300):
            pyauto.Window.enum(lambda current, context: 1, arg)
            self.assertEqual(destroyed.value, 300)
        with enumerate_handles([0]):
            pyauto.Window.enum(lambda current, context: self.assertIsNone(current) or 0, arg)

    def test_real_window_enum_caret_and_os_lifetime(self):
        hwnd = user.CreateWindowExW(0, "EDIT", "pyauto ownership", 0, 0, 0, 80, 40, None, None, None, None)
        self.assertTrue(hwnd)
        window = pyauto.Window.fromHWND(hwnd)
        baseline = sys.getrefcount(window)
        try:
            for _ in range(100):
                seen = []
                pyauto.Window.enum(lambda current, arg, seen=seen: seen.append(current.getHWND()) or 1, None)
                self.assertIn(hwnd, seen)
            user.CreateCaret.argtypes = (P, P, c.c_int, c.c_int)
            user.SetCaretPos.argtypes = (c.c_int, c.c_int)
            self.assertTrue(user.CreateCaret(hwnd, None, 2, 10))
            self.assertTrue(user.SetCaretPos(3, 4))
            original = CALL(w.BOOL, w.DWORD, P)(P.from_address(imports(native)["GetGUIThreadInfo"]).value)
            # Production queries the foreground thread; select our real caret's thread deterministically.
            kernel = c.WinDLL("kernel32")
            with replace_import("GetGUIThreadInfo", CALL(w.BOOL, w.DWORD, P)(
                    lambda thread, info: original(kernel.GetCurrentThreadId(), info)), module=native):
                for _ in range(100):
                    result = pyauto.Window.getCaret()
                    self.assertIs(result[0], window)
                    self.assertEqual(result[1], (3, 4, 5, 14))
                    del result
            self.assertEqual(sys.getrefcount(window), baseline)
        finally:
            user.DestroyCaret()
            user.DestroyWindow(hwnd)
        self.assertIs(pyauto.Window.fromHWND(hwnd), window)
        with window_destructions() as destroyed:
            del window
            self.assertEqual(destroyed.value, 1)

    def test_input_invalid_fetch_failure_cleanup_and_recovery(self):
        class FetchError(Exception):
            pass
        class Items(list):
            def __getitem__(self, index):
                if index == 1:
                    raise FetchError("fetch sentinel")
                return super().__getitem__(index)
        class LengthError(list):
            def __len__(self):
                raise FetchError("length sentinel")
        class TooManyItems(list):
            def __len__(self):
                return 2**31
        good, bad = pyauto.Key("A"), object()
        sent = []
        with replace_import("SendInput", CALL(w.UINT, w.UINT, P, c.c_int)(
                lambda count, pointer, size: sent.append(count) or count), module=native):
            for items, exception in (([good, bad], TypeError), ((bad,), TypeError),
                                     (Items([good, good]), FetchError), (LengthError(), FetchError),
                                     (TooManyItems(), MemoryError)):
                baseline = sys.getrefcount(good), sys.getrefcount(bad)
                with self.subTest(items=type(items).__name__), input_allocations() as (allocated, freed):
                    for _ in range(100):
                        with self.assertRaises(exception):
                            pyauto.Input.send(items)
                    self.assertEqual(allocated.value, sum(counter.value for counter in freed))
                self.assertEqual((sys.getrefcount(good), sys.getrefcount(bad)), baseline)
            self.assertEqual(sent, [])
            pyauto.Input.send([good])
            self.assertEqual(sent, [2])

    def test_input_send_count_time_marker_and_partial_failure(self):
        captured = []
        def send(count, pointer, size):
            captured.extend((InputEvent * count).from_buffer_copy(c.string_at(pointer, count * size)))
            return count
        items = [pyauto.KeyDown("A"), pyauto.Key("B"), pyauto.MouseLeftClick(10, 20)]
        procs = []
        def register(kind, proc, module, thread):
            procs.append(c.PYFUNCTYPE(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)(proc))
            return kind
        with ExitStack() as stack:
            for name, callback in (
                ("SetWindowsHookExW", CALL(P, c.c_int, P, P, w.DWORD)(register)),
                ("UnhookWindowsHookEx", CALL(w.BOOL, P)(lambda handle: 1)),
                ("CallNextHookEx", CALL(c.c_ssize_t, P, c.c_int, w.WPARAM, w.LPARAM)(lambda *args: 0)),
            ):
                stack.enter_context(replace_import(name, callback, module=native))
            hook = pyauto.Hook()
            stack.callback(hook.destroy)
            hook.keydown = lambda *args: 0
            event = KeyboardEvent(65, 30, 0, 0x12345678, 0)
            procs[0](0, 0x100, c.addressof(event))
        with input_allocations() as (allocated, freed), replace_import(
                "SendInput", CALL(w.UINT, w.UINT, P, c.c_int)(send), module=native):
            for container in (items, tuple(items), []):
                self.assertIsNone(pyauto.Input.send(container))
        self.assertEqual(allocated.value, sum(counter.value for counter in freed))
        self.assertEqual(len(captured), 10)
        marker = c.WinDLL(native.__file__)._handle
        for event in captured:
            payload = event.value.key if event.kind == 1 else event.value.mouse
            self.assertEqual(payload.extra, marker)
            self.assertEqual(payload.time, 0x12345678)
        with (input_allocations() as (allocated, freed), replace_import(
                "SendInput", CALL(w.UINT, w.UINT, P, c.c_int)(lambda *args: 1), module=native),
              self.assertRaises(OSError)):
            pyauto.Input.send(items)
        self.assertEqual(allocated.value, sum(counter.value for counter in freed))


if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
