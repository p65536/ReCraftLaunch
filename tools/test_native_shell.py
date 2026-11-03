"""Run rebuilt x64 native API boundaries on a private desktop, with local IAT faults.

COM doubles exercise the compiled cleanup paths, not real Shell extensions.
Real menu/dialog checks use the private station from check_standard_windows.
Use --allow-restricted-desktop only in a restricted test environment: creation
denied with error 5 permits the existing desktop and a reported clipboard skip.
"""
import ctypes as c
import faulthandler
import struct
import sys
import tempfile
import time
import unittest
import uuid
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(RUN_DIR)]
sys._clnch_app_dir = str(ROOT)

from check_standard_windows import isolated_desktop

ALLOW_RESTRICTED_DESKTOP = "--allow-restricted-desktop" in sys.argv
if ALLOW_RESTRICTED_DESKTOP:
    sys.argv.remove("--allow-restricted-desktop")
DESKTOP = isolated_desktop(allow_create_access_denied=ALLOW_RESTRICTED_DESKTOP)

import clnch_native as native
from ckit import ckitcore
from pyauto import pyautocore

P = c.c_void_p
U = w.UINT
H = c.c_long
CALL = c.WINFUNCTYPE
kernel = c.WinDLL("kernel32", use_last_error=True)
user = c.WinDLL("user32", use_last_error=True)
kernel.VirtualProtect.argtypes = (P, c.c_size_t, w.DWORD, c.POINTER(w.DWORD))
user.CreateWindowExW.argtypes = (w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
    c.c_int, c.c_int, c.c_int, c.c_int, P, P, P, P)
user.CreateWindowExW.restype = P
for name in ("DestroyWindow", "IsMenu"):
    getattr(user, name).argtypes = (P,)
user.GetWindowLongPtrW.argtypes = (P, c.c_int)
user.GetWindowLongPtrW.restype = P
user.SetTimer.argtypes = (P, c.c_size_t, U, P)
user.SetTimer.restype = c.c_size_t
user.KillTimer.argtypes = (P, c.c_size_t)
user.PostMessageW.argtypes = (P, U, w.WPARAM, w.LPARAM)


def imports(module=native):
    """Only inspect the loaded test extension's PE64 import table."""
    base = c.WinDLL(module.__file__)._handle
    pe = base + c.c_uint32.from_address(base + 0x3c).value
    assert c.c_uint16.from_address(pe + 24).value == 0x20b
    descriptor = base + c.c_uint32.from_address(pe + 24 + 120).value
    slots = {}
    while c.c_uint32.from_address(descriptor + 12).value:
        names = base + c.c_uint32.from_address(descriptor).value
        addresses = base + c.c_uint32.from_address(descriptor + 16).value
        i = 0
        while (name := c.c_uint64.from_address(names + 8 * i).value):
            if not name >> 63:
                slots[c.string_at(base + name + 2).decode()] = addresses + 8 * i
            i += 1
        descriptor += 20
    return slots


SLOTS = imports()


@contextmanager
def replace_import(name, callback, module=native):
    address = SLOTS[name] if module is native else imports(module)[name]
    with replace_pointer(address, callback) as original:
        yield original


@contextmanager
def replace_pointer(address, callback):
    slot = P.from_address(address)
    original = slot.value
    old = w.DWORD()
    if not kernel.VirtualProtect(address, 8, 4, c.byref(old)):
        raise c.WinError(c.get_last_error())
    try:
        slot.value = c.cast(callback, P).value
        yield original
    finally:
        slot.value = original
        restored = w.DWORD()
        if not kernel.VirtualProtect(address, 8, old.value, c.byref(restored)):
            raise c.WinError(c.get_last_error())


@contextmanager
def executable_thunk(code):
    api = c.WinDLL("kernel32")
    api.VirtualAlloc.argtypes = (P, c.c_size_t, w.DWORD, w.DWORD)
    api.VirtualAlloc.restype = P
    api.VirtualFree.argtypes = (P, c.c_size_t, w.DWORD)
    api.FlushInstructionCache.argtypes = (P, P, c.c_size_t)
    address = api.VirtualAlloc(None, len(code), 0x3000, 4)
    if not address:
        raise c.WinError()
    try:
        c.memmove(address, code, len(code))
        old = w.DWORD()
        if not kernel.VirtualProtect(address, len(code), 0x20, c.byref(old)):
            raise c.WinError(c.get_last_error())
        if not api.FlushInstructionCache(P(-1), address, len(code)):
            raise c.WinError()
        yield P(address)
    finally:
        api.VirtualFree(address, 0, 0x8000)


@contextmanager
def clobber_error_after_gil_restore():
    """Native x64 thunk: RestoreThread must run without a ctypes callback's GIL."""
    restore = P.from_address(SLOTS["PyEval_RestoreThread"]).value
    # Windows x64 shadow space, original RestoreThread, then SetLastError(5).
    code = (b"\x48\x83\xec\x28\x48\xb8" + struct.pack("<Q", restore)
            + b"\xff\xd0\xb9\x05\x00\x00\x00\x48\xb8"
            + struct.pack("<Q", c.cast(c.WinDLL("kernel32").SetLastError, P).value)
            + b"\xff\xd0\x48\x83\xc4\x28\xc3")
    with executable_thunk(code) as address, replace_import("PyEval_RestoreThread", address):
        yield


@contextmanager
def native_allocations():
    """Count CRT calls without entering Python while a native exception is set."""
    allocated, freed = c.c_size_t(), c.c_size_t()
    free_name = "free" if "free" in SLOTS else "_free_dbg"
    with ExitStack() as stack:
        for name, counter in (("malloc", allocated), (free_name, freed)):
            # Increment a native counter, then tail-jump with arguments intact.
            code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(counter)) + b"\x48\xff\x00"
                    + b"\x48\xb8" + struct.pack("<Q", P.from_address(SLOTS[name]).value) + b"\xff\xe0")
            if name == free_name:
                code = b"\x48\x85\xc9\x74\x0d" + code  # Do not count free(NULL).
            address = stack.enter_context(executable_thunk(code))
            stack.enter_context(replace_import(name, address))
        yield allocated, freed


@contextmanager
def observe_shell_invoke():
    """Forward real Shell COM calls and record the actual InvokeCommand result."""
    invoked, errors = [], []
    with ExitStack() as stack:
        def watch(obj, slot, args, after):
            table = P.from_address(obj).value
            # Keep each interface alive until its vtable has been restored.
            CALL(w.ULONG, P)(P.from_address(table + 8).value)(obj)
            release = CALL(w.ULONG, P)(P.from_address(table + 16).value)
            stack.callback(release, obj)
            def forward(this, *values):
                result = original(this, *values)
                if this == obj:
                    try:
                        after(result, values)
                    except BaseException as error:  # noqa: BLE001 - ctypes would otherwise swallow callback failures.
                        errors.append(error)
                return result
            callback = CALL(H, P, *args)(forward)
            original = CALL(H, P, *args)(stack.enter_context(
                replace_pointer(table + slot * 8, callback)))

        def menu3(result, values):
            iid = uuid.UUID("bcfce0a0-ec17-11d0-8d10-00a0c90f2719").bytes_le
            if result >= 0 and values[-1][0] and c.string_at(values[0], 16) == iid:
                watch(values[-1][0], 4, (P,), lambda result, values: invoked.append(result))

        def menu(result, values):
            if result >= 0 and values[-1][0]:
                watch(values[-1][0], 0, (P, c.POINTER(P)), menu3)

        def folder(result, values):
            if result >= 0 and values[-1][0]:
                watch(values[-1][0], 10, (P, U, P, P, P, c.POINTER(P)), menu)

        def desktop(output):
            result = original(output)
            if result >= 0 and output[0]:
                try:
                    watch(output[0], 5, (P, P, P, c.POINTER(P)), folder)
                except BaseException as error:  # noqa: BLE001 - report callback failures to unittest.
                    errors.append(error)
            return result

        original = CALL(H, c.POINTER(P))(stack.enter_context(replace_import(
            "SHGetDesktopFolder", CALL(H, c.POINTER(P))(desktop))))
        yield invoked, errors


