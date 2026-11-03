"""Real native string boundaries on a private Windows desktop; --package DIR.

IAT substitutions capture OS arguments and suppress Shell execution. Conversion
faults and pending-error counters run in native thunks, without Python callbacks.
"""
import ctypes as c
import faulthandler
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
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
    import ckit
    import pyauto

from test_native_pyauto_ownership import count_calls as count_pointer_calls
from test_native_shell import CALL, P, executable_thunk, imports, replace_import

import ckit
import clnch_native
import pyauto
from ckit import ckitcore

GOOD = ("", "abc", "日本語", "a😀𠀀z")
BAD_NUL = ("\0abc", "ab\0cd", "abc\0", "a\0b\0c")


@contextmanager
def column_failure(name, at=1, *, marker=None):
    # Count in native code; preserve pending exceptions and the original arguments.
    count = c.c_size_t()
    slots = imports(ckitcore)
    original = P.from_address(slots[name]).value
    error = c.cast(c.pythonapi.PyErr_NoMemory, P).value
    code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(count)) + b"\x48\xff\x00"
            + b"\x48\x81\x38" + struct.pack("<I", at) + b"\x75\x0c"
            + b"\x48\xb8" + struct.pack("<Q", error) + b"\xff\xe0")
    if marker is None:
        code += b"\x48\xb8" + struct.pack("<Q", original) + b"\xff\xe0"
    else:
        # Py_NewRef returns a new owned reference to the test marker.
        newref = c.cast(c.pythonapi.Py_NewRef, P).value
        code += (b"\x48\xb9" + struct.pack("<Q", id(marker))
                 + b"\x48\xb8" + struct.pack("<Q", newref) + b"\xff\xe0")
    with executable_thunk(code) as thunk, replace_import(name, thunk, module=ckitcore):
        yield count


@contextmanager
def column_allocations():
    slots = imports(ckitcore)
    with ExitStack() as stack:
        allocated = stack.enter_context(count_pointer_calls(slots["malloc"]))
        freed = stack.enter_context(count_pointer_calls(slots["_free_dbg" if "_free_dbg" in slots else "free"]))
        wide_freed = stack.enter_context(count_pointer_calls(slots["PyMem_Free"]))
        tuples_freed = stack.enter_context(count_pointer_calls(slots["_Py_Dealloc"]))
        yield allocated, freed, wide_freed, tuples_freed


class ShellInfo(c.Structure):
    _fields_ = [("size", w.DWORD), ("mask", w.ULONG), ("hwnd", P),
               ("verb", w.LPCWSTR), ("file", w.LPCWSTR), ("param", w.LPCWSTR),
               ("directory", w.LPCWSTR), ("show", c.c_int), ("instance", P),
               ("idlist", P), ("class_name", w.LPCWSTR), ("class_key", P),
               ("hotkey", w.DWORD), ("icon", P), ("process", P)]


@contextmanager
def count_calls(module, name):
    count = c.c_size_t()
    # Count even when a Python exception is pending; return nonzero success.
    code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(count))
            + b"\x48\xff\x00\xb8\x01\x00\x00\x00\xc3")
    with executable_thunk(code) as thunk, replace_import(name, thunk, module=module):
        yield count


@contextmanager
def conversion_error(module):
    address = c.cast(c.pythonapi.PyErr_NoMemory, P).value
    with (executable_thunk(b"\x48\xb8" + struct.pack("<Q", address) + b"\xff\xe0") as thunk,
          replace_import("PyUnicode_AsWideCharString", thunk, module=module)):
        yield


class NativeStringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ckit.registerWindowClass("NativeStrings" + uuid.uuid4().hex)

    def window(self, **kwargs):
        window = ckit.Window(x=0, y=0, width=160, height=80, show=False, **kwargs)
        self.addCleanup(window.destroy)
        return window

    def plane(self, window):
        plane = ckit.TextPlane(window, (0, 0), (160, 80), 0)
        self.addCleanup(plane.destroy)
        plane.setFont(ckit.Font("ＭＳ ゴシック", 16))
        return plane

    def test_selected_native_modules(self):
        for module in (ckitcore, pyauto.pyautocore, clnch_native):
            expected = native_test_support.RUN_DIR / "lib" / (module.__name__.split(".")[-1] + ".pyd")
            self.assertEqual(Path(module.__file__).resolve(), expected.resolve())
        if PACKAGE:
            for module in (ckit, pyauto):
                self.assertTrue(str(module.__file__).startswith(str(PACKAGE / "library.zip")))

    def test_ckit_normal_unicode_and_empty(self):
        window = self.window()
        plane = self.plane(window)
        for text in GOOD:
            with self.subTest(text=text):
                node = ckit.MenuNode(name=text, text=text)
                self.assertEqual(node.name, text)
                node.name = text
                window.setTitle(text)
                self.assertEqual(pyauto.Window.fromHWND(window.getHWND()).getText(), text)
                columns = plane.getStringColumns(text)
                self.assertEqual(len(columns), len(text.encode("utf-16-le")) // 2 + 1)
                self.assertEqual(columns[0], 0)
                self.assertEqual(columns[-1], plane.getStringWidth(text))
                plane.putString(0, 0, 20, 1, ckit.Attribute(fg=(255, 255, 255)), text)
        self.assertEqual(plane.getStringWidth(""), 0)
        self.assertEqual(plane.getStringWidth("abc"), 3)

    def test_columns_allocation_failures_release_ownership_and_recover(self):
        plane = self.plane(self.window())
        text = "a" * 400
        expected = tuple(range(401))
        marker = int("12345678901234567890")
        baseline = sys.getrefcount(marker)
        for name, at in (("PyUnicode_AsWideCharString", 1), ("PyTuple_New", 1),
                         ("PyLong_FromLong", 1), ("PyLong_FromLong", 2),
                         ("PyLong_FromLong", 127), ("PyLong_FromLong", 401)):
            with self.subTest(api=name, at=at):
                for _ in range(20):
                    with (column_allocations() as (allocated, freed, wide_freed, tuples_freed),
                          column_failure(name, at, marker=marker if name == "PyLong_FromLong" else None) as calls):
                        with self.assertRaises(MemoryError):
                            plane.getStringColumns(text)
                        self.assertEqual(calls.value, at)
                        self.assertEqual(allocated.value, freed.value)
                        self.assertEqual(wide_freed.value, int(name != "PyUnicode_AsWideCharString"))
                        self.assertEqual(tuples_freed.value, int(name == "PyLong_FromLong"))
                    self.assertEqual(sys.getrefcount(marker), baseline)
                    self.assertEqual(plane.getStringColumns(text), expected)

    def test_columns_native_array_failure_and_length_boundaries(self):
        plane = self.plane(self.window())
        sizes = []
        def fail(size):
            sizes.append(size)
        malloc = CALL(P, c.c_size_t)(fail)
        with replace_import("malloc", malloc, module=ckitcore), self.assertRaises(MemoryError):
            plane.getStringColumns("abc")
        self.assertEqual(sizes, [16])
        # Substitute only this extension's length query, without allocating GB strings.
        for length in (2**31 - 1, 2**31, 2**32):
            with self.subTest(length=length):
                sizes.clear()
                query = CALL(c.c_size_t, P)(lambda pointer, length=length: length)
                with (replace_import("wcslen", query, module=ckitcore),
                      replace_import("malloc", malloc, module=ckitcore),
                      self.assertRaises(OverflowError)):
                    plane.getStringColumns("abc")
                self.assertEqual(sizes, [])
        sizes.clear()
        query = CALL(c.c_size_t, P)(lambda pointer: 2**31 - 2)
        with (replace_import("wcslen", query, module=ckitcore),
              replace_import("malloc", malloc, module=ckitcore), self.assertRaises(MemoryError)):
            plane.getStringColumns("abc")
        self.assertEqual(sizes, [4 * (2**31 - 1)])
        self.assertEqual(plane.getStringColumns("abc"), (0, 1, 2, 3))

    def test_columns_unicode_large_text_and_integer_width_boundaries(self):
        plane = self.plane(self.window())
        for text in (*GOOD, "a\ud800b", "a\udc00b", "a" * 100000):
            columns = plane.getStringColumns(text)
            self.assertEqual(len(columns), len(text.encode("utf-16-le", "surrogatepass")) // 2 + 1)
            self.assertEqual(columns[0], 0)
            self.assertEqual(columns[-1], plane.getStringWidth(text))
        for measure in (plane.getStringColumns, plane.getStringWidth):
            for tab in (0, -1):
                with self.assertRaises(ValueError):
                    measure("a", tab)
            for argument in (2**31, -2**31 - 1):
                with self.assertRaises(OverflowError):
                    measure("a", argument)
                with self.assertRaises(OverflowError):
                    measure("a", 4, argument)
            for text in ("\t\t", "\ta", "\t全"):
                with self.assertRaises(OverflowError):
                    measure(text, 2**31 - 1)
            self.assertEqual(measure("a"), (0, 1) if measure == plane.getStringColumns else 1)
        self.assertEqual(plane.getStringColumns("\t", 2**31 - 1), (0, 2**31 - 1))
        self.assertEqual(plane.getStringColumns("\t", 2**31 - 1, -2**31), (0, 1))

    def test_ckit_rejects_nul_and_types_before_mutation(self):
        window = self.window(title="unchanged")
        plane = self.plane(window)
        node = ckit.MenuNode(name="unchanged")
        for text, exception in [(s, ValueError) for s in BAD_NUL] + [
                (None, TypeError), (1, TypeError), (b"abc", TypeError)]:
            with self.subTest(text=text):
                for operation in (plane.getStringWidth, plane.getStringColumns, window.setTitle,
                                  lambda s: ckit.MenuNode(name=s), lambda s: ckit.MenuNode(text=s),
                                  lambda s: ckit.Window(title=s), lambda s: ckit.TaskTrayIcon(title=s),
                                  lambda s: setattr(node, "name", s),
                                  lambda s: plane.putString(0, 0, 20, 1, ckit.Attribute(), s)):
                    with self.assertRaises(exception):
                        operation(text)
                self.assertEqual(node.name, "unchanged")
                self.assertEqual(pyauto.Window.fromHWND(window.getHWND()).getText(), "unchanged")
        with conversion_error(ckitcore), self.assertRaises(MemoryError):
            window.setTitle("valid")
        self.assertEqual(pyauto.Window.fromHWND(window.getHWND()).getText(), "unchanged")
        self.assertEqual(plane.getStringWidth("abc"), 3)

    def test_constructor_failures_exit_normally_in_child(self):
        arguments = [str(Path(__file__).resolve()),
                     "NativeStringTests.test_ckit_rejects_nul_and_types_before_mutation"]
        if PACKAGE:
            arguments += ["--package", str(PACKAGE)]
        code = ("import ctypes, runpy, sys; ctypes.WinDLL('kernel32').SetErrorMode(3); "
                "sys.path.insert(0, sys.argv[1]); sys.argv=sys.argv[2:]; "
                "runpy.run_path(sys.argv[0], run_name='__main__')")
        child = subprocess.run([sys.executable, "-B", "-c", code, str(Path(__file__).parent), *arguments],
                               capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)

    def test_pyauto_find_conversion_and_suppression(self):
        captured = []
        callback = CALL(P, w.LPCWSTR, w.LPCWSTR)(lambda name, title: captured.append((name, title)))
        with replace_import("FindWindowW", callback, module=pyauto.pyautocore):
            for text in GOOD:
                self.assertIsNone(pyauto.Window.find(text, text))
                self.assertEqual(captured[-1], (text, text))
            for value in (None, 1, b"abc", object()):
                self.assertIsNone(pyauto.Window.find(value, value))
                self.assertEqual(captured[-1], (None, None))
        with count_calls(pyauto.pyautocore, "FindWindowW") as count:
            for text in BAD_NUL:
                for args in ((text, "valid"), (None, text)):
                    with self.subTest(args=args), self.assertRaises(ValueError):
                        pyauto.Window.find(*args)
            with conversion_error(pyauto.pyautocore), self.assertRaises(MemoryError):
                pyauto.Window.find("valid", "valid")
            self.assertEqual(count.value, 0)
        window = self.window(title="日本語😀" + uuid.uuid4().hex)
        title = pyauto.Window.fromHWND(window.getHWND()).getText()
        self.assertEqual(pyauto.Window.find(None, title).getHWND(), window.getHWND())

    def test_shell_conversion_optional_values_and_suppression(self):
        captured = []
        def execute(pointer):
            info = pointer.contents
            captured.append((info.verb, info.file, info.param, info.directory, info.show))
            return 1
        callback = CALL(w.BOOL, c.POINTER(ShellInfo))(execute)
        with replace_import("ShellExecuteExW", callback, module=pyauto.pyautocore):
            for text in GOOD:
                self.assertIsNone(pyauto.shellExecute(text, text, text, text, "normal"))
                self.assertEqual(captured[-1], (text, text, text, text, 1))
            for value in (None, 1, b"abc", object()):
                self.assertIsNone(pyauto.shellExecute(value, "file", value, value, value))
                self.assertEqual(captured[-1], (None, "file", None, None, 1))
            self.assertIsNone(pyauto.shellExecute(None, "file"))
            for mode, show in (("", 1), ("normal", 1), ("minimized", 2), ("maximized", 3)):
                pyauto.shellExecute(None, "file", None, None, mode)
                self.assertEqual(captured[-1][-1], show)
        with count_calls(pyauto.pyautocore, "ShellExecuteExW") as count:
            for text in BAD_NUL:
                for index in range(5):
                    args = [None, "file", None, None, None]
                    args[index] = text
                    with self.subTest(index=index, text=text), self.assertRaises(ValueError):
                        pyauto.shellExecute(*args)
            with self.assertRaises(ValueError):
                pyauto.shellExecute(None, "file", None, None, "invalid")
            with conversion_error(pyauto.pyautocore), self.assertRaises(MemoryError):
                pyauto.shellExecute("open", "file", "param", "directory", "normal")
            self.assertEqual(count.value, 0)

    def test_clnch_paths_and_failure_before_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("abc", "日本語", "a😀𠀀z"):
                path = Path(directory) / name
                path.write_bytes(b"unchanged")
                self.assertEqual(clnch_native.findFile(str(path))[0][0], name)
                before = path.stat().st_mtime_ns
                with self.assertRaises(ValueError):
                    clnch_native.setFileTime(str(path) + "\0ignored", (2020, 1, 1, 0, 0, 0))
                self.assertEqual(path.stat().st_mtime_ns, before)
                self.assertEqual(path.read_bytes(), b"unchanged")
            for text in BAD_NUL:
                with self.subTest(text=text), self.assertRaises(ValueError):
                    clnch_native.findFile(text)
            for value in (None, 1, b"abc"):
                with self.subTest(value=value), self.assertRaises(TypeError):
                    clnch_native.findFile(value)

    def test_hook_attribute_names_reject_nul(self):
        hook = pyauto.Hook()
        try:
            for name in ("keydown", "keyup", "mousedown", "mouseup", "mousedblclk", "mousemove",
                         "mousewheel", "mousehorizontalwheel", "clipboard"):
                callback = lambda *args: None
                setattr(hook, name, callback)
                for bad in ("\0" + name, name + "\0", name + "\0ignored\0"):
                    with self.subTest(name=bad):
                        with self.assertRaises(ValueError):
                            getattr(hook, bad)
                        with self.assertRaises(ValueError):
                            setattr(hook, bad, None)
                        self.assertIs(getattr(hook, name), callback)
        finally:
            hook.destroy()

    def test_existing_font_rejection_and_line_nul_preservation(self):
        for text in BAD_NUL:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    ckit.Font(text, 16)
                line = ckit.Line(text + "😀\r\n")
                self.assertEqual(line.s, text + "😀")
                self.assertEqual(line.end, "\r\n")
                line.s = text
                line.end = "\0\n"
                self.assertEqual(line.s, text)
                self.assertEqual(line.end, "\n")


class NativeNarrowStringTests(unittest.TestCase):
    def test_both_real_source_implementations(self):
        root = native_test_support.ROOT
        vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
        install = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-version",
            "[18.0,19.0)", "-property", "installationPath"], text=True).strip()
        vcvars = Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
        runtime = Path(sys.executable).parent
        environment = dict(os.environ, PYTHONHOME=str(runtime))
        environment["PATH"] = str(runtime) + os.pathsep + environment["PATH"]
        options = "/MDd /D_DEBUG /Od" if native_test_support.CONFIGURATION == "Debug" else "/MD /O2 /DNDEBUG"
        with tempfile.TemporaryDirectory(prefix="recraft-native-strings-") as temporary:
            for directory in ("ckit/ckitcore", "clnch_native"):
                with self.subTest(source=directory, configuration=native_test_support.CONFIGURATION):
                    source = root / directory
                    executable = Path(temporary) / "strings.exe"
                    command = (f'""{vcvars}" >nul && cl /nologo /EHsc /std:c++17 /utf-8 {options} '
                               f'/I"{source}" /I"{runtime / "include"}" '
                               f'"{root / "tools/native_strings_probe.cpp"}" '
                               f'"{source / "pythonutil.cpp"}" "{source / "strutil.cpp"}" '
                               f'/Fe:"{executable}" /link /LIBPATH:"{runtime / "libs"}" python315.lib"')
                    built = subprocess.run(f'"{os.environ["COMSPEC"]}" /d /s /c {command}', cwd=temporary,
                                           capture_output=True, text=True, timeout=30, check=False)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    tested = subprocess.run([str(executable)], env=environment, cwd=temporary,
                                            capture_output=True, text=True, timeout=30, check=False)
                    self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
                    self.assertIn("Native narrow/string buffer checks OK", tested.stdout)
                    print(f"{directory}: {tested.stdout.strip()}")


if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
