"""Real pyautocore image checks; IAT faults stay inside a timed child process."""
import ctypes as c
import faulthandler
import struct
import subprocess
import sys
import unittest
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path

import native_test_support

PACKAGE = None
if "--package" in sys.argv:
    index = sys.argv.index("--package")
    PACKAGE = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
    native_test_support.RUN_DIR = PACKAGE
    sys.path[:0] = [str(PACKAGE / "library.zip"), str(PACKAGE / "lib")]
    import ckit  # noqa: F401 - Select packaged dependencies before test helpers import them.
    import pyauto

from test_native_pyauto_ownership import count_calls, memory_error
from test_native_shell import CALL, P, executable_thunk, imports, replace_import, user

import pyauto
from pyauto import pyautocore as native


class Bitmap(c.Structure):
    _fields_ = [("kind", w.LONG), ("width", w.LONG), ("height", w.LONG),
               ("stride", w.LONG), ("planes", w.WORD), ("depth", w.WORD), ("bits", P)]


@contextmanager
def native_reply(name, result, *, second=None, sequence=None):
    # Record the last two calls in bounded slots without a Python callback.
    count = c.c_size_t()
    records = (c.c_uint64 * 24)()
    code = (b"\x49\xba" + struct.pack("<Q", c.addressof(count))
            + b"\x49\x8b\x02\x49\xff\x02\x83\xe0\x01\x48\xc1\xe0\x04"
            + b"\x49\xbb" + struct.pack("<Q", c.addressof(records))
            + b"\x49\x01\xc3\x49\x89\x0b\x49\x89\x53\x08")
    if sequence is not None:
        code += (b"\x49\xbb" + struct.pack("<Q", c.addressof(sequence))
                 + b"\x49\xff\x03\x49\x8b\x03"
                 + b"\x49\xbb" + struct.pack("<Q", c.addressof(records) + 23 * 8)
                 + b"\x49\x89\x03")
    code += b"\x48\xb8" + struct.pack("<Q", result)
    if second is not None:
        code += (b"\x49\x83\x3a\x01\x74\x0a\x48\xb8" + struct.pack("<Q", second))
    code += b"\xc3"
    with executable_thunk(code) as thunk, replace_import(name, thunk, module=native):
        yield count, records


@contextmanager
def image_destructions():
    get_slot = c.pythonapi.PyType_GetSlot
    get_slot.argtypes = (c.py_object, c.c_int)
    get_slot.restype = P
    dealloc = get_slot(pyauto.Image, 52)  # Py_tp_dealloc
    prefix = (P * 8).from_address(id(pyauto.Image))
    offsets = [i * c.sizeof(P) for i, value in enumerate(prefix) if value == dealloc]
    assert len(offsets) == 1
    with count_calls(id(pyauto.Image) + offsets[0]) as counter:
        yield counter


@contextmanager
def image_frees():
    slots = imports(native)
    with ExitStack() as stack:
        # free(NULL) is legal and is deliberately excluded from ownership counts.
        counters = []
        for name in ("free", "_free_dbg"):
            if name not in slots:
                continue
            counter = c.c_size_t()
            code = (b"\x48\x85\xc9\x74\x0d\x48\xb8"
                    + struct.pack("<Q", c.addressof(counter)) + b"\x48\xff\x00"
                    + b"\x48\xb8" + struct.pack("<Q", P.from_address(slots[name]).value) + b"\xff\xe0")
            thunk = stack.enter_context(executable_thunk(code))
            stack.enter_context(replace_import(name, thunk, module=native))
            counters.append(counter)
        yield counters


