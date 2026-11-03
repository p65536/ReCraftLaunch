"""Deterministic subprocess startup/cancellation regressions on Windows."""

import io
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(RUN_DIR / "lib")]

import ckit
from ckit import ckit_subprocess


class SubProcessTests(unittest.TestCase):
    def setUp(self):
        self.output = []
        self.process = Mock(pid=123, returncode=7)
        self.process.stdin = io.BytesIO()
        self.process.stdout = io.BytesIO("出力\n末尾\n".encode("mbcs"))
        self.process.poll.side_effect = [None, 7]
        self.addCleanup(self.process.stdout.close)
        self.popen = self.enterContext(patch.object(ckit_subprocess.subprocess, "Popen", return_value=self.process))
        self.terminate = self.enterContext(patch.object(ckit_subprocess.ckit_misc, "terminateProcess"))
        self.task = ckit.SubProcess(["program", "arg"], cwd="work", env={"TEST": "1"},
                                    stdout_write=self.output.append)

    def wait(self, event):
        self.assertTrue(event.wait(3), "Expected subprocess step was not reached")

    def start(self, func):
        results, errors = [], []
        def run():
            try:
                results.append(func())
            except BaseException as error:  # noqa: BLE001  # Surface worker failures in the test thread.
                errors.append(error)
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.addCleanup(self.join, worker)
        return worker, results, errors

    def join(self, worker):
        worker.join(3)
        self.assertFalse(worker.is_alive(), "Subprocess worker did not finish")

    def test_normal_output_exit_code_and_popen_options(self):
        self.assertEqual(self.task(), 7)
        self.assertEqual(self.output, ["出力\n", "末尾\n"])
        self.assertIs(self.task.p, self.process)
        self.assertTrue(self.process.stdin.closed)
        self.assertTrue(self.process.stdout.closed)
        self.terminate.assert_not_called()
        args, options = self.popen.call_args
        self.assertEqual(args, (["program", "arg"],))
        startupinfo = options.pop("startupinfo")
        self.assertEqual((startupinfo.dwFlags, startupinfo.wShowWindow), (1, 0))
        self.assertEqual(options, {"stdin": -1, "stdout": -1, "stderr": -2, "shell": False,
                                   "cwd": "work", "env": {"TEST": "1"}})

    def test_cancel_before_start_is_deferred_and_coalesced(self):
        self.assertIsNone(self.task.cancel())
        self.task.cancel()
        self.terminate.assert_not_called()
        self.process.poll.side_effect = [None, None, 7]
        self.assertEqual(self.task(), 7)
        self.terminate.assert_called_once_with(123)

    def test_missing_stdout_keeps_read_and_drain_failures(self):
        self.process.stdout = None
        for running in (True, False):
            self.process.poll.side_effect = None
            self.process.poll.return_value = None if running else 7
            with self.subTest(running=running):
                with self.assertRaises(AttributeError if running else TypeError) as raised:
                    self.task()
                if running:
                    assert isinstance(raised.exception, AttributeError)
                    self.assertEqual(str(raised.exception), "'NoneType' object has no attribute 'readline'")
                    self.assertEqual(raised.exception.name, "readline")
                    self.assertIsNone(raised.exception.obj)
                else:
                    self.assertEqual(str(raised.exception), "'NoneType' object is not iterable")
                self.assertIs(self.task.p, self.process)
                self.assertEqual(self.output, [])

    def test_output_callback_replacement_is_observed_on_next_read(self):
        replacement = Mock(returncode=9)
        replacement.poll.return_value = 9
        replacement.stdout = io.BytesIO(b"replacement tail\n")
        self.addCleanup(replacement.stdout.close)
        def write(text):
            self.output.append(text)
            self.task.p = replacement
            self.task.stdout_write = lambda text: self.output.append(("new", text))
        self.task.stdout_write = write
        self.assertEqual(self.task(), 9)
        self.assertEqual(self.output, ["出力\n", ("new", "replacement tail\n")])
        self.assertIs(self.task.p, replacement)
        self.assertTrue(self.process.stdin.closed)
        self.assertTrue(self.process.stdout.closed)
        self.assertFalse(replacement.stdout.closed)

    def test_eof_waits_once_without_empty_notifications(self):
        self.process.stdout = Mock()
        self.process.stdout.readline.side_effect = [b"", AssertionError("Read again after EOF")]
        self.process.stdout.__iter__ = Mock(return_value=iter(()))
        self.process.poll.side_effect = None
        self.process.poll.return_value = None
        self.process.wait.side_effect = lambda: setattr(self.process, "returncode", 23)
        self.assertEqual(self.task(), 23)
        self.process.stdout.readline.assert_called_once()
        self.process.wait.assert_called_once_with()
        self.process.stdout.close.assert_called_once_with()
        self.assertTrue(self.process.stdin.closed)
        self.assertEqual(self.output, [])

    def test_failures_and_interrupts_close_pipes_without_killing_or_waiting(self):
        for stage in ("cancel", "read", "decode", "callback", "wait"):
            for failure in (RuntimeError("failure"), KeyboardInterrupt()):
                with self.subTest(stage=stage, failure=type(failure).__name__):
                    process = Mock(pid=123)
                    process.stdin = io.BytesIO()
                    process.stdout = Mock()
                    process.poll.return_value = None
                    process.stdout.readline.return_value = b"line\n"
                    task = ckit.SubProcess(["program"], stdout_write=Mock())
                    if stage == "cancel":
                        task.cancel()
                        self.terminate.side_effect = failure
                    elif stage == "read":
                        process.stdout.readline.side_effect = failure
                    elif stage == "decode":
                        process.stdout.readline.return_value = Mock(decode=Mock(side_effect=failure))
                    elif stage == "callback":
                        task.stdout_write.side_effect = failure
                    else:
                        process.stdout.readline.return_value = b""
                        process.wait.side_effect = failure
                    with patch.object(ckit_subprocess.subprocess, "Popen", return_value=process), \
                         self.assertRaises(type(failure)) as raised:
                        task()
                    self.terminate.side_effect = None
                    self.assertIs(raised.exception, failure)
                    self.assertTrue(process.stdin.closed)
                    process.stdout.close.assert_called_once_with()
                    process.kill.assert_not_called()
                    process.terminate.assert_not_called()
                    if stage != "wait":
                        process.wait.assert_not_called()

    def test_pipe_close_failure_still_closes_other_pipe_and_preserves_exception(self):
        failure = RuntimeError("callback failed")
        self.task.stdout_write = Mock(side_effect=failure)
        stdout = Mock(readline=Mock(return_value=b"line\n"))
        stdout.close.side_effect = OSError("close failed")
        self.process.stdout = stdout
        with self.assertRaises(RuntimeError) as raised:
            self.task()
        self.assertIs(raised.exception, failure)
        self.assertTrue(self.process.stdin.closed)
        self.assertIn("close failed", failure.__notes__[0])

    def test_cancel_during_popen_returns_without_waiting_and_is_delivered(self):
        entered, release = threading.Event(), threading.Event()
        def popen(*args, **kwargs):
            entered.set()
            self.wait(release)
            return self.process
        self.popen.side_effect = popen
        worker, results, errors = self.start(self.task)
        self.addCleanup(release.set)
        self.wait(entered)
        canceled = threading.Event()
        def cancel():
            self.task.cancel()
            self.task.cancel()
            canceled.set()
        controller, _, cancel_errors = self.start(cancel)
        self.wait(canceled)
        self.assertIsNone(self.task.p)
        self.terminate.assert_not_called()
        self.process.poll.side_effect = [None, None, 7]
        release.set()
        self.join(worker)
        self.join(controller)
        self.assertEqual((results, errors, cancel_errors), ([7], [], []))
        self.terminate.assert_called_once_with(123)

    def test_cancel_after_publication_does_not_duplicate_pending_request(self):
        # Stop the worker immediately after publication, before it drains the request.
        published, release = threading.Event(), threading.Event()
        drain = self.task._cancel_pending
        def worker_drain():
            if threading.current_thread() is not threading.main_thread():
                published.set()
                self.wait(release)
            drain()
        self.task.cancel()
        self.process.poll.side_effect = [None, None, 7]
        with patch.object(self.task, "_cancel_pending", side_effect=worker_drain):
            worker, results, errors = self.start(self.task)
            self.addCleanup(release.set)
            self.wait(published)
            self.assertIs(self.task.p, self.process)
            # The UI wins the race to drain the already pending request.
            self.task.cancel()
            release.set()
            self.join(worker)
        self.assertEqual((results, errors), ([7], []))
        self.terminate.assert_called_once_with(123)

    def test_running_cancel_while_worker_reads_output(self):
        reading, release = threading.Event(), threading.Event()
        def readline():
            reading.set()
            self.wait(release)
            return b"output\n"
        self.process.stdout = Mock(readline=readline)
        self.process.stdout.__iter__ = Mock(return_value=iter(()))
        self.process.poll.side_effect = [None, None, 7]
        worker, results, errors = self.start(self.task)
        self.addCleanup(release.set)
        self.wait(reading)
        self.task.cancel()
        self.terminate.assert_called_once_with(123)
        release.set()
        self.join(worker)
        self.assertEqual((results, errors, self.output), ([7], [], ["output\n"]))

    def test_running_cancel_coalesces_reentrant_request_and_allows_later_retry(self):
        self.task.p = self.process
        self.process.poll.side_effect = None
        self.process.poll.return_value = None
        self.terminate.side_effect = lambda pid: self.task.cancel()
        self.task.cancel()
        self.terminate.assert_called_once_with(123)
        self.task.cancel()
        self.assertEqual(self.terminate.call_count, 2)

    def test_concurrent_cancel_returns_while_exit_request_is_in_progress(self):
        self.task.p = self.process
        self.process.poll.side_effect = None
        self.process.poll.return_value = None
        entered, release = threading.Event(), threading.Event()
        def terminate(pid):
            entered.set()
            self.wait(release)
        self.terminate.side_effect = terminate
        worker, _, errors = self.start(self.task.cancel)
        self.addCleanup(release.set)
        self.wait(entered)
        canceled = threading.Event()
        controller, _, cancel_errors = self.start(lambda: (self.task.cancel(), canceled.set()))
        self.wait(canceled)
        release.set()
        self.join(worker)
        self.join(controller)
        self.assertEqual((errors, cancel_errors), ([], []))
        self.terminate.assert_called_once_with(123)

    def test_popen_failure_preserves_exception_and_pending_cancel(self):
        failure = OSError("cannot start")
        self.popen.side_effect = failure
        self.task.cancel()
        with self.assertRaises(OSError) as raised:
            self.task()
        self.assertIs(raised.exception, failure)
        self.assertIsNone(self.task.p)
        self.task.cancel()
        self.terminate.assert_not_called()
        self.process.stdout.seek(0)
        self.process.poll.side_effect = [None, None, 7]
        self.popen.side_effect = None
        self.assertEqual(self.task(), 7)
        self.terminate.assert_called_once_with(123)

    def test_cancel_during_failing_popen(self):
        entered, release = threading.Event(), threading.Event()
        failure = OSError("cannot start")
        def popen(*args, **kwargs):
            entered.set()
            self.wait(release)
            raise failure
        self.popen.side_effect = popen
        worker, results, errors = self.start(self.task)
        self.addCleanup(release.set)
        self.wait(entered)
        self.task.cancel()
        release.set()
        self.join(worker)
        self.assertEqual((results, errors), ([], [failure]))
        self.assertIsNone(self.task.p)
        self.task.cancel()
        self.terminate.assert_not_called()

    def test_cancel_after_exit_never_passes_stale_pid(self):
        self.assertEqual(self.task(), 7)
        self.process.poll.side_effect = None
        self.process.poll.return_value = 7
        self.task.cancel()
        self.task.cancel()
        self.terminate.assert_not_called()

    def test_exit_between_creation_and_pending_cancel_does_not_send(self):
        self.task.cancel()
        self.process.poll.side_effect = None
        self.process.poll.return_value = 7
        self.assertEqual(self.task(), 7)
        self.terminate.assert_not_called()

    def test_exit_request_failure_preserves_exception_and_allows_retry(self):
        self.task.p = self.process
        self.process.poll.side_effect = None
        self.process.poll.return_value = None
        self.terminate.side_effect = RuntimeError("request failed")
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            self.task.cancel()
        self.terminate.side_effect = None
        self.task.cancel()
        self.assertEqual(self.terminate.call_count, 2)


