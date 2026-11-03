"""Real clnch_native enumShare and COM lifetime regressions; no remote server.

IAT faults affect only this process. --package DIR selects the final PYD.
"""
import ctypes as c
import faulthandler
import struct
import sys
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

from test_native_shell import (
    CALL,
    P,
    executable_thunk,
    imports,
    replace_import,
    replace_pointer,
)

import clnch_native as native


class Share(c.Structure):
    _fields_ = [("name", w.LPWSTR), ("kind", w.DWORD), ("remark", w.LPWSTR),
               ("permissions", w.DWORD), ("maximum", w.DWORD), ("current", w.DWORD),
               ("path", w.LPWSTR), ("password", w.LPWSTR), ("reserved", w.DWORD),
               ("security", P)]


ENUM = CALL(w.DWORD, w.LPWSTR, w.DWORD, c.POINTER(P), w.DWORD,
            c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.DWORD))


@contextmanager
def memory_error(name, integer_result=False, skip=0):
    address = c.cast(c.pythonapi.PyErr_NoMemory, P).value
    code = b"\x48\xb8" + struct.pack("<Q", address) + b"\xff\xe0"
    if integer_result:
        code = (b"\x48\x83\xec\x28\x48\xb8" + struct.pack("<Q", address)
                + b"\xff\xd0\xb8\xff\xff\xff\xff\x48\x83\xc4\x28\xc3")
    remaining = c.c_size_t(skip)
    if skip:
        original = P.from_address(imports(native)[name]).value
        code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(remaining))
                + b"\x48\x83\x38\x00\x74\x0f\x48\xff\x08\x48\xb8"
                + struct.pack("<Q", original) + b"\xff\xe0" + code)
    with executable_thunk(code) as thunk, replace_import(name, thunk):
        yield


@contextmanager
def shares(statuses=(0,), error_buffer=False):
    calls = []
    count, records = c.c_size_t(), (P * 1024)()
    class Freed:
        def __len__(self):
            return count.value
        def __eq__(self, other):
            return list(records[:count.value]) == other
    freed = Freed()
    buffers = [(Share * 1)(Share("共有😀", 3, None, 7, 8, 2, "C:\\共有", None, 0, None))
               for _ in statuses]
    def enumerate_shares(server, level, output, maximum, read, total, resume):
        index = resume[0]
        calls.append((server, level, maximum, resume[0]))
        status = statuses[index]
        output[0] = c.addressof(buffers[index]) if status in (0, 234) or error_buffer else None
        read[0], total[0], resume[0] = 1, len(statuses), index + 1
        return status
    # Record frees in native code: a Python callback would consume pending errors.
    code = (b"\x48\xb8" + struct.pack("<Q", c.addressof(count))
            + b"\x48\x8b\x10\x48\xff\x00\x48\xb8"
            + struct.pack("<Q", c.addressof(records)) + b"\x48\x89\x0c\xd0\x31\xc0\xc3")
    with (replace_import("NetShareEnum", ENUM(enumerate_shares)),
          executable_thunk(code) as free, replace_import("NetApiBufferFree", free)):
        yield calls, freed, buffers


def method(pointer, index, result=w.ULONG, args=()):
    table = P.from_address(pointer).value
    return c.PYFUNCTYPE(result, P, *args)(P.from_address(table + index * 8).value)


def release(pointer):
    return method(pointer, 2)(pointer)


@contextmanager
def poison_deleted_object(pointer):
    # Run the real destructor, but defer CRT free and poison the former refcount.
    # The old Release read this value after delete; the fixed one must return 0.
    slots = imports(native)
    name = "free" if "free" in slots else "_free_dbg"
    original = P.from_address(slots[name]).value
    count = c.c_size_t()
    # cmp rcx, object; jne tail-call original; overwrite [rcx+8]; count; ret.
    poisoned = (b"\xc7\x41\x08\x5a\x5a\x5a\x5a\x48\xb8"
                + struct.pack("<Q", c.addressof(count)) + b"\x48\xff\x00\xc3")
    code = (b"\x48\xb8" + struct.pack("<Q", pointer) + b"\x48\x39\xc1\x75"
            + bytes([len(poisoned)]) + poisoned + b"\x48\xb8"
            + struct.pack("<Q", original) + b"\xff\xe0")
    try:
        with executable_thunk(code) as thunk, replace_pointer(slots[name], thunk):
            yield count
    finally:
        if count.value:
            args = (P,) if name == "free" else (P, c.c_int)
            c.PYFUNCTYPE(None, *args)(original)(pointer, *(() if name == "free" else (1,)))