@contextmanager
def capture(*, fault=None, depth=32, rect=(0, 0, 2, 2), layout=None, pixels=None):
    bitmap = Bitmap(0, 2, 2, 8 if depth in (24, 32) else 4, 1, depth, None)
    if layout:
        for name, value in layout.items():
            setattr(bitmap, name, value)
    raw = pixels if pixels is not None else (b"abcdabcd" if depth == 8 else bytes((3, 2, 1, 255, 6, 5, 4, 255)) * 2)
    errors = []
    calls = []
    def get_rect(hwnd, pointer):
        calls.append("rect")
        if fault == "GetWindowRect":
            return 0
        c.memmove(pointer, c.byref(w.RECT(*rect)), c.sizeof(w.RECT))
        return 1
    def get_object(handle, size, pointer):
        calls.append("object")
        if fault == "GetObjectW":
            return 0
        c.memmove(pointer, c.byref(bitmap), c.sizeof(bitmap))
        return size - 1 if fault == "short-object" else size
    def get_bits(handle, size, pointer):
        calls.append(("bits", size))
        if fault == "GetBitmapBits":
            return 0
        # Never dereference the dangerous dimensions supplied by boundary tests.
        if size != len(raw):
            errors.append((size, len(raw)))
            return 0
        c.memmove(pointer, raw, size)
        return size - 1 if fault == "short-bits" else size
    signatures = (
        ("GetWindowRect", CALL(w.BOOL, P, P)(get_rect)),
        ("GetObjectW", CALL(c.c_int, P, c.c_int, P)(get_object)),
        ("GetBitmapBits", CALL(w.LONG, P, w.LONG, P)(get_bits)),
    )
    with ExitStack() as stack:
        for name, callback in signatures:
            stack.enter_context(replace_import(name, callback, module=native))
        replies = {}
        sequence = c.c_size_t()
        for name, result in (("GetWindowDC", 0x101), ("CreateCompatibleDC", 0x202),
                             ("CreateCompatibleBitmap", 0x303), ("SetMapMode", 1), ("BitBlt", 1),
                             ("SelectObject", 0x404), ("DeleteDC", 1), ("DeleteObject", 1),
                             ("ReleaseDC", 1), ("GetPixel", 0x00030201)):
            second = 0 if name == "SelectObject" and fault == "restore" else None
            value = (2**64 - 1 if fault == "HGDI_ERROR" else 0) if (
                fault == name or name == "SelectObject" and fault == "HGDI_ERROR") else result
            if name == "GetPixel" and fault == "GetPixel":
                value = 0xffffffff
            replies[name] = stack.enter_context(native_reply(
                name, value, second=second, sequence=sequence))
        yield calls, replies
        assert not errors, errors


