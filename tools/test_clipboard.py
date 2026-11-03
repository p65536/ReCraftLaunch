"""Clipboard ownership faults and real Windows checks on a private station."""

import ctypes
import sys
import threading
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(RUN_DIR / "lib")]

from ckit import ckit_misc

kernel = ckit_misc._clipboard_kernel32
user = ckit_misc._clipboard_user32


class ClipboardFaultTests(unittest.TestCase):
    def setUp(self):
        self.buffer = ctypes.create_unicode_buffer("日本🙂tail\r")
        self.handle = 0x123456789
        self.api = Mock()
        for dll, name, result in (
            (kernel, "GlobalAlloc", self.handle),
            (kernel, "GlobalLock", ctypes.addressof(self.buffer)),
            (kernel, "GlobalUnlock", 0),
            (kernel, "GlobalFree", None),
            (user, "OpenClipboard", 1),
            (user, "CloseClipboard", 1),
            (user, "EmptyClipboard", 1),
            (user, "GetClipboardData", self.handle),
            (user, "SetClipboardData", self.handle),
        ):
            function = self.enterContext(patch.object(dll, name, return_value=result))
            self.api.attach_mock(function, name)

    def names(self):
        return [call[0] for call in self.api.mock_calls]

    def test_get_copies_before_unlock_and_never_frees_borrowed_memory(self):
        self.assertEqual(ckit_misc.getClipboardText(), "日本🙂tail\r")
        self.assertEqual(self.names(), ["OpenClipboard", "GetClipboardData", "GlobalLock",
                                       "GlobalUnlock", "CloseClipboard"])
        self.api.GlobalLock.assert_called_once_with(self.handle)
        self.api.GlobalUnlock.assert_called_once_with(self.handle)

    def test_get_unavailable_paths_release_only_acquired_resources(self):
        for stage, expected in (
            ("OpenClipboard", ["OpenClipboard"]),
            ("GetClipboardData", ["OpenClipboard", "GetClipboardData", "CloseClipboard"]),
            ("GlobalLock", ["OpenClipboard", "GetClipboardData", "GlobalLock", "CloseClipboard"]),
        ):
            with self.subTest(stage=stage):
                self.api.reset_mock()
                function = getattr(self.api, stage)
                original = function.return_value
                function.return_value = 0
                try:
                    self.assertEqual(ckit_misc.getClipboardText(), "")
                    self.assertEqual(self.names(), expected)
                finally:
                    function.return_value = original

    def test_get_read_exception_unlocks_and_closes_preserving_primary_failure(self):
        failure = RuntimeError("read failed")
        self.api.GlobalUnlock.side_effect = OSError("unlock failed")
        self.api.CloseClipboard.side_effect = OSError("close failed")
        with patch.object(ctypes, "wstring_at", side_effect=failure), \
             self.assertRaises(RuntimeError) as raised:
            ckit_misc.getClipboardText()
        self.assertIs(raised.exception, failure)
        self.api.GlobalUnlock.assert_called_once_with(self.handle)
        self.api.CloseClipboard.assert_called_once_with()
        self.api.GlobalFree.assert_not_called()
        self.assertEqual(len(failure.__notes__), 2)

    def test_get_api_exceptions_close_after_successful_open(self):
        for stage in ("OpenClipboard", "GetClipboardData", "GlobalLock", "CloseClipboard"):
            with self.subTest(stage=stage):
                self.api.reset_mock()
                failure = RuntimeError(stage)
                function = getattr(self.api, stage)
                function.side_effect = failure
                try:
                    with self.assertRaises(RuntimeError) as raised:
                        ckit_misc.getClipboardText()
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(self.api.CloseClipboard.call_count, stage != "OpenClipboard")
                    self.api.GlobalFree.assert_not_called()
                finally:
                    function.side_effect = None

    def test_set_transfers_ownership_only_after_success(self):
        self.assertIsNone(ckit_misc.setClipboardText("🙂end"))
        self.assertEqual(self.buffer.value, "🙂end")
        self.assertEqual(self.names(), ["GlobalAlloc", "GlobalLock", "GlobalUnlock",
                                       "OpenClipboard", "EmptyClipboard", "SetClipboardData", "CloseClipboard"])
        self.api.SetClipboardData.assert_called_once_with(ckit_misc.CF_UNICODETEXT, self.handle)
        self.api.GlobalFree.assert_not_called()

    def test_set_failures_free_untransferred_memory(self):
        for stage, expected in (
            ("GlobalAlloc", ["GlobalAlloc"]),
            ("GlobalLock", ["GlobalAlloc", "GlobalLock", "GlobalFree"]),
            ("OpenClipboard", ["GlobalAlloc", "GlobalLock", "GlobalUnlock", "OpenClipboard", "GlobalFree"]),
            ("EmptyClipboard", ["GlobalAlloc", "GlobalLock", "GlobalUnlock", "OpenClipboard",
                                "EmptyClipboard", "CloseClipboard", "GlobalFree"]),
            ("SetClipboardData", ["GlobalAlloc", "GlobalLock", "GlobalUnlock", "OpenClipboard",
                                  "EmptyClipboard", "SetClipboardData", "CloseClipboard", "GlobalFree"]),
        ):
            with self.subTest(stage=stage):
                self.api.reset_mock()
                function = getattr(self.api, stage)
                original = function.return_value
                function.return_value = 0
                try:
                    self.assertIsNone(ckit_misc.setClipboardText("text"))
                    self.assertEqual(self.names(), expected)
                    if stage != "GlobalAlloc":
                        self.api.GlobalFree.assert_called_once_with(self.handle)
                finally:
                    function.return_value = original

    def test_set_exceptions_free_only_owned_memory(self):
        for stage in ("GlobalLock", "GlobalUnlock", "OpenClipboard", "EmptyClipboard",
                      "SetClipboardData", "CloseClipboard"):
            with self.subTest(stage=stage):
                self.api.reset_mock()
                failure = RuntimeError(stage)
                function = getattr(self.api, stage)
                function.side_effect = failure
                try:
                    with self.assertRaises(RuntimeError) as raised:
                        ckit_misc.setClipboardText("text")
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(self.api.GlobalFree.call_count, stage != "CloseClipboard")
                    self.assertEqual(self.api.CloseClipboard.call_count,
                                     stage in ("EmptyClipboard", "SetClipboardData", "CloseClipboard"))
                finally:
                    function.side_effect = None

    def test_set_copy_exception_unlocks_and_frees_without_opening_clipboard(self):
        failure = KeyboardInterrupt()
        self.api.GlobalUnlock.side_effect = OSError("unlock failed")
        with patch.object(ctypes, "memmove", side_effect=failure), \
             self.assertRaises(KeyboardInterrupt) as raised:
            ckit_misc.setClipboardText("text")
        self.assertIs(raised.exception, failure)
        self.api.GlobalUnlock.assert_called_once_with(self.handle)
        self.api.GlobalFree.assert_called_once_with(self.handle)
        self.api.OpenClipboard.assert_not_called()


class NativeClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from check_standard_windows import isolated_desktop

        cls.desktop = isolated_desktop()
        cls.user32 = cls.desktop[0]
        cls.user32.CreateWindowExW.argtypes = (
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
        cls.user32.CreateWindowExW.restype = wintypes.HWND
        cls.user32.DestroyWindow.argtypes = (wintypes.HWND,)

    def test_native_unicode_roundtrip_and_ownership(self):
        for text in ("", "日本\r\n", "🙂tail\r", "𐀀🙂", "\ud800tail"):
            with self.subTest(text=repr(text)), \
                 patch.object(kernel, "GlobalFree", wraps=kernel.GlobalFree) as free:
                self.assertIsNone(ckit_misc.setClipboardText(text))
                free.assert_not_called()
                self.assertEqual(ckit_misc.getClipboardText(), text)

    def test_native_contention_frees_allocation_and_preserves_clipboard(self):
        ckit_misc.setClipboardText("競合🙂sentinel")
        ready, release = threading.Event(), threading.Event()
        errors = []
        def hold_clipboard():
            hwnd = None
            opened = False
            try:
                if not self.user32.SetThreadDesktop(self.desktop[2]):
                    raise ctypes.WinError(ctypes.get_last_error())
                hwnd = self.user32.CreateWindowExW(0, "STATIC", "clipboard lock", 0,
                                                  0, 0, 10, 10, None, None, None, None)
                if not hwnd:
                    raise ctypes.WinError(ctypes.get_last_error())
                opened = bool(user.OpenClipboard(hwnd))
                if not opened:
                    raise RuntimeError("Cannot open private clipboard")
                ready.set()
                if not release.wait(5):
                    raise TimeoutError("Clipboard holder was not released")
            except BaseException as error:  # noqa: BLE001  # Report worker failures on the test thread.
                errors.append(error)
                ready.set()
            finally:
                if opened:
                    user.CloseClipboard()
                if hwnd:
                    self.user32.DestroyWindow(hwnd)
        worker = threading.Thread(target=hold_clipboard, daemon=True)
        worker.start()
        free_results = []
        real_free = kernel.GlobalFree
        def free_memory(handle):
            result = real_free(handle)
            free_results.append(result)
            return result
        try:
            self.assertTrue(ready.wait(3))
            self.assertEqual(errors, [])
            with patch.object(kernel, "GlobalAlloc", wraps=kernel.GlobalAlloc) as allocate, \
                 patch.object(kernel, "GlobalFree", side_effect=free_memory) as free, \
                 patch.object(user, "SetClipboardData", wraps=user.SetClipboardData) as publish:
                self.assertEqual(ckit_misc.getClipboardText(), "")
                self.assertIsNone(ckit_misc.setClipboardText("blocked"))
                allocate.assert_called_once()
                free.assert_called_once()
                self.assertEqual(free_results, [None])
                publish.assert_not_called()
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(ckit_misc.getClipboardText(), "競合🙂sentinel")

    def test_native_missing_data_returns_empty(self):
        self.assertTrue(user.OpenClipboard(0))
        try:
            self.assertTrue(user.EmptyClipboard())
        finally:
            self.assertTrue(user.CloseClipboard())
        self.assertEqual(ckit_misc.getClipboardText(), "")

    def test_native_rejected_format_frees_untransferred_memory(self):
        real_publish, real_free = user.SetClipboardData, kernel.GlobalFree
        published, freed = [], []
        def reject_format(fmt, handle):
            result = real_publish(0, handle)
            published.append((handle, result))
            return result
        def free_memory(handle):
            result = real_free(handle)
            freed.append((handle, result))
            return result
        with patch.object(user, "SetClipboardData", side_effect=reject_format), \
             patch.object(kernel, "GlobalFree", side_effect=free_memory):
            self.assertIsNone(ckit_misc.setClipboardText("rejected🙂"))
        self.assertEqual(len(published), 1)
        self.assertIsNone(published[0][1])
        self.assertEqual(freed, published)
        self.assertEqual(ckit_misc.getClipboardText(), "")

    def test_native_concurrent_calls_keep_signatures_and_whole_unicode_strings(self):
        texts = ("日本🙂tail", "𐀀emoji🙂end", "other\r\n終")
        ckit_misc.setClipboardText(texts[0])
        errors = []
        barrier = threading.Barrier(3)
        def exchange(text):
            try:
                if not self.user32.SetThreadDesktop(self.desktop[2]):
                    raise ctypes.WinError(ctypes.get_last_error())
                barrier.wait(timeout=3)
                for _ in range(50):
                    ckit_misc.setClipboardText(text)
                    self.assertIn(ckit_misc.getClipboardText(), ("", *texts))
            except BaseException as error:  # noqa: BLE001  # Surface worker assertions in the test thread.
                errors.append(error)
        with patch.object(ctypes.windll.kernel32.GlobalLock, "restype", ctypes.c_wchar_p):
            workers = [threading.Thread(target=exchange, args=(text,), daemon=True) for text in texts]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertIs(kernel.GlobalLock.restype, ctypes.c_void_p)
            self.assertEqual(kernel.GlobalLock.argtypes, (ctypes.c_void_p,))
            self.assertIs(ctypes.windll.kernel32.GlobalLock.restype, ctypes.c_wchar_p)
        ckit_misc.setClipboardText(texts[-1])
        self.assertEqual(ckit_misc.getClipboardText(), texts[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