class NativeClnchLifetimeTests(unittest.TestCase):
    def test_origin(self):
        expected = native_test_support.RUN_DIR / "lib/clnch_native.pyd"
        self.assertEqual(Path(native.__file__).resolve(), expected.resolve())

    def test_invalid_types_do_not_enumerate(self):
        class Stringable:
            def __str__(self):
                raise AssertionError("must not coerce")
        with shares() as (calls, freed, _):
            for value in (None, 123, 1.5, b"server", [], {}, object(), Stringable()):
                baseline = sys.getrefcount(value)
                for _ in range(50):
                    with self.assertRaisesRegex(TypeError, "must be string or unicode"):
                        native.enumShare(value)
                self.assertEqual(sys.getrefcount(value), baseline)
            self.assertEqual((calls, freed), ([], []))

    def test_conversion_and_list_creation_fail_before_enumeration(self):
        for fault in ("PyUnicode_AsWideCharString", "PyList_New"):
            with self.subTest(fault=fault), shares() as (calls, freed, _):
                with memory_error(fault), self.assertRaises(MemoryError):
                    native.enumShare("\\\\server")
                self.assertEqual((calls, freed), ([], []))
                self.assertEqual(len(native.enumShare("")), 1)
                self.assertEqual((len(calls), len(freed)), (1, 1))

    def test_unicode_empty_subclass_and_pagination(self):
        class Server(str):
            def __str__(self):
                raise AssertionError("must not coerce")
        row = ("共有😀", 3, None, 7, 8, 2, "C:\\共有", None)
        for server in ("", "\\\\server", "\\\\サーバー😀", Server("\\\\server")):
            with self.subTest(server=repr(server)), shares((234, 0)) as (calls, freed, buffers):
                self.assertEqual(native.enumShare(servername=server), [row, row])
                self.assertEqual(calls, [(server, 502, 0xffffffff, 0),
                                         (server, 502, 0xffffffff, 1)])
                self.assertEqual(freed, [c.addressof(buffer) for buffer in buffers])

    def test_failures_release_partial_list_items_and_buffers(self):
        incref = c.pythonapi.Py_IncRef
        incref.argtypes = (c.py_object,)
        result, item = [], ("tracked",)
        def new_list(size):
            incref(result)
            return id(result)
        def new_item(*unused):
            incref(item)
            return id(item)
        for fault in ("Py_BuildValue", "PyList_Append"):
            baseline = sys.getrefcount(result), sys.getrefcount(item)
            with self.subTest(fault=fault), shares((234, 0)) as (calls, freed, _), ExitStack() as stack:
                stack.enter_context(replace_import("PyList_New", c.PYFUNCTYPE(P, c.c_ssize_t)(new_list)))
                if fault == "PyList_Append":
                    stack.enter_context(replace_import("Py_BuildValue", c.PYFUNCTYPE(P, P)(new_item)))
                stack.enter_context(memory_error(fault, integer_result=fault == "PyList_Append"))
                for _ in range(50):
                    with self.assertRaises(MemoryError):
                        native.enumShare("")
                self.assertEqual((len(calls), len(freed)), (50, 50))
            self.assertEqual((sys.getrefcount(result), sys.getrefcount(item)), baseline)
        # Fail only after a successful page: the partial result must also be released.
        for fault in ("Py_BuildValue", "PyList_Append"):
            baseline = sys.getrefcount(result)
            with shares((234, 0)) as (calls, freed, _), ExitStack() as stack:
                stack.enter_context(replace_import("PyList_New", c.PYFUNCTYPE(P, c.c_ssize_t)(new_list)))
                stack.enter_context(memory_error(fault, integer_result=fault == "PyList_Append", skip=1))
                with self.assertRaises(MemoryError):
                    native.enumShare("")
                self.assertEqual((len(calls), len(freed)), (2, 2))
                self.assertEqual(len(result), 1)
            self.assertEqual(sys.getrefcount(result), baseline)
            result.clear()
        for statuses in ((5,), (234, 5)):
            with shares(statuses, error_buffer=True) as (calls, freed, buffers):
                with self.assertRaises(OSError) as error:
                    native.enumShare("")
                self.assertEqual(error.exception.winerror, 5)
                self.assertEqual(len(calls), len(statuses))
                self.assertEqual(freed, [c.addressof(buffer) for buffer in buffers])

    def test_real_local_netapi_result(self):
        api = c.WinDLL("netapi32")
        api.NetShareEnum.argtypes, api.NetShareEnum.restype = ENUM._argtypes_, w.DWORD
        api.NetApiBufferFree.argtypes = (P,)
        output, read, total, resume = P(), w.DWORD(), w.DWORD(), w.DWORD()
        expected = []
        while True:
            status = api.NetShareEnum("", 502, c.byref(output), 0xffffffff,
                                      c.byref(read), c.byref(total), c.byref(resume))
            try:
                if status in (0, 234):
                    rows = c.cast(output, c.POINTER(Share))
                    expected.extend(tuple(w.LONG(getattr(rows[i], field)).value
                                          if field in ("kind", "permissions", "maximum", "current")
                                          else getattr(rows[i], field) for field in
                                          ("name", "kind", "remark", "permissions", "maximum",
                                           "current", "path", "password")) for i in range(read.value))
            finally:
                if output:
                    api.NetApiBufferFree(output)
                output = P()
            if status != 234:
                break
        if status:
            with self.assertRaises(OSError) as error:
                native.enumShare("")
            self.assertEqual(error.exception.winerror, status)
        else:
            self.assertEqual(native.enumShare(""), expected)
        print(f"local NetShareEnum status={status}, rows={len(expected)}")

    def test_real_com_reference_transitions_and_final_release(self):
        objects, errors = [], []
        def drag(data, source, effects, output):
            try:
                for pointer in (data, source):
                    self.assertEqual(method(pointer, 1)(pointer), 2)
                    objects.append(pointer)
                enum = P()
                self.assertEqual(method(data, 8, w.LONG, (w.DWORD, c.POINTER(P)))(
                    data, 1, c.byref(enum)), 0)
                objects.append(enum.value)
            except BaseException as error:  # noqa: BLE001 - report ctypes callback failures.
                errors.append(error)
            return 0x40101  # DRAGDROP_S_CANCEL; no physical drag or target.
        with replace_import("DoDragDrop", CALL(w.LONG, P, P, w.DWORD, c.POINTER(w.DWORD))(drag)):
            self.assertIsNone(native.doDragAndDrop(["C:\\lifetime-test.txt"]))
        self.assertEqual(errors, [])
        self.assertEqual(len(objects), 3)
        for pointer, iid in zip(objects, ("0000010e", "00000121", "00000103"), strict=True):
            with self.subTest(interface=iid):
                query = method(pointer, 0, w.LONG, (P, c.POINTER(P)))
                for supported in (iid, "00000000"):
                    guid = c.create_string_buffer(uuid.UUID(supported + "-0000-0000-c000-000000000046").bytes_le)
                    out = P()
                    self.assertEqual(query(pointer, guid, c.byref(out)), 0)
                    self.assertEqual(out.value, pointer)
                    self.assertEqual(release(out.value), 1)
                out = P(1)
                guid = c.create_string_buffer(uuid.UUID("00000001-0000-0000-c000-000000000046").bytes_le)
                self.assertEqual(query(pointer, guid, c.byref(out)), -2147467262)
                self.assertIsNone(out.value)
                for expected in (2, 3, 4):
                    self.assertEqual(method(pointer, 1)(pointer), expected)
                for expected in (3, 2, 1):
                    self.assertEqual(release(pointer), expected)
                with poison_deleted_object(pointer) as freed:
                    self.assertEqual(release(pointer), 0)
                self.assertEqual(freed.value, 1)


if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    unittest.main(verbosity=2)
