"""Ordinary INI failure safety and real Windows locking checks. Run with -B."""
import configparser
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "clnch"), str(RUN_DIR / "lib")]
import clnch_ini


class IniSaveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT / "build")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.path = self.directory / "設定.ini"
        self.lock_path = Path(str(self.path) + ".lock")
        self.old = b"[OTHER]\r\nkeep = original\r\n\r\n"
        self.path.write_bytes(self.old)
        parser = configparser.RawConfigParser()
        parser.read_string("[OTHER]\nkeep = original\n")
        parser["INPUT"] = {"value": "日本語😀 100%", "paths": "C:\\one\nD:\\two", "count": "42"}
        for name, value in (("ini_filename", str(self.path)), ("ini", parser), ("dirty", True),
                            ("read_failed", False)):
            patcher = patch.object(clnch_ini, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.errors = []
        self.mutex_names = set()
        create = clnch_ini._winapi.CreateMutexW
        def create_mutex(attributes, owner, name):
            self.mutex_names.add(name)
            return create(attributes, owner, name)
        patcher = patch.object(clnch_ini._winapi, "CreateMutexW", side_effect=create_mutex)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(clnch_ini.clnch_debug, "printErrorInfo", side_effect=self.report)
        patcher.start()
        self.addCleanup(patcher.stop)

    def report(self):
        self.errors.append(sys.exception())
        self.assert_clean()

    def assert_clean(self):
        self.assertEqual(list(self.directory.glob("*.tmp")), [])
        self.assertFalse(self.lock_path.exists())
        for name in self.mutex_names:
            handle = clnch_ini._winapi.OpenMutexW(0x100000, False, name)
            if handle:
                clnch_ini._winapi.CloseHandle(handle)
                self.fail("INI mutex handle was left open")
        # Windows refuses this if any ordinary INI handle is still open.
        if self.path.exists():
            moved = self.path.with_suffix(".moved")
            self.path.rename(moved)
            moved.rename(self.path)

    def assert_failed(self, exists=True):
        self.assertEqual(len(self.errors), 1)
        self.assertTrue(clnch_ini.dirty)
        self.assertEqual(self.path.read_bytes() if exists else None, self.old if exists else None)
        if not exists:
            self.assertFalse(self.path.exists())
        self.assert_clean()

    def test_uninitialized_parser_keeps_defaults_errors_and_write_state(self):
        cases = (("get", ("S", "key"), "get"),
                 ("getint", ("S", "key"), "getint"),
                 ("set", ("S", "key", "value"), "get"),
                 ("setint", ("S", "key", 1), "getint"),
                 ("remove_section", ("S",), "remove_section"),
                 ("remove_option", ("S", "key"), "remove_option"))
        with patch.object(clnch_ini, "ini", None), patch.object(clnch_ini, "dirty", False):
            self.assertEqual(clnch_ini.get("S", "key", "fallback"), "fallback")
            self.assertEqual(clnch_ini.getint("S", "key", 0), 0)
            for method, args, attribute in cases:
                with self.subTest(method=method), self.assertRaises(AttributeError) as raised:
                    getattr(clnch_ini, method)(*args)
                self.assertEqual(str(raised.exception),
                                 f"'NoneType' object has no attribute '{attribute}'")
                self.assertEqual(raised.exception.name, attribute)
                self.assertIsNone(raised.exception.obj)
                self.assertFalse(clnch_ini.dirty)
            self.assertIsNone(clnch_ini.write())
            self.assertEqual(self.errors, [])
            clnch_ini.dirty = True
            clnch_ini.write()
            self.assert_failed()
            self.assertIsInstance(self.errors[0], AttributeError)
            self.assertEqual(self.errors[0].name, "write")
            self.assertIsNone(self.errors[0].obj)

    def test_update_preserves_serialization_and_reads_back(self):
        expected = io.StringIO()
        clnch_ini.ini.write(expected)
        self.assertIsNone(clnch_ini.write())
        self.assertFalse(clnch_ini.dirty)
        self.assertEqual(self.path.read_bytes(), expected.getvalue().encode("utf-8"))
        clnch_ini.read()
        self.assertEqual(clnch_ini.get("INPUT", "value"), "日本語😀 100%")
        self.assertEqual(clnch_ini.get("INPUT", "paths"), "C:\\one\nD:\\two")
        self.assertEqual(clnch_ini.getint("INPUT", "count"), 42)
        self.assertEqual(clnch_ini.get("OTHER", "keep"), "original")
        self.assertEqual(self.errors, [])
        self.assert_clean()

    def test_first_save_and_missing_read(self):
        self.path.unlink()
        clnch_ini.read()
        self.assertEqual(self.errors, [])
        self.assertFalse(clnch_ini.read_failed)
        self.assertFalse(clnch_ini.dirty)
        self.assertEqual(clnch_ini.ini.sections(), [])
        clnch_ini.set("INPUT", "value", "first save")
        clnch_ini.write()
        self.assertFalse(clnch_ini.dirty)
        clnch_ini.read()
        self.assertEqual(clnch_ini.get("INPUT", "value"), "first save")
        self.assertEqual(self.errors, [])
        self.assert_clean()

    def test_utf8_bom_is_read_and_saved_without_bom(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + self.old)
        clnch_ini.read()
        self.assertFalse(clnch_ini.read_failed)
        self.assertEqual(clnch_ini.get("OTHER", "keep"), "original")
        clnch_ini.set("INPUT", "value", "saved")
        clnch_ini.write()
        self.assertFalse(clnch_ini.dirty)
        self.assertTrue(self.path.read_bytes().startswith(b"[OTHER]"))
        self.assertEqual(self.errors, [])
        self.assert_clean()

    def test_parse_failure_discards_partial_settings_and_blocks_all_saves_until_reread(self):
        valid = "[OTHER]\r\nkeep = original\r\n[COMMANDLINE]\r\nhistory_0 = saved\r\n"
        cases = (
            "[broken\r\n" + valid,
            "[OTHER]\r\nkeep = original\r\n[OTHER]\r\nkeep = lost\r\n" + valid,
            valid + "[COMMANDLINE]\r\nhistory_0 = lost\r\n",
            valid + "invalid line\r\n",
            valid + "history_0 = duplicate\r\n",
        )
        for text in cases:
            with self.subTest(text=text):
                self.errors.clear()
                original = text.encode("utf-8")
                self.path.write_bytes(original)
                clnch_ini.read()
                self.assertEqual(len(self.errors), 1)
                self.assertIsInstance(self.errors[0], configparser.Error)
                self.assertTrue(clnch_ini.read_failed)
                self.assertFalse(clnch_ini.dirty)
                self.assertEqual(clnch_ini.ini.sections(), [])
                clnch_ini.set("GEOMETRY", "width", "18")
                clnch_ini.set("COMMANDLINE", "history_0", "new history")
                with patch.object(clnch_ini.tempfile, "NamedTemporaryFile") as temporary:
                    for _ in range(2):
                        self.assertIsNone(clnch_ini.write())
                    temporary.assert_not_called()
                self.assertTrue(clnch_ini.dirty)
                self.assertEqual(self.path.read_bytes(), original)
                # Repair alone must not let the failed session overwrite the repair.
                self.path.write_bytes(valid.encode("utf-8"))
                clnch_ini.write()
                self.assertEqual(self.path.read_bytes(), valid.encode("utf-8"))
                clnch_ini.read()
                self.assertFalse(clnch_ini.read_failed)
                self.assertFalse(clnch_ini.dirty)
                self.assertEqual(clnch_ini.get("COMMANDLINE", "history_0"), "saved")
                clnch_ini.set("GEOMETRY", "width", "42")
                clnch_ini.write()
                self.assertFalse(clnch_ini.dirty)
                clnch_ini.read()
                self.assertEqual(clnch_ini.get("OTHER", "keep"), "original")
                self.assertEqual(clnch_ini.get("GEOMETRY", "width"), "42")
                self.assertEqual(len(self.errors), 1)
                self.assert_clean()

    def test_read_io_and_lock_failures_block_saves_and_recover(self):
        for target, attribute, failure in (
            (clnch_ini, "open", PermissionError("read denied")),
            (clnch_ini, "open", OSError("read failed")),
            (clnch_ini._winapi, "WaitForSingleObject", OSError("read lock failed")),
            (clnch_ini._winapi, "WaitForSingleObject", FileNotFoundError("lock failed")),
        ):
            with self.subTest(failure=failure):
                self.errors.clear()
                self.path.write_bytes(self.old)
                with patch.object(target, attribute, side_effect=failure, create=True):
                    clnch_ini.read()
                self.assertEqual(self.errors, [failure])
                self.assertTrue(clnch_ini.read_failed)
                clnch_ini.set("GEOMETRY", "width", "18")
                clnch_ini.write()
                self.assertEqual(self.path.read_bytes(), self.old)
                self.assertTrue(clnch_ini.dirty)
                clnch_ini.read()
                self.assertFalse(clnch_ini.read_failed)
                clnch_ini.set("GEOMETRY", "width", "42")
                clnch_ini.write()
                self.assertFalse(clnch_ini.dirty)
                self.assertEqual(len(self.errors), 1)
                self.assert_clean()

    def test_real_windows_read_sharing_failure_blocks_save_after_handle_is_closed(self):
        handle = clnch_ini._winapi.CreateFile(str(self.path), 0x80000000, 0, 0, 3, 0, 0)
        try:
            with patch.object(clnch_ini.clnch_debug, "printErrorInfo",
                              side_effect=lambda: self.errors.append(sys.exception())):
                clnch_ini.read()
        finally:
            clnch_ini._winapi.CloseHandle(handle)
        self.assertEqual(len(self.errors), 1)
        self.assertIsInstance(self.errors[0], PermissionError)
        self.assertTrue(clnch_ini.read_failed)
        clnch_ini.set("GEOMETRY", "width", "18")
        clnch_ini.write()
        self.assertEqual(self.path.read_bytes(), self.old)
        self.assertTrue(clnch_ini.dirty)
        self.assert_clean()

    def test_midstream_read_and_decode_failures_do_not_publish_partial_settings(self):
        def failing_lines():
            yield "[OTHER]\n"
            yield "keep = partial\n"
            raise OSError("midstream read failed")
        for contents in (failing_lines(), io.BytesIO(b"[OTHER]\nkeep = original\n\xff")):
            with self.subTest(contents=contents):
                self.errors.clear()
                stream = io.TextIOWrapper(contents, encoding="utf-8") if isinstance(contents, io.BytesIO) else contents
                with patch.object(clnch_ini, "open", return_value=contextlib.nullcontext(stream), create=True):
                    clnch_ini.read()
                stream.close()
                self.assertEqual(len(self.errors), 1)
                self.assertTrue(clnch_ini.read_failed)
                self.assertEqual(clnch_ini.ini.sections(), [])
                clnch_ini.set("GEOMETRY", "width", "18")
                clnch_ini.write()
                self.assertEqual(self.path.read_bytes(), self.old)

    def test_missing_file_after_failed_read_allows_first_save(self):
        self.path.write_bytes(b"[broken\r\n")
        clnch_ini.read()
        self.assertTrue(clnch_ini.read_failed)
        self.path.unlink()
        clnch_ini.read()
        self.assertFalse(clnch_ini.read_failed)
        clnch_ini.set("GEOMETRY", "width", "18")
        clnch_ini.write()
        self.assertFalse(clnch_ini.dirty)
        self.assertEqual(len(self.errors), 1)
        self.assert_clean()

    def test_get_defaults_types_invalid_values_and_exception_contract(self):
        ini = clnch_ini
        for section, key, default in (("MISC", "auto_complete", 0), ("GEOMETRY", "max_width", 80),
                                      ("GEOMETRY", "min_width", 18), ("FONT", "size", 16)):
            with self.subTest(section=section, key=key):
                self.assertIs(type(ini.getint(section, key, default)), int)
                self.assertEqual(ini.getint(section, key, default), default)
                with self.assertRaises((configparser.NoSectionError, configparser.NoOptionError)):
                    ini.getint(section, key)
                ini.set(section, key, "42")
                self.assertEqual(ini.get(section, key), "42")
                self.assertIs(type(ini.getint(section, key, default)), int)
                self.assertEqual(ini.getint(section, key, default), 42)
                ini.set(section, key, "invalid")
                self.assertEqual(ini.getint(section, key, default), default)
                with self.assertRaises(ValueError):
                    ini.getint(section, key)
        self.assertEqual(ini.get("FONT", "name", ""), "")
        self.assertEqual(ini.get("FONT", "name", "MS Gothic"), "MS Gothic")
        # The public API still returns a caller's default unchanged.
        self.assertIs(ini.getint("MISSING", "key", False), False)
        self.assertEqual(ini.getint("MISSING", "key", "0"), "0")

    def test_auto_complete_serialization_and_readback_keep_existing_format(self):
        for value in ("1", "0"):
            clnch_ini.set("MISC", "auto_complete", value)
            clnch_ini.write()
            self.assertIn(f"[MISC]\nauto_complete = {value}\n".encode(), self.path.read_bytes())
            clnch_ini.read()
            self.assertEqual(clnch_ini.get("MISC", "auto_complete"), value)
            self.assertIs(type(clnch_ini.getint("MISC", "auto_complete", 0)), int)
            self.assertEqual(clnch_ini.getint("MISC", "auto_complete", 0), int(value))
        self.assertEqual(self.errors, [])

    def test_clean_write_does_not_open_files(self):
        clnch_ini.dirty = False
        with (patch.object(clnch_ini, "open", create=True) as opened,
              patch.object(clnch_ini._winapi, "CreateMutexW") as created):
            self.assertIsNone(clnch_ini.write())
        opened.assert_not_called()
        created.assert_not_called()
        self.assertFalse(self.lock_path.exists())

    def test_mutex_creation_failure_preserves_ini(self):
        with patch.object(clnch_ini._winapi, "CreateMutexW", return_value=None):
            clnch_ini.write()
        self.assert_failed()

    def test_mutex_name_uses_canonical_ini_path(self):
        names = []
        create = clnch_ini._winapi.CreateMutexW
        def capture(attributes, owner, name):
            names.append(name)
            return create(attributes, owner, name)
        for path in (self.path, Path(os.path.relpath(self.path)).with_name(self.path.name.upper()),
                     self.path.with_name("other.ini")):
            with (patch.object(clnch_ini, "ini_filename", str(path)),
                  patch.object(clnch_ini._winapi, "CreateMutexW", side_effect=capture), clnch_ini._lock()):
                self.assertEqual(list(self.directory.glob("*.lock")), [])
        self.assertEqual(names[0], names[1])
        self.assertNotEqual(names[0], names[2])
        self.assert_clean()

    def test_partial_write_failure_preserves_old_or_absent_file_and_retries(self):
        def fail(fd):
            fd.write("[INPUT]\nvalue = partial")
            fd.flush()
            raise OSError("partial write")
        for exists in (True, False):
            with self.subTest(exists=exists):
                self.errors.clear()
                if not exists:
                    self.path.unlink()
                clnch_ini.dirty = True
                with patch.object(clnch_ini.ini, "write", side_effect=fail):
                    self.assertIsNone(clnch_ini.write())
                self.assert_failed(exists)
                clnch_ini.write()
                self.assertFalse(clnch_ini.dirty)

    def test_flush_fsync_and_close_failure_preserve_old_file(self):
        create = clnch_ini.tempfile.NamedTemporaryFile
        for failure in ("flush", "fsync", "close"):
            with self.subTest(failure=failure), contextlib.ExitStack() as stack:
                self.errors.clear()
                @contextlib.contextmanager
                def temporary(failure=failure, stack=stack, **kwargs):
                    with create(**kwargs) as fd:
                        if failure == "flush":
                            stack.enter_context(patch.object(fd, "flush", side_effect=OSError("flush")))
                        yield fd
                    if failure == "close":
                        raise OSError("close")
                stack.enter_context(patch.object(clnch_ini.tempfile, "NamedTemporaryFile", side_effect=temporary))
                if failure == "fsync":
                    stack.enter_context(patch.object(clnch_ini.os, "fsync", side_effect=OSError("fsync")))
                clnch_ini.write()
                self.assert_failed()

    def test_replace_failure_keeps_existing_or_absent_file(self):
        for exists in (True, False):
            with self.subTest(exists=exists):
                self.errors.clear()
                if not exists:
                    self.path.unlink()
                with patch.object(clnch_ini.os, "replace", side_effect=PermissionError("replace")):
                    clnch_ini.write()
                self.assert_failed(exists)

    def test_open_target_blocks_real_windows_replace_without_data_loss(self):
        with self.path.open("rb"), patch.object(clnch_ini.clnch_debug, "printErrorInfo",
                                               side_effect=lambda: self.errors.append(sys.exception())):
            clnch_ini.write()
        self.assertIsInstance(self.errors[0], PermissionError)
        self.assert_failed()

    def test_readonly_target_is_not_overwritten(self):
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o666)
        clnch_ini.write()
        self.assertIsInstance(self.errors[0], PermissionError)
        self.assert_failed()

    def test_lock_failure_does_not_touch_target_or_create_temporary(self):
        with patch.object(clnch_ini._winapi, "WaitForSingleObject", side_effect=OSError("lock")):
            clnch_ini.write()
        self.assert_failed()

    def test_temporary_creation_failure_preserves_old_file(self):
        with patch.object(clnch_ini.tempfile, "NamedTemporaryFile", side_effect=OSError("create")):
            clnch_ini.write()
        self.assert_failed()

    def worker(self, operation):
        process = subprocess.Popen([sys.executable, "-B", __file__, "--worker", str(self.path), operation],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        return process

    def wait_marker(self, operation, marker):
        target = Path(str(self.path) + "." + operation + "." + marker)
        deadline = time.monotonic() + 10
        while not target.exists():
            if time.monotonic() >= deadline:
                self.fail("Worker did not reach " + str(target))
            time.sleep(0.01)

    def finish(self, process, data=None):
        output, errors = process.communicate(data, timeout=15)
        self.assertEqual(process.returncode, 0, (output, errors))
        return output

    def test_process_reader_and_writer_wait_through_partial_write_and_replacement(self):
        for operation in ("read", "write"):
            with self.subTest(operation=operation):
                previous = self.path.read_bytes()
                holder = self.worker("hold")
                self.wait_marker("hold", "partial")
                self.assertEqual(self.path.read_bytes(), previous)
                contender = self.worker(operation)
                self.wait_marker(operation, "locking")
                with self.assertRaises(subprocess.TimeoutExpired):
                    contender.communicate(timeout=0.2)
                holder.stdin.write(b"continue\n")
                holder.stdin.flush()
                self.wait_marker("hold", "replaced")
                self.assertEqual(self.path.read_bytes(), b"[S]\nvalue = hold\n\n")
                with self.assertRaises(subprocess.TimeoutExpired):
                    contender.communicate(timeout=0.2)
                self.finish(holder, b"release\n")
                result = self.finish(contender)
                if operation == "read":
                    self.assertIn(b"hold", result)
                else:
                    self.assertEqual(self.path.read_bytes(), b"[S]\nvalue = write\n\n")
                for marker in self.directory.glob("*.hold.*"):
                    marker.unlink()
                self.assert_clean()

    def test_real_lock_timeout_preserves_target(self):
        holder = self.worker("hold")
        self.wait_marker("hold", "partial")
        with patch.object(clnch_ini.clnch_debug, "printErrorInfo",
                          side_effect=lambda: self.errors.append(sys.exception())):
            clnch_ini.write()
        # The holder still owns its temporary file; only check our result here.
        self.assertEqual(self.path.read_bytes(), self.old)
        self.assertTrue(clnch_ini.dirty)
        self.assertEqual(len(self.errors), 1)
        self.finish(holder, b"continue\nrelease\n")
        self.assert_clean()

    def test_terminated_writer_keeps_old_or_absent_ini_and_releases_lock(self):
        for exists in (True, False):
            with self.subTest(exists=exists):
                if exists:
                    self.path.write_bytes(self.old)
                else:
                    self.path.unlink()
                holder = self.worker("hold")
                self.wait_marker("hold", "partial")
                holder.kill()
                holder.communicate(timeout=10)
                self.assertFalse(self.lock_path.exists())
                self.assertEqual(self.path.read_bytes() if exists else None, self.old if exists else None)
                self.assertEqual(self.path.exists(), exists)
                # Forced termination cannot run finally; remove only this test's orphan.
                for orphan in self.directory.glob("*.tmp"):
                    orphan.unlink()
                for marker in self.directory.glob("*.hold.*"):
                    marker.unlink()
                clnch_ini.dirty = True
                clnch_ini.write()
                self.assertFalse(clnch_ini.dirty)
                self.assertEqual(self.errors, [])
                self.assert_clean()

    def test_waiting_writer_recovers_after_owner_is_terminated(self):
        holder = self.worker("hold")
        self.wait_marker("hold", "partial")
        contender = self.worker("write")
        self.wait_marker("write", "locking")
        with self.assertRaises(subprocess.TimeoutExpired):
            contender.communicate(timeout=0.2)
        holder.kill()
        holder.communicate(timeout=10)
        self.finish(contender)
        self.assertEqual(self.path.read_bytes(), b"[S]\nvalue = write\n\n")
        self.assertEqual(Path(str(self.path) + ".write.result").read_text(), "128")
        for orphan in self.directory.glob("*.tmp"):
            orphan.unlink()
        self.assert_clean()


def worker(path, operation):
    clnch_ini.ini_filename = path
    clnch_ini.clnch_debug.printErrorInfo = lambda: sys.exit("INI operation failed")
    waiting = clnch_ini._winapi.WaitForSingleObject
    def wait(handle, timeout):
        Path(path + "." + operation + ".locking").touch()
        result = waiting(handle, timeout)
        Path(path + "." + operation + ".result").write_text(str(result))
        return result
    clnch_ini._winapi.WaitForSingleObject = wait
    if operation == "read":
        clnch_ini.read()
        print(clnch_ini.get("S", "value"), flush=True)
        return
    clnch_ini.ini = configparser.RawConfigParser()
    clnch_ini.ini["S"] = {"value": operation}
    clnch_ini.dirty = True
    if operation == "hold":
        write = clnch_ini.ini.write
        replace = os.replace
        def staged(fd):
            fd.write("[partial")
            fd.flush()
            Path(path + "." + operation + ".partial").touch()
            sys.stdin.buffer.readline()
            fd.seek(0)
            fd.truncate()
            write(fd)
        def replaced(source, destination):
            replace(source, destination)
            Path(path + "." + operation + ".replaced").touch()
            sys.stdin.buffer.readline()
        clnch_ini.ini.write = staged
        os.replace = replaced
    clnch_ini.write()
    if clnch_ini.dirty:
        sys.exit("INI still dirty")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        unittest.main()
