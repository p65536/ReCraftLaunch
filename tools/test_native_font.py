"""Windows-native Font boundary/lifetime checks; no visible GUI is opened."""
import ctypes
import gc
import subprocess
import sys
import unittest
from ctypes import wintypes
from pathlib import Path

import native_test_support  # noqa: F401  # Select and pin the native build before importing ckit.

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ckit import ckitcore


class LogFont(ctypes.Structure):
    _fields_ = [("metrics", wintypes.LONG * 5), ("flags", wintypes.BYTE * 8),
                ("face", wintypes.WCHAR * 32)]


kernel32 = ctypes.WinDLL("kernel32")
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
user32 = ctypes.WinDLL("user32")
user32.GetGuiResources.argtypes = (wintypes.HANDLE, wintypes.DWORD)
user32.GetGuiResources.restype = wintypes.DWORD
gdi32 = ctypes.WinDLL("gdi32")
gdi32.CreateFontIndirectW.argtypes = (ctypes.POINTER(LogFont),)
gdi32.CreateFontIndirectW.restype = wintypes.HFONT
gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
gdi32.DeleteObject.restype = wintypes.BOOL


def gdi_count():
    return user32.GetGuiResources(kernel32.GetCurrentProcess(), 0)


def check_gdi_exhaustion():
    """Reach only this child process's GDI quota, then release every handle."""
    original = ckitcore.Font("MS Gothic", 16)
    dimensions = original.getCharSize()
    logfont = LogFont()
    logfont.metrics[0] = -16
    logfont.face = "MS Gothic"
    handles = []
    before = gdi_count()
    try:
        # Windows' per-process quota is normally 10,000; bound custom quotas too.
        for _ in range(16384):
            handle = gdi32.CreateFontIndirectW(ctypes.byref(logfont))
            if not handle:
                break
            handles.append(handle)
        else:
            raise unittest.SkipTest("GDI quota not reached within bounded allocation")
        exhausted = gdi_count()
        for _ in range(10):
            try:
                ckitcore.Font("MS Gothic", 16)
            except RuntimeError as error:
                assert "CreateFontIndirect failed" in str(error), str(error)
            else:
                raise AssertionError("Font succeeded after GDI allocation failed")
            try:
                ckitcore.Font.__init__(original, "MS Gothic", 20)
            except RuntimeError:
                pass
            else:
                raise AssertionError("reinitialization succeeded at GDI quota")
            assert original.getCharSize() == dimensions
            assert gdi_count() == exhausted
    finally:
        for handle in handles:
            assert gdi32.DeleteObject(handle)
    assert gdi_count() == before
    assert all(value > 0 for value in ckitcore.Font("MS Gothic", 16).getCharSize())
    print(f"CreateFontIndirect failure/recovery verified after {len(handles)} handles")


