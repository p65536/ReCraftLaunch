"""Argument-buffer ownership and reader-lock errors; --package DIR checks the distribution."""
import ctypes
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

import native_test_support

ROOT = Path(__file__).resolve().parent.parent
PROCESS_ARGV = sys.argv[:]
if "--package" in sys.argv:
    index = sys.argv.index("--package")
    package = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]
    native_test_support.RUN_DIR = package
    sys.path[:0] = [str(package / "library.zip"), str(package / "lib")]
else:
    sys.path[:0] = [str(ROOT), str(native_test_support.RUN_DIR / "lib")]

from ckit import ckit_misc


class ArgvFaultTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(ckit_misc, "_argv", None))
        self.enterContext(patch.object(sys, "argv", ["script.py", "日本🙂", ""]))
        self.values = ["python.exe", "-B", *sys.argv]
        self.buffer = (wintypes.LPWSTR * len(self.values))(*self.values)
        self.pointer = ctypes.cast(self.buffer, ctypes.POINTER(wintypes.LPWSTR))
        self.command = self.enterContext(patch.object(
            ctypes.cdll.kernel32, "GetCommandLineW", return_value="command line"))
        self.parse = self.enterContext(patch.object(
            ctypes.windll.shell32, "CommandLineToArgvW", side_effect=self.parse_command))
        self.free = self.enterContext(patch.object(ctypes.windll.kernel32, "LocalFree"))

    def parse_command(self, command, count):
        self.assertEqual(command, "command line")
        ctypes.cast(count, ctypes.POINTER(ctypes.c_int))[0] = len(self.values)
        return self.pointer

    def assert_freed_once(self):
        self.free.assert_called_once()
        self.assertEqual(self.free.call_args.args[0].value, ctypes.addressof(self.buffer))
        self.assertEqual(self.free.argtypes, [wintypes.HLOCAL])
        self.assertIs(self.free.restype, wintypes.HLOCAL)

    def test_success_copies_sys_argv_tail_and_caches_same_mutable_list(self):
        result = ckit_misc.getArgv()
        self.assertEqual(result, sys.argv)
        self.assert_freed_once()
        result.append("caller mutation")
        self.assertIs(ckit_misc.getArgv(), result)
        self.assertEqual(result[-1], "caller mutation")
        self.command.assert_called_once_with()
        self.parse.assert_called_once()
        self.assert_freed_once()

    def test_null_raises_winerror_without_free_or_cache_then_retries(self):
        failure = ctypes.WinError(8)
        self.parse.side_effect = None
        self.parse.return_value = ctypes.POINTER(wintypes.LPWSTR)()
        with patch.object(ctypes, "WinError", return_value=failure), self.assertRaises(OSError) as raised:
            ckit_misc.getArgv()
        self.assertIs(raised.exception, failure)
        self.assertIsNone(ckit_misc._argv)
        self.free.assert_not_called()
        self.parse.side_effect = self.parse_command
        self.assertEqual(ckit_misc.getArgv(), sys.argv)
        self.assertEqual(self.parse.call_count, 2)
        self.assert_freed_once()

    def test_copy_exception_frees_once_without_partial_cache_then_retries(self):
        for failure in (RuntimeError("copy failed"), MemoryError("copy allocation"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                ckit_misc._argv = None
                self.free.reset_mock()
                with patch.object(type(self.pointer), "__getitem__", side_effect=["partial", failure]), \
                     self.assertRaises(type(failure)) as raised:
                    ckit_misc.getArgv()
                self.assertIs(raised.exception, failure)
                self.assertIsNone(ckit_misc._argv)
                self.assert_freed_once()
                self.assertEqual(ckit_misc.getArgv(), sys.argv)
                self.assertEqual(self.free.call_count, 2)

    def test_api_exception_does_not_free_or_cache(self):
        failure = OSError("API call failed")
        self.parse.side_effect = failure
        with self.assertRaises(OSError) as raised:
            ckit_misc.getArgv()
        self.assertIs(raised.exception, failure)
        self.assertIsNone(ckit_misc._argv)
        self.free.assert_not_called()

    def test_zero_count_keeps_empty_list_contract_and_frees_buffer(self):
        self.values = []
        result = ckit_misc.getArgv()
        self.assertEqual(result, [])
        self.assertIs(ckit_misc.getArgv(), result)
        self.assert_freed_once()


class ReaderLockFaultTests(unittest.TestCase):
    def setUp(self):
        self.handle = self.enterContext(patch.object(ckit_misc.msvcrt, "get_osfhandle", return_value=123))
        self.lock = self.enterContext(patch.object(ctypes.windll.kernel32, "LockFileEx", return_value=1))
        self.unlock = self.enterContext(patch.object(ctypes.windll.kernel32, "UnlockFileEx", return_value=1))

    def test_success_keeps_lock_and_unlock_contract_without_output(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            lock = ckit_misc.FileReaderLock(7)
            self.assertTrue(lock.locked)
            self.assertEqual(lock.handle, 123)
            self.assertIsNone(lock.unlock())
            self.assertFalse(lock.locked)
            self.assertIsNone(lock.unlock())
        self.assertEqual(output.getvalue(), "")
        self.handle.assert_called_once_with(7)
        self.assertEqual(self.lock.call_args.args[:5], (123, 1, 0, 0xFFFFFFFF, 0xFFFFFFFF))
        self.unlock.assert_called_once()

    def test_failure_propagates_same_winerror_and_caller_can_catch_silently(self):
        self.lock.return_value = 0
        failure = ctypes.WinError(33)
        output = io.StringIO()
        with patch.object(ctypes, "WinError", return_value=failure), \
             redirect_stdout(output), redirect_stderr(output):
            with self.assertRaises(OSError) as raised:
                ckit_misc.FileReaderLock(7)
            self.assertIs(raised.exception, failure)
            caught = []
            try:
                ckit_misc.FileReaderLock(7)
            except OSError as error:
                caught.append(error)
        self.assertEqual(caught, [failure])
        self.assertEqual(output.getvalue(), "")
        self.unlock.assert_not_called()


class MiscResourcesWindowsTests(unittest.TestCase):
    def test_real_command_line_matches_sys_argv_and_caches(self):
        with patch.object(ckit_misc, "_argv", None), patch.object(sys, "argv", PROCESS_ARGV):
            result = ckit_misc.getArgv()
            self.assertEqual(result, sys.argv)
            self.assertIs(ckit_misc.getArgv(), result)

    def test_real_lock_success_contention_caught_without_output_and_recovery(self):
        # Independent handles to the same file produce a real lock conflict.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock.dat"
            path.write_bytes(b"data")
            with path.open("rb") as holder, path.open("rb") as reader:
                handle = ckit_misc.msvcrt.get_osfhandle(holder.fileno())
                overlapped = ckit_misc.FileReaderLock.OVERLAPPED()
                kernel = ctypes.windll.kernel32
                if not kernel.LockFileEx(handle, 3, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)):
                    raise ctypes.WinError()
                output = io.StringIO()
                try:
                    with redirect_stdout(output), redirect_stderr(output), self.assertRaises(OSError) as raised:
                        ckit_misc.FileReaderLock(reader.fileno())
                    self.assertEqual(raised.exception.winerror, 33)
                    self.assertEqual(output.getvalue(), "")
                finally:
                    if not kernel.UnlockFileEx(handle, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)):
                        raise ctypes.WinError()
                lock = ckit_misc.FileReaderLock(reader.fileno())
                self.assertTrue(lock.locked)
                lock.unlock()
                self.assertFalse(lock.locked)


if __name__ == "__main__":
    unittest.main()