class NativeSubProcessTests(unittest.TestCase):
    def run_task(self, task):
        def abort():
            if task.p is not None and task.p.poll() is None:
                task.p.kill()
        watchdog = threading.Timer(8, abort)
        watchdog.start()
        try:
            return task()
        finally:
            watchdog.cancel()
            watchdog.join(2)
            abort()
            if task.p is not None:
                task.p.wait(timeout=3)
                task.p.stdin.close()
                task.p.stdout.close()

    def test_real_process_output_and_exit(self):
        output = []
        task = ckit.SubProcess([sys.executable, "-B", "-S", "-c",
            "import sys; print('out', flush=True); print('err', file=sys.stderr, flush=True); sys.exit(7)"],
            stdout_write=output.append)
        self.assertEqual(self.run_task(task), 7)
        self.assertEqual("".join(output), "out\r\nerr\r\n")
        self.assertTrue(task.p.stdin.closed)
        self.assertTrue(task.p.stdout.closed)
        self.assertIsNone(task.cancel())

    def test_real_eof_before_exit_waits_with_low_cpu_and_no_empty_callbacks(self):
        output, observations = [], []
        task = ckit.SubProcess([sys.executable, "-B", "-S", "-c",
            "import os, time; os.close(1); os.close(2); time.sleep(0.8); raise SystemExit(23)"],
            stdout_write=output.append)
        real_wait = ckit_subprocess.subprocess.Popen.wait
        def wait(process, *args, **kwargs):
            if process is task.p and not args and not kwargs:
                observations.append(process.poll())
            return real_wait(process, *args, **kwargs)
        wall, cpu = time.monotonic(), time.process_time()
        with patch.object(ckit_subprocess.subprocess.Popen, "wait", wait):
            self.assertEqual(self.run_task(task), 23)
        elapsed, used = time.monotonic() - wall, time.process_time() - cpu
        self.assertEqual(observations, [None])
        self.assertEqual(output, [])
        self.assertGreater(elapsed, 0.7)
        self.assertLess(used, elapsed / 4, (used, elapsed))
        self.assertTrue(task.p.stdin.closed)
        self.assertTrue(task.p.stdout.closed)

    def test_real_callback_exception_closes_pipes_without_waiting_for_child(self):
        failure = RuntimeError("callback failed")
        def write(text):
            raise failure
        task = ckit.SubProcess([sys.executable, "-B", "-S", "-c",
            "import time; print('ready', flush=True); time.sleep(30)"], stdout_write=write)
        try:
            with self.assertRaises(RuntimeError) as raised:
                task()
            self.assertIs(raised.exception, failure)
            self.assertIsNone(task.p.poll())
            self.assertTrue(task.p.stdin.closed)
            self.assertTrue(task.p.stdout.closed)
        finally:
            if task.p is not None:
                task.p.kill()
                task.p.wait(timeout=3)

    def test_real_startup_failure_has_no_published_process(self):
        task = ckit.SubProcess([str(ROOT / "missing-subprocess-test.exe")])
        task.cancel()
        with self.assertRaises(OSError):
            task()
        self.assertIsNone(task.p)
        self.assertTrue(task._cancel_requested)

    def test_real_windowless_process_cancel_remains_best_effort(self):
        output = []
        def write(text):
            output.append(text)
            if text == "ready\r\n":
                task.cancel()
                task.cancel()
                self.assertIsNone(task.p.poll())
                task.p.stdin.write(b"finish\n")
                task.p.stdin.flush()
        pythonw = str(Path(sys.executable).with_name("pythonw.exe"))
        task = ckit.SubProcess([pythonw, "-B", "-S", "-c",
            "import sys; print('ready', flush=True); sys.stdin.readline(); print('done', flush=True); sys.exit(9)"],
            stdout_write=write)
        self.assertEqual(self.run_task(task), 9)
        self.assertEqual("".join(output), "ready\r\ndone\r\n")


if __name__ == "__main__":
    unittest.main()