class NativeFontTests(unittest.TestCase):
    def test_normal_creation_padding_and_destruction(self):
        ckitcore.Font("MS Gothic", 16).getCharSize()  # Warm up GDI.
        before = gdi_count()
        for size in (12, 16, 24, 32):
            for _ in range(5):
                font = ckitcore.Font("MS Gothic", size)
                width, height = font.getCharSize()
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertEqual(ckitcore.Font("MS Gothic", size, 2).getCharSize(),
                                 (width, height + 4))
                del font
        gc.collect()
        self.assertEqual(gdi_count(), before)

    def test_utf16_name_boundary(self):
        for name in ("a" * 31, "日" * 31, "\U0001f680" * 15 + "a"):
            with self.subTest(name=name):
                self.assertTrue(all(n > 0 for n in ckitcore.Font(name, 16).getCharSize()))
        for name in ("a" * 32, "日" * 32, "\U0001f680" * 16, "a" * 100000):
            with self.subTest(length=len(name)), self.assertRaises(ValueError):
                ckitcore.Font(name, 16)

    def test_embedded_nul_is_rejected(self):
        for name in ("\0", "MS Gothic\0", "MS Gothic\0other", "\0" + "a" * 100):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                ckitcore.Font(name, 16)

    def test_existing_gdi_defaults_and_integer_protocol(self):
        class Index:
            def __index__(self):
                return 16

        class Name(str):
            def __str__(self):
                raise AssertionError("Font must use the Unicode value")

        for name, size in (("", 16), ("MS Gothic", 0), ("MS Gothic", -16),
                           (Name("MS Gothic"), Index())):
            with self.subTest(name=name, size=size):
                plain = ckitcore.Font(name, size).getCharSize()
                self.assertTrue(all(n > 0 for n in plain))
                self.assertEqual(ckitcore.Font(name, size, -2**31).getCharSize(), plain)

    def test_invalid_types_and_numeric_overflow(self):
        before = gdi_count()
        for name in (None, b"MS Gothic", 1, [], object()):
            with self.subTest(name=name), self.assertRaises(TypeError):
                ckitcore.Font(name, 16)
        for position in (1, 2):
            for value in (None, 1.5, "16"):
                args = ["MS Gothic", 16, 0]
                args[position] = value
                with self.subTest(args=args), self.assertRaises(TypeError):
                    ckitcore.Font(*args)
            for value in (2**31, -2**31 - 1, 2**100):
                args = ["MS Gothic", 16, 0]
                args[position] = value
                with self.subTest(args=args), self.assertRaises(OverflowError):
                    ckitcore.Font(*args)
        for args in (("MS Gothic", -2**31), ("MS Gothic", 16, 2**31 - 1)):
            with self.subTest(args=args), self.assertRaises(OverflowError):
                ckitcore.Font(*args)
        for args in ((), ("MS Gothic",), ("MS Gothic", 16, 0, 0)):
            with self.subTest(args=args), self.assertRaises(TypeError):
                ckitcore.Font(*args)
        self.assertEqual(gdi_count(), before)

    def test_extreme_sizes_use_gdi_validation_without_leaking(self):
        before = gdi_count()
        for size in (2**31 - 1, -2**31 + 1):
            with self.subTest(size=size):
                try:
                    font = ckitcore.Font("MS Gothic", size)
                except RuntimeError as error:
                    # GDI may reject these sizes during creation or measurement.
                    self.assertIn("failed", str(error))
                else:
                    self.assertTrue(all(n > 0 for n in font.getCharSize()))
                    del font
                self.assertEqual(gdi_count(), before)

    def test_reinitialization_releases_only_its_own_reference(self):
        font = ckitcore.Font("MS Gothic", 16)
        original_size = font.getCharSize()
        ckitcore.registerWindowClass("ReCraftFontLifetimeTest")
        window = ckitcore.Window(x=0, y=0, width=100, height=50, show=False)
        plane = ckitcore.TextPlane(window, (0, 0), (100, 50), 0)
        try:
            plane.setFont(font)
            before = gdi_count()
            for _ in range(10):
                ckitcore.Font.__init__(font, "MS Gothic", 24, 2)
            self.assertEqual(gdi_count(), before + 1)
            self.assertEqual(plane.getFont().getCharSize(), original_size)
            self.assertEqual(font.getCharSize(), ckitcore.Font("MS Gothic", 24, 2).getCharSize())
            current_size = font.getCharSize()
            for args in ((None, 16), ("x" * 32, 16), ("MS Gothic\0other", 16),
                         ("MS Gothic", -2**31), ("MS Gothic", 16, 2**31 - 1)):
                with self.assertRaises((TypeError, ValueError, OverflowError)):
                    ckitcore.Font.__init__(font, *args)
                self.assertEqual(font.getCharSize(), current_size)
            self.assertEqual(plane.getFont().getCharSize(), original_size)
            self.assertEqual(gdi_count(), before + 1)
        finally:
            plane.destroy()
            window.destroy()

    def test_uninitialized_object_can_be_destroyed_or_initialized(self):
        font = ckitcore.Font.__new__(ckitcore.Font)
        with self.assertRaises(ValueError):
            font.getCharSize()
        del font
        font = ckitcore.Font.__new__(ckitcore.Font)
        with self.assertRaises(ValueError):
            ckitcore.Font.__init__(font, "a" * 32, 16)
        ckitcore.Font.__init__(font, "MS Gothic", 16)
        self.assertTrue(all(n > 0 for n in font.getCharSize()))

    def test_real_gdi_creation_failure_in_child_process(self):
        result = subprocess.run([sys.executable, "-B", __file__, "--gdi-exhaustion"],
                                check=False, capture_output=True, text=True, timeout=60)
        if result.returncode == 77:
            self.skipTest(result.stdout.strip())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("failure/recovery verified", result.stdout)
        print(result.stdout.strip())


if __name__ == "__main__":
    if sys.argv[1:] == ["--gdi-exhaustion"]:
        try:
            check_gdi_exhaustion()
        except unittest.SkipTest as error:
            print(error)
            sys.exit(77)
    else:
        unittest.main()