class ShellDouble:
    """Minimal vtables for only the methods used by popupContextMenu."""
    def __init__(self, stage="ok"):
        self.stage = stage
        self.keep = []
        self.refs = dict.fromkeys(("malloc", "desktop", "folder", "menu", "menu3"), 0)
        self.pidls = {}
        self.events = []
        self.menus = []
        self.parses = 0
        self.errors = []
        self.objects = {}
        self.interface("malloc", 9, {5: (None, (P,), self.free)})
        folder_methods = {
            3: (H, (P, P, w.LPWSTR, P, c.POINTER(P), c.POINTER(w.ULONG)), self.parse),
            5: (H, (P, P, P, c.POINTER(P)), self.bind),
            10: (H, (P, U, P, P, P, c.POINTER(P)), self.get_menu),
        }
        self.interface("desktop", 13, folder_methods)
        self.interface("folder", 13, folder_methods)
        menu_methods = {
            0: (H, (P, c.POINTER(P)), self.query),
            3: (H, (P, U, U, U, U), self.populate),
            4: (H, (P,), self.invoke),
        }
        self.interface("menu", 8, menu_methods)
        self.interface("menu3", 8, menu_methods)

    def interface(self, name, size, methods):
        table = (P * size)()
        methods = dict(methods)
        methods[1] = (w.ULONG, (), lambda this: self.addref(name))
        methods[2] = (w.ULONG, (), lambda this: self.release(name))
        for index, (result, args, function) in methods.items():
            callback = CALL(result, P, *args)(function)
            self.keep.append(callback)
            table[index] = c.cast(callback, P).value
        obj = (P * 1)(c.addressof(table))
        self.keep.extend((table, obj))
        self.objects[name] = c.addressof(obj)

    def addref(self, name):
        self.refs[name] += 1
        return self.refs[name]

    def release(self, name):
        self.refs[name] -= 1
        return self.refs[name]

    def output(self, name, output):
        self.events.append(name)
        if self.stage in (name, name + "_null"):
            output[0] = None
            return -2147467259 if self.stage == name else 0
        output[0] = self.objects[name]
        self.refs[name] += 1
        return 0

    def allocate(self, output):
        pidl = c.create_string_buffer(2)
        address = c.addressof(pidl)
        self.pidls[address] = pidl
        output[0] = address
        return 0

    def free(self, this, address):
        if address not in self.pidls:
            self.errors.append(("invalid free", address))
        else:
            del self.pidls[address]

    def parse(self, this, hwnd, bind, name, eaten, output, attributes):
        self.events.append(("parse", hwnd, name, attributes[0]))
        self.parses += 1
        if self.stage in ("parse" + str(self.parses), "parse_null"):
            output[0] = None
            return 0 if self.stage == "parse_null" else -2147467259
        return self.allocate(output)

    def bind(self, this, pidl, bind, iid, output):
        return self.output("folder", output)

    def get_menu(self, this, hwnd, count, pidls, iid, reserved, output):
        self.events.append(("items", count))
        return self.output("menu", output)

    def query(self, this, iid, output):
        return self.output("menu3", output)

    def populate(self, this, menu, index, first, last, flags):
        self.menus.append(menu)
        return -2147467259 if self.stage == "populate" else 1

    def invoke(self, this, info):
        self.events.append("invoke")
        return -2147467259 if self.stage == "invoke" else 0

    @contextmanager
    def installed(self):
        with ExitStack() as stack:
            for api, obj in (("SHGetMalloc", "malloc"), ("SHGetDesktopFolder", "desktop")):
                callback = CALL(H, c.POINTER(P))(lambda output, obj=obj: self.output(obj, output))
                stack.enter_context(replace_import(api, callback))
            def special(hwnd, folder, output):
                self.events.append(("special", hwnd))
                return -2147467259 if self.stage == "special" else self.allocate(output)
            stack.enter_context(replace_import("SHGetSpecialFolderLocation",
                CALL(H, P, c.c_int, c.POINTER(P))(special)))
            def track(menu, flags, x, y, reserved, hwnd, rect):
                self.events.append(("track", hwnd, x, y))
                return 0 if self.stage == "cancel" else 1
            stack.enter_context(replace_import("TrackPopupMenu",
                CALL(w.BOOL, P, U, c.c_int, c.c_int, c.c_int, P, P)(track)))
            if self.stage == "create":
                stack.enter_context(replace_import("CreatePopupMenu", CALL(P)(lambda: None)))
            if self.stage == "subclass":
                stack.enter_context(replace_import("SetWindowLongPtrW",
                    CALL(c.c_ssize_t, P, c.c_int, c.c_ssize_t)(lambda *args: 0)))
            yield self


class ChooseColor(c.Structure):
    _fields_ = [("size", w.DWORD), ("owner", P), ("instance", P), ("rgb", w.DWORD),
               ("colors", c.POINTER(w.DWORD)), ("flags", w.DWORD),
               ("data", w.LPARAM), ("hook", P), ("template", P)]


class NetResource(c.Structure):
    _fields_ = [("scope", w.DWORD), ("type", w.DWORD), ("display", w.DWORD),
               ("usage", w.DWORD), ("local", w.LPWSTR), ("remote", w.LPWSTR),
               ("comment", w.LPWSTR), ("provider", w.LPWSTR)]


class CopyData(c.Structure):
    _fields_ = [("kind", c.c_size_t), ("size", w.DWORD), ("data", P)]


class ShortcutDouble(ShellDouble):
    """Reuse the test vtable builder for the two shortcut-reader interfaces."""
    def __init__(self, internet, stage):
        self.internet, self.stage = internet, stage
        self.keep, self.events, self.objects = [], [], {}
        self.refs = {"link": 0, "persist": 0}
        self.allocations = set()
        self.errors = []
        self.initialized = 0
        self.interface("persist", 9, {5: (H, (w.LPCWSTR, w.DWORD), self.load)})
        methods = {0: (H, (P, c.POINTER(P)), lambda this, iid, out: self.output("persist", out))}
        if internet:
            methods[4] = (H, (c.POINTER(P),), self.url)
        else:
            methods.update({
                3: (H, (P, c.c_int, P, w.DWORD), lambda *args: self.getter("path")),
                8: (H, (P, c.c_int), lambda *args: self.getter("directory")),
                10: (H, (P, c.c_int), lambda *args: self.getter("arguments")),
                14: (H, (P,), lambda *args: self.getter("show")),
            })
        self.interface("link", 21, methods)

    def load(self, this, path, flags):
        return self.getter("load")

    def getter(self, name):
        self.events.append(name)
        return -2147467259 if self.stage == name else 0

    def url(self, this, output):
        if self.stage in ("url_null", "url_false"):
            output[0] = None
            return int(self.stage == "url_false")
        value = c.create_unicode_buffer("https://example.invalid/日本語")
        self.keep.append(value)
        output[0] = c.addressof(value)
        self.allocations.add(output[0])
        return self.getter("url")

    @contextmanager
    def installed(self):
        with ExitStack() as stack:
            def initialize(reserved):
                if self.stage == "initialize":
                    return -2147417850  # RPC_E_CHANGED_MODE
                self.initialized += 1
                return 1  # S_FALSE must still be balanced with CoUninitialize.
            def uninitialize():
                self.initialized -= 1
            def free(address):
                if address:
                    if address not in self.allocations:
                        self.errors.append(("invalid free", address))
                    else:
                        self.allocations.remove(address)
            stack.enter_context(replace_import("CoInitialize", CALL(H, P)(initialize)))
            stack.enter_context(replace_import("CoUninitialize", CALL(None)(uninitialize)))
            stack.enter_context(replace_import("CoCreateInstance",
                CALL(H, P, P, w.DWORD, P, c.POINTER(P))(
                    lambda clsid, outer, flags, iid, out: self.output("link", out))))
            stack.enter_context(replace_import("CoTaskMemFree", CALL(None, P)(free)))
            yield self


class NativeShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert c.sizeof(P) == 8
        ckitcore.registerWindowClass("ReCraftNativeBoundaryTests")
        cls.hwnd = user.CreateWindowExW(0, "STATIC", "Shell boundary tests", 0,
                                       0, 0, 100, 100, None, None, None, None)
        assert cls.hwnd

    @classmethod
    def tearDownClass(cls):
        user.DestroyWindow(cls.hwnd)

    def test_invalid_handles_and_python_inputs(self):
        for value, error in ((None, TypeError), ("1", TypeError), (1.5, TypeError),
                             (-1, OverflowError), (1 << 64, OverflowError), (-(1 << 65), OverflowError)):
            for function, args in ((native.popupContextMenu, (1, 2, ".", [])),
                                   (native.chooseColor, ((1, 2, 3), ())),
                                   (native.addConnection, ("unused",)),
                                   (pyautocore.Window.fromHWND, ()),
                                   (ckitcore.Window.sendIpc, ("unused",))):
                with self.subTest(value=value, api=function.__name__), self.assertRaises(error):
                    function(value, *args)
        with self.assertRaises(OverflowError):
            native.popupContextMenu(self.hwnd, 1 << 40, 0, ".", [])
        for directory, items in ((None, []), (".", None), (".", [object()])):
            with self.assertRaises(TypeError):
                native.popupContextMenu(self.hwnd, 0, 0, directory, items)

    def test_full_width_handles_at_native_boundaries(self):
        for hwnd in (0, 0x1234567887654321, (1 << 64) - 1):
            shell = ShellDouble()
            with shell.installed(), replace_import("SetWindowLongPtrW",
                    CALL(c.c_ssize_t, P, c.c_int, c.c_ssize_t)(lambda *args: 1)):
                self.assertIsNone(native.popupContextMenu(hwnd, -123, 456, "directory", ["file"]))
            self.assertIn(("parse", hwnd or None, "directory", 0), shell.events)
            self.assertIn(("track", hwnd or None, -123, 456), shell.events)
            self.assertEqual(set(shell.refs.values()), {0})
            self.assertFalse(shell.pidls)
            captured = []
            def choose(pointer, captured=captured):
                captured.append(pointer.contents.owner)
                return 0
            with replace_import("ChooseColorW", CALL(w.BOOL, c.POINTER(ChooseColor))(choose)):
                result = native.chooseColor(hwnd, (1, 2, 3), ())
            self.assertEqual(captured, [hwnd or None])
            self.assertEqual(result, (0, (1, 2, 3), ((0, 0, 0),) * 16))

    def test_compiled_cleanup_paths_with_com_doubles(self):
        stages = ("ok", "cancel", "malloc", "malloc_null", "desktop", "desktop_null",
                  "special", "parse_null", "parse1", "parse2", "parse3", "folder", "folder_null",
                  "menu", "menu_null", "menu3", "menu3_null", "create", "populate",
                  "subclass", "invoke")
        previous = user.GetWindowLongPtrW(self.hwnd, -4)
        for stage in stages:
            with self.subTest(stage=stage):
                shell = ShellDouble(stage)
                with shell.installed():
                    self.assertIsNone(native.popupContextMenu(self.hwnd, -123, 456,
                        "" if stage == "special" else "directory", ["one", "two"]))
                self.assertEqual(shell.refs, dict.fromkeys(shell.refs, 0))
                self.assertFalse(shell.pidls)
                self.assertFalse(shell.errors)
                self.assertTrue(all(not user.IsMenu(menu) for menu in shell.menus))
                self.assertEqual(user.GetWindowLongPtrW(self.hwnd, -4), previous)
                if stage in ("ok", "cancel", "invoke"):
                    self.assertIn(("track", self.hwnd, -123, 456), shell.events)
                    self.assertEqual("invoke" in shell.events, stage != "cancel")
                else:
                    self.assertNotIn("invoke", shell.events)
                if stage in ("menu3", "menu3_null"):
                    self.assertFalse(shell.menus)  # Existing behavior: no base-menu display.
        shell = ShellDouble()
        with shell.installed():
            self.assertIsNone(native.popupContextMenu(self.hwnd, 0, 0, "x" * 260, ["one"]))
        self.assertFalse(shell.pidls)
        self.assertEqual(set(shell.refs.values()), {0})

    def test_find_file_results_empty_missing_and_cache(self):
        with tempfile.TemporaryDirectory(prefix="recraft-find-") as directory:
            path = Path(directory, "日本語.txt")
            path.write_bytes(b"test")
            pattern = str(Path(directory, "*.txt"))
            result = native.findFile(pattern)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0][:2], (path.name, 4))
            self.assertEqual(len(result[0][2]), 6)
            self.assertFalse(result[0][3] & 0x10)
            self.assertEqual(native.findFile(path=pattern, use_cache=True), result)
            path.unlink()
            # A cache hit must avoid enumeration, even after the file disappears.
            calls = []
            with replace_import("FindFirstFileW", CALL(P, w.LPCWSTR, P)(lambda *args: calls.append(args) or -1)):
                self.assertEqual(native.findFile(pattern, use_cache=True), result)
            self.assertFalse(calls)
            self.assertEqual(native.findFile(pattern), [])
            Path(directory, "subdir").mkdir()
            entries = native.findFile(str(Path(directory, "*")))
            self.assertEqual([entry[0] for entry in entries], ["subdir"])
            self.assertTrue(entries[0][3] & 0x10)
            with self.assertRaises(OSError) as raised:
                native.findFile(str(Path(directory, "missing", "*")))
            self.assertEqual(raised.exception.winerror, 3)
        calls = []
        with replace_import("FindFirstFileW", CALL(P, w.LPCWSTR, P)(lambda *args: calls.append(args) or -1)):
            for value in (None, 1, b"pattern", object()):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    native.findFile(value)
        self.assertFalse(calls)

    def test_find_file_preserves_error_before_gil_restore(self):
        with tempfile.TemporaryDirectory(prefix="recraft-error-") as directory, clobber_error_after_gil_restore():
            self.assertEqual(native.findFile(str(Path(directory, "*.absent"))), [])
            with self.assertRaises(OSError) as raised:
                native.findFile(str(Path(directory, "missing", "*")))
            self.assertEqual(raised.exception.winerror, 3)

    def test_set_file_time_positional_update_and_invalid_arguments(self):
        stamp = (2024, 2, 3, 12, 34, 56)
        with tempfile.TemporaryDirectory(prefix="recraft-time-") as directory:
            path = Path(directory, "日本語.txt")
            path.touch()
            self.assertIsNone(native.setFileTime(str(path), stamp))
            self.assertEqual(tuple(time.localtime(path.stat().st_mtime)[:6]), stamp)
        calls = []
        with replace_import("GetFileAttributesW", CALL(w.DWORD, w.LPCWSTR)(lambda *args: calls.append(args) or 0)):
            for value in (None, 1, b"path", object()):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    native.setFileTime(value, stamp)
            for args in ((), ("path",), ("path", stamp, 0), ("path", None),
                         ("path", stamp[:5]), ("path", (*stamp[:5], "bad"))):
                with self.subTest(args=args), self.assertRaises(TypeError):
                    native.setFileTime(*args)
            with self.assertRaises(TypeError):
                native.setFileTime(path="path", time=stamp)
        self.assertFalse(calls)

    def test_set_file_time_rejects_invalid_calendar_before_file_access(self):
        invalid = ((1600, 1, 1, 0, 0, 0), (30828, 1, 1, 0, 0, 0),
                   (65536 + 2024, 1, 1, 0, 0, 0), (2024, 0, 1, 0, 0, 0),
                   (2024, 13, 1, 0, 0, 0), (2024, 1, 0, 0, 0, 0),
                   (2024, 4, 31, 0, 0, 0), (2023, 2, 29, 0, 0, 0),
                   (1900, 2, 29, 0, 0, 0), (2024, 1, 1, -1, 0, 0),
                   (2024, 1, 1, 24, 0, 0), (2024, 1, 1, 0, 60, 0),
                   (2024, 1, 1, 0, 0, 60))
        calls = []
        with replace_import("GetFileAttributesW", CALL(w.DWORD, w.LPCWSTR)(lambda *args: calls.append(args) or 0)):
            for stamp in invalid:
                with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                    native.setFileTime("unused", stamp)
        self.assertFalse(calls)

    def test_set_file_time_readonly_file_directory_and_leap_dates(self):
        attributes = CALL(w.DWORD, w.LPCWSTR)(P.from_address(SLOTS["GetFileAttributesW"]).value)
        set_attributes = CALL(w.BOOL, w.LPCWSTR, w.DWORD)(P.from_address(SLOTS["SetFileAttributesW"]).value)
        with tempfile.TemporaryDirectory(prefix="recraft-time-") as directory:
            for is_dir in (False, True):
                path = Path(directory, "日本語-dir" if is_dir else "日本語.txt")
                path.mkdir() if is_dir else path.write_bytes(b"unchanged")
                original = attributes(str(path))
                try:
                    for readonly in (False, True):
                        self.assertTrue(set_attributes(str(path), original | 1 if readonly else original & ~1))
                        attr = attributes(str(path))
                        before = path.stat()
                        for stamp in ((2000, 2, 29, 23, 59, 59), (2024, 2, 29, 0, 0, 0)):
                            with self.subTest(is_dir=is_dir, readonly=readonly, stamp=stamp):
                                self.assertIsNone(native.setFileTime(str(path), stamp))
                                after = path.stat()
                                self.assertEqual(tuple(time.localtime(after.st_mtime)[:6]), stamp)
                                self.assertEqual(after.st_birthtime_ns, before.st_birthtime_ns)
                                self.assertEqual(attributes(str(path)), attr)
                        if not is_dir:
                            self.assertEqual(path.read_bytes(), b"unchanged")
                finally:
                    self.assertTrue(set_attributes(str(path), original))

    def test_set_file_time_failures_preserve_error_and_finish_cleanup(self):
        signatures = {
            "GetTimeZoneInformation": (w.DWORD, (P,), 0xffffffff),
            "TzSpecificLocalTimeToSystemTime": (w.BOOL, (P, P, P), 0),
            "SystemTimeToFileTime": (w.BOOL, (P, P), 0),
            "GetFileAttributesW": (w.DWORD, (w.LPCWSTR,), 0xffffffff),
            "SetFileAttributesW": (w.BOOL, (w.LPCWSTR, w.DWORD), 0),
            "CreateFileW": (P, (w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, P), -1),
            "SetFileTime": (w.BOOL, (P, P, P, P), 0),
            "CloseHandle": (w.BOOL, (P,), 0),
        }
        originals = {name: CALL(result, *args, use_last_error=True)(P.from_address(SLOTS[name]).value)
                     for name, (result, args, _) in signatures.items()}
        cases = [(name,) for name in signatures if name != "SetFileAttributesW"]
        cases += [("clear",), ("restore",), ("SetFileTime", "CloseHandle", "restore"),
                  ("CreateFileW", "restore"), ("CloseHandle", "restore")]
        stamp = (2024, 2, 3, 12, 34, 56)
        with tempfile.TemporaryDirectory(prefix="recraft-time-fault-") as directory:
            path = Path(directory, "readonly.txt")
            path.write_bytes(b"keep")
            original_attr = originals["GetFileAttributesW"](str(path))
            for faults in cases:
                with self.subTest(faults=faults):
                    native.setFileTime(str(path), (2023, 1, 2, 3, 4, 5))
                    self.assertTrue(originals["SetFileAttributesW"](str(path), original_attr | 1))
                    before = path.stat().st_mtime_ns
                    events = []
                    errors = {name: 123 + index for index, name in enumerate(faults)}
                    def wrapper(name, events=events, errors=errors):
                        result, args, failed = signatures[name]
                        def invoke(*values):
                            stage = ("restore" if values[1] & 1 else "clear") if name == "SetFileAttributesW" else name
                            events.append(stage)
                            if stage in errors:
                                # Simulate a close error after closing, to keep the test's real handle owned.
                                if name == "CloseHandle":
                                    originals[name](*values)
                                c.set_last_error(errors[stage])
                                return failed
                            return originals[name](*values)
                        return CALL(result, *args, use_last_error=True)(invoke)
                    try:
                        with ExitStack() as stack:
                            for name in signatures:
                                stack.enter_context(replace_import(name, wrapper(name)))
                            stack.enter_context(clobber_error_after_gil_restore())
                            with self.assertRaises(OSError) as raised:
                                native.setFileTime(str(path), stamp)
                        self.assertEqual(raised.exception.winerror, errors[faults[0]])
                        self.assertEqual(raised.exception.filename, str(path))
                        notes = " ".join(raised.exception.__notes__)
                        if "restore" in faults:
                            self.assertIn("read-only may remain cleared", notes)
                        updated = faults[0] in ("CloseHandle", "restore")
                        self.assertEqual("timestamp was updated" in notes, updated)
                        if updated:
                            self.assertEqual(tuple(time.localtime(path.stat().st_mtime)[:6]), stamp)
                        else:
                            self.assertEqual(path.stat().st_mtime_ns, before)
                        if "SetFileTime" in events:
                            self.assertEqual(events[-2:], ["CloseHandle", "restore"])
                        if "clear" in events and "clear" not in faults:
                            self.assertEqual(events[-1], "restore")
                            self.assertEqual(bool(originals["GetFileAttributesW"](str(path)) & 1), "restore" not in faults)
                    finally:
                        self.assertTrue(originals["SetFileAttributesW"](str(path), original_attr))
            # Both file deletion and content access still work after every cleanup path.
            self.assertEqual(path.read_bytes(), b"keep")
            path.unlink()

    def test_set_file_time_preserves_sharing_retry_before_gil_restore(self):
        signature = CALL(P, w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, P, use_last_error=True)
        create = signature(P.from_address(SLOTS["CreateFileW"]).value)
        for error in (32, 5):
            calls, sleeps = [], []
            def open_file(*args, error=error, calls=calls):
                calls.append(args[0])
                if len(calls) == 1:
                    c.set_last_error(error)
                    return -1
                return create(*args)
            with self.subTest(error=error), tempfile.TemporaryDirectory(prefix="recraft-retry-") as directory:
                path = Path(directory, "test.txt")
                path.touch()
                with replace_import("CreateFileW", signature(open_file)), replace_import(
                        "Sleep", CALL(None, w.DWORD)(sleeps.append)), clobber_error_after_gil_restore():
                    if error == 32:
                        self.assertIsNone(native.setFileTime(str(path), (2024, 2, 3, 12, 34, 56)))
                    else:
                        with self.assertRaises(OSError):
                            native.setFileTime(str(path), (2024, 2, 3, 12, 34, 56))
                self.assertEqual(len(calls), 2 if error == 32 else 1)
                self.assertEqual(sleeps, [250] if error == 32 else [])

    def test_set_file_time_retry_exhaustion_restores_readonly_and_reports_error(self):
        def blocked(*args):
            opens.append(args[0])
            c.set_last_error(32)
            return -1
        attributes = CALL(w.DWORD, w.LPCWSTR)(P.from_address(SLOTS["GetFileAttributesW"]).value)
        set_attributes = CALL(w.BOOL, w.LPCWSTR, w.DWORD)(P.from_address(SLOTS["SetFileAttributesW"]).value)
        with tempfile.TemporaryDirectory(prefix="recraft-time-retry-") as directory:
            path = Path(directory, "readonly.txt")
            path.touch()
            attr = attributes(str(path))
            self.assertTrue(set_attributes(str(path), attr | 1))
            opens, sleeps = [], []
            try:
                with replace_import("CreateFileW", CALL(P, w.LPCWSTR, w.DWORD, w.DWORD, P, w.DWORD, w.DWORD, P,
                                    use_last_error=True)(blocked)), replace_import(
                        "Sleep", CALL(None, w.DWORD)(sleeps.append)), clobber_error_after_gil_restore(), \
                        self.assertRaises(OSError) as raised:
                    native.setFileTime(str(path), (2024, 2, 3, 12, 34, 56))
                self.assertEqual(raised.exception.winerror, 32)
                self.assertEqual(opens, [str(path)] * 5)
                self.assertEqual(sleeps, [250] * 5)
                self.assertEqual(attributes(str(path)), attr | 1)
            finally:
                self.assertTrue(set_attributes(str(path), attr))

    def test_drag_conversion_failure_releases_references_and_native_objects(self):
        invalid = object()
        valid = "a long 日本語 path that owns a native string buffer.txt"
        calls = []
        with replace_import("DoDragDrop", CALL(H, P, P, w.DWORD, P)(lambda *args: calls.append(args) or 0)), replace_import(
                "GlobalAlloc", CALL(P, U, c.c_size_t)(lambda *args: calls.append(args) or None)):
            for container in (list, tuple):
                for items in (container([invalid]), container([valid, invalid, valid])):
                    before = [sys.getrefcount(value) for value in items]
                    with self.subTest(items=items), native_allocations() as (allocated, freed):
                        for _ in range(20):
                            with self.assertRaisesRegex(TypeError, "must be string or unicode"):
                                native.doDragAndDrop(items)
                    self.assertEqual([sys.getrefcount(value) for value in items], before)
                    self.assertGreater(allocated.value, 0)  # Includes CDataObject and its medium array.
                    self.assertEqual(allocated.value, freed.value)
        self.assertFalse(calls)
        with self.assertRaises(TypeError):
            native.doDragAndDrop(None)

    def test_drag_valid_file_lists_payload_and_cleanup(self):
        shell = c.WinDLL("shell32")
        shell.DragQueryFileW.argtypes = (P, U, w.LPWSTR, U)
        kernel.GlobalFlags.argtypes = (P,)
        kernel.GlobalFlags.restype = U
        ole = c.WinDLL("ole32")
        ole.ReleaseStgMedium.argtypes = (P,)
        class Format(c.Structure):
            _fields_ = [("format", w.WORD), ("target", P), ("aspect", w.DWORD),
                        ("index", w.LONG), ("medium", w.DWORD)]
        class Medium(c.Structure):
            _fields_ = [("type", w.DWORD), ("handle", P), ("owner", P)]
        for items in ([], ["C:\\日本語 test.txt", "D:\\second.txt"], ("C:\\one.txt",)):
            handles, payloads, errors = [], [], []
            def drag(obj, source, allowed, effect, payloads=payloads, errors=errors):
                try:
                    table = P.from_address(obj).value
                    get = CALL(H, P, c.POINTER(Format), c.POINTER(Medium))(P.from_address(table + 3 * 8).value)
                    fmt, medium = Format(15, None, 1, -1, 1), Medium()
                    result = get(obj, c.byref(fmt), c.byref(medium))
                    if result != 0:
                        raise AssertionError(result)
                    try:
                        count = shell.DragQueryFileW(medium.handle, 0xffffffff, None, 0)
                        names = []
                        for i in range(count):
                            text = c.create_unicode_buffer(1024)
                            shell.DragQueryFileW(medium.handle, i, text, len(text))
                            names.append(text.value)
                        payloads.append((names, allowed, bool(source)))
                    finally:
                        ole.ReleaseStgMedium(c.byref(medium))
                except BaseException as error:  # noqa: BLE001 - report ctypes callback failures to unittest.
                    errors.append(error)
                return 0x40101  # DRAGDROP_S_CANCEL; no interactive drag starts.
            alloc = CALL(P, U, c.c_size_t)(P.from_address(SLOTS["GlobalAlloc"]).value)
            def global_alloc(flags, size, alloc=alloc, handles=handles):
                handle = alloc(flags, size)
                handles.append(handle)
                return handle
            with self.subTest(items=items), replace_import("DoDragDrop", CALL(H, P, P, w.DWORD, P)(drag)), replace_import(
                    "GlobalAlloc", CALL(P, U, c.c_size_t)(global_alloc)), native_allocations() as (allocated, freed):
                self.assertIsNone(native.doDragAndDrop(items))
            self.assertFalse(errors)
            self.assertEqual(payloads, [(list(items), 1, True)])
            self.assertGreater(allocated.value, 0)
            self.assertEqual(allocated.value, freed.value)
            self.assertEqual(len(handles), 1)
            self.assertTrue(all(kernel.GlobalFlags(handle) == 0x8000 for handle in handles))

    def test_network_connection_arguments_and_errors(self):
        for hwnd in (0, self.hwnd, 0x1234567887654321, (1 << 64) - 1):
            for error in (0, 5, 1223):  # success, access denied, user cancellation
                calls = []
                def connect(owner, pointer, password, username, flags, calls=calls, error=error):
                    data = pointer.contents
                    calls.append((owner, data.type, data.local, data.remote, data.provider,
                                  password, username, flags))
                    return error
                with self.subTest(hwnd=hwnd, error=error), replace_import("WNetAddConnection3W",
                        CALL(w.DWORD, P, c.POINTER(NetResource), P, P, w.DWORD)(connect)):
                    for call in (lambda hwnd=hwnd: native.addConnection(hwnd, r"\\server\日本語"),
                                 lambda hwnd=hwnd: native.addConnection(servername=r"\\server\日本語", hwnd=hwnd)):
                        if error:
                            with self.assertRaises(OSError) as raised:
                                call()
                            self.assertEqual(raised.exception.winerror, error)
                        else:
                            self.assertIsNone(call())
                self.assertEqual(calls, [(hwnd or None, 0, None, r"\\server\日本語",
                                         None, None, None, 8)] * 2)
        calls = []
        with replace_import("WNetAddConnection3W",
                CALL(w.DWORD, P, P, P, P, w.DWORD)(lambda *args: calls.append(args) or 0)), self.assertRaises(TypeError):
            native.addConnection(self.hwnd, None)
        self.assertFalse(calls)

    def test_handle_roundtrip_parent_and_ipc(self):
        user.GetPropW.argtypes = (P, w.LPCWSTR)
        user.GetPropW.restype = P
        user.GetParent.argtypes = (P,)
        user.GetParent.restype = P
        for hwnd in (0x1234567887654321, (1 << 64) - 1):
            self.assertEqual(pyautocore.Window.fromHWND(hwnd).getHWND(), hwnd)
            calls = []
            def send(target, message, wp, lp, calls=calls):
                packet = CopyData.from_address(lp)
                calls.append((target, message, packet.kind, c.string_at(packet.data, packet.size)))
                return 1
            with replace_import("SendMessageW", CALL(c.c_ssize_t, P, U, w.WPARAM, w.LPARAM)(send), ckitcore):
                for payload in ("日本語", "a\0b", b"bytes"):
                    self.assertIsNone(ckitcore.Window.sendIpc(hwnd, payload))
            self.assertEqual(calls, [(hwnd, 0x4a, 0x101, text) for text in
                                    ("日本語".encode(), b"a\0b", b"bytes")])
        create_type = CALL(P, w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                           c.c_int, c.c_int, c.c_int, c.c_int, P, P, P, P)
        create = create_type(P.from_address(imports(ckitcore)["CreateWindowExW"]).value)
        parents = []
        def create_window(exstyle, cls, title, style, x, y, width, height, parent, menu, instance, data):
            parents.append(parent)
            return create(exstyle, cls, title, style, x, y, width, height, None, menu, instance, data)
        with replace_import("CreateWindowExW", create_type(create_window), ckitcore):
            child = ckitcore.Window(show=False, parent_window=0x1234567887654321)
            child.destroy()
        self.assertEqual(parents, [0x1234567887654321])
        self.assertIsNone(pyautocore.Window.fromHWND(0))
        received = []
        parent = ckitcore.Window(show=False, ipc_handler=received.append)
        try:
            hwnd = parent.getHWND()
            self.assertEqual(pyautocore.Window.fromHWND(hwnd).getHWND(), hwnd)
            self.assertIsNone(ckitcore.Window.sendIpc(hwnd, "実IPC 日本語"))
            self.assertEqual(received, ["実IPC 日本語"])
            child = ckitcore.Window(show=False, parent_window=hwnd)
            try:
                self.assertEqual(user.GetParent(child.getHWND()), hwnd)
            finally:
                child.destroy()
            for value in (-1, 1 << 64):
                with self.assertRaises(OverflowError):
                    ckitcore.Window(show=False, parent_window=value)
            address = user.GetPropW(hwnd, "ckit_userdata")
            self.assertTrue(address)
            slot = P.from_address(address)  # Window::hwnd is the first native field.
            try:
                slot.value = 0x1234567887654321
                self.assertEqual(parent.getHWND(), slot.value)
            finally:
                slot.value = hwnd
            with replace_import("GetModuleHandleW", CALL(P, w.LPCWSTR)(lambda name: 0x1234567887654321), ckitcore):
                self.assertEqual(parent.getHINSTANCE(), 0x1234567887654321)
        finally:
            parent.destroy()

    def test_keyboard_state_buffer_boundary(self):
        original = pyautocore.Input.getKeyboardState()
        self.assertEqual(len(original), 256)
        self.assertIsNone(pyautocore.Input.setKeyboardState(original))
        self.assertEqual(pyautocore.Input.getKeyboardState(), original)
        for value in (b"", b"x", bytes(255), bytes(257)):
            with self.assertRaises(ValueError):
                pyautocore.Input.setKeyboardState(value)

    def test_shortcut_compiled_failure_and_release_paths(self):
        for internet, function in ((False, native.getShellLinkInfo), (True, native.getInternetShortcutInfo)):
            for stage in ("ok", "initialize", "link", "link_null", "persist", "persist_null", "load",
                          *(("url", "url_null", "url_false") if internet else ("path", "arguments", "directory", "show"))):
                with self.subTest(internet=internet, stage=stage):
                    double = ShortcutDouble(internet, stage)
                    with double.installed():
                        if stage in ("ok", "url_null", "url_false"):
                            expected = ("https://example.invalid/日本語" if stage == "ok" else "") if internet else ("", "", "", 1)
                            self.assertEqual(function("test shortcut"), expected)
                        else:
                            with self.assertRaises(OSError):
                                function("test shortcut")
                    self.assertEqual(double.refs, {"link": 0, "persist": 0})
                    self.assertFalse(double.allocations)
                    self.assertFalse(double.errors)
                    self.assertEqual(double.initialized, 0)
                    if not internet and stage in ("path", "arguments", "directory", "show"):
                        getters = ["load", "path", "arguments", "directory", "show"]
                        self.assertEqual(double.events[-getters.index(stage)-1:], getters[:getters.index(stage)+1])
            with self.assertRaises(TypeError):
                function(None)

    def test_real_shortcut_reads_and_missing_files(self):
        ole = c.WinDLL("ole32")
        ole.CoCreateInstance.argtypes = (P, P, w.DWORD, P, c.POINTER(P))
        def method(obj, slot, *types):
            table = c.cast(obj, c.POINTER(P))[0]
            address = P.from_address(table + slot * c.sizeof(P)).value
            return CALL(H, P, *types)(address)
        def guid(value):
            return c.create_string_buffer(uuid.UUID(value).bytes_le)
        link = P()
        self.assertEqual(ole.CoCreateInstance(guid("00021401-0000-0000-c000-000000000046"), None, 1,
            guid("000214f9-0000-0000-c000-000000000046"), c.byref(link)), 0)
        try:
            with tempfile.TemporaryDirectory(prefix="recraft-shortcut-") as directory:
                target = str(Path(sys.executable))
                for index, value in ((20, target), (11, "--test 日本語"), (9, directory)):
                    self.assertEqual(method(link, index, w.LPCWSTR)(link, value), 0)
                self.assertEqual(method(link, 15, c.c_int)(link, 7), 0)
                persist = P()
                self.assertEqual(method(link, 0, P, c.POINTER(P))(link,
                    guid("0000010b-0000-0000-c000-000000000046"), c.byref(persist)), 0)
                try:
                    path = Path(directory, "日本語.lnk")
                    self.assertEqual(method(persist, 6, w.LPCWSTR, w.BOOL)(persist, str(path), True), 0)
                finally:
                    method(persist, 2)(persist)
                self.assertEqual(native.getShellLinkInfo(str(path)), (target, "--test 日本語", directory, 7))
                url = Path(directory, "日本語.url")
                url.write_text("[InternetShortcut]\nURL=https://example.invalid/test\n", encoding="utf-8")
                self.assertEqual(native.getInternetShortcutInfo(str(url)), "https://example.invalid/test")
                with self.assertRaises(OSError):
                    native.getShellLinkInfo(str(Path(directory, "missing.lnk")))
                # InternetShortcut may successfully load an absent/empty URL as no URL.
                self.assertEqual(native.getInternetShortcutInfo(str(Path(directory, "missing.url"))), "")
        finally:
            method(link, 2)(link)

    def test_color_invalid_arguments_do_not_open_dialog(self):
        invalid_colors = ([1, 2, 3], 123, object(), "rgb", (), (1, 2), (1, 2, 3, 4),
                          (1, 2, "bad"), (1, 2, 3.0), (1, 2, None))
        calls = []
        with replace_import("ChooseColorW", CALL(w.BOOL, P)(lambda pointer: calls.append(True) or 0)):
            for color in invalid_colors:
                for initial, table in ((color, None), (None, [(1, 2, 3), color])):
                    with self.subTest(initial=initial, table=table), self.assertRaises(TypeError):
                        native.chooseColor(self.hwnd, initial, table)
            with self.assertRaises(TypeError):
                native.chooseColor(self.hwnd, None, [None])
            for table in (123, object(), {(1, 2, 3)}, {}, iter([(1, 2, 3)])):
                with self.subTest(table=table), self.assertRaises(TypeError):
                    native.chooseColor(self.hwnd, None, table)
            for value in (-(1 << 31) - 1, 1 << 31, 1 << 100):
                for component in range(3):
                    color = tuple(value if i == component else 0 for i in range(3))
                    for initial, table in ((color, None), (None, [color])):
                        with self.subTest(initial=initial, table=table), self.assertRaises(OverflowError):
                            native.chooseColor(self.hwnd, initial, table)
        self.assertFalse(calls, "Invalid arguments reached ChooseColorW")

    def test_color_defaults_table_lengths_and_integer_conversion(self):
        class Index:
            def __index__(self):
                return 42
        class First16:
            def __len__(self):
                return 17
            def __getitem__(self, index):
                if index >= 16:
                    raise AssertionError("Unused color was accessed")
                return (index, index + 1, index + 2)
        colors = [(i, i + 1, i + 2) for i in range(16)]
        black = ((0, 0, 0),) * 16
        cases = [(None, None, (0, 0, 0), black),
                 ((12, 34, 56), [], (12, 34, 56), black),
                 ((12, 34, 56), colors[:3], (12, 34, 56), tuple(colors[:3]) + black[:13]),
                 ((12, 34, 56), tuple(colors), (12, 34, 56), tuple(colors)),
                 ((12, 34, 56), colors + [object()], (12, 34, 56), tuple(colors)),
                 ((12, 34, 56), First16(), (12, 34, 56), tuple(colors)),
                 ((-1, 256, 511), [(-(1 << 31), (1 << 31) - 1, 258)],
                  (255, 0, 255), ((0, 255, 2),) + black[:15]),
                 ((True, False, Index()), [(Index(), False, True)],
                  (1, 0, 42), ((42, 0, 1),) + black[:15])]
        captured = []
        def choose(pointer):
            data = pointer.contents
            captured.append((data.rgb, tuple(data.colors[i] for i in range(16)), data.flags))
            return 0
        with replace_import("ChooseColorW", CALL(w.BOOL, c.POINTER(ChooseColor))(choose)):
            for initial, table, rgb, expected_table in cases:
                with self.subTest(initial=initial, table=table):
                    before = list(table) if isinstance(table, (list, tuple)) else None
                    self.assertEqual(native.chooseColor(self.hwnd, initial, table), (0, rgb, expected_table))
                    self.assertEqual(captured[-1], (rgb[0] | rgb[1] << 8 | rgb[2] << 16,
                        tuple(r | g << 8 | b << 16 for r, g, b in expected_table), 3))
                    if before is not None:
                        self.assertEqual(list(table), before)
        self.assertEqual(len(captured), len(cases))

    def test_color_reference_and_sequence_failures(self):
        class Broken:
            def __len__(self):
                return 1
            def __getitem__(self, index):
                raise RuntimeError("color item")
        class BrokenLength(Broken):
            def __len__(self):
                raise RuntimeError("color length")
        class BrokenIndex:
            def __index__(self):
                raise RuntimeError("color integer")
        calls = []
        with replace_import("ChooseColorW", CALL(w.BOOL, P)(lambda pointer: calls.append(True) or 0)):
            for table, message in ((Broken(), "color item"), (BrokenLength(), "color length")):
                with self.subTest(table=table), self.assertRaisesRegex(RuntimeError, message):
                    native.chooseColor(self.hwnd, (1, 2, 3), table)
            for initial, table in (((BrokenIndex(), 2, 3), None), (None, [(1, 2, BrokenIndex())])):
                with self.subTest(initial=initial, table=table), self.assertRaisesRegex(RuntimeError, "color integer"):
                    native.chooseColor(self.hwnd, initial, table)
        self.assertFalse(calls)
        item = (200, 201, 202)
        table = [item] * 16
        before = sys.getrefcount(item)
        with replace_import("ChooseColorW", CALL(w.BOOL, P)(lambda pointer: 0)):
            for _ in range(20):
                self.assertEqual(native.chooseColor(self.hwnd, (1, 2, 3), table)[2], tuple(table))
        self.assertEqual(sys.getrefcount(item), before)
        for invalid in ((1, 2, "bad"), [1, 2, 3], object(), (1, 2, 1 << 100)):
            table = [item, invalid]
            before = (sys.getrefcount(item), sys.getrefcount(invalid))
            calls = []
            with replace_import("ChooseColorW", CALL(w.BOOL, P)(lambda pointer, calls=calls: calls.append(True) or 0)):
                for _ in range(20):
                    with self.assertRaises((TypeError, OverflowError)):
                        native.chooseColor(self.hwnd, (1, 2, 3), table)
            self.assertEqual((sys.getrefcount(item), sys.getrefcount(invalid)), before)
            self.assertFalse(calls)

    def test_real_shell_menu_cancel_and_missing_pidl(self):
        ole = c.WinDLL("ole32")
        result = ole.CoInitialize(None)
        self.assertGreaterEqual(result, 0)
        try:
            with tempfile.TemporaryDirectory(prefix="recraft-shell-") as directory:
                Path(directory, "日本語 test.txt").write_text("test", encoding="utf-8")
                ticks = []
                @CALL(None, P, U, c.c_size_t, w.DWORD)
                def cancel(hwnd, message, timer, time):
                    ticks.append(True)
                    user.EndMenu()
                timer = user.SetTimer(self.hwnd, 0, 100, cancel)
                self.assertTrue(timer)
                try:
                    self.assertIsNone(native.popupContextMenu(self.hwnd, 10, 20, directory, ["日本語 test.txt"]))
                finally:
                    user.KillTimer(self.hwnd, timer)
                self.assertTrue(ticks, "Real TrackPopupMenu did not run its modal message loop")
                self.assertIsNone(native.popupContextMenu(self.hwnd, 0, 0, directory, ["missing-file.txt"]))
                self.assertIsNone(native.popupContextMenu(self.hwnd, 0, 0, directory + "-missing", []))
        finally:
            ole.CoUninitialize()

    def test_real_shell_copy_command(self):
        # The real Shell builds the menu and invokes Copy; only selection is automated.
        user.GetMenuItemCount.argtypes = (P,)
        user.GetMenuStringW.argtypes = (P, U, w.LPWSTR, c.c_int, U)
        user.GetMenuItemID.argtypes = (P, c.c_int)
        user.GetMenuItemID.restype = U
        user.OpenClipboard.argtypes = (P,)
        user.GetClipboardData.argtypes = (U,)
        user.GetClipboardData.restype = P
        shell32 = c.WinDLL("shell32")
        shell32.DragQueryFileW.argtypes = (P, U, w.LPWSTR, U)
        selected = []
        def copy(menu, flags, x, y, reserved, hwnd, rect):
            text = c.create_unicode_buffer(1024)
            for index in range(user.GetMenuItemCount(menu)):
                user.GetMenuStringW(menu, index, text, len(text), 0x400)
                # Built-in Copy labels on the supported Japanese/English test hosts.
                if text.value in ("コピー(&C)", "&Copy", "Copy"):
                    command = user.GetMenuItemID(menu, index)
                    selected.append(command)
                    return command
            return 0
        with tempfile.TemporaryDirectory(prefix="recraft-shell-copy-") as directory:
            path = Path(directory, "日本語 copy.txt")
            path.write_text("copy test", encoding="utf-8")
            with observe_shell_invoke() as (invoked, errors), replace_import("TrackPopupMenu",
                    CALL(w.BOOL, P, U, c.c_int, c.c_int, c.c_int, P, P)(copy)):
                self.assertIsNone(native.popupContextMenu(self.hwnd, 0, 0, directory, [path.name]))
            self.assertEqual(len(selected), 1, "Shell Copy command was not found")
            self.assertFalse(errors)
            self.assertEqual(len(invoked), 1, "Shell InvokeCommand was not called exactly once")
            self.assertGreaterEqual(invoked[0], 0, "Shell InvokeCommand failed")
            with self.subTest(check="CF_HDROP"):
                self.check_shell_copy_payload(path, shell32)

    def check_shell_copy_payload(self, path, shell32):
        allow_denied = ALLOW_RESTRICTED_DESKTOP and DESKTOP is None
        c.set_last_error(0)
        if not user.OpenClipboard(self.hwnd):
            error = c.get_last_error()
            if allow_denied and error == 5:
                self.skipTest("CF_HDROP: OpenClipboard denied on the restricted desktop")
            self.fail(f"OpenClipboard failed with winerror {error}")
        try:
            c.set_last_error(0)
            drop = user.GetClipboardData(15)  # CF_HDROP
            error = c.get_last_error()
            if not drop and allow_denied and error == 5:
                self.skipTest("CF_HDROP: GetClipboardData denied on the restricted desktop")
            self.assertTrue(drop, f"GetClipboardData failed with winerror {error}")
            self.assertEqual(shell32.DragQueryFileW(drop, 0xffffffff, None, 0), 1)
            copied = c.create_unicode_buffer(32768)
            self.assertTrue(shell32.DragQueryFileW(drop, 0, copied, len(copied)))
            self.assertEqual(Path(copied.value), path)
        finally:
            user.CloseClipboard()

    def test_desktop_fallback_only_on_station_creation_denied(self):
        for stage, error, allowed in (("CreateWindowStationW", 5, True),
                ("CreateWindowStationW", 5, False), ("CreateWindowStationW", 8, True),
                ("SetProcessWindowStation", 5, True), ("CreateDesktopW", 5, True),
                ("CreateDesktopW", 8, True), ("SetThreadDesktop", 5, True)):
            api = Mock()
            for name in ("CreateWindowStationW", "SetProcessWindowStation", "CreateDesktopW", "SetThreadDesktop"):
                getattr(api, name).return_value = 0 if name == stage else 123
            with self.subTest(stage=stage, error=error, allowed=allowed), patch(
                    "check_standard_windows.ctypes.WinDLL", return_value=api), patch(
                    "check_standard_windows.ctypes.get_last_error", return_value=error):
                if stage == "CreateWindowStationW" and error == 5 and allowed:
                    self.assertIsNone(isolated_desktop(allow_create_access_denied=True))
                    api.SetProcessWindowStation.assert_not_called()
                else:
                    with self.assertRaises(OSError) as raised:
                        isolated_desktop(allow_create_access_denied=allowed)
                    self.assertEqual(raised.exception.winerror, error)

    def test_shell_invoke_observer_reports_success_failure_and_no_call(self):
        for stage in ("ok", "invoke", "cancel", "menu3", "menu3_null"):
            shell = ShellDouble(stage)
            with self.subTest(stage=stage), shell.installed(), observe_shell_invoke() as (invoked, errors):
                self.assertIsNone(native.popupContextMenu(self.hwnd, 0, 0, "directory", ["file"]))
            self.assertFalse(errors)
            self.assertEqual(invoked, [0] if stage == "ok" else [-2147467259] if stage == "invoke" else [])
            self.assertEqual(set(shell.refs.values()), {0})
            self.assertFalse(shell.pidls)

    def test_clipboard_denial_requires_explicit_fallback_and_reports_skip(self):
        for allowed, desktop in ((False, None), (True, None), (True, (1, 2, 3))):
            for stage in ("open", "read"):
                for error in (5, 6):
                    api = Mock()
                    def denied(error=error):
                        c.set_last_error(error)
                    api.OpenClipboard.side_effect = (lambda hwnd, denied=denied: denied()) if stage == "open" else None
                    api.OpenClipboard.return_value = True
                    api.GetClipboardData.side_effect = lambda fmt, denied=denied: denied()
                    expected = unittest.SkipTest if allowed and desktop is None and error == 5 else AssertionError
                    with self.subTest(allowed=allowed, desktop=desktop, stage=stage, error=error), patch.dict(
                            globals(), user=api, DESKTOP=desktop, ALLOW_RESTRICTED_DESKTOP=allowed), self.assertRaises(expected):
                        self.check_shell_copy_payload(Path("unused"), Mock())
                    self.assertEqual(api.CloseClipboard.call_count, int(stage == "read"))

    def test_real_color_dialog_accept_and_cancel(self):
        user.SetWindowsHookExW.argtypes = (c.c_int, P, P, w.DWORD)
        user.SetWindowsHookExW.restype = P
        user.CallNextHookEx.argtypes = (P, c.c_int, w.WPARAM, w.LPARAM)
        user.CallNextHookEx.restype = c.c_ssize_t
        user.UnhookWindowsHookEx.argtypes = (P,)
        cases = ((command, initial, table, rgb, expected_table)
                 for command in (1, 2)
                 for initial, table, rgb, expected_table in
                 ((None, None, (0, 0, 0), ((0, 0, 0),) * 16),
                  ((12, 34, 56), ((1, 2, 3),) * 16, (12, 34, 56), ((1, 2, 3),) * 16)))
        for command, initial, table, rgb, expected_table in cases:
            dialogs = []
            @CALL(c.c_ssize_t, c.c_int, w.WPARAM, w.LPARAM)
            def hook(code, hwnd, detail, dialogs=dialogs, command=command):
                if code == 5:  # HCBT_ACTIVATE: initialized common dialog, before interaction.
                    dialogs.append(hwnd)
                    user.PostMessageW(hwnd, 0x111, command, 0)
                return user.CallNextHookEx(None, code, hwnd, detail)
            handle = user.SetWindowsHookExW(5, hook, None, kernel.GetCurrentThreadId())
            self.assertTrue(handle)
            try:
                result = native.chooseColor(self.hwnd, initial, table)
            finally:
                user.UnhookWindowsHookEx(handle)
            self.assertTrue(dialogs)
            self.assertEqual(result, (int(command == 1), rgb, expected_table))


if __name__ == "__main__":
    faulthandler.dump_traceback_later(40, exit=True)
    unittest.main(verbosity=2)
