"""Regression checks for SyncCall, JobQueue and Cron thread coordination."""

import contextlib
import io
import sys
import threading
import time
import traceback
import unittest
from pathlib import Path
from unittest.mock import patch

from native_test_support import RUN_DIR

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(RUN_DIR / "lib")]

import ckit
from ckit import ckit_threadutil


class SyncCallTests(unittest.TestCase):
    def setUp(self):
        self.sync = ckit.SyncCall()

    def wait(self, event):
        self.assertTrue(event.wait(3), "SyncCall did not reach the expected step")

    def join(self, thread):
        thread.join(3)
        self.assertFalse(thread.is_alive(), "SyncCall worker did not finish")

    def start(self, func, args=()):
        outcome = {}
        done = threading.Event()
        def run():
            try:
                outcome["result"] = self.sync(func, args)
            except BaseException as error:  # noqa: BLE001  # Capture worker failures for assertions on the test thread.
                outcome["error"] = error
                outcome["traceback"] = traceback.extract_tb(error.__traceback__)
            finally:
                done.set()
        thread = threading.Thread(target=run, daemon=True)
        self.addCleanup(self.join, thread)
        thread.start()
        return thread, outcome, done

    def submit(self, func, args=()):
        accepted = threading.Event()
        put = self.sync._requests.put
        def enqueue(request):
            put(request)
            accepted.set()
        with patch.object(self.sync._requests, "put", side_effect=enqueue):
            worker = self.start(func, args)
            self.wait(accepted)
        return worker

    def test_owner_calls_directly_with_result_none_and_exceptions(self):
        self.assertEqual(self.sync(lambda a, b: (a + b, threading.get_ident()), (2, 3)),
                         (5, threading.get_ident()))
        self.assertIsNone(self.sync(lambda: None))
        for error in (ValueError("direct"), KeyboardInterrupt("direct")):
            with self.subTest(error=error):
                def fail(error=error):
                    raise error
                with self.assertRaises(type(error)) as caught:
                    self.sync(fail)
                self.assertIs(caught.exception, error)
        self.assertTrue(self.sync._requests.empty())

    def test_worker_waits_for_check_and_runs_on_owner(self):
        owner = threading.get_ident()
        for value in (None, "result", 0):
            with self.subTest(value=value):
                calls = []
                def callback(arg, calls=calls):
                    calls.append(threading.get_ident())
                    return arg
                thread, outcome, done = self.submit(callback, (value,))
                self.assertFalse(done.is_set())
                self.assertEqual(calls, [])
                self.assertIsNone(self.sync.check())
                self.wait(done)
                self.join(thread)
                self.assertEqual(calls, [owner])
                self.assertEqual(outcome, {"result": value})

    def test_exceptions_keep_identity_traceback_and_pending_successor(self):
        class Fatal(BaseException):
            pass
        for error in (ValueError("worker"), Fatal("fatal"), SystemExit(7), KeyboardInterrupt()):
            with self.subTest(error=error):
                cause = OSError("cause")
                def fail(error=error, cause=cause):
                    raise error from cause
                first, failed, failed_done = self.submit(fail)
                second, passed, passed_done = self.submit(lambda: "next")
                self.assertIsNone(self.sync.check())
                self.wait(failed_done)
                self.join(first)
                self.assertIs(failed["error"], error)
                self.assertIs(error.__cause__, cause)
                self.assertEqual(failed["traceback"][-1].name, "fail")
                self.assertFalse(passed_done.is_set())
                self.sync.check()
                self.wait(passed_done)
                self.join(second)
                self.assertEqual(passed, {"result": "next"})

    def test_concurrent_workers_receive_their_own_fifo_results(self):
        count = 8
        ready = threading.Barrier(count + 1, timeout=3)
        accepted = threading.Event()
        order = []
        calls = []
        put = self.sync._requests.put
        lock = threading.Lock()
        def enqueue(request):
            with lock:
                put(request)
                order.append(request.args[0])
                if len(order) == count:
                    accepted.set()
        def callback(index):
            calls.append(index)
            return index * 10
        def run(index, outcome):
            try:
                ready.wait()
                outcome["result"] = self.sync(callback, (index,))
            except BaseException as error:  # noqa: BLE001  # Capture worker failures for assertions on the test thread.
                outcome["error"] = error
        workers = []
        with patch.object(self.sync._requests, "put", side_effect=enqueue):
            for index in range(count):
                outcome = {}
                thread = threading.Thread(target=run, args=(index, outcome), daemon=True)
                self.addCleanup(self.join, thread)
                thread.start()
                workers.append((thread, outcome))
            ready.wait()
            self.wait(accepted)
        for index in range(count):
            self.sync.check()
            self.assertEqual(calls, order[:index + 1])
        for index, (thread, outcome) in enumerate(workers):
            self.join(thread)
            self.assertEqual(outcome, {"result": index * 10})

    def test_request_added_during_callback_survives_first_completion(self):
        later = []
        def callback():
            # Acceptance must finish while this callback is still running.
            later.append(self.submit(lambda value: value, ("later",)))
            self.assertFalse(later[0][2].is_set())
            return self.sync(lambda: "nested direct")
        first, outcome, done = self.submit(callback)
        self.sync.check()
        self.wait(done)
        self.join(first)
        self.assertEqual(outcome, {"result": "nested direct"})
        thread, outcome, done = later[0]
        self.assertFalse(done.is_set())
        self.sync.check()
        self.wait(done)
        self.join(thread)
        self.assertEqual(outcome, {"result": "later"})

    def test_empty_check_returns_without_waiting(self):
        done = threading.Event()
        def run():
            ckit.SyncCall().check()
            done.set()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.join(thread)
        self.assertTrue(done.is_set())