class ImageTests(unittest.TestCase):
    def test_selected_binary(self):
        expected = native_test_support.RUN_DIR / "lib/pyautocore.pyd"
        self.assertEqual(Path(native.__file__).resolve(), expected.resolve())
        if PACKAGE:
            self.assertEqual(Path(pyauto.__file__).parent.parent, PACKAGE / "library.zip")

    def test_rgb_copy_short_buffer_modes_and_empty_images(self):
        raw = bytes(range(18))
        image = pyauto.Image.fromString("RGB", (3, 2), raw + b"ignored")
        self.assertEqual((image.getSize(), image.getMode(), image.getBuffer()), ((3, 2), "RGB", raw))
        for length in (0, 1, 17):
            with self.subTest(length=length), self.assertRaises(ValueError):
                pyauto.Image.fromString("RGB", (3, 2), raw[:length])
        with self.assertRaises(ValueError):
            pyauto.Image.fromString("RGBA", (1, 1), b"abcd")
        for size in ((0, 0), (0, 2**31 - 1), (2**31 - 1, 0), (-1, -1), (-1, 2),
                     (2, -1), (-2**31, 2**31 - 1)):
            with self.subTest(size=size):
                empty = pyauto.Image.fromString("RGB", size, b"")
                self.assertEqual((empty.getSize(), empty.getBuffer()), ((0, 0), b""))
                self.assertEqual(image.find(empty), (0, 0))
                self.assertEqual(empty.find(empty), (0, 0))
                self.assertIsNone(empty.find(image))

    def test_extreme_dimensions_reject_before_allocating(self):
        # 65536*3*65536 used to wrap to zero and create a huge, empty-backed image.
        for size, exception in (((65536, 65536), ValueError), ((715827882, 1), ValueError),
                                ((715827883, 1), ValueError), ((2**31 - 1, 2**31 - 1), OverflowError)):
            with self.subTest(size=size), native_reply("malloc", 0) as (allocated, _):
                with self.assertRaises(exception):
                    pyauto.Image.fromString("RGB", size, b"")
                self.assertEqual(allocated.value, 0)
        with self.assertRaises(OverflowError):
            pyauto.Image.fromString("RGB", (2**31, 1), b"")

    def test_find_order_edges_oversize_and_invalid_type(self):
        image = pyauto.Image.fromString("RGB", (3, 2), b"abcDEFghiJKLDEFxyz")
        for data, position in ((b"abc", (0, 0)), (b"DEF", (1, 0)), (b"xyz", (2, 1)), (b"???", None)):
            needle = pyauto.Image.fromString("RGB", (1, 1), data)
            self.assertEqual(image.find(needle), position)
        self.assertEqual(image.find(image), (0, 0))
        self.assertEqual(image.find(pyauto.Image.fromString("RGB", (2, 2), b"DEFghiDEFxyz")), (1, 0))
        self.assertIsNone(image.find(pyauto.Image.fromString("RGB", (4, 1), b"abc" * 4)))
        self.assertIsNone(image.find(pyauto.Image.fromString("RGB", (1, 3), b"abc" * 3)))
        with self.assertRaises(TypeError):
            image.find(b"abc")

    def test_allocation_failure_and_recovery(self):
        for size in ((0, 0), (1, 1)):
            with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                pyauto.Image.fromString("RGB", size, b"abc")
        with image_destructions() as destroyed, native_reply("malloc", 0):
            with self.assertRaises(MemoryError):
                pyauto.Image.fromString("RGB", (1, 1), b"abc")
            self.assertEqual(destroyed.value, 1)
        image = pyauto.Image.fromString("RGB", (1, 1), b"abc")
        with memory_error("PyBytes_FromStringAndSize"), self.assertRaises(MemoryError):
            image.getBuffer()
        self.assertEqual(image.getBuffer(), b"abc")

    def test_capture_formats_padding_and_cleanup_order(self):
        cases = ((32, None, bytes((1, 2, 3, 4, 5, 6)) * 2),
                 (24, bytes((3, 2, 1, 6, 5, 4, 99, 99)) * 2, bytes((1, 2, 3, 4, 5, 6)) * 2),
                 (16, b"\x00\xf8\xe0\x07\x1f\x00\xff\xff", bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255))),
                 (8, b"abcdabcd", bytes((1, 2, 3)) * 4))
        window = pyauto.Window.fromHWND(0x12345)
        for depth, raw, expected in cases:
            with self.subTest(depth=depth), capture(depth=depth, pixels=raw) as (_, replies):
                image = window.getImage()
                self.assertEqual((image.getSize(), image.getBuffer()), ((2, 2), expected))
                selected, records = replies["SelectObject"]
                self.assertEqual(selected.value, 2)
                self.assertEqual(list(records[:4]), [0x202, 0x303, 0x202, 0x404])
                self.assertLess(records[23], replies["DeleteDC"][1][23])
                self.assertLess(replies["DeleteDC"][1][23], replies["DeleteObject"][1][23])
                self.assertEqual(replies["ReleaseDC"][0].value, 1)

    def test_capture_failures_release_only_acquired_resources(self):
        window = pyauto.Window.fromHWND(0x12345)
        faults = ("GetWindowRect", "GetWindowDC", "CreateCompatibleDC", "CreateCompatibleBitmap",
                  "SelectObject", "HGDI_ERROR", "SetMapMode", "BitBlt", "GetObjectW",
                  "short-object", "GetBitmapBits", "short-bits", "restore", "GetPixel")
        for fault in faults:
            with self.subTest(fault=fault), capture(fault=fault, depth=8 if fault == "GetPixel" else 32) as (_, replies), image_frees() as freed, image_destructions() as destroyed:
                with self.assertRaises(RuntimeError):
                    window.getImage()
                self.assertEqual(replies["ReleaseDC"][0].value, int(fault not in faults[:2]))
                self.assertEqual(replies["DeleteDC"][0].value, int(fault not in faults[:3]))
                self.assertEqual(replies["DeleteObject"][0].value, int(fault not in faults[:4]))
                if replies["DeleteObject"][0].value:
                    self.assertEqual(replies["DeleteObject"][1][0], 0x303)
                if replies["ReleaseDC"][0].value:
                    self.assertEqual(list(replies["ReleaseDC"][1][:2]), [0x12345, 0x101])
                self.assertEqual(destroyed.value, int(fault in ("restore", "GetPixel")))
                expected_frees = 2 if fault in ("restore", "GetPixel") else int(fault in ("GetBitmapBits", "short-bits"))
                self.assertEqual(sum(item.value for item in freed), expected_frees)
                if fault not in faults[:6]:
                    self.assertEqual(replies["SelectObject"][0].value, 2)
        with capture():
            self.assertEqual(window.getImage().getBuffer(), bytes((1, 2, 3, 4, 5, 6)) * 2)

    def test_capture_layout_and_size_fail_before_reading(self):
        window = pyauto.Window.fromHWND(0x12345)
        cases = (({"width": 1}, RuntimeError), ({"height": -1}, RuntimeError),
                 ({"stride": 0}, RuntimeError), ({"stride": 7}, RuntimeError),
                 ({"planes": 2}, RuntimeError), ({"stride": 2**30}, OverflowError),
                 ({"stride": 2**30 - 1}, MemoryError))
        for layout, exception in cases:
            with self.subTest(layout=layout), capture(layout=layout) as (calls, replies):
                with native_reply("malloc", 0) as (allocated, _), self.assertRaises(exception):
                    window.getImage()
                self.assertEqual(allocated.value, int(exception is MemoryError))
                self.assertFalse(any(isinstance(call, tuple) for call in calls))
                self.assertEqual(replies["SelectObject"][0].value, 2)
        # Exactly LONG_MAX is representable; stop at malloc instead of allocating.
        with capture(rect=(0, 0, 2, 1), layout={"height": 1, "stride": 2**31 - 1}) as (calls, _):
            with native_reply("malloc", 0) as (allocated, records), self.assertRaises(MemoryError):
                window.getImage()
            self.assertEqual((allocated.value, records[0]), (1, 2**31 - 1))
            self.assertFalse(any(isinstance(call, tuple) for call in calls))
        for rect, exception in (((-2**31, 0, 2**31 - 1, 1), OverflowError),
                                ((0, 0, 2**31 - 1, 2**31 - 1), OverflowError)):
            with self.subTest(rect=rect), capture(rect=rect) as (_, replies), self.assertRaises(exception):
                window.getImage()
            self.assertEqual(replies["GetWindowDC"][0].value, 0)
        for rect in ((0, 0, 0, 10), (10, 10, 0, 0)):
            with capture(rect=rect) as (_, replies):
                image = window.getImage()
                self.assertEqual((image.getSize(), image.getBuffer()), ((0, 0), b""))
                self.assertEqual(replies["GetWindowDC"][0].value, 0)
                with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                    window.getImage()

    def test_capture_allocation_failures_free_memory_and_wrapper(self):
        window = pyauto.Window.fromHWND(0x12345)
        # Fail allocation 1 (raw bitmap) or 2 (RGB); real allocations stay tiny.
        for failed in (1, 2):
            with capture() as (_, replies), image_frees() as freed, image_destructions() as destroyed, ExitStack() as stack:
                original = P.from_address(imports(native)["malloc"]).value
                allocated = c.c_size_t()
                code = (b"\x49\xba" + struct.pack("<Q", c.addressof(allocated))
                        + b"\x49\xff\x02\x49\x83\x3a" + bytes([failed])
                        + b"\x75\x03\x31\xc0\xc3\x48\xb8" + struct.pack("<Q", original) + b"\xff\xe0")
                thunk = stack.enter_context(executable_thunk(code))
                stack.enter_context(replace_import("malloc", thunk, module=native))
                with self.assertRaises(MemoryError):
                    window.getImage()
                self.assertEqual(allocated.value, failed)
                self.assertEqual(destroyed.value, int(failed == 2))
                self.assertEqual(sum(item.value for item in freed), failed - 1)
                self.assertEqual(replies["ReleaseDC"][0].value, 1)
        with capture() as (_, replies), image_frees() as freed:
            with memory_error("_PyObject_New"), self.assertRaises(MemoryError):
                window.getImage()
            self.assertEqual(sum(item.value for item in freed), 1)
            self.assertEqual(replies["DeleteObject"][0].value, 1)

    def test_restore_failure_preserves_primary_exception(self):
        window = pyauto.Window.fromHWND(0x12345)
        with capture(fault="restore") as (_, replies), memory_error("_PyObject_New"):
            with self.assertRaises(MemoryError):
                window.getImage()
            self.assertEqual(replies["SelectObject"][0].value, 2)
            self.assertLess(replies["DeleteDC"][1][23], replies["DeleteObject"][1][23])

    def test_real_gdi_pixels_restoration_and_resource_stability(self):
        gdi = c.WinDLL("gdi32")
        kernel = c.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = P
        user.GetGuiResources.argtypes = (P, w.DWORD)
        gdi.GetCurrentObject.argtypes = (P, w.UINT)
        gdi.GetCurrentObject.restype = P
        gdi.SetPixel.argtypes = (P, c.c_int, c.c_int, w.DWORD)
        gdi.CreateCompatibleDC.argtypes = (P,)
        gdi.CreateCompatibleDC.restype = P
        gdi.CreateDIBSection.argtypes = (P, P, w.UINT, c.POINTER(P), P, w.DWORD)
        gdi.CreateDIBSection.restype = P
        gdi.SelectObject.argtypes = (P, P)
        gdi.SelectObject.restype = P
        gdi.DeleteDC.argtypes = (P,)
        gdi.DeleteObject.argtypes = (P,)
        hwnd = user.CreateWindowExW(0, "EDIT", "image test", 0, 0, 0, 80, 40, None, None, None, None)
        self.assertTrue(hwnd)
        window = pyauto.Window.fromHWND(hwnd)
        left, top, right, bottom = window.getRect()
        width, height = right - left, bottom - top
        source = gdi.CreateCompatibleDC(None)
        self.assertTrue(source)
        info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = P()
        bitmap = gdi.CreateDIBSection(source, info, 0, c.byref(bits), None, 0)
        self.assertTrue(bitmap)
        old = gdi.SelectObject(source, bitmap)
        c.memset(bits, 0, width * height * 4)
        c.memmove(bits, bytes((3, 2, 1, 0, 6, 5, 4, 0)), 8)
        c.memmove(bits.value + width * 4, bytes((9, 8, 7, 0)), 4)
        try:
            # A private desktop need not support screen BitBlt. Use a real DIB DC
            # as the capture source; all destination/conversion GDI calls are real.
            with ExitStack() as stack:
                stack.enter_context(native_reply("GetWindowDC", source))
                stack.enter_context(native_reply("ReleaseDC", 1))
                self.check_real_capture(window, gdi, kernel)
        finally:
            user.DestroyWindow(hwnd)
            gdi.SelectObject(source, old)
            gdi.DeleteDC(source)
            gdi.DeleteObject(bitmap)
        with self.assertRaises(RuntimeError):
            window.getImage()

    def check_real_capture(self, window, gdi, kernel):
        image = window.getImage()
        left, top, right, bottom = window.getRect()
        self.assertEqual(image.getSize(), (right - left, bottom - top))
        width = right - left
        raw = image.getBuffer()
        self.assertEqual(raw[:6], bytes(range(1, 7)))
        self.assertEqual(raw[width * 3:width * 3 + 3], bytes(range(7, 10)))
        original_select = CALL(P, P, P)(P.from_address(imports(native)["SelectObject"]).value)
        selections = []
        def select(dc, obj):
            result = original_select(dc, obj)
            selections.append((dc, obj, result, gdi.GetCurrentObject(dc, 7)))
            return result
        with replace_import("SelectObject", CALL(P, P, P)(select), module=native):
            window.getImage()
        self.assertEqual(len(selections), 2)
        self.assertEqual(selections[0][2], selections[1][1])
        self.assertEqual(selections[1][3], selections[0][2])
        counts = []
        for _ in range(5):
            for _ in range(100):
                window.getImage()
            gdi.GdiFlush()
            counts.append(user.GetGuiResources(kernel.GetCurrentProcess(), 0))
        self.assertLessEqual(max(counts) - min(counts), 1, counts)

class IsolatedImageTests(unittest.TestCase):
    def test_native_child(self):
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--image-child"]
        if PACKAGE:
            command += ["--package", str(PACKAGE)]
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout + result.stderr, end="")


if __name__ == "__main__":
    faulthandler.dump_traceback_later(80, exit=True)
    if "--image-child" in sys.argv:
        sys.argv.remove("--image-child")
        print(f"Image native checks: {native.__file__}", flush=True)
        unittest.main(defaultTest="ImageTests", verbosity=2)
    else:
        unittest.main(defaultTest="IsolatedImageTests", verbosity=2)
