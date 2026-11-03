"""Inspect real pyauto's ShellExecuteEx boundary; only the EXE probe is actually launched."""
import ctypes as c
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes as w
from pathlib import Path

import native_test_support

if "--package" in sys.argv:
    index = sys.argv.index("--package")
    native_test_support.RUN_DIR = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]

from test_native_shell import CALL, P, executable_thunk, imports, replace_import

import pyauto


class ShellExecuteInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("mask", w.ULONG), ("hwnd", P),
                ("verb", w.LPCWSTR), ("file", w.LPCWSTR), ("parameters", w.LPCWSTR),
                ("directory", w.LPCWSTR), ("show", c.c_int), ("instance", P),
                ("idlist", P), ("cls", w.LPCWSTR), ("key", P), ("hotkey", w.DWORD),
                ("icon", P), ("process", P)]


class ShellExecuteTests(unittest.TestCase):
    def test_flags_and_all_public_arguments_from_thread_without_message_loop(self):
        self.assertEqual(Path(pyauto.pyautocore.__file__).resolve(),
                         native_test_support.RUN_DIR / "lib/pyautocore.pyd")
        calls, failures = [], []
        @CALL(w.BOOL, c.POINTER(ShellExecuteInfo))
        def execute(pointer):
            info = pointer.contents
            calls.append((info.size, info.mask, info.verb, info.file, info.parameters,
                          info.directory, info.show, info.hwnd, info.process))
            return 1
        def launch():
            try:
                for verb in (None, "open", "runas"):
                    for target in (r"C:\tools\app.exe", r"Z:\temp\日本語 file.txt", "https://example.invalid/"):
                        for mode in (None, "normal", "minimized", "maximized"):
                            self.assertIsNone(pyauto.shellExecute(verb, target, '  "a b" ""  ', r"C:\work", mode))
            except BaseException as error:  # noqa: BLE001  # Surface worker failures in the test thread.
                failures.append(error)
        with replace_import("ShellExecuteExW", execute, module=pyauto.pyautocore):
            worker = threading.Thread(target=launch)
            worker.start()
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(calls), 36)
        for size, mask, verb, file, params, directory, show, hwnd, process in calls:
            self.assertEqual(size, c.sizeof(ShellExecuteInfo))
            self.assertEqual(mask, 0x0c | 0x400 | 0x100)
            self.assertEqual(params, '  "a b" ""  ')
            self.assertEqual(directory, r"C:\work")
            self.assertIsNone(hwnd)
            self.assertIsNone(process)
        self.assertEqual([call[6] for call in calls[:4]], [1, 1, 2, 3])

    def test_shell_errors_survive_gil_restore_including_uac_cancel(self):
        import struct
        slots = imports(pyauto.pyautocore)
        restore = P.from_address(slots["PyEval_RestoreThread"]).value
        set_error = c.cast(c.WinDLL("kernel32").SetLastError, P).value
        # Native thunks are necessary while RestoreThread has no GIL.
        clobber = (b"\x48\x83\xec\x28\x48\xb8" + struct.pack("<Q", restore)
                   + b"\xff\xd0\xb9\x05\x00\x00\x00\x48\xb8" + struct.pack("<Q", set_error)
                   + b"\xff\xd0\x48\x83\xc4\x28\xc3")
        for code in (2, 5, 1223):
            fail = (b"\x48\x83\xec\x28\xb9" + struct.pack("<I", code) + b"\x48\xb8"
                    + struct.pack("<Q", set_error) + b"\xff\xd0\x31\xc0\x48\x83\xc4\x28\xc3")
            with self.subTest(code=code), executable_thunk(fail) as failed, \
                    executable_thunk(clobber) as restored, \
                    replace_import("ShellExecuteExW", failed, module=pyauto.pyautocore), \
                    replace_import("PyEval_RestoreThread", restored, module=pyauto.pyautocore), \
                    self.assertRaises(OSError) as raised:
                pyauto.shellExecute("runas", "unused.exe")
            self.assertEqual(raised.exception.winerror, code)

    def test_real_exe_launch_does_not_wait_for_process_exit(self):
        api = c.WinDLL("kernel32")
        api.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
        api.OpenProcess.restype = P
        api.WaitForSingleObject.argtypes = (P, w.DWORD)
        api.CloseHandle.argtypes = (P,)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            output, release, finished = (folder / name for name in ("started.json", "release", "finished"))
            script = folder / "probe.py"
            script.write_text(
                "import json,os,pathlib,sys,time\n"
                "out,release,finished=map(pathlib.Path,sys.argv[1:4])\n"
                "temporary=out.with_suffix('.tmp')\n"
                "temporary.write_text(json.dumps({'cwd':os.getcwd(),'args':sys.argv[4:],'pid':os.getpid()}),encoding='utf-8')\n"
                "temporary.replace(out)\n"
                "deadline=time.monotonic()+8\n"
                "while not release.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
                "finished.touch()\n", encoding="utf-8")
            args = [str(script), str(output), str(release), str(finished), "日本語 file.txt", ""]
            process = None
            try:
                pyauto.shellExecute(None, str(Path(sys.executable).with_name("pythonw.exe")),
                                    subprocess.list2cmdline(args), directory)
                deadline = time.monotonic() + 5
                while not output.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(output.exists())
                result = json.loads(output.read_text(encoding="utf-8"))
                process = api.OpenProcess(0x100000, False, result.pop("pid"))
                self.assertTrue(process)
                self.assertEqual(api.WaitForSingleObject(process, 0), 258)  # Still alive after API return.
                self.assertFalse(finished.exists())
                self.assertEqual(result, {"cwd": directory, "args": ["日本語 file.txt", ""]})
            finally:
                release.touch()
                if process:
                    try:
                        self.assertEqual(api.WaitForSingleObject(process, 5000), 0)
                    finally:
                        api.CloseHandle(process)

    def test_real_document_and_url_shell_commands_with_isolated_class(self):
        import uuid
        import winreg

        # A unique test class changes no file/URL defaults; CLASSKEY applies to this call only.
        key_name = "Software\\Classes\\ReCraftLaunch.Test." + uuid.uuid4().hex
        api = c.WinDLL("kernel32")
        api.WaitForSingleObject.argtypes = (P, w.DWORD)
        api.CloseHandle.argtypes = (P,)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            document = folder / "日本語 document.txt"
            document.write_text("document probe", encoding="utf-8")
            output = folder / "result.json"
            script = folder / "probe.py"
            script.write_text(
                "import json,pathlib,sys\n"
                "target=sys.argv[2]; path=pathlib.Path(target)\n"
                "result={'target':target,'content':path.read_text(encoding='utf-8') if path.is_file() else None}\n"
                "pathlib.Path(sys.argv[1]).write_text(json.dumps(result),encoding='utf-8')\n", encoding="utf-8")
            command = subprocess.list2cmdline([str(Path(sys.executable).with_name("pythonw.exe")),
                                               str(script), str(output)]) + ' "%1"'
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_name)
            try:
                with winreg.CreateKey(key, "shell\\open\\command") as child:
                    winreg.SetValueEx(child, "", 0, winreg.REG_SZ, command)
                handles, failures, masks = [], [], []
                original = CALL(w.BOOL, c.POINTER(ShellExecuteInfo))(
                    P.from_address(imports(pyauto.pyautocore)["ShellExecuteExW"]).value)
                def launch(pointer):
                    try:
                        info = pointer.contents
                        masks.append(info.mask)
                        info.mask |= 0x03 | 0x40  # CLASSKEY and test-owned process handle.
                        info.key = int(key)
                        result = original(pointer)
                        if info.process:
                            handles.append(info.process)
                        return result
                    except BaseException as error:  # noqa: BLE001  # Surface callback failures after restoration.
                        failures.append(error)
                        return 0
                callback = CALL(w.BOOL, c.POINTER(ShellExecuteInfo))(launch)
                for target, content in ((str(document), "document probe"),
                                        ("https://example.invalid/document?x=1", None)):
                    handles.clear()
                    failures.clear()
                    masks.clear()
                    try:
                        with replace_import("ShellExecuteExW", callback, module=pyauto.pyautocore):
                            pyauto.shellExecute(None, target, "", directory)
                        self.assertEqual(failures, [])
                        self.assertEqual(masks, [0x50c])
                        self.assertTrue(handles)
                        self.assertEqual(api.WaitForSingleObject(handles[0], 5000), 0)
                        self.assertEqual(json.loads(output.read_text(encoding="utf-8")),
                                         {"target": target, "content": content})
                        output.unlink()
                    finally:
                        for handle in handles:
                            api.WaitForSingleObject(handle, 5000)
                            api.CloseHandle(handle)
            finally:
                key.Close()
                for suffix in ("\\shell\\open\\command", "\\shell\\open", "\\shell", ""):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_name + suffix)
                    except FileNotFoundError:
                        pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