class JobQueueTests(unittest.TestCase):
    def setUp(self):
        self.queues = []
        self.controllers = []
        for name, value in (("_job_queue_list", []), ("_job_queue", None)):
            replacement = patch.object(ckit_threadutil, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        detector = patch.object(ckit_threadutil.ckitcore, "setBlockDetector")
        detector.start()
        self.addCleanup(detector.stop)
        messages = patch.dict(ckit_threadutil.ckit_resource.strings,
                              job_suspended="suspended", job_resumed="resumed")
        messages.start()
        self.addCleanup(messages.stop)
        self.addCleanup(self.close_queues)

    def make_queue(self, *items):
        with patch.object(ckit.JobQueue, "start"):
            queue = ckit.JobQueue()
        queue.daemon = True
        self.queues.append(queue)
        queue.start()
        for item in items:
            queue.enqueue(item)
        return queue

    def close_queues(self):
        # Bypass the public join under test so even a deadlock regression is reclaimed.
        for queue in self.queues:
            queue.cancel()
            queue.restart()
            queue.cancel_requested = True
            queue.sema.release()
        for queue in self.queues:
            threading.Thread.join(queue, timeout=3)
            queue.destroy()
        for thread, _, _ in self.controllers:
            thread.join(3)
        self.assertFalse(any(queue.is_alive() for queue in self.queues), "JobQueue worker leaked")
        self.assertFalse(any(thread.is_alive() for thread, _, _ in self.controllers), "Controller leaked")

    def start(self, func):
        done = threading.Event()
        errors = []
        def run():
            try:
                func()
            except BaseException as error:  # noqa: BLE001  # Surface controller failures on the test thread.
                errors.append(error)
            finally:
                done.set()
        thread = threading.Thread(target=run, daemon=True)
        self.controllers.append((thread, done, errors))
        thread.start()
        return thread, done, errors

    def complete(self, controller):
        thread, done, errors = controller
        self.assertTrue(done.wait(3), "JobQueue operation did not finish")
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "JobQueue did not reach the expected state")
            time.sleep(0.01)

    def test_pause_with_waiting_items_and_restart_preserves_order(self):
        calls = []
        items = [ckit.JobItem(lambda item, i=i: calls.append((i, threading.get_ident()))) for i in range(3)]
        queue = self.make_queue(*items)
        self.complete(self.start(queue.pause))
        queue.check()
        self.assertEqual(calls, [])
        queue.restart()
        self.complete(self.start(queue.join))
        self.assertEqual(calls, [(i, queue.ident) for i in range(3)])

    def test_pause_with_finished_item_does_not_require_completion_dispatch(self):
        item = ckit.JobItem()
        queue = self.make_queue(item)
        queue.check()
        self.wait_for(lambda: item.status == ckit_threadutil.JOB_STATUS_FINISHED)
        self.complete(self.start(queue.pause))
        self.assertEqual(queue.numItems(), 1)
        self.complete(self.start(queue.join))

    def test_join_drains_paused_queue_without_canceling(self):
        calls = []
        queue = self.make_queue()
        queue.pause()
        item = ckit.JobItem(lambda item: calls.append(item.isCanceled()))
        queue.enqueue(item)
        self.complete(self.start(queue.join))
        self.assertEqual(calls, [False])
        self.assertFalse(queue.is_alive())

    def test_pause_cancel_join_skips_unstarted_items_and_notifies_caller(self):
        calls = []
        finished = []
        queue = self.make_queue()
        queue.pause()
        items = [ckit.JobItem(lambda item: calls.append(item),
                             lambda item: finished.append((item, threading.get_ident()))) for _ in range(3)]
        for item in items:
            queue.enqueue(item)
        queue.check()  # Dispatch to the worker's queue-pause gate, before the callback starts.
        self.wait_for(lambda: queue.pause_waiting)
        queue.cancel()
        controller = self.start(queue.join)
        self.complete(controller)
        self.assertEqual(calls, [])
        self.assertEqual(finished, [(item, controller[0].ident) for item in items])
        self.assertTrue(all(item.isCanceled() for item in items))

    def test_canceled_dispatch_finishes_while_queue_remains_paused(self):
        calls = []
        queue = self.make_queue()
        queue.pause()
        item = ckit.JobItem(lambda item: calls.append(item))
        queue.enqueue(item)
        queue.check()
        self.wait_for(lambda: queue.pause_waiting)
        item.cancel()
        self.wait_for(lambda: item.status == ckit_threadutil.JOB_STATUS_FINISHED)
        self.assertTrue(queue.pause_requested)
        self.assertEqual(calls, [])
        self.complete(self.start(queue.join))

    def test_canceled_dispatch_is_not_executed_after_restart(self):
        calls = []
        queue = self.make_queue()
        queue.pause()
        item = ckit.JobItem(lambda item: calls.append(item))
        queue.enqueue(item)
        queue.check()
        self.wait_for(lambda: queue.pause_waiting)
        queue.cancel()
        queue.restart()
        self.complete(self.start(queue.join))
        self.assertEqual(calls, [])

    def test_pause_waits_for_running_job_to_finish_without_waitPaused(self):
        entered, release = threading.Event(), threading.Event()
        def work(item):
            entered.set()
            release.wait(3)
        item = ckit.JobItem(work)
        queue = self.make_queue(item, ckit.JobItem())
        self.addCleanup(release.set)
        queue.check()
        self.assertTrue(entered.wait(3))
        controller = self.start(queue.pause)
        try:
            self.wait_for(item.isPaused)
            self.assertFalse(controller[1].is_set())
            release.set()
            self.complete(controller)
            self.assertEqual(item.status, ckit_threadutil.JOB_STATUS_FINISHED)
            self.complete(self.start(queue.join))
        finally:
            release.set()

    def test_cooperative_pause_restart_and_cancel_join(self):
        for action in ("restart", "join", "cancel"):
            with self.subTest(action=action):
                entered, proceed = threading.Event(), threading.Event()
                results = []
                def work(item, entered=entered, proceed=proceed, results=results):
                    entered.set()
                    if proceed.wait(3):
                        results.append((item.waitPaused(), item.isCanceled()))
                item = ckit.JobItem(work)
                queue = self.make_queue(item)
                self.addCleanup(proceed.set)
                queue.check()
                self.assertTrue(entered.wait(3))
                controller = self.start(queue.pause)
                try:
                    self.wait_for(item.isPaused)
                    proceed.set()
                    self.complete(controller)
                    self.assertTrue(item.pause_waiting)
                    if action == "cancel":
                        queue.cancel()
                    elif action == "restart":
                        queue.restart()
                    self.complete(self.start(queue.join))
                    self.assertEqual(results, [(True, action == "cancel")])
                finally:
                    proceed.set()

    def test_join_waits_for_normal_running_job_and_notifies_in_order(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def work(item):
            entered.set()
            release.wait(3)
            calls.append(("work", threading.get_ident(), item.isCanceled()))
        first = ckit.JobItem(work, lambda item: calls.append(("first", threading.get_ident())))
        second = ckit.JobItem(lambda item: calls.append(("next", threading.get_ident())),
                              lambda item: calls.append(("second", threading.get_ident())))
        queue = self.make_queue(first, second)
        self.addCleanup(release.set)
        queue.check()
        self.assertTrue(entered.wait(3))
        controller = self.start(queue.join)
        try:
            self.assertFalse(controller[1].wait(0.1))
            release.set()
            self.complete(controller)
            self.assertEqual(calls, [("work", queue.ident, False), ("first", controller[0].ident),
                                     ("next", queue.ident), ("second", controller[0].ident)])
        finally:
            release.set()

    def test_cancel_running_job_is_cooperative_and_skips_pending(self):
        entered, observed, release = threading.Event(), threading.Event(), threading.Event()
        calls = []
        def work(item):
            entered.set()
            while not item.isCanceled():
                if release.wait(0.01):
                    return
            observed.set()
            release.wait(3)
        queue = self.make_queue(ckit.JobItem(work), ckit.JobItem(lambda item: calls.append("pending")))
        self.addCleanup(release.set)
        queue.check()
        self.assertTrue(entered.wait(3))
        queue.cancel()
        controller = self.start(queue.join)
        try:
            self.assertTrue(observed.wait(3))
            self.assertFalse(controller[1].is_set())
            release.set()
            self.complete(controller)
            self.assertEqual(calls, [])
        finally:
            release.set()

    def test_check_notifies_on_caller_and_continues_after_callback_errors(self):
        owner = threading.get_ident()
        calls = []
        def fail(item):
            raise ValueError("job callback failure")
        first = ckit.JobItem(fail, fail)
        first.finished_func_list.append(lambda item: calls.append(("first", threading.get_ident())))
        second = ckit.JobItem(lambda item: calls.append(("work", threading.get_ident())),
                             lambda item: calls.append(("second", threading.get_ident())))
        queue = self.make_queue(first, second)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            queue.check()
            self.wait_for(lambda: first.status == ckit_threadutil.JOB_STATUS_FINISHED)
            queue.check()
            self.wait_for(lambda: second.status == ckit_threadutil.JOB_STATUS_FINISHED)
            queue.check()
        self.assertEqual(calls, [("first", owner), ("work", queue.ident), ("second", owner)])
        self.assertEqual(output.getvalue().count("ValueError: job callback failure"), 2)
        self.assertEqual(queue.numItems(), 0)
        self.complete(self.start(queue.join))

    def test_cancel_all_join_all_delivers_canceled_completion_without_work(self):
        calls = []
        finished = []
        for _ in range(2):
            queue = self.make_queue()
            queue.pause()
            queue.enqueue(ckit.JobItem(lambda item: calls.append(item),
                                      lambda item: finished.append((item.isCanceled(), threading.get_ident()))))
        ckit.JobQueue.cancelAll()
        controller = self.start(ckit.JobQueue.joinAll)
        self.complete(controller)
        self.assertEqual(calls, [])
        self.assertEqual(finished, [(True, controller[0].ident)] * 2)


class CronTests(unittest.TestCase):
    def setUp(self):
        for target, name, value in (
            (ckit_threadutil, "_cron_thread_list", []),
            (ckit_threadutil, "_cron_thread", None),
        ):
            replacement = patch.object(target, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        detector = patch.object(ckit_threadutil.ckitcore, "setBlockDetector")
        detector.start()
        self.addCleanup(detector.stop)

    def make_table(self, *items):
        with patch.object(ckit.CronTable, "start"):
            table = ckit.CronTable()
        # A regression must fail the test instead of leaving the test process stuck.
        table.daemon = True
        self.addCleanup(self.close_table, table)
        for item in items:
            table.add(item)
        return table

    def close_table(self, table):
        table.cancel_requested = True
        if table.ident is not None:
            threading.Thread.join(table, timeout=3)
            self.assertFalse(table.is_alive(), "Cron thread did not stop")
        table.destroy()

    @staticmethod
    def due(func):
        item = ckit.CronItem(func, 0)
        item.last = 0
        return item

    def wait(self, event):
        self.assertTrue(event.wait(3), "Cron callback did not reach the expected step")

    def test_item_cancel_is_terminal_and_does_not_unregister(self):
        calls = []
        reached = threading.Event()
        canceled = self.due(lambda item: calls.append("canceled"))
        canceled.cancel()
        canceled.cancel()
        table = self.make_table(canceled)
        table.remove(canceled)
        table.add(canceled)
        table.add(self.due(lambda item: reached.set()))
        table.start()
        self.wait(reached)
        table.join()
        self.assertTrue(canceled.isCanceled())
        self.assertEqual(table.numItems(), 2)
        self.assertEqual(calls, [])

    def test_table_cancel_returns_during_callback_and_accepts_new_items(self):
        entered = threading.Event()
        release = threading.Event()
        canceled = threading.Event()
        new_ran = threading.Event()
        calls = []

        def running(item):
            entered.set()
            release.wait(3)
            calls.append(item.isCanceled())

        first = self.due(running)
        pending = self.due(lambda item: calls.append("pending"))
        table = self.make_table(first, pending)
        self.addCleanup(release.set)
        table.start()
        self.wait(entered)

        def cancel():
            table.cancel()
            canceled.set()

        controller = threading.Thread(target=cancel, daemon=True)
        controller.start()
        try:
            self.wait(canceled)
            self.assertTrue(table.is_alive())
            self.assertTrue(first.isCanceled())
            self.assertTrue(pending.isCanceled())
            table.add(self.due(lambda item: new_ran.set()))
            release.set()
            self.wait(new_ran)
            table.join()
            self.assertEqual(calls, [True])
        finally:
            release.set()
            controller.join(3)

    def test_join_requests_cooperative_exit_and_waits_for_running_callback(self):
        entered = threading.Event()
        observed_cancel = threading.Event()
        release = threading.Event()
        joined = threading.Event()
        calls = []

        def running(item):
            entered.set()
            while not item.isCanceled():
                if release.wait(0.01):
                    return
            observed_cancel.set()
            release.wait(3)

        table = self.make_table(self.due(running), self.due(lambda item: calls.append("pending")))
        self.addCleanup(release.set)
        table.start()
        self.wait(entered)

        def join():
            table.join()
            joined.set()

        controller = threading.Thread(target=join, daemon=True)
        controller.start()
        try:
            self.wait(observed_cancel)
            self.assertFalse(joined.is_set())
            with self.assertRaises(RuntimeError):
                table.add(self.due(lambda item: None))
            release.set()
            self.wait(joined)
            self.assertFalse(table.is_alive())
            self.assertEqual(calls, [])
            table.join()
        finally:
            release.set()
            controller.join(3)

    def test_callback_can_cancel_all_pending_items_without_deadlock(self):
        reached = threading.Event()
        calls = []

        def cancel(item):
            table.cancel()
            reached.set()

        table = self.make_table(self.due(cancel), self.due(lambda item: calls.append("pending")))
        table.start()
        self.wait(reached)
        table.join()
        self.assertEqual(calls, [])

    def test_remove_from_callback_skips_pending_snapshot_without_canceling_item(self):
        reached = threading.Event()
        calls = []
        pending = self.due(lambda item: calls.append("pending"))

        def remove(item):
            table.remove(pending)
            item.cancel()

        table = self.make_table(self.due(remove), pending, self.due(lambda item: reached.set()))
        table.start()
        self.wait(reached)
        table.join()
        self.assertEqual(calls, [])
        self.assertFalse(pending.isCanceled())
        self.assertEqual(table.numItems(), 2)

    def test_clear_from_callback_skips_pending_snapshot_without_canceling_items(self):
        reached = threading.Event()
        calls = []

        def clear(item):
            table.clear()
            reached.set()

        first = self.due(clear)
        pending = self.due(lambda item: calls.append("pending"))
        table = self.make_table(first, pending)
        table.start()
        self.wait(reached)
        table.join()
        self.assertEqual(calls, [])
        self.assertEqual(table.numItems(), 0)
        self.assertFalse(first.isCanceled())
        self.assertFalse(pending.isCanceled())

    def test_callback_can_add_a_new_item(self):
        reached = threading.Event()
        calls = []

        def add(item):
            calls.append("add")
            item.cancel()
            table.add(self.due(lambda new_item: reached.set()))

        table = self.make_table(self.due(add))
        table.start()
        self.wait(reached)
        table.join()
        self.assertEqual(calls, ["add"])

    def test_exception_is_reported_and_later_items_still_run(self):
        reached = threading.Event()

        def fail(item):
            item.cancel()
            raise ValueError("Cron callback failure")

        table = self.make_table(self.due(fail), self.due(lambda item: reached.set()))
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            table.start()
            self.wait(reached)
            table.join()
        self.assertIn("ValueError: Cron callback failure", output.getvalue())

    def test_cancel_all_and_join_all_operate_on_every_registered_table(self):
        items = [ckit.CronItem(lambda item: None, 3600) for _ in range(2)]
        tables = [self.make_table(item) for item in items]
        for table in tables:
            table.start()
        ckit.CronTable.cancelAll()
        self.assertTrue(all(item.isCanceled() for item in items))
        self.assertTrue(all(table.is_alive() for table in tables))
        ckit.CronTable.joinAll()
        self.assertTrue(all(not table.is_alive() for table in tables))

    def test_join_all_signals_every_table_before_waiting_for_the_first(self):
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        joined = threading.Event()
        observed = []

        def first(item):
            entered[0].set()
            while not second_item.isCanceled():
                if release.wait(0.01):
                    return
            observed.append(item.isCanceled())

        def second(item):
            entered[1].set()
            while not item.isCanceled():
                if release.wait(0.01):
                    return

        second_item = self.due(second)
        tables = [self.make_table(self.due(first)), self.make_table(second_item)]
        self.addCleanup(release.set)
        for table in tables:
            table.start()
        for event in entered:
            self.wait(event)

        def join():
            ckit.CronTable.joinAll()
            joined.set()

        controller = threading.Thread(target=join, daemon=True)
        controller.start()
        try:
            self.wait(joined)
            self.assertEqual(observed, [True])
        finally:
            release.set()
            controller.join(3)


if __name__ == "__main__":
    unittest.main()
